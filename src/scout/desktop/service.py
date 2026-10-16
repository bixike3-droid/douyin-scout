"""Desktop operations. Every call owns its database connection."""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
import yaml

from ..app import AppContext
from ..config import load_config
from ..db.connect import Database
from ..paths import Paths
from ..store.desktop import DesktopStore
from ..store.enterprise import EnterpriseStore


class DesktopService:
    def __init__(self, paths: Paths):
        self.paths = paths

    def initialize(self):
        with AppContext.create(load_config(self.paths)):
            pass
        data = self.overview()
        data["enterprise"] = self.enterprise_workspace()
        return data

    def overview(self):
        with Database.open(self.paths.db_path, read_only=True) as db:
            data = DesktopStore(db).overview()
            data["self"] = dict(data["self"]) if data["self"] else {}
        data["paths"] = {"root": str(self.paths.root), "db": str(self.paths.db_path)}
        data["settings"] = self.settings()
        from .actions import login_status
        data["login"] = login_status(self.paths)
        return data

    def page(self, view, search="", page=0, segment="raw"):
        with Database.open(self.paths.db_path, read_only=True) as db:
            return DesktopStore(db).page(view, search, page, segment)

    def benchmarks(self):
        from ..store.benchmark import Benchmarks
        with Database.open(self.paths.db_path, read_only=True) as db:
            store = Benchmarks(db)
            accounts = store.list()
            for account in accounts:
                account["works"] = store.works(account["sec_uid"], limit=20)
        return accounts

    def add_benchmark(self, text):
        from ..store.benchmark import Benchmarks, parse_sec_uid
        sec_uid = parse_sec_uid(text)
        if not sec_uid:
            raise ValueError("无法识别：请粘贴对标账号的主页链接，或直接粘贴 sec_uid")
        with Database.open(self.paths.db_path) as db:
            created = Benchmarks(db).add(sec_uid)
        return {"created": created, "sec_uid": sec_uid}

    def remove_benchmark(self, sec_uid):
        from ..store.benchmark import Benchmarks
        with Database.open(self.paths.db_path) as db:
            Benchmarks(db).remove(sec_uid)

    def enterprise_workspace(self):
        with Database.open(self.paths.db_path, read_only=True) as db:
            return EnterpriseStore(db).workspace()

    def save_enterprise(self, profile):
        with Database.open(self.paths.db_path) as db:
            EnterpriseStore(db).save_profile(profile)
            return EnterpriseStore(db).workspace()

    def enterprise_report(self, report_id):
        with Database.open(self.paths.db_path, read_only=True) as db:
            return EnterpriseStore(db).report(report_id)

    def conversation(self, conversation_id):
        from ..store.conversation import Conversations
        with Database.open(self.paths.db_path, read_only=True) as db:
            return Conversations(db).get(conversation_id)

    def revise_enterprise(self, report_id, content, reason, reviewed):
        with Database.open(self.paths.db_path) as db:
            EnterpriseStore(db).revise(report_id, content, reason, reviewed)
            return EnterpriseStore(db).report(report_id)

    def save_enterprise_metrics(self, data):
        with Database.open(self.paths.db_path) as db:
            EnterpriseStore(db).save_metrics(data)
            return EnterpriseStore(db).workspace()

    def settings(self):
        cfg = load_config(self.paths)
        key = cfg.llm.api_key
        return {"configured": bool(key), "model": cfg.llm.model,
                "masked": key[:6] + "…" + key[-4:] if len(key) > 12 else ("已设置" if key else "未设置"),
                "config_file": str(self.paths.config_dir / "llm.local.yaml"),
                "quick_works_limit": cfg.targets.quick_works_limit,
                "browser": cfg.browser.channel or "Chromium"}

    def hot_board(self):
        """抓取抖音实时热点并做 AI 可用性评估（同步入口，供后台任务调用）。"""
        from ..analyze.hotboard import load_hot_board
        cfg = load_config(self.paths)

        async def run():
            ctx = AppContext.create(cfg)
            try:
                return await load_hot_board(ctx)
            finally:
                if ctx.session is not None:
                    await ctx.session.stop()
                ctx.close()

        try:
            return asyncio.run(run())
        except Exception as exc:  # noqa: BLE001 —— 失败也返回失败态给面板
            return {"error": f"热点获取失败：{type(exc).__name__}：{str(exc)[:140]}", "fetched_at": ""}

    def save_settings(self, api_key: str, model: str):
        target = self.paths.config_dir / "llm.local.yaml"
        data = yaml.safe_load(target.read_text(encoding="utf-8")) if target.exists() else {}
        data = {} if data is None else data
        if not isinstance(data, dict) or not isinstance(data.get("llm", {}), dict):
            raise ValueError("现有配置格式错误，请检查配置文件")
        model = model.strip()
        if not model:
            raise ValueError("模型名称不能为空")
        llm = dict(data.get("llm", {}))
        if api_key.strip():
            llm["api_key"] = api_key.strip()
        llm.update({"provider": "deepseek", "model": model})
        data["llm"] = llm
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".llm-", suffix=".yaml", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return self.settings()
