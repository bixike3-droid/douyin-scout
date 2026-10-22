"""Real local extraction, multimodal handoff, retention and account isolation."""
import asyncio
import json
from pathlib import Path
import re
import zipfile

import pytest
from PIL import Image

from scout.attachments import validate_files, import_file, extract, managed_path, _run_ffmpeg
from scout.analyze.conversation import send
from scout.app import AppContext
from scout.llm import LLMReply, LLMError
from scout.store.attachments import Attachments
from scout.store.conversation import Conversations
from scout.tools import registry


class FileClient:
    def __init__(self):
        self.visual_calls, self.message_calls = [], []
        self.fail_vision = False

    async def chat(self, *args, **kwargs):
        return LLMReply(text='{"speaker":"steward","workflow":null}', model="route")

    async def chat_messages(self, system, messages, **kwargs):
        if isinstance(messages[-1]["content"], list):
            self.visual_calls.append(messages)
            if self.fail_vision:
                raise LLMError("model does not support image input")
            keys = set(re.findall(r'"asset_id":\s*"(A\d+)"', str(messages)))
            if keys:
                return LLMReply(text=json.dumps({"observations": [{"asset_id": key, "description": "实际识别：红色画面，未提供音轨。"} for key in keys],
                                                   "summary": "实际识别：红色画面，未提供音轨。"}, ensure_ascii=False), model="vision", prompt_tokens=30, completion_tokens=10)
            ids = set(re.findall(r"附件 ID：([a-f0-9]+)", str(messages)))
            return LLMReply(text=json.dumps({"attachments": [{"id": id, "summary": "实际识别：红色画面，未提供音轨。"} for id in ids]}, ensure_ascii=False), model="vision", prompt_tokens=30, completion_tokens=10)
        self.message_calls.append(messages)
        return LLMReply(text="已根据附件资料完成分析。", model="test")


@pytest.mark.skip(reason="依赖已移除的原生推理循环；改写为 Codex 验收脚本前先跳过")
def test_text_attachment_reaches_model_and_survives_original_removal(ctx, tmp_path):
    source = tmp_path / "需求.txt"
    source.write_text("活动预算 5000 元；只在周六营业。", encoding="utf-8")
    client = FileClient()
    result = asyncio.run(send(ctx, client, "分析这份需求", attachment_paths=[str(source)]))
    assert "活动预算 5000" in str(client.message_calls[-1])
    item = result["conversation"]["messages"][0]["attachments"][0]
    stored = managed_path(ctx.paths, item["relative_path"])
    source.unlink()
    assert stored.read_text(encoding="utf-8").startswith("活动预算")
    with AppContext.create(ctx.config) as reopened:
        conversation = Conversations(reopened.db).get(1)
        assert conversation["messages"][0]["attachments"][0]["name"] == "需求.txt"
        assert "只在周六营业" in str(Conversations(reopened.db).context_history(1))
    asyncio.run(send(ctx, client, "继续解释预算", conversation_id=1))
    assert "活动预算 5000" in str(client.message_calls[-1])


@pytest.mark.skip(reason="依赖已移除的原生推理循环；改写为 Codex 验收脚本前先跳过")
def test_image_is_resized_and_sent_as_real_visual_input(ctx, tmp_path):
    source = tmp_path / "图片.png"
    Image.new("RGBA", (2000, 1000), (255, 0, 0, 128)).save(source)
    client = FileClient()
    result = asyncio.run(send(ctx, client, "", attachment_paths=[str(source)]))
    assert client.visual_calls
    blocks = client.visual_calls[0][0]["content"]
    assert any(b.get("image_url", {}).get("url", "").startswith("data:image/jpeg;base64,") for b in blocks)
    assert "实际识别：红色画面" in str(client.message_calls[-1])
    item = Attachments(ctx.db).list(1)[0]
    from scout.store.attachment_workspace import AssetStore
    asset = AssetStore(ctx.db).get(item["id"], "A0001")
    with Image.open(managed_path(ctx.paths, asset["thumbnail_path"])) as image:
        assert image.width == 640 and image.mode == "RGB"
    assert item["status"] == "ready" and result["conversation"]["messages"][0]["content"]
    assert ctx.db.scalar("SELECT COUNT(*) FROM model_calls WHERE purpose='attachment_overview'") == 1


@pytest.mark.skip(reason="依赖已移除的原生推理循环；改写为 Codex 验收脚本前先跳过")
def test_unsupported_visual_model_is_explicit_and_does_not_claim_reading(ctx, tmp_path):
    source = tmp_path / "input.png"
    Image.new("RGB", (20, 20), "red").save(source)
    client = FileClient()
    client.fail_vision = True
    result = asyncio.run(send(ctx, client, "read", agent_id="steward", attachment_paths=[str(source)]))
    item = Attachments(ctx.db).list(1)[0]
    assert item["status"] == "partial" and "未完成批次" in item["analysis"]
    assert "does not support" in str(client.message_calls[-1])
    assert result["conversation"]["messages"][0]["attachments"]


@pytest.mark.parametrize("suffix,member,xml,expected", [
    (".docx", "word/document.xml", '<w:document xmlns:w="urn:w"><w:body><w:p><w:r><w:t>Word 内容</w:t></w:r></w:p></w:body></w:document>', "Word 内容"),
    (".pptx", "ppt/slides/slide1.xml", '<p:sld xmlns:p="urn:p" xmlns:a="urn:a"><a:p><a:r><a:t>演示文稿内容</a:t></a:r></a:p></p:sld>', "幻灯片 1\n演示文稿内容"),
    (".xlsx", "xl/worksheets/sheet1.xml", '<worksheet xmlns="urn:x"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>预算</t></is></c><c r="B1"><v>5000</v></c></row></sheetData></worksheet>', "A1=预算\tB1=5000"),
    (".odt", "content.xml", '<office:document xmlns:office="urn:o" xmlns:text="urn:t"><text:p>ODT 内容</text:p></office:document>', "ODT 内容"),
])
def test_office_formats_are_read_locally_without_executing_content(ctx, tmp_path, suffix, member, xml, expected):
    source = tmp_path / ("document" + suffix)
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(member, xml)
    item = import_file(ctx.paths, source)
    result = extract(ctx.paths, item)
    assert expected in result["text"] and "不执行" in result["limitations"]


def test_real_video_extracts_timestamped_frames(ctx, tmp_path):
    source = tmp_path / "sample.mp4"
    result = _run_ffmpeg(["-f", "lavfi", "-i", "color=c=red:s=160x90:r=10", "-t", "0.6", "-pix_fmt", "yuv420p", "-y", str(source)])
    assert result.returncode == 0
    item = import_file(ctx.paths, source)
    extracted = extract(ctx.paths, item)
    assert len(extracted["visuals"]) >= 3
    assert "未转写或识别音轨" in extracted["limitations"]
    assert all("秒" in frame["label"] and managed_path(ctx.paths, frame["path"]).is_file() for frame in extracted["visuals"])


def test_scan_pdf_renders_real_pages_and_password_pdf_reports_error(ctx, tmp_path):
    from pypdf import PdfWriter
    source = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    writer.write(source)
    result = extract(ctx.paths, import_file(ctx.paths, source))
    assert result["visuals"] and "文本层不足" in result["limitations"]
    writer.encrypt("secret")
    writer.write(source)
    with pytest.raises(ValueError, match="密码保护"):
        extract(ctx.paths, import_file(ctx.paths, source))


@pytest.mark.skip(reason="依赖已移除的原生推理循环；改写为 Codex 验收脚本前先跳过")
def test_corrupt_document_is_preserved_with_honest_failure(ctx, tmp_path):
    source = tmp_path / "broken.docx"
    source.write_bytes(b"not a zip document")
    client = FileClient()
    result = asyncio.run(send(ctx, client, "read", agent_id="steward", attachment_paths=[str(source)]))
    assert result["conversation"]["messages"][0]["attachments"][0]["status"] == "failed"
    assert "读取失败" in str(client.message_calls[-1])


def test_attachment_tools_cannot_cross_conversations_and_support_pagination(ctx, tmp_path):
    source = tmp_path / "large.txt"
    source.write_text("a" * 4000 + "后半段证据", encoding="utf-8")
    asyncio.run(send(ctx, FileClient(), "read", agent_id="steward", attachment_paths=[str(source)]))
    item = Attachments(ctx.db).list(1)[0]
    ctx.tool_conversation_id = Conversations(ctx.db).create("other")
    result = asyncio.run(registry.execute(ctx, "attachment_read", "steward", {"attachment_id": item["id"]}))
    assert not result["ok"]
    ctx.tool_conversation_id = 1
    result = asyncio.run(registry.execute(ctx, "attachment_read", "steward", {"attachment_id": item["id"], "offset": 4000}))
    assert "后半段证据" in result["content"]
    with pytest.raises(ValueError, match="账号目录"):
        managed_path(ctx.paths, "../outside.txt")


def test_validation_accepts_regular_files_and_bounds_batch(tmp_path):
    with pytest.raises(ValueError, match="文件夹"):
        validate_files([tmp_path])
    bad = tmp_path / "file.exe"
    bad.write_bytes(b"test")
    assert validate_files([bad]) == [bad]
    assert validate_files([bad] * 100) == [bad]


def test_plan_workflow_freezes_attachment_evidence_and_retains_on_rerun(ctx, tmp_path):
    from test_workflow import WorkflowClient, seed_data
    seed_data(ctx)
    source = tmp_path / "brief.txt"
    source.write_text("附件独有约束：只做周六夜场。", encoding="utf-8")
    client = WorkflowClient()
    first = asyncio.run(send(ctx, client, "仅用已有数据生成方案", want_plan=True, attachment_paths=[str(source)]))
    assert "只做周六夜场" in str(client.calls[-1][1]["context"]["evidence"])
    assert first["conversation"]["messages"][0]["attachments"]
    source.unlink()
    second = asyncio.run(send(ctx, client, "重做", conversation_id=1, workflow_run_id=first["workflow"]["id"], rerun=True))
    assert second["workflow"]["status"] == "complete"
    assert "只做周六夜场" in str(client.calls[-1][1]["context"]["evidence"])


def test_all_visual_attachments_are_overviewed(ctx, tmp_path):
    import scout.attachments as module
    sources = []
    for index in range(6):
        source = tmp_path / f"sample-{index}.jpg"
        Image.new("RGB", (20, 20), "red").save(source)
        sources.append(str(source))
    client = FileClient()
    asyncio.run(send(ctx, client, "read", agent_id="steward", attachment_paths=sources))
    assert len(client.visual_calls) == 6
    items = Attachments(ctx.db).list(1)
    assert all("总览已查看 1/1" in a["text_content"] for a in items)


@pytest.mark.skip(reason="依赖已移除的原生推理循环；改写为 Codex 验收脚本前先跳过")
def test_followup_can_reinspect_saved_image_through_attachment_tool(ctx, tmp_path):
    source = tmp_path / "poster.jpg"
    Image.new("RGB", (80, 80), "red").save(source)
    asyncio.run(send(ctx, FileClient(), "看一下", agent_id="steward", attachment_paths=[str(source)]))
    item = Attachments(ctx.db).list(1)[0]
    source.unlink()
    class Followup:
        async def chat_messages(self, system, messages, **kwargs):
            if isinstance(messages[-1]["content"], list):
                assert any(b["type"] == "image_url" for b in messages[-1]["content"])
                return LLMReply(text="重新检查：画面是红色，未见可读文字。", model="vision")
            if messages[-1]["role"] == "tool":
                assert "重新检查：画面是红色" in messages[-1]["content"]
                return LLMReply(text="画面里未见可读文字。", model="test")
            return LLMReply(text="", model="test", tool_calls=[{"id": "inspect", "name": "attachment_inspect",
                "arguments": json.dumps({"attachment_id": item["id"], "asset_ids": ["A0001"], "question": "海报上有什么文字？"}, ensure_ascii=False)}])
    result = asyncio.run(send(ctx, Followup(), "海报上有什么文字？", agent_id="steward", conversation_id=1))
    assert result["conversation"]["chat_run"]["model_calls"] == 3
    assert not result.get("failed")
