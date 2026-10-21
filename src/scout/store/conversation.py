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
        from .attachments import Attachments
        attachments = Attachments(self.db).list(conversation_id)
        for message in data["messages"]:
            message["attachments"] = [dict({k: v for k, v in item.items() if k not in ("text_content", "analysis", "visuals")},
                                           preview_relative_path=item["visuals"][0]["path"] if item["visuals"] else "")
                                      for item in attachments if item["message_id"] == message["id"]]
            for metadata in message["attachments"]:
                item = next(a for a in attachments if a["id"] == metadata["id"])
                metadata["preview_text"] = item["text_content"][:12000]
                from .attachment_workspace import AssetStore
                metadata["workspace"] = AssetStore(self.db).progress(item["id"])
        from .workflow import Workflows
        data["workflow"] = Workflows(self.db).latest(conversation_id)
        from .chat import ChatRuns
        data["chat_run"] = ChatRuns(self.db).latest(conversation_id)
        return data

    def recent(self):
        return self.db.rows_as_dicts("SELECT id,title,created_at,updated_at,report_id FROM conversations ORDER BY updated_at DESC,id DESC LIMIT 100")

    def add(self, conversation_id, role, content, *, status="complete", reply=None, input_json="{}", reasoning="", agent=""):
        if not self.db.query_one("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)):
            raise ValueError("对话不存在")
        cur = self.db.conn.execute("INSERT INTO conversation_messages(conversation_id,role,content,status,created_at,model,prompt_tokens,completion_tokens,duration_ms,input_json,reasoning,agent) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (conversation_id, role, content, status, iso(), reply.model if reply else "",
             reply.prompt_tokens if reply else 0, reply.completion_tokens if reply else 0,
             reply.duration_ms if reply else 0, input_json, reasoning, agent))
        self.db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (iso(), conversation_id))
        return cur.lastrowid

    def history(self, conversation_id):
        messages = self.completed(conversation_id)
        result, length = [], 0
        for message in reversed(messages[-20:]):
            content = message["content"][:4000]
            if length + len(content) > 16000:
                break
            result.append({"role": message["role"], "content": content})
            length += len(content)
        return list(reversed(result))

    def completed(self, conversation_id, after_id=0):
        messages = self.db.rows_as_dicts(
            "SELECT id,role,content FROM conversation_messages WHERE conversation_id=? "
            "AND status='complete' AND role IN ('user','assistant') AND id>? ORDER BY id",
            (conversation_id, after_id))
        from .attachments import Attachments
        store = Attachments(self.db)
        attachments = store.list(conversation_id)
        for message in messages:
            evidence = store.context([a for a in attachments if a["message_id"] == message["id"]])
            if evidence:
                message["content"] += "\n\n【用户附件资料】\n" + evidence
        return messages

    def context_history(self, conversation_id):
        """Keep every uncovered message; compaction, rather than a count, owns the boundary."""
        memory = self.memory(conversation_id)
        covered = memory.get("covered_message_id", 0) if memory else 0
        return [{"role": m["role"], "content": m["content"]}
                for m in self.completed(conversation_id, covered)]

    def memory(self, conversation_id):
        """较早对话的压缩摘要；没有则 None。"""
        row = self.db.query_one(
            "SELECT m.summary,m.turns,m.updated_at,COALESCE(p.covered_message_id,0) AS covered_message_id "
            "FROM conversation_memory m LEFT JOIN conversation_memory_progress p USING(conversation_id) "
            "WHERE m.conversation_id=?",
            (conversation_id,))
        return dict(row) if row else None

    def save_memory(self, conversation_id, summary, turns, covered_message_id=0):
        with self.db.transaction():
            current = self.db.scalar("SELECT covered_message_id FROM conversation_memory_progress WHERE conversation_id=?",
                                     (conversation_id,), default=0)
            if current > covered_message_id:
                return
            self.db.execute(
                "INSERT INTO conversation_memory(conversation_id,summary,turns,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(conversation_id) DO UPDATE SET summary=excluded.summary,"
                "turns=excluded.turns,updated_at=excluded.updated_at",
                (conversation_id, summary[:4000], int(turns), iso()))
            self.db.execute(
                "INSERT INTO conversation_memory_progress(conversation_id,covered_message_id) VALUES(?,?) "
                "ON CONFLICT(conversation_id) DO UPDATE SET covered_message_id=excluded.covered_message_id",
                (conversation_id, covered_message_id))
