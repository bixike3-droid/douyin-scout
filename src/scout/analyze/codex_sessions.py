"""Explicit conversation branching and compaction, without modifying the source."""
import asyncio
from dataclasses import replace
import json
import uuid

from ..codex.runtime import server, CodexError
from ..store.conversation import Conversations
from ..store.workflow import WorkflowLease
from ..util import iso


def copy_conversation(ctx, cid, thread_id, session):
    source = Conversations(ctx.db).get(cid)
    with ctx.db.transaction():
        target = Conversations(ctx.db).create(source["title"] + " · 分支")
        messages = {}
        for row in ctx.db.rows_as_dicts("SELECT * FROM conversation_messages WHERE conversation_id=? ORDER BY id", (cid,)):
            old = row.pop("id")
            row["conversation_id"] = target
            cursor = ctx.db.conn.execute("INSERT INTO conversation_messages(" + ",".join(row) + ") VALUES(" + ",".join("?" for _ in row) + ")", tuple(row.values()))
            messages[old] = cursor.lastrowid
        attachment_map = {}
        for row in ctx.db.rows_as_dicts("SELECT * FROM attachments WHERE conversation_id=?", (cid,)):
            old = row["id"]
            row.update(id=uuid.uuid4().hex, conversation_id=target, message_id=messages.get(row["message_id"]))
            attachment_map[old] = row["id"]
            ctx.db.execute("INSERT INTO attachments(" + ",".join(row) + ") VALUES(" + ",".join("?" for _ in row) + ")", tuple(row.values()))
            for table in ("attachment_assets", "attachment_overviews"):
                columns = [r["name"] for r in ctx.db.query(f"PRAGMA table_info({table})") if r["name"] != "attachment_id"]
                cols = ",".join(columns)
                ctx.db.execute(f"INSERT INTO {table}(attachment_id,{cols}) SELECT ?,{cols} FROM {table} WHERE attachment_id=?", (row["id"], old))
        for row in ctx.db.rows_as_dicts("SELECT * FROM workspace_artifacts WHERE conversation_id=?", (cid,)):
            row.pop("id")
            row.update(conversation_id=target, message_id=messages.get(row["message_id"]))
            ctx.db.execute("INSERT INTO workspace_artifacts(" + ",".join(row) + ") VALUES(" + ",".join("?" for _ in row) + ")", tuple(row.values()))
        ctx.db.execute("INSERT INTO conversation_branches(conversation_id,parent_conversation_id,attachment_map_json,created_at) VALUES(?,?,?,?)",
                       (target, cid, json.dumps(attachment_map), iso()))
        ctx.db.execute("INSERT INTO codex_sessions(conversation_id,agent,provider_url,model,thread_id,last_message_id,tools_digest) VALUES(?,?,?,?,?,?,?)",
            (target, session["agent"], session["provider_url"], session["model"], thread_id, max(messages.values(), default=0), session["tools_digest"]))
    return Conversations(ctx.db).get(target)


async def manage(ctx, cid, action, emit):
    Conversations(ctx.db).get(cid)
    session = ctx.db.query_one("SELECT * FROM codex_sessions WHERE conversation_id=? ORDER BY last_message_id DESC LIMIT 1", (cid,))
    if not session:
        raise ValueError("此会话尚未使用 Codex 引擎")
    latest = ctx.db.query_one("SELECT * FROM chat_runs WHERE conversation_id=? ORDER BY id DESC LIMIT 1", (cid,))
    if latest and latest["account_uid"] != (ctx.cursors.get("self_sec_uid") or ""):
        raise ValueError("请切回此会话原来的登录账号")
    if latest and latest["status"] in ("running", "waiting"):
        raise ValueError("请先停止或完成当前任务")
    cfg = replace(ctx.config.llm, model=session["model"], base_url=session["provider_url"])
    with WorkflowLease(ctx.paths.state_dir):
        async with server(ctx.paths, cfg) as rpc:
            if action == "fork":
                emit({"message": "正在从当前对话另开方案…"})
                result = await rpc.request("thread/fork", {"threadId": session["thread_id"], "excludeTurns": True})
                data = copy_conversation(ctx, cid, result["thread"]["id"], session)
                return {"conversation": data, "message": "已另开方案，原会话保留", "report_id": None}
            if action != "compact":
                raise ValueError("未知会话操作")
            await rpc.request("thread/resume", {"threadId": session["thread_id"], "excludeTurns": True})
            emit({"message": "正在整理较早上下文，完整记录保留…"})
            await rpc.request("thread/compact/start", {"threadId": session["thread_id"]})
            while True:
                event = await rpc.events.get()
                if isinstance(event, Exception):
                    raise event
                params = event.get("params", {})
                if params.get("threadId", session["thread_id"]) != session["thread_id"]:
                    continue
                if event.get("method") == "error":
                    raise CodexError(rpc.clean(params))
                if event.get("method") == "item/completed" and params.get("item", {}).get("type") == "contextCompaction":
                    break
                if event.get("method") == "turn/completed":
                    if params["turn"]["status"] != "completed":
                        raise CodexError(rpc.clean(params["turn"].get("error") or "上下文整理未完成"))
                    break
            return {"conversation": Conversations(ctx.db).get(cid), "message": "上下文已整理，完整记录与附件保留", "report_id": None}
