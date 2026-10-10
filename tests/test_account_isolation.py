"""账号隔离测试。

**为什么这组测试重要**

账号串号是"事后才发现、且不可逆"的错误 —— 等你看出来时，两个号的粉丝、作品、
画像已经混在一张表里，而且无法分辨哪条属于谁。

所以隔离必须靠**物理隔离**（一个账号一个数据目录）来保证，而不是靠每条 SQL 都写对。
这组测试盯住三件事：

1. 路径确实按账号分开了
2. **登录态（浏览器 profile）也跟着分开** —— 这里真出过 bug
3. 账号名不能用来做路径穿越
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scout.config import load_config
from scout.paths import DEFAULT_ACCOUNT, Paths, validate_account
from scout.store.account import check_account


# ── 账号名校验 ──────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["../evil", "a/b", "a\\b", "", "   ", "a" * 41, "a b"])
def test_rejects_dangerous_account_names(bad):
    """账号名会直接变成目录名，必须挡住路径穿越和非法字符。"""
    with pytest.raises(ValueError):
        validate_account(bad)


@pytest.mark.parametrize("good", ["main", "alt", "小号A", "my-account_2", "a"])
def test_accepts_reasonable_names(good):
    assert validate_account(good) == good


def test_account_name_is_stripped():
    assert validate_account("  main  ") == "main"


# ── 目录隔离 ────────────────────────────────────────────────


def test_each_account_gets_its_own_data_dir(tmp_path):
    a = Paths.build(root=tmp_path, account="main")
    b = Paths.build(root=tmp_path, account="alt")
    assert a.data_dir != b.data_dir
    assert a.db_path != b.db_path
    assert a.raw_dir != b.raw_dir
    assert a.profiles_dir != b.profiles_dir


def test_account_dir_is_nested_under_accounts(tmp_path):
    p = Paths.build(root=tmp_path, account="main")
    assert p.data_dir == tmp_path / "data" / "accounts" / "main"
    assert p.db_path.parent == p.data_dir / "db"


def test_default_account_is_main(tmp_path):
    assert Paths.build(root=tmp_path).account == DEFAULT_ACCOUNT


def test_profile_dir_follows_account(tmp_path):
    """**回归测试**：登录态必须跟着账号走。

    这里真出过 bug：`resolved_profile_dir` 原来硬编码
    `Path("data/profiles") / f"tier_{name}"`，**完全无视传入的 paths**，
    导致所有账号共用同一个浏览器 profile —— 账号隔离在登录态这一层直接漏掉。

    而且这个 bug 很隐蔽：数据目录明明是分开的，但登录态是共用的，
    表现出来是"切了账号，采集却还是写进另一个号的库"。
    """
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "default.yaml").write_text("tiers:\n  a:\n    mode: logged_in\n",
                                                      encoding="utf-8")
    a = Paths.build(root=tmp_path, account="main")
    b = Paths.build(root=tmp_path, account="alt")
    cfg_a, cfg_b = load_config(a), load_config(b)

    dir_a = cfg_a.tier("a").resolved_profile_dir(a)
    dir_b = cfg_b.tier("a").resolved_profile_dir(b)

    assert dir_a != dir_b, "两个账号的浏览器 profile 指向了同一个目录"
    assert dir_a == a.profiles_dir / "tier_a"
    assert "accounts" in str(dir_a) and "main" in str(dir_a)


def test_explicit_absolute_profile_dir_still_honored(tmp_path):
    """显式配了绝对路径时照旧尊重（有人就是想把 profile 放别处）。"""
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    fixed = tmp_path / "custom_profile"
    (tmp_path / "config" / "default.yaml").write_text(
        f"tiers:\n  a:\n    mode: logged_in\n    profile_dir: {fixed}\n", encoding="utf-8"
    )
    p = Paths.build(root=tmp_path, account="main")
    assert load_config(p).tier("a").resolved_profile_dir(p) == fixed


# ── 身份对账 ────────────────────────────────────────────────


class _StubDB:
    def __init__(self):
        self._cursor = "MS4wLjABAAAAuser_a"
        self._users = {self._cursor: {"nickname": "张三", "sec_uid": self._cursor}}


class _StubCursors:
    def __init__(self, value=""):
        self._v = value

    def get(self, name):
        return self._v if name == "self_sec_uid" else None


class _StubUsers:
    def __init__(self, nick=""):
        self._nick = nick
        self._sec = ""

    def get(self, sec_uid):
        return {"nickname": self._nick} if self._nick else {}


class _StubCtx:
    def __init__(self, stored_sec="", stored_nick=""):
        self.cursors = _StubCursors(stored_sec)
        self.users = _StubUsers(stored_nick)


def test_matching_identity_passes():
    ctx = _StubCtx("MS4wLjABAAAAa", "张三")
    r = check_account(ctx, live_sec_uid="MS4wLjABAAAAa", live_nickname="张三")
    assert r.ok and r.status == "ok"


def test_mismatched_identity_is_blocked():
    """库里是张三的，但登录的是李四 —— 必须拦下。"""
    ctx = _StubCtx("MS4wLjABAAAAa", "张三")
    r = check_account(ctx, live_sec_uid="MS4wLjABAAAAB", live_nickname="李四")
    assert not r.ok
    assert r.status == "mismatch"
    assert "账号不匹配" in r.message
    # 报错信息必须给出可操作的出路，不能只说"错了"
    assert "--account" in r.message


def test_first_run_without_stored_identity_is_allowed():
    ctx = _StubCtx("", "")
    r = check_account(ctx, live_sec_uid="MS4wLjABAAAAnew", live_nickname="新人")
    assert r.ok and r.status == "unknown"


def test_no_login_probe_is_not_a_failure():
    ctx = _StubCtx("MS4wLjABAAAAa", "张三")
    r = check_account(ctx)
    assert r.ok and r.status == "no_login"


# ── 旧布局迁移 ──────────────────────────────────────────────


def test_legacy_layout_is_migrated(tmp_path):
    from scout.store.migrate_layout import migrate_legacy, needs_migration

    base = tmp_path / "data"
    (base / "db").mkdir(parents=True)
    (base / "db" / "scout.sqlite3").write_text("x", encoding="utf-8")
    (base / "raw").mkdir()
    (base / "raw" / "a.json").write_text("{}", encoding="utf-8")

    p = Paths.build(root=tmp_path, account="main")
    assert needs_migration(p)

    result = migrate_legacy(p, account="main")
    assert result.changed
    assert (p.db_path).is_file()
    assert (p.raw_dir / "a.json").is_file()
    assert not (base / "db" / "scout.sqlite3").exists(), "旧文件应该被搬走而不是复制"
    assert not needs_migration(p)


def test_migration_never_overwrites_existing(tmp_path):
    """目标已有数据时**跳过**，不覆盖 —— 宁可停下让人处理。"""
    from scout.store.migrate_layout import migrate_legacy

    base = tmp_path / "data"
    (base / "db").mkdir(parents=True)
    (base / "db" / "scout.sqlite3").write_text("OLD", encoding="utf-8")
    target = base / "accounts" / "main" / "db"
    target.mkdir(parents=True)
    (target / "scout.sqlite3").write_text("NEW", encoding="utf-8")

    p = Paths.build(root=tmp_path, account="main")
    result = migrate_legacy(p, account="main")
    assert not result.changed
    assert result.skipped
    assert (target / "scout.sqlite3").read_text(encoding="utf-8") == "NEW"


def test_migration_is_idempotent(tmp_path):
    from scout.store.migrate_layout import migrate_legacy

    p = Paths.build(root=tmp_path, account="main")
    assert not migrate_legacy(p, account="main").changed
    assert not migrate_legacy(p, account="main").changed


def test_dry_run_makes_no_changes(tmp_path):
    from scout.store.migrate_layout import migrate_legacy

    base = tmp_path / "data"
    (base / "db").mkdir(parents=True)
    (base / "db" / "scout.sqlite3").write_text("x", encoding="utf-8")
    p = Paths.build(root=tmp_path, account="main")
    result = migrate_legacy(p, account="main", dry_run=True)
    assert result.moved
    assert (base / "db" / "scout.sqlite3").exists(), "dry-run 不该动文件"
