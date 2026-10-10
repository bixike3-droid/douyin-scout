"""前端资源健全性测试。

**为什么要测这个**

页面是单文件 HTML + 内联 `<script>`。如果 JS 里有语法错误，
**静态 HTML 照样渲染**（标题、导航都在），但所有 `load*()` 函数都不会执行 ——
卡片全空、按钮全不响应。

表现出来是"页面打开了但没数据"，很容易被误判成后端接口坏了。
实际上后端好好的，是前端脚本解析失败。

这个 bug 真实发生过：用 PowerShell 正则往 HTML 里插函数时，
反引号被当成转义符吃掉了，`` `nav `` 变成换行、`` `${name}` `` 变成 `${name}`，
整个脚本报 `missing ) after argument list`。

所以这里用 node 做一次真正的语法检查。没装 node 就跳过
（不能因为环境没有 node 就让测试失败，那样会挡住正常的开发）。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

HTML_PATH = Path(__file__).resolve().parents[1] / "src" / "scout" / "web" / "static" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_html_exists(html):
    assert html, "前端页面文件读不到或为空"


def test_has_single_inline_script(html):
    blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert len(blocks) == 1, f"预期 1 个内联 script 块，实际 {len(blocks)} 个"
    assert len(blocks[0]) > 5000, "script 块太短，可能被破坏了"


def test_script_syntax_is_valid(html):
    """用 node 做真正的语法检查。没装 node 就跳过。"""
    node = shutil.which("node")
    if not node:
        pytest.skip("没装 node，无法做 JS 语法检查")

    block = re.findall(r"<script>(.*?)</script>", html, re.S)[0]
    proc = subprocess.run(
        [node, "--check", "-"],
        input=block.encode("utf-8"),
        capture_output=True,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace")
        pytest.fail(f"前端 JS 语法错误（页面会打开但功能全废）：\n{err[:800]}")


def test_no_backtick_mangling(html):
    """回归测试：反引号被吃掉留下的**具体残骸**。

    出过的事故：`document.querySelector(`nav button[data-tab=`${name}`]`)`
    被 PowerShell 处理后变成 `av button[data-tab=${name}]`，
    少了开头的 `n` 和反引号，整个脚本解析失败。

    这里只查这个具体形态。**不要写成"扫描所有 ${...} 看前面有没有反引号"** ——
    那会误报：模板字面量可以很长，反引号常在几百字符之外。
    而且那种检查是多余的：真被吃掉的话 `test_script_syntax_is_valid` 会直接失败。
    """
    # 残骸特征：占位符没被引号包起来（正确的是 data-tab=" + name + "）
    #
    # 注意别写成 `"av button[data-tab=" not in html` ——
    # 那会匹配到正确代码 `'nav button[data-tab="'`，
    # 因为它们共享子串 `av button[data-tab=`。
    assert "data-tab=${" not in html, "发现被吃掉的模板字面量残骸"
    assert "querySelector(\n" not in html, "querySelector 参数里出现了换行，多半是被转义吃掉的"


# 没有 loader 的标签页 —— 它们是事件驱动，不靠定时轮询
TABS_WITHOUT_LOADER = {
    # 实时日志：由 SSE（pushLog）往里写，不需要 loader
    "events",
}


def test_tab_loaders_match_tab_buttons(html):
    """每个标签页按钮都要有对应的 loader，否则切过去是空白。"""
    tabs = set(re.findall(r'data-tab="([a-zA-Z0-9_-]+)"', html))
    m = re.search(r"const LOADERS = \{(.*?)\};", html, re.S)
    assert m, "找不到 LOADERS 定义"
    loaders = set(re.findall(r"([a-zA-Z0-9_-]+):\s*load[A-Za-z]+", m.group(1)))
    missing = sorted(tabs - loaders - TABS_WITHOUT_LOADER)
    assert not missing, f"这些标签页没有对应的 loader（切过去会空白）：{missing}"


def test_required_ids_are_present(html):
    """页面元素 id 和 JS 里引用的必须对得上。

    `$('#xxx')` 找不到元素会静默失败（返回 null），
    点下去没反应但也不报错 —— 又是那种"看起来正常其实坏了"的问题。
    """
    used = set(re.findall(r"\$\('#([a-zA-Z0-9_-]+)'\)", html))
    declared = set(re.findall(r'id="([a-zA-Z0-9_-]+)"', html))
    missing = sorted(used - declared)
    assert not missing, f"JS 引用了不存在的元素 id：{missing}"


def test_tab_loaders_match_tab_buttons(html):
    """每个标签页按钮都要有对应的 loader，否则切过去是空白。"""
    tabs = set(re.findall(r'data-tab="([a-zA-Z0-9_-]+)"', html))
    m = re.search(r"const LOADERS = \{(.*?)\};", html, re.S)
    assert m, "找不到 LOADERS 定义"
    loaders = set(re.findall(r"([a-zA-Z0-9_-]+):\s*load[A-Za-z]+", m.group(1)))
    missing = sorted(tabs - loaders - TABS_WITHOUT_LOADER)
    assert not missing, f"这些标签页没有对应的 loader（切过去会空白）：{missing}"


def test_every_load_function_is_defined(html):
    """LOADERS 里引用的函数必须真的定义了。"""
    m = re.search(r"const LOADERS = \{(.*?)\};", html, re.S)
    names = set(re.findall(r"load[A-Za-z]+", m.group(1)))
    for name in names:
        assert re.search(rf"function {name}\s*\(", html), f"{name} 被引用但没有定义"
