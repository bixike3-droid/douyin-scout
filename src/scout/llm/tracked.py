"""Record every provider call, including routing, repair, summaries and delegation."""
import asyncio
import hashlib
import json
import time

from ..util import iso


class TrackedClient:
    def __init__(self, client, db, conversation_id, purpose="chat", run_ref="", max_calls=None):
        self.client, self.db, self.conversation_id = client, db, conversation_id
        self.purpose, self.run_ref = purpose, run_ref
        self.max_calls = max_calls

    def scoped(self, purpose, run_ref=None, max_calls=None):
        return TrackedClient(self.client, self.db, self.conversation_id, purpose,
                             self.run_ref if run_ref is None else run_ref,
                             self.max_calls if max_calls is None else max_calls)

    async def chat(self, system, user, **kwargs):
        return await self._call("chat", system, user, **kwargs)

    async def chat_messages(self, system, messages, **kwargs):
        return await self._call("chat_messages", system, messages, **kwargs)

    async def _call(self, method, system, body, **kwargs):
        if self.max_calls is not None and self.run_ref.startswith("chat:"):
            from ..store.chat import ChatRuns
            runs = ChatRuns(self.db)
            run_id = int(self.run_ref.split(":", 1)[1])
            run = runs.get(run_id)
            if run["model_calls"] >= self.max_calls:
                raise ValueError("本次模型调用次数已达上限")
            runs.update(run_id, model_calls=run["model_calls"] + 1)
        started, reply, status = time.monotonic(), None, "failed"
        digest = lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()
        payload = json.dumps({"system": system, "body": body,
                              "options": {k: v for k, v in kwargs.items() if k not in ("on_delta", "stop_event")}},
                             ensure_ascii=False, sort_keys=True)
        try:
            reply = await getattr(self.client, method)(system, body, **kwargs)
            status = "complete"
            return reply
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        finally:
            self.db.execute(
                "INSERT INTO model_calls(conversation_id,run_ref,purpose,prompt_version,input_digest,"
                "model,prompt_tokens,completion_tokens,duration_ms,retries,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (self.conversation_id, self.run_ref, self.purpose, digest(system), digest(payload),
                 reply.model if reply else "", reply.prompt_tokens if reply else 0,
                 reply.completion_tokens if reply else 0,
                 reply.duration_ms if reply and reply.duration_ms else int((time.monotonic() - started) * 1000),
                 reply.retries if reply else 0, status, iso()))
