"""Persistent desktop configuration and startup paths."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from ..paths import Paths, find_project_root


def prepare_runtime(root: Path | None = None) -> Paths:
    if root is None:
        root = Path(os.environ.get("SCOUT_ROOT") or (
            Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "douyin-scout"
        ))
    root = root.resolve()
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    bundle = Path(getattr(sys, "_MEIPASS", find_project_root()))
    source = bundle / "config" / "default.yaml"
    destination = config_dir / "default.yaml"
    # Ship defaults; leave persistent user overrides intact.
    if source.resolve() != destination.resolve():
        shutil.copyfile(source, destination)
    os.environ["SCOUT_ROOT"] = str(root)
    os.environ["SCOUT_DATA_DIR"] = str(root / "data")
    os.environ["SCOUT_CONFIG_DIR"] = str(config_dir)
    os.environ.setdefault("SCOUT_ACCOUNT", "main")
    return Paths.build()
