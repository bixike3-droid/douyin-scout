"""创作者侧分析：评价我的作品、制定下一步计划。

和"点赞人画像"是两条不同的任务：

- `profile`（已有）—— 分析**每个点赞人**是谁
- `review`（本模块）—— 用点赞人的画像分布 + 我自己的作品数据，**评价我的作品**
- `plan`（本模块）—— 基于 review 的结论，给出**可执行的下一步计划**

设计要点：
1. **review 必须喂真实的受众分布**，不能只给"我有 2 个作品"。否则 AI 只能
   说些"多发优质内容"这种废话 —— 那是没有价值的输出。
2. **plan 依赖 review 的结论**，不是独立的又一次空谈。
3. 输出全部结构化，页面才能渲染成可读的卡片。
"""

from __future__ import annotations

import json
from typing import Any

from ..app import AppContext
from ..llm import DeepSeekClient, LLMError
from ..util import sha256_bytes
from .ai import TASK_PROFILE, AnalysisResult, _parse_json

PROMPT_VERSION = "v1"
TASK_REVIEW = "review"
TASK_PLAN = "plan"

SYSTEM_REVIEW = """你是一名短视频内容运营顾问。你会拿到一个创作者的\
作品数据、账号数据、以及他作品点赞者的画像分布。请对这个创作者的作品做出评价。

只输出 JSON，不要解释文字、不要 markdown。字段：

{
  "score": 1到10的整数（作品整体表现打分）,
  "overall": "整体评价（50字内）",
  "strengths": ["做得好的地方，2-3条，每条25字内"],
  "problems": ["存在的问题，2-3条，每条25字内"],
  "audience_match": "内容与受众的匹配度分析（50字内）",
  "actions": ["具体可执行的改进建议，3条，每条30字内"]
}

要求：
- 必须基于给出的数据说话，**不要编造数据里没有的信息**
- 建议要具体到"做什么"，不要写"多互动""提高质量"这种空话
- 数据量小的时候（比如只有几个作品）要明确指出"样本太少，结论仅供参考"\
，而不是假装很有把握"""

SYSTEM_PLAN = """你是一名短视频内容策划。你会拿到对一个创作者作品的评价结论\
和他的受众画像。请给出下一步的**可执行计划**。

只输出 JSON，不要解释文字、不要 markdown。字段：

{
  "positioning": "账号定位建议（30字内）",
  "topics": [
    {"title": "选题方向", "why": "为什么适合他（25字内）", "priority": "高 或 中 或 低"}
  ],
  "cadence": "发布节奏建议（30字内）",
  "engagement": ["互动策略，2-3条，每条25字内"],
  "avoid": ["应该避免的做法，1-2条，每条25字内"],
  "next_7_days": ["未来7天要做的具体事情，3条，每条25字内"]
}

要求：
- 每个选题方向都要能追溯到受众画像里的证据
- next_7_days 必须是"今天就能开始做"的具体动作
- 不要写空泛的运营术语"""


# ── 输入构造 ─────────────────────────────────────────────────


def _fan_buckets(ctx: AppContext) -> dict[str, int]:
    rows = ctx.db.query(
        """SELECT u.follower_count FROM users u
           WHERE u.sec_uid IN (SELECT sec_uid FROM like_edges)"""
    )
    buckets = {"<100": 0, "100-1k": 0, "1k-1w": 0, "1w-10w": 0, ">=10w": 0, "未知": 0}
    for r in rows:
        n = r["follower_count"]
        if n is None:
            buckets["未知"] += 1
        elif n < 100:
            buckets["<100"] += 1
        elif n < 1000:
            buckets["100-1k"] += 1
        elif n < 10000:
            buckets["1k-1w"] += 1
        elif n < 100000:
            buckets["1w-10w"] += 1
        else:
            buckets[">=10w"] += 1
    return buckets


def _liker_profiles(ctx: AppContext) -> list[dict[str, Any]]:
    """已生成的点赞人画像。"""
    out = []
    for r in ctx.llm_results.all_latest(TASK_PROFILE):
        try:
            data = json.loads(r["output_json"] or "{}")
        except Exception:
            continue
        out.append({"sec_uid": r["subject_id"], "data": data,
                    "summary": r.get("input_summary", "")})
    return out


def build_review_input(ctx: AppContext) -> tuple[str, str, str]:
    """(喂给模型的文本, 输入哈希, 摘要)"""
    mine = ctx.works.mine()
    me_uid = ctx.cursors.get("self_sec_uid") or ""
    me = ctx.users.get(me_uid) if me_uid else None

    lines = ["【我的账号】"]
    if me:
        lines.append(f"昵称：{me.get('nickname')}")
        if me.get("follower_count") is not None:
            lines.append(f"粉丝数：{me['follower_count']}")
        if me.get("aweme_count") is not None:
            lines.append(f"作品数：{me['aweme_count']}")
        if me.get("total_favorited") is not None:
            lines.append(f"累计获赞：{me['total_favorited']}")
    else:
        lines.append("（账号资料缺失）")

    lines.append("")
    lines.append(f"【我的作品】共 {len(mine)} 条")
    for w in mine:
        lines.append(
            f"- {w.get('description') or '（无标题）'}"
            f"｜点赞 {w.get('digg_count', '?')}"
            f"｜评论 {w.get('comment_count', '?')}"
            f"｜转发 {w.get('share_count', '?')}"
            f"｜时长 {(w.get('duration_ms') or 0) // 1000}s"
        )

    likers = ctx.db.rows_as_dicts(
        """SELECT u.nickname, u.follower_count, u.signature, u.douyin_id
           FROM users u WHERE u.sec_uid IN (SELECT sec_uid FROM like_edges)"""
    )
    lines.append("")
    lines.append(f"【点赞人概况】共 {len(likers)} 人")
    buckets = _fan_buckets(ctx)
    lines.append("粉丝量级分布：" + "，".join(f"{k} {v}人" for k, v in buckets.items() if v))
    with_works = ctx.db.scalar(
        "SELECT COUNT(DISTINCT sec_uid) FROM user_work_listings", default=0
    )
    lines.append(f"其中有作品数据的：{with_works} 人")

    profiles = _liker_profiles(ctx)
    if profiles:
        domains: dict[str, int] = {}
        scores: dict[int, int] = {}
        for p in profiles:
            for d in (p["data"].get("content_domains") or []):
                domains[str(d)] = domains.get(str(d), 0) + 1
            try:
                s = int(p["data"].get("relevance_score") or 0)
            except (TypeError, ValueError):
                s = 0
            if s:
                scores[s] = scores.get(s, 0) + 1
        top = sorted(domains.items(), key=lambda x: -x[1])[:8]
        lines.append("")
        lines.append(f"【点赞人画像统计】已分析 {len(profiles)} 人")
        lines.append("内容领域分布：" + "，".join(f"{k} {v}人" for k, v in top))
        lines.append(
            "与我的相关性评分分布："
            + "，".join(f"{k}分 {v}人" for k, v in sorted(scores.items(), reverse=True))
        )
        high = [p for p in profiles if int(p["data"].get("relevance_score") or 0) >= 4]
        if high:
            lines.append(f"高相关点赞人（4-5分）{len(high)} 人，样本：")
            for p in high[:6]:
                lines.append(f"  - {p['summary']}：{p['data'].get('persona', '')}")
        low = [p for p in profiles if int(p["data"].get("relevance_score") or 0) <= 2]
        if low:
            lines.append(f"低相关点赞人（1-2分）{len(low)} 人 —— 说明作品可能触达了非目标人群")
    else:
        lines.append("")
        lines.append("【点赞人画像统计】（尚未生成，请只基于作品数据分析）")

    text = "\n".join(lines)
    digest = sha256_bytes(text.encode("utf-8"))[:32]
    summary = f"作品评价：{len(mine)} 个作品、{len(likers)} 个点赞人"
    return text, digest, summary


def build_plan_input(ctx: AppContext, review_text: str) -> tuple[str, str, str]:
    """计划必须建立在评价结论之上，不是又一次空谈。"""
    review = ctx.llm_results.latest("self", "me", TASK_REVIEW)
    lines = []
    if review:
        try:
            lines.append("【对作品的评价结论】")
            lines.append(json.dumps(json.loads(review["output_json"]), ensure_ascii=False, indent=1))
        except Exception:
            pass
    if not lines:
        lines.append("【作品数据】")
        lines.append(review_text)

    lines.append("")
    lines.append("【受众画像】")
    for p in _liker_profiles(ctx)[:20]:
        d = p["data"]
        lines.append(
            f"- {p['summary']}｜领域 {'/'.join(d.get('content_domains') or [])}"
            f"｜相关性 {d.get('relevance_score')}/5｜{d.get('persona', '')}"
        )
    buckets = _fan_buckets(ctx)
    lines.append("粉丝量级分布：" + "，".join(f"{k} {v}人" for k, v in buckets.items() if v))

    text = "\n".join(lines)
    digest = sha256_bytes(text.encode("utf-8"))[:32]
    summary = "下一步计划"
    return text, digest, summary


# ── 执行 ─────────────────────────────────────────────────────


async def _run_task(
    ctx: AppContext,
    client: DeepSeekClient,
    *,
    task: str,
    system: str,
    text: str,
    digest: str,
    summary: str,
    force: bool,
) -> AnalysisResult:
    if not force:
        cached = ctx.llm_results.find("self", "me", task, PROMPT_VERSION, digest)
        if cached:
            return AnalysisResult(
                ok=True, subject_id="me",
                data=json.loads(cached["output_json"] or "{}"), cached=True,
            )
    try:
        reply = await client.chat(system, text, json_mode=True, max_tokens=2500)
    except LLMError as exc:
        return AnalysisResult(ok=False, subject_id="me", error=str(exc))

    data = _parse_json(reply.text)
    if not data:
        return AnalysisResult(
            ok=False, subject_id="me",
            error=f"模型返回无法解析为 JSON：{reply.text[:160]}",
        )
    ctx.llm_results.save(
        subject_kind="self", subject_id="me", task=task,
        prompt_version=PROMPT_VERSION, model=reply.model, input_digest=digest,
        input_summary=summary, output_json=json.dumps(data, ensure_ascii=False),
        raw_text=reply.text, prompt_tokens=reply.prompt_tokens,
        completion_tokens=reply.completion_tokens, duration_ms=reply.duration_ms,
    )
    ctx.db.log_event("info", "llm", f"{summary} 完成｜{reply.total_tokens} tokens")
    return AnalysisResult(
        ok=True, subject_id="me", data=data,
        tokens=reply.total_tokens, duration_ms=reply.duration_ms,
    )


async def analyze_review(ctx: AppContext, client: DeepSeekClient, *, force: bool = False):
    text, digest, summary = build_review_input(ctx)
    return await _run_task(
        ctx, client, task=TASK_REVIEW, system=SYSTEM_REVIEW,
        text=text, digest=digest, summary=summary, force=force,
    )


async def analyze_plan(ctx: AppContext, client: DeepSeekClient, *, force: bool = False):
    review_text, _, _ = build_review_input(ctx)
    text, digest, summary = build_plan_input(ctx, review_text)
    return await _run_task(
        ctx, client, task=TASK_PLAN, system=SYSTEM_PLAN,
        text=text, digest=digest, summary=summary, force=force,
    )
