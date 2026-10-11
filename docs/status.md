# 项目当前状态

> 这份文件的作用：**上下文压缩或换会话之后，看这一份就能接着干。**
> 最后更新：2026-10-11

## 一句话

抖音互动数据采集 + AI 受众分析。当前形态：**桌面应用**（原生窗口，双击即用）。

## 现在的架构

```
桌面程序（用户自己电脑）
├── 采集        Playwright，用户自己的 IP 和环境 → 无风控
├── 登录        用户扫码，cookie 存本机 → 无隐私问题
├── AI 分析     用户自己的 DeepSeek Key
├── 数据展示    PyWebView 原生窗口（内部是 WebView2）
└── 数据        用户本机的 SQLite（userdata/data/accounts/main/）
```

**服务器（139.224.200.6 / douyin.baodaoxiaoyuan.cn）现在只是历史遗留** ——
它上面还跑着 scout-web + nginx，但按新架构它只需要放"产品介绍 + 下载链接"。
**未改造。**

## 关键路径

| 用途 | 路径 |
|---|---|
| 开发目录 | `D:\新建文件夹 (5)\douyin-scout` |
| 桌面入口 | `desktop\app.py`（开发）/ `desktop\启动.bat`（用户） |
| 打包脚本 | `desktop\打包.bat`（**写了但没跑过**） |
| 前端 | `src\scout\web\static\index.html`（单文件，含内联 JS） |
| 数据库 | 用户目录下 `userdata\data\accounts\main\db\scout.sqlite3` |
| 配置 | `config\default.yaml`（随程序分发） |
| 密钥 | `config\llm.local.yaml`（**用户自己的，绝不打包**） |

## 已完成的界面

| 界面 | 状态 |
|---|---|
| 概览（产品定位 + 系统状态 + 六步引导） | ✅ |
| 采集（登录面板 + 助手探测 + 一键采集 + SSE 实时日志） | ✅ |
| AI Key 配置（引导填写 / 打码显示 / 更换 + 当场验证） | ✅ |
| AI 画像（三个按钮 + 结果卡片） | ✅ |
| 点赞人档案 / 作品 / 存储 / 日志 / 报告 | ✅ |
| 桌面原生窗口 | ✅ 已验证能打开 |

## 未完成

| 项 | 说明 |
|---|---|
| **打包成 exe** | 脚本在 `desktop\打包.bat`，**没跑过**。PyInstaller 对 Playwright/PyWebView 常见坑 |
| **桌面窗口里的完整流程** | 只验证了"窗口打开 + 服务响应"，**没在窗口里点过登录/采集/AI** |
| 服务器改造 | 按新架构应改成落地页（介绍 + 下载），**没做** |
| 首次启动向导 | 概览页有六步引导，但没有"第一次打开"的弹窗 |

## 两个独立的"登录"概念（容易搞混）

1. **抖音登录** —— 二选一：
   - `scout.cli login --tier a`（本地持久 profile，能扫码）
   - 本地助手 `agent\agent.py`（网页触发，同样在用户机器上）
2. **AI Key** —— 用户自己的 DeepSeek Key，在概览页填

## 踩过的关键坑（别再踩）

| 坑 | 教训 |
|---|---|
| 解析器递归扫全响应 | 把别人的百万赞视频挂到 98 粉丝的号名下。**只读 `aweme_list` + 按作者过滤** |
| 游标键名 `cursor` vs `max_cursor` | 对不上 = 只采第一页，**从结果上完全看不出来** |
| `min_cursor` = `max_cursor` | 作品列表接口第二页返回 0 条。**只给 max_cursor** |
| `browser.channel: msedge` | 服务器没装 Edge。**服务器/打包必须留空用自带 Chromium** |
| 打包带 `config;config` | **会把开发者的 API Key 分发出去**。只带 `default.yaml` |
| 页面显示个人账号 | 公开站点上不能有预置的个人账号。**页头已去掉账号标签** |
| 前端 JS 被 PowerShell 吃掉反引号 | 整个脚本解析失败，页面**能打开但功能全废**。已加 node 语法检查测试 |
| `launch_persistent_context` 不接受 `storage_state` | 只能用 `new_context(storage_state=...)` |
| 抖音对全新匿名上下文返回验证码页 | 无头/有头/改 UA 都一样。**登录必须在用户自己环境完成** |
| 登录凭据全是 HttpOnly | 网页 JS 读不到 → 书签小工具方案不可行 |

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q      # 199 项
```

## 常用命令

```powershell
# 桌面版
.\.venv\Scripts\python.exe desktop\app.py

# 网页版（开发调试）
.\.venv\Scripts\python.exe -m scout.cli web

# 本地助手（登录用）
.\.venv\Scripts\python.exe agent\agent.py

# 采集（命令行）
.\.venv\Scripts\python.exe -m scout.cli --account main seed
.\.venv\Scripts\python.exe -m scout.cli --account main run
```

## 服务器信息

见 `docs/server.md`。要点：SSH 密钥在本地 `~/.ssh/scout_ecs`（免密已配好）。
