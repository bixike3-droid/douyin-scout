"""采集层。

每个采集器都是「模板方法」：护栏 → 节流 → 真实浏览器导航 → 交互 → 收响应
→ 归档 → 解析 → 落库。子类只覆盖 url_for / interact / persist。

核心纪律：
1. 发请求前必过 guard（配额 + 熔断）。
2. **先归档原始响应，再解析**。顺序不能反——解析可以随时重做，响应丢了就没了。
3. 任何异常都不外抛，转成 outcome.ok=False 并记录，由调度器决定是否重试。
"""

from .api_base import ApiCollector
from .base import CollectOutcome, Collector
from .likers import LikersCollector
from .notice import NoticeCollector
from .profile import ProfileCollector
from .self_profile import SelfCollector
from .user_works_api import UserWorksApiCollector

COLLECTORS: dict[str, type[Collector]] = {
    NoticeCollector.kind: NoticeCollector,
    LikersCollector.kind: LikersCollector,
    UserWorksApiCollector.kind: UserWorksApiCollector,
    SelfCollector.kind: SelfCollector,
    ProfileCollector.kind: ProfileCollector,
}


def collector_for(kind: str) -> type[Collector] | None:
    return COLLECTORS.get(kind)


__all__ = [
    "Collector",
    "CollectOutcome",
    "ApiCollector",
    "NoticeCollector",
    "LikersCollector",
    "UserWorksApiCollector",
    "SelfCollector",
    "ProfileCollector",
    "COLLECTORS",
    "collector_for",
]
