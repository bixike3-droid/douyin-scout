"""Real loopback HTTP and WebSocket adapter tests; no provider or GUI calls."""
import asyncio
import json
import urllib.request
import urllib.error
from pathlib import Path
import time

import pytest
from PIL import Image

from scout.web_desktop.api import create_app
from scout.web_desktop.gateway import Gateway
from scout.web_desktop.window import Server
from scout.store.conversation import Conversations
from scout.store.attachments import Attachments
from scout.attachments import import_file
from scout.app import AppContext
from scout.config import load_config


class Client:
    def __init__(self, gateway, server):
        self.gateway, self.server = gateway, server
        self.base = f"http://127.0.0.1:{server.port}"

    def request(self, route, *, method="GET", body=None, raw=None, auth=True, headers=None):
        data = json.dumps(body).encode() if body is not None else raw
        h = {"Authorization": "Bearer " + self.gateway.token} if auth else {}
        if body is not None:
            h["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + route, data=data, method=method, headers={**h, **(headers or {})})
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as response:
            return response.code, response.read(), dict(response.headers)
        with response:
            return response.status, response.read(), dict(response.headers)

    def json(self, route, **kwargs):
        status, value, headers = self.request(route, **kwargs)
        assert status == 200, value
        return json.loads(value)


@pytest.fixture
def client(paths):
    gateway = Gateway(paths)
    server = Server(create_app(paths, gateway=gateway))
    server.start()
    try:
        yield Client(gateway, server)
    finally:
        server.close()


def test_private_api_requires_token_and_matching_origin(client):
    assert client.request("/api/bootstrap", auth=False)[0] == 401
    assert client.request("/api/bootstrap", headers={"Origin": "https://unrelated.example"})[0] == 403
    data = client.json("/api/bootstrap")
    assert "api_key" not in data["settings"] and data["conversations"] == []


def test_streamed_upload_keeps_arbitrary_format_and_never_deletes_native_source(client, tmp_path):
    payload = b"archive-like-binary\x00" * 200000
    added = client.json("/api/uploads?name=sample.zip", method="PUT", raw=payload)
    assert added["size"] == len(payload) and added["kind"] == "archive"
    assert client.json("/api/uploads?name=unknown.xyz123", method="PUT", raw=b"arbitrary")["status"] == "ready"
    assert client.request(f"/api/uploads/{added['id']}/file")[1] == payload
    path = tmp_path / "native-original.txt"
    path.write_text("keep me", encoding="utf-8")
    native = client.gateway.register([path])[0]
    client.json(f"/api/uploads/{native['id']}", method="DELETE")
    assert path.read_text() == "keep me"
    temporary = client.gateway.upload(added["id"]).path
    client.json(f"/api/uploads/{added['id']}", method="DELETE")
    assert not temporary.exists()


def test_media_range_and_thumbnail_are_real_files(client, tmp_path):
    path = tmp_path / "red.png"
    Image.new("RGB", (900, 500), "red").save(path)
    with AppContext.create(load_config(client.gateway.paths)) as ctx:
        cid = Conversations(ctx.db).create("image")
        item = import_file(ctx.paths, path)
        Attachments(ctx.db).add(item, cid)
    status, preview, _ = client.request(f"/api/files/{item['id']}?variant=thumbnail")
    assert status == 200 and preview.startswith(b"\xff\xd8")
    status, partial, headers = client.request(f"/api/files/{item['id']}", headers={"Range": "bytes=0-9"})
    assert status == 206 and len(partial) == 10
    assert client.request("/api/files/../../config/llm.local.yaml")[0] != 200


def test_job_stream_and_cancel_do_not_require_qt(client):
    async def runner(paths, kind, emit, options):
        emit({"type": "answer_delta", "delta": "real transport"})
        await asyncio.Event().wait()
    client.gateway.runner = runner
    from websockets.sync.client import connect
    with connect(f"ws://127.0.0.1:{client.server.port}/api/events?token={client.gateway.token}", origin=client.base) as socket:
        assert json.loads(socket.recv())["type"] == "snapshot"
        job = client.json("/api/jobs", method="POST", body={"kind": "enterprise"})
        found = []
        while "answer_delta" not in found:
            found.append(json.loads(socket.recv(timeout=3))["type"])
        assert client.json("/api/job")["answer"] == "real transport"
        client.json("/api/jobs/stop", method="POST")
        while True:
            value = json.loads(socket.recv(timeout=3))
            if value["type"] == "result":
                assert value["state"] == "cancelled"
                break


def test_settings_persist_locally_and_hide_key(client):
    saved = client.json("/api/settings", method="PUT", body={"api_key": "test-api-key-never-sent", "model": "deepseek-flash", "reasoning_effort": "low"})
    assert saved["model"] == "deepseek-flash" and "test-api-key-never-sent" not in json.dumps(saved)
    assert load_config(client.gateway.paths).llm.api_key == "test-api-key-never-sent"
    preferences = client.json("/api/preferences", method="PUT", body={"theme": "dark"})
    assert preferences["theme"] == "dark"


def test_video_compatibility_preview_and_original_preservation(client, tmp_path):
    from scout.attachments import _run_ffmpeg
    source = tmp_path / "sample.mp4"
    result = _run_ffmpeg(["-f", "lavfi", "-i", "color=c=blue:s=128x96:d=0.2", "-c:v", "libx264", "-y", str(source)])
    assert result.returncode == 0
    original = source.read_bytes()
    with AppContext.create(load_config(client.gateway.paths)) as ctx:
        cid = Conversations(ctx.db).create("video")
        item = import_file(ctx.paths, source)
        Attachments(ctx.db).add(item, cid)
    status, preview, headers = client.request(f"/api/files/{item['id']}?variant=web-video")
    assert status == 200 and preview[:4] == b"\x1aE\xdf\xa3"
    assert headers["content-type"].startswith("video/webm")
    assert source.read_bytes() == original
