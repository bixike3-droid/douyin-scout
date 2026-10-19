# 第三方组件与许可

本项目自身代码以 MIT 许可发布（见 [LICENSE](LICENSE)）。运行时/构建时依赖的第三方组件按其各自许可发布，请注意区分。

| 组件 | 版本 | 许可 | 说明 |
|---|---|---|---|
| PySide6 (Qt for Python) | 6.8.3 | LGPL-3.0 / 商业双许可 | 桌面界面与多媒体；动态链接使用，未修改 Qt 源码 |
| PySide6-Fluent-Widgets | 1.11.3 | **GPL-3.0** | 组件库（下拉框、开关、InfoBar、CommandBar、气泡提示等） |
| PySide6-Frameless-Window | 0.8.2 | GPL-3.0 | Fluent Widgets 的依赖 |
| Playwright (Python) + Chromium | 1.63.0 | Apache-2.0 | 用真实浏览器采集数据、渲染图表 |
| Typer / Click | 0.27.3 | MIT / BSD-3-Clause | 命令行入口 |
| Pydantic | 2.14.0 | MIT | 数据结构校验 |
| PyInstaller | 6.22.3 | GPL-2.0 with exception | 仅用于打包，产物不受其许可传染 |
| pytest | 9.1.1 | MIT | 测试 |

## 关于 GPL 依赖的实际影响

`PySide6-Fluent-Widgets` 是 GPL-3.0。因为本项目在**运行时导入**它，所以：

- **只使用/修改本项目源码**（不打包、不分发二进制）：按 MIT 条款即可。
- **分发打包产物**（例如发布的 `源镜.exe`、zip 安装包）：该产物属于“与 GPL 组件的组合作品”，需要按 GPL-3.0 提供相应源代码（本仓库即为其源代码）。
- 若希望产物也能保持宽松许可，可选做法：
  1. 将项目整体改为 GPL-3.0；
  2. 移除 Fluent Widgets，改用纯 Qt 控件（`src/scout/desktop/controls.py` 已把该依赖隔离在一层，替换成本可控）；
  3. 向组件作者购买商业授权。

如果后续要去掉这层限制，优先考虑第 2 条：`controls.py` 里的 `ComboBox / switch / notify / state_tip / progress_ring / command_bar / bar_action / flyout_show / install_fluent_tooltips / smooth_scroll_area` 是全部接入点。
