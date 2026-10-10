"""浏览器实验室。

用途：在写任何采集逻辑之前，先**观察真实浏览器到底发了什么**。
这是 M1「可见性勘探」的执行工具，产出三样东西：

1. `data/exports/probe-*.json` —— 完整的响应清单（url / 状态 / 大小 / 类型）
2. `data/exports/probe-*.md`   —— 人能读的勘探报告
3. `data/raw/...`              —— 每个响应的正文，永久归档，可回放重解

有了它就不需要靠猜：字段名、分页游标、接口路径、是否弹登录墙，全都看得见。

它也是 HAR 的替代品——比 HAR 更有用，因为已经按抖音接口筛过一遍并做了初步解析。
"""

from .probe import ProbeReport, Prober

__all__ = ["Prober", "ProbeReport"]
