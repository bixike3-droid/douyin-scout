"""双档会话管理。

档 A（登录态，小号）：只做它独占的事——解析点赞人列表拿 sec_uid。绝不浏览主页。
档 B（匿名态）：承担全部公开数据采集。没有账号可封，但配额按 IP 算，更严。

两者用**同一个 Playwright 实例、两个独立 BrowserContext**：
- 档 A 用 launch_persistent_context，登录态落在 data/profiles/tier_a；
- 档 B 用全新 context，自动获得新的 ttwid，与档 A 的 cookie 完全隔离。

不实现任何签名算法：所有请求都由真实浏览器用页面自身的 JS 环境发出。
"""

from .health import check_login
from .lock import ProfileLock, ProfileLockBusy
from .manager import SessionManager, SessionError, TierSession
from .mirror import CapturedResponse, ResponseMirror

__all__ = [
    "SessionManager",
    "SessionError",
    "TierSession",
    "ResponseMirror",
    "CapturedResponse",
    "ProfileLock",
    "ProfileLockBusy",
    "check_login",
]
