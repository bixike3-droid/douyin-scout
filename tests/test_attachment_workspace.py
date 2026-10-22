"""Complete traversal, contact-sheet coverage, persistent resume and detail tools."""
import asyncio
import io
import json
from pathlib import Path
import re
import zipfile

import pytest
from PIL import Image

from scout.app import AppContext
from scout.attachments import import_file, managed_path
from scout.attachment_workspace import build_workspace, overview
from scout.analyze.conversation import send
from scout.llm import LLMReply
from scout.llm.tracked import TrackedClient
from scout.store.attachments import Attachments
from scout.store.attachment_workspace import AssetStore
from scout.store.conversation import Conversations
from scout.tools import registry


def image_archive(path, count):
    image = io.BytesIO()
    Image.new("RGB", (120, 80), "red").save(image, "JPEG")
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(count):
            archive.writestr(f"photos/image-{index:03d}.jpg", image.getvalue())


class VisionClient:
    def __init__(self):
        self.overviews = []
        self.cancel_on = None
    async def chat(self, *args, **kwargs):
        return LLMReply(text='{"speaker":"steward","workflow":null}', model="route")
    async def chat_messages(self, system, messages, **kwargs):
        if isinstance(messages[-1]["content"], list):
            keys = sorted(set(re.findall(r'"asset_id":\s*"(A\d+)"', str(messages))))
            if keys:
                self.overviews.append(keys)
                if self.cancel_on == len(self.overviews):
                    raise asyncio.CancelledError
                return LLMReply(text=json.dumps({"observations": [{"asset_id": key, "description": "红色图片 " + key} for key in keys],
                                                   "summary": "本批素材均已逐项查看"}), model="vision")
            return LLMReply(text="原图细节已检查", model="vision")
        return LLMReply(text="全部素材总览已完成，可继续选择原图。", model="main")


def test_all_73_images_get_indexed_and_overviewed_across_every_sheet(ctx, tmp_path):
    source = tmp_path / "many.zip"
    image_archive(source, 73)
    client = VisionClient()
    result = asyncio.run(send(ctx, client, "逐项浏览全部素材", attachment_paths=[str(source)], agent_id="steward"))
    item = Attachments(ctx.db).list(1)[0]
    store = AssetStore(ctx.db)
    progress = store.progress(item["id"])
    assert progress["total"] == progress["thumbnails"] == progress["overviewed"] == 73
    assert progress["failed"] == 0 and progress["pending"] == 0
    assert len(client.overviews) == 7
    keys = [key for group in client.overviews for key in group]
    assert len(keys) == len(set(keys)) == 73
    assert all(a["source_path"] and a["thumbnail_path"] for a in store.assets(item["id"]))
    assert len(store.batches(item["id"])) == 7
    assert result["conversation"]["messages"][0]["attachments"][0]["workspace"]["overviewed"] == 73


def test_cancelled_overview_resumes_after_database_reopen_without_repeating_complete_batches(ctx, tmp_path):
    source = tmp_path / "resume.zip"
    image_archive(source, 29)
    client = VisionClient()
    client.cancel_on = 2
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(send(ctx, client, "全部看完", attachment_paths=[str(source)], agent_id="steward"))
    item = Attachments(ctx.db).list(1)[0]
    assert AssetStore(ctx.db).progress(item["id"])["overviewed"] == 12
    finished_keys = set(client.overviews[0])
    continued = VisionClient()
    with AppContext.create(ctx.config) as reopened:
        tracker = TrackedClient(continued, reopened.db, 1)
        progress = asyncio.run(overview(reopened, tracker, item, "继续全部看完"))
    assert progress["overviewed"] == 29
    assert not finished_keys.intersection(key for group in continued.overviews for key in group)


@pytest.mark.skip(reason="依赖已移除的原生推理循环；改写为 Codex 验收脚本前先跳过")
def test_detail_inspection_beyond_eight_calls_reuses_index_and_originals(ctx, tmp_path):
    source = tmp_path / "detail.zip"
    image_archive(source, 12)
    asyncio.run(send(ctx, VisionClient(), "建立总览", attachment_paths=[str(source)], agent_id="steward"))
    item = Attachments(ctx.db).list(1)[0]
    class ManyInspections(VisionClient):
        parent_calls = 0
        async def chat_messages(self, system, messages, **kwargs):
            if isinstance(messages[-1]["content"], list):
                return await super().chat_messages(system, messages, **kwargs)
            self.parent_calls += 1
            if self.parent_calls <= 10:
                return LLMReply(text="", model="main", tool_calls=[{"id": f"look-{self.parent_calls}", "name": "attachment_inspect",
                    "arguments": json.dumps({"attachment_id": item["id"], "asset_ids": [f"A{self.parent_calls:04d}"], "question": "查看这一张原图"})}])
            return LLMReply(text="十张原图均已检查。", model="main")
    result = asyncio.run(send(ctx, ManyInspections(), "逐张细看前十张", conversation_id=1, agent_id="steward"))
    run = result["conversation"]["chat_run"]
    assert run["tool_count"] == 10 and run["model_calls"] == 21
    assert run["status"] == "complete" and AssetStore(ctx.db).progress(item["id"])["inspected"] == 10


def test_asset_search_paginates_to_last_image_and_checks_conversation(ctx, tmp_path):
    source = tmp_path / "search.zip"
    image_archive(source, 31)
    asyncio.run(send(ctx, VisionClient(), "总览", attachment_paths=[str(source)], agent_id="steward"))
    item = Attachments(ctx.db).list(1)[0]
    ctx.tool_conversation_id = 1
    result = asyncio.run(registry.execute(ctx, "attachment_assets", "steward", {"attachment_id": item["id"], "offset": 30}))
    assert "image-030.jpg" in result["content"] and not result["data"]["has_more"]
    ctx.tool_conversation_id = Conversations(ctx.db).create("other")
    denied = asyncio.run(registry.execute(ctx, "attachment_assets", "steward", {"attachment_id": item["id"]}))
    assert not denied["ok"]


def test_original_crop_uses_full_image_coordinates(ctx, tmp_path):
    source = tmp_path / "crop.jpg"
    image = Image.new("RGB", (2000, 1000), "red")
    image.paste("blue", (1000, 0, 2000, 1000))
    image.save(source)
    asyncio.run(send(ctx, VisionClient(), "查看", attachment_paths=[str(source)], agent_id="steward"))
    item = Attachments(ctx.db).list(1)[0]
    ctx.tool_conversation_id = 1
    ctx.tool_client = TrackedClient(VisionClient(), ctx.db, 1)
    result = asyncio.run(registry.execute(ctx, "attachment_inspect", "steward", {"attachment_id": item["id"], "asset_ids": ["A0001"], "question": "右半部分", "crop": [0.5, 0, 1, 1]}))
    asset = AssetStore(ctx.db).get(item["id"], "A0001")
    with Image.open(managed_path(ctx.paths, asset["preview_path"])) as preview:
        r, g, b = preview.getpixel((preview.width // 2, preview.height // 2))
        assert b > 200 and r < 30
    assert result["ok"]


def test_cancelling_thumbnail_build_waits_for_worker_and_reuses_cached_thumbnail(ctx, tmp_path, monkeypatch):
    import scout.attachments as attachment_module
    import time
    source = tmp_path / "stop-build.zip"
    image_archive(source, 12)
    cid = Conversations(ctx.db).create("build")
    item = import_file(ctx.paths, source)
    Attachments(ctx.db).add(item, cid)
    original = attachment_module._image
    calls = []
    def slow_image(source, output, **kwargs):
        calls.append(str(source))
        time.sleep(.03)
        return original(source, output, **kwargs)
    monkeypatch.setattr(attachment_module, "_image", slow_image)
    async def exercise():
        event = asyncio.Event()
        loop = asyncio.get_running_loop()
        def emit(event_data):
            if "1/12" in event_data.get("message", ""):
                loop.call_soon_threadsafe(event.set)
        client = TrackedClient(VisionClient(), ctx.db, cid)
        task = asyncio.create_task(overview(ctx, client, item, "浏览", emit))
        await asyncio.wait_for(event.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(exercise())
    assert AssetStore(ctx.db).progress(item["id"])["thumbnails"] == 1
    with AppContext.create(ctx.config) as reopened:
        asyncio.run(overview(reopened, TrackedClient(VisionClient(), reopened.db, cid), item, "继续"))
    assert len(calls) == 12


def test_detail_checkpoints_reuse_completed_asset_after_cancellation(ctx, tmp_path):
    from scout.attachment_workspace import inspect_assets
    source = tmp_path / "detail-resume.zip"
    image_archive(source, 2)
    asyncio.run(send(ctx, VisionClient(), "总览", attachment_paths=[str(source)], agent_id="steward"))
    item = Attachments(ctx.db).list(1)[0]
    class Interrupted(VisionClient):
        details = 0
        async def chat_messages(self, *args, **kwargs):
            self.details += 1
            if self.details == 2:
                raise asyncio.CancelledError
            return LLMReply(text="细看结果", model="vision")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(inspect_assets(ctx, TrackedClient(Interrupted(), ctx.db, 1), item, ["A0001", "A0002"], "细看"))
    class Continued(VisionClient):
        details = 0
        async def chat_messages(self, *args, **kwargs):
            self.details += 1
            return LLMReply(text="细看结果", model="vision")
    client = Continued()
    with AppContext.create(ctx.config) as reopened:
        asyncio.run(inspect_assets(reopened, TrackedClient(client, reopened.db, 1), item, ["A0001", "A0002"], "细看"))
    assert client.details == 1


def test_vision_routing_keeps_planning_model_and_respects_custom_endpoints():
    from scout.config import LLMConfig
    from scout.llm import DeepSeekClient
    client = DeepSeekClient(LLMConfig(api_key="test", model="deepseek-v4-pro"))
    assert client.for_vision().cfg.model == "deepseek-flash" and client.cfg.model == "deepseek-v4-pro"
    custom = DeepSeekClient(LLMConfig(api_key="test", base_url="https://example.com", model="custom-model"))
    assert custom.for_vision().cfg.model == "custom-model"
