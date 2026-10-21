"""Search the complete asset index, continue overviews, and inspect originals."""
import json
from .registry import ToolSpec, register
from ..store.attachments import Attachments
from ..store.attachment_workspace import AssetStore
from ..attachment_workspace import ensure_index, build_workspace, overview, inspect_assets
import asyncio


def _item(ctx, args):
    conversation_id = getattr(ctx, "tool_conversation_id", None)
    item = Attachments(ctx.db).get(args["attachment_id"], conversation_id) if conversation_id is not None else None
    if not item:
        raise ValueError("当前会话中不存在这个附件")
    return item


async def _assets(ctx, args):
    item = _item(ctx, args)
    await asyncio.to_thread(ensure_index, ctx, item)
    store = AssetStore(ctx.db)
    assets = [a for a in store.assets(item["id"]) if a["state"] != "directory"]
    query = (args.get("query") or "").casefold()
    if query:
        assets = [a for a in assets if query in (a["asset_id"] + " " + a["name"] + " " + a["observation"] + " " + a["detail"] + " " + a["metadata"].get("text", "")).casefold()]
    if args.get("kind"):
        assets = [a for a in assets if a["kind"] == args["kind"]]
    start, count = args.get("offset", 0), args.get("count", 20)
    page = assets[start:start + count]
    rows = [{"asset_id": a["asset_id"], "name": a["name"], "kind": a["kind"], "state": a["state"],
             "observation": a["observation"], "error": a["error"]} for a in page]
    return {"ok": True, "summary": f"素材索引 {start + 1} 至 {min(start + count, len(assets))} / {len(assets)}",
            "content": json.dumps(rows, ensure_ascii=False),
            "data": {"progress": store.progress(item["id"]), "next_offset": start + len(page), "has_more": start + len(page) < len(assets)}}


async def _overview(ctx, args):
    item = _item(ctx, args)
    client = getattr(ctx, "tool_client", None)
    if client is None:
        return {"ok": False, "summary": "当前无法继续视觉分析"}
    progress = await overview(ctx, client, item, args.get("question") or "建立完整素材概览，并指出值得查看原图的素材", getattr(ctx, "tool_emit", None))
    errors = [b["error"] for b in AssetStore(ctx.db).batches(item["id"]) if b["error"]]
    return {"ok": not errors, "code": "VISION_PROVIDER_ERROR" if errors else "OK", "partial": progress["pending"] > 0 or progress["failed"] > 0,
            "summary": f"缩略图 {progress['thumbnails']}/{progress['visual_total']}，总览 {progress['overviewed']}/{progress['visual_total']}，细看 {progress['inspected']}，失败 {progress['failed']}",
            "content": Attachments(ctx.db).get(item["id"], item["conversation_id"])["text_content"], "data": progress}


async def _inspect(ctx, args):
    item = _item(ctx, args)
    client = getattr(ctx, "tool_client", None)
    if client is None:
        return {"ok": False, "summary": "当前无法检查原图"}
    result = await inspect_assets(ctx, client, item, args["asset_ids"], args["question"], crop=args.get("crop"), times=args.get("times"))
    return {"ok": True, "summary": f"已细看 {len(result)} 项素材", "content": json.dumps(result, ensure_ascii=False),
            "data": AssetStore(ctx.db).progress(item["id"])}


COMMON = {"attachment_id": {"type": "string", "minLength": 1}}
register(ToolSpec(id="attachment_assets", name="查找全部素材", description="完整素材目录与缩略图观察索引。按文件名、画面描述关键词、类型检索；offset/count 只是分页，可一直继续。每项有稳定 asset_id，供查看原图。",
 parameters={"type": "object", "properties": {**COMMON, "query": {"type": "string"}, "kind": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}, "count": {"type": "integer", "minimum": 1}}, "required": ["attachment_id"]}, handler=_assets))
register(ToolSpec(id="attachment_overview", name="继续浏览素材总览", description="建立全部素材缩略图联系表，逐批浏览所有未完成格子；复用已完成批次，中断后可以继续；总览不等于原图细读。",
 parameters={"type": "object", "properties": {**COMMON, "question": {"type": "string"}}, "required": ["attachment_id"]}, handler=_overview))
register(ToolSpec(id="attachment_inspect", name="查看原图与视频帧", description="按 asset_ids 查看原图，或指定视频时间点。crop=[left,top,right,bottom] 为0到1的区域，便于放大细节；times 为视频秒数列表，可继续请求其他时间点。不会把缩略图总览冒充完整视频或音轨。",
 parameters={"type": "object", "properties": {**COMMON, "asset_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1}, "question": {"type": "string", "minLength": 1}, "crop": {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1}, "minItems": 4, "maxItems": 4}, "times": {"type": "array", "items": {"type": "number", "minimum": 0}, "minItems": 1}}, "required": ["attachment_id", "asset_ids", "question"]}, handler=_inspect))
