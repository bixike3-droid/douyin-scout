# douyin-scout

抖音互动数据采集与分析框架。**本地单机自用**，登录态与匿名态严格分离。

> 本仓库只做「把你手动能看的操作自动化」，不实现抖音的请求签名，也不绕过任何技术保护措施。
> 所有请求都由真实浏览器用页面自身的 JS 环境发出，程序只在旁边归档响应。

## 设计取向

长期工程，**稳定优先于速度**。三条不可动摇的原则：

1. **原始响应永不丢** —— 每个响应落盘归档（`data/raw/YYYY-MM-DD/`）。抖音改版是必然的，归档是唯一的后悔药，解析器可以随时回放重解。
2. **采集与解析解耦** —— 改版只改 `parse/`，`collect/` 不动。
3. **配额优先于进度** —— 触到配额立刻停，绝不为「数据完整性」超额。

## 两档权限模型

| 档位 | 身份 | 职责 | 说明 |
|---|---|---|---|
| A | 登录态（**小号**） | 只解析点赞人列表，拿 `sec_uid` | 请求数压到极限，绝不点进主页 |
| B | 匿名态（无登录） | 全部公开数据：资料、作品列表 | 承担主要请求量，无账号可封 |

档 A 请求量目标：一天个位数到几十个。

## 快速开始

```powershell
# 0. 先确认核心逻辑没问题（不需要联网、不需要装任何第三方库）
python scripts\smoke.py

# 1. 建虚拟环境并安装依赖（需要联网）
pwsh -File scripts/setup.ps1

# 2. 环境自检：依赖、配置、数据库、登录态锁
.\.venv\Scripts\python.exe -m scout.cli doctor

# 3. 初始化（建目录 + 建库 + 迁移）
.\.venv\Scripts\python.exe -m scout.cli init

# 4. 扫码登录档 A（用小号）
.\.venv\Scripts\python.exe -m scout.cli login --tier a

# 5. 勘探「消息-赞」真正的地址（会自动写入 local.yaml）
.\.venv\Scripts\python.exe -m scout.cli discover --tier a

# 6. 拉一轮点赞人名单，看是否触底
.\.venv\Scripts\python.exe -m scout.cli run --kind fetch_notice
.\.venv\Scripts\python.exe -m scout.cli coverage

# 7. 打开本地面板
.\.venv\Scripts\python.exe -m scout.cli web
```

装依赖时如果外网慢，换国内镜像：

```powershell
.\.venv\Scripts\python.exe -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
.\.venv\Scripts\python.exe -m playwright install chromium
```

## 命令速查

| 命令 | 用途 |
|---|---|
| `scout doctor` | 环境自检（装不上依赖、跑不动时先看这个） |
| `scout init` | 初始化目录与数据库 |
| `scout config` | 显示生效配置及来源 |
| `scout login` | 手动扫码登录（档 A） |
| `scout discover` | **依次勘探候选地址，找出「消息-赞」真正的地址** |
| `scout probe` | **可见性勘探**，产出报告与原始归档 |
| `scout coverage` | **名单完整性证据**：有没有触底、共覆盖多少不同的人 |
| `scout seed` | 补齐待办任务 |
| `scout run` | 跑一轮采集 |
| `scout status` | 一屏看全：数据量 / 配额 / 熔断 / 任务 |
| `scout users` / `scout tasks` / `scout raw` | 查数据 |
| `scout replay <raw_id>` | **对归档回放重解**（改版后主力工具） |
| `scout report` / `scout export` | 画像报告 / CSV 导出 |
| `scout circuit status\|reset\|open` | 熔断器操作 |
| `scout web` | 本地面板 |

`scripts/smoke.py` 是不依赖第三方库的自检脚本，覆盖迁移、幂等 upsert、归档去重、
配额、熔断、解析、分析、导出共 24 项检查。改完核心代码先跑它。


## 目录

```
src/scout/
  paths.py      路径解析
  config.py     配置加载（default.yaml < local.yaml < 环境变量）
  db/           SQLite 连接、迁移、schema
  store/        仓储层 + 原始响应归档
  guard/        配额、节流、熔断
  session/      双档浏览器会话 + 响应镜像
  collect/      采集器
  parse/        解析层（容错深度提取 + 可注册的精确解析器）
  schedule/     任务队列引擎
  analyze/      画像分析
  web/          本地网页 UI
  cli.py        命令行入口
```

## 文档

- `docs/architecture.md` —— 架构与数据流
- `docs/runbook.md` —— 运维手册：封控处置、渐进放量、恢复流程
- `docs/reference-projects.md` —— GitHub 参照项目调研与借鉴清单
- `docs/visibility-report.md` —— 可见性勘探报告（**M1 交付物，待填**）

## 当前状态

| 里程碑 | 状态 |
|---|---|
| M0 框架（骨架 / 存储 / 护栏 / 会话 / 采集 / 调度 / CLI / 面板） | ✅ 完成 |
| M1 可见性勘探 | ✅ **完成**，接口已实测校准 |
| M2 档 A 取点赞人 | ✅ **跑通**，已入库真实数据 |
| M3 档 B 取公开数据 | ✅ 采集器就绪，待放量 |
| M4 小量跑通并观察 | ⬜ 下一步 |
| M5 分析层 | ✅ 已有雏形（`scout report`） |
| M6 放量与运维 | ⬜ runbook 已备好 |

### 已确认的接口（实测校准）

```
GET https://www.douyin.com/aweme/v1/web/notice/?notice_group=960&count=10
  notice_list     → 空数组，别读
  notice_list_v2  → 数据在这里
    [i].digg.from_user[]  → 点赞人（带 sec_uid / 昵称 / 抖音号 / 粉丝数 / 签名 / 认证）
    [i].digg.aweme        → 被赞的作品
    [i].digg.merge_count  → 该条聚合了多少人
    [i].digg.has_digg_list→ true 表示名单不全，需要点开「赞过的人」
```

**关键收益**：点赞人资料在通知接口里就带全了，**不用挨个访问主页**，省掉一大半档 B 配额。

### 验证记录

- 单元测试 **84 项全过**（含 11 项专门盯通知解析器）
- 免依赖自检 24 项全过
- 浏览器端到端（Edge 154）跑通
- **从归档回放入库 42 个用户 / 12 个作品 / 42 条点赞边**，全程零新增请求
- 本地面板全部 API + SSE 实时流跑通

### 已修复的真实缺陷（都有测试兜底）

| 缺陷 | 后果 | 修复 |
|---|---|---|
| 读 `notice_list` 而不是 `notice_list_v2` | 得到 0 条 | 精确解析器 + 测试 |
| 把 `digg.aweme.author` 当点赞人 | 把视频作者当成点赞人 | 改读 `digg.from_user` |
| 非通知接口也抽点赞边 | 表情包接口抽出 36 条假点赞人 | `detect_kind` 收紧 |
| 静态资源算进配额 | 一次勘探烧掉 340 点配额 | 只按数据接口计 |
| 静态资源正文都读进内存 | 浏览器严重卡顿 | 读 body 前就过滤 |
| `executescript` 隐式提交 | 数据库建不起来 | 迁移改 `BEGIN/COMMIT` 内联 |
| 档位非惰性启动 | `probe --tier b` 弹出档 A 窗口并占锁 | 按需创建 |
| `duration_ms` 恒为 0 | 耗时遥测失效 | 读完 body 再取计时 |




## 合规边界

仅供你本人分析自己账号的互动数据。数据不出本机、不公开、不转售、不提供给第三方。
大规模采集他人个人信息并构建画像涉及《个人信息保护法》，请勿把本工具做成对外服务。
