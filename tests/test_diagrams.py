"""可视化渲染：mermaid 块提取、缓存与兜底逻辑（真实浏览器渲染由脚本人工冒烟）。"""
from scout.desktop import diagrams


def test_extract_and_strip_mermaid_blocks():
    content = "开场\n\n```mermaid\nflowchart TD\n  A[一] --> B[二]\n```\n\n收尾"
    assert diagrams.extract_mermaid_blocks(content) == ["flowchart TD\n  A[一] --> B[二]"]
    assert diagrams.strip_mermaid_blocks(content) == "开场\n\n收尾"
    assert diagrams.extract_mermaid_blocks("没有图") == []
    assert diagrams.strip_mermaid_blocks("没有图") == "没有图"
    assert diagrams.strip_mermaid_blocks("") == ""


def test_render_prefers_local_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(diagrams, "cache_dir", lambda: tmp_path)
    calls = []

    def fake_local(code):
        calls.append(code)
        return b"\x89PNG\r\n\x1a\nlocal"

    monkeypatch.setattr(diagrams, "_render_local", fake_local)
    first = diagrams.render_png("flowchart TD\n  A[一] --> B[二]")
    assert first is not None and first.read_bytes().startswith(b"\x89PNG")
    assert len(calls) == 1
    second = diagrams.render_png("flowchart TD\n  A[一] --> B[二]")
    assert second == first and len(calls) == 1          # 命中缓存不再渲染


def test_render_falls_back_to_kroki(tmp_path, monkeypatch):
    monkeypatch.setattr(diagrams, "cache_dir", lambda: tmp_path)

    def boom(code):
        raise RuntimeError("没有浏览器")

    monkeypatch.setattr(diagrams, "_render_local", boom)
    monkeypatch.setattr(diagrams, "_render_kroki", lambda code: b"\x89PNGkroki")
    path = diagrams.render_png("pie\n title 占比")
    assert path is not None and path.read_bytes() == b"\x89PNGkroki"


def test_render_returns_none_when_everything_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(diagrams, "cache_dir", lambda: tmp_path)

    def boom(code):
        raise RuntimeError("都炸了")

    monkeypatch.setattr(diagrams, "_render_local", boom)
    monkeypatch.setattr(diagrams, "_render_kroki", boom)
    assert diagrams.render_png("flowchart TD\n A-->B") is None
    assert diagrams.render_png("") is None
