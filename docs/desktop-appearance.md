# 桌面外观

界面提供浅色、深色、跟随系统三种外观模式。可使用窗口右上角的外观按钮快速切换明暗，也可在「设置 → 模型与外观 → 外观」选择（跟随系统会随 Windows 主题自动切换）。选择会保存在当前工作空间的 `desktop-ui.ini`，重启后恢复。

外观覆盖窗口工具栏、七个导航板块、对话与思考面板、团队任务卡、热点、方案、可视化容器、数据表格、表单和弹窗。现有板块、信号、业务操作和数据格式继续使用。

设计基准（2026-10-16）：全部界面按 Apple 风格实现。系统蓝 `#007AFF` / 深色 `#0A84FF`；窗口与侧栏使用中性系统灰；圆角收敛为四档（控件 6 / 小卡 10 / 容器 12 / 胶囊 999）；正文 13px、标题 22–26px；卡片统一轻投影（`soft_shadow`）替代重描边；表格行分隔线 + 柔和选中；菜单项圆角高亮；滚动条 8px 悬停加深；深浅切换 150ms 过渡。审计清单 60 项中已落地令牌收敛、去满屏描边、侧栏与选中态柔和化、跟随系统、过渡等；空状态组件、滚动条 overlay 隐藏、菜单材质等列入后续增量。

切换时保留当前会话、未发送消息与未保存表单，不会调用模型或发起采集。长任务标题在有限宽度内省略显示，悬停可查看全文。

`src/scout/desktop/appearance.py` 定义两套颜色与共享样式；`theme.py` 将样式应用到原生 Qt 调色板、图标和成员徽标。按钮、文字、状态与背景使用同一组颜色。

窗口外壳（2026-10-16 修复）：标题栏三键为标准「最小化 — / 最大化还原 □ / 关闭 ×」（右侧、悬停高亮）；主窗口使用 Windows 11 系统圆角，最大化时自动切直角；窗口边缘 6px 为拖拽缩放带（缩放光标，仅真实窗口环境）；最大化 / 还原为瞬时切换，过渡动画由系统最小化 / 还原承担。

## 预览

原生页面预览使用现有数据库的独立副本，迁移、偏好设置和截图均写入系统临时目录：

```powershell
.venv\Scripts\python.exe scripts\render_native_preview.py --data-dir desktop\userdata --output "$env:TEMP\scout-ui-light" --appearance light
.venv\Scripts\python.exe scripts\render_native_preview.py --data-dir desktop\userdata --output "$env:TEMP\scout-ui-dark" --appearance dark
```

加 `--conversation-id <编号>` 可展示指定的历史会话和关联方案。离屏预览关闭动效，不获取热点或调用模型。
