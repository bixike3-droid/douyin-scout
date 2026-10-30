"""应用内更新：检查、下载状态机、跳过版本与自动替换的前置条件。"""
from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.request

import pytest

import scout.desktop.update as update_module
import scout.web_desktop.gateway as gateway_module
from scout.web_desktop.api import create_app
from scout.web_desktop.gateway import Gateway
from scout.web_desktop.server import Server


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

    def json(self, route, **kwargs):
        status, body = self.request(route, **kwargs)
        assert status == 200, (status, body)
        return json.loads(body)


@pytest.fixture()
def client(paths):
    gateway = Gateway(paths)
    server = Server(create_app(paths, gateway=gateway))
    server.start()
    try:
        yield Client(gateway, server)
    finally:
        server.close()


def latest(version="9.9.9", **extra):
    return {"version": version, "name": f"v{version}", "notes": "修复若干问题",
            "page": "https://example.invalid/releases", "zip_url": "https://example.invalid/app.zip",
            "zip_size": 2048, "sha256": "x" * 64, "prerelease": False, "source": "feed", **extra}


def test_check_reports_newer_version(client, monkeypatch):
    monkeypatch.setattr(gateway_module, "fetch_latest", lambda timeout=6.0: latest())
    data = client.json("/api/update?check=1")
    assert data["newer"] is True
    assert data["latest"]["version"] == "9.9.9"
    assert data["current"] == update_module.current_version()
    assert data["checked_at"] > 0


def test_check_reports_up_to_date_and_failure(client, monkeypatch):
    monkeypatch.setattr(gateway_module, "fetch_latest",
                        lambda timeout=6.0: latest(update_module.current_version()))
    assert client.json("/api/update?check=1")["newer"] is False

    monkeypatch.setattr(gateway_module, "fetch_latest", lambda timeout=6.0: None)
    data = client.json("/api/update?check=1")
    assert data["latest"] is None and data["newer"] is False


def test_download_state_machine_and_apply(client, paths, monkeypatch, tmp_path):
    monkeypatch.setattr(gateway_module, "fetch_latest", lambda timeout=6.0: latest())
    target_folder = tmp_path / "install"
    target_folder.mkdir()
    monkeypatch.setattr(gateway_module, "install_dir", lambda: target_folder)
    launched = []
    monkeypatch.setattr(gateway_module, "launch_updater", lambda archive, folder: launched.append((archive, folder)) or True)

    def fake_download(url, dest, timeout=60.0, sha256="", progress=None):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"zip" * 800)
        if progress:
            progress(1024, 2400)
            progress(2400, 2400)
        return True

    monkeypatch.setattr(gateway_module, "download_update", fake_download)

    assert client.request("/api/update/apply", method="POST")[0] == 400      # 还没检查/下载
    status = client.json("/api/update/download", method="POST")
    assert status["download"]["state"] in ("downloading", "ready")

    deadline = time.monotonic() + 5
    data = client.json("/api/update")
    while data["download"]["state"] == "downloading" and time.monotonic() < deadline:
        time.sleep(0.05)
        data = client.json("/api/update")
    assert data["download"]["state"] == "ready"
    assert data["download"]["received"] == 2400
    assert data["download"]["version"] == "9.9.9"

    applied = client.json("/api/update/apply", method="POST")
    assert data["download"]["verified"] is True
    assert applied["started"] is True
    assert launched and launched[0][1] == target_folder
    assert client.json("/api/update")["download"]["state"] == "applying"


def test_apply_refuses_unverified_archive(client, paths, monkeypatch, tmp_path):
    monkeypatch.setattr(gateway_module, "fetch_latest", lambda timeout=6.0: latest(sha256=""))
    monkeypatch.setattr(gateway_module, "install_dir", lambda: tmp_path)

    def fake_download(url, dest, timeout=60.0, sha256="", progress=None):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"zip" * 800)
        return True

    monkeypatch.setattr(gateway_module, "download_update", fake_download)
    client.json("/api/update/download", method="POST")
    deadline = time.monotonic() + 5
    while client.json("/api/update")["download"]["state"] == "downloading" and time.monotonic() < deadline:
        time.sleep(0.05)
    status, body = client.request("/api/update/apply", method="POST")
    assert status == 400
    assert "sha256" in body.decode("utf-8")


def test_source_mode_refuses_apply(client, paths, monkeypatch):
    monkeypatch.setattr(gateway_module, "fetch_latest", lambda timeout=6.0: latest())
    monkeypatch.setattr(gateway_module, "install_dir", lambda: None)

    def fake_download(url, dest, timeout=60.0, sha256="", progress=None):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"zip" * 800)
        return True

    monkeypatch.setattr(gateway_module, "download_update", fake_download)
    client.json("/api/update/download", method="POST")
    deadline = time.monotonic() + 5
    while client.json("/api/update")["download"]["state"] == "downloading" and time.monotonic() < deadline:
        time.sleep(0.05)
    status, body = client.request("/api/update/apply", method="POST")
    assert status == 400
    assert "源码运行" in body.decode("utf-8")


def test_download_fails_when_source_unreachable(client, monkeypatch):
    monkeypatch.setattr(gateway_module, "fetch_latest", lambda timeout=6.0: None)
    status, body = client.request("/api/update/download", method="POST")
    assert status == 400
    assert "无法获取版本信息" in body.decode("utf-8")


def test_skip_version_and_auto_check_preferences(client, monkeypatch):
    monkeypatch.setattr(gateway_module, "fetch_latest", lambda timeout=6.0: latest())
    client.json("/api/update?check=1")
    assert client.json("/api/preferences", method="PUT", body={"update_skipped": "v9.9.9"})["update_skipped"] == "9.9.9"
    data = client.json("/api/update")
    assert data["skipped"] == "9.9.9"

    client.json("/api/preferences", method="PUT", body={"update_auto": False})
    assert client.json("/api/update")["auto_check"] is False

    assert client.request("/api/preferences", method="PUT", body={"update_skipped": 5})[0] == 400


def test_download_reports_progress(monkeypatch, tmp_path):
    payload = b"zip" * 800

    class Response(io.BytesIO):
        headers = {"Content-Length": str(len(payload))}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(update_module, "urlopen", lambda request, timeout=0: Response(payload))
    seen = []
    target = tmp_path / "app.zip"
    assert update_module.download("https://example.invalid/app.zip", target,
                                  progress=lambda received, total: seen.append((received, total)))
    assert target.read_bytes() == payload
    assert seen and seen[-1] == (len(payload), len(payload))
