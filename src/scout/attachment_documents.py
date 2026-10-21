"""Additional document and structured text formats, decoded without execution."""
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
import json
from pathlib import Path
import zipfile
import codecs


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"): self.hidden += 1
        if tag in ("p", "div", "br", "h1", "h2", "li", "tr"): self.parts.append("\n")
    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.hidden: self.hidden -= 1
    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)


def html_text(value):
    parser = _HTMLText()
    parser.feed(value)
    return "".join(parser.parts)


def decode_text(raw):
    encodings = ("utf-16",) if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "gb18030")
    for encoding in encodings:
        try:
            text = codecs.getincrementaldecoder(encoding)().decode(raw, final=False)
            if "\x00" in text or sum(not c.isprintable() and c not in "\r\n\t\f" for c in text) > max(1, len(text) // 50):
                continue
            return text
        except UnicodeError:
            continue
    raise ValueError("已保存原文件；当前未能解析此二进制格式或文本编码")


def read_text_segment(source, offset, limit):
    with source.open("rb") as stream:
        sample = stream.read(8192)
    candidates = ("utf-16",) if sample.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "gb18030")
    encoding = None
    for candidate in candidates:
        try:
            codecs.getincrementaldecoder(candidate)().decode(sample, final=False)
            encoding = candidate
            break
        except UnicodeError:
            continue
    if not encoding:
        raise ValueError("无法识别文本编码")
    with source.open("r", encoding=encoding) as stream:
        remaining = offset
        while remaining:
            skipped = stream.read(min(65536, remaining))
            if not skipped:
                return "", False
            remaining -= len(skipped)
        part = stream.read(limit + 1)
        return part[:limit], len(part) > limit


def document_text(source, extension):
    if extension == ".xls":
        import xlrd
        workbook = xlrd.open_workbook(source, on_demand=True)
        try:
            lines = []
            for sheet in workbook.sheets()[:30]:
                lines.append("工作表：" + sheet.name)
                for row in range(min(5000, sheet.nrows)):
                    lines.append("\t".join(str(sheet.cell_value(row, col)) for col in range(min(100, sheet.ncols))))
                    if sum(map(len, lines)) >= 180000:
                        return "\n".join(lines), "表格文字已截断；未执行公式或宏。"
            return "\n".join(lines), "至多读取前 30 张表，每表前 5000 行、100 列；公式使用保存的缓存值。"
        finally:
            workbook.release_resources()
    if extension == ".epub":
        with zipfile.ZipFile(source) as archive:
            parts = []
            for name in sorted(n for n in archive.namelist() if Path(n).suffix.lower() in (".html", ".xhtml", ".htm"))[:100]:
                with archive.open(name) as stream:
                    parts.append(name + "\n" + html_text(decode_text(stream.read(2 * 1024 * 1024))))
                if sum(map(len, parts)) > 180000: break
            return "\n\n".join(parts), "提取至多 100 个 HTML 章节；按包内文件名排序，未读取嵌入媒体。"
    with source.open("rb") as stream:
        raw = stream.read(2 * 1024 * 1024)
    if extension == ".eml":
        message = BytesParser(policy=policy.default).parsebytes(raw)
        body = message.get_body(preferencelist=("plain", "html")) if message.is_multipart() else message
        content = body.get_content() if body else ""
        if body and body.get_content_type() == "text/html": content = html_text(content)
        headings = "\n".join(f"{key}: {message.get(key, '')}" for key in ("Subject", "From", "To", "Date"))
        files = [a.get_filename() or "未命名附件" for a in message.iter_attachments()]
        return headings + "\n\n" + str(content) + "\n邮件附件：" + "、".join(files), "已读取邮件头和正文；邮件内附件只列名称。"
    text = decode_text(raw)
    if extension == ".rtf":
        from striprtf.striprtf import rtf_to_text
        return rtf_to_text(text, errors="replace"), "仅提取 RTF 文本。"
    if extension == ".ipynb":
        notebook = json.loads(text)
        parts = [f"[{c.get('cell_type', 'cell')}]\n" + ("".join(c.get("source", [])) if isinstance(c.get("source"), list) else str(c.get("source", ""))) for c in notebook.get("cells", [])]
        return "\n\n".join(parts), "读取 Notebook 的 Markdown 和代码单元；未执行代码或读取富媒体输出。"
    return text, "按文本读取；仅读取前 2MB，不执行其中的内容。"
