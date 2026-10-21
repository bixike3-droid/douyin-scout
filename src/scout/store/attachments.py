"""Account-local immutable originals and conversation-scoped attachment evidence."""
import json

from ..util import iso


class Attachments:
    def __init__(self, db):
        self.db = db

    def add(self, item, conversation_id):
        self.db.execute(
            "INSERT INTO attachments(id,conversation_id,name,kind,size,digest,relative_path,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (item["id"], conversation_id, item["name"], item["kind"], item["size"], item["digest"], item["relative_path"], iso()))

    def extracted(self, attachment_id, *, text="", visuals=(), limitations="", status="ready"):
        self.db.execute("UPDATE attachments SET text_content=?,visuals_json=?,limitations=?,status=? WHERE id=?",
                        (text, json.dumps(list(visuals), ensure_ascii=False), limitations, status, attachment_id))

    def analysis(self, attachment_id, text, *, status="ready"):
        self.db.execute("UPDATE attachments SET analysis=?,status=? WHERE id=?", (text, status, attachment_id))

    def add_limitation(self, attachment_id, text):
        self.db.execute("UPDATE attachments SET limitations=limitations || ? WHERE id=?", (text, attachment_id))

    def bind(self, ids, conversation_id, message_id):
        if not ids:
            return
        with self.db.transaction():
            message = self.db.query_one("SELECT conversation_id FROM conversation_messages WHERE id=?", (message_id,))
            if not message or message[0] != conversation_id:
                raise ValueError("附件消息不属于当前会话")
            for attachment_id in ids:
                row = self.db.query_one("SELECT conversation_id,message_id FROM attachments WHERE id=?", (attachment_id,))
                if not row or row["conversation_id"] != conversation_id or row["message_id"] not in (None, message_id):
                    raise ValueError("附件不属于当前消息")
                self.db.execute("UPDATE attachments SET message_id=? WHERE id=?", (message_id, attachment_id))

    def list(self, conversation_id, message_id=None):
        sql = "SELECT * FROM attachments WHERE conversation_id=?"
        params = [conversation_id]
        if message_id is not None:
            sql += " AND message_id=?"
            params.append(message_id)
        rows = self.db.rows_as_dicts(sql + " ORDER BY created_at,id", params)
        for row in rows:
            row["visuals"] = json.loads(row.pop("visuals_json"))
        return rows

    def get(self, attachment_id, conversation_id):
        return next((a for a in self.list(conversation_id) if a["id"] == attachment_id), None)

    @staticmethod
    def context(items, per_file=3500):
        parts = []
        for item in items:
            body = "\n".join(part for part in (("模型识别结果（仅针对所提供的画面，可能有误）：\n" + item["analysis"]) if item.get("analysis") else "", item.get("text_content")) if part)
            if len(body) > per_file:
                body = body[:per_file] + "\n（附件正文已截断，可用 attachment_read 按位置继续读取）"
            parts.append(f"[F{item['id']}] {item['name']} · {item['kind']} · {item['status']}\n{body}\n范围与限制：{item.get('limitations') or '用户上传资料，未经独立核实'}")
        return "\n\n".join(parts)
