"""Run the real local archive-to-contact-sheet path in an isolated data directory."""
import argparse
import json
import asyncio
from pathlib import Path

from scout.app import AppContext
from scout.config import load_config
from scout.paths import Paths
from scout.store.conversation import Conversations
from scout.store.attachments import Attachments
from scout.store.attachment_workspace import AssetStore
from scout.attachments import import_file
from scout.attachment_workspace import build_workspace, refresh_attachment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    parser.add_argument("--output", required=True)
    parser.add_argument("--analyse", action="store_true")
    parser.add_argument("--inspect", nargs="*", default=[])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    paths = Paths.build(root=root, data_dir=Path(args.output)).ensure()
    with AppContext.create(load_config(paths)) as ctx:
        store = Attachments(ctx.db)
        previous = ctx.db.query_one("SELECT id,conversation_id FROM attachments ORDER BY created_at DESC LIMIT 1")
        if previous:
            item = store.get(previous["id"], previous["conversation_id"])
        else:
            conversation_id = Conversations(ctx.db).create("本地素材索引验收")
            item = import_file(paths, Path(args.archive))
            store.add(item, conversation_id)
        def emit(event):
            print(event.get("message", ""), flush=True)
        progress = build_workspace(ctx, item, emit)
        refresh_attachment(ctx, item)
        if args.analyse:
            from scout.llm import DeepSeekClient
            from scout.llm.tracked import TrackedClient
            from scout.attachment_workspace import overview, inspect_assets
            client = TrackedClient(DeepSeekClient(ctx.config.llm), ctx.db, item["conversation_id"], run_ref="workspace-validation")
            async def analyse():
                result = await overview(ctx, client, item, "逐项浏览本包全部素材，记录实际可见场景和主题，并指出哪些内容需要查看原图；不推断人物身份或未提供的音轨。", emit)
                if args.inspect and result["overviewed"]:
                    await inspect_assets(ctx, client, item, args.inspect, "读取画面实际内容及可辨认文字，说明不确定项。")
                return AssetStore(ctx.db).progress(item["id"])
            progress = asyncio.run(analyse())
        report = {"attachment_id": item["id"], "progress": progress,
                  "sheets": AssetStore(ctx.db).batches(item["id"]), "data_dir": str(paths.data_dir)}
        report["local_index_verified"] = progress["thumbnails"] == progress["visual_total"] and not progress["failed"]
        report["online_overview_verified"] = progress["overviewed"] == progress["visual_total"] and not progress["failed"]
        output = Path(args.output) / "workspace-report.json"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"report": str(output), "progress": progress}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
