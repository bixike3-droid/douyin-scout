"""测试夹具。

刻意只用标准库可跑的模块（config / db / store / guard / parse），
不引入 playwright —— 核心逻辑必须能在任何环境里被验证。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scout.app import AppContext
from scout.config import (
    AppConfig,
    BrowserConfig,
    Config,
    GuardConfig,
    StorageConfig,
    TargetsConfig,
    TierConfig,
)
from scout.paths import Paths

REPO_DEFAULT_YAML = Path(__file__).resolve().parents[1] / "config" / "default.yaml"


@pytest.fixture()
def paths(tmp_path):
    """临时项目根，但复制真实的 default.yaml，保证测的是真配置。"""
    root = tmp_path
    (root / "config").mkdir(parents=True, exist_ok=True)
    if REPO_DEFAULT_YAML.is_file():
        shutil.copy(REPO_DEFAULT_YAML, root / "config" / "default.yaml")
    return Paths.build(root=root).ensure()


@pytest.fixture()
def config(paths):
    return Config(
        paths=paths,
        app=AppConfig(max_tasks_per_run=10),
        tiers={
            "a": TierConfig(name="a", mode="logged_in", daily_request_quota=5),
            "b": TierConfig(name="b", mode="anonymous", daily_request_quota=100),
        },
        guard=GuardConfig(),
        browser=BrowserConfig(),
        storage=StorageConfig(),
        targets=TargetsConfig(notice_url="https://www.douyin.com/notification"),
    )


@pytest.fixture()
def ctx(config):
    context = AppContext.create(config)
    try:
        yield context
    finally:
        context.close()
