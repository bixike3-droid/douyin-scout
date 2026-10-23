"""Versioned JSON-RPC transport for the native Codex app-server.

No shell wrapping, personal Codex configuration, or task-wide execution budget.
The host keeps policy decisions in its existing tool registry.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess


class CodexError(RuntimeError):
    pass


def executable(configured="codex") -> str:
    if configured in ("codex", "codex.exe"):
        try:
            from codex_cli_bin import bundled_codex_path
            return str(bundled_codex_path())
        except ImportError:
            pass
    candidate = shutil.which(configured) or configured
    path = Path(candidate).expanduser()
    if path.is_file() and path.suffix.lower() not in (".cmd", ".bat", ".ps1"):
        return str(path.resolve())
    if configured not in ("codex", "codex.exe"):
        raise CodexError("llm.codex_executable 必须指向可执行的 Codex 原生程序")
    if os.name == "nt":
        # npm's shim is not an executable. Resolve the native optional package,
        # including npm versions which nest it under @openai/codex/node_modules.
        arch = "aarch64" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"
        package = "codex-win32-arm64" if arch == "aarch64" else "codex-win32-x64"
        triple = arch + "-pc-windows-msvc"
        roots = [path.parent / "node_modules" / "@openai"]
        if os.environ.get("APPDATA"):
            roots.append(Path(os.environ["APPDATA"]) / "npm" / "node_modules" / "@openai")
        for root in roots:
            for vendor in (root / "codex" / "node_modules" / "@openai" / package / "vendor",
                           root / package / "vendor", root / "codex" / "vendor"):
                for folder in ("bin", "codex"):
                    binary = vendor / triple / folder / "codex.exe"
                    if binary.is_file():
                        return str(binary.resolve())
    raise CodexError("找不到 Codex 原生程序，请安装 Codex CLI 或设置 llm.codex_executable 的绝对路径")


def model_catalog():
    """DeepSeek's documented Codex metadata, with the host's own instructions."""
    models = []
    for index, model in enumerate(("deepseek-flash", "deepseek-v4-pro")):
        models.append({
            "slug": model, "display_name": model, "description": "DeepSeek via Responses API",
            "default_reasoning_level": "high",
            "supported_reasoning_levels": [{"effort": e, "description": e} for e in ("low", "high", "max")],
            "shell_type": "shell_command", "visibility": "list", "supported_in_api": True,
            "priority": index, "upgrade": None,
            "base_instructions": "你是源镜工作台的执行助手。使用工作台提供的工具完成用户任务，保留证据，准确说明完成范围。",
            "supports_reasoning_summaries": True, "default_reasoning_summary": "none",
            "support_verbosity": True, "default_verbosity": "low", "apply_patch_tool_type": "freeform",
            "truncation_policy": {"mode": "tokens", "limit": 10000},
            "supports_parallel_tool_calls": True, "experimental_supported_tools": [],
            "context_window": 1048576, "max_context_window": 1048576,
            "effective_context_window_percent": 95, "auto_compact_token_limit": None,
            "input_modalities": ["text", "image"] if model == "deepseek-flash" else ["text"],
            "supports_image_detail_original": model == "deepseek-flash", "prefer_websockets": False,
            "use_responses_lite": False, "tool_mode": None,
        })
    return {"models": models}


def prepare_runtime(paths, cfg):
    if cfg.provider != "deepseek" or cfg.model not in ("deepseek-flash", "deepseek-v4-pro"):
        raise CodexError("Codex 试验引擎当前支持 DeepSeek 官方模型 deepseek-flash / deepseek-v4-pro")
    if not cfg.api_key:
        raise CodexError("请先配置 DeepSeek API Key")
    home = paths.state_dir / "codex"
    work = home / "workspace"
    work.mkdir(parents=True, exist_ok=True)
    from .skills import install
    install(home)
    catalog = home / "models.json"
    catalog.write_text(json.dumps(model_catalog(), ensure_ascii=False, indent=2), encoding="utf-8")
    # JSON quoted strings are also valid TOML strings, including Windows paths.
    quote = lambda value: json.dumps(str(value), ensure_ascii=False)
    config = (
        f'model = {quote(cfg.model)}\nmodel_provider = "deepseek"\n'
        'forced_login_method = "api"\nweb_search = "disabled"\n'
        f'model_reasoning_effort = {quote(cfg.reasoning_effort)}\n'
        f'model_catalog_json = {quote(catalog)}\n'
        'project_doc_max_bytes = 0\n'
        + ('[windows]\nsandbox = "mxc"\n' if os.name == "nt" else '') +
        '[features]\nshell_tool = false\nview_image = false\nmulti_agent = false\ncode_mode = false\ncode_mode_host = false\n'
        '[model_providers.deepseek]\nname = "DeepSeek"\n'
        f'base_url = {quote(cfg.base_url.rstrip("/"))}\n'
        'wire_api = "responses"\nenv_key = "DEEPSEEK_API_KEY"\n'
        'requires_openai_auth = false\nsupports_websockets = false\n'
        f'stream_idle_timeout_ms = {int(cfg.timeout_s) * 1000}\n'
        'request_max_retries = 0\nstream_max_retries = 0\n'
    )
    (home / "config.toml").write_text(config, encoding="utf-8")
    # Set CODEX_HOME only for the child, never mutate the host's environment.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CODEX_", "OPENAI_", "SCOUT_"))}
    env.update(CODEX_HOME=str(home), DEEPSEEK_API_KEY=cfg.api_key)
    return home, work, env


class AppServer:
    def __init__(self, command, *, env=None, cwd=None, secret=""):
        self.command, self.env, self.cwd, self.secret = command, env, cwd, secret
        self.events = asyncio.Queue()
        self.pending = {}
        self.serial = 0
        self.process = None
        self.tasks = []
        self.stderr = ""
        self.closed = False
        self.listeners = []

    def clean(self, value):
        text = str(value)
        return text.replace(self.secret, "[密钥]") if self.secret else text

    async def __aenter__(self):
        try:
            options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            self.process = await asyncio.create_subprocess_exec(
                *self.command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, cwd=self.cwd, env=self.env, **options)
            self.tasks = [asyncio.create_task(self._read()), asyncio.create_task(self._errors())]
            self.info = await self.request("initialize", {
                "clientInfo": {"name": "yuanjing", "title": "源镜", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True}})
            await self.notify("initialized", {})
            return self
        except BaseException:
            await self.close()
            raise

    async def __aexit__(self, *unused):
        await self.close()

    async def write(self, message):
        if not self.process or self.process.returncode is not None:
            raise CodexError("Codex 内核已经退出：" + self.stderr[-1200:])
        self.process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode())
        await self.process.stdin.drain()

    async def request(self, method, params, *, timeout=30):
        self.serial += 1
        key = self.serial
        future = asyncio.get_running_loop().create_future()
        self.pending[key] = future
        try:
            await self.write({"id": key, "method": method, "params": params})
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(key, None)

    async def notify(self, method, params):
        await self.write({"method": method, "params": params})

    async def respond(self, key, result):
        await self.write({"id": key, "result": result})

    async def _read(self):
        # read chunks instead of readline's 64 KiB ceiling: tools may return
        # large text or image content in a single JSON-RPC frame.
        buffer = bytearray()
        try:
            while chunk := await self.process.stdout.read(65536):
                buffer.extend(chunk)
                while (end := buffer.find(b"\n")) >= 0:
                    raw = bytes(buffer[:end])
                    del buffer[:end + 1]
                    if not raw.strip():
                        continue
                    data = json.loads(raw)
                    if "id" in data and "method" not in data:
                        future = self.pending.get(data["id"])
                        if future is not None and not future.done():
                            if "error" in data:
                                future.set_exception(CodexError(self.clean(data["error"])))
                            else:
                                future.set_result(data.get("result", {}))
                    else:
                        for listener in tuple(self.listeners):
                            listener(data)
                        if data.get("method") == "command/exec/outputDelta" and self.listeners:
                            # The command listener streams these bytes to disk.
                            # Do not accumulate a second copy while its tool awaits.
                            continue
                        await self.events.put(data)
            if buffer.strip():
                raise CodexError("Codex 协议消息未完整写入")
            raise CodexError("Codex 内核连接已关闭")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = CodexError(self.clean(exc))
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(error)
            if not self.closed:
                await self.events.put(error)

    async def _errors(self):
        while chunk := await self.process.stderr.read(4096):
            self.stderr = (self.stderr + self.clean(chunk.decode("utf-8", errors="replace")))[-16000:]

    async def close(self):
        self.closed = True
        if self.process:
            if self.process.stdin:
                self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    self.process.terminate()
                # Process.wait() also waits for inherited stdout/stderr handles.
                # A surviving helper can hold them open after the server exits.
                # Close our pipe transports before waiting for forced teardown.
                self.process._transport.close()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self.process.wait(), 3)
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.process:
            # Proactor pipes can remain open after wait() if a native child
            # inherited a handle. Explicitly close all asyncio pipe transports.
            self.process._transport.close()
            await asyncio.sleep(0)
        for future in self.pending.values():
            if not future.done():
                future.cancel()


def server(paths, cfg):
    home, work, env = prepare_runtime(paths, cfg)
    return AppServer([executable(cfg.codex_executable), "app-server", "--listen", "stdio://"],
                     env=env, cwd=work, secret=cfg.api_key)
