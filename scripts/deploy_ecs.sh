#!/usr/bin/env bash
# deploy_ecs.sh —— 在阿里云 ECS（Alibaba Cloud Linux 4 / RHEL 9 系）上从零跑通
#
# 用法（在服务器上，代码已经 clone 到当前目录）：
#     bash scripts/deploy_ecs.sh
#
# 设计原则：
#   1. **不因为一个无关紧要的包就整个中断。** 字体装不上不影响采集。
#   2. **用"真的启动一次 Chromium"来判断依赖够不够**，而不是猜包名。
#      Playwright 官方支持列表里没有 Alibaba Cloud Linux，
#      包名和标准 RHEL 有出入，靠猜会一直翻车。
#   3. 出问题时给出能直接执行的排查命令，而不是只说"失败了"。

set -uo pipefail    # 刻意不加 -e：每一步自己判断成败，不要中途静默退出

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

VENV_DIR="${SCOUT_VENV:-$HOME/scout-venv}"
ACCOUNT="${SCOUT_ACCOUNT:-main}"

# ── 国内镜像 ────────────────────────────────────────────────
# 在阿里云 ECS 上直连 pypi.org / playwright 的 CDN 会非常慢，
# 慢到看起来像卡死（尤其配上 --quiet 时完全没有任何进度提示，更难判断）。
# 所以默认就走国内镜像，并允许用环境变量覆盖。
PIP_INDEX="${SCOUT_PIP_INDEX:-https://mirrors.aliyun.com/pypi/simple/}"
PIP_HOST="${SCOUT_PIP_HOST:-mirrors.aliyun.com}"
# Playwright 的浏览器本体也走镜像
export PLAYWRIGHT_DOWNLOAD_HOST="${PLAYWRIGHT_DOWNLOAD_HOST:-https://npmmirror.com/mirrors/playwright}"

FAILED=0

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '  \033[1;32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[1;33m!\033[0m %s\n' "$*"; }
bad()  { printf '  \033[1;31m✗\033[0m %s\n' "$*"; FAILED=1; }
note() { printf '    \033[2m%s\033[0m\n' "$*"; }

# ── 0. 环境预检 ──────────────────────────────────────────────
say "0/5 环境预检"

ARCH="$(uname -m)"
if [ "$ARCH" != "x86_64" ]; then
  warn "架构是 $ARCH，不是 x86_64。Playwright 的 Chromium 在非 x86_64 上可能没有预编译包。"
fi

PY="$(command -v python3 || true)"
[ -n "$PY" ] || { bad "找不到 python3"; exit 1; }
PYVER="$($PY -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if ! $PY -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)'; then
  bad "需要 Python 3.11+，当前 $PYVER"; exit 1
fi
ok "架构 $ARCH ｜ Python $PYVER ｜ 目录 $PROJECT_DIR"

MEM_MB="$(free -m | awk '/^Mem:/{print $2}')"
SWAP_MB="$(free -m | awk '/^Swap:/{print $2}')"
ok "内存 ${MEM_MB}MB ｜ swap ${SWAP_MB}MB"
[ "$MEM_MB" -ge 1800 ] || warn "内存偏小，跑 Chromium 会很紧"
if [ "$SWAP_MB" -lt 1024 ]; then
  warn "swap 不足 1GB，建议加一个（Chromium 偶发内存尖峰会 OOM）："
  note "sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo swapfile 见下"
  note "sudo mkswap /swapfile && sudo swapon /swapfile"
fi

# ── 1. 系统依赖 ──────────────────────────────────────────────
say "1/5 装 Chromium 系统依赖（dnf）"

if ! command -v dnf >/dev/null 2>&1; then
  bad "没有 dnf。这个脚本只覆盖 RHEL 系（Alibaba Cloud Linux / CentOS / Anolis）"
  exit 1
fi

# Chromium 运行时真正需要的动态库。
# 这些一般各个发行版都有，只是包名可能不同。
REQUIRED=(
  nss nspr atk at-spi2-atk at-spi2-core cups-libs
  libdrm libXcomposite libXdamage libXrandr
  libgbm pango alsa-lib libxkbcommon
)
# 有更好、没有也不影响采集的。
# **字体属于这一类** —— 我们无头取数据，不渲染中文，字体只影响截图好看不好看。
OPTIONAL=(
  libXScrnSaver libxkbcommon-x11
  liberation-fonts dejavu-sans-fonts
  wqy-zenhei-fonts google-noto-sans-cjk-fonts
)

# 先整体试一次（快，且 dnf 会给出一份"哪些找不到"的清单）。
# 整体失败再逐个试，把装不上的挑出来单独报告 —— 而不是整个脚本挂掉。
try_install() {
  local label="$1"; shift
  local -a pkgs=("$@")
  [ "${#pkgs[@]}" -eq 0 ] && return 0

  if sudo dnf install -y "${pkgs[@]}" >/tmp/dnf_scout.log 2>&1; then
    ok "$label：${#pkgs[@]} 个包全部就绪"
    return 0
  fi

  local good=0 bad_pkgs=()
  for p in "${pkgs[@]}"; do
    if sudo dnf install -y "$p" >/dev/null 2>&1; then
      good=$((good + 1))
    else
      bad_pkgs+=("$p")
    fi
  done
  ok "$label：装好 $good 个"
  if [ "${#bad_pkgs[@]}" -gt 0 ]; then
    warn "$label 里这个发行版没有的：${bad_pkgs[*]}"
  fi
  return "${#bad_pkgs[@]}"
}

try_install "必需库" "${REQUIRED[@]}"
REQ_MISSING=$?
try_install "可选库（字体等）" "${OPTIONAL[@]}" || true

if [ "$REQ_MISSING" -gt 0 ]; then
  warn "有 $REQ_MISSING 个必需库没装上 —— 继续往下走，"
  warn "最后会用「真的启动一次 Chromium」来判定到底行不行。"
  note "如果最后启动失败，把这条命令的输出发我："
  note "ldd \$(ls -d ~/.cache/ms-playwright/chromium-*/chrome-linux/chrome 2>/dev/null | head -1) | grep 'not found'"
fi

# ── 2. Python 环境 ──────────────────────────────────────────
say "2/5 建虚拟环境并装 Python 依赖"
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR" || { bad "建 venv 失败"; exit 1; }
  ok "已建虚拟环境 $VENV_DIR"
else
  ok "复用已有虚拟环境 $VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate" || { bad "激活 venv 失败"; exit 1; }

# 配好镜像，后面所有 pip 操作都走它
mkdir -p "$HOME/.pip"
cat > "$HOME/.pip/pip.conf" <<PIPCONF
[global]
index-url = $PIP_INDEX
trusted-host = $PIP_HOST
timeout = 60
PIPCONF
ok "pip 镜像已设为 $PIP_INDEX"

note "升级 pip（进度可见，慢的话是在下载，别急着中断）…"
python -m pip install --upgrade pip 2>&1 | tail -2 || warn "pip 升级失败（不致命，继续）"

note "装 Python 依赖：playwright / typer / rich / PyYAML / fastapi / uvicorn"
note "（playwright 的 wheel 约 40MB，走阿里云镜像一般几十秒）"
if python -m pip install \
      "playwright>=1.47" "typer>=0.12" "rich>=13.7" "PyYAML>=6.0" \
      "fastapi>=0.115" "uvicorn>=0.30" 2>&1 | tail -5; then
  ok "Python 依赖装好了"
else
  bad "Python 依赖装失败。可以手动重试："
  note "source $VENV_DIR/bin/activate"
  note "pip install -i $PIP_INDEX playwright typer rich PyYAML fastapi uvicorn"
  exit 1
fi

# ── 3. 浏览器本体 + **真的启动一次** ─────────────────────────
say "3/5 下载 Chromium 并验证能启动"
note "（浏览器本体约 150MB，国内可能较慢。卡住可以先 Ctrl+C，"
note "  然后设镜像重试：export PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright）"

if ! playwright install chromium; then
  bad "下载 Chromium 失败。试试国内镜像后重跑本脚本："
  note "export PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright"
  note "playwright install chromium"
  exit 1
fi
ok "Chromium 已下载"

# **这是唯一可靠的依赖验证方式。**
# 不去猜包名装没装上，直接让它启动 —— 缺库会在这里报出来。
note "实际启动一次 Chromium 验证系统依赖…"
if python - <<'PY' 2>/tmp/chromium_launch.err
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("about:blank")
    browser.close()
print("launched")
PY
then
  ok "Chromium 能正常启动 —— 系统依赖没问题"
else
  bad "Chromium 启动失败。错误原文："
  sed 's/^/      /' /tmp/chromium_launch.err | tail -15
  echo ""
  warn "排查缺哪个库："
  note "ldd \$(ls -d ~/.cache/ms-playwright/chromium-*/chrome-linux/chrome 2>/dev/null | head -1) | grep 'not found'"
  note "把上面输出里所有 'not found' 的库名发我，我告诉你装哪个包。"
  exit 1
fi

# ── 4. 服务器侧配置 ──────────────────────────────────────────
say "4/5 写入服务器侧配置（config/local.yaml）"

# 注意：不能只看文件存在就跳过 —— 本地的 local.yaml 容易被一起带上来，
# 那个文件里没有这两项，跳过会导致服务器静默地用错配置。
if [ -f config/local.yaml ] && grep -qE '^[[:space:]]+use_storage_state:[[:space:]]*true' config/local.yaml; then
  ok "config/local.yaml 里已有 use_storage_state: true"
else
  if [ -f config/local.yaml ]; then
    cp config/local.yaml "config/local.yaml.bak.$(date +%Y%m%d%H%M%S)"
    warn "config/local.yaml 存在但没有 use_storage_state: true，已备份并追加"
  fi
  cat >> config/local.yaml <<'YAML'

# ── 服务器侧（由 deploy_ecs.sh 追加）──
# 服务器上没有屏幕没法扫码，用本地导出的登录态文件建立会话。
tiers:
  a:
    use_storage_state: true
    headless: true
YAML
  ok "已写入 config/local.yaml"
  note "如果这个文件里原本就有 tiers 段，现在会有重复，请检查后合并。"
fi

# ── 5. 自检 ─────────────────────────────────────────────────
say "5/5 自检"
STATE="$PROJECT_DIR/data/accounts/$ACCOUNT/state/tier_a_storage.json"
if [ -f "$STATE" ]; then
  ok "找到登录态文件：$STATE"
  python -m scout.cli --account "$ACCOUNT" account check || warn "账号核对未通过（登录态可能过期）"
else
  warn "还没有登录态文件："
  note "$STATE"
  echo ""
  note "本地电脑上执行（扫码登录并导出）："
  note "  .\\.venv\\Scripts\\python.exe -m scout.cli --account $ACCOUNT login --tier a"
  note "然后传上来："
  note "  scp data/accounts/$ACCOUNT/state/tier_a_storage.json admin@<IP>:~/"
  note "  mkdir -p $PROJECT_DIR/data/accounts/$ACCOUNT/state"
  note "  mv ~/tier_a_storage.json $STATE"
fi

# ── 收尾 ────────────────────────────────────────────────────
say "完成"
if [ "$FAILED" -ne 0 ]; then
  warn "上面有步骤报错了，先处理它们再往下走。"
fi
cat <<EOF

下一步：
  1. 激活环境      source $VENV_DIR/bin/activate
  2. 上传登录态    （见上面提示）
  3. 验证身份      python -m scout.cli --account $ACCOUNT account check
  4. 跑第一轮      python -m scout.cli --account $ACCOUNT seed
                   python -m scout.cli --account $ACCOUNT run
EOF
