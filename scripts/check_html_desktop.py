"""Browser acceptance of the real HTML desktop API, using an explicit offline runner.

Tests local transport/UI rather than model quality. No credentials or live account
data are used; files and databases stay under tmp/html-desktop/acceptance/.
"""
import asyncio
import io
import json
from pathlib import Path
import shutil
import time
import zipfile

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright, expect

from scout.app import AppContext
from scout.config import load_config
from scout.paths import Paths
from scout.attachments import import_file
from scout.attachment_workspace import build_workspace, refresh_attachment
from scout.store.attachments import Attachments
from scout.store.conversation import Conversations
from scout.web_desktop.gateway import Gateway
from scout.web_desktop.api import create_app
from scout.web_desktop.window import Server


def main():
    repo = Path(__file__).resolve().parents[1]
    base = repo / "tmp" / "html-desktop" / "acceptance"
    base.mkdir(parents=True, exist_ok=True)
    root = base / ("run-" + str(time.time_ns()))
    (root / "config").mkdir(parents=True)
    shutil.copyfile(repo / "config/default.yaml", root / "config/default.yaml")
    (root / "config/llm.local.yaml").write_text("llm:\n  api_key: test-key-never-sent\n  model: deepseek-flash\n", encoding="utf-8")
    paths = Paths.build(root=root)
    files = base / "inputs"
    files.mkdir(exist_ok=True)
    image = Image.new("RGB", (720, 480), "#d5e5f5")
    ImageDraw.Draw(image).text((40, 40), "Yuanjing HTML desktop file test", fill="black")
    image_path = files / "sample-image.png"
    image.save(image_path)
    archive_path = files / "sample-materials.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for index, color in enumerate(("#d5e5f5", "#e7dbc8", "#d1decf")):
            frame = Image.new("RGB", (320, 220), color)
            output = io.BytesIO()
            frame.save(output, "JPEG")
            archive.writestr(f"photos/image-{index}.jpg", output.getvalue())
    events, calls = [], []

    async def runner(paths, kind, emit, options):
        calls.append(kind)
        with AppContext.create(load_config(paths)) as ctx:
            cid = options["conversation_id"]
            store = Conversations(ctx.db)
            mid = store.add(cid, "user", options["request"], status="pending")
            for file in options.get("attachment_paths", []):
                item = import_file(ctx.paths, Path(file))
                Attachments(ctx.db).add(item, cid)
                Attachments(ctx.db).bind([item["id"]], cid, mid)
                build_workspace(ctx, item)
                refresh_attachment(ctx, item)
            emit({"type": "assigned", "agent": "steward", "name": "源镜"})
            if "追加测试" in options["request"]:
                arrived = asyncio.Event()
                async def accept(text):
                    next_id = store.add(cid, "user", text)
                    emit({"type": "steer_done", "accepted": True, "text": text, "message_id": next_id})
                    arrived.set()
                options["control"].activate(accept)
                emit({"type": "codex_ready", "ready": True})
                await arrived.wait()
            if "确认测试" in options["request"]:
                from scout.tools.registry import ToolSpec
                spec = ToolSpec("html_confirmation_test", "界面确认测试", "", {"type": "object"}, level="confirm")
                approved = await options["broker"].confirmer(emit)(spec, "steward", {"说明": "只验证确认通道，不修改业务数据"})
                if not approved:
                    raise ValueError("确认测试没有被允许")
            if "停止测试" in options["request"]:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    ctx.db.execute("UPDATE conversation_messages SET status='cancelled' WHERE id=?", (mid,))
                    store.add(cid, "error", "界面停止测试已完成，任务没有继续执行。", status="cancelled")
                    raise
            emit({"type": "thinking", "delta": "本次为本地界面与文件传输联调，不调用在线模型。"})
            emit({"type": "tool", "phase": "start", "tool": "attachment_assets", "name": "查看完整素材目录"})
            await asyncio.sleep(.15)
            emit({"type": "tool", "phase": "done", "tool": "attachment_assets", "ok": True, "summary": "真实文件已导入并建立本地缩略图"})
            answer = "界面联调完成。\n\n已实际保存上传文件，并生成压缩包内全部图片的缩略图。\n\n| 检查 | 结果 |\n|---|---|\n| 文件传输 | 通过 |\n| 流式事件 | 通过 |\n| 历史恢复 | 已保存 |"
            for part in (answer[:20], answer[20:70], answer[70:]):
                emit({"type": "answer_delta", "delta": part})
                await asyncio.sleep(.08)
            ctx.db.execute("UPDATE conversation_messages SET status='complete' WHERE id=?", (mid,))
            store.add(cid, "assistant", answer)
            return {"message": "界面联调完成", "conversation": store.get(cid), "report_id": None}

    gateway = Gateway(paths, runner=runner)
    server = Server(create_app(paths, gateway=gateway))
    server.start()
    report = {"model_calls": 0, "checks": [], "screenshots": {}}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            url = f"http://127.0.0.1:{server.port}/#token={gateway.token}"
            page.goto(url)
            expect(page.get_by_text("今天，想完成什么？")).to_be_visible()
            expect(page.get_by_text("本地已连接", exact=True)).to_be_visible()
            page.screenshot(path=str(base / "welcome.png"))
            report["screenshots"]["welcome"] = str(base / "welcome.png")
            for name in ("素材库", "作品数据", "互动受众", "分析报告", "对标账号", "执行记录"):
                page.get_by_role("button", name=name, exact=True).click()
                expect(page.get_by_role("heading", name=name, exact=True)).to_be_visible()
            report["checks"].append({"name": "navigation", "passed": True})
            page.get_by_role("button", name="设置", exact=True).click()
            page.get_by_role("button", name="深色", exact=True).click()
            expect(page.locator("html")).to_have_attribute("data-theme", "dark")
            page.screenshot(path=str(base / "dark-settings.png"))
            report["screenshots"]["dark_settings"] = str(base / "dark-settings.png")
            page.get_by_role("button", name="浅色", exact=True).click()
            page.get_by_role("button", name="新建对话", exact=False).click()
            page.locator('input[type="file"]').set_input_files([str(image_path), str(archive_path)])
            expect(page.locator(".composer-attachments .file-tile")).to_have_count(2)
            expect(page.get_by_text("正在添加", exact=False)).to_have_count(0)
            page.get_by_role("textbox", name="发送给源镜的消息").fill("本地界面联调：请检查附件。")
            page.get_by_role("button", name="发送消息", exact=True).click()
            expect(page.locator(".assistant-message .markdown")).to_contain_text("界面联调完成", timeout=15000)
            expect(page.get_by_role("button", name="发送消息", exact=True)).to_be_visible(timeout=15000)
            expect(page.locator(".message-files .file-tile")).to_have_count(2)
            report["checks"].append({"name": "upload_send_stream", "passed": True})
            page.screenshot(path=str(base / "conversation.png"))
            report["screenshots"]["conversation"] = str(base / "conversation.png")
            page.locator(".message-files .file-main").filter(has_text="sample-image.png").click()
            expect(page.get_by_role("dialog")).to_be_visible()
            expect(page.locator(".preview-image")).to_be_visible()
            page.get_by_role("button", name="关闭", exact=True).click()
            page.locator(".message-files .file-main").filter(has_text="sample-materials.zip").click()
            expect(page.get_by_role("dialog")).to_be_visible()
            expect(page.locator(".asset-card")).to_have_count(3, timeout=10000)
            page.screenshot(path=str(base / "gallery.png"))
            report["screenshots"]["gallery"] = str(base / "gallery.png")
            page.get_by_role("button", name="关闭", exact=True).click()
            report["checks"].append({"name": "image_archive_preview", "passed": True})
            page.reload()
            expect(page.locator(".assistant-message .markdown")).to_contain_text("界面联调完成", timeout=10000)
            report["checks"].append({"name": "history_restore", "passed": True})
            transfer = page.evaluate_handle("""() => { const value = new DataTransfer(); value.items.add(new File(['opaque bytes'], 'drag-format.xyz123', { type: 'application/octet-stream' })); return value; }""")
            page.dispatch_event('.desktop-app', 'dragover', { 'dataTransfer': transfer })
            page.dispatch_event('.desktop-app', 'drop', { 'dataTransfer': transfer })
            expect(page.locator('.composer-attachments .file-tile')).to_have_count(1)
            expect(page.get_by_text('正在添加', exact=False)).to_have_count(0)
            page.locator('.composer-attachments .file-tile').hover()
            page.get_by_role('button', name='移除 drag-format.xyz123', exact=True).click()
            expect(page.locator('.composer-attachments .file-tile')).to_have_count(0)
            report["checks"].append({"name": "drag_unknown_format", "passed": True})
            page.get_by_role("textbox", name="发送给源镜的消息").fill("追加测试")
            page.get_by_role("button", name="发送消息", exact=True).click()
            expect(page.get_by_role("textbox", name="发送给源镜的消息")).to_have_attribute("placeholder", "补充要求，按 Enter 追加到当前任务…")
            page.get_by_role("textbox", name="发送给源镜的消息").fill("请保留这条追加要求")
            page.get_by_role("button", name="追加要求", exact=True).click()
            expect(page.get_by_role("button", name="发送消息", exact=True)).to_be_visible(timeout=10000)
            expect(page.locator(".user-bubble").filter(has_text="请保留这条追加要求")).to_be_visible()
            report["checks"].append({"name": "in_flight_steering", "passed": True})
            page.get_by_role("textbox", name="发送给源镜的消息").fill("确认测试")
            page.get_by_role("button", name="发送消息", exact=True).click()
            expect(page.get_by_text('允许执行「界面确认测试」？', exact=True)).to_be_visible()
            page.get_by_role('button', name='允许这次', exact=True).click()
            expect(page.get_by_role("button", name="发送消息", exact=True)).to_be_visible(timeout=10000)
            expect(page.locator('.confirmation')).to_have_count(0)
            report["checks"].append({"name": "tool_confirmation", "passed": True})
            page.get_by_role("textbox", name="发送给源镜的消息").fill("停止测试")
            page.get_by_role("button", name="发送消息", exact=True).click()
            page.get_by_role("button", name="停止生成", exact=True).click()
            expect(page.get_by_role("button", name="发送消息", exact=True)).to_be_visible(timeout=10000)
            expect(page.get_by_text("界面停止测试已完成", exact=False)).to_be_visible(timeout=10000)
            report["checks"].append({"name": "stop", "passed": True})
            report["browser_errors"] = errors
            report["verified"] = all(x["passed"] for x in report["checks"]) and not errors
            browser.close()
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        server.close()
        output = base / "report.json"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"report": str(output), "verified": report.get("verified", False), "error": report.get("error")}, ensure_ascii=False))
    return 0 if report.get("verified") else 1


if __name__ == "__main__":
    raise SystemExit(main())
