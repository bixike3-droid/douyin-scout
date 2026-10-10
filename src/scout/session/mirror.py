"""响应镜像。

这是本方案的技术核心：**不自己发请求，让浏览器去发，我们在旁边收。**

所有签名（a_bogus / msToken）都是抖音自己的 webmssdk.js 生成的，我们零签名工作。
同时因为请求头、TLS 指纹、JS 环境全是真的，风控识别难度远高于自造请求。

实现上挂在 BrowserContext 的 response 事件上；response.body() 是异步的，
所以事件回调里起一个 task，由 drain() 负责等齐。
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

DEFAULT_INCLUDE = (
    "/aweme/v1/web/*",
    "/aweme/v1/web/notice/*",
    "/aweme/v1/web/aweme/post/*",
    "/aweme/v1/web/user/profile/*",
)


# 认定"数据接口"的 URL 特征。
# 关键教训：一次页面加载会产生几百个响应，绝大多数是 CDN 上的 JS/CSS。
# 如果把它们都算进配额、写进日志、存进归档，配额会被瞬间烧穿（实测 672/120），
# 日志被淹没，归档一天涨几个 GB —— 而真正的接口一个都看不见。
API_HINTS = (
    "/aweme/v1/",
    "/aweme/v2/",
    "/api/",
    "/passport/",
    "/webcast/",
    "/notice/",
    "/message",
    "imapi.douyin.com",
    "/im/",
    "/creator/",
    "/user/",
    "/v1/",
    "/v2/",
)


def _matches(url: str, patterns: Sequence[str]) -> bool:
    """URL 是否命中任一模式。

    踩过的坑：fnmatch 是**整串匹配**，模式 "/aweme/v1/web/*" 永远匹配不上
    "https://www.douyin.com/aweme/v1/web/notice/?..."，因为后者不以 "/" 开头。
    结果采集器的响应过滤器把所有东西都挡掉了 —— 而且不报错，
    只表现为"空返回、捕获 0"，极难察觉。

    所以三种都试：子串命中 / 整串 glob / 前面补通配符的 glob。
    """
    if not patterns:
        return True
    for p in patterns:
        if not p:
            continue
        if p in url:
            return True
        if fnmatch.fnmatch(url, p):
            return True
        if not p.startswith("*") and fnmatch.fnmatch(url, "*" + p):
            return True
    return False


def looks_like_data(content_type: str, url: str, resource_type: str = "") -> bool:
    """**读 body 之前**就能判断的"这是不是要保留的响应"。

    这一步是性能关键：一次页面加载有几百个 JS/CSS 响应体，
    如果每个都 await response.body()，光读内存就是几十 MB，
    浏览器会明显卡顿 —— 换浏览器治不了，得先不读。

    注意：主文档（resource_type == "document"）**必须保留**。
    抖音的 PC 网页会把数据 SSR 进 HTML 里，
    漏掉它等于漏掉一整个数据源。
    """
    if resource_type == "document":
        return True

    ct = (content_type or "").lower()
    if "json" in ct or "protobuf" in ct or "text/plain" in ct:
        return True

    path = url.split("?")[0].lower()
    if path.endswith((".js", ".css", ".woff", ".woff2", ".png", ".jpg", ".jpeg",
                      ".webp", ".gif", ".mp4", ".svg", ".ico")):
        return False
    return any(hint in url for hint in API_HINTS)


@dataclass
class CapturedResponse:
    url: str
    status: int
    content_type: str
    body: bytes | None = None
    error: str = ""
    duration_ms: int = 0
    resource_type: str = ""
    from_mirror: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def byte_size(self) -> int:
        return len(self.body or b"")

    @property
    def is_json(self) -> bool:
        if "json" in (self.content_type or "").lower():
            return True
        body = (self.body or b"")[:64].lstrip()
        return body.startswith(b"{") or body.startswith(b"[")

    @property
    def is_data(self) -> bool:
        """是不是值得归档 / 记日志的"数据响应"。

        静态资源（JS/CSS/字体/图片/埋点）不算。

        ⚠️ protobuf 必须算 —— 抖音部分接口（尤其 IM 系）返回 application/x-protobuf。
        早期版本只认 JSON 和 URL 特征，protobuf 两个都不满足，会被**静默丢掉**：
        正文白读了，归档里也没有，表现为"这个页面上没有这个接口"。
        """
        if self.resource_type == "document":
            return True
        content_type = (self.content_type or "").lower()
        if "json" in content_type or "protobuf" in content_type or "text/plain" in content_type:
            return True
        if self.is_json:
            return True
        url = self.url
        return any(hint in url for hint in API_HINTS)

    @property
    def api_path(self) -> str:
        """去掉域名和查询串的路径，用于按接口聚合统计。"""
        try:
            from urllib.parse import urlparse

            return urlparse(self.url).path or self.url
        except Exception:
            return self.url

    def json(self) -> Any:
        if not self.body:
            return None
        try:
            return json.loads(self.body.decode("utf-8", errors="replace"))
        except Exception:
            return None


async def _duration_ms(response: Any) -> int:
    """从 Playwright 的资源计时里取真实耗时，单位毫秒。

    必须在 **body 读完之后** 调用：response 事件是在收到响应头时就触发的，
    那一刻 responseEnd 还是 -1，取出来永远是 0。这是踩过的坑。

    不同版本里 timing 可能是属性也可能是方法，两种都兼容；
    取不到就返回 0 —— 遥测本身绝不允许成为失败点。
    """
    try:
        timing = response.request.timing
        if callable(timing):
            timing = timing()
        if asyncio.iscoroutine(timing):
            timing = await timing
    except Exception:
        return 0
    if not isinstance(timing, dict):
        return 0

    def pick(*keys: str) -> float:
        for key in keys:
            value = timing.get(key)
            if isinstance(value, (int, float)) and value >= 0:
                return float(value)
        return -1.0

    request_start = pick("requestStart")
    response_end = pick("responseEnd")
    response_start = pick("responseStart")

    if request_start >= 0 and response_end >= request_start:
        return int(response_end - request_start)
    if request_start >= 0 and response_start >= request_start:
        return int(response_start - request_start)
    return 0


class ResponseMirror:
    """挂在 BrowserContext 上，把匹配的响应抄一份下来。"""

    def __init__(
        self,
        *,
        include: Sequence[str] = DEFAULT_INCLUDE,
        exclude: Sequence[str] = (),
        capture_body: bool = True,
        capture_static_bodies: bool = False,
        max_body_bytes: int = 8_000_000,
    ):
        self.include = tuple(include)
        self.exclude = tuple(exclude)
        self.capture_body = capture_body
        # 是否连静态资源（JS/CSS/图片）的正文也读。默认关：
        # 这是浏览器卡顿的头号原因，而且静态资源的正文对采集毫无价值。
        self.capture_static_bodies = capture_static_bodies
        self.max_body_bytes = max_body_bytes
        self._captured: list[CapturedResponse] = []
        self._pending: set[asyncio.Task] = set()
        self._context: Any = None
        self.bodies_read = 0
        self.bodies_skipped = 0

    # ── 生命周期 ────────────────────────────────────────────

    def attach(self, context: Any) -> None:
        self._context = context
        context.on("response", self._on_response)

    def detach(self) -> None:
        if self._context is not None:
            try:
                self._context.remove_listener("response", self._on_response)
            except Exception:
                pass
            self._context = None

    def _on_response(self, response: Any) -> None:
        try:
            url = response.url
        except Exception:
            return
        if not _matches(url, self.include):
            return
        if self.exclude and _matches(url, self.exclude):
            return
        try:
            task = asyncio.get_running_loop().create_task(self._collect(response))
        except RuntimeError:
            return
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _collect(self, response: Any) -> None:
        headers = getattr(response, "headers", None) or {}
        content_type = headers.get("content-type", "")
        try:
            resource_type = response.request.resource_type or ""
        except Exception:
            resource_type = ""

        item = CapturedResponse(
            url=response.url,
            status=int(getattr(response, "status", 0) or 0),
            content_type=content_type,
            resource_type=resource_type,
        )

        # 先判断要不要读 body —— 不读才是性能优化，读完再丢没用
        wants_body = self.capture_body and (
            self.capture_static_bodies
            or looks_like_data(content_type, response.url, resource_type)
        )
        if wants_body:
            try:
                body = await response.body()
                if len(body) <= self.max_body_bytes:
                    item.body = body
                else:
                    item.extra["truncated"] = len(body)
                self.bodies_read += 1
            except Exception as exc:
                item.error = f"body 读取失败：{exc}"
        else:
            item.extra["body_skipped"] = True
            self.bodies_skipped += 1

        # 必须在 body 读完之后取耗时，否则 responseEnd 还是 -1
        item.duration_ms = await _duration_ms(response)
        self._captured.append(item)

    async def drain(self, *, timeout: float = 20.0) -> None:
        """等所有在途的 body 读取完成。"""
        if not self._pending:
            return
        pending = list(self._pending)
        try:
            await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=timeout)
        except asyncio.TimeoutError:
            pass

    # ── 取数 ────────────────────────────────────────────────

    def take(self, *, pattern: str | None = None) -> list[CapturedResponse]:
        if pattern is None:
            out, self._captured = self._captured, []
            return out
        out = [c for c in self._captured if _matches(c.url, (pattern,))]
        self._captured = [c for c in self._captured if c not in out]
        return out

    def peek(self) -> list[CapturedResponse]:
        return list(self._captured)

    def json_items(self, *, pattern: str | None = None) -> list[tuple[str, Any]]:
        out: list[tuple[str, Any]] = []
        for item in self.take(pattern=pattern):
            if item.is_json and item.body:
                payload = item.json()
                if payload is not None:
                    out.append((item.url, payload))
        return out

    def clear(self) -> None:
        self._captured.clear()

    def stats(self) -> dict[str, Any]:
        return {
            "captured": len(self._captured),
            "pending": len(self._pending),
            "include_patterns": list(self.include),
            "bodies_read": self.bodies_read,
            "bodies_skipped": self.bodies_skipped,
            "capture_static_bodies": self.capture_static_bodies,
        }


def iter_dicts(node: Any) -> Iterable[dict]:
    """深度遍历任意 JSON 结构，产出所有 dict。解析层的公共基础。"""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from iter_dicts(value)
    elif isinstance(node, list):
        for value in node:
            yield from iter_dicts(value)


def ascii_safe(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")
