"""从品牌 SVG 生成程序需要的位图与 .ico（矢量为准，位图只是产物）。

用采集同款 Playwright Chromium 渲染 SVG，Pillow 打包 .ico，不依赖 Qt。
"""
import base64
import io
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "brand"
TARGET = ROOT / "src" / "scout" / "desktop" / "assets"
SITE = ROOT / "site" / "assets"
WEB = ROOT / "desktop-html" / "src" / "brand"
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def render(page, svg_path: Path, size: int) -> Image.Image:
    """把 SVG 铺满 size×size 的透明画布（与原先 QSvgRenderer 一致：不保留宽高比）。

    先按 SVG 自身尺寸以 4 倍像素密度截图，再缩放到目标尺寸，边缘更干净。
    """
    page.set_content(
        "<!doctype html><style>html,body{margin:0;background:transparent}img{display:block}</style>"
        f'<img src="data:image/svg+xml;base64,{base64.b64encode(svg_path.read_bytes()).decode("ascii")}">'
    )
    page.wait_for_function("document.images[0].complete && document.images[0].naturalWidth > 0")
    shot = page.locator("img").screenshot(omit_background=True)
    return Image.open(io.BytesIO(shot)).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)


def render_sized(page, svg_bytes: bytes, width: int) -> Image.Image:
    """按原比例渲染：先高倍截图，再等比缩放到目标宽度。"""
    page.set_content(
        "<!doctype html><style>html,body{margin:0;background:transparent}img{display:block}</style>"
        f'<img src="data:image/svg+xml;base64,{base64.b64encode(svg_bytes).decode("ascii")}">'
    )
    page.wait_for_function("document.images[0].complete && document.images[0].naturalWidth > 0")
    shot = page.locator("img").screenshot(omit_background=True)
    image = Image.open(io.BytesIO(shot)).convert("RGBA")
    height = round(image.height * width / image.width)
    return image.resize((width, height), Image.Resampling.LANCZOS)


def save_png(image: Image.Image, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "PNG")
    print("png", target.relative_to(ROOT), image.width)


def save_ico(image: Image.Image, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "ICO", sizes=ICO_SIZES)
    print("ico", target.relative_to(ROOT))


app_icon_svg = BRAND / "源镜_App图标.svg"
mark_svg = BRAND / "源镜_图形标志_透明底.svg"
lockup_svg = BRAND / "源镜_标志组合_透明底.svg"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(device_scale_factor=4)
    app_icon = render(page, app_icon_svg, 256)
    site_mark = render(page, mark_svg, 96)
    mark = render_sized(page, mark_svg.read_bytes(), 256)
    lockup = render_sized(page, lockup_svg.read_bytes(), 434)
    # 深色主题用浅色字标，标志本身保持原色
    dark_lockup = render_sized(
        page, lockup_svg.read_text(encoding="utf-8").replace('fill="#10294D"', 'fill="#E8E6E3"').encode("utf-8"), 434)
    browser.close()

save_png(app_icon, TARGET / "brand_app.png")
# 前端打包用：同一个标志的三种形态随 Vite 进 dist，不依赖后端文件路由
save_png(mark, WEB / "mark.png")
save_png(app_icon, WEB / "app-icon.png")
save_png(lockup, WEB / "lockup-light.png")
save_png(dark_lockup, WEB / "lockup-dark.png")
save_ico(app_icon, TARGET / "yuanjing.ico")
save_png(site_mark, SITE / "logo-mark.png")
save_ico(app_icon, SITE / "app-icon.ico")

# 站点直接用矢量
(SITE / "logo-mark.svg").write_bytes(mark_svg.read_bytes())
(SITE / "app-icon.svg").write_bytes(app_icon_svg.read_bytes())
print("site svg copied")
