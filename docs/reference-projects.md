# 参照项目调研（M0 前置）

调研时间：2026-10-09。目的：确认我们要做的事有成熟先例、借鉴其架构、避免重复踩坑。

---

## 一、主要参照对象

### 1. NanmiCoder/MediaCrawler —— 主参照

- 地址：https://github.com/NanmiCoder/MediaCrawler
- 规模：**66,514 star / 12,751 fork**，Python，调研当天仍在推送更新（2026-10-09）
- 覆盖：小红书 / 抖音 / 快手 / B站 / 微博 / 贴吧 / 知乎
- 技术路线：Playwright 启动浏览器 → 扫码登录 → 保存登录态 → 页面内取数 / 配合签名客户端请求

**它的分层（从目录树读出来的真实结构）：**

```
base/base_crawler.py      4 个抽象接口：AbstractCrawler / AbstractLogin
                          / AbstractStore / AbstractApiClient
cache/                    abs_cache.py + local_cache.py + redis_cache.py + factory
config/                   base_config.py + 每平台一个 dy_config.py 等
constant/                 平台常量
database/                 db.py / db_session.py / models.py / mongodb_store_base.py
cmd_arg/arg.py            16KB，所有命令行参数集中一处
tools/                    browser_launcher.py(11.6KB) / cdp_browser.py(22KB)
                          / crawler_util.py / slider_util.py / easing.py
                          / async_file_writer.py / user_hash.py / time_util.py
api/                      FastAPI：routers(crawler|data|websocket) + crawler_manager
webui/                    React + Vite + Tailwind，i18n 双语
```

**最有价值的四个设计点：**

1. **只有 4 个抽象基类**（`base_crawler.py` 仅 3.2KB）。薄抽象，平台实现各自独立，不搞过度设计。
2. **`AbstractApiClient.update_cookies()`** —— 这是关键机制：浏览器负责登录和维持真实环境，
   登录后把 cookie 同步给 HTTP 客户端，由后者发高频请求。**混合架构**，不是二选一。
3. **`tools/easing.py`** —— 缓动函数，用于拟人化滚动和鼠标轨迹。我们原设计漏了这一层。
4. **`cache/` 抽象 + factory** —— 去重缓存做成了可替换后端（本地 / Redis）。印证了
   「去重是最大收益优化」这个判断，且它必须是独立抽象层。

**另外注意到的信号：**
- 有 `tools/slider_util.py`（滑块处理）——说明风控弹窗是常态，不是偶发。
- 有 `tools/cdp_browser.py`（22KB）+ `docs/CDP模式使用指南.md` ——CDP 连接模式是一等公民。
- 有 `tools/async_file_writer.py` ——高频写文件不阻塞主流程。

### 2. paopaojun/Douyin_Curation_Assistant —— 场景最贴近

- 地址：https://github.com/paopaojun/Douyin_Curation_Assistant
- 描述：抖音自动互动 + 自动获取作者/作品/评论区信息 + **创作者画像**，本地化数据采集与运营工作流
- 技术路线：Node.js + Express + SQLite 后端，Vue3 + Vite 前端（与我们的选型不同，但架构可借鉴）

**它的目录里最值得看的是「浏览器实验室」这一块：**

```
server/labs/douyin_browser_lab/
    captureStore.js          采集结果存储
    extractActionSummary.js  从一次动作里提取摘要
    watchBrowser.js(15KB)    观察浏览器实际发了什么请求
    sessionHealth.js         会话健康检查
    runAction.js(15.5KB)     执行一个浏览动作
server/src/scripts/
    captureActionRequests.js 采集某个动作触发的请求
    prepareBrowserSession.js 准备浏览器会话
server/src/services/douyin/
    sessionCoordinatorService.js(15.7KB)   会话协调
    profileLockService.js                   profile 独占锁
    runtimeSessionCacheService.js           运行期会话缓存
    headers.js                              请求头集中管理
```

**这四个设计直接补上了我们原方案的缺口：**

1. **profile 独占锁** —— Playwright 持久化 profile 不能被两个进程同时打开。
   原方案完全没考虑，实际跑起来第二个进程会直接崩。**必须补。**
2. **会话健康检查** —— 需要独立的「登录态还有效吗」探测，不能等到采集返回空才发现。
3. **会话协调 + 运行期会话缓存** —— 多任务共享一个浏览器会话时的调度问题。
4. **capture / action summary** —— 记录「这个动作触发了哪些请求」，正是我们 `scout probe` 要做的事，
   它把它做成了一等公民模块。

**用户分析侧的模型命名也很有参考价值：**
`CreatorProfile` / `RecommendAuthorSnapshot`（作者快照，做时间序列）/
`ActionExecutionLog` / `OperationLog` / `AnalysisDictionary`（分析词典）。
**「快照」这个思路我们漏了** —— 只存当前值，就失去趋势分析能力。要补 `user_snapshots` 表。

### 3. 其它

| 项目 | 用途 | 结论 |
|---|---|---|
| [JoeanAmier/Douyin_TikTok_Download_API](https://github.com/JoeanAmier/Douyin_TikTok_Download_API) | 异步 API 化爬取 | 偏下载器，与我们的互动分析场景不同 |
| [Johnserf-Seed/f2](https://github.com/Johnserf-Seed/f2) | 多平台高速下载器 | 同上 |
| [amxsa/douyin_abogus_python](https://github.com/amxsa/douyin_abogus_python) | 纯 Python 的 a_bogus 实现 | **明确不采用**，见下 |

---

## 二、许可证警告（重要）

- **MediaCrawler 不是标准开源协议。** GitHub 标记为 `NOASSERTION`，源码文件头部写明
  `Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1`，条款包含：不得商用、不得大规模爬取、
  应控制请求频率、须遵守目标平台条款。
- **Douyin_Curation_Assistant 根目录没有 LICENSE 文件**，默认保留所有权利。
- 该项目还内置了 `server/src/vendors/douyin/dy_ab.cjs`（**540KB 的 a_bogus 签名实现**）。

**结论：只借鉴架构思想和目录划分，不复制任何一行代码。**
签名实现（`dy_ab.cjs`、`douyin_abogus_python`）一律不引入——既是许可证问题，
也把我们拖进「绕过技术保护措施」的区间，正是本方案要避开的。

---

## 三、并入本项目的改进

| # | 借鉴点 | 来源 | 落到哪 |
|---|---|---|---|
| 1 | 拟人化缓动（滚动/延时曲线） | MediaCrawler `easing.py` | 新增 `scout/humanize.py` |
| 2 | 去重缓存做成抽象 + 工厂 | MediaCrawler `cache/` | 新增 `scout/store/cache.py` |
| 3 | 薄抽象：Crawler/Login/Store/Client 四接口 | MediaCrawler `base_crawler.py` | 已体现在 `collect/base.py`、`session/`、`store/` |
| 4 | 浏览器持 cookie → HTTP 客户端发高频请求 | MediaCrawler `update_cookies()` | 预留 `session/api_client.py` 接口，**默认不启用** |
| 5 | profile 独占锁 | Douyin_Curation_Assistant `profileLockService` | 新增 `scout/session/lock.py` |
| 6 | 登录态健康检查 | 同上 `sessionHealth.js` | 新增 `scout/session/health.py` |
| 7 | 浏览器实验室（动作→请求 的采集） | 同上 `douyin_browser_lab/` | `scout/lab/`，即 `scout probe` 的实现 |
| 8 | 用户快照表（趋势分析） | 同上 `RecommendAuthorSnapshot` | schema 增 `user_snapshots` |
| 9 | 实时推送日志到前端 | MediaCrawler `api/routers/websocket.py` | Web UI 用 SSE（比 WS 简单，够用） |
| 10 | 用户标识哈希脱敏 | MediaCrawler `tools/user_hash.py` | 并入 `scout/util.py` |

---

## 四、没有被借鉴的（有意为之）

| 做法 | 为什么不跟 |
|---|---|
| 自实现 a_bogus 签名 + 直连 API | 维护成本极高、风控识别度更高、且踩「绕过技术措施」红线。速度收益在配额内≈0 |
| 多平台通用化 | 我们只做抖音；通用抽象会稀释掉场景深度 |
| 商用化 / Pro 订阅 / 云端 | 明确不做，本地单机自用 |
| 高并发 + 代理池 | 风控最先抓的就是并发特征；单 IP 低频是长期存活的前提 |
