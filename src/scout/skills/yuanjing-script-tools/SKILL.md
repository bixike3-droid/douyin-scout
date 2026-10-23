---
name: yuanjing-script-tools
description: 在源镜会话中临时编写 Python 或使用 FFmpeg，处理文件、转换媒体、统计数据或生成可交付产物。
---

先用 workspace_info 了解实际工作目录、输入清单和运行环境。Python 中读取环境变量 SCOUT_INPUT_MANIFEST 指向的 JSON，它包含本会话完整附件与已展开素材的路径；SCOUT_WORKSPACE_DIR 是输出根目录，SCOUT_FFMPEG 是可用的 FFmpeg 可执行文件。

workspace_python 运行 Python 源码，workspace_ffmpeg 接收参数数组。两者通过 Codex 命令沙箱执行，输入原件只读，网络关闭；必要库和格式支持应由实际执行结果确认。执行失败时根据完整日志修正，不把缺少依赖说成用户文件损坏。

产物写到当前工作目录中名称明确的文件，例如 outputs/contact-sheet.jpg 或 outputs/material-index.csv。stdout/stderr 完整保存在 .runs/ 中，可用 workspace_read 分段读取；返回文本只是末尾预览。需要展示图像时用 workspace_view 检查实际内容，其他产物用 workspace_artifacts 核对名称与大小。

选择适合任务的批次和输出分辨率，保留后续继续处理的入口，不把一次请求的批次大小当作整个任务的上限。
