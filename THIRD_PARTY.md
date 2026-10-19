# 第三方组件与许可

本项目整体以 **GNU General Public License v3.0** 发布（见 [LICENSE](LICENSE)），
因为运行时分发依赖中的 PySide6-Fluent-Widgets 采用 GPL-3.0。

源镜 · 传播工作台
Copyright (C) 2026 bixike3-droid and 源镜 contributors

| 组件 | 版本 | 许可 | 说明 |
|---|---|---|---|
| PySide6 (Qt for Python) | 6.8.3 | LGPL-3.0 / 商业双许可 | 桌面界面与多媒体；动态链接使用，未修改 Qt 源码 |
| PySide6-Fluent-Widgets | 1.11.3 | GPL-3.0 | 组件库（下拉框、开关、InfoBar、CommandBar、气泡提示等） |
| PySide6-Frameless-Window | 0.8.2 | GPL-3.0 | Fluent Widgets 的依赖 |
| Playwright (Python) + Chromium | 1.63.0 | Apache-2.0 | 用真实浏览器采集数据、渲染图表 |
| Typer / Click | 0.27.3 | MIT / BSD-3-Clause | 命令行入口 |
| Pydantic | 2.14.0 | MIT | 数据结构校验 |
| PyInstaller | 6.22.3 | GPL-2.0 with exception | 仅用于打包，产物不受其许可传染 |
| pytest | 9.1.1 | MIT | 测试 |

## GPL-3.0 义务对照

- **分发即触发**：只自己用不触发；对外发 exe / zip 时必须提供完整对应源代码（本仓库即源码，
  含 `douyin-scout.spec`、`desktop/打包.bat`、`brand/` 源文件，可重建产物）。
- **不得附加限制**：不能对已分发的产物加“禁止反制/禁止再分发/仅限个人使用”等条款。
- **保留声明**：保留版权与许可文本；修改过的第三方文件需注明。
- **允许收费**：可以卖，但不能阻止收到的人免费再分发。
- **专利**：贡献者授予专利许可，主动对下游发专利诉讼会失去授权。

## LGPL 组件（PySide6 / Qt）

Qt 采用 LGPL-3.0：动态链接使用不要求开源你的代码，但需要
1) 随产物附上 LGPL-3.0 文本与 Qt 版权声明；
2) 让用户能够替换 Qt 库（建议用 PyInstaller 的 onedir 模式，而非 onefile）。

## 商标与品牌

仓库内 `brand/` 下的名称与图形标志是项目方商标，**不在 GPL 授权范围内**。
基于本项目二次开发或再分发时，请更换程序名称与图标，避免造成来源混淆。
