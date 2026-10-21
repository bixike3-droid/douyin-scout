"""联网工具：网页读取（web_fetch）与联网搜索（web_search）。

沿用项目哲学：零新增依赖（标准库 urllib），阻塞请求放线程里跑。
网页读取：DeepSeek Fetch API（干净 Markdown）优先，失败回落本地 HTTP；
联网搜索：默认 DeepSeek 服务端搜索，也可选 deepseek_api（原始结果）/tavily/bocha。
正文归档进 raw_blobs，引用可回放核对。
"""
from __future__ import annotations

import asyncio
import http.client
import json
import re
import time
import urllib.error
import urllib.request
from html import unescape

from .registry import ToolSpec, register

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
FETCH_LIMIT = 7000
DEEPSEEK_API_BASE = "https://api.deepseek.com"
DEEPSEEK_FETCH_TIMEOUT = 60
DEEPSEEK_TOOLS_TIMEOUT = 45
DEEPSEEK_API_ATTEMPTS = 3
DEEPSEEK_RETRY_STATUS = {408, 429, 500, 502, 503, 504}
DEEPSEEK_SEARCH_MAX_TOKENS = 4096
DEEPSEEK_SEARCH_MAX_USES = 5
DEEPSEEK_SEARCH_TIMEOUT = 90
# 长响应（10 条结果带加密块可达上百 KB）偶尔会被链路提前断开，失败重试一次
DEEPSEEK_SEARCH_ATTEMPTS = 2
# 服务端搜索工具版本：端点目前支持 web_search_20250305 / web_search_20260209，用最新版
# （实测默认返回约 10 条来源；web_fetch / code_execution 等其他服务端工具不存在）。
DEEPSEEK_SEARCH_TOOL_TYPE = "web_search_20260209"


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


def _deepseek_key(config) -> str:
    """复用大模型 Key；search.api_key 仅作兼容兑底。"""
    llm = getattr(config, "llm", None)
    search = getattr(config, "search", None)
    return ((getattr(llm, "api_key", "") or "").strip()
            or (getattr(search, "api_key", "") or "").strip())


def _deepseek_base(config) -> str:
    llm = getattr(config, "llm", None)
    return (getattr(llm, "base_url", "") or DEEPSEEK_API_BASE).strip().rstrip("/")


def _post_json_retry(url: str, payload: dict, headers: dict, *, timeout: float,
                     attempts: int = DEEPSEEK_API_ATTEMPTS) -> dict:
    """429/5xx 退避重试；其他 4xx 直接抛给调用方判断。"""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return _http_post_json(url, payload, headers, timeout=timeout)
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code in DEEPSEEK_RETRY_STATUS and attempt + 1 < attempts:
                time.sleep(0.8 * (attempt + 1))
                continue
            raise
        except (http.client.IncompleteRead, urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.6 * (attempt + 1))
    raise last_error or RuntimeError("请求失败")


def _deepseek_fetch(config, url: str) -> dict:
    """Fetch API：返回 {title, content(Markdown)}；403/404 由调用方回落本地。"""
    headers = {"Authorization": f"Bearer {_deepseek_key(config)}"}
    return _post_json_retry(f"{_deepseek_base(config)}/v1/tools/fetch", {"url": url}, headers,
                            timeout=DEEPSEEK_FETCH_TIMEOUT)


def _deepseek_search_api(config, query: str, count: int, *, ori_question: str = "") -> list[dict]:
    """Search API：返回原始结构化结果（title/url/summary/date/authority）。"""
    headers = {"Authorization": f"Bearer {_deepseek_key(config)}"}
    payload: dict = {"query": query, "count": count}
    if ori_question:
        payload["ori_question"] = ori_question[:128]
    data = _post_json_retry(f"{_deepseek_base(config)}/v1/tools/search", payload, headers,
                            timeout=DEEPSEEK_TOOLS_TIMEOUT)
    results = data.get("results") if isinstance(data, dict) else None
    return [item for item in results or [] if isinstance(item, dict)]


def _archive_fetch(ctx, url: str, text: str, note: str = "") -> None:
    """归档网页正文，便于回放核对（失败不影响工具结果）。"""
    try:
        ctx.archive.save(text, url=url, tier="", content_type="text/markdown",
                         source="web_fetch", note=note[:80])
    except Exception:  # noqa: BLE001
        pass


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
    model = (getattr(search, "model", "") or "").strip() or "deepseek-flash"
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
        "tools": [{"type": DEEPSEEK_SEARCH_TOOL_TYPE, "name": "web_search",
                   "max_uses": DEEPSEEK_SEARCH_MAX_USES}],
    }
    data = None
    endpoint = base.rstrip("/") + "/messages"
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    last_error: Exception | None = None
    for _attempt in range(DEEPSEEK_SEARCH_ATTEMPTS):
        try:
            data = _http_post_json(endpoint, payload, headers, timeout=DEEPSEEK_SEARCH_TIMEOUT)
            break
        except urllib.error.HTTPError:
            raise
        except (http.client.IncompleteRead, urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            last_error = exc
    if data is None:
        raise last_error or RuntimeError("DeepSeek 服务端搜索失败")

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
    usage = data.get("usage") or {}
    searches = int((usage.get("server_tool_use") or {}).get("web_search_requests") or 0)
    suffix = f"，{searches} 次服务端请求" if searches else ""
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
            "summary": f"搜索「{query}」找到 {len(sources)} 条结果（DeepSeek 服务端搜索{suffix}）",
            "content": "\n".join(lines)}


async def _fetch(ctx, args: dict) -> dict:
    url = str(args.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return {"ok": False, "summary": "链接必须以 http:// 或 https:// 开头"}
    note = ""
    if _deepseek_key(ctx.config):
        try:
            page = await asyncio.to_thread(_deepseek_fetch, ctx.config, url)
            content = str((page or {}).get("content") or "").strip()
            if content:
                body = content[:FETCH_LIMIT]
                title = str((page or {}).get("title") or "").strip()
                _archive_fetch(ctx, url, body, title)
                prefix = f"《{title}》" if title else ""
                return {"ok": True, "summary": f"已读取网页{prefix}（{len(body)} 字，服务端抓取）",
                        "content": body}
            note = "服务端未取得正文，已改用本地读取；"
        except urllib.error.HTTPError as exc:
            note = f"服务端抓取不可用（HTTP {exc.code}），已改用本地读取；"
        except Exception as exc:  # noqa: BLE001 —— 服务端失败一律回落本地
            note = f"服务端抓取失败（{type(exc).__name__}），已改用本地读取；"
    try:
        status, body_bytes, content_type = await asyncio.to_thread(_http_get, url)
    except Exception as exc:
        return {"ok": False, "summary": f"{note}读取失败：{type(exc).__name__}：{str(exc)[:140]}"}
    charset = "utf-8"
    match = re.search(r"charset=([\w-]+)", content_type, re.I)
    if match:
        charset = match.group(1)
    text = body_bytes.decode(charset, errors="replace")
    if "html" in content_type.lower() or text.lstrip().startswith("<"):
        readable = _html_to_text(text)
    else:
        readable = text.strip()[:FETCH_LIMIT]
    if not readable:
        return {"ok": False, "summary": f"{note}页面没有可读文本（HTTP {status}）"}
    _archive_fetch(ctx, url, readable, "本地读取")
    return {"ok": True, "summary": f"{note}已读取网页（{len(readable)} 字，本地）", "content": readable}

def _format_api_results(query: str, results: list[dict]) -> dict:
    if not results:
        return {"ok": True, "summary": f"搜索「{query}」没有找到结果", "content": "（没有搜索结果）"}
    lines = []
    for index, item in enumerate(results, 1):
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        summary = str(item.get("summary") or item.get("snippet") or "").strip()
        summary = re.sub(r"\n{2,}", "\n", summary)[:600]
        meta = []
        date = str(item.get("date") or "")[:10]
        if date:
            meta.append(date)
        authority = item.get("authority")
        if isinstance(authority, int) and authority >= 3:
            meta.append("权威源")
        suffix = f"（{' · '.join(meta)}）" if meta else ""
        lines.append(f"{index}. {title}{suffix}\n   {url}\n   {summary}")
    return {"ok": True, "summary": f"搜索「{query}」找到 {len(results)} 条结果（DeepSeek 搜索 API）",
            "content": "\n".join(lines)}


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

    if provider in ("deepseek_api", "deepseek-api", "search_api"):
        # 原始结构化结果：不做模型摘要，返回 title/url/summary/date/authority
        if not llm_key and not api_key:
            return {"ok": False, "summary": "deepseek_api 搜索需要 DeepSeek Key（复用 llm.api_key）"}
        try:
            results = await asyncio.to_thread(_deepseek_search_api, ctx.config, query, count)
        except urllib.error.HTTPError as exc:
            if exc.code == 402:
                return {"ok": False, "summary": "搜索失败（DeepSeek 搜索 API）：账号余额不足"}
            return {"ok": False, "summary": f"搜索失败（DeepSeek 搜索 API）：HTTP {exc.code}"}
        except Exception as exc:
            return {"ok": False, "summary": f"搜索失败（DeepSeek 搜索 API）：{type(exc).__name__}：{str(exc)[:140]}"}
        return _format_api_results(query, results)

    if provider not in ("tavily", "bocha"):
        return {"ok": False, "summary": f"不认识搜索供应商 {provider}（支持 deepseek / deepseek_api / tavily / bocha / off）"}
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
                "properties": {"url": {"type": "string", "minLength": 1, "maxLength": 4000, "description": "完整网址（http/https）"}},
                "required": ["url"]},
    handler=_fetch))

register(ToolSpec(
    id="web_search", name="联网搜索",
    description="联网搜索实时信息（新闻、热点、资料）。需要了解最新信息或不知道具体网址时使用。",
    parameters={"type": "object",
                "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 2000, "description": "搜索关键词"},
                               "count": {"type": "integer", "minimum": 1, "maximum": 10, "description": "结果数量 1-10，默认 6"}},
                "required": ["query"]},
    handler=_search))
