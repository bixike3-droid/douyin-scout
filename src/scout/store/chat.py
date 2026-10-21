"""Durable ordinary-chat decisions and results, scoped to the account database."""
import json

from ..util import iso


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class ChatRuns:
    def __init__(self, db):
        self.db = db

    def create(self, conversation_id, user_id, agent, account_uid, request, system, messages):
        now = iso()
        cur = self.db.conn.execute(
            "INSERT INTO chat_runs(conversation_id,user_message_id,agent,account_uid,request,system_prompt,"
            "context_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (conversation_id, user_id, agent, account_uid, request, system, encode(messages), now, now))
        return self.get(cur.lastrowid)

    def get(self, run_id):
        row = self.db.query_one("SELECT * FROM chat_runs WHERE id=?", (run_id,))
        if not row:
            raise ValueError("对话任务不存在")
        run = dict(row)
        run["context"] = json.loads(run.pop("context_json"))
        run["calls"] = self.db.rows_as_dicts("SELECT * FROM chat_invocations WHERE run_id=? ORDER BY position", (run_id,))
        for call in run["calls"]:
            result = call.pop("result_json")
            call["result"] = json.loads(result) if result is not None else None
        return run

    def latest(self, conversation_id):
        row = self.db.query_one("SELECT id FROM chat_runs WHERE conversation_id=? ORDER BY id DESC LIMIT 1", (conversation_id,))
        return self.get(row[0]) if row else None

    def update(self, run_id, **fields):
        allowed = {"status", "model_calls", "tool_count", "elapsed_ms", "delegate_calls", "error"}
        if not fields or set(fields) - allowed:
            raise ValueError("无效任务字段")
        fields["updated_at"] = iso()
        self.db.execute("UPDATE chat_runs SET " + ",".join(f"{key}=?" for key in fields) + " WHERE id=?",
                        (*fields.values(), run_id))

    def select(self, run_id, reply):
        """Commit the whole selected batch before any of its tools can run."""
        run = self.get(run_id)
        position = len(run["calls"])
        calls = []
        for index, call in enumerate(reply.tool_calls):
            arguments = call.get("arguments")
            if not isinstance(arguments, str):
                arguments = encode(arguments) if arguments is not None else "{}"
            calls.append({"id": call.get("id") or f"chat_{run_id}_{position + index}",
                          "type": "function", "function": {"name": call.get("name") or "", "arguments": arguments}})
        # Providers should return unique IDs; normalize duplicates for a valid tool transcript.
        used = {call["provider_call_id"] for call in run["calls"]}
        for index, call in enumerate(calls):
            if call["id"] in used:
                call["id"] = f"chat_{run_id}_{position + index}"
            used.add(call["id"])
        context = [*run["context"], {"role": "assistant", "content": reply.text or "", "tool_calls": calls}]
        with self.db.transaction():
            self.db.execute("UPDATE chat_runs SET context_json=?,updated_at=? WHERE id=?", (encode(context), iso(), run_id))
            self.db.execute_many(
                "INSERT INTO chat_invocations(run_id,position,provider_call_id,tool,arguments,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                [(run_id, position + index, call["id"], call["function"]["name"], call["function"]["arguments"], iso(), iso())
                 for index, call in enumerate(calls)])

    def call(self, call_id):
        row = self.db.query_one("SELECT * FROM chat_invocations WHERE id=?", (call_id,))
        if not row:
            raise ValueError("工具执行记录不存在")
        return dict(row)

    def call_state(self, call_id, status, *, result=None, approved=None, expires_at=None):
        fields = {"status": status, "updated_at": iso()}
        if result is not None:
            fields["result_json"] = encode(result)
        if approved is not None:
            fields["approved"] = int(approved)
        if expires_at is not None:
            fields["expires_at"] = expires_at
        self.db.execute("UPDATE chat_invocations SET " + ",".join(f"{key}=?" for key in fields) + " WHERE id=?",
                        (*fields.values(), call_id))

    def messages(self, run_id):
        run = self.get(run_id)
        results = {call["provider_call_id"]: call["result"] for call in run["calls"]}
        messages = []
        for message in run["context"]:
            messages.append(message)
            for call in message.get("tool_calls", []):
                result = results.get(call["id"])
                if result is not None:
                    # Full results stay in SQLite; the context carries a bounded representation.
                    visible = dict(result)
                    visible["content"] = str(visible.get("content") or "")[:4000]
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": encode(visible)})
        return messages
