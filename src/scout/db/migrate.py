"""迁移：按编号顺序执行 migrations/*.sql，已执行的记入 schema_migrations。

规则：
- 文件名必须是 NNNN_name.sql，NNNN 四位数字，执行顺序按它排序。
- 每个迁移文件只在单个事务内跑一次，失败整体回滚。
- 已应用的迁移永不修改。改 schema 请新增文件。
"""

from __future__ import annotations

from pathlib import Path

from ..util import iso
from .connect import Database

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _migration_files(directory: Path = MIGRATIONS_DIR) -> list[tuple[int, str, Path]]:
    items: list[tuple[int, str, Path]] = []
    for path in sorted(directory.glob("*.sql")):
        stem = path.stem
        head, _, name = stem.partition("_")
        if not head.isdigit():
            raise ValueError(f"迁移文件名必须以编号开头（NNNN_name.sql）：{path.name}")
        items.append((int(head), name or stem, path))
    items.sort(key=lambda x: x[0])
    return items


def _ensure_table(db: Database) -> None:
    db.conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def applied_versions(db: Database) -> set[int]:
    _ensure_table(db)
    return {int(r["version"]) for r in db.query("SELECT version FROM schema_migrations")}


def pending_versions(db: Database, directory: Path = MIGRATIONS_DIR) -> list[tuple[int, str]]:
    done = applied_versions(db)
    return [(v, n) for v, n, _ in _migration_files(directory) if v not in done]


def migrate(db: Database, directory: Path = MIGRATIONS_DIR, *, verbose: bool = False) -> list[str]:
    """应用所有未执行的迁移，返回已应用的名字列表。

    注意：sqlite3 的 executescript() 会先隐式提交当前事务，所以不能把它包在
    Database.transaction() 里。这里改成把 BEGIN/COMMIT 写进脚本本身来保证原子性；
    迁移记录随后单独写入。DDL 全部是 IF NOT EXISTS，即使中途断电重跑也安全。
    """
    _ensure_table(db)
    done = applied_versions(db)
    applied: list[str] = []
    for version, name, path in _migration_files(directory):
        if version in done:
            continue
        sql = path.read_text(encoding="utf-8")
        try:
            db.conn.executescript(f"BEGIN;\n{sql}\nCOMMIT;")
        except Exception:
            try:
                db.conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        db.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?,?,?)",
            (version, name, iso()),
        )
        applied.append(f"{version:04d}_{name}")
        if verbose:
            print(f"[migrate] applied {version:04d}_{name}")
    return applied
