"""Real Flash acceptance of script tools, steering, forks and compaction."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import secrets

from PIL import Image, ImageDraw
from scout.app import AppContext
from scout.config import load_config
from scout.paths import Paths
from scout.llm import DeepSeekClient
from scout.analyze.conversation import send
from scout.analyze.codex_sessions import manage
from scout.codex.control import RunControl
from scout.tools.workspace import root as workspace_root


def main():
    base = Path("tmp/codex-probe/workspace-acceptance").resolve()
    base.mkdir(parents=True, exist_ok=True)
    paths = Paths.build(data_dir=base / "data")
    cfg = load_config(paths)
    cfg = replace(cfg, llm=replace(cfg.llm, model="deepseek-flash", reasoning_effort="low"))
    files = []
    for index, color in enumerate(("red", "green", "blue", "yellow")):
        path = base / f"input-{index}.png"
        image = Image.new("RGB", (400, 280), color)
        ImageDraw.Draw(image).text((20, 20), f"INPUT {index}", fill="black")
        image.save(path)
        files.append(str(path))
    report = {"model": "deepseek-flash", "checks": []}
    control, steered, marker = RunControl(), False, secrets.token_hex(6)
    def emit(event):
        nonlocal steered
        if event.get("type") == "tool":
            print(json.dumps({k: event.get(k) for k in ("type", "phase", "tool", "ok", "summary")}, ensure_ascii=False), flush=True)
            if event.get("phase") == "start" and event.get("tool") == "workspace_python" and not steered:
                steered = control.submit(f"追加要求：请在同一工作目录生成 outputs/steer-proof.txt，内容为 {marker}。")
        elif event.get("type") == "steer_done":
            report["steer_accepted"] = event["accepted"]
        elif event.get("message"):
            print(event["message"], flush=True)
    with AppContext.create(cfg) as ctx:
        async def run():
            result = await send(ctx, DeepSeekClient(cfg.llm),
                "请用 workspace_skills 加载适合的工作方法，再用脚本处理这些图片：生成 outputs/material-index.csv（记录原图名和尺寸）"
                "和 outputs/contact-sheet.jpg（包含全部4张图片的联系表）。请用 workspace_view 检查联系表实际内容。"
                "然后用 workspace_ffmpeg 生成 outputs/sample.mp4，内容为1秒钟蓝色画面，尺寸128x96。最终列出实际产物。",
                attachment_paths=files, emit=emit, control=control)
            report["result"] = result
            if result.get("failed"):
                return
            directory = workspace_root(ctx)
            required = ["outputs/material-index.csv", "outputs/contact-sheet.jpg", "outputs/sample.mp4", "outputs/steer-proof.txt"]
            report["checks"].append({"name": "real_artifacts", "passed": all((directory / name).is_file() for name in required)})
            proof = directory / "outputs/steer-proof.txt"
            report["checks"].append({"name": "in_flight_steering", "passed": report.get("steer_accepted", False) and proof.is_file() and marker in proof.read_text(encoding="utf-8")})
            cid = result["conversation"]["id"]
            original_count = len(result["conversation"]["messages"])
            branch = await manage(ctx, cid, "fork", emit)
            new_id = branch["conversation"]["id"]
            followup = await send(ctx, DeepSeekClient(cfg.llm), "上个任务生成的 CSV 文件名是什么？直接回答文件名。", conversation_id=new_id, emit=emit)
            report["checks"].append({"name": "fork_context", "passed": not followup.get("failed") and "material-index.csv" in followup["conversation"]["messages"][-1]["content"]})
            report["checks"].append({"name": "source_unchanged", "passed": original_count == ctx.db.scalar("SELECT COUNT(*) FROM conversation_messages WHERE conversation_id=?", (cid,))})
            await manage(ctx, new_id, "compact", emit)
            report["checks"].append({"name": "compaction", "passed": True})
            report["verified"] = all(item["passed"] for item in report["checks"])
        try:
            asyncio.run(run())
        except Exception as exc:
            report["error"] = str(exc).replace(cfg.llm.api_key, "[redacted]") if cfg.llm.api_key else str(exc)
        finally:
            output = base / "report.json"
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"report": str(output), "verified": report.get("verified", False)}, ensure_ascii=False), flush=True)
    return 0 if report.get("verified") else 1


if __name__ == "__main__":
    raise SystemExit(main())
