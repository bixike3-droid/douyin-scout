# 运维手册

这个项目的成败不在于写得快，在于**能不能连续跑半年不出事**。
这份手册是出事时的操作流程，不要临时想办法。

---

## 一、先搞清楚：什么在保护你，什么没在保护你

三样机制，作用完全不同，别混为一谈：

| 机制 | 作用 | 默认 | 说明 |
|---|---|---|---|
| **节流** | 随机间隔，打散"固定频率"这个最明显的机器特征 | ✅ 开 | `guard/throttle.py`，跟量级无关 |
| **熔断** | 连续空返回/错误就停，**防止把被降级后的空数据洗进分析** | ✅ 开 | `guard/circuit.py`，跟量级无关 |
| **配额** | 每日"动作数"总量上限 | ⬜ **不限** | 可选的，默认只计数不拦截 |

### 关于配额：默认不限，因为日常根本用不上

**配额记的是"动作数"**：一次页面导航算 1 个，展开一条通知再加 1 个。
**不记页面自己发了多少请求** —— 你打开一次抖音网页，页面自己就会发一百多个 XHR，
那是站点的正常行为，不是你的消耗。

日常采集一天几个到几十个动作。这个量级下设上限**没有任何安全收益**，
只会挡住你自己的正常操作（实测被挡过一次：库里才 14 条数据，却提示"配额已用尽"）。

**什么时候才该设**：数据量大起来之后，比如你有几千个点赞人、要逐个访问主页：

```yaml
# config/local.yaml
tiers:
  b:
    daily_request_quota: 300
```

设了之后观察几天：空返回率有没有上升、有没有触发熔断。没异常再往上调。

**加量阶梯（只有设了上限才需要）**：100 → 观察 7 天 → 300 → 观察 7 天 → 600。

**档 A 建议永远不设**：它一天就几个动作，设了纯属自找麻烦。

### 每日检查（1 分钟）

```powershell
.\.venv\Scripts\python.exe -m scout.cli status
```

三个必看的数字：

- `请求（24h）` 的 **空返回率**：> 10% 说明有问题，先停下来看
- `熔断状态`：有 `open` 就别再跑了 ← **这个比配额重要得多**
- `任务` 的 `failed`：集中失败说明接口变了

---

## 一·补、点赞人名单的完整性

**已确认的数据源：网页端「通知」页 → 能看到哪些人赞过某条视频。**

### 先判断是哪种形态（决定要不要配交互动作）

| 形态 | 表现 | 需要配什么 |
|---|---|---|
| **A 扁平流** | 每条通知是一条"XXX 赞了你的作品《YYY》"，一路滚下去 | 什么都不用配，滚动就够 |
| **B 按作品聚合** | 一条通知是"XXX 等 N 人赞了《YYY》"，**点进去**才看到完整名单 | 要配 `notice_item_selector` + 展开动作 |

**形态 B 才是"能拿到完整名单"的形态**——因为聚合条目里默认只显示前几个头像，
必须点开才展开全部。

### 拿到名单（四步）

```powershell
# 1. 找出「通知」页真正的地址（会依次勘探候选并写入 local.yaml）
.\.venv\Scripts\python.exe -m scout.cli discover --tier a

# 2.（仅形态 B）试着点开一条通知，看能不能触发点赞人列表接口
#    先用 --actions 试跑，看动作有没有点中、有没有新响应出来
.\.venv\Scripts\python.exe -m scout.cli probe --tier a --url "<通知页地址>" --scroll 2 --actions notice_expand

# 3. 拉一轮，采集器会滚到底（形态 B 还会逐条展开）
.\.venv\Scripts\python.exe -m scout.cli run --kind fetch_notice

# 4. 看完整性结论
.\.venv\Scripts\python.exe -m scout.cli coverage
```

### 形态 B（已实测确认，2026-10-10 校准）

**好消息：大部分通知根本不用点开。** 接口直接把点赞人名单给你了。

#### 接口事实

```
GET https://www.douyin.com/aweme/v1/web/notice/?notice_group=960&count=10&...
```

```jsonc
{
  "notice_list":    [],          // ← 空的！读它就什么都拿不到
  "notice_list_v2": [            // ← 数据在这里
    {
      "nid_str": "...", "type": 41,        // 41 = 点赞通知
      "aweme_id": "7689477790995846377",
      "digg": {
        "aweme":      { ... },             // 被赞的作品完整对象
        "from_user":  [                    // ← 点赞人在这里
          { "sec_uid": "MS4wLjAB...", "uid": "...", "nickname": "培德娄",
            "unique_id": "82979114749",    // 抖音号
            "follower_count": 61,          // ← 画像数据直接就有
            "signature": "...", "custom_verify": "..." }
        ],
        "merge_count": 22,                 // 这条通知聚合了多少人
        "has_digg_list": true              // true = from_user 只给了一部分
      }
    }
  ],
  "has_more": 0, "max_time": ..., "min_time": ...
}
```

#### 三个必须记住的坑

| 坑 | 后果 |
|---|---|
| 读 `notice_list` | 它是**空数组**，会得到 0 条。必须读 `notice_list_v2` |
| 把 `digg.aweme.author` 当点赞人 | 那是**视频作者（你自己）**。点赞人在 `digg.from_user` |
| 以为必须点开每条通知 | 不用。`merge_count == from_user 长度` 时名单**本来就是完整的** |

#### 只有 `has_digg_list = true` 的才需要点开 —— 而要点的是那个箭头

实测确认：`merge_count=22` 的那条，接口**只给 7 个预览头像**，剩下 15 个要点开才给。

**关键细节（截图确认）**：要点的是条目右侧那个 **`›` 箭头按钮**，不是条目本身。

```
JJ
等22人赞了你的作品                    ← 锚点文案
[头像][头像][头像][头像]  (›)          ← 红圈那个箭头，点它
09-26
```

**它是个图标、没有文字**，所以：

| 做法 | 结果 |
|---|---|
| `click_text "查看全部"` | ❌ 找不到 |
| `click_pattern "等\d+人赞了..."` | ❌ 那是点条目，不是点箭头 |
| **`click_anchor_button`** | ✅ 按几何位置找：锚点文案所在行里，最靠右的可点元素 |

`click_anchor_button` 不依赖任何类名 —— 抖音改样式也能用。配置里已经设好了：

```yaml
interactions:
  notice_click:
    - action: click_anchor_button
      anchor: "人赞了你的作品"
      candidates: 'button,[role="button"],svg,[class*="arrow"],...'
```

#### 验证箭头点击能不能命中

```powershell
# 打开面板 + 试一次箭头点击，看有没有触发新接口
.\.venv\Scripts\python.exe -m scout.cli notice

# 自动方式不灵就人工介入（浏览器交给你，程序只负责记录）
.\.venv\Scripts\python.exe -m scout.cli notice --manual
```

看输出的「发现的数据接口」表：出现**带点赞人数的新接口**就是命中了。

#### 日常操作（比你想象的简单）

```powershell
# 1. 登录档 A（小号），一次即可
.\.venv\Scripts\python.exe -m scout.cli login --tier a

# 2. 拉一轮
.\.venv\Scripts\python.exe -m scout.cli run --kind fetch_notice

# 3. 看结果
.\.venv\Scripts\python.exe -m scout.cli coverage
.\.venv\Scripts\python.exe -m scout.cli users -n 30
```

#### 省配额的关键：不用挨个访问主页

`from_user` 已经带了 `sec_uid / nickname / unique_id / follower_count / signature / 认证`。
所以**画像数据在第一步就拿到了**，档 B 只需要给真正要深挖（作品列表）的人跑。

#### 改版后怎么修

解析器在 `src/scout/parse/registry.py` 的 `_parse_notice`，有 11 项测试盯着它
（`tests/test_notice_parser.py`）。改完用归档回放验证，**不用重新采集**：

```powershell
# 单条：看解析结果
.\.venv\Scripts\python.exe -m scout.cli replay 413

# 批量回填历史数据
.\.venv\Scripts\python.exe -m scout.cli replay --all --match "/aweme/v1/web/notice/" --persist
```

### 探索新的接口（比如「赞过的人」的完整名单）

```powershell
.\.venv\Scripts\python.exe -m scout.cli notice --dump
```

会打开面板、滚动列表、尝试点开聚合条目，最后打印一张**「发现的数据接口」**表——
有数据的接口永远排在最前面。新接口就藏在那张表里。

### `coverage` 的三种结论怎么读

| 结论 | 含义 | 怎么办 |
|---|---|---|
| **最近一次已触底，名单可视为完整** | 页面提示了"没有更多了"，或连续多轮没有新内容 | 正常，按放量表逐步提高频率 |
| **最后一次没有触底（原因）** | 中途停了 | 看停止原因：轮数上限就调大 `notice_max_rounds`；登录墙就重登；连续无新响应可能就是真到底了 |
| **从未触底过** | 采集轮次不够或一直被中断 | 多跑几轮再看 |

### 采集器怎么判断"到底了"

1. 页面出现 `notice_end_texts` 里的字样（默认「没有更多了」等）→ 判定触底
2. 连续 `notice_idle_rounds` 轮（默认 3）没有任何新增响应 → 也判定触底
3. 被重定向到 passport / login / verifycenter → 判定被挡，立即停

每轮都记一行 `notice_runs`，所以「完整性」是**有据可查的**，不是感觉。

### 一直不触底怎么办

- 页面根本不做滚动加载 → 改成点击"加载更多"；把按钮文案/选择器写进 `interactions`
- 名单就是**有上限**的（平台只保留最近 N 条）→ 那"完整"的定义就是"这 N 条"，
  把 `notice_max_rounds` 调大覆盖它，然后看 `edges_seen` 是否稳定不再增长
- 网址错了 → `--url` 手动传真实地址重试

---

## 二、故障处置

### 1. 熔断被触发（最常见）

**现象**：`scout run` 报 `CircuitOpen`，或面板上熔断卡片变红。

**这意味着**：连续出现空返回/错误 → 判定被静默降级。

**处置**：

```powershell
# 第一步：先看是什么原因触发的，别急着解除
.\.venv\Scripts\python.exe -m scout.cli circuit status

# 第二步：看最近的失败请求到底返回了什么
.\.venv\Scripts\python.exe -m scout.cli raw --limit 20
```

- 如果 `reason` 是**空返回**：多半是账号/ IP 被限流。**等满冷却时间**，
  然后降低配额再开。不要立刻 `reset` 硬顶。
- 如果 `reason` 是**连续错误**：看 `request_logs` 里的 `error` 字段。
  连接失败 → 网络/代理问题；4xx → 接口变了。

**确认要恢复时**：

```powershell
.\.venv\Scripts\python.exe -m scout.cli circuit reset b
```

同时把配额降到上一个档位的水平，观察 3 天再恢复。

### 2. 空返回率突然升高（还没到熔断阈值）

**先手动熔断，再排查**：

```powershell
.\.venv\Scripts\python.exe -m scout.cli circuit open b --reason "空返回率异常，人工停机"
```

然后勘探一次看真实情况：

```powershell
.\.venv\Scripts\python.exe -m scout.cli probe --url "https://www.douyin.com/user/<一个已知有效的SEC_UID>" --tier b --scroll 2
```

看报告里：
- **疑似登录墙 = 是** → 匿名态被挡了，需要换策略（见下文"登录墙"）
- **捕获响应 = 0** → 页面地址或接口变了
- **解析出数据 = 否** → 接口结构变了，走「改版处置」

### 3. 改版处置（解析器维护）

**关键认知：改版不需要重新采集。** 原始响应都在归档里。

```powershell
# 1. 找一条改版后采到的原始响应
.\.venv\Scripts\python.exe -m scout.cli raw --limit 30

# 2. 看它现在解析成什么
.\.venv\Scripts\python.exe -m scout.cli replay <raw_id>

# 3. 改 src/scout/parse/extract.py 里的字段映射（只改这一个文件）

# 4. 回放验证
.\.venv\Scripts\python.exe -m scout.cli replay <raw_id>

# 5. 确认无误后批量回填历史数据
.\.venv\Scripts\python.exe -m scout.cli raw --limit 200   # 拿到一批 raw_id
.\.venv\Scripts\python.exe -m scout.cli replay <raw_id> --persist
```

**通用抽取器是你的安全网**：即使精确解析器全挂，它也能按对象形状抽出数据。
如果 `replay` 显示 `parser: generic` 且能出数据，说明还能跑，可以慢慢修精确解析器。

### 4. 撞登录墙（匿名态被挡）

**现象**：`probe` 报告 `疑似登录墙 = 是`，或用户主页大批返回空。

**处置顺序（从低风险到高风险）**：

1. **降低频率**。最常见的原因就是太快了。配额砍半，等 3 天。
2. **换时段**。深夜跑，避开平台高峰。
3. **检查是否过于规律**。看 `throttle` 配置，把 `min_delay_s` / `max_delay_s` 区间放宽。
4. **走分享页入口**。抖音的外部分享链接通常没有登录墙。
   勘探确认可用后，把 `targets.user_url_template` 换成分享页格式。
5. **最后手段**：给档 B 注入档 A 的 `storage_state`。
   注意这会让匿名档带上账号身份，**不再是匿名的**，风险等级上升。
   除非前 4 步都无效，否则不要做。

### 5. 档 A 登录态失效

**现象**：通知流采不到数据，或 `probe --tier a` 报告登录墙。

```powershell
.\.venv\Scripts\python.exe -m scout.cli login --tier a
```

重新扫码。profile 是持久化的，正常情况几周才需要重登一次。

### 6. profile 被占用

**现象**：报 `ProfileLockBusy`。

```powershell
Get-Process python | Select-Object Id, ProcessName, StartTime
```

确认没有别的进程在跑之后：

```powershell
Remove-Item "data\profiles\tier_a\.dsh-lock"
```

**不要在有进程活着的时候删这个文件**，会导致两个浏览器实例同时写 profile，profile 会损坏。

### 7. 进程崩溃 / 断电

不用做任何事。下次 `scout run` 会自动把卡在 `running` 的任务捞回 `pending`。

验证一下：

```powershell
.\.venv\Scripts\python.exe -m scout.cli tasks --state pending | Select-Object -First 10
```

---

## 三、参数调整速查

全在 `config/local.yaml`，改完立即生效，不用重启（下次运行读新配置）。

| 想解决的问题 | 改哪个 | 怎么改 |
|---|---|---|
| 太慢，想多采 | `tiers.b.daily_request_quota` | 按放量表逐档加，**不要跳步** |
| 被限流 | `tiers.b.min_delay_s` / `max_delay_s` | 区间放大 1.5~2 倍 |
| 太规律 | `guard.throttle.jitter_ratio` | 0.35 → 0.5 |
| 空返回没被及时拦住 | `guard.circuit.consecutive_empty_open` | 5 → 3（更敏感） |
| 页面内容没加载完就收工 | `tiers.b.scroll_rounds` | 6 → 10 |
| 想改采集页数上限 | `app.max_tasks_per_run` | 按需 |

环境变量可以临时覆盖，不用改文件：

```powershell
$env:SCOUT_TIERS__B__DAILY_REQUEST_QUOTA = "50"
.\.venv\Scripts\python.exe -m scout.cli run
```

---

## 四、数据维护

### 备份（唯一重要的资产是 DB 和 raw）

```powershell
$stamp = Get-Date -Format "yyyyMMdd"
Copy-Item "data\db\scout.sqlite3" "backup\scout-$stamp.sqlite3"
Compress-Archive -Path "data\raw\*" -DestinationPath "backup\raw-$stamp.zip"
```

**永远不要删 `data/raw/`。** 那是唯一无法重新获得的东西。

### 导出

```powershell
.\.venv\Scripts\python.exe -m scout.cli export --table users
.\.venv\Scripts\python.exe -m scout.cli export --table works
.\.venv\Scripts\python.exe -m scout.cli report
```

---

## 五、红线（任何时候不要越）

1. **不要为了"采完"而突破配额。** 配额是长期存活的唯一保障。
2. **不要上并发。** 风控最先抓的就是并发特征。
3. **不要伪造浏览器指纹**（stealth 插件、改 `navigator.webdriver`）。
   要更真实就用 `browser.cdp_url` 连接你自己的浏览器。
4. **不要引入第三方签名实现**（a_bogus 之类）。
   既踩合规红线，也是维护无底洞。
5. **不要把它做成对外服务。** 一旦托管他人账号，法律身份就变了。
6. **不要用主号做档 A。** 用小号。

---

## 六、出问题时的信息收集清单

报问题给我时，带上这四样，能省掉一半排查时间：

```powershell
# 1. 当前状态
.\.venv\Scripts\python.exe -m scout.cli status --json > diag-status.json

# 2. 哪个请求在出错
.\.venv\Scripts\python.exe -m scout.cli raw --limit 20

# 3. 最近事件
.\.venv\Scripts\python.exe -m scout.cli circuit status

# 4. 一次勘探报告（最有价值）
.\.venv\Scripts\python.exe -m scout.cli probe --url "<出问题的地址>" --tier b
# 然后把 exports\probe-*.md 发我
```

---

## 账号隔离（一账号一数据目录）

**切换账号前必读。** 每个账号是一套完全独立的目录，互不污染：

```
data/accounts/
  main/                 ← 账号槽位（名字你起）
    db/scout.sqlite3
    profiles/tier_a/    ← 登录态（浏览器 profile）
    raw/  exports/  state/
  alt/
    ...
```

用法：

```powershell
python -m scout.cli --account main status
python -m scout.cli --account alt  seed
python -m scout.cli account list      # 有哪些账号
python -m scout.cli account show      # 当前用哪套、数据属于谁
python -m scout.cli account check     # 核对"目录 vs 登录号"是否一致
```

也可以设环境变量：`$env:SCOUT_ACCOUNT = "alt"`

### 三层保护

| 层 | 作用 |
|---|---|
| 独立目录 | **物理隔离**，不可能串号 |
| 开跑前对账 | `scout run` 会先问一次"我是谁"，与库里记录不一致就**拒绝开跑** |
| 页面显示 | 顶部常驻显示当前账号和身份，"以为在看 A 号数据其实是 B 号"不会发生 |

### 万一目录和登录号对不上

`scout run` 会停下并给出两个出路：

1. **换个目录**（推荐）：`scout --account <新名字> ...`
2. **显式认领**：`scout account adopt`（会覆盖身份记录，但**不清理已混入的数据**）

### 为什么不用"给表加 account 列"

独立目录是物理隔离；加列要靠每条 SQL 都写对，漏一处就串号，而串号无声无息。
本地单机自用、不需要跨账号对比，独立目录的确定性更值。
