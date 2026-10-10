"""大模型客户端。

只依赖标准库：HTTP 用 urllib 放在工作线程里跑，不引入 httpx/aiohttp。
理由：这是长期项目，少一个依赖少一处维护；而且这个调用量（几十次/天）
根本不需要连接池复用。

DeepSeek 兼容 OpenAI 的 /chat/completions 协议，所以换供应商只要改 base_url。
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from ..config import LLMConfig


class LLMError(RuntimeError):
    pass


@dataclass
class LLMReply:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: int = 0
    retries: int = 0

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
    ) -> LLMReply:
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.cfg.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_mode:
            # DeepSeek 支持 JSON 输出模式，能避免它夹带解释文字
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Accept": "application/json",
        }

        last_err: Exception | None = None
        for attempt in range(max(1, self.cfg.max_retries + 1)):
            started = time.monotonic()
            try:
                raw = await asyncio.to_thread(
                    _post_json, self.endpoint, payload, headers, float(self.cfg.timeout_s)
                )
            except LLMError as exc:
                last_err = exc
                # 认证类错误重试没意义
                if "401" in str(exc) or "402" in str(exc) or "403" in str(exc):
                    raise
                await asyncio.sleep(1.5 * (attempt + 1))
                continue

            duration_ms = int((time.monotonic() - started) * 1000)
            choices = raw.get("choices") or []
            if not choices:
                last_err = LLMError(f"响应里没有 choices：{str(raw)[:200]}")
                continue
            content = ((choices[0].get("message") or {}).get("content") or "").strip()
            usage = raw.get("usage") or {}
            return LLMReply(
                text=content,
                model=raw.get("model") or self.cfg.model,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                duration_ms=duration_ms,
                retries=attempt,
            )

        raise LLMError(f"重试 {self.cfg.max_retries} 次仍失败：{last_err}")

    async def ping(self) -> dict:
        """连通性自检。面板和 doctor 用它。"""
        reply = await self.chat("你是助手。", "只回复 JSON：{\"ok\":true}", max_tokens=32)
        return {"ok": True, "model": reply.model, "tokens": reply.total_tokens,
                "duration_ms": reply.duration_ms, "text": reply.text[:120]}
