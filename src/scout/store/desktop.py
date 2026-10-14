"""Bounded, searchable desktop queries. No GUI dependencies."""
from __future__ import annotations

from typing import Any
from ..db.connect import Database
from .collection import Quality, clean_metrics
from .enterprise import EnterpriseStore

PAGE_SIZE = 100
VIEWS = {
    "works": ("works w", "w.is_mine=1", "w.description", "w.aweme_id", "w.create_time DESC, w.aweme_id"),
    "users": ("users u LEFT JOIN v_audience_quality q ON q.sec_uid=u.sec_uid", "EXISTS (SELECT 1 FROM like_edges le WHERE le.sec_uid=u.sec_uid)",
              "u.nickname", "u.sec_uid", "u.last_seen_at DESC, u.sec_uid"),
    "analyses": ("llm_results r", "NOT EXISTS (SELECT 1 FROM llm_results n WHERE "
                 "n.subject_kind=r.subject_kind AND n.subject_id=r.subject_id AND n.task=r.task "
                 "AND (n.created_at>r.created_at OR (n.created_at=r.created_at AND n.id>r.id)))",
                 "r.input_summary", "r.subject_id", "r.created_at DESC, r.id DESC"),
    "tasks": ("tasks t LEFT JOIN collection_coverage c ON c.kind=t.kind AND c.target=t.target", "1=1", "t.kind", "t.target", "t.updated_at DESC, t.id DESC"),
}


class DesktopStore:
    def __init__(self, db: Database):
        self.db = db

    def overview(self) -> dict[str, Any]:
        return {
            "works": self.db.scalar("SELECT COUNT(*) FROM works WHERE is_mine=1", default=0),
            "users": self.db.scalar("SELECT COUNT(DISTINCT sec_uid) FROM like_edges", default=0),
            "analyses": self.db.scalar("SELECT COUNT(*) FROM llm_results", default=0),
            "pending": self.db.scalar("SELECT COUNT(*) FROM tasks WHERE state='pending'", default=0),
            "self": self.db.query_one("SELECT u.nickname FROM users u JOIN cursor_state c "
                                      "ON c.name='self_sec_uid' AND c.cursor=u.sec_uid"),
            "events": self.db.rows_as_dicts("SELECT ts, level, message FROM event_logs ORDER BY id DESC LIMIT 12"),
            "task_counts": {r["state"]: r["count"] for r in self.db.query("SELECT state, COUNT(*) AS count FROM tasks GROUP BY state")},
            "recent_works": self.db.rows_as_dicts("SELECT description, digg_count, create_time FROM works WHERE is_mine=1 ORDER BY create_time DESC LIMIT 5"),
            "quality": Quality(self.db).report(),
        }

    def page(self, view: str, search: str = "", page: int = 0, segment: str = "raw") -> dict[str, Any]:
        source, condition, text_column, id_column, ordering = VIEWS[view]
        if view == "users":
            filters = {"raw": "1=1", "active": "q.interaction_works>0", "repeated": "q.interaction_works>=2",
                       "incomplete": "q.interaction_works>0 AND q.data_status='资料待补'",
                       "unsampled": "q.interaction_works>0 AND q.sample_count=0"}
            condition += " AND (" + filters[segment] + ")"
            ordering = "q.interaction_works DESC,u.last_seen_at DESC,u.sec_uid"
        pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where = f"({condition}) AND ({text_column} LIKE ? ESCAPE '\\' OR {id_column} LIKE ? ESCAPE '\\')"
        total = int(self.db.scalar(f"SELECT COUNT(*) FROM {source} WHERE {where}", (pattern, pattern), default=0))
        page = min(max(0, page), max(0, (total - 1) // PAGE_SIZE))
        rows = self.db.rows_as_dicts(
            f"SELECT {'t.*, c.state AS collection_state' if view == 'tasks' else '*'} FROM {source} WHERE {where} ORDER BY {ordering} LIMIT ? OFFSET ?",
            (pattern, pattern, PAGE_SIZE, page * PAGE_SIZE),
        )
        rendered = [EnterpriseStore(self.db).enrich(row) if view == "works" else clean_metrics(row) for row in rows]
        return {"rows": rendered, "total": total, "page": page, "page_size": PAGE_SIZE}
