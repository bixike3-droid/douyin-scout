"""Real sandbox execution, generated-file lifecycle, steering and branch isolation."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path

import pytest
from PIL import Image

from scout.codex.runtime import executable, server, CodexError
from scout.codex.control import RunControl
from scout.config import LLMConfig
from scout.store.conversation import Conversations
from scout.store.attachments import Attachments
from scout.store.attachment_workspace import AssetStore
from scout.attachments import import_file
from scout.tools import workspace
from scout.analyze.codex_sessions import copy_conversation


def setup(ctx):
    ctx.tool_conversation_id = Conversations(ctx.db).create("workspace")
    ctx.chat_run_id = None
    ctx.tool_emit = lambda event: None
    ctx.config = replace(ctx.config, llm=LLMConfig(api_key="offline-test-key", model="deepseek-flash"))


def test_native_sandbox_runs_python_protects_originals_and_removes_credentials(ctx, tmp_path):
    try:
        executable()
    except CodexError:
        pytest.skip("Codex CLI not installed")
    setup(ctx)
    image = tmp_path / "original.jpg"
    Image.new("RGB", (45, 30), "red").save(image)
    item = import_file(ctx.paths, image)
    Attachments(ctx.db).add(item, ctx.tool_conversation_id)
    blocked = ctx.paths.root / "outside-sandbox.txt"
    code = '''
import os,json
from pathlib import Path
from PIL import Image
assert "DEEPSEEK_API_KEY" not in os.environ
m=json.loads(Path(os.environ["SCOUT_INPUT_MANIFEST"]).read_text(encoding="utf-8"))
with Image.open(m["attachments"][0]["path"]) as im:
    im.resize((90,60)).save("result.png")
Path("report.csv").write_text("name,width\\nimage,90\\n",encoding="utf-8")
print("unicode: 完成")
'''
    async def run():
        async with server(ctx.paths, ctx.config.llm) as rpc:
            ctx.codex_rpc = rpc
            result = await workspace._python(ctx, {"code": code})
            assert result["ok"], result
            assert {a["name"] for a in result["artifacts"]} == {"result.png", "report.csv"}
            assert "完成" in result["stdout"]
            large = await workspace._python(ctx, {"code": "print('x'*300000)"})
            assert len(large["stdout"]) == 12000
            full = workspace.local_path(ctx, large["logs"]["stdout"])
            assert full.stat().st_size > 300000
            denied = await workspace._python(ctx, {"code": f"from pathlib import Path\nPath({str(blocked)!r}).write_text('forbidden')"})
            assert not denied["ok"] and not blocked.exists(), denied
    asyncio.run(run())
    assert image.exists()
    with Image.open(workspace.root(ctx) / "result.png") as result:
        assert result.size == (90, 60)


def test_artifact_rescan_keeps_message_binding_and_scopes_access(ctx):
    setup(ctx)
    file = workspace.root(ctx) / "table.csv"
    file.write_text("x,y\n1,2\n", encoding="utf-8")
    saved = workspace.scan_artifacts(ctx)[0]
    mid = Conversations(ctx.db).add(ctx.tool_conversation_id, "assistant", "file generated")
    ctx.db.execute("UPDATE workspace_artifacts SET message_id=? WHERE id=?", (mid, saved["id"]))
    assert workspace.scan_artifacts(ctx)[0]["message_id"] == mid
    assert Conversations(ctx.db).get(ctx.tool_conversation_id)["messages"][-1]["attachments"][0]["generated"]
    with pytest.raises(ValueError):
        workspace.local_path(ctx, "../../secret")
    ctx.tool_conversation_id = Conversations(ctx.db).create("other")
    with pytest.raises(ValueError):
        workspace._resolve_read(ctx, {"artifact_id": f"W{saved['id']}"})


def test_branch_copies_evidence_without_copying_original_bytes_or_progress_mutations(ctx, tmp_path):
    setup(ctx)
    cid = ctx.tool_conversation_id
    mid = Conversations(ctx.db).add(cid, "user", "analyse file")
    source = tmp_path / "sample.txt"
    source.write_text("original evidence", encoding="utf-8")
    item = import_file(ctx.paths, source)
    Attachments(ctx.db).add(item, cid)
    Attachments(ctx.db).bind([item["id"]], cid, mid)
    AssetStore(ctx.db).index(item["id"], [{"name": "sample.txt", "kind": "text"}])
    session = {"agent": "steward", "provider_url": "https://api.deepseek.com", "model": "deepseek-flash", "tools_digest": "current"}
    branch = copy_conversation(ctx, cid, "new-engine-thread", session)
    cloned = Attachments(ctx.db).list(branch["id"])[0]
    assert cloned["id"] != item["id"] and cloned["relative_path"] == item["relative_path"]
    assert cloned["message_id"] != mid
    AssetStore(ctx.db).update(cloned["id"], "A0001", detail="branch observation")
    assert AssetStore(ctx.db).get(item["id"], "A0001")["detail"] == ""
    assert branch["codex"] and branch["chat_run"] is None


def test_control_accepts_cross_thread_submission_and_stops_after_close():
    control, observed = RunControl(), []
    async def run():
        done = asyncio.Event()
        async def handler(text):
            observed.append(text)
            done.set()
        control.activate(handler)
        assert await asyncio.to_thread(control.submit, "focus on video")
        await asyncio.wait_for(done.wait(), 1)
        await control.close()
        assert not control.submit("too late")
    asyncio.run(run())
    assert observed == ["focus on video"]


def test_skills_are_discoverable_and_readable_without_loading_every_body(ctx):
    result = asyncio.run(workspace._skills(ctx, {}))
    assert len(result["data"]) == 3 and all("content" not in e for e in result["data"])
    loaded = asyncio.run(workspace._skills(ctx, {"name": "yuanjing-materials"}))
    assert loaded["ok"] and "attachment_assets" in loaded["content"]
