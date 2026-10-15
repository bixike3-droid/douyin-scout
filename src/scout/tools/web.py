"""联网工具：网页读取（web_fetch）与联网搜索（web_search）。

沿用项目哲学：零新增依赖（标准库 urllib），阻塞请求放线程里跑。
搜索默认走 DeepSeek 服务端搜索（复用 llm.api_key、免申请搜索 Key、按量计费）；
也可切到 tavily / bocha 第三方；没有任何可用 Key 时给出清晰指引而不是报错。
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
DEEPSEEK_SEARCH_MAX_TOKENS = 4096
DEEPSEEK_SEARCH_MAX_USES = 5
DEEPSEEK_SEARCH_TIMEOUT = 90


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


def _deepseek_search(config, query: str, count: int) -> dict:
    """DeepSeek 服务端搜索：Anthropic 兼容端点 + 原生 web_search 工具（与官方 dsh 同路线）。

    复用 llm.api_key，搜索在 DeepSeek 服务器上执行、按量计费；结果里除结构化
    来源块外还有一段模型摘要。同步函数，放线程里跑。
    """
    llm = getattr(config, "llm", None)
    search = getattr(config, "search", None)
    api_key = (getattr(llm, "api_key", "") or "").strip()
    model = (getattr(search, "model", "") or "").strip() or "deepseek-v4-flash"
    base = (getattr(search, "base_url", "") or "").strip()
    if not base:
        llm_base = (getattr(llm, "base_url", "") or "https://api.deepseek.com").strip()
        base = llm_base.rstrip("/") + "/anthropic/v1"
    payload = {
        "model": model,
        "max_tokens": DEEPSEEK_SEARCH_MAX_TOKENS,
        "messages": [{"role": "user",
                      "content": [{"type": "text",
                                   "text": f"Perform a web search for the query: {query}"}]}],
        "tools": [{"type": "web_search_20250305", "name": "web_search",
                   "max_uses": DEEPSEEK_SEARCH_MAX_USES}],
    }
    data = _http_post_json(base.rstrip("/") + "/messages", payload,
                           {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                           timeout=DEEPSEEK_SEARCH_TIMEOUT)

    sources: list[dict[str, str]] = []
    answer_parts: list[str] = []
    for block in data.get("content") or []:
        kind = block.get("type")
        if kind == "web_search_tool_result":
            items = block.get("content")
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and item.get("type") == "web_search_result":
                        sources.append({"title": str(item.get("title") or ""),
                                        "url": str(item.get("url") or "")})
        elif kind == "text":
            text = str(block.get("text") or "").strip()
            if text:
                answer_parts.append(text)
    sources = sources[:count]
    answer = "\n".join(answer_parts).strip()
    if not sources and not answer:
        return {"ok": False, "summary": "DeepSeek 服务端搜索没有返回结果，换个说法或稍后再试"}
    lines: list[str] = []
    if answer:
        lines.append(answer)
    if sources:
        if lines:
            lines.append("")
        lines.append("来源：")
        for index, item in enumerate(sources, 1):
            lines.append(f"{index}. {item['title']}\n   {item['url']}")
    return {"ok": True,
            "summary": f"搜索「{query}」找到 {len(sources)} 条结果（DeepSeek 服务端搜索）",
            "content": "\n".join(lines)}


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
    llm = getattr(ctx.config, "llm", None)
    llm_key = (getattr(llm, "api_key", "") or "").strip()

    if provider in ("off", "none", "disabled"):
        return {"ok": False, "summary": "联网搜索已在配置中关闭（search.provider = off）"}

    if provider in ("", "deepseek"):
        # 默认模式：复用 DeepSeek Key 走服务端搜索，零额外配置
        if not llm_key:
            return {"ok": False, "summary": "尚未配置联网搜索：请填写配置的 search.provider（deepseek，免申请、"
                                            "复用 DeepSeek Key；或用 tavily / bocha + search.api_key）后重试；"
                                            "也可以先用 web_fetch 直接读取某个网页。"}
        try:
            return await asyncio.to_thread(_deepseek_search, ctx.config, query, count)
        except urllib.error.HTTPError as exc:
            return {"ok": False, "summary": f"搜索失败（DeepSeek 服务端）：HTTP {exc.code}，检查 DeepSeek Key 与额度"}
        except Exception as exc:
            return {"ok": False, "summary": f"搜索失败（DeepSeek 服务端）：{type(exc).__name__}：{str(exc)[:140]}"}

    if provider not in ("tavily", "bocha"):
        return {"ok": False, "summary": f"不认识搜索供应商 {provider}（支持 deepseek / tavily / bocha / off）"}
    if not api_key:
        return {"ok": False, "summary": f"搜索供应商 {provider} 需要配置 search.api_key"}

    try:
        if provider == "tavily":
            data = await asyncio.to_thread(
                _http_post_json, "https://api.tavily.com/search",
                {"query": query, "max_results": count, "search_depth": "basic"},
                {"Authorization": f"Bearer {api_key}"})
            hits = [{"title": item.get("title", ""), "url": item.get("url", ""),
                     "snippet": (item.get("content") or "")[:300]}
                    for item in (data.get("results") or [])]
        else:  # bocha
            data = await asyncio.to_thread(
                _http_post_json, "https://api.bochaai.com/v1/web-search",
                {"query": query, "count": count, "summary": True},
                {"Authorization": f"Bearer {api_key}"})
            pages = (((data.get("data") or {}).get("webPages") or {}).get("value")) or []
            hits = [{"title": item.get("name", ""), "url": item.get("url", ""),
                     "snippet": (item.get("summary") or item.get("snippet") or "")[:300]}
                    for item in pages]
    except urllib.error.HTTPError as exc:
        return {"ok": False, "summary": f"搜索失败（{provider}）：HTTP {exc.code}（检查 Key 是否有效）"}
    except Exception as exc:
        return {"ok": False, "summary": f"搜索失败（{provider}）：{type(exc).__name__}：{str(exc)[:140]}"}
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
