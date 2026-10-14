"""Desktop operations. Every call owns its database connection."""
from __future__ import annotations

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
