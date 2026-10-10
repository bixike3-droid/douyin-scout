"""配置层测试。"""

from __future__ import annotations

from scout.config import deep_merge, load_config
from scout.paths import Paths


def test_deep_merge_recursive():
    base = {"a": 1, "tiers": {"b": {"quota": 10, "headless": True}}}
    override = {"tiers": {"b": {"quota": 20}}}
    merged = deep_merge(base, override)
    assert merged["a"] == 1
    assert merged["tiers"]["b"]["quota"] == 20
    assert merged["tiers"]["b"]["headless"] is True, "未覆盖的字段必须保留"


def test_deep_merge_list_replaced_not_appended():
    merged = deep_merge({"x": [1, 2, 3]}, {"x": [9]})
    assert merged["x"] == [9]


def test_load_config_reads_project_defaults(paths: Paths):
    cfg = load_config(paths)
    assert "b" in cfg.tiers
    assert cfg.targets.user_url_template.startswith("https://")
    assert cfg.targets.notice_url.startswith("https://www.douyin.com/")
    assert cfg.tiers["b"].min_delay_s > 0, "节流参数必须有值"


def test_default_quota_is_unlimited(paths: Paths):
    """默认不设总量上限 —— 日常采集不需要，设了只会挡住自己。"""
    cfg = load_config(paths)
    for name, tier in cfg.tiers.items():
        assert tier.daily_request_quota == 0, f"档 {name} 的默认配额应为 0（不限）"


def test_default_interactions_are_wellformed(paths: Paths):
    """交互脚本写错会让采集静默失效，配置层就要拦住。"""
    cfg = load_config(paths)
    assert cfg.interactions, "default.yaml 里应该有 interactions"
    for name, steps in cfg.interactions.items():
        assert steps, f"{name} 是空的"
        for step in steps:
            assert isinstance(step, dict) and step.get("action"), f"{name} 里有非法动作"


def test_env_override_wins(paths: Paths, monkeypatch):
    monkeypatch.setenv("SCOUT_TIERS__B__DAILY_REQUEST_QUOTA", "7")
    cfg = load_config(paths)
    assert cfg.tiers["b"].daily_request_quota == 7


def test_env_override_coerces_bool(paths: Paths, monkeypatch):
    monkeypatch.setenv("SCOUT_TIERS__B__HEADLESS", "false")
    cfg = load_config(paths)
    assert cfg.tiers["b"].headless is False


def test_local_yaml_overrides_default(paths: Paths):
    paths.local_config.write_text(
        "tiers:\n  b:\n    daily_request_quota: 3\n", encoding="utf-8"
    )
    cfg = load_config(paths)
    assert cfg.tiers["b"].daily_request_quota == 3
    assert str(paths.local_config) in cfg.sources


def test_tier_url_template():
    from scout.config import TargetsConfig

    t = TargetsConfig()
    assert t.user_url("SEC123").endswith("/user/SEC123")
