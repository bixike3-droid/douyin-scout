"""Persistent conversation turns, with failed/cancelled calls distinguished."""
from ..util import iso


class Conversations:
    def __init__(self, db):
        self.db = db

    def create(self, title):
        now = iso()
        cur = self.db.conn.execute("INSERT INTO conversations(title,created_at,updated_at) VALUES(?,?,?)", (title[:80], now, now))
        return cur.lastrowid

    def get(self, conversation_id):
        row = self.db.query_one("SELECT * FROM conversations WHERE id=?", (conversation_id,))
        if not row:
            raise ValueError("对话不存在")
        data = dict(row)
        data["messages"] = self.db.rows_as_dicts("SELECT * FROM conversation_messages WHERE conversation_id=? ORDER BY id", (conversation_id,))
        return data

    def recent(self):
        return self.db.rows_as_dicts("SELECT id,title,created_at,updated_at,report_id FROM conversations ORDER BY updated_at DESC,id DESC LIMIT 100")

    def add(self, conversation_id, role, content, *, status="complete", reply=None, input_json="{}", reasoning=""):
        self.get(conversation_id)
        cur = self.db.conn.execute("INSERT INTO conversation_messages(conversation_id,role,content,status,created_at,model,prompt_tokens,completion_tokens,duration_ms,input_json,reasoning) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (conversation_id, role, content, status, iso(), reply.model if reply else "",
             reply.prompt_tokens if reply else 0, reply.completion_tokens if reply else 0,
             reply.duration_ms if reply else 0, input_json, reasoning))
        self.db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (iso(), conversation_id))
        return cur.lastrowid

    def history(self, conversation_id):
        messages = [m for m in self.get(conversation_id)["messages"] if m["status"] == "complete" and m["role"] in ("user", "assistant")]
        result, length = [], 0
        for message in reversed(messages[-20:]):
            content = message["content"][:4000]
            if length + len(content) > 16000:
                break
            result.append({"role": message["role"], "content": content})
            length += len(content)
        return list(reversed(result))
