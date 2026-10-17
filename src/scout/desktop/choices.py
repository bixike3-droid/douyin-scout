"""AI 回复末尾的「下一步选择题」：``choices`` 代码块 → 可点击选项。"""
from __future__ import annotations

import json
import re

CHOICE_BLOCK_RE = re.compile(r"```choices[ \t]*\n(.*?)```", re.S)
MAX_QUESTIONS = 2
MAX_OPTIONS = 4


def extract_choices(text: str) -> tuple[str, list[dict]]:
    """取出 ``choices`` 块并校验：返回（去掉块的正文, 问题列表）。

    模型的 JSON 可能不合法或字段缺失：一律静默丢弃那一段，不影响正文显示。
    问题最多 2 个、每题最多 4 个选项，避免界面被塞满。
    """
    questions: list[dict] = []
    for block in CHOICE_BLOCK_RE.findall(text or ""):
        try:
            data = json.loads(block)
        except (TypeError, ValueError):
            continue
        items = data.get("questions") if isinstance(data, dict) else data
        for item in items or []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("header") or "").strip()
            raw_options = item.get("options") or []
            options: list[str] = []
            for option in raw_options:
                if isinstance(option, dict):
                    option = option.get("label") or option.get("value") or ""
                option = str(option).strip()
                if option and option not in options:
                    options.append(option[:40])
            if not title or len(options) < 2:
                continue
            questions.append({"title": title[:40], "multi": bool(item.get("multi")),
                              "options": options[:MAX_OPTIONS]})
    cleaned = CHOICE_BLOCK_RE.sub("", text or "")
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip(), questions[:MAX_QUESTIONS]
