"""旧数据布局 → 账号目录布局 的一次性迁移。

升级前::

    data/db/scout.sqlite3
    data/raw/
    data/profiles/
    data/exports/
    data/state/

升级后::

    data/accounts/main/db/scout.sqlite3
    data/accounts/main/raw/
    ...

迁移是 **move**（不是 copy），所以不会占双倍空间，也不会留下两份数据让人搞混。
但只有在目标不存在时才动手 —— 重复运行是安全的（幂等）。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..paths import DEFAULT_ACCOUNT, Paths


@dataclass
class MigrationResult:
    moved: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.moved)

    def to_dict(self) -> dict:
        return {
            "moved": [{"from": a, "to": b} for a, b in self.moved],
            "skipped": self.skipped,
            "failed": [{"from": a, "reason": b} for a, b in self.failed],
        }


def needs_migration(paths: Paths) -> bool:
    """旧布局里还有东西吗？"""
    return any(p.exists() for p in paths.legacy_paths())


def migrate_legacy(
    paths: Paths, *, account: str = DEFAULT_ACCOUNT, dry_run: bool = False
) -> MigrationResult:
    """把旧布局的数据搬进账号目录。"""
    result = MigrationResult()
    base = paths.accounts_dir.parent
    target = paths.account_dirs(account)

    mapping = [
        (base / "db" / "scout.sqlite3", target / "db" / "scout.sqlite3"),
        (base / "raw", target / "raw"),
        (base / "profiles", target / "profiles"),
        (base / "exports", target / "exports"),
        (base / "state", target / "state"),
    ]

    for src, dst in mapping:
        if not src.exists():
            continue
        if dst.exists():
            # 目标已经有数据了 —— 绝不覆盖，记下来让人自己判断
            result.skipped.append(f"{src}（目标已存在：{dst}）")
            continue
        if dry_run:
            result.moved.append((str(src), str(dst)))
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            result.moved.append((str(src), str(dst)))
        except Exception as exc:
            result.failed.append((str(src), f"{type(exc).__name__}: {exc}"))

    # 搬完把空壳目录清掉，避免下次又判断成"需要迁移"
    if not dry_run:
        for d in (base / "db", base / "logs"):
            try:
                if d.is_dir() and not any(d.iterdir()):
                    d.rmdir()
            except OSError:
                pass

    return result
