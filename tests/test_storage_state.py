"""登录态迁移（无头服务器路线）测试。

**要解决的问题**

云服务器上没有屏幕，没法扫码登录。而且持久 profile 目录跨机器搬不动：
本机是 Edge on Windows，服务器是 Chromium on Linux，profile 格式不通用。

`storage_state` 只存 cookie + localStorage，跟浏览器和系统无关，
是 Playwright 官方支持的跨机器迁移登录态的方式。

所以加了一个开关：打开后不再用 `launch_persistent_context`，
而是用 `new_context(storage_state=...)`。

**为什么不能直接用 launch_persistent_context + storage_state**
    Playwright 的这个函数**不接受 storage_state 参数**（签名里没有）。
    这组测试里有一条专门锁住这个事实 —— 哪天 Playwright 支持了，
    这条测试会失败，提醒我们可以简化实现。
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from scout.config import load_config
from scout.paths import Paths
from scout.session.manager import SessionManager


@pytest.fixture
def state_file(tmp_path):
    p = tmp_path / "state"
    p.mkdir(parents=True)
    f = p / "tier_a_storage.json"
    f.write_text(json.dumps({
        "cookies": [{"name": "sessionid", "value": "x", "domain": ".douyin.com",
                     "path": "/", "expires": -1, "httpOnly": True,
                     "secure": True, "sameSite": "Lax"}],
        "origins": [],
    }), encoding="utf-8")
    return f


def _manager(tmp_path, *, use_state: bool) -> SessionManager:
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "default.yaml").write_text(
        "tiers:\n"
        "  a:\n"
        "    mode: logged_in\n"
        f"    use_storage_state: {'true' if use_state else 'false'}\n",
        encoding="utf-8",
    )
    paths = Paths.build(root=tmp_path, account="main").ensure()
    cfg = load_config(paths)
    return SessionManager(cfg)


def test_storage_state_not_supported_by_persistent_context():
    """锁住这个事实：持久上下文不接受 storage_state。

    如果哪天 Playwright 支持了，这条会失败 —— 那是个好消息，
    说明可以简化实现（不用再分两条路）。
    """
    from playwright.async_api import BrowserType

    params = inspect.signature(BrowserType.launch_persistent_context).parameters
    assert "storage_state" not in params, (
        "Playwright 现在支持 storage_state 了，可以简化 SessionManager._open_tier"
    )


def test_switch_defaults_to_off():
    """默认不开 —— 本机开发要靠持久 profile 扫码，别把默认改坏。"""
    from scout.config import TierConfig

    assert TierConfig(name="a").use_storage_state is False


def test_config_reads_the_switch(tmp_path):
    assert _manager(tmp_path, use_state=True).config.tier("a").use_storage_state is True
    assert _manager(tmp_path, use_state=False).config.tier("a").use_storage_state is False


def test_state_file_path_follows_account(tmp_path):
    """登录态文件也要跟着账号走 —— 否则切账号会共用登录态。"""
    a = SessionManager(load_config(Paths.build(root=tmp_path, account="main").ensure()))
    b = SessionManager(load_config(Paths.build(root=tmp_path, account="alt").ensure()))
    assert a.state_file_for("a") != b.state_file_for("a")
    assert "main" in str(a.state_file_for("a"))
    assert "alt" in str(b.state_file_for("a"))


def test_missing_state_file_falls_back_to_profile(tmp_path):
    """文件不存在时必须退回持久 profile，不能静默失败。

    判断依据：`_open_tier` 里那个分支要求 `state_file.is_file()`。
    这里验证前提条件本身成立。
    """
    mgr = _manager(tmp_path, use_state=True)
    assert not mgr.state_file_for("a").is_file()


def test_force_persistent_profile_overrides_switch(tmp_path):
    """`scout login` 必须走持久 profile。

    否则登录态过期时会死循环：要登录 → 读旧 state → 失败 → 要登录。
    """
    mgr = _manager(tmp_path, use_state=True)
    assert mgr.config.tier("a").use_storage_state is True
    mgr.force_persistent_profile("a")
    assert "a" in mgr._force_persistent


def test_force_set_starts_empty(tmp_path):
    mgr = _manager(tmp_path, use_state=False)
    assert mgr._force_persistent == set()


def test_real_exported_state_has_what_we_need():
    """如果本地有真实导出的登录态，检查它结构完整（没有就跳过）。"""
    real = Path("data/accounts/main/state/tier_a_storage.json")
    if not real.is_file():
        pytest.skip("本地还没有导出的登录态")
    data = json.loads(real.read_text(encoding="utf-8"))
    assert "cookies" in data and "origins" in data
    assert len(data["cookies"]) > 0
    names = {c.get("name") for c in data["cookies"]}
    # 抖音登录态的关键 cookie —— 少了它就不是登录态
    assert "sessionid" in names or "sessionid_ss" in names or "sid_tt" in names
