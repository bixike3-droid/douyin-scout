# 桌面外观

界面提供浅色、深色两种外观。可使用窗口右上角的外观按钮切换，也可在「设置 → 模型与外观 → 外观」选择。选择会保存在当前工作空间的 `desktop-ui.ini`，重启后恢复。

外观覆盖窗口工具栏、七个导航板块、对话与思考面板、团队任务卡、热点、方案、可视化容器、数据表格、表单和弹窗。现有板块、信号、业务操作和数据格式继续使用。

切换时保留当前会话、未发送消息与未保存表单，不会调用模型或发起采集。长任务标题在有限宽度内省略显示，悬停可查看全文。

`src/scout/desktop/appearance.py` 定义两套颜色与共享样式；`theme.py` 将样式应用到原生 Qt 调色板、图标和成员徽标。按钮、文字、状态与背景使用同一组颜色。

## 预览

原生页面预览使用现有数据库的独立副本，迁移、偏好设置和截图均写入系统临时目录：

```powershell
.venv\Scripts\python.exe scripts\render_native_preview.py --data-dir desktop\userdata --output "$env:TEMP\scout-ui-light" --appearance light
.venv\Scripts\python.exe scripts\render_native_preview.py --data-dir desktop\userdata --output "$env:TEMP\scout-ui-dark" --appearance dark
```

加 `--conversation-id <编号>` 可展示指定的历史会话和关联方案。离屏预览关闭动效，不获取热点或调用模型。
