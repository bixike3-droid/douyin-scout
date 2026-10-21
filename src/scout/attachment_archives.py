"""Streaming archive readers. Member paths never become extraction destinations."""
import bz2
import gzip
import hashlib
import json
import lzma
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile
import zipfile

ARCHIVES = {".zip", ".7z", ".rar", ".tar", ".tgz", ".tbz", ".tbz2", ".txz", ".gz", ".bz2", ".xz"}
MAX_PREVIEWS = 20


def safe_name(name):
    name = name.replace("\\", "/")
    if not name or name.startswith("/") or ":" in name or "\x00" in name or ".." in PurePosixPath(name).parts:
        return False
    return len(name) <= 1024


class Archive:
    def __init__(self, source, name=None):
        self.source, self.name = Path(source), name or Path(source).name
        self.handle, self.kind, self.entries = None, "", []

    def __enter__(self):
        try:
            suffix = Path(self.name).suffix.lower()
            if suffix == ".zip":
                self.kind, self.handle = "zip", zipfile.ZipFile(self.source)
                self.entries = [{"name": i.filename, "size": i.file_size, "directory": i.is_dir(),
                                 "blocked": bool(i.flag_bits & 1) or stat.S_ISLNK(i.external_attr >> 16),
                                 "reason": "加密或链接文件"} for i in self.handle.infolist()]
            elif suffix == ".7z":
                import py7zr
                self.kind, self.handle = "7z", py7zr.SevenZipFile(self.source, "r")
                if self.handle.needs_password():
                    raise ValueError("7z 压缩包已加密，请解密后上传")
                links = {f.filename for f in self.handle.files if f.is_symlink or f.is_junction}
                self.entries = [{"name": i.filename, "size": i.uncompressed or 0, "directory": i.is_directory,
                                 "blocked": i.filename in links, "reason": "链接文件"} for i in self.handle.list()]
            elif suffix == ".rar":
                import rarfile
                rarfile.BSDTAR_TOOL = shutil.which("bsdtar") or shutil.which("tar") or "bsdtar"
                self.kind, self.handle = "rar", rarfile.RarFile(self.source)
                self.entries = [{"name": i.filename, "size": i.file_size, "directory": i.isdir(),
                                 "blocked": i.needs_password() or i.is_symlink(), "reason": "加密或链接文件"}
                                for i in self.handle.infolist()]
            else:
                try:
                    self.kind, self.handle = "tar", tarfile.open(self.source, "r:*")
                    for i in self.handle:
                        self.entries.append({"name": i.name, "size": i.size, "directory": i.isdir(),
                                             "blocked": not (i.isfile() or i.isdir()), "reason": "链接或特殊文件"})
                except tarfile.ReadError:
                    opener = {".gz": gzip.open, ".bz2": bz2.open, ".xz": lzma.open}.get(suffix)
                    if opener is None:
                        raise ValueError("压缩包损坏或格式无法识别")
                    self.kind = "single"
                    self.handle = opener(self.source, "rb")
                    self.entries = [{"name": Path(self.name).stem or "contents", "size": None, "directory": False, "blocked": False}]
            seen = set()
            for entry in self.entries:
                raw = entry["name"]
                normalized = raw.replace("\\", "/").rstrip("/")
                if not safe_name(raw) or normalized in seen:
                    entry.update(blocked=True, reason="不安全或重复路径")
                seen.add(normalized)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *exc):
        if self.handle is not None:
            self.handle.close()

    def write_many(self, names, directory):
        wanted = {e["name"]: e for e in self.entries if e["name"] in names}
        if len(wanted) != len(names) or any(e["blocked"] or e["directory"] for e in wanted.values()):
            raise ValueError("压缩包成员不存在或不可读取")
        directory.mkdir(parents=True, exist_ok=True)
        destinations = {name: directory / (hashlib.sha256(name.encode()).hexdigest() + Path(name).suffix.lower()) for name in names}
        if self.kind == "7z":
            import py7zr
            class Sink(py7zr.Py7zIO):
                def __init__(self, path): self.buffer = path.open("w+b")
                def write(self, data):
                    return self.buffer.write(data)
                def read(self, size=None): return self.buffer.read(-1 if size is None else size)
                def seek(self, offset, whence=0): return self.buffer.seek(offset, whence)
                def flush(self): self.buffer.flush()
                def size(self):
                    position = self.buffer.tell()
                    size = self.buffer.seek(0, 2)
                    self.buffer.seek(position)
                    return size
            class Factory(py7zr.WriterFactory):
                def __init__(self): self.products = {}
                def create(self, filename):
                    if filename not in wanted:
                        raise ValueError("出现未选择的压缩包成员")
                    self.products[filename] = Sink(destinations[filename])
                    return self.products[filename]
            factory = Factory()
            try:
                self.handle.reset()
                self.handle.extract(targets=list(names), factory=factory)
            finally:
                for sink in factory.products.values():
                    sink.buffer.close()
            return {name: destinations[name] for name in factory.products}
        output = {}
        for name in names:
            if self.kind in ("zip", "rar"):
                stream = self.handle.open(name)
            elif self.kind == "tar":
                stream = self.handle.extractfile(name)
            else:
                stream = self.handle
            if stream is None:
                raise ValueError("无法读取该成员")
            try:
                with destinations[name].open("wb") as target:
                    shutil.copyfileobj(stream, target, length=1024 * 1024)
                output[name] = destinations[name]
            finally:
                if self.kind != "single":
                    stream.close()
        return output


def listing(entries):
    lines = [f"压缩包目录（{len(entries)} 个条目）："]
    for entry in entries:
        size = "大小待展开" if entry["size"] is None else f"{entry['size']} 字节"
        state = "目录" if entry["directory"] else entry.get("reason", "不可读取") if entry["blocked"] else "可读取"
        lines.append(f"{entry['name']}｜{size}｜{state}")
    return "\n".join(lines)


def inspect_archive(paths, item, directory, *, member=None, depth=0):
    from .attachments import managed_path, extract, SUPPORTED, IMAGES, VIDEOS
    source = managed_path(paths, item["relative_path"])
    directory.mkdir(parents=True, exist_ok=True)
    with Archive(source, item["name"]) as archive:
        if member is None:
            (directory / "archive-index.json").write_text(json.dumps(archive.entries, ensure_ascii=False), encoding="utf-8")
            chosen = []
            for entry in archive.entries:
                parts = PurePosixPath(entry["name"].replace("\\", "/")).parts
                if entry["blocked"] or entry["directory"] or any(p in (".git", ".venv", "node_modules", "__MACOSX") for p in parts):
                    continue
                suffix = Path(entry["name"]).suffix.lower()
                if suffix in ARCHIVES or (suffix not in SUPPORTED and suffix):
                    continue
                if len(chosen) >= MAX_PREVIEWS:
                    continue
                chosen.append(entry["name"])
        else:
            chosen = [member]
        text = [listing(archive.entries)] if member is None else []
        visuals, errors, successful = [], [], 0
        # Batch 7z extraction avoids repeatedly decompressing a solid archive.
        payloads = {}
        if archive.kind == "7z" and chosen:
            payloads = archive.write_many(chosen, directory)
        for name in chosen:
            try:
                leaf = payloads[name] if name in payloads else archive.write_many([name], directory)[name]
                suffix = Path(name).suffix.lower()
                if suffix in ARCHIVES and depth >= 1:
                    raise ValueError("嵌套压缩包已保存目录层级，请单独上传该内层压缩包继续读取")
                child = {"id": item["id"] + "-" + hashlib.sha256(name.encode()).hexdigest()[:12], "name": name,
                         "relative_path": leaf.relative_to(paths.data_dir).as_posix()}
                result = extract(paths, child, archive_depth=depth + 1)
                text.append(f"\n--- 压缩包成员：{name} ---\n{result['text']}\n读取范围：{result['limitations']}")
                for visual in result["visuals"]:
                    visual = dict(visual)
                    visual["label"] = f"压缩包成员 {name}：{visual['label']}"
                    # Outer extract() normalizes absolute paths once.
                    visual["path"] = paths.data_dir / visual["path"]
                    visuals.append(visual)
                successful += 1
            except Exception as exc:
                errors.append(f"{name}：{type(exc).__name__}：{str(exc)[:180]}")
        if member and not successful:
            raise ValueError("；".join(errors) or "该成员没有可读取内容")
        note = f"共 {len(archive.entries)} 个条目；先预览 {MAX_PREVIEWS} 个支持的文件；其余可用 attachment_read 的 member 参数按内部路径继续读取。"
        if errors:
            note += "部分成员读取失败：" + "；".join(errors[:10])
        if any(e["blocked"] for e in archive.entries):
            note += "加密、链接或不安全路径的成员未展开。"
        return "\n".join(text), visuals[:16], note
