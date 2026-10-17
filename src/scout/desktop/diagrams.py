"""AI 可视化：mermaid 文本 → PNG。

本地优先：用采集同款 Playwright Chromium 渲染（等效官方 mermaid-cli 的
Puppeteer 方案，但不需要安装 Node；mermaid.min.js 随包分发、离线可用）。
兜底：kroki.io 在线渲染。结果按内容哈希缓存，重复消息不重复渲染。
"""
from __future__ import annotations

import base64
import hashlib
import html as html_lib
import os
import re
import sys
import tempfile
import urllib.request
import zlib
from pathlib import Path

MERMAID_BLOCK_RE = re.compile(r"```mermaid[ \t]*\n(.*?)```", re.S)
KROKI_TIMEOUT = 30
RENDER_TIMEOUT_MS = 25000
# 渲染结果变化时递增：旧的宽画布缓存自动失效，不要手工清目录。
RENDER_VERSION = 2


def extract_mermaid_blocks(text: str) -> list[str]:
    """从消息文本里取出所有 mermaid 代码块（按出现顺序）。"""
    return [block.strip() for block in MERMAID_BLOCK_RE.findall(text or "") if block.strip()]


def strip_mermaid_blocks(text: str) -> str:
    """去掉 mermaid 代码块后的正文（图表由独立控件展示，不留在气泡里）。"""
    cleaned = MERMAID_BLOCK_RE.sub("", text or "")
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def split_mermaid_blocks(text: str) -> list[tuple[str, str]]:
    """把正文切成 [("text", 正文), ("mermaid", 图), ...]。

    图要留在它原来的位置：附件式“统统一到最后”会让图和后面那几段文字看起来
    挤在一起，读者也分不清图属于哪一节。
    """
    parts: list[tuple[str, str]] = []
    position = 0
    for match in MERMAID_BLOCK_RE.finditer(text or ""):
        before = (text or "")[position:match.start()]
        if before.strip():
            parts.append(("text", before))
        code = match.group(1).strip()
        if code:
            parts.append(("mermaid", code))
        position = match.end()
    rest = (text or "")[position:]
    if rest.strip():
        parts.append(("text", rest))
    return parts


def cache_dir() -> Path:
    root = Path(os.environ.get("SCOUT_DATA_DIR") or tempfile.gettempdir())
    target = root / "cache" / "diagrams"
    target.mkdir(parents=True, exist_ok=True)
    return target


def asset_path(name: str) -> Path:
    """开发目录与打包（_MEIPASS）两处都能找到资源。"""
    candidates = []
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidates.append(Path(bundle) / "scout" / "desktop" / "assets" / name)
    candidates.append(Path(__file__).resolve().parent / "assets" / name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[-1]


def _render_local(code: str) -> bytes:
    """Playwright + mermaid.min.js 本地渲染，元素截图返回 PNG。"""
    from playwright.sync_api import sync_playwright

    mermaid_js = asset_path("mermaid.min.js").read_text(encoding="utf-8")
    escaped = html_lib.escape(code)
    page_html = f"""<!doctype html><html><head><meta charset="utf-8">
<style>html,body{{margin:0;padding:0;background:#ffffff}}
pre.mermaid{{margin:0;padding:10px;font-size:16px;display:inline-block;text-align:center}}</style>
</head><body><pre class="mermaid" id="diagram">{escaped}</pre>
<script>{mermaid_js}</script>
<script>
window.__done = false; window.__err = null;
(async () => {{
  try {{
    const mermaid = window.mermaid;
    if (!mermaid) throw new Error("mermaid 资源未加载");
    mermaid.initialize({{ startOnLoad: false, theme: "default", securityLevel: "strict" }});
    await mermaid.run({{ nodes: document.querySelectorAll(".mermaid") }});
    // 默认 SVG 宽度是 100%，会把图拉成整页宽、内容挤在左边；
    // 改成按 viewBox 的原始尺寸，截图就只包住图本身。
    for (const svg of document.querySelectorAll("pre.mermaid svg")) {{
      const box = svg.viewBox && svg.viewBox.baseVal;
      if (box && box.width > 0 && box.height > 0) {{
        svg.setAttribute("width", box.width);
        svg.setAttribute("height", box.height);
        svg.style.maxWidth = "none";
      }}
    }}
    window.__done = true;
  }} catch (err) {{ window.__err = String(err); }}
}})();
</script></body></html>"""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(device_scale_factor=2, viewport={"width": 1200, "height": 900})
            page.set_content(page_html, wait_until="load")
            page.wait_for_function("window.__done === true || window.__err !== null",
                                   timeout=RENDER_TIMEOUT_MS)
            error = page.evaluate("window.__err")
            if error:
                raise RuntimeError(str(error)[:200])
            element = page.query_selector("pre.mermaid")
            if element is None:
                raise RuntimeError("没有找到渲染元素")
            return element.screenshot()
        finally:
            browser.close()


def _render_kroki(code: str) -> bytes:
    payload = base64.urlsafe_b64encode(zlib.compress(code.encode("utf-8"), 9)).decode("ascii")
    request = urllib.request.Request(f"https://kroki.io/mermaid/png/{payload}",
                                     headers={"User-Agent": "yuanjing/1.0"})
    with urllib.request.urlopen(request, timeout=KROKI_TIMEOUT) as response:
        return response.read()


def render_png(code: str, *, prefer_local: bool = True) -> Path | None:
    """渲染并缓存；失败返回 None（调用方展示失败态，不抛异常）。"""
    code = (code or "").strip()
    if not code:
        return None
    digest = hashlib.sha1(f"v{RENDER_VERSION}|{code}".encode("utf-8")).hexdigest()
    target = cache_dir() / f"{digest}.png"
    if target.is_file() and target.stat().st_size > 0:
        return target
    data: bytes | None = None
    if prefer_local:
        try:
            data = _render_local(code)
        except Exception:
            data = None
    if not data:
        try:
            data = _render_kroki(code)
        except Exception:
            data = None
    if not data:
        return None
    handle, temporary = tempfile.mkstemp(prefix="diagram-", suffix=".png", dir=target.parent)
    try:
        with os.fdopen(handle, "wb") as fh:
            fh.write(data)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target
