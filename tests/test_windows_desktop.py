"""Trust and runtime boundaries for the WebView2 desktop carrier."""
from pathlib import Path
from types import SimpleNamespace
import json
import sys

import pytest

from scout.web_desktop.edge import DesktopBridge, trusted_navigation
from scout.web_desktop.gateway import Gateway
from scout.tools.workspace import python_exe


def test_native_file_grants_require_the_desktop_session_token(paths, tmp_path):
    file = tmp_path / "完整素材.zip"
    file.write_bytes(b"original")
    gateway = Gateway(paths)
    bridge = DesktopBridge(gateway, [file])
    with pytest.raises(ValueError):
        bridge.initialFiles("wrong-token")
    assert not gateway.uploads
    granted = json.loads(bridge.initialFiles(gateway.token))
    assert len(granted) == 1
    assert gateway.upload(granted[0]["id"]).path == file.resolve()
    assert json.loads(bridge.initialFiles(gateway.token)) == []
    gateway.discard(granted[0]["id"])
    assert file.read_bytes() == b"original"


@pytest.mark.parametrize("target", ["https://example.com", "file:///C:/Windows/win.ini", "http://127.0.0.1:1235/", "http://127.0.0.1:1234@example.com/", "javascript:alert(1)"])
def test_native_bridge_cannot_follow_a_navigation_off_origin(target):
    assert not trusted_navigation(target, "http://127.0.0.1:1234")
    assert trusted_navigation("http://127.0.0.1:1234/#token=local", "http://127.0.0.1:1234")


def test_packaged_scripts_prefer_the_shipped_python_over_path(ctx, tmp_path, monkeypatch):
    exe = tmp_path / "源镜.exe"
    exe.touch()
    python = tmp_path / "runtime/python/python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setenv("PATH", "")
    assert Path(python_exe(ctx)) == python
