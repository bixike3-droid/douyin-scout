"""改版本号：只在这里给一个数字，其他三处自动同步。

用法：
    python scripts/bump_version.py 0.12.0

会更新：
    src/scout/version.py         __version__ / __version_info__
    pyproject.toml              [project] version
    scripts/windows_version.txt  exe 文件属性里的四个版本字段
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "src" / "scout" / "version.py"
PYPROJECT = ROOT / "pyproject.toml"
WINDOWS_VERSION = ROOT / "scripts" / "windows_version.txt"


def parse(text: str) -> tuple[int, int, int, int]:
    match = re.fullmatch(r"\s*v?(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?\s*", text or "")
    if not match:
        raise SystemExit(f"版本号格式应为 x.y.z（收到：{text!r}）")
    major, minor, patch, build = match.groups()
    return int(major), int(minor), int(patch), int(build or 0)


def bump(version: str) -> list[Path]:
    info = parse(version)
    dotted = ".".join(str(part) for part in info[:3])

    text = VERSION_FILE.read_text(encoding="utf-8")
    text = re.sub(r'__version__\s*=\s*"[^"]*"', f'__version__ = "{dotted}"', text)
    text = re.sub(r"__version_info__\s*=\s*\([^)]*\)", f"__version_info__ = {info}", text)
    VERSION_FILE.write_text(text, encoding="utf-8", newline="\n")

    text = PYPROJECT.read_text(encoding="utf-8")
    text = re.sub(r'(?m)^version\s*=\s*"[^"]*"$', f'version = "{dotted}"', text, count=1)
    PYPROJECT.write_text(text, encoding="utf-8", newline="\n")

    text = WINDOWS_VERSION.read_text(encoding="utf-8")
    text = re.sub(r"filevers=\([^)]*\)", f"filevers={info}", text)
    text = re.sub(r"prodvers=\([^)]*\)", f"prodvers={info}", text)
    text = re.sub(r"('FileVersion',\s*')[^']*(')", rf"\g<1>{dotted}.0\g<2>", text)
    text = re.sub(r"('ProductVersion',\s*')[^']*(')", rf"\g<1>{dotted}.0\g<2>", text)
    WINDOWS_VERSION.write_text(text, encoding="utf-8", newline="\n")
    return [VERSION_FILE, PYPROJECT, WINDOWS_VERSION]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法：python scripts/bump_version.py 0.12.0")
    changed = bump(sys.argv[1])
    print("版本已更新为", ".".join(map(str, parse(sys.argv[1])[:3])))
    for path in changed:
        print(" ", path.relative_to(ROOT))
    print("下一步：跑测试，再执行 scripts/build_windows_release.py 打包。")
