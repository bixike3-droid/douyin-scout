"""工具注册表：成员"能干什么"的唯一定义处。

- 参数 schema 提供给模型（OpenAI tools 格式）
- 权限（哪些成员可调用哪个工具）在这里声明，执行器再校验一次——模型无法绕过
- 每次调用（含被拒绝的）都写审计表 tool_calls
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..util import iso

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
                  conversation_id: int | None = None) -> dict[str, Any]:
    """执行工具：权限校验 → 执行 → 审计。失败返回 {"ok": False, "summary": ...}，不抛异常。"""
    spec = get(tool_id)
    if spec is None or spec.handler is None:
        return {"ok": False, "summary": f"没有名为 {tool_id} 的工具"}
    if not allows(spec, agent_id):
        _audit(ctx, conversation_id, agent_id, tool_id, args, "denied", "该成员没有此工具权限", 0)
        return {"ok": False, "summary": "当前成员没有调用这个工具的权限"}
    started = time.monotonic()
    try:
        result = await spec.handler(ctx, args or {})
        if not isinstance(result, dict):
            result = {"ok": True, "summary": str(result)}
        result.setdefault("ok", True)
        status = "complete" if result.get("ok") else "failed"
    except Exception as exc:  # noqa: BLE001 —— 工具失败不影响对话，转成模型可读的结果
        result = {"ok": False, "summary": f"工具执行出错：{type(exc).__name__}：{str(exc)[:160]}"}
        status = "failed"
    _audit(ctx, conversation_id, agent_id, tool_id, args, status,
           str(result.get("summary") or "")[:300], int((time.monotonic() - started) * 1000))
    return result


def _audit(ctx, conversation_id, agent_id, tool_id, args, status, summary, duration_ms) -> None:
    try:
        ctx.db.execute(
            "INSERT INTO tool_calls(conversation_id,agent,tool,args_json,status,summary,duration_ms,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (conversation_id, agent_id, tool_id, json.dumps(args or {}, ensure_ascii=False),
             status, summary, duration_ms, iso()))
    except Exception:
        pass  # 审计写入失败不阻断主流程
