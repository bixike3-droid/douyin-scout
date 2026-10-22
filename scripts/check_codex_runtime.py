"""Exercise the real Rust engine with DeepSeek Flash and Scout's registered tools.

Credentials come from SCOUT_LLM__API_KEY or existing local configuration. Reports
contain execution evidence only. Each send launches a fresh app-server process.
"""
import argparse
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import secrets

from scout.app import AppContext
from scout.config import load_config
from scout.paths import Paths
from scout.llm import DeepSeekClient
from scout.analyze.conversation import send
from scout.tools import registry
from scout.store.attachment_workspace import AssetStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="tmp/codex-probe/live-report.json")
    parser.add_argument("--archive-report", help="Reuse an isolated check_attachment_workspace.py dataset")
    parser.add_argument("--effort", choices=("low", "high", "max"), default="low")
    parser.add_argument("--cancel-resume", action="store_true", help="Also stop a live tool and resume the same durable task")
    parser.add_argument("--cancel-only", action="store_true", help="Run just the live cancellation/resume check")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    workspace = json.loads(Path(args.archive_report).read_text(encoding="utf-8")) if args.archive_report else None
    data_base = Path(workspace["data_dir"]).parent.parent if workspace else output.parent / "data"
    paths = Paths.build(root=root, data_dir=data_base).ensure()
    config = load_config(paths)
    config = replace(config, llm=replace(config.llm, model="deepseek-flash", reasoning_effort=args.effort))
    evidence = {"provider": "deepseek", "model": "deepseek-flash", "engine": "codex", "steps": []}
    nonce, calls = secrets.token_hex(8), []
    paused = asyncio.Event()
    pause_once = True

    async def probe(ctx, values):
        nonlocal pause_once
        calls.append(values)
        if values.get("marker") == "pause" and pause_once:
            pause_once = False
            paused.set()
            await asyncio.Event().wait()
        return {"ok": True, "summary": "Runtime probe completed", "nonce": nonce}

    registry.register(registry.ToolSpec(id="runtime_probe", name="运行时验证", description="Return this test's unpredictable verification nonce.",
        parameters={"type": "object", "properties": {"marker": {"type": "string"}}, "required": ["marker"]}, handler=probe))

    def emit(event):
        if event.get("type") == "tool":
            print(json.dumps({k: event.get(k) for k in ("type", "phase", "tool", "ok", "summary")}, ensure_ascii=False), flush=True)
        elif event.get("type") == "codex" or event.get("message"):
            print(json.dumps({k: event.get(k) for k in ("type", "model", "message")}, ensure_ascii=False), flush=True)

    with AppContext.create(config) as ctx:
        async def cancellation():
            from scout.store.chat import ChatRuns
            task = asyncio.create_task(send(ctx, DeepSeekClient(config.llm),
                'Call runtime_probe with marker="pause" and reply with its nonce only.', emit=emit))
            try:
                await asyncio.wait_for(paused.wait(), 90)
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            rid = ctx.db.scalar("SELECT MAX(id) FROM chat_runs")
            saved = ChatRuns(ctx.db).get(rid)
            result = await send(ctx, DeepSeekClient(config.llm), saved["request"],
                conversation_id=saved["conversation_id"], chat_run_id=rid, emit=emit)
            evidence["steps"].append({"name": "cancel_and_resume", "passed": saved["status"] == "cancelled"
                and not result.get("failed") and nonce in result["conversation"]["messages"][-1]["content"], "result": result})
            evidence["verified"] = all(s["passed"] for s in evidence["steps"])

        async def perform():
            if args.cancel_only:
                await cancellation()
                return
            if workspace:
                item = ctx.db.query_one("SELECT conversation_id FROM attachments WHERE id=?", (workspace["attachment_id"],))
                cid = item["conversation_id"]
                request = (f"请完整分析附件 {workspace['attachment_id']}。先用 attachment_assets 确认全部素材，再用 attachment_overview 完成所有未完成的联系表，"
                           "随后用 attachment_inspect 查看至少两张有代表性的原图，并查看一个视频在0秒和2秒的画面。"
                           "最后报告总文件数、图片与视频数、总览覆盖数、细看范围和实际主题；不能把缩略图和视频抽帧说成全部原件细读或音轨分析。")
                result = await send(ctx, DeepSeekClient(config.llm), request, conversation_id=cid, emit=emit)
                progress = AssetStore(ctx.db).progress(workspace["attachment_id"])
                evidence.update(conversation_id=cid, progress=progress, result=result)
                evidence["verified"] = not result.get("failed") and progress["overviewed"] == progress["visual_total"] and progress["inspected"] >= 3
            else:
                result = await send(ctx, DeepSeekClient(config.llm),
                    'Call runtime_probe exactly once with marker="first". Reply with the returned nonce only.', emit=emit)
                cid = result["conversation"]["id"]
                first = result["conversation"]["messages"][-1]["content"]
                tid = ctx.db.scalar("SELECT thread_id FROM codex_sessions WHERE conversation_id=?", (cid,))
                evidence["steps"].append({"name": "tool_roundtrip", "passed": bool(calls) and nonce in first, "result": result})
                if result.get("failed"):
                    return
                result = await send(ctx, DeepSeekClient(config.llm),
                    "Repeat the verification nonce returned by runtime_probe in the previous turn. Do not call tools.",
                    conversation_id=cid, emit=emit)
                second = result["conversation"]["messages"][-1]["content"]
                tid2 = ctx.db.scalar("SELECT thread_id FROM codex_sessions WHERE conversation_id=?", (cid,))
                evidence["steps"].append({"name": "fresh_process_resume", "passed": tid == tid2 and nonce in second and len(calls) == 1, "result": result})
                evidence["verified"] = all(s["passed"] for s in evidence["steps"])
                evidence["thread_id"] = tid
                if args.cancel_resume:
                    await cancellation()
        try:
            asyncio.run(perform())
        except KeyboardInterrupt:
            evidence["interrupted"] = True
        except Exception as exc:
            evidence["error"] = str(exc).replace(config.llm.api_key, "[redacted]") if config.llm.api_key else str(exc)
        finally:
            output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"report": str(output), "verified": evidence.get("verified", False)}, ensure_ascii=False), flush=True)
    return 0 if evidence.get("verified") else 1


if __name__ == "__main__":
    raise SystemExit(main())
