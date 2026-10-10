"""AI 画像分析。

把「点赞人的主页信息 + 他的作品列表」拼成 prompt，交给 DeepSeek，
产出结构化画像，并落库。

三个设计原则（都是踩过坑之后定的）：

1. **输入要采样，不能全塞。** 一个人可能有几百条作品，全塞超上下文也费钱。
   策略：点赞数 Top N + 最近 M 条（N/M 可配）。
2. **输出必须是 JSON。** 页面要渲染成卡片，自由文本没法用。
   用 `response_format: json_object` 约束。
3. **结果按输入哈希去重。** 输入没变就不重跑；改了才产生新记录。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from ..app import AppContext
from ..llm import DeepSeekClient, LLMError
from ..util import iso, sha256_bytes

PROMPT_VERSION = "v1"
TASK_PROFILE = "profile"

SYSTEM_PROFILE = """你是一名短视频内容运营分析师。你会拿到某个抖音用户的公开主页信息和作品列表，\
需要判断这个人的画像，以及他作为「我作品的点赞者」对我的价值。

只输出 JSON，不要任何解释文字、不要 markdown 代码块。字段和含义：

{
  "content_domains": ["他的内容领域，最多3个词"],
  "persona": "一句话说清这个人是谁（20字内）",
  "audience": "他的内容面向什么受众（20字内）",
  "activity_level": "高 或 中 或 低",
  "activity_reason": "判断依据，比如作品数量与更新时间（25字内）",
  "relevance_score": 1到5的整数,
  "relevance_reason": "为什么给这个分（30字内）",
  "recommended_action": "回关 或 评论互动 或 观察 或 忽略，后面跟简短理由（25字内）",
  "summary": "整体结论（40字内）"
}

relevance_score 衡量「这个人与我的内容和受众的契合度」：
5 = 同赛道同受众，值得重点互动；3 = 有部分交集；1 = 完全无关。

判断要基于给出的数据，不要编造。数据不足时降低把握而不是硬猜。"""


@dataclass
class AnalysisResult:
    ok: bool
    subject_id: str
    data: dict[str, Any] | None = None
    error: str = ""
    cached: bool = False
    tokens: int = 0
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "subject_id": self.subject_id,
            "data": self.data,
            "error": self.error,
            "cached": self.cached,
            "tokens": self.tokens,
            "duration_ms": self.duration_ms,
        }


# ── 输入构造 ─────────────────────────────────────────────────


def sample_works(ctx: AppContext, sec_uid: str, limit: int) -> list[dict[str, Any]]:
    """按点赞数取 Top N + 按时间取最近 M，去重后返回。"""
    top_n = max(0, int(ctx.config.llm.works_top_by_likes))
    recent_m = max(0, int(ctx.config.llm.works_recent))
    picked: dict[str, dict[str, Any]] = {}

    if top_n:
        for r in ctx.db.query(
            "SELECT w.* FROM works w JOIN user_work_listings l ON l.aweme_id = w.aweme_id "
            "WHERE l.sec_uid = ? ORDER BY COALESCE(w.digg_count,-1) DESC LIMIT ?",
            (sec_uid, top_n),
        ):
            picked[r["aweme_id"]] = dict(r)
    if recent_m:
        for r in ctx.db.query(
            "SELECT w.* FROM works w JOIN user_work_listings l ON l.aweme_id = w.aweme_id "
            "WHERE l.sec_uid = ? ORDER BY w.create_time DESC NULLS LAST LIMIT ?",
            (sec_uid, recent_m),
        ):
            picked.setdefault(r["aweme_id"], dict(r))
    return list(picked.values())[: max(1, limit)]


def build_user_input(ctx: AppContext, sec_uid: str) -> tuple[str, str, dict[str, Any]]:
    """返回 (摘要, 输入哈希, 结构化输入)。"""
    user = ctx.users.get(sec_uid) or {}
    works = sample_works(ctx, sec_uid, limit=40)

    lines: list[str] = ["【主页信息】"]
    lines.append(f"昵称：{user.get('nickname') or '未知'}")
    if user.get("douyin_id"):
        lines.append(f"抖音号：{user['douyin_id']}")
    if user.get("signature"):
        lines.append(f"个人简介：{user['signature']}")
    if user.get("follower_count") is not None:
        lines.append(f"粉丝数：{user['follower_count']}")
    if user.get("following_count") is not None:
        lines.append(f"关注数：{user['following_count']}")
    if user.get("aweme_count") is not None:
        lines.append(f"作品数：{user['aweme_count']}")
    if user.get("total_favorited") is not None:
        lines.append(f"获赞总数：{user['total_favorited']}")
    if user.get("region"):
        lines.append(f"地区：{user['region']}")
    if user.get("is_verified"):
        lines.append(f"认证：{user.get('verification') or '是'}")

    lines.append("")
    lines.append(f"【作品列表】共采到 {len(works)} 条（按点赞与时间采样）")
    for w in works:
        tag = (w.get("hashtags_json") or "").strip()
        lines.append(
            f"- 标题：{w.get('description') or '（无）'}"
            f"｜点赞 {w.get('digg_count', '?')}"
            f"｜评论 {w.get('comment_count', '?')}"
            f"｜时长 {w.get('duration_ms') or '?'}ms"
            + (f"｜标签 {tag}" if tag and tag != "[]" else "")
        )

    payload = {
        "profile": {
            k: user.get(k)
            for k in (
                "nickname", "douyin_id", "signature", "follower_count",
                "following_count", "aweme_count", "total_favorited", "region",
                "is_verified", "verification",
            )
        },
        "works": [
            {
                "desc": w.get("description"),
                "digg_count": w.get("digg_count"),
                "comment_count": w.get("comment_count"),
                "duration_ms": w.get("duration_ms"),
                "create_time": w.get("create_time"),
                "hashtags": w.get("hashtags_json"),
            }
            for w in works
        ],
    }
    text = "\n".join(lines)
    digest = sha256_bytes(text.encode("utf-8"))[:32]
    summary = f"{user.get('nickname') or sec_uid[:12]}：{len(works)} 条作品、粉丝 {user.get('follower_count')}"
    return text, digest, {"text": text, "digest": digest, "summary": summary, "payload": payload}


# ── 分析执行 ─────────────────────────────────────────────────


def _parse_json(text: str) -> dict[str, Any]:
    """模型偶尔会包一层 ```json，容错剥掉。"""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    try:
        data = json.loads(t)
        return data if isinstance(data, dict) else {"raw": data}
    except Exception:
        start, end = t.find("{"), t.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(t[start : end + 1])
            except Exception:
                pass
        return {}


async def analyze_user(
    ctx: AppContext,
    client: DeepSeekClient,
    sec_uid: str,
    *,
    force: bool = False,
) -> AnalysisResult:
    """分析一个点赞人。已分析过且输入未变时直接返回缓存。"""
    if not sec_uid:
        return AnalysisResult(ok=False, subject_id="", error="缺少 sec_uid")

    built = build_user_input(ctx, sec_uid)
    text, digest, meta = built

    if not force:
        cached = ctx.llm_results.find("user", sec_uid, TASK_PROFILE, PROMPT_VERSION, digest)
        if cached:
            return AnalysisResult(
                ok=True,
                subject_id=sec_uid,
                data=json.loads(cached["output_json"] or "{}"),
                cached=True,
                tokens=int(cached["prompt_tokens"] or 0) + int(cached["completion_tokens"] or 0),
            )

    try:
        reply = await client.chat(SYSTEM_PROFILE, text, json_mode=True)
    except LLMError as exc:
        return AnalysisResult(ok=False, subject_id=sec_uid, error=str(exc))

    data = _parse_json(reply.text)
    if not data:
        return AnalysisResult(
            ok=False, subject_id=sec_uid,
            error=f"模型返回无法解析为 JSON：{reply.text[:160]}",
        )

    ctx.llm_results.save(
        subject_kind="user",
        subject_id=sec_uid,
        task=TASK_PROFILE,
        prompt_version=PROMPT_VERSION,
        model=reply.model,
        input_digest=digest,
        input_summary=meta["summary"],
        output_json=json.dumps(data, ensure_ascii=False),
        raw_text=reply.text,
        prompt_tokens=reply.prompt_tokens,
        completion_tokens=reply.completion_tokens,
        duration_ms=reply.duration_ms,
    )
    ctx.db.log_event(
        "info", "llm",
        f"分析完成 {meta['summary']}｜{reply.total_tokens} tokens｜{reply.duration_ms}ms",
        {"sec_uid": sec_uid, "score": data.get("relevance_score")},
    )
    return AnalysisResult(
        ok=True, subject_id=sec_uid, data=data,
        tokens=reply.total_tokens, duration_ms=reply.duration_ms,
    )


def pending_targets(ctx: AppContext, *, force: bool = False, limit: int = 100) -> list[str]:
    """还没分析过（或输入已变）的点赞人。"""
    rows = ctx.db.query(
        "SELECT DISTINCT sec_uid FROM like_edges ORDER BY sec_uid LIMIT ?", (limit,)
    )
    out: list[str] = []
    for r in rows:
        sec_uid = r["sec_uid"]
        if force:
            out.append(sec_uid)
            continue
        built = build_user_input(ctx, sec_uid)
        existing = ctx.llm_results.find("user", sec_uid, TASK_PROFILE, PROMPT_VERSION, built[1])
        if not existing:
            out.append(sec_uid)
    return out


async def analyze_many(
    ctx: AppContext,
    client: DeepSeekClient,
    sec_uids: list[str],
    *,
    force: bool = False,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """串行分析（并发靠配置，这里保持顺序以便进度可视）。

    刻意不做高并发：DeepSeek 有速率限制，而且一个人一次调用本来就要几秒。
    """
    import asyncio

    results: list[dict[str, Any]] = []
    total = len(sec_uids)
    for idx, sec_uid in enumerate(sec_uids, 1):
        if on_progress:
            on_progress({"type": "start_item", "index": idx, "total": total, "sec_uid": sec_uid})
        res = await analyze_user(ctx, client, sec_uid, force=force)
        row = res.to_dict()
        row["index"] = idx
        row["total"] = total
        if on_progress:
            on_progress({"type": "item", **row})
        results.append(row)
        if idx < total:
            await asyncio.sleep(0.4)
    if on_progress:
        on_progress({"type": "done", "total": total,
                     "ok": sum(1 for r in results if r["ok"]),
                     "failed": sum(1 for r in results if not r["ok"])})
    return results
