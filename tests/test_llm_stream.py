"""流式解析（SSE → LLMReply）：思维链先行、usage 收尾、取消可中断，均不依赖网络。"""
import asyncio
import io
import json
import threading
import urllib.error

import pytest

from scout.config import LLMConfig
from scout.llm import client as llm_client


class FakeResponse:
    def __init__(self, lines):
        self._lines = [line.encode("utf-8") for line in lines]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._lines)


def test_stream_collects_reasoning_content_and_usage(monkeypatch):
    lines = [
        'data: {"model":"m1","choices":[{"delta":{"reasoning_content":"先"}}]}',
        'data: {"model":"m1","choices":[{"delta":{"reasoning_content":"想一想"}}]}',
        'data: {"model":"m1","choices":[{"delta":{"content":"{\\"ok\\":true}"}}]}',
        'data: {"model":"m1","choices":[{"delta":{},"finish_reason":"stop"}]}',
        'data: {"usage":{"prompt_tokens":3,"completion_tokens":5,"completion_tokens_details":{"reasoning_tokens":4}}}',
        "data: [DONE]",
    ]
    monkeypatch.setattr(llm_client.urllib.request, "urlopen", lambda req, timeout=None: FakeResponse(lines))
    seen = []
    result = llm_client._post_stream("http://fake", {}, {}, 5.0, lambda kind, text: seen.append((kind, text)))
    assert result["reasoning"] == "先想一想"
    assert result["content"] == '{"ok":true}'
    assert result["model"] == "m1"
    assert result["usage"]["completion_tokens_details"]["reasoning_tokens"] == 4
    assert seen == [("reasoning", "先"), ("reasoning", "想一想"), ("content", '{"ok":true}')]


def test_stream_stops_immediately_after_cancel(monkeypatch):
    lines = [
        'data: {"choices":[{"delta":{"reasoning_content":"第一段"}}]}',
        'data: {"choices":[{"delta":{"reasoning_content":"第二段"}}]}',
        "data: [DONE]",
    ]
    monkeypatch.setattr(llm_client.urllib.request, "urlopen", lambda req, timeout=None: FakeResponse(lines))
    stop = threading.Event()
    seen = []

    def on_delta(kind, text):
        seen.append(text)
        stop.set()

    with pytest.raises(llm_client.LLMError) as info:
        llm_client._post_stream("http://fake", {}, {}, 5.0, on_delta, stop)
    assert info.value.no_retry
    assert seen == ["第一段"]


def test_chat_drops_thinking_when_service_rejects_it(monkeypatch):
    """不认识 thinking 参数的服务（旧模型 / 自定义 base_url）：自动去掉后重试，回答不受影响。"""
    payloads = []

    def fake_urlopen(req, timeout=None):
        body = json.loads(req.data.decode("utf-8"))
        payloads.append(body)
        if "thinking" in body:
            raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {},
                io.BytesIO(b'{"error":{"message":"Unsupported parameter: thinking"}}'))
        return FakeResponse([
            'data: {"model":"m","choices":[{"delta":{"content":"{\\"reply\\":\\"ok\\",\\"plan\\":null}"}}]}',
            'data: {"usage":{"prompt_tokens":1,"completion_tokens":2}}',
            "data: [DONE]",
        ])

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", fake_urlopen)
    cfg = LLMConfig(api_key="test-key", model="legacy-model", base_url="http://fake")
    reply = asyncio.run(llm_client.DeepSeekClient(cfg).chat("sys", "你好", thinking=True, on_delta=lambda kind, text: None))
    assert reply.text == '{"reply":"ok","plan":null}'
    assert [("thinking" in payload) for payload in payloads] == [True, False]


def test_stream_assembles_tool_call_arguments(monkeypatch):
    lines = [
        'data: {"model":"m","choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"web_fetch","arguments":"{\\"url\\":"}}]}}]}',
        'data: {"model":"m","choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"https://e.com\\"}"}}]}}]}',
        'data: {"model":"m","choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
        "data: [DONE]",
    ]
    monkeypatch.setattr(llm_client.urllib.request, "urlopen", lambda req, timeout=None: FakeResponse(lines))
    result = llm_client._post_stream("http://fake", {}, {}, 5.0, lambda kind, text: None)
    assert result["tool_calls"] == [{"id": "call_1", "name": "web_fetch", "arguments": '{"url":"https://e.com"}'}]
    assert result["content"] == ""
