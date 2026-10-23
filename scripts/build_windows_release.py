"""Build the self-contained WebView2 desktop distribution without Qt or UPX.

Run with the project's venv. Outputs are isolated from the original Qt release.
Build dependencies: .[windows-desktop,workspace-python] and PyInstaller.
"""
from __future__ import annotations

import argparse
from collections import deque
import hashlib
from importlib import metadata
from importlib.util import find_spec
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tomllib
import zipfile

REPO = Path(__file__).resolve().parents[1]
STAGE = REPO / "dist/windows/源镜"
VERSION = "0.11.0"


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def copy_tree(source, target):
    shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", "tests", "test", "__tests__", "demos", "examples"))


def python_runtime():
    """Ship a normal interpreter and zipped standard library, no installation needed."""
    target = STAGE / "runtime/python"
    target.mkdir(parents=True, exist_ok=True)
    base = Path(sys.base_prefix)
    dll = f"python{sys.version_info.major}{sys.version_info.minor}"
    for name in ("python.exe", "pythonw.exe", f"{dll}.dll", "python3.dll", "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt"):
        source = base / name
        if source.is_file():
            shutil.copy2(source, target / name)
    for source in (base / "DLLs").iterdir():
        if source.suffix.lower() in (".pyd", ".dll") and not source.name.lower().startswith(("_tkinter", "tcl", "tk8", "_test")):
            shutil.copy2(source, target / source.name)
    with zipfile.ZipFile(target / f"{dll}.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted((base / "Lib").rglob("*.py")):
            relative = file.relative_to(base / "Lib")
            if not any(part in {"site-packages", "__pycache__", "test", "tests", "idlelib", "tkinter", "turtledemo", "ensurepip", "venv"} for part in relative.parts):
                archive.write(file, relative.as_posix())
    (target / f"{dll}._pth").write_text(f"{dll}.zip\n.\nLib/site-packages\nimport site\n", encoding="utf-8")
    packages = target / "Lib/site-packages"
    packages.mkdir(parents=True, exist_ok=True)
    for name in ("PIL", "openpyxl", "et_xmlfile", "docx", "lxml", "reportlab", "charset_normalizer", "xlsxwriter", "typing_extensions"):
        spec = find_spec(name)
        if spec is None or spec.origin is None:
            raise RuntimeError(f"Missing workspace Python dependency: {name}")
        source = Path(spec.origin)
        if source.name == "__init__.py":
            copy_tree(source.parent, packages / name)
        else:
            shutil.copy2(source, packages / source.name)
    # Exercise the shipped interpreter with no Python installed on PATH.
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "SCOUT_", "DEEPSEEK", "OPENAI", "CODEX"))}
    clean_env["PATH"] = os.environ.get("SYSTEMROOT", "C:\\Windows") + "\\System32"
    subprocess.run([str(target / "python.exe"), "-I", "-X", "utf8", "-c",
        "import csv,sqlite3,ssl,zipfile,PIL,openpyxl,docx,reportlab,xlsxwriter; print('Standalone Python OK')"],
        env=clean_env, cwd=target, check=True)


def dependency_licenses():
    from packaging.requirements import Requirement
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    requirements = project["dependencies"] + project["optional-dependencies"]["windows-desktop"] + project["optional-dependencies"]["workspace-python"]
    pending, seen, inventory = deque(requirements), set(), []
    directory = STAGE / "licenses"
    directory.mkdir(exist_ok=True)
    while pending:
        request = Requirement(pending.popleft())
        if request.marker and not request.marker.evaluate({"extra": ""}):
            continue
        name = request.name.lower().replace("_", "-")
        if name in seen:
            continue
        seen.add(name)
        dist = metadata.distribution(name)
        record = {"name": dist.metadata["Name"], "version": dist.version,
                  "license": dist.metadata.get("License-Expression") or dist.metadata.get("License"),
                  "homepage": dist.metadata.get("Home-page"), "project_urls": dist.metadata.get_all("Project-URL") or []}
        inventory.append(record)
        for file in dist.files or []:
            relative = Path(str(file))
            if any(word in relative.name.lower() for word in ("license", "copying", "notice")) and relative.suffix.lower() not in (".py", ".pyc", ".pyd", ".exe"):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    destination = directory / name / relative.name
                    destination.parent.mkdir(exist_ok=True)
                    shutil.copy2(source, destination)
        pending.extend(dist.requires or [])
    shutil.copy2(REPO / "LICENSE", directory / "源镜-LICENSE.txt")
    shutil.copy2(REPO / "THIRD_PARTY.md", directory / "THIRD_PARTY.md")
    (directory / "dependencies.json").write_text(json.dumps(sorted(inventory, key=lambda r: r["name"]), ensure_ascii=False, indent=2), encoding="utf-8")


def build():
    import PyInstaller.__main__
    work = REPO / "build/windows-release"
    work.mkdir(parents=True, exist_ok=True)
    options = [str(REPO / "desktop-html/windows.py"), "--name", "源镜", "--noconfirm", "--clean",
        "--onedir", "--windowed", "--noupx", "--optimize", "0", "--distpath", str(STAGE.parent),
        "--workpath", str(work), "--specpath", str(work), "--paths", str(REPO / "src"),
        "--icon", str(REPO / "src/scout/desktop/assets/yuanjing.ico"),
        "--version-file", str(REPO / "scripts/windows_version.txt")]
    for source, dest in (("config/default.yaml", "config"), ("src/scout/desktop/assets", "scout/desktop/assets"),
                         ("src/scout/db/migrations", "scout/db/migrations"), ("src/scout/skills", "scout/skills"),
                         ("desktop-html/dist", "desktop-html/dist")):
        options += ["--add-data", f"{REPO / source};{dest}"]
    for package in ("playwright", "pypdfium2", "pypdfium2_raw", "py7zr", "pillow_heif", "codex_cli_bin"):
        options += ["--collect-all", package]
    for module in ("uvicorn.logging", "uvicorn.loops.asyncio", "uvicorn.protocols.http.h11_impl",
                   "uvicorn.protocols.websockets.websockets_sansio_impl", "uvicorn.lifespan.on", "webview.platforms.edgechromium"):
        options += ["--hidden-import", module]
    for module in ("PySide6", "PyQt5", "PyQt6", "qtpy", "tkinter", "matplotlib", "numpy", "pandas", "scipy", "IPython", "notebook",
                   "pytest", "setuptools", "pip", "imageio_ffmpeg", "scout.web_desktop.window"):
        options += ["--exclude-module", module]
    PyInstaller.__main__.run(options)
    # This integration exposes only host-owned dynamic tools. Code Mode is
    # explicitly disabled in prepare_runtime; its separate host is not used.
    (STAGE / "_internal/codex_cli_bin/bin/codex-code-mode-host.exe").unlink(missing_ok=True)
    python_runtime()
    import imageio_ffmpeg
    media = STAGE / "runtime/ffmpeg"
    media.mkdir(parents=True, exist_ok=True)
    shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), media / "ffmpeg.exe")
    # Keep upstream Codex binaries byte-for-byte; their signatures are checked
    # during release verification. Strip no binaries and apply no executable packer.
    dependency_licenses()
    (STAGE / "使用说明.txt").write_text(
        "源镜 Windows 桌面版 " + VERSION + "\n\n解压整个文件夹后双击 源镜.exe。不要只复制 exe。\n"
        "首次使用：设置 → 模型，保存自己的 DeepSeek API Key。默认使用 Flash。\n"
        "支持直接拖入图片、视频、文档和压缩包。脚本与视频处理环境已随包提供。\n"
        "界面使用 Microsoft WebView2；Windows 11 通常已有，缺失时请安装微软 WebView2 Evergreen Runtime。\n"
        "采集使用系统 Microsoft Edge。需要自行扫码登录，不附带任何账号或登录态。\n"
        "个人数据位于 %LOCALAPPDATA%\\douyin-scout，升级与卸载不主动删除这些数据。\n"
        "旧版数据可用命令行 --data-dir 指向原数据根目录；请先备份，避免两版同时操作同一数据。\n"
        "源代码与许可证随包提供。发布文件的扫描、签名与验收结果见 release-verification.json。\n",
        encoding="utf-8-sig")
    source_archive = STAGE / "源代码.zip"
    with zipfile.ZipFile(source_archive, "w", zipfile.ZIP_DEFLATED) as archive:
        for folder in ("src", "scripts", "tests", "desktop-html/src", "desktop-html/public"):
            for file in sorted((REPO / folder).rglob("*")):
                if file.is_file() and "__pycache__" not in file.parts:
                    archive.write(file, file.relative_to(REPO).as_posix())
        for name in ("LICENSE", "README.md", "THIRD_PARTY.md", "pyproject.toml", "config/default.yaml", "desktop-html/package.json",
                     "desktop-html/package-lock.json", "desktop-html/index.html", "desktop-html/windows.py"):
            archive.write(REPO / name, name)


def finalize():
    entries = [{"path": f.relative_to(STAGE).as_posix(), "bytes": f.stat().st_size, "sha256": digest(f)}
               for f in sorted(STAGE.rglob("*")) if f.is_file() and f.name != "files.sha256.json"]
    (STAGE / "files.sha256.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    target = STAGE.parent / f"源镜-{VERSION}-Windows-x64.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=7) as archive:
        for file in sorted(STAGE.rglob("*")):
            if file.is_file():
                archive.write(file, "源镜/" + file.relative_to(STAGE).as_posix())
    checksum = digest(target)
    target.with_suffix(".zip.sha256.txt").write_text(checksum + "  " + target.name + "\n", encoding="utf-8")
    print(json.dumps({"package": str(target), "bytes": target.stat().st_size, "sha256": checksum,
                      "installed_bytes": sum(e["bytes"] for e in entries)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--finalize-only", action="store_true")
    parser.add_argument("--no-zip", action="store_true")
    args = parser.parse_args()
    os.chdir(REPO)
    if not args.finalize_only:
        build()
    if not args.no_zip:
        finalize()
