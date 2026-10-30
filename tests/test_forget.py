"""按人删除：只清除目标互动者，其他人的数据原样保留。"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from scout.config import load_config
from scout.paths import Paths
from scout.store.forget import ForgetPerson
from scout.util import iso
from scout.web_desktop.api import create_app
from scout.web_desktop.gateway import Gateway
from scout.web_desktop.server import Server

TARGET = "MS4wLjABAAAAtarget000000000001"
OTHER = "MS4wLjABAAAAother0000000000002"


def seed(ctx):
    ctx.works.upsert({"aweme_id": "mine-1", "description": "我的作品", "is_mine": 1})
    ctx.works.upsert({"aweme_id": "theirs-1", "description": "目标的作品", "author_sec_uid": TARGET, "is_mine": 0})
    ctx.users.upsert({"sec_uid": TARGET, "nickname": "目标", "follower_count": 1200, "profile_state": "ok"})
    ctx.users.upsert({"sec_uid": OTHER, "nickname": "其他人", "follower_count": 80})
    ctx.like_edges.add_many([
        {"sec_uid": TARGET, "aweme_id": "mine-1", "notice_id": "n1"},
        {"sec_uid": OTHER, "aweme_id": "mine-1", "notice_id": "n2"},
        {"sec_uid": OTHER, "aweme_id": "theirs-1", "notice_id": "n3"},
    ])
    ctx.comments.upsert_many([
        {"comment_id": "c1", "aweme_id": "mine-1", "sec_uid": TARGET, "text": "目标评论"},
        {"comment_id": "c2", "aweme_id": "mine-1", "sec_uid": OTHER, "text": "别人评论"},
        {"comment_id": "c3", "aweme_id": "theirs-1", "sec_uid": OTHER, "text": "目标作品下的评论"},
    ])
    ctx.snapshots.record(TARGET, {"follower_count": 1200}, day="2026-10-30")
    ctx.snapshots.record(OTHER, {"follower_count": 80}, day="2026-10-30")
    ctx.works.link_listings(TARGET, ["theirs-1"])
    ctx.works.link_listings(OTHER, ["mine-1"])
    ctx.llm_results.save(subject_kind="user", subject_id=TARGET, task="profile",
                         prompt_version="v1", model="test", input_digest="a", input_summary="x",
                         output_json="{}", raw_text="{}")
    ctx.llm_results.save(subject_kind="user", subject_id=OTHER, task="profile",
                         prompt_version="v1", model="test", input_digest="b", input_summary="x",
                         output_json="{}", raw_text="{}")
    ctx.tasks.enqueue("fetch_profile", TARGET, "b")
    ctx.tasks.enqueue("fetch_profile", OTHER, "b")
    ctx.db.execute(
        "INSERT INTO collection_coverage(kind, target, state, updated_at) VALUES ('fetch_profile', ?, 'done', ?)",
        (TARGET, iso()))
    ctx.db.execute(
        "INSERT INTO collection_coverage(kind, target, state, updated_at) VALUES ('fetch_profile', ?, 'done', ?)",
        (OTHER, iso()))


def test_preview_counts_target_data(ctx):
    seed(ctx)
    data = ForgetPerson(ctx.db).preview(TARGET)
    assert data["exists"] is True
    assert data["users"] == 1
    assert data["like_edges"] == 1
    assert data["comments"] == 1
    assert data["snapshots"] == 1
    assert data["listings"] == 1
    assert data["analyses"] == 1
    assert data["tasks"] == 1
    assert data["coverage"] == 1
    assert data["works"] == 1
    assert data["work_edges"] == 1          # 别人给他作品点的赞
    assert data["work_comments"] == 1
    assert data["total"] > 0


def test_delete_removes_only_target(ctx):
    seed(ctx)
    result = ForgetPerson(ctx.db).delete(TARGET)
    assert result["deleted"]["users"] == 1

    db = ctx.db
    assert db.scalar("SELECT COUNT(*) FROM users WHERE sec_uid=?", (TARGET,)) == 0
    assert db.scalar("SELECT COUNT(*) FROM users WHERE sec_uid=?", (OTHER,)) == 1
    assert db.scalar("SELECT COUNT(*) FROM like_edges WHERE sec_uid=?", (TARGET,)) == 0
    assert db.scalar("SELECT COUNT(*) FROM comments WHERE sec_uid=?", (TARGET,)) == 0
    assert db.scalar("SELECT COUNT(*) FROM user_snapshots WHERE sec_uid=?", (TARGET,)) == 0
    assert db.scalar("SELECT COUNT(*) FROM user_work_listings WHERE sec_uid=?", (TARGET,)) == 0
    assert db.scalar("SELECT COUNT(*) FROM llm_results WHERE subject_id=?", (TARGET,)) == 0
    assert db.scalar("SELECT COUNT(*) FROM tasks WHERE target=?", (TARGET,)) == 0
    assert db.scalar("SELECT COUNT(*) FROM collection_coverage WHERE target=?", (TARGET,)) == 0
    assert db.scalar("SELECT COUNT(*) FROM works WHERE aweme_id='theirs-1'") == 0

    # 其他人的数据保持完整
    assert db.scalar("SELECT COUNT(*) FROM like_edges WHERE sec_uid=?", (OTHER,)) == 1
    assert db.scalar("SELECT COUNT(*) FROM comments WHERE sec_uid=?", (OTHER,)) == 1
    assert db.scalar("SELECT COUNT(*) FROM user_snapshots WHERE sec_uid=?", (OTHER,)) == 1
    assert db.scalar("SELECT COUNT(*) FROM llm_results WHERE subject_id=?", (OTHER,)) == 1
    assert db.scalar("SELECT COUNT(*) FROM tasks WHERE target=?", (OTHER,)) == 1
    assert db.scalar("SELECT COUNT(*) FROM works WHERE aweme_id='mine-1'") == 1

    # 有审计记录
    event = db.query_one("SELECT message FROM event_logs WHERE scope='privacy' ORDER BY id DESC LIMIT 1")
    assert event is not None and "按人删除" in event["message"]


def test_delete_unknown_and_invalid(ctx):
    with pytest.raises(LookupError):
        ForgetPerson(ctx.db).delete("MS4wLjABAAAAmissing00000000000")
    with pytest.raises(ValueError):
        ForgetPerson(ctx.db).preview("  ")
    with pytest.raises(ValueError):
        ForgetPerson(ctx.db).delete("bad id with spaces")


class Client:
    def __init__(self, gateway, server):
        self.gateway, self.server = gateway, server
        self.base = f"http://127.0.0.1:{server.port}"

    def request(self, route, *, method="GET"):
        request = urllib.request.Request(self.base + route, method=method,
                                         headers={"Authorization": "Bearer " + self.gateway.token})
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as response:
            return response.code, response.read()
        with response:
            return response.status, response.read()


@pytest.fixture()
def client(paths):
    gateway = Gateway(paths)
    server = Server(create_app(paths, gateway=gateway))
    server.start()
    try:
        yield Client(gateway, server)
    finally:
        server.close()


def test_api_preview_and_delete(client, paths, ctx):
    seed(ctx)
    status, body = client.request(f"/api/people/{TARGET}")
    assert status == 200
    preview = json.loads(body)
    assert preview["exists"] is True and preview["like_edges"] == 1

    status, body = client.request(f"/api/people/{TARGET}", method="DELETE")
    assert status == 200
    assert json.loads(body)["deleted"]["users"] == 1

    status, _ = client.request(f"/api/people/{TARGET}")
    assert status == 200
    assert json.loads(client.request(f"/api/people/{TARGET}")[1])["exists"] is False

    status, _ = client.request(f"/api/people/{TARGET}", method="DELETE")
    assert status == 404
    status, _ = client.request("/api/people/bad%20id", method="DELETE")
    assert status == 400
