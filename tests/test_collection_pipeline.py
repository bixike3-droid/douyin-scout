"""Collection efficiency, completeness and reversible cleaning rules."""
import asyncio
import json
from urllib.parse import urlparse, parse_qs
from dataclasses import replace

from scout.collect.user_works_api import UserWorksApiCollector
from scout.collect.likers import LikersCollector
from scout.collect.pipeline import Pipeline
from scout.store.collection import Coverage, Quality, clean_metrics
from scout.util import iso


def work(index, owner):
    return {"aweme_id": str(100000 + index), "desc": f"作品 {index}", "create_time": 1700000000 + index,
            "author": {"sec_uid": owner}, "statistics": {"digg_count": 2}}


def install_browser(ctx, monkeypatch, responder):
    calls = []
    class Page:
        url = "https://www.douyin.com/"
    class Session:
        async def ensure(self, tier):
            pass
        async def page(self, tier):
            return Page()
    async def session(*args, **kwargs):
        return Session()
    async def wait(*args):
        return 0
    async def fetch(self, page, url):
        calls.append(url)
        await asyncio.sleep(0.002)
        payload, status = responder(parse_qs(urlparse(url).query), url)
        return json.dumps(payload).encode(), status, ""
    monkeypatch.setattr(ctx, "open_session", session)
    monkeypatch.setattr(ctx.throttle, "wait", wait)
    monkeypatch.setattr("scout.collect.api_base.ApiCollector.fetch_in_page", fetch)
    ctx.quota.set_limit("a", 0)
    ctx.cursors.set("self_sec_uid", "owner")
    ctx.users.upsert({"sec_uid": "owner", "nickname": "创作者"})
    ctx.users.upsert({"sec_uid": "guest", "nickname": "观众", "follower_count": 0})
    return calls


def posts(total):
    def responder(query, url):
        offset = int(query["max_cursor"][0])
        size = int(query["count"][0])
        end = min(total, offset + size)
        return {"status_code": 0, "aweme_list": [work(i, query["sec_user_id"][0]) for i in range(offset,end)],
                "has_more": end < total, "max_cursor": end}, 200
    return responder


def test_sampling_and_deeper_resume_reduce_requests_without_duplicates(ctx, monkeypatch):
    calls = install_browser(ctx, monkeypatch, posts(75))
    first = asyncio.run(UserWorksApiCollector(ctx).run({"target": "guest", "tier": "a", "_item_limit": 12, "_resume": True}))
    assert first.ok and first.persisted["collection_state"] == "sampled"
    assert not first.persisted["exhausted"] and len(calls) == 1
    assert Coverage(ctx.db).fresh("fetch_user_works", "guest", required=12)
    assert not Coverage(ctx.db).fresh("fetch_user_works", "guest", required=60)
    second = asyncio.run(UserWorksApiCollector(ctx).run({"target": "guest", "tier": "a", "_item_limit": 60, "_resume": True}))
    assert second.ok and second.persisted["items"] == 60
    assert len(calls) == 4
    assert ctx.db.scalar("SELECT COUNT(*) FROM user_work_listings WHERE sec_uid='guest'") == 60
    assert ctx.db.scalar("SELECT MIN(duration_ms) FROM request_logs") > 0


def test_configured_work_limit_is_enforced(ctx, monkeypatch):
    calls = install_browser(ctx, monkeypatch, posts(100))
    ctx.config = replace(ctx.config, targets=replace(ctx.config.targets, works_per_user_limit=12))
    result = asyncio.run(UserWorksApiCollector(ctx).run({"target": "guest", "tier": "a"}))
    assert result.persisted["items"] == 12 and len(calls) == 1


def test_midway_failure_retains_data_but_is_not_completed(ctx, monkeypatch):
    normal = posts(75)
    def responder(query, url):
        return ({"status_code": 500}, 500) if int(query["max_cursor"][0]) else normal(query,url)
    install_browser(ctx, monkeypatch, responder)
    result = asyncio.run(UserWorksApiCollector(ctx).run({"target": "guest", "tier": "a", "_item_limit": 0}))
    assert not result.ok and result.persisted["collection_state"] == "partial"
    assert ctx.db.scalar("SELECT COUNT(*) FROM user_work_listings WHERE sec_uid='guest'") == 18
    assert Coverage(ctx.db).get("fetch_user_works", "guest")["next_cursor"] == 18


def test_repeated_cursor_is_not_mistaken_for_exhaustion(ctx, monkeypatch):
    def responder(query, url):
        return {"status_code": 0, "aweme_list": [work(1,"guest")], "has_more": True, "max_cursor": 0}, 200
    calls = install_browser(ctx, monkeypatch, responder)
    result = asyncio.run(UserWorksApiCollector(ctx).run({"target": "guest", "tier": "a"}))
    assert not result.ok and not result.persisted["exhausted"] and len(calls) == 1


def test_quota_is_checked_and_charged_per_page(ctx, monkeypatch):
    calls = install_browser(ctx, monkeypatch, posts(75))
    ctx.quota.set_limit("a", 1)
    result = asyncio.run(UserWorksApiCollector(ctx).run({"target": "guest", "tier": "a", "_item_limit": 0}))
    assert result.blocked and len(calls) == 1 and ctx.quota.used("a") == 1
    assert result.persisted["collection_state"] == "partial"


def test_schema_change_is_not_cached_as_empty(ctx, monkeypatch):
    install_browser(ctx, monkeypatch, lambda query,url: ({"status_code":0,"has_more":False,"data":[]},200))
    result = asyncio.run(UserWorksApiCollector(ctx).run({"target":"guest","tier":"a"}))
    assert not result.ok and not Coverage(ctx.db).fresh("fetch_user_works","guest",required=12)


def test_only_complete_liker_scan_marks_absent_edges(ctx, monkeypatch):
    ctx.works.upsert({"aweme_id":"100001","author_sec_uid":"owner","is_mine":1})
    ctx.users.upsert({"sec_uid":"absent","nickname":"旧观众"})
    ctx.like_edges.add_many([{"sec_uid":"absent","aweme_id":"100001"}])
    def responder(query,url):
        return {"status_code":0,"user_list":[{"sec_uid":"guest","nickname":"观众","follower_count":0}],
                "has_more":True,"max_cursor":0},200
    install_browser(ctx,monkeypatch,responder)
    partial=asyncio.run(LikersCollector(ctx).run({"target":"100001","tier":"a"}))
    assert not partial.ok
    assert ctx.db.scalar("SELECT is_stale FROM like_edges WHERE sec_uid='absent'") == 0
    install_browser(ctx,monkeypatch,lambda q,u: ({"status_code":0,"user_list":[],"has_more":False,"max_cursor":0},200))
    complete=asyncio.run(LikersCollector(ctx).run({"target":"100001","tier":"a"}))
    assert complete.ok
    assert ctx.db.scalar("SELECT is_stale FROM like_edges WHERE sec_uid='absent'") == 1
    assert ctx.db.scalar("SELECT COUNT(*) FROM like_edges WHERE sec_uid='absent'") == 1


def test_quick_pipeline_skips_notification_and_reuses_fresh_data(ctx, monkeypatch):
    def responder(query,url):
        if "sec_user_id" in query:
            return posts(2)(query,url)
        return {"status_code":0,"user_list":[{"sec_uid":"guest","nickname":"观众","follower_count":0}],
                "has_more":False,"max_cursor":0},200
    calls=install_browser(ctx,monkeypatch,responder)
    first=asyncio.run(Pipeline(ctx,lambda event:None).run(mode="quick"))
    assert first["ok"] == 3 and first["quality"]["repeated_users"] == 1
    assert not any("notice" in url for url in calls)
    assert not any("sec_user_id=guest" in url for url in calls)
    before=len(calls)
    second=asyncio.run(Pipeline(ctx,lambda event:None).run(mode="quick"))
    assert second["cached"] == 3 and len(calls) == before


def test_quality_dedup_keeps_quiet_viewer_and_raw_evidence(ctx):
    ctx.cursors.set("self_sec_uid","owner")
    ctx.users.upsert({"sec_uid":"quiet","nickname":"安静的观众","follower_count":0,"aweme_count":0})
    ctx.works.upsert({"aweme_id":"1","author_sec_uid":"owner","is_mine":1})
    ctx.works.upsert({"aweme_id":"2","author_sec_uid":"other"})
    ctx.like_edges.add_many([{"sec_uid":"quiet","aweme_id":"1","notice_id":"n1"},
        {"sec_uid":"quiet","aweme_id":"1","notice_id":"n2"}, {"sec_uid":"quiet","aweme_id":"2"}])
    report=Quality(ctx.db).report()
    assert report["raw_edges"] == 3 and report["valid_edges"] == 1
    assert report["active_users"] == 1 and report["without_samples"] == 1
    assert report["duplicate_edges"] == 1 and report["invalid_edges"] == 1
    assert Quality(ctx.db).audience()[0]["data_status"] == "基础资料可用"
    assert ctx.like_edges.stats()["total"] == 3


def test_metric_cleaning_preserves_zero_and_original_record():
    raw={"follower_count":0,"digg_count":-5,"nickname":"  观众  "}
    cleaned=clean_metrics(raw)
    assert cleaned["follower_count"] == 0 and cleaned["digg_count"] is None
    assert cleaned["nickname"] == "观众" and raw["digg_count"] == -5


def test_analysis_candidates_are_filtered_before_limit(ctx):
    from scout.analyze.ai import pending_targets, build_user_input, PROMPT_VERSION
    ctx.cursors.set("self_sec_uid","owner")
    ctx.works.upsert({"aweme_id":"1","author_sec_uid":"owner","is_mine":1,"description":"校园生活"})
    for uid in ("a","b","c"):
        ctx.users.upsert({"sec_uid":uid,"nickname":uid,"follower_count":0})
        ctx.like_edges.add_many([{"sec_uid":uid,"aweme_id":"1"}])
    digest=build_user_input(ctx,"a")[1]
    ctx.llm_results.save(subject_kind="user",subject_id="a",task="profile",prompt_version=PROMPT_VERSION,
        model="test",input_digest=digest,input_summary="a",output_json="{}",raw_text="{}")
    assert pending_targets(ctx,limit=2) == ["b","c"]


def test_no_content_evidence_cannot_produce_high_relevance(ctx):
    from scout.analyze.ai import analyze_user, build_user_input
    from scout.llm.client import LLMReply
    ctx.cursors.set("self_sec_uid","owner")
    ctx.works.upsert({"aweme_id":"1","author_sec_uid":"owner","is_mine":1,"description":"校园生活"})
    ctx.users.upsert({"sec_uid":"quiet","nickname":"安静的观众","follower_count":0})
    ctx.like_edges.add_many([{"sec_uid":"quiet","aweme_id":"1"}])
    class Client:
        async def chat(self,*args,**kwargs):
            return LLMReply(text=json.dumps({"content_domains":[],"persona":"资料不足","relevance_score":5}),model="test")
    result=asyncio.run(analyze_user(ctx,Client(),"quiet"))
    assert result.ok and result.data["relevance_score"] is None and result.data["confidence"] == "低"
    assert "校园生活" in build_user_input(ctx,"quiet")[0]


def test_model_change_invalidates_profile_digest(ctx):
    from scout.analyze.ai import build_user_input
    first=build_user_input(ctx,"quiet")[1]
    ctx.config=replace(ctx.config,llm=replace(ctx.config.llm,model="different-model"))
    assert build_user_input(ctx,"quiet")[1] != first


def test_empty_likers_with_positive_statistic_do_not_erase_audience(ctx,monkeypatch):
    install_browser(ctx,monkeypatch,lambda q,u: ({"status_code":0,"user_list":[],"has_more":False},200))
    ctx.works.upsert({"aweme_id":"1","author_sec_uid":"owner","is_mine":1,"digg_count":50})
    ctx.like_edges.add_many([{"sec_uid":"guest","aweme_id":"1"}])
    result=asyncio.run(LikersCollector(ctx).run({"target":"1","tier":"a"}))
    assert not result.ok
    assert ctx.db.scalar("SELECT is_stale FROM like_edges WHERE sec_uid='guest'") == 0


def test_selected_enrichment_does_not_recrawl_other_lists(ctx,monkeypatch):
    calls=install_browser(ctx,monkeypatch,posts(75))
    ctx.works.upsert({"aweme_id":"1","author_sec_uid":"owner","is_mine":1})
    ctx.like_edges.add_many([{"sec_uid":"guest","aweme_id":"1"}])
    result=asyncio.run(Pipeline(ctx,lambda event:None).run(mode="deep",targets=["guest"],works_limit=12,limit=1))
    assert result["sampled"] == 1 and len(calls) == 1
    assert "sec_user_id=guest" in calls[0]


def test_missing_pagination_flag_is_not_full(ctx,monkeypatch):
    install_browser(ctx,monkeypatch,lambda q,u: ({"status_code":0,"aweme_list":[work(1,"guest")]},200))
    result=asyncio.run(UserWorksApiCollector(ctx).run({"target":"guest","tier":"a"}))
    assert not result.ok and not result.persisted["exhausted"]


def test_page_limited_owner_scan_can_resume_without_duplicate_work(ctx,monkeypatch):
    calls=install_browser(ctx,monkeypatch,posts(42))
    ctx.config=replace(ctx.config,targets=replace(ctx.config.targets,works_max_pages=1))
    states=[]
    for _ in range(3):
        result=asyncio.run(UserWorksApiCollector(ctx).run({"target":"owner","tier":"a","_resume":True}))
        states.append(result.persisted["collection_state"])
    assert states == ["partial","partial","full"] and len(calls) == 3
    assert ctx.db.scalar("SELECT COUNT(*) FROM works WHERE is_mine=1") == 42


def test_refused_owner_api_uses_known_works_without_repeating_denied_call(ctx,monkeypatch):
    from scout.collect import user_works_api
    monkeypatch.setattr(user_works_api, "CAPTURE_TIMEOUT_S", 0.05)
    monkeypatch.setattr(user_works_api, "CAPTURE_NEXT_TIMEOUT_S", 0.05)

    def responder(query,url):
        if "sec_user_id" in query:
            return {},403
        return {"status_code":0,"user_list":[{"sec_uid":"guest","nickname":"观众","follower_count":0}],"has_more":False},200
    calls=install_browser(ctx,monkeypatch,responder)
    ctx.works.upsert({"aweme_id":"1","author_sec_uid":"owner","is_mine":1,"digg_count":1})
    result=asyncio.run(Pipeline(ctx,lambda event:None).run(mode="quick"))
    assert len(calls) == 2 and result["ok"] == 1 and result["failed"] == 1
    assert result["warnings"] and result["quality"]["active_users"] == 1


def test_refused_likers_api_stops_remaining_requests(ctx,monkeypatch):
    def responder(query,url):
        return posts(3)(query,url) if "sec_user_id" in query else ({},403)
    calls=install_browser(ctx,monkeypatch,responder)
    result=asyncio.run(Pipeline(ctx,lambda event:None).run(mode="quick"))
    assert len(calls) == 2 and "HTTP 403" in result["stop_reason"]
