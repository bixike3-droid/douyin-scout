"""声明式交互层的测试。

用一个假 page 对象，不需要真浏览器。重点验证「容错」：
单个动作失败不能把整串带崩，除非显式要求必需。
"""

from __future__ import annotations

import asyncio
import re

from scout.interact import run_actions


class FakeLocator:
    def __init__(self, page: "FakePage", key: str, count: int):
        self.page = page
        self.key = key
        self._count = count
        self._nth = 0

    async def count(self) -> int:
        return self._count

    def nth(self, i: int) -> "FakeLocator":
        clone = FakeLocator(self.page, self.key, self._count)
        clone._nth = i
        return clone

    @property
    def first(self) -> "FakeLocator":
        return self

    async def click(self, timeout: int = 5000) -> None:
        self.page.clicks.append((self.key, self._nth))
        if self.page.fail_on and self.page.fail_on in self.key:
            raise RuntimeError("点击失败（模拟）")

    async def hover(self, timeout: int = 5000) -> None:
        self.page.hovers.append(self.key)

    async def evaluate(self, script: str, arg=None) -> str:
        return self.page.html

    def get_by_text(self, text, exact: bool = False) -> "FakeLocator":
        key = f"re:{text.pattern}" if isinstance(text, re.Pattern) else str(text)
        return FakeLocator(self.page, key, self.page.counts.get(key, 0))


class FakeMouse:
    def __init__(self, page: "FakePage"):
        self.page = page

    async def move(self, x: int, y: int, steps: int = 1) -> None:
        self.page.moves += 1

    async def wheel(self, dx: int, dy: int) -> None:
        self.page.wheels.append((dx, dy))

    async def click(self, x: float, y: float) -> None:
        self.page.mouse_clicks.append((x, y))


class FakeKeyboard:
    def __init__(self, page: "FakePage"):
        self.page = page

    async def press(self, key: str) -> None:
        self.page.presses.append(key)


class FakePage:
    def __init__(self, counts: dict[str, int] | None = None, fail_on: str = "",
                 texts: list[str] | None = None, html: str = "<div>fake</div>",
                 anchor_result: dict | None = None):
        self.counts = counts or {}
        self.fail_on = fail_on
        self.texts = texts or []
        self.html = html
        self.anchor_result = anchor_result if anchor_result is not None else {"found": False}
        self.clicks: list[tuple[str, int]] = []
        self.hovers: list[str] = []
        self.presses: list[str] = []
        self.moves = 0
        self.wheels: list[tuple[int, int]] = []
        self.mouse_clicks: list[tuple[float, float]] = []
        self.gotos: list[str] = []
        self.screenshots: list[str] = []
        self.mouse = FakeMouse(self)
        self.keyboard = FakeKeyboard(self)

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector, self.counts.get(selector, 0))

    def get_by_text(self, text, exact: bool = False) -> FakeLocator:
        if isinstance(text, re.Pattern):
            key = f"re:{text.pattern}"
            return FakeLocator(self, key, self.counts.get(key, 0))
        text = str(text)
        if exact:
            return FakeLocator(self, text, self.counts.get(text, 0))
        # 模拟 Playwright 的子串匹配：把所有包含该文案的键计数加起来
        total = sum(
            n for k, n in self.counts.items() if not k.startswith("re:") and text in k
        )
        return FakeLocator(self, text, total)

    async def evaluate(self, script: str, arg=None) -> dict:
        arg = arg or {}
        if "anchor" in arg:
            # click_anchor_button 的脚本：由测试预先设定返回什么
            return dict(self.anchor_result)
        limit = arg.get("limit", 400)
        texts = self.texts[:limit]
        return {"texts": texts, "total": len(texts)}

    async def goto(self, url: str, **kwargs) -> None:
        self.gotos.append(url)

    async def go_back(self, **kwargs) -> None:
        self.gotos.append("<back>")

    async def screenshot(self, path: str, full_page: bool = False) -> None:
        self.screenshots.append(path)


def run(page, actions, export_dir=None):
    return asyncio.run(run_actions(page, actions, export_dir=export_dir))


def test_empty_actions_is_noop():
    report = run(FakePage(), [])
    assert report.results == []
    assert report.summary()["steps"] == 0


def test_click_text_success():
    page = FakePage(counts={"查看全部": 3})
    report = run(page, [{"action": "click_text", "text": "查看全部"}])
    assert report.ok_count == 1
    assert page.clicks == [("查看全部", 0)]


def test_click_text_nth():
    page = FakePage(counts={"查看全部": 5})
    run(page, [{"action": "click_text", "text": "查看全部", "nth": 2}])
    assert page.clicks == [("查看全部", 2)]


def test_missing_element_records_failure_without_raising():
    page = FakePage(counts={})
    report = run(page, [{"action": "click_text", "text": "不存在"}])
    assert report.ok_count == 0
    assert len(report.failed) == 1
    assert "没有文案" in report.failed[0].detail


def test_required_failure_aborts_chain():
    page = FakePage(counts={})
    report = run(page, [
        {"action": "click_text", "text": "不存在"},
        {"action": "press", "key": "Escape"},
    ])
    assert report.aborted is True
    assert page.presses == [], "必需动作失败后不应继续执行"


def test_optional_failure_continues():
    page = FakePage(counts={})
    report = run(page, [
        {"action": "click_text", "text": "不存在", "optional": True},
        {"action": "press", "key": "Escape"},
    ])
    assert report.aborted is False
    assert page.presses == ["Escape"], "可选动作失败不应中断"
    assert len(report.failed) == 1 and report.ok_count == 1


def test_click_all_clicks_up_to_max():
    page = FakePage(counts={"查看全部": 10})
    report = run(page, [{"action": "click_all", "text": "查看全部", "max": 3}])
    assert len(page.clicks) == 3
    assert "3/10" in report.results[0].detail


def test_hover_press_goto_back():
    page = FakePage(counts={".item": 1})
    report = run(page, [
        {"action": "hover", "selector": ".item"},
        {"action": "press", "key": "Enter"},
        {"action": "goto", "url": "https://example.com"},
        {"action": "back"},
    ])
    assert page.hovers == [".item"]
    assert page.presses == ["Enter"]
    assert page.gotos == ["https://example.com", "<back>"]
    assert report.ok_count == 4


def test_wait_and_move():
    page = FakePage()
    report = run(page, [
        {"action": "wait", "seconds": 0.01},
        {"action": "move", "times": 2},
    ])
    assert report.ok_count == 2
    assert page.moves == 2


def test_unknown_action_is_reported_not_raised():
    report = run(FakePage(), [{"action": "teleport"}])
    assert report.ok_count == 0
    assert "未知动作" in report.failed[0].detail


def test_non_mapping_step_is_rejected():
    report = run(FakePage(), ["just a string"])
    assert "必须是映射" in report.failed[0].detail


def test_screenshot_without_export_dir_fails_cleanly():
    report = run(FakePage(), [{"action": "screenshot", "optional": True}])
    assert report.ok_count == 0
    assert "export_dir" in report.failed[0].detail


def test_click_all_on_zero_matches_raises():
    report = run(FakePage(counts={}), [{"action": "click_all", "text": "无"}])
    assert report.ok_count == 0
    assert "一个都没点到" in report.failed[0].detail


def test_summary_shape():
    report = run(FakePage(counts={"a": 1}), [{"action": "click_text", "text": "a"}])
    summary = report.summary()
    assert set(summary) == {"steps", "ok", "failed", "aborted", "detail"}
    assert summary["detail"][0]["action"] == "click_text"


# ── 形态 B 专用的三个新动作 ──────────────────────────────────


def test_click_pattern_matches_regex():
    page = FakePage(counts={"re:查看全部|共\\d+人": 2})
    report = run(page, [{"action": "click_pattern", "pattern": r"查看全部|共\d+人"}])
    assert report.ok_count == 1
    assert page.clicks == [("re:查看全部|共\\d+人", 0)]


def test_click_pattern_no_match_reports_clearly():
    report = run(FakePage(counts={}), [{"action": "click_pattern", "pattern": r"查看全部"}])
    assert report.ok_count == 0
    assert "没有文案匹配" in report.failed[0].detail


def test_click_pattern_requires_pattern():
    report = run(FakePage(), [{"action": "click_pattern"}])
    assert "需要 pattern" in report.failed[0].detail


def test_click_pattern_scoped_to_selector():
    page = FakePage(counts={"re:全部": 1})
    run(page, [{"action": "click_pattern", "pattern": "全部", "selector": ".item"}])
    assert page.clicks == [("re:全部", 0)]


def test_dump_texts_returns_joined_text():
    page = FakePage(texts=["查看全部", "12人赞过", "回复"])
    report = run(page, [{"action": "dump_texts", "max": 10}])
    assert report.ok_count == 1
    assert "查看全部" in report.results[0].detail
    assert "12人赞过" in report.results[0].detail


def test_dump_texts_keyword_filter():
    page = FakePage(texts=["查看全部", "回复", "赞过"])
    report = run(page, [{"action": "dump_texts", "keyword": "赞"}])
    assert "赞过" in report.results[0].detail
    assert "回复" not in report.results[0].detail


def test_dump_texts_empty():
    report = run(FakePage(texts=[]), [{"action": "dump_texts"}])
    assert "没有可见短文本" in report.results[0].detail


def test_dump_html_writes_file(tmp_path):
    page = FakePage(html="<div class='notice-item'>x</div>")
    report = run(page, [{"action": "dump_html", "selector": "body", "path": "d.html"}], export_dir=tmp_path)
    assert report.ok_count == 1
    assert (tmp_path / "d.html").read_text(encoding="utf-8").startswith("<div class='notice-item'")


def test_dump_html_truncates_large_dom(tmp_path):
    page = FakePage(html="x" * 5000)
    report = run(
        page, [{"action": "dump_html", "selector": "body", "max_chars": 100}], export_dir=tmp_path
    )
    assert "已截断" in report.results[0].detail
    assert "已截断" in (tmp_path / "dom-body.html").read_text(encoding="utf-8")


def test_dump_html_without_export_dir():
    report = run(FakePage(), [{"action": "dump_html"}])
    assert "export_dir" in report.failed[0].detail


def test_form_b_script_shape_is_valid():
    """形态 B 的默认脚本必须是合法动作串，否则采集时会静默失效。"""
    script = [
        {"action": "click_pattern", "pattern": r"查看全部|共\d+人", "max": 1, "optional": True},
        {"action": "wait", "seconds": 0.01},
        {"action": "scroll", "rounds": 1},
    ]
    page = FakePage(counts={"re:查看全部|共\\d+人": 1})
    report = run(page, script)
    assert report.ok_count == 3
    assert page.clicks, "应该点到一次查看全部"


# ── 箭头按钮（形态 B 的关键）─────────────────────────────────


def test_click_anchor_button_clicks_resolved_coordinates():
    """那条「等22人赞了你的作品」右侧的 › 箭头是图标，没有文字。

    click_text / click_pattern 都点不到它 —— 只能按几何位置找。
    """
    page = FakePage(anchor_result={
        "found": True, "x": 640.0, "y": 300.0, "tag": "DIV", "cls": "arrow", "depth": 3,
    })
    report = run(page, [{"action": "click_anchor_button", "anchor": "人赞了你的作品"}])
    assert report.ok_count == 1
    assert page.mouse_clicks == [(640.0, 300.0)]
    assert "arrow" in report.results[0].detail


def test_click_anchor_button_missing_anchor_reports_clearly():
    page = FakePage(anchor_result={"found": False, "count": 0})
    report = run(page, [{"action": "click_anchor_button", "anchor": "人赞了你的作品"}])
    assert report.ok_count == 0
    assert "没找到对应的按钮" in report.failed[0].detail


def test_click_anchor_button_requires_anchor():
    report = run(FakePage(), [{"action": "click_anchor_button"}])
    assert "需要 anchor" in report.failed[0].detail


def test_click_anchor_button_optional_does_not_abort():
    page = FakePage(anchor_result={"found": False})
    report = run(page, [
        {"action": "click_anchor_button", "anchor": "x", "optional": True},
        {"action": "press", "key": "Escape"},
    ])
    assert report.aborted is False
    assert page.presses == ["Escape"]


# ── 悬停（活页面板的正确打开方式）───────────────────────────


def test_hover_text_hovers_instead_of_clicking():
    """互动消息面板是活页：点完鼠标就离开了，面板当场消失。

    所以打开方式必须是悬停并保持 —— 这个测试防止有人改回 click。
    """
    page = FakePage(counts={"通知": 1})
    report = run(page, [{"action": "hover_text", "text": "通知"}])
    assert report.ok_count == 1
    assert page.hovers == ["通知"]
    assert page.clicks == [], "不能点击 —— 点完面板就没了"


def test_hover_text_falls_back_to_substring_match():
    page = FakePage(counts={"通知": 0, "全部通知": 1})
    report = run(page, [{"action": "hover_text", "text": "通知"}])
    assert report.ok_count == 1


def test_hover_text_missing_reports_clearly():
    report = run(FakePage(counts={}), [{"action": "hover_text", "text": "不存在"}])
    assert "没有文案" in report.failed[0].detail


def test_hover_text_requires_text():
    report = run(FakePage(), [{"action": "hover_text"}])
    assert "需要 text" in report.failed[0].detail


def test_anchor_button_hover_mode_does_not_click():
    """mode: hover 时只把鼠标移过去，不点 —— 活页用。"""
    page = FakePage(anchor_result={
        "found": True, "x": 10.0, "y": 20.0, "tag": "DIV", "cls": "arrow", "depth": 2,
    })
    report = run(page, [{"action": "click_anchor_button", "anchor": "x", "mode": "hover"}])
    assert report.ok_count == 1
    assert page.mouse_clicks == [], "hover 模式不该真的点下去"
    assert "hover" in report.results[0].detail
