"""联网工具：网页读取（web_fetch）与联网搜索（web_search）。

沿用项目哲学：零新增依赖（标准库 urllib），阻塞请求放线程里跑。
搜索需要配置供应商与 Key（tavily / bocha），未配置时给出清晰指引而不是报错。
"""
from __future__ import annotations

import asyncio
import json
import re
import urllib.error
import urllib.request
from html import unescape

from .registry import ToolSpec, register

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
FETCH_LIMIT = 7000


def _http_get(url: str, timeout: float = 25) -> tuple[int, bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept-Language": "zh-CN,zh;q=0.9"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read(), response.headers.get("Content-Type", "")


def _http_post_json(url: str, payload: dict, headers: dict, timeout: float = 30) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": USER_AGENT, **headers})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _html_to_text(html: str, limit: int = FETCH_LIMIT) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|template|svg|head)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()[:limit]


async def _fetch(ctx, args: dict) -> dict:
    url = str(args.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return {"ok": False, "summary": "链接必须以 http:// 或 https:// 开头"}
    try:
        status, body, content_type = await asyncio.to_thread(_http_get, url)
    except Exception as exc:
        return {"ok": False, "summary": f"读取失败：{type(exc).__name__}：{str(exc)[:140]}"}
    charset = "utf-8"
    match = re.search(r"charset=([\w-]+)", content_type, re.I)
    if match:
        charset = match.group(1)
    text = body.decode(charset, errors="replace")
    if "html" in content_type.lower() or text.lstrip().startswith("<"):
        readable = _html_to_text(text)
    else:
        readable = text.strip()[:FETCH_LIMIT]
    if not readable:
        return {"ok": False, "summary": f"页面没有可读文本（HTTP {status}）"}
    return {"ok": True, "summary": f"已读取网页（{len(readable)} 字）", "content": readable}


async def _search(ctx, args: dict) -> dict:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"ok": False, "summary": "缺少搜索关键词"}
    count = max(1, min(10, int(args.get("count") or 6)))
    cfg = getattr(ctx.config, "search", None)
    provider = (getattr(cfg, "provider", "") or "").strip().lower()
    api_key = (getattr(cfg, "api_key", "") or "").strip()
    if not provider or not api_key:
        return {"ok": False, "summary": "尚未配置联网搜索：请填写配置的 search.provider（tavily 或 bocha）"
                                        "与 search.api_key 后重试；也可以先用 web_fetch 直接读取某个网页。"}
    try:
        if provider == "tavily":
            data = await asyncio.to_thread(
                _http_post_json, "https://api.tavily.com/search",
                {"query": query, "max_results": count, "search_depth": "basic"},
                {"Authorization": f"Bearer {api_key}"})
            hits = [{"title": item.get("title", ""), "url": item.get("url", ""),
                     "snippet": (item.get("content") or "")[:300]}
                    for item in (data.get("results") or [])]
        elif provider == "bocha":
            data = await asyncio.to_thread(
                _http_post_json, "https://api.bochaai.com/v1/web-search",
                {"query": query, "count": count, "summary": True},
                {"Authorization": f"Bearer {api_key}"})
            pages = (((data.get("data") or {}).get("webPages") or {}).get("value")) or []
            hits = [{"title": item.get("name", ""), "url": item.get("url", ""),
                     "snippet": (item.get("summary") or item.get("snippet") or "")[:300]}
                    for item in pages]
        else:
            return {"ok": False, "summary": f"不认识搜索供应商 {provider}（支持 tavily / bocha）"}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "summary": f"搜索服务返回 HTTP {exc.code}（检查 Key 是否有效）"}
    except Exception as exc:
        return {"ok": False, "summary": f"搜索失败：{type(exc).__name__}：{str(exc)[:140]}"}
    if not hits:
        return {"ok": True, "summary": f"搜索「{query}」没有找到结果", "content": "（没有搜索结果）"}
    lines = [f"{idx}. {hit['title']}  {hit['url']}\n   {hit['snippet']}" for idx, hit in enumerate(hits, 1)]
    return {"ok": True, "summary": f"搜索「{query}」找到 {len(hits)} 条结果", "content": "\n".join(lines)}


register(ToolSpec(
    id="web_fetch", name="网页读取",
    description="读取一个公开网页的正文内容。需要查看某个具体链接里写了什么时使用。",
    parameters={"type": "object",
                "properties": {"url": {"type": "string", "description": "完整网址（http/https）"}},
                "required": ["url"]},
    handler=_fetch))

register(ToolSpec(
    id="web_search", name="联网搜索",
    description="联网搜索实时信息（新闻、热点、资料）。需要了解最新信息或不知道具体网址时使用。",
    parameters={"type": "object",
                "properties": {"query": {"type": "string", "description": "搜索关键词"},
                               "count": {"type": "integer", "description": "结果数量 1-10，默认 6"}},
                "required": ["query"]},
    handler=_search))
