"""Persist each file's thumbnail, overview and detailed inspection independently."""
import json


class AssetStore:
    def __init__(self, db):
        self.db = db

    def index(self, attachment_id, entries):
        self.db.execute_many(
            "INSERT OR IGNORE INTO attachment_assets(attachment_id,asset_id,position,name,kind,size,state,error) VALUES(?,?,?,?,?,?,?,?)",
            [(attachment_id, f"A{index + 1:04d}", index, entry["name"], entry["kind"], entry.get("size"),
              "blocked" if entry.get("blocked") else "directory" if entry.get("directory") else "indexed",
              entry.get("reason", "") if entry.get("blocked") else "") for index, entry in enumerate(entries)])

    def assets(self, attachment_id):
        rows = self.db.rows_as_dicts("SELECT * FROM attachment_assets WHERE attachment_id=? ORDER BY position", (attachment_id,))
        for row in rows:
            row["metadata"] = json.loads(row.pop("metadata_json"))
        return rows

    def get(self, attachment_id, asset_id):
        return next((a for a in self.assets(attachment_id) if a["asset_id"] == asset_id or a["name"] == asset_id), None)

    def update(self, attachment_id, asset_id, **fields):
        allowed = {"source_path", "thumbnail_path", "preview_path", "state", "observation", "detail", "error", "metadata_json"}
        if not fields or set(fields) - allowed:
            raise ValueError("无效附件素材字段")
        self.db.execute("UPDATE attachment_assets SET " + ",".join(f"{k}=?" for k in fields) + " WHERE attachment_id=? AND asset_id=?",
                        (*fields.values(), attachment_id, asset_id))

    def overview(self, attachment_id, batch_id, ids, sheet):
        previous = self.db.query_one("SELECT asset_ids_json FROM attachment_overviews WHERE attachment_id=? AND batch_id=?", (attachment_id, batch_id))
        if previous and json.loads(previous[0]) != ids:
            self.db.execute("UPDATE attachment_overviews SET asset_ids_json=?,sheet_path=?,state='pending' WHERE attachment_id=? AND batch_id=?",
                            (json.dumps(ids), sheet, attachment_id, batch_id))
        else:
            self.db.execute("INSERT OR IGNORE INTO attachment_overviews(attachment_id,batch_id,asset_ids_json,sheet_path) VALUES(?,?,?,?)",
                            (attachment_id, batch_id, json.dumps(ids), sheet))

    def batches(self, attachment_id):
        rows = self.db.rows_as_dicts("SELECT * FROM attachment_overviews WHERE attachment_id=? ORDER BY batch_id", (attachment_id,))
        for row in rows:
            row["asset_ids"] = json.loads(row.pop("asset_ids_json"))
        return rows

    def batch_state(self, attachment_id, batch_id, state, observation="", error=""):
        self.db.execute("UPDATE attachment_overviews SET state=?,observation=?,error=? WHERE attachment_id=? AND batch_id=?",
                        (state, observation, error, attachment_id, batch_id))

    def progress(self, attachment_id):
        conditions = {
            "total": "state<>'directory'", "images": "kind='image'", "videos": "kind='video'",
            "visual_total": "kind IN ('image','video') AND state<>'blocked'",
            "thumbnails": "kind IN ('image','video') AND thumbnail_path<>''",
            "overviewed": "kind IN ('image','video') AND observation<>''",
            "inspected": "kind IN ('image','video') AND detail<>''", "failed": "error<>''",
            "pending": "kind IN ('image','video') AND state<>'blocked' AND observation='' AND error=''"}
        row = self.db.query_one("SELECT " + ",".join(f"COALESCE(SUM(CASE WHEN {value} THEN 1 ELSE 0 END),0) AS {key}" for key, value in conditions.items()) +
                                " FROM attachment_assets WHERE attachment_id=?", (attachment_id,))
        return dict(row)
