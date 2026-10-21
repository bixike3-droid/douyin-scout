"""大模型客户端。

只依赖标准库：HTTP 用 urllib 放在工作线程里跑，不引入 httpx/aiohttp。
理由：这是长期项目，少一个依赖少一处维护；而且这个调用量（几十次/天）
根本不需要连接池复用。

DeepSeek 兼容 OpenAI 的 /chat/completions 协议，所以换供应商只要改 base_url。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from ..config import LLMConfig

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    def __init__(self, message: str, *, no_retry: bool = False):
        super().__init__(message)
        # 已经产生过输出（或用户已取消）时不再重试：重试会让界面收到重复内容。
        self.no_retry = no_retry


@dataclass
class LLMReply:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: int = 0
    retries: int = 0
    reasoning: str = ""
    reasoning_tokens: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    # 硬盘前缀缓存命中情况：命中部分按约 1/50 计价
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def _post_json(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    """同步 POST。会被放到线程里执行。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            pass
        raise LLMError(f"HTTP {exc.code}：{detail or exc.reason}") from None
    except Exception as exc:
        raise LLMError(f"请求失败：{exc}") from None
    try:
        return json.loads(body)
    except Exception as exc:
        raise LLMError(f"响应不是 JSON：{body[:200]}") from None


def _reasoning_tokens(usage: dict) -> int:
    details = usage.get("completion_tokens_details") or {}
    return int(details.get("reasoning_tokens") or 0)


def _cache_tokens(usage: dict) -> tuple[int, int]:
    return (int(usage.get("prompt_cache_hit_tokens") or 0),
            int(usage.get("prompt_cache_miss_tokens") or 0))


def _post_stream(
    url: str,
    payload: dict,
    headers: dict,
    timeout: float,
    on_delta: Callable[[str, str], None],
    stop_event: threading.Event | None = None,
) -> dict:
    """同步流式 POST（SSE 增量），在工作线程里跑；逐段回调 on_delta(kind, text)。

    kind 为 "reasoning"（思维链）或 "content"（正式回答）。
    stop_event 置位后尽快中断读取并关闭连接（用户取消）。
    已经产生输出之后失败会带上 no_retry 标记，避免重试导致界面内容重复。
    """
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    reasoning: list[str] = []
    content: list[str] = []
    calls: dict[int, dict] = {}
    usage: dict = {}
    model = ""
    produced = False
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                if stop_event is not None and stop_event.is_set():
                    raise LLMError("已取消", no_retry=True)
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    obj = json.loads(chunk)
                except ValueError:
                    continue
                model = obj.get("model") or model
                if obj.get("usage"):
                    usage = obj["usage"]
                delta = ((obj.get("choices") or [{}])[0].get("delta")) or {}
                piece = delta.get("reasoning_content")
                if piece:
                    produced = True
                    reasoning.append(piece)
                    on_delta("reasoning", piece)
                piece = delta.get("content")
                if piece:
                    produced = True
                    content.append(piece)
                    on_delta("content", piece)
                for call in delta.get("tool_calls") or []:
                    # 流式工具调用：参数按 index 分片拼装（与 OpenAI 协议一致）。
                    index = int(call.get("index") or 0)
                    slot = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if call.get("id"):
                        slot["id"] = str(call["id"])
                    function = call.get("function") or {}
                    if function.get("name"):
                        slot["name"] = str(function["name"])
                    if function.get("arguments"):
                        slot["arguments"] += str(function["arguments"])
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            pass
        raise LLMError(f"HTTP {exc.code}：{detail or exc.reason}", no_retry=produced) from None
    except LLMError:
        raise
    except Exception as exc:
        raise LLMError(f"请求失败：{exc}", no_retry=produced) from None
    return {"reasoning": "".join(reasoning), "content": "".join(content), "usage": usage, "model": model,
            "tool_calls": [calls[index] for index in sorted(calls)]}


class DeepSeekClient:
    """极简客户端：一个 chat 方法，够用。"""

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        if not cfg.api_key:
            raise LLMError(
                "没有配置 api_key。请在 config/llm.local.yaml 里填 llm.api_key"
            )

    @property
    def endpoint(self) -> str:
        return self.cfg.base_url.rstrip("/") + "/chat/completions"

    def for_vision(self):
        from urllib.parse import urlparse
        configured = getattr(self.cfg, "vision_model", "")
        model = configured or ("deepseek-flash" if urlparse(self.cfg.base_url).hostname == "api.deepseek.com" else self.cfg.model)
        return self if model == self.cfg.model else DeepSeekClient(replace(self.cfg, model=model))

    async def chat(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = True,
        temperature: float | None = None,
        max_tokens: int = 2000,
        history: list[dict[str, str]] | None = None,
        thinking: bool = False,
        effort: str | None = None,
        on_delta: Callable[[str, str], None] | None = None,
        stop_event: threading.Event | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMReply:
        """一次对话调用（单轮 user 消息的便捷写法），详见 chat_messages。"""
        return await self.chat_messages(
            system,
            [*(history or []), {"role": "user", "content": user}],
            json_mode=json_mode, temperature=temperature, max_tokens=max_tokens,
            thinking=thinking, effort=effort, on_delta=on_delta, stop_event=stop_event, tools=tools)

    async def chat_messages(
        self,
        system: str,
        messages: list[dict[str, Any]],
        *,
        json_mode: bool = True,
        temperature: float | None = None,
        max_tokens: int = 2000,
        thinking: bool = False,
        effort: str | None = None,
        on_delta: Callable[[str, str], None] | None = None,
        stop_event: threading.Event | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMReply:
        """多轮对话调用（支持 tool 消息与 function calling）。

        - thinking=True 请求思维链（DeepSeek thinking 模式，返回 reasoning_content）。
        - effort 控制思考强度（low / high / max），默认取配置里的 reasoning_effort。
        - on_delta 非空时用流式：每段增量回调 on_delta(kind, text)，
          kind 为 "reasoning"（思维链）或 "content"（正式回答）。
        - tools 非空时携带工具定义；模型可能返回 tool_calls（流式同样支持）。
        - json_mode 与 tools 不同时使用（response_format 与工具调用互斥）。
        - stop_event 置位后尽快中断流式读取（用户取消）。
        """
        if any(m.get("role") not in ("user", "assistant", "tool") for m in messages):
            raise LLMError("对话消息格式错误")
        stream = on_delta is not None
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": self.cfg.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if json_mode and not tools:
            # DeepSeek 支持 JSON 输出模式，能避免它夹带解释文字；与工具调用互斥。
            payload["response_format"] = {"type": "json_object"}
        if tools:
            payload["tools"] = tools
        thinking_requested = thinking
        if thinking_requested:
            payload["thinking"] = {"type": "enabled"}
            strength = (effort or getattr(self.cfg, "reasoning_effort", "") or "high").strip().lower()
            if strength in ("low", "high", "max"):
                payload["reasoning_effort"] = strength

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Accept": "text/event-stream" if stream else "application/json",
        }

        last_err: Exception | None = None
        for attempt in range(max(1, self.cfg.max_retries + 1)):
            started = time.monotonic()
            try:
                if stream:
                    raw = await asyncio.to_thread(
                        _post_stream, self.endpoint, payload, headers, float(self.cfg.timeout_s), on_delta, stop_event
                    )
                else:
                    raw = await asyncio.to_thread(
                        _post_json, self.endpoint, payload, headers, float(self.cfg.timeout_s)
                    )
            except LLMError as exc:
                last_err = exc
                if exc.no_retry:
                    raise
                if thinking_requested and "thinking" in str(exc).lower():
                    # 目标服务不认识 thinking 参数（自定义 base_url / 旧模型）：去掉后立即重试。
                    thinking_requested = False
                    payload.pop("thinking", None)
                    continue
                if "reasoning_effort" in str(exc).lower():
                    # 旧端点不认思考档位：去掉这个参数再试，不影响主流程。
                    payload.pop("reasoning_effort", None)
                    continue
                # 认证类错误重试没意义
                if "401" in str(exc) or "402" in str(exc) or "403" in str(exc):
                    raise
                await asyncio.sleep(1.5 * (attempt + 1))
                continue

            duration_ms = int((time.monotonic() - started) * 1000)
            if stream:
                usage = raw.get("usage") or {}
                content = (raw.get("content") or "").strip()
                reasoning = (raw.get("reasoning") or "").strip()
                tool_calls = raw.get("tool_calls") or []
                if not content and not reasoning and not tool_calls:
                    last_err = LLMError("流式响应没有内容")
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                hit, miss = _cache_tokens(usage)
                reply = LLMReply(
                    text=content,
                    model=raw.get("model") or self.cfg.model,
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                    duration_ms=duration_ms,
                    retries=attempt,
                    reasoning=reasoning,
                    reasoning_tokens=_reasoning_tokens(usage),
                    tool_calls=tool_calls,
                    cache_hit_tokens=hit,
                    cache_miss_tokens=miss,
                )
                log.info("llm stream model=%s cache_hit=%s cache_miss=%s", reply.model, hit, miss)
                return reply

            choices = raw.get("choices") or []
            if not choices:
                last_err = LLMError(f"响应里没有 choices：{str(raw)[:200]}")
                continue
            message = choices[0].get("message") or {}
            usage = raw.get("usage") or {}
            tool_calls = []
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                tool_calls.append({"id": str(call.get("id") or ""),
                                   "name": str(function.get("name") or ""),
                                   "arguments": str(function.get("arguments") or "")})
            hit, miss = _cache_tokens(usage)
            reply = LLMReply(
                text=(message.get("content") or "").strip(),
                model=raw.get("model") or self.cfg.model,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                duration_ms=duration_ms,
                retries=attempt,
                reasoning=(message.get("reasoning_content") or "").strip(),
                reasoning_tokens=_reasoning_tokens(usage),
                tool_calls=tool_calls,
                cache_hit_tokens=hit,
                cache_miss_tokens=miss,
            )
            log.info("llm model=%s cache_hit=%s cache_miss=%s", reply.model, hit, miss)
            return reply

        raise LLMError(f"重试 {self.cfg.max_retries} 次仍失败：{last_err}")

    async def vision_json(self, prompt: str, image_path: str | Path, *, system: str = "",
                          max_tokens: int = 900) -> LLMReply:
        """图片理解（仅 deepseek-flash 支持）：返回 JSON 文本，用于读后台截图。

        图片以 base64 data URL 内联（≤32MB；不传给 Files API，避免客户素材上云留存）。
        """
        path = Path(image_path)
        data = path.read_bytes()
        if len(data) > 32 * 1024 * 1024:
            raise LLMError("截图超过 32MB，请先压缩再试")
        media_type = mimetypes.guess_type(path.name)[0] or "image/png"
        if media_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
            media_type = "image/png"
        inline = base64.b64encode(data).decode("ascii")
        messages = [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{inline}"}},
        ]}]
        return await self.for_vision().chat_messages(system or "你是严谨的数据录入助手，只输出 JSON。", messages,
                                        json_mode=True, max_tokens=max_tokens, temperature=0.0)

    async def ping(self) -> dict:
        """连通性自检。面板和 doctor 用它。"""
        reply = await self.chat("你是助手。", "只回复 JSON：{\"ok\":true}", max_tokens=32)
        return {"ok": True, "model": reply.model, "tokens": reply.total_tokens,
                "duration_ms": reply.duration_ms, "text": reply.text[:120]}
