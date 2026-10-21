"""生成自建版本源 version.json，并给出上传命令。

用法：
    python scripts/publish_update.py dist\\yuanjing-0.9.1-windows-x64.zip --version 0.9.1 --notes FILE

产物：
    dist/update/version.json     ← 上传到服务器 /var/www/douyin/update/
    dist/update/<zip 同名>        ← zip 上传到 /var/www/douyin/download/
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

BASE = "https://douyin.baodaoxiaoyuan.cn"
ROOT = Path(__file__).resolve().parents[1]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="生成站点更新源 version.json")
    parser.add_argument("zip", type=Path, help="安装包 zip")
    parser.add_argument("--version", required=True, help="版本号，如 0.9.2")
    parser.add_argument("--notes", type=Path, help="更新说明文件（markdown）")
    parser.add_argument("--page", default=f"{BASE}/", help="发布页地址")
    parser.add_argument("--prerelease", action="store_true")
    args = parser.parse_args()

    zip_path = args.zip if args.zip.is_absolute() else (ROOT / args.zip)
    if not zip_path.exists():
        raise SystemExit(f"找不到安装包：{zip_path}")

    notes = args.notes.read_text(encoding="utf-8") if args.notes else ""
    payload = {
        "version": args.version,
        "name": f"v{args.version}",
        "published_at": date.today().isoformat(),
        "zip_url": f"{BASE}/download/{zip_path.name}",
        "size": zip_path.stat().st_size,
        "sha256": sha256_of(zip_path),
        "notes": notes,
        "page": args.page,
        "prerelease": bool(args.prerelease),
    }

    out_dir = ROOT / "dist" / "update"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "version.json"
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"已生成 {out_file}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("\n上传到服务器（两条）：")
    print(f"  scp \"{zip_path}\" admin@139.224.200.6:/var/www/douyin/download/")
    print(f"  scp \"{out_file}\" admin@139.224.200.6:/var/www/douyin/update/version.json")
    print("\n服务器端目录（首次需要建）：")
    print("  sudo mkdir -p /var/www/douyin/update && sudo chmod 755 /var/www/douyin/update")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
