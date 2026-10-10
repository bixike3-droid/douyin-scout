#!/usr/bin/env bash
# deploy_ecs.sh —— 在阿里云 ECS（Alibaba Cloud Linux 4 / RHEL 9 系）上从零跑通
#
# 用法（在服务器上，代码已经解压到当前目录）：
#     bash scripts/deploy_ecs.sh
#
# 它会做五件事：
#   1. 装 Chromium 的系统依赖（dnf）
#   2. 建 Python venv 并装依赖
#   3. 下载 Playwright 的 Chromium
#   4. 关掉 use_storage_state 之外可能踩的配置坑
#   5. 跑自检
#
# **不会**做的事：不会碰你的登录态文件，不会跑采集。
# 登录态要你自己从本地传上来（见文末说明）。

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

VENV_DIR="${SCOUT_VENV:-$HOME/scout-venv}"
ACCOUNT="${SCOUT_ACCOUNT:-main}"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[注意] %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m[失败] %s\033[0m\n' "$*" >&2; exit 1; }

# ── 0. 先确认环境符合预期 ────────────────────────────────────
say "0/5 环境预检"
ARCH="$(uname -m)"
[ "$ARCH" = "x86_64" ] || warn "架构是 $ARCH，不是 x86_64。Playwright 的 Chromium 在非 x86_64 上可能没有预编译包，请留意。"
PY="$(command -v python3 || true)"
[ -n "$PY" ] || die "找不到 python3"
PYVER="$($PY -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
$PY -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' \
  || die "需要 Python 3.11+，当前是 $PYVER"
echo "  架构 $ARCH ｜ Python $PYVER ｜ 项目目录 $PROJECT_DIR"

MEM_MB="$(free -m | awk '/^Mem:/{print $2}')"
[ "$MEM_MB" -ge 1800 ] || warn "内存只有 ${MEM_MB}MB，跑 Chromium 会很紧，建议加 swap"
SWAP_MB="$(free -m | awk '/^Swap:/{print $2}')"
[ "$SWAP_MB" -ge 1024 ] || warn "swap 只有 ${SWAP_MB}MB。建议：sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile"
echo "  内存 ${MEM_MB}MB ｜ swap ${SWAP_MB}MB"

# ── 1. Chromium 的系统依赖 ──────────────────────────────────
# 这一步最容易出问题：Playwright 官方支持列表里**没有** Alibaba Cloud Linux，
# 它自带的 install-deps 可能不认这个发行版。所以这里手动装。
say "1/5 装 Chromium 系统依赖（dnf）"
if command -v dnf >/dev/null 2>&1; then
  PKGS=(
    nss nspr atk at-spi2-atk at-spi2-core cups-libs
    libdrm libXcomposite libXdamage libXrandr libXScrnSaver
    libgbm pango alsa-lib libxkbcommon libxkbcommon-x11
    liberation-fonts
  )
  # 中文字体装不上不影响采集（我们是无头取数据，不渲染中文），所以不阻断
  sudo dnf install -y "${PKGS[@]}" \
    || die "dnf 装依赖失败。把上面的包名逐个试，找出哪个不存在。"
  sudo dnf install -y wqy-zenhei-fonts 2>/dev/null \
    || warn "中文字体没装上（不影响采集，只影响截图里的中文显示）"
else
  die "没有 dnf。这个脚本只覆盖 RHEL 系（Alibaba Cloud Linux / CentOS / Anolis）"
fi

# ── 2. Python 环境 ──────────────────────────────────────────
say "2/5 建虚拟环境并装 Python 依赖"
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet \
  "playwright>=1.47" "typer>=0.12" "rich>=13.7" "PyYAML>=6.0" \
  "fastapi>=0.115" "uvicorn>=0.30"
echo "  已装：$(python -c 'import playwright; print("playwright", playwright.__version__ if hasattr(playwright,"__version__") else "")' 2>/dev/null || echo playwright)"

# ── 3. 浏览器本体 ───────────────────────────────────────────
say "3/5 下载 Chromium（约 150MB，首次会比较慢）"
playwright install chromium || die "下载 Chromium 失败。检查网络，或设 PLAYWRIGHT_DOWNLOAD_HOST 走镜像。"

# ── 4. 配置：打开无头服务器开关 ──────────────────────────────
say "4/5 写入服务器侧配置（config/local.yaml）"

# 检查当前配置里开关到底开没开。
# 不能只看文件存不存在 —— 本地的 local.yaml 容易被一起打包带上来，
# 那个文件里没有这两项，而"文件存在就跳过"会让服务器静默地用错配置。
need_write=1
if [ -f config/local.yaml ]; then
  if grep -qE '^\s+use_storage_state:\s*true' config/local.yaml 2>/dev/null; then
    echo "  ✓ config/local.yaml 里已有 use_storage_state: true"
    need_write=0
  else
    warn "config/local.yaml 存在，但里面**没有** use_storage_state: true"
    warn "这多半是从本地一起打包带过来的。现在追加服务器需要的那几行。"
    cp config/local.yaml "config/local.yaml.bak.$(date +%Y%m%d%H%M%S)"
    cat >> config/local.yaml <<'YAML'

# ── 服务器侧（由 deploy_ecs.sh 追加）──
tiers:
  a:
    use_storage_state: true
    headless: true
YAML
    warn "已追加，原文件备份为 config/local.yaml.bak.*"
    warn "如果 local.yaml 里原本就有 tiers 段，这个追加会重复。请检查后合并。"
    need_write=0
  fi
fi

if [ "$need_write" = "1" ]; then
  cat > config/local.yaml <<'YAML'
# 服务器侧配置（不进版本库）
#
# use_storage_state: 服务器上没有屏幕没法扫码，
# 用本地导出的登录态文件建立会话。
tiers:
  a:
    use_storage_state: true
    headless: true
YAML
  echo "  已写入 config/local.yaml"
fi

# ── 5. 自检 ─────────────────────────────────────────────────
say "5/5 自检"
STATE="$PROJECT_DIR/data/accounts/$ACCOUNT/state/tier_a_storage.json"
if [ -f "$STATE" ]; then
  echo "  ✓ 找到登录态文件：$STATE"
  python -m scout.cli --account "$ACCOUNT" doctor || true
else
  warn "还没有登录态文件：$STATE"
  echo "  本地电脑上执行："
  echo "      .\\.venv\\Scripts\\python.exe -m scout.cli --account $ACCOUNT login --tier a"
  echo "  然后把 data/accounts/$ACCOUNT/state/tier_a_storage.json 传上来："
  echo "      scp tier_a_storage.json admin@<服务器IP>:~/douyin-scout/data/accounts/$ACCOUNT/state/"
  echo "  传完再跑一次本脚本，或直接："
  echo "      python -m scout.cli --account $ACCOUNT account check"
fi

say "完成"
cat <<'EOF'
下一步：
  1. 上传登录态（见上面提示）
  2. 验证身份    python -m scout.cli --account main account check
  3. 跑第一轮    python -m scout.cli --account main seed
                 python -m scout.cli --account main run

记得先激活环境：source ~/scout-venv/bin/activate
EOF
