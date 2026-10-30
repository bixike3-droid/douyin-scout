# 第三方组件与许可

本项目整体以 **GNU General Public License v3.0** 发布（见 [LICENSE](LICENSE)）。
早期版本因 PySide6-Fluent-Widgets（GPL-3.0）而选择 GPL；该依赖已随 Qt 界面一起移除，
当前运行时分发依赖中没有强制 GPL 的库，是否改用更宽松的许可由维护者另行决定，
在此之前仍按 GPL-3.0 发布。

源镜 · 传播工作台
Copyright (C) 2026 bixike3-droid and 源镜 contributors

| 组件 | 版本 | 许可 | 说明 |
|---|---|---|---|
| pywebview | 6.2.1 | BSD-3-Clause | WebView2 窗口与本地文件桥 |
| pythonnet / .NET | 3.2.1 | MIT | pywebview 驱动 WebView2 所需 |
| FastAPI | 0.143.0 | MIT | 本地回环 API |
| Uvicorn | 0.54.0 | BSD-3-Clause | 本地回环服务 |
| Playwright (Python) + Chromium | 1.63.0 | Apache-2.0 | 用真实浏览器采集数据、渲染图表与品牌位图 |
| Typer / Click | 0.27.3 | MIT / BSD-3-Clause | 命令行入口 |
| Pydantic | 2.14.0 | MIT | 数据结构校验 |
| PyInstaller | 6.22.3 | GPL-2.0 with exception | 仅用于打包，产物不受其许可传染 |
| pytest | 9.1.1 | MIT | 测试 |
| Pillow | 13.0.0 | MIT-CMU | 附件图片缩放及格式转换 |
| pypdf | 6.21.1 | BSD-3-Clause | PDF 文本提取 |
| pypdfium2 / PDFium | 5.14.0 | BSD-3-Clause / Apache-2.0 及依赖许可 | 扫描 PDF 页面渲染，随分发包保留依赖许可 |
| imageio-ffmpeg | 0.6.0 | BSD-2-Clause | 随包提供视频解码程序 |
| FFmpeg（Windows wheel 内置构建） | 以分发包版本为准 | GPL-3.0-or-later | 本地视频封面与抽帧；打包时保留对应许可文件及来源信息 |

## GPL-3.0 义务对照

- **分发即触发**：只自己用不触发；对外发 exe / zip 时必须提供完整对应源代码（本仓库即源码，
  含 `desktop-html/`、`scripts/build_windows_release.py`、`brand/` 源文件，可重建产物）。
- **不得附加限制**：不能对已分发的产物加“禁止反制/禁止再分发/仅限个人使用”等条款。
- **保留声明**：保留版权与许可文本；修改过的第三方文件需注明。
- **允许收费**：可以卖，但不能阻止收到的人免费再分发。
- **专利**：贡献者授予专利许可，主动对下游发专利诉讼会失去授权。

## WebView2 运行时

窗口使用系统自带的 Microsoft Edge WebView2 运行时（Windows 11 内置，旧系统需
[单独安装](https://developer.microsoft.com/microsoft-edge/webview2/)），不随包分发，
因此不引入额外许可义务。

## 商标与品牌

仓库内 `brand/` 下的名称与图形标志是项目方商标，**不在 GPL 授权范围内**。
基于本项目二次开发或再分发时，请更换程序名称与图标，避免造成来源混淆。

## Codex execution runtime

The optional `openai-codex==0.163.0` dependency includes the pinned
`openai-codex-cli-bin==0.163.0` runtime, distributed under Apache-2.0.
Upstream: https://github.com/openai/codex . Product skill sources are maintained
in `src/scout/skills/`; they are separate from personal Codex skills.
