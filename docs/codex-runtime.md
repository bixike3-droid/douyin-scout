# Codex 执行引擎试用

源镜可以用独立的 `codex app-server` 进程执行普通对话，模型保持使用 DeepSeek。
2026-10-22 初次接入使用 Codex CLI 0.153.4；脚本、会话操作与技能验收使用官方 Python SDK 固定的 0.163.0 运行时，模型为 `deepseek-flash`。

## 在桌面中使用

1. 安装执行依赖：`.venv\Scripts\python.exe -m pip install -e ".[desktop,codex]"`。优先使用官方 SDK 附带的固定运行时，无须修改个人 Codex。
2. 启动源码桌面：`.venv\Scripts\python.exe desktop\app.py`。
3. 设置 → 模型与外观：模型选择 `deepseek-flash`，保存。
4. 在工作台拖入附件并发送任务；停止和继续任务沿用现有入口。

推理循环统一由 Codex 内核执行，界面上不再提供引擎切换。
已有打包程序需要重新构建后才包含此变更。
已更新打包脚本以包含运行时和产品技能；本轮尚未重新生成发行 exe。
也可以设置 `llm.codex_executable` 为指定原生可执行文件的绝对路径；Windows 脚本执行需要支持 MXC 的版本。
源码模式复用当前 Python 环境；打包版脚本执行需要本机 Python（可通过 `llm.python_executable` 指定）。

也可以在现有 `config/llm.local.yaml` 的 `llm` 段合并：

```yaml
model: deepseek-flash
```

密钥沿用源镜本地设置。开发验证可通过 `SCOUT_LLM__API_KEY` 环境变量临时传入。

## 边界与实现

- Rust 内核管理推理循环、流式事件和持久会话；Python 保留界面、采集、业务数据库和工具策略。
- 工具使用 app-server 的实验性 `dynamicTools` 接口直接回调到现有注册表；参数校验、成员权限、确认和审计继续生效。
- 普通对话一律由 Codex 内核执行；派单（谁接手）与固定协作流程在引擎分派之前完成，不再依赖具体内核。
- 图片、视频、压缩包先导入原件，再由执行内核调用完整索引、联系表总览、原图与指定视频帧工具。
- 测试统一使用 Flash。模型目录也声明 V4 Pro 的文本能力；图片工具可以通过独立 Flash 视觉调用回传观察结果。
- DeepSeek 使用 Responses API；不依赖服务端 `previous_response_id` 存储历史。图片工具当前沿用项目已有的 DeepSeek 视觉客户端。
- 每个账号的内核状态位于 `state/codex/`，配置与会话独立于个人 `~/.codex`。API Key 仅通过子进程环境变量传递。
- Python 与 FFmpeg 通过 `command/exec` 执行。Windows 显式启用 MXC，写入范围为当前会话工作目录，网络关闭，脚本子进程移除模型密钥。实际测试验证目录外写入失败；隔离机制不可用时返回错误。
- stdout/stderr 流式写入 `.runs/` 日志，工具只返回末尾预览；完整日志可分页读取，原始输出不在事件队列中重复堆积。
- 产物保存在 `workspaces/<conversation_id>/`，作为图片、视频或文件卡片挂到聊天记录；工作目录与会话互相隔离。
- 执行中输入文字并按 Enter 或“追加指令”，通过 `turn/steer` 送入当前轮；送达成功后清空输入，失败时保留。生成按钮仍用于停止。
- 已有 Codex 会话可在“会话”菜单另开方案或整理上下文。分支复用原件，复制会话和素材观察进度，后续观察独立更新；已有产物在分支中作为只读来源。
- 三个产品技能安装到账号独立的 `state/codex/skills/`，也可通过 `workspace_skills` 按需加载正文。个人技能目录不变。
- 动态工具变化后，空闲旧会话的下次任务会同步已保存的聊天和附件证据到新执行会话；旧内核日志保留。中断中的旧任务继续使用原执行记录。
- 当前接入只开放源镜工具，关闭原生 shell、原生看图和内核多代理功能。内核申请内置命令或文件写入时不会绕过源镜工具策略。
- 不设附件任务总工具数、总模型调用数、总时长或上传大小的产品上限。单次网络连接的无数据超时沿用模型配置，不代表任务只能运行这么久。
- 0024 迁移保存引擎会话映射、执行轮次及原始事件；已有工具执行记录在回传内核前保存。恢复时复用完成结果，执行中的副作用需要核对，不自动重做。
- 接口仍为试用状态；升级 Codex 后应重跑协议、恢复与文件验收。

## 真实验收

### 脚本、追加要求、分支与上下文整理

```powershell
.venv\Scripts\python.exe scripts/check_codex_workspace.py
```

固定使用 Flash，实际完成：加载脚本技能、生成四图联系表和 CSV、用视觉工具重新检查联系表、FFmpeg 生成并校验 1 秒 128×96 视频。
在脚本运行期间追加随机内容写入要求，模型实际生成对应文件；随后另开方案并正确回答前文文件名，原会话消息数保持不变；上下文整理正常完成。
报告位于 `tmp/codex-probe/workspace-acceptance/report.json`，五项检查全部通过。
本轮 452 项核心回归通过；追加指令、会话菜单、生成图片预览、附件拖放、任务恢复界面与桌面启动检查通过。

SDK 接入选择：复用 `openai-codex==0.163.0` 的固定运行时包和资源，保留当前直接 JSON-RPC 连接层，以便异步执行业务工具、并行接收追加要求和流式保存命令输出。

### 工具与跨进程会话

```powershell
.venv\Scripts\python.exe scripts/check_codex_runtime.py
```

实际启动 Rust 内核，由 Flash 调用工具获得随机校验码。退出内核后重新启动，在同一会话中再次准确回答该码。
报告：`tmp/codex-probe/live-report.json`，两项均通过。脚本始终指定 Flash，不更改本地已选模型。

### 主动停止与继续

```powershell
.venv\Scripts\python.exe scripts/check_codex_runtime.py --cancel-only `
  --output tmp/codex-probe/cancel-report.json
```

Flash 请求工具后，在工具等待期间主动取消任务，再通过保存的任务 ID 继续。
实际验证成功：保留同一 Rust 会话，安全重试未完成的只读工具，完成最终答复。
补测期间还遇到一次 DeepSeek SSE 空闲超时，已验证记录为失败并保留执行状态。

本地回归覆盖大帧协议消息、凭证隔离、参数校验、确认拒绝、重复调用、
副作用中断核对、已完成轮次恢复、失败脱敏、取消状态，以及桌面设置与启动。

### 用户提供的大压缩包

```powershell
.venv\Scripts\python.exe scripts/check_codex_runtime.py `
  --archive-report tmp/real-archive-workspace/workspace-report.json `
  --output tmp/codex-probe/archive-report.json
```

复用隔离数据中的原件与缩略图缓存，实际调用 Flash 完成全部视觉分析。结果：

| 项目 | 验收结果 |
|---|---:|
| 原始压缩包 | 1,457,114,513 字节 |
| 全部素材 | 73 |
| 图片 / 视频 | 66 / 7 |
| 联系表 | 7 批 |
| 总览覆盖 | 73/73 |
| 额外原图细看 | 3 |
| 额外视频细看 | 1 段，0 秒和 2 秒 |
| 失败 | 0 |

最终答复明确区分联系表覆盖、原图细看、视频抽帧和音轨范围。
私人素材、会话记录、截图与联网报告保留在忽略的本地目录，不进入版本库。

## 官方接口依据

- [OpenAI App Server](https://learn.chatgpt.com/docs/app-server)
- [DeepSeek Codex 接入](https://api-docs.deepseek.com/quick_start/agent_integrations/codex/)
- [DeepSeek Responses 兼容性](https://api-docs.deepseek.com/guides/responses_api/)
