"""对标账号：链接解析、登记存储、更新检查（采集前后差集检测）。"""
import asyncio

from scout.desktop import actions
from scout.store.benchmark import Benchmarks, parse_sec_uid

UID = "MS4wLjABAAAAtest0123456789abcdef"


def test_parse_sec_uid_from_link_and_raw_id():
    assert parse_sec_uid(f"https://www.douyin.com/user/{UID}?from_tab_name=main") == UID
    assert parse_sec_uid(f"  {UID}  ") == UID
    assert parse_sec_uid("https://www.douyin.com/") is None
    assert parse_sec_uid("短") is None
    assert parse_sec_uid("") is None


def test_benchmark_store_add_list_remove(ctx):
    store = Benchmarks(ctx.db)
    uid = "MS4wLjABAAAA0000000000000001"
    assert store.add(uid, nickname="同行甲") is True
    assert store.add(uid) is False  # 重复添加不算新建，昵称保留
    assert store.get(uid)["nickname"] == "同行甲"
    ctx.works.upsert({"aweme_id": "bench-1", "author_sec_uid": uid,
                      "description": "对标作品", "digg_count": 3})
    rows = store.list()
    assert len(rows) == 1 and rows[0]["display_name"] == "同行甲" and rows[0]["works_count"] == 1
    assert store.works(uid)[0]["aweme_id"] == "bench-1"
    store.mark_checked(uid, 2)
    assert store.get(uid)["last_new_count"] == 2 and store.get(uid)["last_checked_at"]
    store.remove(uid)
    assert store.list() == [] and store.works(uid)[0]["aweme_id"] == "bench-1"  # 作品不受影响


def test_benchmark_check_reports_new_works(ctx, monkeypatch):
    uid = "MS4wLjABAAAA0000000000000002"
    Benchmarks(ctx.db).add(uid)
    monkeypatch.setattr(actions, "login_status",
                        lambda paths: {"saved": True, "tier": "a", "message": ""})

    class FakeOutcome:
        ok = True
        blocked = False
        error = ""
        requests = 1
        persisted = {"collection_state": "sampled"}

    class FakeCollector:
        def __init__(self, context):
            self.on_progress = None

        async def run(self, task):
            ctx.works.upsert({"aweme_id": "new-work-1", "author_sec_uid": uid,
                              "description": "刚发布的新作品", "digg_count": 1})
            return FakeOutcome()

    import scout.collect.user_works_api as user_works_api
    monkeypatch.setattr(user_works_api, "UserWorksApiCollector", FakeCollector)

    events = []
    result = asyncio.run(actions.check_benchmarks(ctx, events.append, {"sec_uid": uid}))
    assert "共新增 1 条" in result["message"] and result["report"]["new_works"] == 1
    account = Benchmarks(ctx.db).get(uid)
    assert account["last_new_count"] == 1 and account["last_checked_at"] and not account["last_error"]
    task_row = ctx.db.query_one(
        "SELECT state FROM tasks WHERE kind='fetch_user_works' AND target=?", (uid,))
    assert task_row["state"] == "done"
    assert any("新增 1" in str(event.get("message") or "") for event in events)
