"""Render the actual native attachment composer with isolated demonstration data."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from pathlib import Path
import argparse
import tempfile
import time
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QThreadPool

from scout.attachments import _run_ffmpeg
from scout.desktop.harness import HarnessPage
from scout.desktop.theme import apply_theme
from scout.paths import Paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("light", "dark"), default="light")
    mode = parser.parse_args().mode
    out = Path(__file__).resolve().parents[1] / "tmp" / "attachment-ui-preview"
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    apply_theme(app, mode)
    with tempfile.TemporaryDirectory(prefix="scout-attachment-preview-") as directory:
        root = Path(directory)
        paths = Paths.build(root=root).ensure()
        photo = root / "活动海报.png"
        image = Image.new("RGB", (900, 600), "#E1EBE5")
        draw = ImageDraw.Draw(image)
        draw.ellipse((430, -160, 1120, 510), fill="#B1CAC0")
        draw.ellipse((550, 240, 1050, 740), fill="#779E8F")
        draw.rounded_rectangle((70, 85, 400, 515), 26, fill="#FAF8EF")
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 42)
        small = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 24)
        draw.text((105, 150), "山野来信", font=font, fill="#315349")
        draw.text((105, 225), "周末，一起去自然里", font=small, fill="#657D72")
        draw.line((110, 320, 350, 320), fill="#A1B4A6", width=2)
        draw.text((105, 355), "10.24  SAT", font=small, fill="#657D72")
        image.save(photo)
        video = root / "周末活动短片.mp4"
        _run_ffmpeg(["-loop", "1", "-i", str(photo), "-t", "1", "-pix_fmt", "yuv420p", "-y", str(video)])
        brief = root / "周末传播方案.pdf"
        brief.write_bytes(b"preview")
        sheet = root / "活动预算.xlsx"
        sheet.write_bytes(b"preview")
        page = HarnessPage(paths)
        page.set_motion(False)
        page.resize(1120, 860)
        page.splitter.setSizes([740, 380])
        page.composer.setPlainText("帮我看看这张海报和活动短片，再结合方案与预算，整理一下下周的传播重点。")
        page.attachment_tray.add_files([str(photo), str(video), str(brief), str(sheet)])
        page.show()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            app.processEvents()
            tiles = page.attachment_tray.findChildren(__import__('scout.desktop.attachments', fromlist=['AttachmentTile']).AttachmentTile)
            if any(t.kind == "video" and not t.preview.isNull() for t in tiles):
                break
            time.sleep(.02)
        for _ in range(8):
            app.processEvents()
        page.grab().save(str(out / f"workspace-{mode}.png"))
        page.findChild(QWidget, "composerBox").grab().save(str(out / f"composer-{mode}.png"))
        from scout.desktop.attachments import AttachmentGroup
        group = AttachmentGroup([{"name": p.name, "source_path": str(p), "size": p.stat().st_size, "status": "pending"}
                                 for p in (photo, video, brief, sheet)], paths)
        group.resize(650, 220)
        from scout.desktop.appearance import color
        group.setStyleSheet("background: " + color("surface") + ";")
        group.show()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            app.processEvents()
            if all(not t.preview.isNull() for t in group.findChildren(__import__('scout.desktop.attachments', fromlist=['AttachmentTile']).AttachmentTile) if t.kind == "video"):
                break
            time.sleep(.02)
        group.grab().save(str(out / f"message-attachments-{mode}.png"))
        group.close()
        page.close()
        QThreadPool.globalInstance().waitForDone(30000)
    print(out)


if __name__ == "__main__":
    main()
