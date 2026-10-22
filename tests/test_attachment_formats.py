"""Archive contents, bounded extraction, additional formats and generic files."""
import asyncio
import bz2
import gzip
import io
import json
import lzma
from pathlib import Path
import stat
import tarfile
import zipfile

import pytest
from PIL import Image

from scout.attachments import import_file, extract, validate_files, managed_path
from scout.attachment_archives import Archive
from scout.analyze.conversation import send
from scout.store.attachments import Attachments
from scout.tools import registry
from test_attachments import FileClient


@pytest.mark.skip(reason="依赖已移除的原生推理循环；改写为 Codex 验收脚本前先跳过")
def test_zip_lists_and_reads_chinese_paths_and_saved_contents(ctx, tmp_path):
    source = tmp_path / "素材合集.zip"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("活动/说明.txt", "周六开放，预算 5000 元")
        archive.writestr("代码/main.go", 'package main\nfunc main() {}')
        archive.writestr("数据.json", '{"count":10}')
    client = FileClient()
    result = asyncio.run(send(ctx, client, "分析压缩包", agent_id="steward", attachment_paths=[str(source)]))
    assert "活动/说明.txt" in str(client.message_calls[-1]) and "周六开放" in str(client.message_calls[-1])
    item = Attachments(ctx.db).list(1)[0]
    assert item["kind"] == "archive" and item["status"] == "ready"
    source.unlink()
    ctx.tool_conversation_id = 1
    directory = asyncio.run(registry.execute(ctx, "attachment_read", "steward", {"attachment_id": item["id"], "directory": True}))
    assert "代码/main.go" in directory["content"]
    content = asyncio.run(registry.execute(ctx, "attachment_read", "steward", {"attachment_id": item["id"], "member": "活动/说明.txt"}))
    assert content["ok"] and "预算 5000 元" in content["content"]
    assert result["conversation"]["messages"][0]["attachments"][0]["name"] == "素材合集.zip"


@pytest.mark.parametrize("mode,suffix", [("w", ".tar"), ("w:gz", ".tar.gz"), ("w:bz2", ".tar.bz2"), ("w:xz", ".tar.xz")])
def test_tar_variants_extract_supported_members(ctx, tmp_path, mode, suffix):
    source = tmp_path / ("data" + suffix)
    with tarfile.open(source, mode) as archive:
        payload = "压缩包内部资料".encode()
        info = tarfile.TarInfo("目录/readme.md")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    result = extract(ctx.paths, import_file(ctx.paths, source))
    assert "目录/readme.md" in result["text"] and "压缩包内部资料" in result["text"]


@pytest.mark.parametrize("suffix,compress", [(".gz", gzip.compress), (".bz2", bz2.compress), (".xz", lzma.compress)])
def test_single_compressed_text(ctx, tmp_path, suffix, compress):
    source = tmp_path / ("notes.txt" + suffix)
    source.write_bytes(compress("单文件压缩内容".encode()))
    result = extract(ctx.paths, import_file(ctx.paths, source))
    assert "单文件压缩内容" in result["text"]


def test_real_7z_with_nested_path_and_multiple_members(ctx, tmp_path):
    import py7zr
    first, second = tmp_path / "first.txt", tmp_path / "second.md"
    first.write_text("7z 正文一", encoding="utf-8")
    second.write_text("7z 正文二", encoding="utf-8")
    source = tmp_path / "资料.7z"
    with py7zr.SevenZipFile(source, "w") as archive:
        archive.write(first, "folder/first.txt")
        archive.write(second, "second.md")
    result = extract(ctx.paths, import_file(ctx.paths, source))
    assert "7z 正文一" in result["text"] and "7z 正文二" in result["text"]


def test_encrypted_7z_is_reported_without_guessing(ctx, tmp_path):
    import py7zr
    source = tmp_path / "locked.7z"
    with py7zr.SevenZipFile(source, "w", password="secret") as archive:
        archive.writestr(b"secret", "private.txt")
    with pytest.raises(ValueError, match="已加密"):
        extract(ctx.paths, import_file(ctx.paths, source))


def test_zip_reads_members_and_blocks_unsafe_paths_and_links(ctx, tmp_path):
    source = tmp_path / "paths.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("../../outside.txt", "escape")
        archive.writestr("C:/outside.txt", "escape")
        archive.writestr("safe.txt", "safe evidence")
        archive.writestr("large.txt", "a" * 256)
        link = zipfile.ZipInfo("shortcut")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "../outside")
    item = import_file(ctx.paths, source)
    result = extract(ctx.paths, item)
    assert "safe evidence" in result["text"]
    assert "不安全或重复路径" in result["text"] and "a" * 256 in result["text"]
    assert not (ctx.paths.data_dir.parent / "outside.txt").exists()
    with Archive(managed_path(ctx.paths, item["relative_path"]), item["name"]) as archive:
        with pytest.raises(ValueError, match="不可读取"):
            archive.write_many(["../../outside.txt"], tmp_path / "output")


def test_archive_directory_and_unknown_binary_retention(ctx, tmp_path):
    source = tmp_path / "many.zip"
    with zipfile.ZipFile(source, "w") as archive:
        for i in range(3): archive.writestr(f"{i}.txt", "test")
    assert "3 个条目" in extract(ctx.paths, import_file(ctx.paths, source))["text"]
    binary = tmp_path / "model.custom"
    binary.write_bytes(b"\x00\x01\x02\x03")
    assert validate_files([binary]) == [binary]
    result = asyncio.run(send(ctx, FileClient(), "保留文件", agent_id="steward", attachment_paths=[str(binary)]))
    item = result["conversation"]["messages"][0]["attachments"][0]
    assert item["status"] == "partial" and "未解析二进制内容" in item["limitations"]


@pytest.mark.parametrize("name,content,expected", [
    ("note.rtf", r"{\rtf1\ansi Hello \b World\b0}", "Hello World"),
    ("event.ics", "BEGIN:VEVENT\nSUMMARY:周末活动\nEND:VEVENT", "周末活动"),
    ("notes.toml", 'title = "本地配置"', "本地配置"),
    ("main.rs", "fn main() { /* 说明 */ }", "fn main"),
    ("no_extension", "无扩展名的文本", "无扩展名的文本"),
    ("book.ipynb", json.dumps({"cells": [{"cell_type": "markdown", "source": ["# Notebook说明"]}, {"cell_type": "code", "source": ["print('example')"]}]}), "Notebook说明"),
    ("mail.eml", "Subject: Event\nFrom: user@example.com\nContent-Type: text/plain; charset=utf-8\n\nmeeting notes", "meeting notes"),
])
def test_additional_text_and_document_formats(ctx, tmp_path, name, content, expected):
    source = tmp_path / name
    source.write_text(content, encoding="utf-8")
    result = extract(ctx.paths, import_file(ctx.paths, source))
    assert expected in result["text"]


def test_epub_and_heic_are_read(ctx, tmp_path):
    source = tmp_path / "book.epub"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("OEBPS/ch1.xhtml", "<html><body><p>电子书正文</p></body></html>")
    assert "电子书正文" in extract(ctx.paths, import_file(ctx.paths, source))["text"]
    from pillow_heif import register_heif_opener
    register_heif_opener()
    photo = tmp_path / "photo.heic"
    Image.new("RGB", (30, 20), "red").save(photo, format="HEIF")
    result = extract(ctx.paths, import_file(ctx.paths, photo))
    assert managed_path(ctx.paths, result["visuals"][0]["path"]).is_file()


def test_rar_directory_and_readable_member_contents(ctx):
    root = Path(__file__).parent / "fixtures" / "archives"
    first = extract(ctx.paths, import_file(ctx.paths, root / "rar3-comment-plain.rar"))
    assert "file1.txt" in first["text"] and "file2.txt" in first["text"]
    second = extract(ctx.paths, import_file(ctx.paths, root / "rar5-crc.rar"))
    assert "stest2.txt" in second["text"] and "000\n001" in second["text"]


def test_large_file_metadata_and_many_attachments_have_no_upload_ceiling(tmp_path, monkeypatch):
    import os
    source = tmp_path / "large.bin"
    source.write_bytes(b"data")
    original = Path.stat
    def large_stat(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path == source:
            values = list(result)
            values[6] = 2 * 1024 ** 4
            return os.stat_result(values)
        return result
    monkeypatch.setattr(Path, "stat", large_stat)
    assert validate_files([source]) == [source]
    files = []
    for i in range(32):
        file = tmp_path / f"file-{i}.txt"
        file.write_text("test")
        files.append(file)
    assert len(validate_files(files)) == 32


def test_large_archive_member_is_streamed_and_long_text_can_continue(ctx, tmp_path):
    source = tmp_path / "large.zip"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        with archive.open("long.txt", "w") as output:
            for _ in range(33):
                output.write(b"a" * 1024 * 1024)
            output.write(b"tail-marker")
    asyncio.run(send(ctx, FileClient(), "查看目录", agent_id="steward", attachment_paths=[str(source)]))
    item = Attachments(ctx.db).list(1)[0]
    ctx.tool_conversation_id = 1
    result = asyncio.run(registry.execute(ctx, "attachment_read", "steward", {
        "attachment_id": item["id"], "member": "long.txt", "offset": 33 * 1024 * 1024, "limit": 100}))
    assert result["ok"] and result["content"] == "tail-marker"


def test_text_can_be_read_beyond_initial_preview(ctx, tmp_path):
    source = tmp_path / "long.txt"
    source.write_text("资料" * 120000 + "最终约束", encoding="utf-8")
    asyncio.run(send(ctx, FileClient(), "查看", agent_id="steward", attachment_paths=[str(source)]))
    ctx.tool_conversation_id = 1
    item = Attachments(ctx.db).list(1)[0]
    result = asyncio.run(registry.execute(ctx, "attachment_read", "steward", {
        "attachment_id": item["id"], "offset": 240000, "limit": 100}))
    assert result["content"] == "最终约束"
