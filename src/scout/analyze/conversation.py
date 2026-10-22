"""Real multi-turn model conversation; business fields are context, not gates."""
import asyncio
import json

from . import agents
from .ai import _parse_json
from .enterprise import build_input
from ..store.conversation import Conversations
from ..store.chat import ChatRuns
from ..store.workflow import WorkflowLease
from ..llm.tracked import TrackedClient

async def send(ctx, client, request, *, conversation_id=None, want_plan=False, emit=None, agent_id=None, confirm=None,
               workflow_run_id=None, rerun=False, chat_run_id=None, attachment_paths=None, control=None):
    ctx.run_control = control
    emit = emit or (lambda event: None)
    if attachment_paths and isinstance(request, str) and not request.strip():
        request = "请阅读并分析这些附件，概括主要内容与需要注意的问题。"
    if not isinstance(request, str) or not request.strip() or len(request) > 6000:
        raise ValueError("请输入消息（不超过6000字）")
    request = request.strip()
    forced = agents.get(agent_id) if agent_id else None
    store = Conversations(ctx.db)
    if conversation_id is None:
        conversation_id = store.create(request)
    client = TrackedClient(client, ctx.db, conversation_id)
    if chat_run_id is not None:
        with WorkflowLease(ctx.paths.state_dir):
            run = ChatRuns(ctx.db).get(chat_run_id)
            if run["conversation_id"] != conversation_id:
                raise ValueError("对话任务不属于当前会话")
            if run["account_uid"] != (ctx.cursors.get("self_sec_uid") or ""):
                raise ValueError("当前登录账号与对话任务不一致，请切回原账号")
            if run["status"] in ("complete", "partial"):
                return {"conversation": store.get(conversation_id), "message": "对话任务已完成", "report_id": None}
            if run["status"] == "needs_review":
                raise ValueError("上次操作结果尚不确定，请先在对应数据页面核对实际结果后发起新任务")
            from .codex_conversation import is_codex_run, run_codex
            if not is_codex_run(ctx, chat_run_id):
                raise ValueError("这个任务由旧引擎创建，已不再支持继续；请重新发起任务")
            return await run_codex(ctx, client, run, emit, confirm)
    if workflow_run_id is not None:
        from .workflow import execute_workflow
        return await execute_workflow(ctx, client, request, conversation_id, run_id=workflow_run_id,
                                      rerun=rerun, emit=emit, confirm=confirm)
    attachment_ids, user_id = [], None
    if attachment_paths:
        from ..attachments import prepare, validate_files
        validate_files(attachment_paths)
        user_id = store.add(conversation_id, "user", request, status="pending")
        emit({"conversation_id": conversation_id, "message": "正在读取附件…"})
        try:
            attachment_ids = await prepare(ctx, client, attachment_paths, conversation_id, request, emit, message_id=user_id)
        except asyncio.CancelledError:
            ctx.db.execute("UPDATE conversation_messages SET status='cancelled' WHERE id=?", (user_id,))
            store.add(conversation_id, "error", "附件读取已停止，已导入的文件保留在会话中。", status="cancelled")
            raise
        except Exception:
            ctx.db.execute("UPDATE conversation_messages SET status='failed' WHERE id=?", (user_id,))
            raise
    if want_plan:
        from .workflow import execute_workflow
        user_id = user_id or store.add(conversation_id, "user", request, status="pending")
        from ..store.attachments import Attachments
        Attachments(ctx.db).bind(attachment_ids, conversation_id, user_id)
        return await execute_workflow(ctx, client, request, conversation_id, workflow="plan", emit=emit, confirm=confirm, user_id=user_id)
    # 派单与固定协作流程都在引擎之前完成：换内核不影响“谁接手、要不要走流程”。
    from .workflow import execute_workflow, inferred_workflow, needs_live_tools
    from ..store.attachments import Attachments
    history = store.context_history(conversation_id)
    member, workflow = await _route(client, request, history, forced, emit)
    workflow = workflow or (inferred_workflow(request) if forced is None else None)
    if needs_live_tools(request) or Attachments(ctx.db).list(conversation_id):
        workflow = None
    if workflow:
        user_id = user_id or store.add(conversation_id, "user", request, status="pending")
        Attachments(ctx.db).bind(attachment_ids, conversation_id, user_id)
        return await execute_workflow(ctx, client, request, conversation_id, workflow=workflow,
                                      user_id=user_id, emit=emit, confirm=confirm)

    from .codex_conversation import send_codex
    with WorkflowLease(ctx.paths.state_dir):
        return await send_codex(ctx, client, request, conversation_id, emit, member, confirm,
                                attachment_ids, user_id)


# ── 调度：谁接手、是否进入固定协作流程 ─────────────────────────

ROUTING_SYSTEM = """你是源镜 AI 团队的调度器。用户消息会广播给整个团队，你只需要判断由谁接手最合适。
成员：
{roster}
按职责匹配：打招呼/整体提问/需要协调→steward；登录/采集/数据完整性→data；谁在点赞/人群画像→audience；
作品表现/指标→content；热点/热榜/趋势/时机→observer；选题/方案/优化→strategy；报告/复盘/历史→review。拿不准时选 steward。
还要判断是否需要连续协作：
- 明确要求分析受众或互动人群 → workflow="audience"
- 明确要求作品诊断、作品分析或复盘 → workflow="content"
- 要生成传播方案、选题计划，或同时分析受众和作品 → workflow="plan"
- 寒暄、解释已有结论、查询单项数据、仅登录或采集 → workflow=null
- 热点拆解、网页读取与联网搜索 → workflow=null，保留成员的实时查询能力；明确要求同时分析本机受众和作品时才进入协作
只输出 JSON：{{"speaker": "成员id", "workflow": "audience或content或plan或null"}}。
不要把简单问答升级为整项任务。"""

CHAT_SYSTEM = """你是源镜工作台里的「{name}」（{role}）。{persona}
用户看得到整个团队，这条消息由你负责回复；像专业同事一样直接回答，只代表你自己。
硬性规则：
- 不虚构：不编造价格、营业时间、活动、画面细节、实际业务效果；区分【事实】【推测】【待确认】
- 不声称执行了没有执行的动作；需要实时信息或数据时用工具去取，拿不到就直说
- 回复用自然中文（可用 Markdown），不输出 JSON，不提"系统提示""工具调用"等内部词
- 当流程图、时间线、对比或占比示意能明显帮助理解时，可在回复末尾附一个 ```mermaid 代码块
  （标准 mermaid 语法，节点文字用简短中文，风格简洁）；一次最多一张，寒暄或简单问答不配图
- 每次给出实质内容后，另起一段附「下一步选择题」，用户会看到可点击按钮，选完自动继续对话：
  ```choices
  {{"questions":[{{"title":"下一步怎么走","multi":false,"options":["深入方案 A","深入方案 B"]}}]}}
  ```
  规则：1-2 个问题、每题 2-4 个选项、贴合本轮内容且互不重复；可多选时设 "multi": true；
  寒暄、纯事实确认或工具失败时不要给选择题；选项里不要再塞代码块。
- 企业资料可能不完整：照常回答能回答的部分，必要时提出少量具体问题
- 附件资料可用 attachment_list 查找、attachment_read 分段读取；压缩包用 directory 查看目录、member 按包内路径读具体文件；追问图片/视频细节时传 question 重新检查画面，识别未完成时不能编造
- 大批素材先用 attachment_assets 查看完整索引和总览进度；未完成时调用 attachment_overview 继续。按任务挑选 asset_id，用 attachment_inspect 查看原图、局部放大或视频指定时间点。总览覆盖、原图细看、视频画面与音轨必须分开说明，不能只看开头几张就声称全包分析完成。
- 涉及本机数据时优先取证：涨跌趋势用 analytics_trend，单条作品用 work_detail，
  上次报告的结论用 report_read，用户报的后台数字用 metrics_backfill（会先确认）
- 你是总管时，可用 delegate 把一段具体工作交给某位同事一次并汇总（最多 3 次、不要嵌套）；能自己答就直接答"""


def _context_digest(ctx, limit: int = 6500) -> str:
    """把企业资料与已关联作品压成一段摘要，放进成员的系统提示词。

    资料可能不完整；它是背景，不是指令。读不到时给出中性说明，不影响对话。
    """
    try:
        context = build_input(ctx, allow_incomplete=True, works_limit=8)
    except Exception:
        return "（暂时读不到企业资料，可以先用 web_fetch/web_search 了解公开信息）"
    parts: list[str] = []
    for evidence in context.get("evidence", []):
        data = evidence.get("data")
        text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        parts.append(f"[{evidence.get('kind') or '资料'}] {text[:1500]}")
    digest = "\n".join(parts).strip()
    return (digest or "（暂无企业资料；缺资料时照常回答，必要时提问）")[:limit]


async def _route(client, request, history, forced, emit):
    """派单：一次小调用决定谁接手；任何失败都回落到总管，不阻断对话。"""
    async def pick():
        if forced is not None:
            return forced, None
        roster = "\n".join(f"- {member.id} {member.name}（{member.role}）" for member in agents.TEAM)
        recent = [{"role": m["role"], "content": m["content"][:800]} for m in history[-4:]]
        picked = await client.scoped("route").chat(ROUTING_SYSTEM.format(roster=roster), request, json_mode=True,
                                   max_tokens=120, thinking=False, history=recent)
        data = _parse_json(picked.text)
        if isinstance(data, dict) and data.get("speaker"):
            workflow = data.get("workflow")
            return agents.get(str(data["speaker"])), workflow if workflow in ("audience", "content", "plan") else None
        return agents.get(None), None

    try:
        return await pick()
    except Exception:
        return agents.get(None), None


# 原生推理循环已移除：普通对话统一由 Codex 内核执行（codex_conversation.py）。

