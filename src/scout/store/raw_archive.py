"""原始响应归档。

这是整个项目最重要的资产：抖音改版是必然的，只要原始响应还在，
就能随时回放重解，不用重新采集。所以：

- 默认策略是永不删除（storage.raw_retention_days = 0）。
- 按 sha256 去重：同一个响应重复出现只落一份。
- 超过 raw_max_bytes 的大响应只记元数据，不落盘（避免磁盘被视频流塞满）。
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..db.connect import Database
from ..paths import Paths
from ..util import iso, sha256_bytes, truncate

_TEXTUAL = ("json", "javascript", "html", "xml", "text", "x-www-form-urlencoded")


@dataclass(frozen=True)
class RawRef:
    id: int
    sha256: str
    path: str
    byte_size: int
    deduped: bool
    stored: bool  # False 表示只记了元数据、正文没落盘

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sha256": self.sha256,
            "path": self.path,
            "byte_size": self.byte_size,
            "deduped": self.deduped,
            "stored": self.stored,
        }


def _extension(content_type: str, url: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct:
        guessed = mimetypes.guess_extension(ct)
        if guessed:
            return guessed.lstrip(".")
        if "json" in ct:
            return "json"
        if "html" in ct:
            return "html"
    suffix = Path(url.split("?")[0]).suffix.lstrip(".")
    return suffix if 0 < len(suffix) <= 5 else "bin"


def _looks_textual(content_type: str) -> bool:
    ct = (content_type or "").lower()
    return any(t in ct for t in _TEXTUAL)


class RawArchive:
    def __init__(self, db: Database, paths: Paths, *, max_bytes: int = 8_000_000):
        self.db = db
        self.paths = paths
        self.max_bytes = max_bytes

    # ── 写入 ────────────────────────────────────────────────

    def save(
        self,
        payload: bytes | str,
        *,
        url: str = "",
        tier: str = "",
        content_type: str = "",
        source: str = "collect",
        note: str = "",
    ) -> RawRef:
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
        digest = sha256_bytes(data)

        existing = self.db.query_one("SELECT * FROM raw_blobs WHERE sha256 = ?", (digest,))
        if existing is not None:
            return RawRef(
                id=int(existing["id"]),
                sha256=digest,
                path=existing["path"],
                byte_size=int(existing["byte_size"]),
                deduped=True,
                stored=bool(existing["path"]),
            )

        stored = len(data) <= self.max_bytes
        rel_path = ""
        if stored:
            day = iso()[:10]
            target_dir = self.paths.raw_dir / day
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{digest[:20]}.{_extension(content_type, url)}"
            if not target.exists():
                target.write_bytes(data)
            rel_path = str(target.relative_to(self.paths.root))

        self.db.execute(
            """
            INSERT INTO raw_blobs (sha256, path, url, tier, content_type, byte_size,
                                   collected_at, source, note)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                digest,
                rel_path,
                truncate(url, 2000),
                tier,
                truncate(content_type, 120),
                len(data),
                iso(),
                source,
                truncate(note, 500),
            ),
        )
        row = self.db.query_one("SELECT id FROM raw_blobs WHERE sha256 = ?", (digest,))
        return RawRef(
            id=int(row["id"]),
            sha256=digest,
            path=rel_path,
            byte_size=len(data),
            deduped=False,
            stored=stored,
        )

    # ── 读取 ────────────────────────────────────────────────

    def get(self, raw_id: int) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM raw_blobs WHERE id = ?", (raw_id,))
        return dict(row) if row else None

    def load_bytes(self, raw_id: int) -> bytes:
        row = self.get(raw_id)
        if row is None:
            raise KeyError(f"raw_blob {raw_id} 不存在")
        if not row["path"]:
            raise ValueError(f"raw_blob {raw_id} 只记录了元数据，正文未落盘（超过大小上限）")
        return (self.paths.root / row["path"]).read_bytes()

    def load_text(self, raw_id: int) -> str:
        return self.load_bytes(raw_id).decode("utf-8", errors="replace")

    def is_textual(self, raw_id: int) -> bool:
        row = self.get(raw_id)
        return bool(row) and _looks_textual(row.get("content_type", ""))

    def recent(self, limit: int = 50, *, source: str | None = None) -> list[dict[str, Any]]:
        if source:
            rows = self.db.query(
                "SELECT * FROM raw_blobs WHERE source = ? ORDER BY collected_at DESC LIMIT ?",
                (source, limit),
            )
        else:
            rows = self.db.query("SELECT * FROM raw_blobs ORDER BY collected_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        return {
            "count": self.db.scalar("SELECT COUNT(*) FROM raw_blobs", default=0),
            "bytes": self.db.scalar("SELECT COALESCE(SUM(byte_size),0) FROM raw_blobs", default=0),
            "metadata_only": self.db.scalar(
                "SELECT COUNT(*) FROM raw_blobs WHERE path = ''", default=0
            ),
            "today": self.db.scalar(
                "SELECT COUNT(*) FROM raw_blobs WHERE collected_at >= ?",
                (iso()[:10] + "T00:00:00Z",),
                default=0,
            ),
        }

    # ── 清理 ────────────────────────────────────────────────

    _STATIC_WHERE = (
        "(content_type LIKE '%javascript%' OR content_type LIKE '%ecmascript%' "
        "OR content_type LIKE 'text/css%' OR content_type LIKE 'image/%' "
        "OR content_type LIKE '%font%' OR content_type LIKE '%octet-stream%')"
    )

    def static_stats(self) -> dict[str, Any]:
        return {
            "blobs": self.db.scalar(
                f"SELECT COUNT(*) FROM raw_blobs WHERE {self._STATIC_WHERE}", default=0
            ),
            "bytes": self.db.scalar(
                f"SELECT COALESCE(SUM(byte_size),0) FROM raw_blobs WHERE {self._STATIC_WHERE}",
                default=0,
            ),
        }

    def prune_static(self, *, dry_run: bool = False) -> dict[str, Any]:
        """删掉归档里的静态资源（JS/CSS/图片/字体）。

        早期版本会把页面上几百个 JS/CSS 也归档下来，一天涨几个 GB，
        而且真正要看的数据接口会被淹没。这个命令用来清理历史遗留。
        **只删静态资源，数据接口的归档一律不碰。**
        """
        rows = self.db.query(
            f"SELECT id, path, byte_size FROM raw_blobs WHERE {self._STATIC_WHERE}"
        )
        freed = 0
        removed_files = 0
        for row in rows:
            rel = row["path"]
            if rel:
                try:
                    target = self.paths.root / rel
                    if target.is_file():
                        if not dry_run:
                            target.unlink()
                        removed_files += 1
                except Exception:
                    pass
            freed += int(row["byte_size"] or 0)
        ids = [int(r["id"]) for r in rows]
        if ids and not dry_run:
            self.db.execute_many("DELETE FROM raw_blobs WHERE id = ?", [(i,) for i in ids])
        return {
            "dry_run": dry_run,
            "blobs": len(ids),
            "files_unlinked": removed_files,
            "bytes_freed": freed,
        }
