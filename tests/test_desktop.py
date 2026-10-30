"""Desktop settings persistence and bounded record queries."""
from __future__ import annotations

import json

import pytest

from scout.config import load_config
from scout.desktop.runtime import prepare_runtime
from scout.desktop.service import DesktopService
from scout.store.desktop import DesktopStore


def test_settings_store_model_and_effort(tmp_path, monkeypatch):
    from scout.paths import Paths
    from scout.desktop.service import DesktopService
    root = tmp_path
    (root / "config").mkdir(parents=True, exist_ok=True)
    paths = Paths.build(root=root).ensure()
    service = DesktopService(paths)
    service.save_settings("sk-local-test-abcdefghijkl", "deepseek-v4-pro", "low")
    data = service.settings()
    assert data["model"] == "deepseek-v4-pro"
    assert data["reasoning_effort"] == "low"
    assert "agent_engine" not in data
    service.save_settings("", "deepseek-flash", "low")
    assert load_config(paths).llm.api_key == "sk-local-test-abcdefghijkl"
    service.save_settings("", "deepseek-flash", "high")
    assert service.settings()["model"] == "deepseek-flash"


def test_configuration_survives_restart_and_bundle_change(tmp_path, monkeypatch):
    import sys
    from pathlib import Path
    defaults = Path(__file__).resolve().parents[1] / "config" / "default.yaml"
    for name in ("bundle-one", "bundle-two"):
        bundle = tmp_path / name
        (bundle / "config").mkdir(parents=True)
        (bundle / "config" / "default.yaml").write_bytes(defaults.read_bytes())
    for key in ("SCOUT_ROOT", "SCOUT_DATA_DIR", "SCOUT_CONFIG_DIR", "SCOUT_ACCOUNT"):
        # Record even absent variables so prepare_runtime's writes are restored.
        monkeypatch.setenv(key, "main" if key == "SCOUT_ACCOUNT" else "")
    monkeypatch.setattr(sys, "_MEIPASS", tmp_path / "bundle-one", raising=False)
    paths = prepare_runtime(tmp_path / "userdata")
    service = DesktopService(paths)
    service.initialize()
    result = service.save_settings("sk-local-test-abcdefghijkl", "test-model")
    assert "sk-local-test-abcdefghijkl" not in json.dumps(result)
    monkeypatch.setattr(sys, "_MEIPASS", tmp_path / "bundle-two")
    restarted = prepare_runtime(tmp_path / "userdata")
    assert restarted.db_path == paths.db_path
    assert load_config(restarted).llm.api_key == "sk-local-test-abcdefghijkl"
    assert load_config(restarted).llm.model == "test-model"
    DesktopService(restarted).save_settings("", "changed-model")
    assert load_config(restarted).llm.api_key == "sk-local-test-abcdefghijkl"
    assert not (tmp_path / "bundle-one" / "config" / "llm.local.yaml").exists()
    assert not (tmp_path / "bundle-two" / "config" / "llm.local.yaml").exists()


def test_desktop_queries_page_and_search_literal_text(ctx):
    for index in range(105):
        ctx.works.upsert({"aweme_id": f"mine-{index}", "description": f"作品 {index}", "is_mine": 1})
    ctx.works.upsert({"aweme_id": "other", "description": "别人的作品"})
    ctx.works.upsert({"aweme_id": "literal", "description": "100%_真实", "is_mine": 1})
    store = DesktopStore(ctx.db)
    first = store.page("works")
    second = store.page("works", page=1)
    assert first["total"] == 106
    assert len(first["rows"]) == 100 and len(second["rows"]) == 6
    assert not ({r["aweme_id"] for r in first["rows"]} & {r["aweme_id"] for r in second["rows"]})
    assert store.page("works", "%_")["total"] == 1
    assert store.page("works", "' OR 1=1 --")["total"] == 0
    assert store.overview()["works"] == 106
    with pytest.raises(KeyError):
        store.page("untrusted-table")


def test_records_scope_links_likes_to_their_work(ctx):
    """互动数据按作品归口：人是互动作品列表，作品是已采点赞人列表。"""
    ctx.works.upsert({"aweme_id": "w1", "description": "校园视频", "is_mine": 1, "digg_count": 30})
    ctx.works.upsert({"aweme_id": "w2", "description": "食堂视频", "is_mine": 1, "digg_count": 5})
    ctx.users.upsert({"sec_uid": "u1", "nickname": "观众甲"})
    ctx.like_edges.add_many([
        {"sec_uid": "u1", "aweme_id": "w1", "notice_id": "n1"},
        {"sec_uid": "u1", "aweme_id": "w1", "notice_id": "api:w1"},  # 同一人同一作品：通知 + 接口
        {"sec_uid": "u1", "aweme_id": "w2", "notice_id": "n2"},
    ])
    store = DesktopStore(ctx.db)
    user = next(r for r in store.page("users")["rows"] if r["sec_uid"] == "u1")
    assert user["links"]["total"] == 2
    assert {i["id"] for i in user["links"]["items"]} == {"w1", "w2"}
    assert {i["label"] for i in user["links"]["items"]} == {"校园视频", "食堂视频"}
    work = next(r for r in store.page("works")["rows"] if r["aweme_id"] == "w1")
    assert work["links"]["total"] == 1                 # 两条边只算一个人
    assert work["links"]["items"][0]["label"] == "观众甲"

def test_latest_analysis_is_unique_when_timestamps_tie(ctx):
    for digest in ("first", "second"):
        ctx.llm_results.save(subject_kind="user", subject_id="a", task="profile",
            prompt_version="v1", model="test", input_digest=digest, input_summary="test",
            output_json="{}", raw_text="{}")
    ctx.db.execute("UPDATE llm_results SET created_at='2026-10-11T00:00:00Z'")
    data = DesktopStore(ctx.db).page("analyses")
    assert data["total"] == 1
    assert data["rows"][0]["input_digest"] == "second"


def test_invalid_user_configuration_is_not_overwritten(paths):
    target = paths.config_dir / "llm.local.yaml"
    target.write_text("- broken\n", encoding="utf-8")
    with pytest.raises(ValueError):
        DesktopService(paths).save_settings("new", "model")
    assert target.read_text(encoding="utf-8") == "- broken\n"
