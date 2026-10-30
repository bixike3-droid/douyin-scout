"""作品媒体：详情聚合、代理流、地址过期刷新、显式保存。

全部用假的上游流，不联网、不启动浏览器。
"""
from __future__ import annotations

import io
import json
import time

import pytest

from scout.app import AppContext
from scout.config import load_config
from scout.web_desktop.api import create_app
from scout.web_desktop.gateway import Gateway
from scout.web_desktop.server import Server


class Client:
    def __init__(self, gateway, server):
        self.gateway, self.server = gateway, server
        self.base = f"http://127.0.0.1:{server.port}"
        import urllib.error
        import urllib.request
        self._error = urllib.error.HTTPError
        self._request = urllib.request.Request
        self._open = urllib.request.urlopen

    def request(self, route, *, method="GET", headers=None):
        request = self._request(self.base + route, method=method,
                                headers={"Authorization": "Bearer " + self.gateway.token, **(headers or {})})
        try:
            response = self._open(request, timeout=10)
        except self._error as response:
            return response.code, response.read(), {key.lower(): value for key, value in response.headers.items()}
        with response:
            return response.status, response.read(), {key.lower(): value for key, value in response.headers.items()}

    def json(self, route, **kwargs):
        status, body, headers = self.request(route, **kwargs)
        assert status == 200, (status, body)
        return json.loads(body)


class Upstream:
    """可编排的假源站：按顺序返回给定的 (状态, 头, 字节)。"""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, range_header=""):
        self.calls.append((url, range_header))
        status, headers, body = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return status, dict(headers), io.BytesIO(body)


VIDEO = b"\x00\x00\x00\x18ftypmp42" + b"payload" * 40


@pytest.fixture()
def client(paths):
    gateway = Gateway(paths)
    server = Server(create_app(paths, gateway=gateway))
    server.start()
    try:
        yield Client(gateway, server)
    finally:
        server.close()


def seed(paths, *, images=None, **overrides):
    ctx = AppContext.create(load_config(paths))
    try:
        record = {
            "aweme_id": "7412345678901234567",
            "description": "校园夜跑",
            "create_time": 1761000000,
            "duration_ms": 61000,
            "play_count": 12345,
            "digg_count": 842,
            "comment_count": 31,
            "share_count": 7,
            "collect_count": 19,
            "music_title": "夜跑 BGM",
            "play_url": "https://cdn.example.invalid/v.mp4?x-expires=9999999999",
            "play_url_expires": int(time.time()) + 3600,
            "media_type": "video",
            "is_mine": 1,
        }
        record.update(overrides)
        if images is not None:
            record["images"] = images
        ctx.works.upsert(record)
        ctx.users.upsert({"sec_uid": "SEC1", "nickname": "观众甲"})
        ctx.like_edges.add_many([{"sec_uid": "SEC1", "aweme_id": record["aweme_id"], "notice_id": "n1"}])
    finally:
        ctx.close()
    return record["aweme_id"]


def test_detail_returns_metrics_likers_and_proxy_urls(client, paths):
    aweme_id = seed(paths)
    data = client.json(f"/api/works/{aweme_id}")
    work = data["work"]
    assert work["description"] == "校园夜跑"
    assert work["play_count"] == 12345 and work["digg_count"] == 842
    assert work["media_kind"] == "video" and work["image_count"] == 0
    assert data["urls"]["media"] == f"/api/works/{aweme_id}/media"
    assert data["urls"]["cover"] == f"/api/works/{aweme_id}/cover"
    assert data["likers"]["total"] == 1 and data["likers"]["items"][0]["nickname"] == "观众甲"
    assert data["saved"] is None
    # 签名地址不外泄
    assert "play_url" not in work and "x-expires" not in json.dumps(data)


def test_image_work_reports_gallery(client, paths):
    aweme_id = seed(paths, play_url="", play_url_expires=0, media_type="image",
                    images=["https://cdn.example.invalid/1.jpg", "https://cdn.example.invalid/2.jpg"])
    data = client.json(f"/api/works/{aweme_id}")
    assert data["work"]["media_kind"] == "image"
    assert data["work"]["image_count"] == 2
    assert data["urls"]["media"] == ""
    assert data["urls"]["images"] == [f"/api/works/{aweme_id}/image/0", f"/api/works/{aweme_id}/image/1"]


def test_unknown_or_invalid_id_is_404(client):
    status, _, _ = client.request("/api/works/999999999999999999")
    assert status == 404
    status, _, _ = client.request("/api/works/not-a-number")
    assert status == 404


def test_media_stream_forwards_range_and_content_headers(client, paths):
    aweme_id = seed(paths)
    upstream = Upstream((206, {"Content-Type": "video/mp4", "Content-Length": str(len(VIDEO)),
                               "Content-Range": f"bytes 0-{len(VIDEO) - 1}/{len(VIDEO)}",
                               "Accept-Ranges": "bytes"}, VIDEO))
    client.gateway.work_media._opener = upstream

    status, body, headers = client.request(f"/api/works/{aweme_id}/media", headers={"Range": "bytes=0-"})
    assert status == 206
    assert body == VIDEO
    assert headers["content-range"].startswith("bytes 0-")
    assert headers["accept-ranges"] == "bytes"
    # Range 透传给源站
    assert upstream.calls and upstream.calls[0][1] == "bytes=0-"


def test_expired_url_triggers_one_refresh(client, paths, monkeypatch):
    aweme_id = seed(paths, play_url="https://cdn.example.invalid/old.mp4?x-expires=1", play_url_expires=1)
    upstream = Upstream((200, {"Content-Type": "video/mp4", "Content-Length": str(len(VIDEO))}, VIDEO))
    client.gateway.work_media._opener = upstream
    refreshed = []

    async def refresh(target, *, force=False):
        refreshed.append((target, force))
        ctx = AppContext.create(load_config(paths))
        try:
            ctx.works.upsert({"aweme_id": target, "play_url": "https://cdn.example.invalid/new.mp4",
                              "play_url_expires": int(time.time()) + 3600})
        finally:
            ctx.close()
        return "https://cdn.example.invalid/new.mp4"

    monkeypatch.setattr(client.gateway, "refresh_work", refresh)
    status, body, _ = client.request(f"/api/works/{aweme_id}/media")
    assert status == 200 and body == VIDEO
    assert refreshed == [(aweme_id, False)]
    assert upstream.calls[0][0].endswith("/new.mp4")


def test_upstream_refusal_refreshes_then_retries(client, paths, monkeypatch):
    aweme_id = seed(paths)
    upstream = Upstream((403, {}, b""), (206, {"Content-Type": "video/mp4", "Content-Length": "4"}, b"data"))
    client.gateway.work_media._opener = upstream
    forced = []

    async def refresh(target, *, force=False):
        forced.append(force)
        return "https://cdn.example.invalid/fresh.mp4"

    monkeypatch.setattr(client.gateway, "refresh_work", refresh)
    status, body, _ = client.request(f"/api/works/{aweme_id}/media")
    assert status == 206 and body == b"data"
    assert forced == [True]
    assert len(upstream.calls) == 2


def test_cover_and_image_are_proxied_and_cached(client, paths, monkeypatch):
    aweme_id = seed(paths, play_url="", play_url_expires=0, media_type="image",
                    images=["https://cdn.example.invalid/1.jpg"])
    client.gateway.work_media._opener = Upstream((200, {"Content-Type": "image/jpeg"}, b"\xff\xd8jpeg"))
    status, body, headers = client.request(f"/api/works/{aweme_id}/image/0")
    assert status == 200 and body.startswith(b"\xff\xd8")
    assert headers["cache-control"].startswith("private")
    status, body, headers = client.request(f"/api/works/{aweme_id}/cover")
    assert status == 200 and body.startswith(b"\xff\xd8")

    async def refresh(target, *, force=False):
        raise AssertionError("图片有效时不应刷新")

    monkeypatch.setattr(client.gateway, "refresh_work", refresh)
    status, _, _ = client.request(f"/api/works/{aweme_id}/image/0")
    assert status == 200


def test_image_out_of_range_is_404(client, paths):
    aweme_id = seed(paths, play_url="", play_url_expires=0, media_type="image",
                    images=["https://cdn.example.invalid/1.jpg"])
    status, _, _ = client.request(f"/api/works/{aweme_id}/image/9")
    assert status == 404


def test_save_usage_and_clear(client, paths):
    aweme_id = seed(paths)
    client.gateway.work_media._opener = Upstream((200, {"Content-Type": "video/mp4"}, VIDEO))
    saved = client.json(f"/api/works/{aweme_id}/save", method="POST")
    assert saved["bytes"] == len(VIDEO) and saved["name"].endswith(".mp4")

    detail = client.json(f"/api/works/{aweme_id}")
    assert detail["saved"]["bytes"] == len(VIDEO)

    usage = client.json("/api/media")
    assert usage["files"] == 1 and usage["bytes"] == len(VIDEO)

    assert client.json(f"/api/works/{aweme_id}/save", method="DELETE")["removed"] is True
    assert client.json("/api/media")["files"] == 0

    client.json(f"/api/works/{aweme_id}/save", method="POST")
    cleared = client.json("/api/media", method="DELETE")
    assert cleared["files"] == 1 and cleared["bytes"] == len(VIDEO)
    assert client.json("/api/media")["files"] == 0
