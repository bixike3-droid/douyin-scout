"""热点视频：词条关联与「交给团队」的路由。"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from scout.store.hot import HotVideoLinks
from scout.web_desktop.api import create_app
from scout.web_desktop.gateway import Gateway
from scout.web_desktop.server import Server

SID = "2719825"
A = "7702292106248850739"
B = "7702054563636940075"


def seed(ctx):
    ctx.works.upsert({"aweme_id": A, "description": "代表视频", "digg_count": 100, "play_count": 1000,
                      "author_sec_uid": "SEC_A", "play_url": "https://cdn.example.invalid/a.mp4",
                      "play_url_expires": 9999999999, "media_type": "video"})
    ctx.works.upsert({"aweme_id": B, "description": "相关视频", "digg_count": 50,
                      "play_url": "https://cdn.example.invalid/b.mp4",
                      "play_url_expires": 9999999999, "media_type": "video"})
    HotVideoLinks(ctx.db).replace(SID, [A, B])


def test_links_replace_and_listing(ctx):
    seed(ctx)
    store = HotVideoLinks(ctx.db)
    rows = store.listing(SID)
    assert [row["aweme_id"] for row in rows] == [A, B]
    assert rows[0]["rank"] == 0 and rows[0]["description"] == "代表视频"
    assert store.fetched_at(SID)

    store.replace(SID, [B])
    rows = store.listing(SID)
    assert [row["aweme_id"] for row in rows] == [B]


class Client:
    def __init__(self, gateway, server):
        self.gateway, self.server = gateway, server
        self.base = f"http://127.0.0.1:{server.port}"

    def request(self, route, *, method="GET", body=None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": "Bearer " + self.gateway.token}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + route, data=data, method=method, headers=headers)
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


def test_api_lists_links(client, ctx):
    seed(ctx)
    status, body = client.request(f"/api/hot/{SID}/videos")
    assert status == 200
    data = json.loads(body)
    assert [item["aweme_id"] for item in data["items"]] == [A, B]
    assert data["fetched_at"]


def test_send_route_wires_to_gateway(client, monkeypatch):
    seen = {}

    async def fake(sentence_id, aweme_id, request=""):
        seen.update(sentence_id=sentence_id, aweme_id=aweme_id, request=request)
        return {"conversation_id": 99}

    monkeypatch.setattr(client.gateway, "send_hot_video", fake)
    status, body = client.request(f"/api/hot/{SID}/videos/{A}/send", method="POST", body={})
    assert status == 200
    assert json.loads(body)["conversation_id"] == 99
    assert seen == {"sentence_id": SID, "aweme_id": A, "request": ""}
