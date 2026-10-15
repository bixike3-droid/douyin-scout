"""配置加载：default.yaml < local.yaml < 环境变量 SCOUT_*。

只用标准库（dataclasses + PyYAML），配置对象不可变，加载后全局共享。
所有可调参数都必须经过这里，代码里不允许出现魔法数字。
"""

from __future__ import annotations

import os
from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

from .paths import Paths

try:  # PyYAML 可能在未安装依赖时缺失，保持核心模块可导入
    import yaml
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


# ── YAML 合并 ────────────────────────────────────────────────


def deep_merge(base: dict, override: dict) -> dict:
    """递归合并，override 优先。列表整体替换，不做拼接。"""
    out = dict(base)
    for k, v in (override or {}).items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    if yaml is None:
        raise RuntimeError("未安装 PyYAML，无法读取配置文件；请先运行 scripts/setup.ps1")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"配置文件顶层必须是映射：{path}")
    return data


def _coerce(raw: str) -> Any:
    """环境变量字符串 → 合适的 Python 类型。"""
    low = raw.strip().lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("none", "null", ""):
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _env_overrides(prefix: str = "SCOUT_") -> dict:
    """SCOUT_TIERS__B__DAILY_REQUEST_QUOTA=100 → {'tiers': {'b': {'daily_request_quota': 100}}}"""
    out: dict = {}
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        path = key[len(prefix):].lower().split("__")
        if not path or not path[0]:
            continue
        node = out
        for part in path[:-1]:
            node = node.setdefault(part, {})
        node[path[-1]] = _coerce(value)
    return out


# ── 配置结构 ─────────────────────────────────────────────────


@dataclass(frozen=True)
class AppConfig:
    timezone: str = "Asia/Shanghai"
    max_tasks_per_run: int = 40


@dataclass(frozen=True)
class TierConfig:
    name: str = "b"
    enabled: bool = True
    mode: str = "anonymous"          # logged_in | anonymous
    profile_dir: str = ""
    # 用 storage_state 文件建立会话，而不是持久 profile 目录。
    #
    # 这是**无头服务器**需要的：服务器上没有屏幕没法扫码，
    # 而且持久 profile 跨机器/跨浏览器搬不动（本地 Edge on Windows →
    # 服务器 Chromium on Linux）。
    #
    # 打开后流程变成：本地扫码登录 → 导出 state → 拷到服务器 → 注入。
    # 服务器上不需要显示器，也不需要 Edge。
    use_storage_state: bool = False
    # 每日「动作」上限。**0 = 不限制（默认）**。
    #
    # 为什么默认不限：配额记的是"我们做了几个动作"（一次导航算 1 个，
    # 展开一条通知再加 1 个），不记页面自己发了多少请求。
    # 日常采集一天也就几个到几十个动作，远低于任何会被注意的量级，
    # 此时设上限只会挡住你自己的正常操作。
    #
    # 什么时候该设：数据量大起来之后（比如几千个点赞人要逐个访问主页），
    # 主动加一道总量闸门更稳妥。设了就按天计数，到点自动停。
    #
    # 真正防封的是**节流**和**熔断**，不是这个数字。
    daily_request_quota: int = 0
    min_delay_s: float = 1.5
    max_delay_s: float = 4.0
    page_stay_s: float = 1.0
    headless: bool = True
    scroll_rounds: int = 5

    def resolved_profile_dir(self, paths: Paths) -> Path:
        """浏览器 profile（登录态）放哪。

        ⚠️ 这里踩过一个**账号隔离直接失效**的坑（2026-10-10）：
        原来写的是 `Path("data/profiles") / f"tier_{name}"` —— **硬编码路径，
        完全无视传进来的 `paths`**。结果所有账号共用同一个 profile 目录，
        "一个账号一个数据目录"的隔离在登录态这一层直接漏掉了。

        正确做法：没显式配 `profile_dir` 时，落到**当前账号**的 profiles 目录下。
        """
        if self.profile_dir:
            p = Path(self.profile_dir)
            return p if p.is_absolute() else (paths.root / p)
        return paths.profiles_dir / f"tier_{self.name}"


@dataclass(frozen=True)
class CircuitConfig:
    consecutive_empty_open: int = 5
    consecutive_error_open: int = 8
    cooldown_minutes: int = 45


@dataclass(frozen=True)
class BackoffConfig:
    base_s: int = 60
    factor: float = 2.0
    max_s: int = 3600


@dataclass(frozen=True)
class ThrottleConfig:
    jitter_ratio: float = 0.35
    long_pause_every: int = 25
    long_pause_min_s: float = 20.0
    long_pause_max_s: float = 60.0


@dataclass(frozen=True)
class GuardConfig:
    circuit: CircuitConfig = field(default_factory=CircuitConfig)
    backoff: BackoffConfig = field(default_factory=BackoffConfig)
    throttle: ThrottleConfig = field(default_factory=ThrottleConfig)


@dataclass(frozen=True)
class BrowserConfig:
    channel: str = ""
    cdp_url: str = ""                # 非空则连接你自己启动的真实浏览器，不新开进程、不伪造
    locale: str = "zh-CN"
    timezone: str = "Asia/Shanghai"
    viewport_width: int = 1440
    viewport_height: int = 900
    user_agent: str = ""
    block_resources: tuple[str, ...] = ("image", "media", "font")
    block_url_globs: tuple[str, ...] = ()


@dataclass(frozen=True)
class StorageConfig:
    # ── 保留策略 ────────────────────────────────────────────
    #
    # 归档正文保留几天。**只删正文，保留元数据** ——
    # raw_blobs 行只占几字节，raw/ 下的正文占几十 MB。
    # 留下来 sha256/url/byte_size/collected_at，"曾经采过什么"仍可追溯。
    # 0 = 永不清理（会让磁盘慢慢满）。
    raw_retention_days: int = 7
    # 请求日志 / 事件日志保留几天
    log_retention_days: int = 30
    # 已完成的任务保留几天（pending/failed 不删）
    task_retention_days: int = 14
    # 点赞边多久没被再次确认就标记为陈旧。
    # **只标记不删除** —— 可能是接口偶发返回不全，删了就找不回来。
    edge_stale_days: int = 30

    raw_max_bytes: int = 8_000_000
    # 是否归档静态资源（JS/CSS/图片/埋点）。
    # 默认 False：一次页面加载几百个静态文件，存下来一天涨几个 GB，
    # 而且真正要看的数据接口会被淹没。只有需要研究前端实现时才打开。
    archive_static: bool = False
    # 是否把静态资源也写进请求日志。默认 False，同上。
    log_static: bool = False


@dataclass(frozen=True)
class TargetsConfig:
    home_url: str = "https://www.douyin.com"
    # 入口是**你自己的个人主页**：右侧的「互动消息」面板就在这个页面上。
    # 点开「等 N 人赞了你的作品」会弹出「赞过的人」覆盖层，全程不跳转。
    notice_url: str = "https://www.douyin.com/user/self?from_tab_name=main&showTab=post"
    notice_url_candidates: tuple[str, ...] = (
        "https://www.douyin.com/user/self?from_tab_name=main&showTab=post",
        "https://www.douyin.com/user/self",
        "https://www.douyin.com/notification",
        "https://www.douyin.com/message",
    )

    # ── 打开展开前的准备动作（比如先点开「互动消息」面板）──
    # 指向 config 里 interactions 的键名；留空 = 面板本来就开着
    notice_pre_actions: str = "notice_pre"
    # 兜底：如果 notice_pre 没把面板打开，就按这个顺序逐个试点，
    # 每点一次都验证「页面上有没有出现点赞文案」。
    # ⚠️ 顺序有讲究：实测点「消息」打开的是**私信**页，
    #    互动消息在「通知」下面，所以「通知」排第一。
    notice_open_texts: tuple[str, ...] = ("通知", "互动消息", "全部消息", "消息")

    # ── 滚动 ──
    # 互动消息是**面板内部滚动**，必须把鼠标悬停到面板上滚轮才生效。
    # 不填这个会导致永远滚不动 → 被误判成触底 → 静默采到 0 条。
    notice_scroll_over: str = ""
    # 单轮通知流采集最多滚多少轮（防止无底洞）
    notice_max_rounds: int = 40
    # 触底判定文本（页面上出现这些字样就认为拿完了）
    notice_end_texts: tuple[str, ...] = (
        "暂时没有更多了",
        "没有更多了",
        "没有更多",
        "到底了",
        "已显示全部",
        "暂无更多",
    )
    # 连续多少轮没有新响应就判定到底
    notice_idle_rounds: int = 3

    # ── 形态 B：通知按作品聚合，需要点开才看到完整点赞人 ──
    # 展开前先点「打开」动作（默认是条目右侧那个 › 箭头按钮）
    notice_click_actions: str = "notice_click"
    # 列表打开之后做什么（等加载 + 滚动）
    notice_expand_actions: str = "notice_expand"
    # 展开完之后用来收尾的脚本（点「返回」/关浮层）。留空则默认按 Escape
    notice_close_actions: str = "notice_close"
    # 通知条目选择器；填了才逐个条目展开，否则整页只展开一次
    notice_item_selector: str = ""
    # 更省事的办法：**用文案正则**枚举聚合条目，不需要 CSS 选择器。
    # 抖音的类名是混淆的，但文案稳定。截图里的形态是「JJ 等22人赞了你的作品」。
    notice_item_pattern: str = r"等\s*\d+\s*人赞了你的作品"
    # 单轮最多展开多少个条目（防止把配额烧光）
    notice_max_items: int = 20
    # 互动消息是周期任务：距上次完成不足这个分钟数就跳过重新入队，
    # 防止连续手滑触发多次。设 0 表示每次都重新跑。
    notice_min_interval_minutes: int = 30

    user_url_template: str = "https://www.douyin.com/user/{sec_uid}"

    # ── 点赞人接口（/aweme/v1/web/favorite/list/）──
    # 实测：单页最多 50 人，超过会被接口拒绝（status_code=5）。
    # 但**分页是通的**：用上一页返回的 max_cursor 翻下一页，has_more 变 false 就到底。
    # 所以"全部点赞人"是能拿全的，代价是 ceil(点赞数 / 50) 次请求。
    likers_page_size: int = 50
    # 单个作品最多翻多少页（50 × 40 = 2000 人）。防止某个爆款把请求量拉爆。
    likers_max_pages: int = 40

    # ── 作品列表接口（/aweme/v1/web/aweme/post/）──
    # 同样是页面内 fetch、不需要签名。这是 AI 画像的原料。
    works_page_size: int = 18
    works_max_pages: int = 20
    # 每人最多采多少个作品（0 = 不限，按 max_pages 走）
    works_per_user_limit: int = 60
    api_min_delay_s: float = 1.5
    api_max_delay_s: float = 3.0
    quick_works_limit: int = 12
    collection_ttl_hours: int = 24
    # 统计数据的保鲜期（天）。超过就重新采一遍 ——
    # 点赞评论是会一直涨的，采一次永不更新等于在页面上挂一个冻结的数字。
    works_stats_ttl_days: int = 3
    # 每轮最多刷新多少个作品的统计（防止一次跑太久）
    works_stats_refresh_limit: int = 60

    def user_url(self, sec_uid: str) -> str:
        return self.user_url_template.format(sec_uid=sec_uid)


@dataclass(frozen=True)
class WebConfig:
    host: str = "127.0.0.1"
    port: int = 8787


@dataclass(frozen=True)
class LLMConfig:
    """大模型配置。

    放在独立的 config/llm.local.yaml 里，**不进版本库** ——
    避免 api_key 和普通配置混在一起被误提交。
    """
    provider: str = "deepseek"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    timeout_s: int = 120
    max_retries: int = 2
    max_concurrency: int = 3
    temperature: float = 0.3
    # 喂给模型的作品采样：全塞会超上下文，也费钱
    works_top_by_likes: int = 10
    works_recent: int = 6

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True)
class SearchConfig:
    """联网搜索配置。

    provider 取值：
    - ""（默认）：自动模式——有 DeepSeek Key 就用服务端搜索，没有则提示先配置；
    - "deepseek"：DeepSeek 服务端搜索。复用 llm.api_key，不另要搜索 Key；
      搜索在 DeepSeek 服务器执行、按量计费（usage.server_tool_use.web_search_requests）；
    - "tavily" / "bocha"：第三方搜索 API，需要 api_key；
    - "off"：关闭联网搜索（web_search 直接说明已关闭）。
    """
    provider: str = ""
    api_key: str = ""
    # deepseek 服务端搜索的模型与端点；base_url 留空 = llm.base_url + /anthropic/v1
    model: str = "deepseek-v4-flash"
    base_url: str = ""

    @property
    def enabled(self) -> bool:
        """是否显式配置了第三方搜索（deepseek 复用 llm key，不靠这里判断）。"""
        return bool(self.provider and self.api_key)


@dataclass(frozen=True)
class Config:
    paths: Paths
    app: AppConfig
    tiers: dict[str, TierConfig]
    guard: GuardConfig
    browser: BrowserConfig
    storage: StorageConfig
    targets: TargetsConfig
    web: WebConfig
    # 声明式页面交互脚本：{"notice_expand": [{"action": "click_text", "text": "查看全部"}, ...]}
    # 放在这里而不是写死在代码里，是为了改版时只改 YAML。
    interactions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    llm: LLMConfig = field(default_factory=LLMConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    sources: tuple[str, ...] = ()

    def tier(self, name: str) -> TierConfig:
        try:
            return self.tiers[name]
        except KeyError:
            raise KeyError(f"未定义档位 {name!r}；已定义：{sorted(self.tiers)}") from None

    def interaction(self, name: str) -> list[dict[str, Any]]:
        """取一组交互脚本；不存在返回空列表（视为不做交互）。"""
        if not name:
            return []
        return list(self.interactions.get(name) or [])

    def enabled_tiers(self) -> list[str]:
        return [n for n, t in sorted(self.tiers.items()) if t.enabled]


# ── 反序列化 ─────────────────────────────────────────────────


def _build(cls, data: dict | None):
    """按 dataclass 字段构造，忽略未知键，缺失用默认值。"""
    data = data or {}
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        raw = data[f.name]
        if f.default_factory is not MISSING:  # type: ignore[misc]
            default = f.default_factory()  # type: ignore[misc]
        elif f.default is not MISSING:
            default = f.default
        else:
            default = None
        if is_dataclass(type(default)):
            kwargs[f.name] = _build(type(default), raw)
        elif isinstance(default, tuple) and isinstance(raw, list):
            kwargs[f.name] = tuple(raw)
        else:
            kwargs[f.name] = raw
    return cls(**kwargs)


def load_config(paths: Paths | None = None, extra_files: list[Path] | None = None) -> Config:
    paths = (paths or Paths.build()).ensure()
    merged: dict = {}
    sources: list[str] = []
    # llm.local.yaml 单独一份，专门放 api_key，避免它混进普通配置
    files = [
        paths.default_config,
        paths.local_config,
        paths.config_dir / "llm.local.yaml",
        *(extra_files or []),
    ]
    for f in files:
        if f.is_file():
            merged = deep_merge(merged, _load_yaml(f))
            sources.append(str(f))
    env = _env_overrides()
    if env:
        merged = deep_merge(merged, env)
        sources.append("env:SCOUT_*")

    tiers: dict[str, TierConfig] = {}
    for name, raw in (merged.get("tiers") or {}).items():
        tiers[name] = _build(TierConfig, {"name": name, **(raw or {})})
    if not tiers:
        tiers = {"b": TierConfig(name="b")}

    return Config(
        paths=paths,
        app=_build(AppConfig, merged.get("app")),
        tiers=tiers,
        guard=_build(GuardConfig, merged.get("guard")),
        browser=_build(BrowserConfig, merged.get("browser")),
        storage=_build(StorageConfig, merged.get("storage")),
        targets=_build(TargetsConfig, merged.get("targets")),
        web=_build(WebConfig, merged.get("web")),
        interactions=dict(merged.get("interactions") or {}),
        llm=_build(LLMConfig, merged.get("llm")),
        search=_build(SearchConfig, merged.get("search")),
        sources=tuple(sources),
    )
