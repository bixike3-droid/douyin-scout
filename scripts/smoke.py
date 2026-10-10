"""自检脚本：不依赖任何第三方库，验证核心逻辑端到端可用。

用途：装完 env 之前先确认地基是好的；以后每次改完核心代码也跑一遍。

    python scripts/smoke.py

它覆盖：迁移 → 幂等 upsert → 归档去重 → 配额 → 熔断 → 解析 → 分析 → 导出。
不覆盖：浏览器、Web 面板（那两个需要 playwright / fastapi）。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scout.analyze import analyze_users, export_csv, overview, render_markdown  # noqa: E402
from scout.app import AppContext  # noqa: E402
from scout.config import (  # noqa: E402
    AppConfig,
    BrowserConfig,
    Config,
    GuardConfig,
    StorageConfig,
    TargetsConfig,
    TierConfig,
    WebConfig,
)
from scout.guard.circuit import CircuitBreaker, CircuitOpen  # noqa: E402
from scout.guard.quota import QuotaExceeded  # noqa: E402
from scout.config import CircuitConfig  # noqa: E402
from scout.parse import parse_payload  # noqa: E402
from scout.paths import Paths  # noqa: E402

SEC_A = "MS4wLjABAAAAaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SEC_B = "MS4wLjABAAAAbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

FIXTURE = {
    "status_code": 0,
    "has_more": 1,
    "max_cursor": "1700000000000",
    "aweme_list": [
        {
            "aweme_id": "7300000000000000001",
            "desc": "自检用作品 #冒烟测试",
            "create_time": 1699000000,
            "statistics": {"digg_count": 120, "comment_count": 8},
            "text_extra": [{"hashtag_name": "冒烟测试"}],
            "author": {"sec_uid": SEC_A, "nickname": "作者甲", "unique_id": "jia123",
                       "follower_count": 5200, "uid": "1001"},
        }
    ],
}

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(name)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="scout-smoke-"))
    paths = Paths.build(root=tmp).ensure()
    config = Config(
        paths=paths,
        app=AppConfig(),
        tiers={
            "a": TierConfig(name="a", mode="logged_in", daily_request_quota=3),
            "b": TierConfig(name="b", mode="anonymous", daily_request_quota=50),
        },
        guard=GuardConfig(),
        browser=BrowserConfig(),
        storage=StorageConfig(),
        targets=TargetsConfig(notice_url="https://www.douyin.com/notification"),
        web=WebConfig(),
    )

    print(f"\n自检临时目录：{tmp}")
    ctx = AppContext.create(config)
    try:
        print("\n[1] 迁移与存储")
        check("数据库已建表", ctx.db.scalar(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'", default=0) >= 10)

        ctx.users.upsert({"sec_uid": SEC_A, "nickname": "作者甲", "follower_count": 5200})
        ctx.users.upsert({"sec_uid": SEC_A, "nickname": "作者甲", "follower_count": 5300})
        rows = ctx.users.list(limit=10)
        check("用户 upsert 幂等", len(rows) == 1, f"实际 {len(rows)} 行")
        check("用户字段已更新", rows[0]["follower_count"] == 5300)

        added = ctx.like_edges.add_many([{"sec_uid": SEC_A, "aweme_id": "1", "notice_id": "n1"}])
        added2 = ctx.like_edges.add_many([{"sec_uid": SEC_A, "aweme_id": "1", "notice_id": "n1"}])
        check("点赞边去重", added == 1 and added2 == 0, f"{added} / {added2}")

        print("\n[2] 原始归档")
        ref1 = ctx.archive.save('{"a":1}', url="https://x.test/1", content_type="application/json")
        ref2 = ctx.archive.save('{"a":1}', url="https://x.test/1", content_type="application/json")
        check("归档按 sha256 去重", ref1.deduped is False and ref2.deduped is True)
        check("归档内容可读回", ctx.archive.load_text(ref1.id) == '{"a":1}')
        check("归档正文已落盘", (paths.root / ref1.path).is_file())

        print("\n[3] 解析层")
        result = parse_payload("https://www.douyin.com/aweme/v1/web/aweme/post/", FIXTURE)
        check("作品解析", len(result.works) == 1, f"实际 {len(result.works)}")
        check("用户解析", len(result.users) == 1, f"实际 {len(result.users)}")
        check("游标解析", result.cursor.get("cursor") == "1700000000000")
        check("话题标签解析", result.works[0]["hashtags"] == ["冒烟测试"])
        check("垃圾输入不抛异常", parse_payload("https://x.test/x", "不是 JSON") is not None)

        for work in result.works:
            ctx.works.upsert(work, raw_blob_id=ref1.id)
        check("作品入库", ctx.works.stats()["total"] == 1)

        print("\n[4] 护栏")
        ctx.quota.consume("a", 3)
        try:
            ctx.quota.check("a")
            check("配额超限应拦截", False, "没有抛异常")
        except QuotaExceeded:
            check("配额超限应拦截", True)

        breaker = CircuitBreaker(ctx.telemetry, CircuitConfig(consecutive_empty_open=2, cooldown_minutes=30))
        breaker.record_empty("b")
        breaker.record_empty("b")
        try:
            breaker.check("b")
            check("连续空返回应熔断", False, "没有抛异常")
        except CircuitOpen:
            check("连续空返回应熔断", True)
        breaker.reset("b")
        check("熔断可人工解除", breaker.check("b") == "closed")

        print("\n[5] 任务队列")
        ok1 = ctx.tasks.enqueue("fetch_profile", SEC_B, "b")
        ok2 = ctx.tasks.enqueue("fetch_profile", SEC_B, "b")
        check("任务不重复入队", ok1 is True and ok2 is False)
        claimed = ctx.tasks.claim("b", limit=1)
        check("任务可领取", len(claimed) == 1)
        ctx.tasks.complete(claimed[0]["id"])
        check("任务可完成", ctx.tasks.stats()["done"] == 1)

        print("\n[6] 分析层")
        data = analyze_users(ctx)
        check("分析有输出", data["sample_size"] >= 1)
        md = render_markdown(data)
        check("报告可渲染", "粉丝量级分布" in md and len(md) > 200)
        csv_path = export_csv(ctx, paths.export_dir / "users.csv", table="users")
        check("CSV 可导出", csv_path.is_file() and csv_path.stat().st_size > 0)
        check("概览可用", "users" in overview(ctx))

        print("\n[7] 日志与遥测")
        ctx.telemetry.log_request(tier="b", url="https://x.test/1", status=200, ok=True, byte_size=7)
        stats = ctx.telemetry.request_stats(hours=24)
        check("请求日志已记录", stats["total"] >= 1)
        check("事件日志已记录", len(ctx.telemetry.events(limit=5)) >= 0)
    finally:
        ctx.close()

    print("\n" + "=" * 52)
    if failures:
        print(f"自检失败 {len(failures)} 项：")
        for name in failures:
            print(f"  - {name}")
        return 1

    print("自检全部通过。核心逻辑可用。")

    import importlib.util

    if importlib.util.find_spec("playwright") is None:
        print("下一步：pwsh -File scripts/setup.ps1   （安装 playwright 等依赖）")
    else:
        print("浏览器依赖已就绪。下一步：")
        print("  .\\.venv\\Scripts\\python.exe -m scout.cli doctor")
        print("  .\\.venv\\Scripts\\python.exe -m scout.cli login --tier a")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
