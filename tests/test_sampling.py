"""体量自适应抽样策略：预算规则、配置接线与随机抽样。"""
import random

from scout.collect.likers import LikersCollector
from scout.collect.sampling import budget, budget_for, sample_rows


def test_budget_small_medium_huge():
    assert budget(10) == 10          # 体量小 → 全采
    assert budget(30) == 30          # 阈值上沿仍全采
    assert budget(31) == 20          # 超过阈值 → 保底抽样
    assert budget(50) == 20          # 50 → 20（用户示例）
    assert budget(100) == 40
    assert budget(10000) == 100      # 爆款 → 封顶 100（用户示例）
    assert budget(250) == 100


def test_budget_unknown_and_invalid_default_to_probe():
    assert budget(None) == 20
    assert budget(0) == 20
    assert budget(-5) == 20
    assert budget("abc") == 20


def test_budget_custom_thresholds():
    assert budget(80, ratio=0.25, floor=10, cap=50, all_below=10) == 20
    assert budget(500, ratio=0.25, floor=10, cap=50, all_below=10) == 50
    assert budget(8, ratio=0.25, floor=10, cap=50, all_below=10) == 8


def test_sample_rows_random_bounded_and_reproducible():
    rows = list(range(100))
    assert sample_rows(rows, 200) == rows      # 预算 ≥ 存量 → 全返
    assert sample_rows(rows, 0) == []
    picked = sample_rows(rows, 20, rng=random.Random(7))
    assert len(picked) == 20 and picked == sorted(picked) and set(picked) <= set(rows)
    assert sample_rows(rows, 20, rng=random.Random(7)) == picked   # 同种子可复现
    assert sample_rows(rows, 20, rng=random.Random(8)) != picked   # 不同种子不同样本


def test_likers_budget_follows_work_volume(ctx):
    ctx.works.upsert({"aweme_id": "big", "author_sec_uid": "owner", "digg_count": 10000})
    ctx.works.upsert({"aweme_id": "small", "author_sec_uid": "owner", "digg_count": 10})
    collector = LikersCollector(ctx)
    assert collector.max_items({"target": "big"}) == 100        # 大名单 → 封顶
    assert collector.max_items({"target": "small"}) == 10       # 小名单 → 全采
    assert collector.max_items({"target": "small", "_item_limit": 5}) == 5   # 显式覆盖优先
    assert collector.max_items({"target": "missing"}) == 20     # 未知作品 → 保底探一层
    assert budget_for(ctx.config.targets, 50) == 20
