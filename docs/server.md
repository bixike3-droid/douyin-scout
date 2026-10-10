# 服务器与部署信息

> 这份文件是给**你和我**一起用的速查表。
> **里面刻意不写任何真实密码** —— 理由见文末。

## 主机

| 项 | 值 |
|---|---|
| 公网 IP | `139.224.200.6` |
| 主机名 | `iZuf6fca923n6uf18c0muxZ` |
| 登录用户 | `admin`（uid=1000，有免密 sudo） |
| 系统 | Alibaba Cloud Linux 4（RHEL 9 系，用 `dnf`） |
| 架构 | x86_64 |
| 配置 | 2 核 / 1.8 GB 内存 / 6 GB swap / 40 GB 磁盘 |

## 域名

| 项 | 值 |
|---|---|
| **线上地址** | **http://douyin.baodaoxiaoyuan.cn**（**无需密码，公开访问**） |
| 主域名 | `baodaoxiaoyuan.cn`（**已备案**） |
| 解析 | A 记录 → `139.224.200.6`（已配置） |

### ⚠️ 站点状态（2026-10-11 凌晨）

**这是一个公开站点，服务器上刻意没有任何个人数据：**

| 项 | 状态 |
|---|---|
| 登录态 | **已删除** —— 默认未登录 |
| 业务数据 | 全清（users / works / like_edges / llm_results 都是 0） |
| 归档 | 空 |
| 页面显示 | 不展示任何个人账号信息 |
| Nginx 密码 | **已移除**（公开访问） |

**设计原则：公开站点上不能出现任何预先存在的个人账号。**
登录态 = 个人身份 + 可执行操作的能力，两者都不该默认存在。

### 未决问题：功能真空

现在站点干净但**采集走不通**，因为：
- 网页「登录抖音」按钮**点不通** —— 抖音对全新匿名上下文返回验证码页
  （实测：无头 / 有头 / 改 UA 三种方式结果一致，title 都是「验证码中间页」）
- 服务器没法自己登录 → 没有登录态 → 采集一步也走不了

三个选项（**待定，尚未实施**）：

| 方案 | 做法 | 代价 |
|---|---|---|
| **A 纯演示站** | 本地采好数据，脱敏后放上去 | 数据是静态的 |
| **B 操作者后台**（推荐） | 网页公开可看，但采集/登录要口令 | 需要加一点代码 |
| C 访客各自登录 | 要攻破抖音验证码页 | **不建议**，那正是架构明确不碰的逆向 |

## 服务（systemd）


| 服务 | 作用 | 状态 |
|---|---|---|
| `scout-web` | 网页面板，绑 `127.0.0.1:8787` | `systemctl status scout-web` |
| `nginx` | 反代 80 → 8787，带 Basic 认证 | `systemctl status nginx` |

**两个都设了开机自启。**

```bash
sudo systemctl restart scout-web    # 改了代码后重启
sudo systemctl reload nginx         # 改了 nginx 配置后重载
```

## 服务器侧配置的关键项

`config/local.yaml`（不进版本库，服务器上单独维护）：

```yaml
browser:
  channel: ""            # ← 必须留空！本地用 msedge，服务器上没装 Edge
tiers:
  a:
    use_storage_state: true   # 用导出的登录态，不依赖扫码
    headless: true            # 必须无头，有头窗口在无桌面环境会挂住
```

**`channel` 这一项踩过坑**：留成 `msedge` 会报
`Chromium distribution 'msedge' is not found at /opt/microsoft/msedge/msedge`。

## Nginx 配置要点

`/etc/nginx/conf.d/scout.conf`：

```nginx
proxy_buffering off;      # ⚠️ 必须关！否则「实时采集进度」会卡住不动
proxy_cache off;
proxy_read_timeout 3600s; # 采集要跑很久
```

**`proxy_buffering off` 是 SSE 的命门**：Nginx 默认会把响应攒起来再发，
而实时进度是长连接流式推送，一攒就变成"进度条不动"。

## 项目安装方式

服务器上是**可编辑安装**（因为项目是 src 布局）：

```bash
cd ~/douyin-scout && source ~/scout-venv/bin/activate
pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
```

不装这一句会报 `No module named 'scout'`。

## 常用命令

```bash
# 进项目、激活环境
cd ~/douyin-scout && source ~/scout-venv/bin/activate

# 核对登录态
python -m scout.cli --account main account check

# Web 服务（systemd）
sudo systemctl status scout-web
sudo systemctl restart scout-web
sudo journalctl -u scout-web -n 50 --no-pager

# Nginx
sudo nginx -t
sudo systemctl reload nginx
sudo tail -30 /var/log/nginx/error.log


## 服务器上的路径

| 用途 | 路径 |
|---|---|
| 代码 | `/home/admin/douyin-scout` |
| Python 虚拟环境 | `/home/admin/scout-venv` |
| Playwright 浏览器 | `/home/admin/.cache/ms-playwright` |
| 账号数据 | `/home/admin/douyin-scout/data/accounts/main` |
| 登录态文件 | `/home/admin/douyin-scout/data/accounts/main/state/tier_a_storage.json` |
| 服务器侧配置 | `/home/admin/douyin-scout/config/local.yaml` |
| DeepSeek 配置 | `/home/admin/douyin-scout/config/llm.local.yaml` |

## Git 与密钥

| 项 | 值 |
|---|---|
| 仓库 | `git@github-scout:bixike3-droid/douyin-scout.git`（私有） |
| SSH 别名 | `github-scout`（定义在服务器 `~/.ssh/config`） |
| Deploy Key | 服务器 `~/.ssh/scout_deploy` |
| Deploy Key 指纹 | `SHA256:3olFWhUdeeYHlOjdWPFnK93tTbQiflww7lMw1TBZxbs` |
| Deploy Key 公钥 | `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFx/vgzNwgrGftayvTZqc27irXtr5kR1KA3LQU2VuZD4 scout-deploy` |

**这把是 GitHub 的 Deploy Key（只读），不是服务器登录凭据。**

## 常用命令

```bash
# 进项目、激活环境
cd ~/douyin-scout && source ~/scout-venv/bin/activate

# 核对登录态
python -m scout.cli --account main account check

# Web 服务（手动跑，前台）
python -m scout.cli web --host 127.0.0.1 --port 8787

# Web 服务（systemd）
sudo systemctl status scout-web
sudo systemctl restart scout-web
sudo journalctl -u scout-web -n 50 --no-pager

# Nginx
sudo nginx -t
sudo systemctl reload nginx
sudo tail -30 /var/log/nginx/error.log
```

## 更新流程

```bash
# 服务器
cd ~/douyin-scout && git pull
sudo systemctl restart scout-web
```

`data/` 和 `config/local.yaml`、`config/llm.local.yaml` 都在 `.gitignore` 里，
**`git pull` 永远不会覆盖数据和配置。**
（但 `pip install -e .` 不用重跑，除非依赖变了。）

## 凭据

| 凭据 | 在哪 | 说明 |
|---|---|---|
| 网页访问密码 | **没有记录在任何文件里** | Nginx Basic Auth，用户名 `admin`。忘了就在服务器上重设：`sudo htpasswd -c /etc/nginx/.htpasswd admin` |
| 服务器 SSH 密码 | **没有记录在任何文件里** | 用密钥登录即可（见下）。要拿回密码：阿里云控制台 → ECS → 实例 → 更多 → 密码/密钥 → 重置实例密码 |
| 服务器 SSH 密钥 | 本地 `C:\Users\32227\.ssh\scout_ecs` | **已授权，可免密登录** |
| GitHub Deploy Key | 服务器 `~/.ssh/scout_deploy` | 只读，用于 `git pull` |
| DeepSeek API Key | 服务器 `config/llm.local.yaml` | 不进版本库 |

### 免密登录

```powershell
ssh -i "$env:USERPROFILE\.ssh\scout_ecs" admin@139.224.200.6
scp -i "$env:USERPROFILE\.ssh\scout_ecs" 文件 admin@139.224.200.6:~/
```


---

## 为什么这份文件里没有密码

1. **密码从没出现在对话里** —— 你在终端输密码时不回显，粘贴出来的输出不含它
2. **写进文件很危险** —— 项目是 git 仓库，就算加进 `.gitignore`，
   一旦哪天误提交，密码就永久留在 git 历史里了
3. **根本不需要** —— 已经配了 SSH 密钥（`~/.ssh/scout_ecs`），
   之后所有操作都可以用密钥，不需要密码

### 如果你确实需要密码

阿里云控制台 → **ECS → 实例 → 更多 → 密码/密钥 → 重置实例密码**
（需要重启实例，1-2 分钟生效）

### 密钥登录（推荐）

本地私钥：`C:\Users\32227\.ssh\scout_ecs`

配置好之后：

```powershell
scp -i "$env:USERPROFILE\.ssh\scout_ecs" 文件 admin@139.224.200.6:~/
ssh -i "$env:USERPROFILE\.ssh\scout_ecs" admin@139.224.200.6
```
