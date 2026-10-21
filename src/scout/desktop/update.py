"""应用内更新：查最新 Release、下载 zip、退出后替换并重启。

设计取舍：
- 只在**打包后的 exe** 里启用；源码运行时只提示版本，不做自动替换。
- 网络请求 6 秒超时，失败静默（不能因为查更新拖慢启动）。
- 更新动作由外部脚本完成：程序退出后用批处理解压覆盖再重启，
  因为运行中的 exe 在 Windows 上无法自我覆盖。
- 刻意**不用 PowerShell**（尤其不用 Hidden + ExecutionPolicy Bypass + 自删除），
  那套组合是杀软判定「脚本化下载器」的典型特征，会直接把程序当木马清掉。
  改用 .cmd + 系统自带 tar，窗口可见，行为对用户透明。
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
# 自建版本源优先：发布方在服务器上放一个 JSON，国内访问比 GitHub 稳定得多。
# 先 http 再 https：站点目前没有证书，https 会直接连不上；两个都失败才回退 GitHub。
FEED_URLS = (
    "http://douyin.baodaoxiaoyuan.cn/update/version.json",
    "https://douyin.baodaoxiaoyuan.cn/update/version.json",
)
FEED_URL = FEED_URLS[0]
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
    """读自建版本源（http/https 都试），失败再回退 GitHub；都失败返回 None。"""
    for url in FEED_URLS:
        payload = _read_json(url, timeout)
        if isinstance(payload, dict) and payload.get("version"):
            info = _from_feed(payload)
            # 下载地址统一按「版本源所在协议」走：站点没有证书时别把 https 带进来
            base = url.split("/update/")[0]
            zip_url = str(info.get("zip_url") or "")
            if zip_url.startswith("/"):
                zip_url = base + zip_url
            elif zip_url.startswith(base.split("://")[1]):
                zip_url = base.split("://")[0] + "://" + zip_url.split("://", 1)[1]
            elif zip_url.startswith("https://" + base.split("://")[1].split("/")[0]):
                zip_url = "http://" + zip_url[len("https://"):]
            info["zip_url"] = zip_url
            info["feed_url"] = url
            return info
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


def _updater_script(archive: Path, target: Path, stage: Path) -> str:
    """生成更新批处理内容（逻辑全 ASCII，避免代码页问题）。"""
    unzip = stage / "unzip"
    lines = [
        "@echo off",
        "title Yuanjing updater",
        "echo Installing Yuanjing update, please wait...",
        "echo.",
        "timeout /t 3 /nobreak >nul",
        'cd /d "%~dp0"',
        f'if exist "{unzip}" rmdir /s /q "{unzip}"',
        f'mkdir "{unzip}" 2>nul',
        f'tar -xf "{archive}" -C "{unzip}"',
        "if errorlevel 1 goto fail",
        'set "SRC="',
        'for /f "delims=" %%f in (\'dir /b /s "unzip\\*.exe" 2^>nul\') do if not defined SRC (set "SRC=%%~dpf" & set "APPEXE=%%f")',
        'if not defined SRC set "SRC=unzip\\"',
        f'echo Copying files to "{target}" ...',
        'xcopy "%SRC%*" "' + str(target) + '\\" /E /Y /I >nul',
        "if errorlevel 1 goto fail",
        'for %%f in ("%APPEXE%") do set "EXENAME=%%~nxf"',
        'if not defined EXENAME set "EXENAME=' + EXE_NAME + '"',
        f'echo Starting "{target}\\%EXENAME%" ...',
        'start "" "' + str(target) + '\\%EXENAME%"',
        "exit /b 0",
        ":fail",
        "echo.",
        "echo Update failed. Please unzip the downloaded file manually.",
        "pause",
        "exit /b 1",
        "",
    ]
    return "\r\n".join(lines)


def launch_updater(archive: Path, target: Path) -> bool:
    """写一个可见的批处理：等本进程退出 → 解压覆盖 → 重启。"""
    if os.name != "nt":
        return False
    stage = Path(tempfile.mkdtemp(prefix="yuanjing-update-"))
    script = stage / "apply_update.cmd"
    try:
        script.write_text(_updater_script(archive, target, stage), encoding="mbcs")
    except (LookupError, UnicodeEncodeError):
        script.write_text(_updater_script(archive, target, stage), encoding="utf-8", errors="replace")
    try:
        subprocess.Popen(["cmd", "/c", str(script)], close_fds=True)
        return True
    except OSError:
        return False


def friendly_size(value: int) -> str:
    if value <= 0:
        return ""
    if value >= 1024 * 1024:
        return f"{value / 1048576:.0f} MB"
    return f"{value / 1024:.0f} KB"
