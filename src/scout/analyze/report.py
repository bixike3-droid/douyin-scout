"""画像分析。全部基于本地 SQLite，不联网。"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from ..app import AppContext
from ..util import local_hm

# 粉丝量级分档。用于把"谁是我的核心互动者"变得可读。
FANS_BUCKETS = (
    (0, 100, "素人 <100"),
    (100, 1_000, "小号 100-1k"),
    (1_000, 10_000, "腰部 1k-1w"),
    (10_000, 100_000, "中腰 1w-10w"),
    (100_000, 1_000_000, "头部 10w-100w"),
    (1_000_000, None, "大V >100w"),
)


def _bucket(fans: int | None) -> str:
    if fans is None:
        return "未知"
    for lo, hi, label in FANS_BUCKETS:
        if fans >= lo and (hi is None or fans < hi):
            return label
    return "未知"


def overview(ctx: AppContext) -> dict[str, Any]:
    return {
        "users": ctx.users.stats(),
        "works": ctx.works.stats(),
        "like_edges": ctx.like_edges.stats(),
        "notice_coverage": ctx.notice_runs.coverage(),
        "raw": ctx.archive.stats(),
        "requests": ctx.telemetry.request_stats(hours=24),
        "tasks": ctx.tasks.stats(),
        "quota": ctx.quota.snapshot(),
        "circuit": ctx.circuit.snapshot(),
    }


def analyze_users(ctx: AppContext, *, limit: int = 5000) -> dict[str, Any]:
    """对点赞人做画像。样本量不足时结果里会明确标注。"""
    rows = ctx.users.list(limit=limit, order="like_count")
    sample = len(rows)

    fans_dist: dict[str, int] = {}
    region_dist: dict[str, int] = {}
    gender_dist: dict[str, int] = {"未知": 0, "男": 0, "女": 0}
    verified = 0
    with_fans = 0

    for row in rows:
        bucket = _bucket(row.get("follower_count"))
        fans_dist[bucket] = fans_dist.get(bucket, 0) + 1
        if row.get("follower_count") is not None:
            with_fans += 1
        region = (row.get("region") or "未知").strip() or "未知"
        region_dist[region] = region_dist.get(region, 0) + 1
        gender = {1: "男", 2: "女"}.get(row.get("gender"), "未知")
        gender_dist[gender] = gender_dist.get(gender, 0) + 1
        if row.get("is_verified"):
            verified += 1

    # 回关候选：互动次数高 + 自身有一定影响力 + 不是大 V（大 V 不会回关小号）
    candidates = [
        r for r in rows
        if (r.get("like_count") or 0) >= 2
        and (r.get("follower_count") or 0) >= 1_000
        and (r.get("follower_count") or 0) < 1_000_000
    ][:50]

    hashtags = _top_hashtags(ctx, limit=20)
    hours = _work_hours(ctx)

    return {
        "sample_size": sample,
        "fans_with_data": with_fans,
        "fans_distribution": dict(sorted(fans_dist.items(), key=lambda kv: -kv[1])),
        "region_top": dict(sorted(region_dist.items(), key=lambda kv: -kv[1])[:15]),
        "gender": gender_dist,
        "verified_count": verified,
        "verified_ratio": round(verified / sample, 4) if sample else None,
        "top_likers": rows[:30],
        "reengage_candidates": candidates,
        "top_hashtags": hashtags,
        "work_hours": hours,
        "caveats": _caveats(ctx, sample),
    }


def _caveats(ctx: AppContext, sample: int) -> list[str]:
    out: list[str] = []
    if sample == 0:
        out.append("样本量为 0：先跑 `scout run` 采集，再来看分析。")
    elif sample < 100:
        out.append(f"样本量仅 {sample}，分布类结论不可靠，只能当线索。")
    missing = ctx.db.scalar(
        "SELECT COUNT(*) FROM users WHERE follower_count IS NULL", default=0
    )
    if missing:
        out.append(f"有 {missing} 个用户缺粉丝数（主页未采到或该字段被裁剪），它们被归入「未知」桶。")

    # 通知接口能给的字段和不能给的，要说清楚，否则"全是未知"看着像 bug
    no_gender = int(ctx.db.scalar("SELECT COUNT(*) FROM users WHERE gender IS NULL", default=0))
    no_region = int(ctx.db.scalar("SELECT COUNT(*) FROM users WHERE region = ''", default=0))
    if no_gender or no_region:
        out.append(
            f"性别 {no_gender} 人、地区 {no_region} 人未知："
            f"这两个字段**通知接口里没有**，需要档 B 采主页才能补齐。"
            f"粉丝数 / 抖音号 / 认证在通知接口里已经有了，不用额外请求。"
        )

    wall = ctx.db.scalar(
        "SELECT COUNT(*) FROM users WHERE profile_state IN ('blocked','login_wall')", default=0
    )
    if wall:
        out.append(f"有 {wall} 个用户主页返回空或撞登录墙，画像存在系统性缺口。")

    pending = int(ctx.db.scalar(
        "SELECT COUNT(*) FROM users WHERE profile_state = 'pending'", default=0
    ))
    if pending:
        out.append(
            f"还有 {pending} 个用户的资料处于待采状态（档 B 未跑）。"
            f"跑 `scout run --tier b` 可补齐性别、地区、作品列表。"
        )
    return out


def _top_hashtags(ctx: AppContext, limit: int = 20) -> list[dict[str, Any]]:
    import collections
    import json

    counter: collections.Counter = collections.Counter()
    for row in ctx.db.query(
        "SELECT hashtags_json FROM works WHERE hashtags_json != '[]' LIMIT 5000"
    ):
        try:
            for tag in json.loads(row["hashtags_json"]) or []:
                if isinstance(tag, str) and tag:
                    counter[tag] += 1
        except Exception:
            continue
    return [{"tag": t, "n": n} for t, n in counter.most_common(limit)]


def _work_hours(ctx: AppContext, tz: str = "Asia/Shanghai") -> dict[str, int]:
    counts = {str(h): 0 for h in range(24)}
    for row in ctx.db.query(
        "SELECT create_time FROM works WHERE create_time IS NOT NULL LIMIT 5000"
    ):
        try:
            counts[str(local_hm(int(row["create_time"]), tz))] += 1
        except Exception:
            continue
    return counts


def render_markdown(data: dict[str, Any], *, title: str = "用户分析报告") -> str:
    lines = [f"# {title}", ""]
    lines.append(f"样本量：**{data['sample_size']}**（其中 {data['fans_with_data']} 个有粉丝数）")
    lines.append("")

    if data.get("caveats"):
        lines.append("## 先读这些")
        for item in data["caveats"]:
            lines.append(f"- ⚠️ {item}")
        lines.append("")

    lines.append("## 粉丝量级分布")
    lines.append("")
    for bucket, n in data["fans_distribution"].items():
        ratio = n / data["sample_size"] if data["sample_size"] else 0
        lines.append(f"- {bucket}：{n}（{ratio:.1%}）")
    lines.append("")

    lines.append("## 性别 / 认证")
    lines.append("")
    gender = data["gender"]
    lines.append(f"- 男 {gender.get('男', 0)} / 女 {gender.get('女', 0)} / 未知 {gender.get('未知', 0)}")
    lines.append(f"- 认证账号 {data['verified_count']}")
    lines.append("")

    lines.append("## 地区 Top")
    lines.append("")
    for region, n in data["region_top"].items():
        lines.append(f"- {region}：{n}")
    lines.append("")

    lines.append("## 互动最频繁的点赞人 Top 30")
    lines.append("")
    lines.append("| 昵称 | 抖音号 | 粉丝 | 点赞次数 |")
    lines.append("|------|--------|------|----------|")
    for row in data["top_likers"]:
        lines.append(
            f"| {row.get('nickname') or '（未采到）'} | {row.get('douyin_id') or '-'} "
            f"| {row.get('follower_count') if row.get('follower_count') is not None else '-'} "
            f"| {row.get('like_count')} |"
        )
    lines.append("")

    lines.append("## 回关候选（互动 ≥2 次 且 粉丝 1k~100w）")
    lines.append("")
    if not data["reengage_candidates"]:
        lines.append("（无。可能是样本太小，或大部分互动来自素人）")
    else:
        lines.append("| 昵称 | 粉丝 | 点赞次数 | sec_uid |")
        lines.append("|------|------|----------|---------|")
        for row in data["reengage_candidates"][:20]:
            lines.append(
                f"| {row.get('nickname') or '-'} | {row.get('follower_count')} "
                f"| {row.get('like_count')} | `{row.get('sec_uid')}` |"
            )
    lines.append("")

    lines.append("## 作品发布时段分布（本地时间）")
    lines.append("")
    for hour in sorted(data["work_hours"], key=lambda h: int(h)):
        n = data["work_hours"][hour]
        if n:
            lines.append(f"- {int(hour):02d}:00 — {n}")
    lines.append("")

    if data["top_hashtags"]:
        lines.append("## 高频话题标签")
        lines.append("")
        lines.append("　".join(f"{t['tag']}({t['n']})" for t in data["top_hashtags"]))
        lines.append("")

    return "\n".join(lines)


def export_csv(ctx: AppContext, path: str | Path, *, table: str = "users") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if table == "users":
        rows = ctx.users.list(limit=100_000, order="like_count")
    elif table == "works":
        rows = ctx.works.list(limit=100_000)
    elif table == "like_edges":
        rows = ctx.db.rows_as_dicts("SELECT * FROM like_edges ORDER BY discovered_at DESC LIMIT 100000")
    else:
        raise ValueError(f"不支持的导出表：{table}")

    with target.open("w", encoding="utf-8-sig", newline="") as fh:
        if not rows:
            fh.write("（无数据）\n")
            return target
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return target
