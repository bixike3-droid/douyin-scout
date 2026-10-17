"""后台截图识别：输出解析与图片请求组装（不联网）。"""
import asyncio
from pathlib import Path

from scout.analyze.metrics_vision import parse_metrics
from scout.config import LLMConfig
from scout.llm import DeepSeekClient
from scout.llm import client as llm_client


def test_parse_metrics_reads_numbers_and_unknowns():
    result = parse_metrics('{"play_count": 1200, "digg_count": "80", "comment_count": null,'
                           ' "share_count": 5, "collected_at": "2026-10-16T10:00:00",'
                           ' "confidence": "high", "missing": ["评论量"], "notes": "截图右上角"}')
    assert result["ok"] is True
    data = result["data"]
    assert data["play_count"] == 1200 and data["digg_count"] == 80 and data["comment_count"] is None
    assert data["collected_at"] == "2026-10-16" and data["confidence"] == "high"
    assert data["missing"] == ["评论量"]


def test_parse_metrics_rejects_empty_or_bad_output():
    assert parse_metrics("不是 JSON")["ok"] is False
    empty = parse_metrics('{"play_count": null, "digg_count": null, "comment_count": null,'
                          ' "share_count": null}')
    assert empty["ok"] is False and "没有识别到" in empty["error"]
    bad_date = parse_metrics('{"play_count": 1, "collected_at": "10月16日"}')
    assert bad_date["ok"] is True and bad_date["data"]["collected_at"] is None


def test_thinking_effort_is_sent_with_thinking(monkeypatch):
    captured = {}

    def fake_post(url, payload, headers, timeout):
        captured.clear()
        captured.update(payload)
        return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    monkeypatch.setattr(llm_client, "_post_json", fake_post)
    client = DeepSeekClient(LLMConfig(api_key="k", model="deepseek-flash", reasoning_effort="high"))
    asyncio.run(client.chat("系统", "问题", thinking=True, effort="max"))
    assert captured["thinking"] == {"type": "enabled"}
    assert captured["reasoning_effort"] == "max"
    asyncio.run(client.chat("系统", "问题", thinking=False))
    assert "reasoning_effort" not in captured or captured.get("thinking") is None


def test_vision_request_embeds_inline_image_and_reads_cache(tmp_path, monkeypatch):
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    captured = {}

    def fake_post(url, payload, headers, timeout):
        captured.update(payload)
        return {"model": "deepseek-flash",
                "choices": [{"message": {"content": '{"play_count": 42}'}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10,
                          "prompt_cache_hit_tokens": 60, "prompt_cache_miss_tokens": 40}}

    monkeypatch.setattr(llm_client, "_post_json", fake_post)
    client = DeepSeekClient(LLMConfig(api_key="k", model="deepseek-flash"))
    reply = asyncio.run(client.vision_json("读图", image))
    blocks = captured["messages"][1]["content"]
    assert blocks[0]["type"] == "text"
    assert blocks[1]["type"] == "image_url"
    assert blocks[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert reply.text == '{"play_count": 42}'
    assert reply.cache_hit_tokens == 60 and reply.cache_miss_tokens == 40
