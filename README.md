# 源镜

**单机桌面 AI 传播工具**：把你手动才能看的抖音数据自动采回本机，交给 AI 分析，
在传播工作台里变成有依据、可复盘的传播决策。

- 采集、分析、工作台在一个程序里，双击即用（PySide6 / Qt，Windows）
- 所有数据保存在本机 SQLite；只有分析内容会发送到你自己的 DeepSeek 服务
- 不实现抖音请求签名、不绕过任何技术保护措施：所有请求由真实浏览器用页面自身的 JS 发出，程序只在旁边归档响应

## 快速开始

```powershell
# 首次：建环境并安装依赖（需要联网）
pwsh -File scripts/setup.ps1

# 跑桌面版
.venv\Scripts\python.exe desktop\app.py
```

也可以双击 `desktop\启动.bat`（日常启动）或 `desktop\开发预览.bat`（开发时改代码自动重载）。

## 测试与自检

```powershell
.venv\Scripts\python.exe -m pytest -q                      # 测试套件
.venv\Scripts\python.exe scripts\smoke.py                  # 免依赖核心自检
.venv\Scripts\python.exe scripts\check_desktop_startup.py  # 桌面启动冒烟（离屏）
```

## 文档（只看这四份）

| 文档 | 内容 |
|---|---|
| [docs/product.md](docs/product.md) | 产品定义（草案）：给谁用、做什么、不做什么 |
| [docs/status.md](docs/status.md) | 当前状态：验证过的 / 没验证的 / 下一步 |
| [docs/architecture.md](docs/architecture.md) | 技术架构：采集、归档、解析、护栏 |
| [docs/runbook.md](docs/runbook.md) | 运维手册：配额、熔断、出事时的操作流程 |

历史文档（旧方向、研究笔记、验收记录）在 [docs/archive/](docs/archive/)，不作为当前依据。

## 开发约定

- 验证脚本的产物（冒烟目录、预览、截图）一律输出到系统临时目录，不写入仓库。
- 界面代码不写 SQL；后台任务使用独立数据库连接，不跨线程共享上下文。


