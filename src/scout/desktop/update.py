"""应用内更新：查最新 Release、下载 zip、退出后替换并重启。

设计取舍：
- 只在**打包后的 exe** 里启用；源码运行时只提示版本，不做自动替换。
- 网络请求 6 秒超时，失败静默（不能因为查更新拖慢启动）。
- 更新动作由外部脚本完成：程序退出后用 PowerShell 解压覆盖再重启，
  因为运行中的 exe 在 Windows 上无法自我覆盖。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

REPO = "bixike3-droid/douyin-scout"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
# 自建版本源优先：发布方在服务器上放一个 JSON，国内访问比 GitHub 稳定得多
FEED_URL = "https://douyin.baodaoxiaoyuan.cn/update/version.json"
PAGE = f"https://github.com/{REPO}/releases"
_HEADERS = {"User-Agent": "yuanjing-updater", "Accept": "application/vnd.github+json"}

EXE_NAME = "源镜.exe"


def current_version() -> str:
    try:
        from ..version import __version__
        return str(__version__)
    except Exception:      # noqa: BLE001
        return "0.0.0"


def parse_version(text: str) -> tuple[int, ...]:
    digits: list[int] = []
    for chunk in str(text).lstrip("vV").replace("-", ".").split("."):
        number = "".join(ch for ch in chunk if ch.isdigit())
        digits.append(int(number) if number else 0)
    while len(digits) < 3:
        digits.append(0)
    return tuple(digits[:4])


def is_newer(remote: str, local: str | None = None) -> bool:
    return parse_version(remote) > parse_version(local or current_version())


def _read_json(url: str, timeout: float) -> dict | None:
    try:
        with urlopen(Request(url, headers=_HEADERS), timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (URLError, OSError, ValueError):
        return None


def _from_feed(payload: dict) -> dict:
    """自建 version.json 的字段映射（字段名保持简单，方便手工维护）。"""
    return {
        "version": str(payload.get("version") or "").lstrip("vV"),
        "name": payload.get("name") or f"v{payload.get('version', '')}",
        "notes": payload.get("notes") or "",
        "page": payload.get("page") or FEED_URL,
        "zip_url": payload.get("zip_url") or "",
        "zip_size": int(payload.get("size") or 0),
        "sha256": str(payload.get("sha256") or "").lower(),
        "prerelease": bool(payload.get("prerelease")),
        "source": "feed",
    }


def _from_github(payload: dict) -> dict:
    assets = payload.get("assets") or []
    zip_asset = next((item for item in assets if str(item.get("name", "")).endswith(".zip")), None)
    digest = str((zip_asset or {}).get("digest") or "")
    return {
        "version": str(payload.get("tag_name") or "").lstrip("vV"),
        "name": payload.get("name") or payload.get("tag_name") or "",
        "notes": payload.get("body") or "",
        "page": payload.get("html_url") or PAGE,
        "zip_url": (zip_asset or {}).get("browser_download_url", ""),
        "zip_size": int((zip_asset or {}).get("size") or 0),
        "sha256": digest.replace("sha256:", "").lower(),
        "prerelease": bool(payload.get("prerelease")),
        "source": "github",
    }


def fetch_latest(timeout: float = 6.0) -> dict | None:
    """先读自建版本源，失败再回退 GitHub；都失败返回 None（界面静默处理）。"""
    payload = _read_json(FEED_URL, timeout)
    if isinstance(payload, dict) and payload.get("version"):
        return _from_feed(payload)
    payload = _read_json(API_LATEST, timeout)
    if isinstance(payload, dict):
        return _from_github(payload)
    return None


def download(url: str, dest: Path, timeout: float = 60.0, sha256: str = "") -> bool:
    if not url:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    try:
        with urlopen(Request(url, headers=_HEADERS), timeout=timeout) as response:
            total = 0
            with part.open("wb") as handle:
                while True:
                    chunk = response.read(262144)
                    if not chunk:
                        break
                    handle.write(chunk)
                    total += len(chunk)
        if total < 1024:
            part.unlink(missing_ok=True)
            return False
        if sha256:
            import hashlib
            digest = hashlib.sha256(part.read_bytes()).hexdigest()
            if digest.lower() != sha256.lower():
                part.unlink(missing_ok=True)
                return False
        part.replace(dest)
        return True
    except (URLError, OSError):
        part.unlink(missing_ok=True)
        return False


def install_dir() -> Path | None:
    """打包后返回 exe 所在目录；源码运行时返回 None（不支持自动更新）。"""
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve().parent


def launch_updater(archive: Path, target: Path) -> bool:
    """写一个后台脚本：等本进程退出 → 解压覆盖 → 重启。"""
    if os.name != "nt":
        return False
    stage = Path(tempfile.mkdtemp(prefix="yuanjing-update-"))
    script = stage / "apply_update.ps1"
    script.write_text(
        "$ErrorActionPreference = 'Continue'\r\n"
        "Start-Sleep -Seconds 3\r\n"
        f"Expand-Archive -LiteralPath '{archive}' -DestinationPath '{stage / 'unzip'}' -Force\r\n"
        "$src = Join-Path '{stage}' 'unzip'\r\n"
        "$inner = Join-Path $src '源镜'\r\n"
        "if (Test-Path $inner) { $src = $inner }\r\n"
        f"robocopy $src '{target}' /E /NFL /NDL /NJH /NJS /NP | Out-Null\r\n"
        f"Start-Process -FilePath (Join-Path '{target}' '{EXE_NAME}')\r\n"
        "Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue\r\n",
        encoding="utf-8-sig",
    )
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )
        return True
    except OSError:
        return False


def friendly_size(value: int) -> str:
    if value <= 0:
        return ""
    if value >= 1024 * 1024:
        return f"{value / 1048576:.0f} MB"
    return f"{value / 1024:.0f} KB"
