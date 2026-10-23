"""Exercise the built executable with development paths removed.

Offline mode checks native WebView2, real file grants, private API, standalone
Python/FFmpeg and the real MXC sandbox. --live additionally uses saved DeepSeek
credentials only in the child environment and always selects Flash.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[1]


def port():
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        return handle.getsockname()[1]


def stamp_zone_identifier(stage: Path) -> int:
    """模拟“从浏览器下载 zip 再解压”：每个文件都带上 Zone.Identifier。

    .NET 默认拒绝从网络位置加载程序集，这是用户机器上 pythonnet / WebView2
    初始化失败的真实原因，所以验收必须在带标记的目录上跑。
    """
    if os.name != "nt":
        return 0
    stamped = 0
    for path in stage.rglob("*"):
        if not path.is_file():
            continue
        try:
            with open(f"{path}:Zone.Identifier", "w", encoding="utf-8") as handle:
                handle.write("[ZoneTransfer]\nZoneId=3\n")
            stamped += 1
        except OSError:
            pass
    return stamped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--archive", type=Path, help="Real archive acceptance through the packaged UI (uses Flash)")
    parser.add_argument("--effort", choices=("low", "high", "max"), default="low")
    parser.add_argument("--package", type=Path, default=REPO / "dist/windows/源镜")
    args = parser.parse_args()
    if args.archive:
        args.live = True
        args.archive = args.archive.resolve(strict=True)
    stage = args.package.resolve()
    marked = stamp_zone_identifier(stage)
    directory = Path(tempfile.gettempdir()) / "yuanjing-release-qa" / ("run-" + str(time.time_ns()))
    directory.mkdir(parents=True)
    report = {"package": str(stage), "directory": str(directory), "checks": [], "model": "deepseek-flash" if args.live else None,
              "reasoning_effort": args.effort if args.live else None}
    child_env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "VIRTUAL_ENV", "SCOUT_", "DEEPSEEK", "OPENAI", "CODEX", "QT_"))}
    child_env["PATH"] = os.environ.get("SYSTEMROOT", "C:\\Windows") + "\\System32"
    child_env["LOCALAPPDATA"] = str(directory / "local")
    child_env["SCOUT_LLM__MODEL"] = "deepseek-flash"
    child_env["SCOUT_LLM__REASONING_EFFORT"] = args.effort
    secret = ""
    process = None

    def record(name, **details):
        report["checks"].append({"name": name, "passed": True, **details})
        print(name + " passed", flush=True)

    try:
        exe = stage / "源镜.exe"
        assert exe.is_file()
        assert not list(stage.rglob("Qt6*.dll")), "Qt was unexpectedly bundled"
        assert not (stage / "_internal/codex_cli_bin/bin/codex-code-mode-host.exe").exists()
        record("release_dependency_boundary")
        offline = directory / "offline.json"
        result = subprocess.run([str(exe), "--data-dir", str(directory / "offline-data"), "--self-check", str(offline)],
                                cwd=directory, env=child_env, timeout=180)
        assert result.returncode == 0, offline.read_text(encoding="utf-8") if offline.exists() else "self-check did not finish"
        verification = json.loads(offline.read_text(encoding="utf-8"))
        assert verification["frozen"] and verification["verified"]
        record("frozen_offline_runtime", checks=verification["checks"])

        inputs = directory / "inputs"
        inputs.mkdir()
        colors = ("red", "green", "blue", "yellow")
        images = []
        for index, color in enumerate(colors):
            source = inputs / f"input-{index}.png"
            picture = Image.new("RGB", (400, 280), color)
            ImageDraw.Draw(picture).text((20, 20), f"INPUT {index}", fill="black")
            picture.save(source)
            images.append(source)
        if args.archive:
            images = [args.archive]
        opaque = inputs / "任意格式.xyz123"
        opaque.write_bytes(b"opaque original bytes")
        ready = directory / "native-ready.json"
        debug_port = port()
        if args.live:
            from scout.config import load_config
            from scout.paths import Paths
            config = load_config(Paths.build(root=REPO / "desktop/userdata"))
            secret = config.llm.api_key
            if not secret:
                raise RuntimeError("No saved DeepSeek credential is available for live verification")
            child_env["SCOUT_LLM__API_KEY"] = secret
        process = subprocess.Popen([str(exe), "--data-dir", str(directory / "native-data"), "--ready-file", str(ready),
                                    "--debug-port", str(debug_port), "--attach", *map(str, images)], cwd=directory, env=child_env)
        deadline = time.monotonic() + 40
        while not ready.exists():
            assert process.poll() is None, "Native window exited during startup"
            if time.monotonic() > deadline:
                raise TimeoutError("Native service did not become ready")
            time.sleep(.1)
        connection = json.loads(ready.read_text(encoding="utf-8"))
        origin = f"http://127.0.0.1:{connection['port']}"
        record("mark_of_the_web_tolerated", stamped_files=marked)

        def api(path, body=None, method=None):
            headers = {"Authorization": "Bearer " + connection["token"]}
            if body is not None:
                headers["Content-Type"] = "application/json"
            request = urllib.request.Request(origin + "/api" + path,
                data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)

        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as playwright:
            deadline = time.monotonic() + 35
            while True:
                try:
                    browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{debug_port}")
                    break
                except Exception:
                    assert process.poll() is None
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(.2)
            context = browser.contexts[0]
            deadline = time.monotonic() + 20
            while not context.pages:
                if time.monotonic() > deadline:
                    raise TimeoutError("WebView2 page was not created")
                time.sleep(.1)
            page = context.pages[0]
            errors = []
            report["browser_errors"] = errors
            page.on("pageerror", lambda error: errors.append(str(error)))
            expect(page.get_by_text("今天，想完成什么？")).to_be_visible(timeout=20000)
            expect(page.get_by_role("button", name="最小化", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="最大化或还原", exact=True)).to_be_visible()
            expect(page.get_by_test_id("composer-attachments").get_by_test_id("file-tile")).to_have_count(len(images))
            assert page.evaluate("window.pywebview.platform") == "edgechromium"
            page.screenshot(path=str(directory / "native-window.png"))
            record("native_webview2_and_original_file_grants")
            for name in ("素材库", "作品数据", "互动受众", "分析报告", "对标账号", "执行记录"):
                page.get_by_role("button", name=name, exact=True).click()
                expect(page.get_by_role("heading", name=name, exact=True)).to_be_visible()
            page.get_by_role("button", name="工作台", exact=True).click()
            record("native_navigation")

            # Let WebView2 supply the real File object's path through its native
            # AdditionalObjects channel. Do not stub pywebviewFullPath or grant
            # arbitrary paths through a production HTTP endpoint.
            page.wait_for_function("window.__YUANJING_DROP_READY__ === true")
            page.evaluate("""() => { let input=document.createElement('input'); input.type='file'; input.id='native-drop-check'; input.style.display='none'; document.body.appendChild(input); }""")
            # Playwright's remote set_input_files may synthesize an in-memory
            # File, which WebView2 correctly refuses as a native disk grant.
            # CDP's file-path operation retains the real on-disk backing object.
            cdp = context.new_cdp_session(page)
            document = cdp.send("DOM.getDocument")
            node = cdp.send("DOM.querySelector", {"nodeId": document["root"]["nodeId"], "selector": "#native-drop-check"})
            cdp.send("DOM.setFileInputFiles", {"nodeId": node["nodeId"], "files": [str(opaque)]})
            uploads = []
            page.on("request", lambda request: uploads.append(request.url) if request.method == "PUT" and "/api/uploads" in request.url else None)
            page.evaluate("""() => { const transfer=new DataTransfer(); transfer.items.add(document.querySelector('#native-drop-check').files[0]); document.dispatchEvent(new DragEvent('drop',{dataTransfer:transfer,bubbles:true,cancelable:true})); }""")
            expect(page.get_by_test_id("composer-attachments").get_by_test_id("file-tile")).to_have_count(len(images) + 1)
            assert not uploads, "Native drop unexpectedly uploaded a second copy"
            record("native_drop_arbitrary_format_without_upload_copy")
            page.get_by_role("button", name="移除 任意格式.xyz123", exact=True).click(force=True)
            assert opaque.read_bytes() == b"opaque original bytes"

            # Host privileges remain inaccessible without the desktop token.
            denied = page.evaluate("""async () => { try { await pywebview.api.initialFiles('wrong-session-token'); return false; } catch { return true; } }""")
            assert denied
            record("native_bridge_token_boundary")
            if args.live:
                request = ("请用 workspace_skills 加载适合的工作方法，再用 workspace_python 处理这4张图片："
                    "生成 outputs/material-index.csv（记录全部原图名和尺寸）和 outputs/contact-sheet.jpg（包含全部4张图片）。"
                    "用 workspace_view 检查联系表实际内容，再用 workspace_ffmpeg 生成1秒钟128x96蓝色视频 outputs/sample.mp4。"
                    "脚本执行时请先等待8秒，以便我追加要求。最终列出实际产物。")
                if args.archive:
                    request = ("请完整分析这个压缩包。先用 attachment_assets 确认全部素材，再用 attachment_overview 完成所有未完成的联系表，"
                        "随后用 attachment_inspect 查看至少两张有代表性的原图，并查看一个视频在0秒和2秒的画面。"
                        "最后报告总文件数、图片与视频数、总览覆盖数、细看范围和实际主题；不能把缩略图和视频抽帧说成全部原件细读或音轨分析。")
                page.get_by_role("textbox", name="发送给源镜的消息").fill(request)
                page.get_by_role("button", name="发送消息", exact=True).click()
                deadline = time.monotonic() + (1800 if args.archive else 600)
                steered = False
                marker = hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:12]
                tool_names = []
                while True:
                    state = api("/job")
                    if state and state.get("state") == "running":
                        assert page.get_by_role("button", name="停止生成", exact=True).is_enabled()
                    if state:
                        tool_names = [tool.get("tool") for tool in state.get("tools", [])]
                        if not args.archive and not steered and state.get("ready") and "workspace_python" in tool_names:
                            api("/jobs/steer", {"text": f"追加要求：请生成 outputs/steer-proof.txt，文件内容为 {marker}。"}, "POST")
                            steered = True
                        if state.get("state") not in ("running",):
                            if state.get("state") != "complete":
                                raise AssertionError({"state": state.get("state"), "message": state.get("message")})
                            break
                    if time.monotonic() > deadline:
                        raise TimeoutError("Live acceptance did not finish within the observation window")
                    time.sleep(.3)
                cid = state["conversation_id"]
                from scout.paths import Paths
                from scout.db.connect import Database
                paths = Paths.build(root=directory / "native-data")
                workspace = paths.data_dir / "workspaces" / str(cid)
                if args.archive:
                    from scout.store.attachments import Attachments
                    from scout.store.attachment_workspace import AssetStore
                    from scout.attachments import IMAGES, VIDEOS
                    import zipfile
                    with zipfile.ZipFile(args.archive) as archive:
                        expected = [m for m in archive.infolist() if not m.is_dir()]
                    with Database.open(paths.db_path, read_only=True) as db:
                        item = Attachments(db).list(cid)[0]
                        store = AssetStore(db)
                        progress = store.progress(item["id"])
                        assets = store.assets(item["id"])
                        batches = store.batches(item["id"])
                    assert progress["total"] == len(expected), progress
                    assert progress["images"] == sum(Path(m.filename).suffix.lower() in IMAGES for m in expected), progress
                    assert progress["videos"] == sum(Path(m.filename).suffix.lower() in VIDEOS for m in expected), progress
                    assert progress["thumbnails"] == progress["visual_total"] == progress["overviewed"], progress
                    assert progress["inspected"] >= 3 and not progress["failed"], progress
                    assert any(a["kind"] == "video" and a["detail"] for a in assets)
                    assert sum(a["kind"] == "image" and bool(a["detail"]) for a in assets) >= 2
                    record("real_archive_complete_coverage_and_original_inspection", source_bytes=args.archive.stat().st_size,
                           progress=progress, contact_sheets=len(batches), tools=sorted(set(tool_names)))
                else:
                    assert (workspace / "outputs/material-index.csv").is_file()
                    import csv
                    with (workspace / "outputs/material-index.csv").open(encoding="utf-8-sig", newline="") as handle:
                        rows = list(csv.reader(handle))
                    assert len(rows) >= 5
                    with Image.open(workspace / "outputs/contact-sheet.jpg") as sheet:
                        assert sheet.width > 200 and sheet.height > 150
                    assert (workspace / "outputs/sample.mp4").stat().st_size > 100
                    assert steered and (workspace / "outputs/steer-proof.txt").read_text(encoding="utf-8").strip() == marker
                    assert "workspace_view" in tool_names and "workspace_ffmpeg" in tool_names
                    record("live_flash_tools_vision_artifacts_and_steering", tools=sorted(set(tool_names)), conversation_id=cid)
                page.screenshot(path=str(directory / "live-conversation.png"))
                page.reload()
                expect(page.locator('article[data-role="assistant"]')).to_be_visible(timeout=15000)
                record("native_history_restore")
            report["browser_errors"] = errors
            assert not errors
            page.get_by_role("button", name="关闭窗口", exact=True).click()
            process.wait(timeout=25)
            assert process.returncode == 0
            record("native_clean_shutdown")
        report["verified"] = True
    except Exception:
        report["verified"] = False
        report["error"] = traceback.format_exc().replace(secret, "[redacted]") if secret else traceback.format_exc()
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
        report_path = directory / "report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = Path(tempfile.gettempdir()) / "yuanjing-release-qa" / ("latest-archive.json" if args.archive else "latest-live.json" if args.live else "latest-offline.json")
        summary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"report": str(report_path), "verified": report["verified"], "error": report.get("error")}, ensure_ascii=False), flush=True)
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
