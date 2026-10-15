"""采集类工具：数据管家的「真干活」入口（登录抖音 / 开始采集）。

这些操作会动用用户的浏览器和抖音账号，全部是 confirm 级：
调用前在对话里出现确认卡，用户点允许后才执行。
执行期间的长任务进度通过 ctx.tool_emit 上报（由对话循环注入的一次性回调，
见 analyze/conversation.py）；没有则静默。操作本体复用桌面按钮同一条链路
（desktop.actions），避免出现两份采集逻辑。
"""
from __future__ import annotations

from .registry import ToolSpec, register

KINDS_TEXT = {"quick", "deep"}


def _emit_of(ctx):
    emit = getattr(ctx, "tool_emit", None)
    return emit if callable(emit) else (lambda event: None)


async def _login(ctx, args: dict) -> dict:
    from ..desktop import actions  # 延迟导入：避免 tools 与 desktop 在模块层互相牵连

    timeout = int(args.get("timeout_s") or 300)
    timeout = max(60, min(600, timeout))
    try:
        result = await actions.login(ctx, _emit_of(ctx), timeout=timeout)
    except ValueError as exc:
        return {"ok": False, "summary": str(exc)}
    except TimeoutError as exc:
        return {"ok": False, "summary": str(exc)}
    return {"ok": True, "summary": str(result.get("message") or "登录完成")}


async def _collect(ctx, args: dict) -> dict:
    from ..desktop import actions

    kinds = str(args.get("kinds") or "quick").strip().lower()
    if kinds not in KINDS_TEXT:
        return {"ok": False, "summary": "kinds 只能是 quick 或 deep"}
    limit = int(args.get("limit") or 40)
    limit = max(5, min(200, limit))
    options = {"kinds": kinds, "limit": limit, "force": bool(args.get("force"))}
    try:
        result = await actions.collect(ctx, _emit_of(ctx), options)
    except ValueError as exc:
        return {"ok": False, "summary": str(exc)}
    return {"ok": True, "summary": str(result.get("message") or "采集结束")}


register(ToolSpec(
    id="collect_login", name="登录抖音",
    description="打开浏览器引导用户扫码登录抖音，登录态会保存，之后采集和查数据都用它。"
                "当数据概览显示尚未识别账号、或采集提示登录态失效时使用。执行前会先让用户确认。",
    parameters={"type": "object",
                "properties": {"timeout_s": {"type": "integer",
                                             "description": "等待扫码的秒数，60-600，默认 300"}}},
    agents=("data",), level="confirm",
    handler=_login))

register(ToolSpec(
    id="collect_start", name="开始采集",
    description="启动一轮真实采集：从抖音取回账号数据（点赞与互动者、作品），清洗入库。"
                "耗时可达几分钟，过程中进度会实时显示。需要已有登录态；执行前会先让用户确认。",
    parameters={"type": "object",
                "properties": {"kinds": {"type": "string", "enum": ["quick", "deep"],
                                         "description": "quick=快速（默认）｜deep=深度（补充资料）"},
                               "limit": {"type": "integer",
                                         "description": "本轮最多处理多少个任务，5-200，默认 40"},
                               "force": {"type": "boolean",
                                         "description": "true=忽略缓存强制重采，默认 false"}}},
    agents=("data",), level="confirm",
    handler=_collect))
