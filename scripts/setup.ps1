# 环境搭建。用法：
#   pwsh -File scripts/setup.ps1
#   pwsh -File scripts/setup.ps1 -SkipBrowser     # 不下载 Chromium（约 150MB）
#   pwsh -File scripts/setup.ps1 -Python "C:\path\to\python.exe"

param(
    [string]$Python = "",
    [switch]$SkipBrowser,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
Write-Host "项目根：$root" -ForegroundColor Cyan

# ── 找 Python ────────────────────────────────────────────────
if (-not $Python) {
    foreach ($cand in @("python", "py", "python3")) {
        $cmd = Get-Command $cand -ErrorAction SilentlyContinue
        if ($cmd) { $Python = $cmd.Source; break }
    }
}
if (-not $Python) {
    Write-Host "找不到 Python。请安装 Python 3.11+ 或显式传 -Python <路径>。" -ForegroundColor Red
    exit 1
}
Write-Host "使用 Python：$Python"
& $Python -c "import sys; assert sys.version_info >= (3,11), sys.version; print('版本 OK', sys.version.split()[0])"

# ── 建虚拟环境 ───────────────────────────────────────────────
$venv = Join-Path $root ".venv"
$py = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "创建虚拟环境 .venv ..." -ForegroundColor Cyan
    & $Python -m venv $venv
} else {
    Write-Host "复用已有虚拟环境 .venv" -ForegroundColor DarkGray
}

Write-Host "安装依赖（这一步需要联网）..." -ForegroundColor Cyan
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -e ".[dev]"

if (-not $SkipBrowser) {
    Write-Host "下载 Chromium（约 150MB，只做一次）..." -ForegroundColor Cyan
    & $py -m playwright install chromium
} else {
    Write-Host "已跳过 Chromium 下载：浏览器相关命令暂不可用，其余功能正常。" -ForegroundColor Yellow
}

if (-not $SkipTests) {
    Write-Host "`n跑测试..." -ForegroundColor Cyan
    & $py -m pytest -q
}

# ── 初始化数据目录 ───────────────────────────────────────────
Write-Host "`n初始化数据目录与数据库..." -ForegroundColor Cyan
& $py -m scout.cli init

Write-Host "`n完成。常用命令：" -ForegroundColor Green
Write-Host "  .\.venv\Scripts\python.exe -m scout.cli probe --help"
Write-Host "  .\.venv\Scripts\python.exe -m scout.cli web"
