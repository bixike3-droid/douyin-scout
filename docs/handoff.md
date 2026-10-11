# 交接文档

> **新会话 / 新 AI 请先读这一份。**
> 读完你应该能：知道这是什么、怎么跑、做到哪了、下一步做什么、哪些路已经试过并否掉了。
>
> 最后更新：2026-10-11

---

## 0. 先看这里 —— 用户的工作方式

**这一节比技术内容更重要。读它能让协作顺畅，不读会用错力气。**

| 用户的风格 | 你该怎么做 |
|---|---|
| **极度反感"空口来凤"** | **没跑过的不要说"能"、不要说"成功"、不要说"突破"**。说"我试了，结果是这样"。 |
| 反复强调**"每个业务闭环必须跑通"** | 不要跳步。一步没验证完不要开下一步。 |
| 曾经因为**把用户的手动成果说成程序的突破**而发过火 | 严格区分"程序做的"和"人做的"。 |
| 说**"不图快，只图稳定"** | 宁可慢，不要为了看起来快而掩盖问题。 |
| 发现问题时会**直接骂**，但骂完继续干活 | 不要道歉太多，**去修**。 |
| 会**明确下达"禁止修改"** | 那一轮就只读、只分析、只回答，**一个字都不要改**。 |
| 要求**先本地测通再上服务器** | 别急着部署。 |

**沟通用中文。**

---

## 1. 这是什么

抖音互动数据采集 + AI 受众分析。

从**你自己的抖音账号**出发：取回每条作品的**完整点赞人名单** → 拉回他们的公开主页与作品 → 交给大模型分析每个点赞人是谁、和你内容有多契合 → 反哺到**作品评价**和**下一步内容计划**。

**当前形态：桌面应用**（PyWebView 原生窗口，打包成单个 exe）。

---

## 2. 怎么跑起来（新机器从零）

```powershell
# 1. 克隆（私有仓库，需要认证）
git clone https://github.com/bixike3-droid/douyin-scout.git
cd douyin-scout

# 2. 建环境（项目是 src 布局，必须 pip install -e .）
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
.\.venv\Scripts\python.exe -m pip install pywebview playwright -i https://pypi.tuna.tsinghua.edu.cn/simple
.\.venv\Scripts\python.exe -m playwright install chromium

# 3. 确认没坏（应该 199 项全过）
.\.venv\Scripts\python.exe -m pytest -q

# 4. 跑桌面版
.\.venv\Scripts\python.exe desktop\app.py
```

**两个文件不在仓库里**（密钥和数据不进版本库），需要自己建：

| 文件 | 内容 |
|---|---|
| `config/local.yaml` | 本机配置覆盖（可选） |
| `config/llm.local.yaml` | DeepSeek API Key（**用户自己的**） |

`config/llm.local.yaml` 格式：

```yaml
llm:
  provider: deepseek
  api_key: "sk-..."
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
```

**也可以在界面上填**（概览页有配置卡片，会当场验证 Key 有效性）。

---

## 3. 当前状态：什么已验证、什么没有

### ✅ 已经跑通并验证过的

| 项 | 证据 |
|---|---|
| 采集链路（3 个接口全自动） | `fetch_self` / `fetch_likers` / `fetch_user_works` 实测成功，27/27 点赞人一个不少 |
| AI 分析（画像 / 作品评价 / 下一步计划） | 真实调用 DeepSeek，输出结构化 JSON |
| 桌面原生窗口 | WebView2 进程实测起来了 |
| **打包成 exe** | `dist\douyin-scout.exe` 57.8 MB，**空目录双击实测通过**（自动建目录、建表、开窗口、零报错） |
| 199 项测试 | 全过 |
| 账号隔离 | 独立数据目录，物理隔离 |
| 数据保留策略 | 归档 7 天 / 日志 30 天 / 陈旧点赞边标记 |
| 本地助手（登录用） | CORS 白名单实测（`evil.com` 被拒） |

### ⬜ 没验证过的（不要声称它行）

| 项 | 说明 |
|---|---|
| **桌面窗口里的完整流程** | 只验证了"窗口打开 + 无报错"，**没在里面点过登录 / 采集 / AI** |
| **全新机器上的 exe** | 开发机有 Playwright 浏览器；**干净电脑上首次运行不会自动下载浏览器**，会报找不到浏览器 |
| 服务器上的多用户流程 | 服务器跑着旧版本，没有真实用户数据 |
| 抖音扫码登录在用户环境下 | 理论上可行（真实环境过验证码），**没有实测** |

### ⚠️ 已知问题

| 问题 | 影响 |
|---|---|
| exe 首次运行不自动装浏览器 | **分发障碍**，需要在启动时检测并下载 |
| 服务器是架构改造前的遗留 | 按新架构应改成"产品介绍 + 下载"落地页 |
| `fetch_profile` 采集器返回空 | 但它已经冗余 —— `favorite/list` 接口已给完整主页数据 |

---

## 4. 下一步该做什么

**按优先级：**

1. **在桌面窗口里点一遍完整流程** —— 登录 → 采集 → AI 分析
   （改了代码后重启 `desktop\app.py`，看有没有断的地方）
2. **解决"全新机器自动装浏览器"** —— 分发的前提
3. **服务器改成落地页** —— 如果继续走桌面路线，服务器网页只需要放介绍 + 下载
4. 首次启动向导（现在概览页有六步引导，但没有专门的首次弹窗）

---

## 5. 架构决策历史（**别再提已被否掉的方案**）

这些是讨论过的路线，以及为什么被否：

| 方案 | 结论 | 原因 |
|---|---|---|
| **服务器上的多用户网页登录** | ❌ 否 | 抖音对全新匿名上下文一律返回「验证码中间页」（无头/有头/改UA 实测都一样）。要过就得破解滑块验证 + `__ac_signature` 签名 |
| **破解抖音签名算法** | ❌ **明确不做** | 项目唯一的硬原则：**不实现请求签名，让真实浏览器发请求，我们只镜像响应**。破解 = 推翻地基，而且平台改版就要跟 |
| **书签小工具自动读 cookie** | ❌ 否 | 实测：登录凭据**全是 HttpOnly**（sessionid / sid_tt / odin_tt / ttwid…），网页 JS 读不到 |
| **浏览器扩展** | ⚠️ 可用但没做 | 能读 HttpOnly，但分发是障碍（商店审核 / 开发者模式） |
| **本地助手**（已做） | ✅ 采用 | 登录在用户自己环境完成，无风控、无隐私问题 |
| **全本地桌面应用**（已做） | ✅ 当前路线 | 前面那些补丁（账号隔离、无头模式、CORS…）在桌面形态下全部不需要 |
| **PyQt 原生 UI** | ❌ 否 | 要重写 1100 行界面，**而且数据可视化会比网页更朴素**（用户以为"网页不好看"，其实网页图形上限更高） |

**当前架构：**

```
桌面程序（用户自己电脑）
├── 采集      Playwright，用户自己的 IP → 无风控
├── 登录      用户扫码，cookie 存本机 → 无隐私问题
├── AI        用户自己的 DeepSeek Key
├── 界面      PyWebView 原生窗口（内部 WebView2）
└── 数据      用户本机 SQLite（userdata/data/accounts/main/）
```

---

## 6. 踩过的坑（**别再踩**）

每条都是真实踩过、且花了时间才定位的。

### 采集侧

| 坑 | 症状 | 教训 |
|---|---|---|
| **解析器递归扫全响应** | 98 粉丝的号挂着 178 万赞视频 | `_parse_user_works` 原来用 `extract_works()` 递归扫整个 payload，把抖音塞的推广位视频当成了作者作品。**只读 `aweme_list` + 按作者过滤 + 落库再校验**（三层防护） |
| **游标键名对不上** | 「接口说 33 个作品，只采到 17」 | 解析器返回 `cursor`，翻页逻辑读 `max_cursor` → 每页拿到 None → 判定到底了。**键名两个都给** |
| **`min_cursor` = `max_cursor`** | 第二页返回 0 条 | 作品列表接口不接受这个写法。**只给 `max_cursor`** |
| **空结果被当降级** | 采几十个人后熔断误触发 | 接口干净返回 `status_code=0` 但列表为空 = 这个人没作品，**不是账号被降级** |

### 部署侧

| 坑 | 症状 | 教训 |
|---|---|---|
| **`browser.channel: msedge`** | 服务器报 `Chromium distribution 'msedge' is not found` | 服务器/打包**必须留空**用自带 Chromium |
| **前端 JS 被 PowerShell 吃掉反引号** | 页面**能打开但功能全废** | 用正则往 HTML 插 JS 时，`` `nav `` 变成换行、`` `${name}` `` 变成 `${name}` → 整个 script 解析失败。**静态 HTML 照样渲染，极难发现** |
| **打包漏了 `db/migrations`** | exe 启动即报 `no such table: cursor_state` | `--add-data` 要带上 `.sql` 迁移文件 |
| **打包带 `config;config`** | **把开发者的 API Key 分发出去** | 只带 `default.yaml`，密钥让用户自己填 |
| **`launch_persistent_context` 不接受 `storage_state`** | 无法注入登录态 | 只能用 `new_context(storage_state=...)` |
| **登录态目录硬编码** | 账号隔离形同虚设 | `resolved_profile_dir` 原来写死 `Path("data/profiles")`，**无视传入的 paths** |
| **新加字段没回填** | 28 条点赞边全被判成陈旧 | 加 `last_confirmed_at` 默认空 → 所有历史数据都是"从未确认"。**用 discovered_at 回填** |

### 平台侧（抖音）

| 事实 | 影响 |
|---|---|
| 登录凭据**全是 HttpOnly** | 网页 JS 读不到 → 任何"网页上自动拿 cookie"的方案都不可行 |
| 全新匿名上下文 → **验证码中间页** | 服务器侧登录不可行 |
| `favorite` 在抖音是**点赞**不是收藏 | `/aweme/v1/web/favorite/list/` = 某作品的**完整点赞人名单**（一次 50 人，带完整主页数据） |
| 这些接口**不需要 a_bogus 签名** | 用浏览器会话直接 `fetch` 就返回 200。**这是整个项目的关键发现** |
| `aweme_count` 字段不准 | 说 33 实际 76。**只能当参考** |
| `is_verified` 布尔在 `favorite/list` 里**全员为 true** | 不可信，只在有 `custom_verify` 文案时才算认证 |

---

## 7. 代码导航

| 路径 | 作用 |
|---|---|
| `desktop/app.py` | **桌面版入口**（3.5 KB，很短，先读它） |
| `desktop/打包.bat` | 打包脚本（含所有坑的注释） |
| `src/scout/cli.py` | 命令行入口（所有子命令） |
| `src/scout/collect/likers.py` | **点赞人名单**采集器（核心） |
| `src/scout/collect/user_works_api.py` | 点赞人作品采集器 |
| `src/scout/collect/api_base.py` | 接口型采集器基类（翻页、归档、限速） |
| `src/scout/parse/registry.py` | 响应解析器（每个接口一个） |
| `src/scout/analyze/ai.py` | AI 画像 |
| `src/scout/analyze/creator.py` | AI 作品评价 + 下一步计划 |
| `src/scout/web/static/index.html` | **整个前端**（单文件，含内联 JS，约 1300 行） |
| `src/scout/web/app.py` | HTTP 接口 |
| `src/scout/store/repo.py` | 所有 SQL 都在这 |
| `tests/test_frontend.py` | 前端健全性检查（node 语法检查等，**很重要**） |

---

## 8. 关键路径与凭据

| 项 | 位置 |
|---|---|
| 开发目录 | `D:\新建文件夹 (5)\douyin-scout` |
| 桌面数据 | 程序旁 `userdata\data\accounts\main\`（打包后是 exe 旁边） |
| 开发时数据 | `data\accounts\main\` |
| 打包产物 | `dist\douyin-scout.exe`（57.8 MB，**没进仓库**） |
| 服务器 | `139.224.200.6` / `douyin.baodaoxiaoyuan.cn`，详见 `docs/server.md` |
| SSH 密钥 | 本地 `~/.ssh/scout_ecs`（免密已配） |

---

## 9. 常用命令

```powershell
# 桌面版
.\.venv\Scripts\python.exe desktop\app.py

# 测试（199 项）
.\.venv\Scripts\python.exe -m pytest -q

# 网页版（开发调试）
.\.venv\Scripts\python.exe -m scout.cli web

# 本地助手（网页登录用）
.\.venv\Scripts\python.exe agent\agent.py

# 采集
.\.venv\Scripts\python.exe -m scout.cli --account main seed
.\.venv\Scripts\python.exe -m scout.cli --account main run

# 打包
desktop\打包.bat
```

---

## 10. 其他文档

| 文件 | 内容 |
|---|---|
| `docs/architecture.md` | 架构原则（为什么不实现签名等） |
| `docs/server.md` | 服务器完整信息 |
| `docs/runbook.md` | 运维手册（含账号隔离说明） |
| `docs/reference-projects.md` | 参考项目调研（**注意 LICENSE**） |
| `docs/visibility-report.md` | 可见性说明 |
