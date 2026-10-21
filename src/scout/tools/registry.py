"""工具注册表：成员"能干什么"的唯一定义处。

- 参数 schema 提供给模型（OpenAI tools 格式）
- 权限（哪些成员可调用哪个工具）在这里声明，执行器再校验一次——模型无法绕过
- 每次调用（含被拒绝的）都写审计表 tool_calls
"""
from __future__ import annotations

import json
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..util import iso
from .validation import parse_arguments

Handler = Callable[[Any, dict], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ToolSpec:
    id: str
    name: str                                # 展示名（界面上给用户看的）
    description: str                         # 给模型看的用途说明
    parameters: dict[str, Any]               # JSON Schema
    agents: tuple[str, ...] = ()             # 允许的成员 id；空元组 = 全部成员
    level: str = "read"                      # read（直接执行）| confirm（下一批接确认流程）
    handler: Handler | None = None


REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> None:
    REGISTRY[spec.id] = spec


def get(tool_id: str) -> ToolSpec | None:
    return REGISTRY.get(tool_id)


def allows(spec: ToolSpec, agent_id: str) -> bool:
    return not spec.agents or agent_id in spec.agents


def specs_for(agent_id: str) -> list[dict[str, Any]]:
    """该成员可用的工具，转成 OpenAI tools 格式。"""
    return [{"type": "function",
             "function": {"name": spec.id, "description": spec.description, "parameters": spec.parameters}}
            for spec in REGISTRY.values() if allows(spec, agent_id)]


def display_name(tool_id: str) -> str:
    spec = get(tool_id)
    return spec.name if spec else tool_id


async def execute(ctx, tool_id: str, agent_id: str, args: dict, *,
                  conversation_id: int | None = None,
                  confirm: Callable[[ToolSpec, str, dict], Awaitable[bool]] | None = None,
                  invocation_id: int | None = None) -> dict[str, Any]:
    """执行工具：权限校验 → （按需）用户确认 → 执行 → 审计。失败返回 {"ok": False, "summary": ...}，不抛异常。"""
    spec = get(tool_id)
    from ..store.chat import ChatRuns
    runs = ChatRuns(ctx.db)
    invocation = runs.call(invocation_id) if invocation_id is not None else None
    if invocation:
        run = runs.get(invocation["run_id"])
        if invocation["tool"] != tool_id or run["agent"] != agent_id or run["conversation_id"] != conversation_id:
            raise ValueError("工具执行记录与当前任务不一致")
        if invocation["result_json"] is not None:
            return json.loads(invocation["result_json"])
        # Reuse only the persisted arguments, never substitute parameters on resume.
        args = invocation["arguments"]

    def finish(result, status, duration_ms=0):
        result.setdefault("ok", True)
        result.setdefault("code", "OK" if result["ok"] else "TOOL_FAILED")
        result.setdefault("retryable", False)
        result.setdefault("partial", False)
        _audit(ctx, conversation_id, agent_id, tool_id, args, status,
               str(result.get("summary") or "")[:300], duration_ms)
        if invocation:
            runs.call_state(invocation_id, status, result=result)
        return result

    if spec is None or spec.handler is None:
        return finish({"ok": False, "code": "UNKNOWN_TOOL", "summary": f"没有名为 {tool_id} 的工具"}, "denied")
    if not allows(spec, agent_id):
        return finish({"ok": False, "code": "PERMISSION_DENIED", "summary": "当前成员没有调用这个工具的权限"}, "denied")
    try:
        args = parse_arguments(args, spec.parameters)
    except ValueError as exc:
        return finish({"ok": False, "code": "INVALID_ARGUMENTS", "summary": str(exc), "retryable": True}, "invalid")
    if invocation and invocation["status"] == "running" and spec.level != "read":
        return finish({"ok": False, "code": "NEEDS_REVIEW", "partial": True,
                       "summary": "上次操作执行中断，是否完成尚不确定。请先核对实际结果，本次没有重复执行。"}, "needs_review")
    if spec.level == "confirm":
        if invocation and invocation["approved"] == 0:
            return finish({"ok": False, "code": "USER_DECLINED", "summary": "用户没有允许这个操作，不要重复发起"}, "declined")
        if invocation and invocation["approved"] == 1 and invocation["expires_at"] and invocation["expires_at"] <= time.time():
            runs.call_state(invocation_id, "declined", approved=False)
            return finish({"ok": False, "code": "USER_DECLINED", "summary": "上次确认已过期，本次没有执行；需要时请重新发起具体操作。"}, "declined")
        if confirm is None and not (invocation and invocation["approved"] == 1):
            return finish({"ok": False, "code": "CONFIRMATION_UNAVAILABLE",
                           "summary": "这个操作需要用户先确认；当前环境没有确认通道，请在源镜桌面工作台里发起"}, "denied")
        try:
            approved = bool(invocation and invocation["approved"] == 1)
            if not approved:
                expires = (invocation["expires_at"] or time.time() + 180) if invocation else time.time() + 180
                if invocation:
                    runs.call_state(invocation_id, "waiting", expires_at=expires)
                    runs.update(invocation["run_id"], status="waiting")
                if expires <= time.time():
                    approved = False
                elif getattr(confirm, "supports_durable", False) and invocation:
                    approved = bool(await confirm(spec, agent_id, args, request_id=f"chat-confirm-{invocation_id}", expires_at=expires))
                else:
                    approved = bool(await confirm(spec, agent_id, args))
                if invocation:
                    runs.call_state(invocation_id, "approved" if approved else "declined", approved=approved)
                    runs.update(invocation["run_id"], status="running")
        except Exception:  # noqa: BLE001 —— 确认通道故障按未允许处理
            approved = False
        if not approved:
            return finish({"ok": False, "code": "USER_DECLINED", "summary": "用户没有允许这个操作，不要重复发起；可以改为说明操作影响，或先问清用户意图"}, "declined")
    started = time.monotonic()
    if invocation:
        runs.call_state(invocation_id, "running")
    try:
        result = await spec.handler(ctx, args or {})
        if not isinstance(result, dict):
            result = {"ok": True, "summary": str(result)}
        result.setdefault("ok", True)
        status = "complete" if result.get("ok") else "failed"
    except asyncio.CancelledError:
        _audit(ctx, conversation_id, agent_id, tool_id, args, "cancelled", "执行中断，结果待核对", int((time.monotonic() - started) * 1000))
        raise
    except Exception as exc:  # noqa: BLE001 —— 工具失败不影响对话，转成模型可读的结果
        detail = str(exc)
        key = getattr(getattr(ctx.config, "llm", None), "api_key", "")
        if key:
            detail = detail.replace(key, "[密钥]")
        uncertain = spec.level != "read"
        result = {"ok": False, "code": "NEEDS_REVIEW" if uncertain else "TOOL_ERROR", "partial": uncertain,
                  "retryable": not uncertain and isinstance(exc, (TimeoutError, ConnectionError)),
                  "summary": ("操作异常中断，请先核对实际结果：" if uncertain else "工具执行出错：") + f"{type(exc).__name__}：{detail[:160]}"}
        status = "needs_review" if uncertain else "failed"
    return finish(result, status, int((time.monotonic() - started) * 1000))


def _audit(ctx, conversation_id, agent_id, tool_id, args, status, summary, duration_ms) -> None:
    try:
        ctx.db.execute(
            "INSERT INTO tool_calls(conversation_id,agent,tool,args_json,status,summary,duration_ms,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (conversation_id, agent_id, tool_id, json.dumps(args or {}, ensure_ascii=False),
             status, summary, duration_ms, iso()))
    except Exception:
        logging.getLogger(__name__).exception("工具审计写入失败 tool=%s", tool_id)
