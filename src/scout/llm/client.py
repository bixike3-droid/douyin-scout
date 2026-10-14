"""大模型客户端。

只依赖标准库：HTTP 用 urllib 放在工作线程里跑，不引入 httpx/aiohttp。
理由：这是长期项目，少一个依赖少一处维护；而且这个调用量（几十次/天）
根本不需要连接池复用。

DeepSeek 兼容 OpenAI 的 /chat/completions 协议，所以换供应商只要改 base_url。
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from ..config import LLMConfig


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
    return {"reasoning": "".join(reasoning), "content": "".join(content), "usage": usage, "model": model}


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
        on_delta: Callable[[str, str], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> LLMReply:
        """一次对话调用。

        - thinking=True 请求思维链（DeepSeek thinking 模式，返回 reasoning_content）。
        - on_delta 非空时用流式：每段增量回调 on_delta(kind, text)，
          kind 为 "reasoning"（思维链）或 "content"（正式回答）。
        - stop_event 置位后尽快中断流式读取（用户取消）。
        """
        history = history or []
        if any(m.get("role") not in ("user", "assistant") or not isinstance(m.get("content"), str) for m in history):
            raise LLMError("对话历史格式错误")
        stream = on_delta is not None
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                *history,
                {"role": "user", "content": user},
            ],
            "temperature": self.cfg.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if json_mode:
            # DeepSeek 支持 JSON 输出模式，能避免它夹带解释文字
            payload["response_format"] = {"type": "json_object"}
        thinking_requested = thinking
        if thinking_requested:
            payload["thinking"] = {"type": "enabled"}

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
                if not content and not reasoning:
                    last_err = LLMError("流式响应没有内容")
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                return LLMReply(
                    text=content,
                    model=raw.get("model") or self.cfg.model,
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                    duration_ms=duration_ms,
                    retries=attempt,
                    reasoning=reasoning,
                    reasoning_tokens=_reasoning_tokens(usage),
                )

            choices = raw.get("choices") or []
            if not choices:
                last_err = LLMError(f"响应里没有 choices：{str(raw)[:200]}")
                continue
            message = choices[0].get("message") or {}
            usage = raw.get("usage") or {}
            return LLMReply(
                text=(message.get("content") or "").strip(),
                model=raw.get("model") or self.cfg.model,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                duration_ms=duration_ms,
                retries=attempt,
                reasoning=(message.get("reasoning_content") or "").strip(),
                reasoning_tokens=_reasoning_tokens(usage),
            )

        raise LLMError(f"重试 {self.cfg.max_retries} 次仍失败：{last_err}")

    async def ping(self) -> dict:
        """连通性自检。面板和 doctor 用它。"""
        reply = await self.chat("你是助手。", "只回复 JSON：{\"ok\":true}", max_tokens=32)
        return {"ok": True, "model": reply.model, "tokens": reply.total_tokens,
                "duration_ms": reply.duration_ms, "text": reply.text[:120]}
