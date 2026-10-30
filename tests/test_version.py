"""版本号只能有一个来源，其他位置必须与它一致。"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

from scout.version import __version__, __version_info__

ROOT = Path(__file__).resolve().parents[1]


def test_version_info_matches_version_string():
    assert ".".join(str(part) for part in __version_info__[:3]) == __version__


def test_other_version_sources_agree():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == __version__

    windows = re.sub(r"\s+", "", (ROOT / "scripts" / "windows_version.txt").read_text(encoding="utf-8"))
    compact = "(" + ",".join(str(part) for part in __version_info__) + ")"
    assert f"filevers={compact}" in windows
    assert f"prodvers={compact}" in windows
    assert __version__ in windows


def test_build_script_reads_version_instead_of_hardcoding():
    source = (ROOT / "scripts" / "build_windows_release.py").read_text(encoding="utf-8")
    assert "VERSION = project_version()" in source
    assert not re.search(r'^VERSION\s*=\s*"\d', source, re.M)
