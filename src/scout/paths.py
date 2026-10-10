"""路径解析：项目根、账号数据目录、归档目录。

**账号隔离靠"一个账号一个数据目录"实现。**

为什么用独立目录，而不是给表加 `account` 列：

- 独立目录是**物理隔离**，不可能串号
- 加列的话每条 SQL 都得写对，漏一处就是数据串号 —— 而串号无声无息，
  等发现时数据已经废了（作品归属被污染那次就是这个性质的问题）
- 本地单机自用，不需要跨账号对比，所以独立目录的代价（不能简单跨号查询）
  换来的确定性是划算的

目录结构::

    data/
      accounts/
        main/            ← 账号槽位（名字你自己起）
          db/scout.sqlite3
          profiles/tier_a/
          raw/
          exports/
          state/
        alt/
          ...

切换账号就是换 `--account`，两套数据互不相干。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ACCOUNT = "main"
ACCOUNTS_SUBDIR = "accounts"
# 账号名会直接变成目录名，必须挡掉路径穿越和非法字符
_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{1,40}$")


def find_project_root(start: str | Path | None = None) -> Path:
    """从 start 向上找到含 pyproject.toml 的目录；找不到就返回 start 所在目录。"""
    p = Path(start or __file__).resolve()
    if p.is_file():
        p = p.parent
    for cand in (p, *p.parents):
        if (cand / "pyproject.toml").is_file():
            return cand
    return p


def validate_account(name: str) -> str:
    """账号名会变成目录名，必须挡住 `..`、`/`、空白等危险输入。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("账号名不能为空")
    if not _ACCOUNT_RE.match(name):
        raise ValueError(
            f"账号名不合法：{name!r}。只允许中文、字母、数字、下划线、短横线，长度 1-40"
        )
    return name


# ── 当前账号 ────────────────────────────────────────────────
#
# 用一个模块级状态而不是给每个 Paths.build() 调用点加参数：
# 项目里有近 20 处调用，逐个加参一定会有漏的，而漏掉一处就是"写进别的账号"。
# 所以改成"入口设一次，全局生效"，出错面收敛到一个地方。

_current_account: str = DEFAULT_ACCOUNT


def set_current_account(name: str) -> str:
    """设定当前账号。CLI 入口、Web 启动时各调一次。"""
    global _current_account
    _current_account = validate_account(name)
    return _current_account


def get_current_account() -> str:
    return _current_account


@dataclass(frozen=True)
class Paths:
    root: Path
    config_dir: Path
    default_config: Path
    local_config: Path
    account: str
    accounts_dir: Path
    data_dir: Path          # 当前账号的数据根目录
    raw_dir: Path
    profiles_dir: Path
    log_dir: Path
    export_dir: Path
    state_dir: Path
    db_path: Path

    @classmethod
    def build(
        cls,
        root: str | Path | None = None,
        data_dir: str | Path | None = None,
        account: str | None = None,
    ) -> "Paths":
        root_p = Path(root).resolve() if root else find_project_root()
        base = Path(data_dir).resolve() if data_dir else (root_p / "data")
        # 优先用环境变量：Web 服务是子进程，靠它把账号传进去
        acct = validate_account(
            account or os.environ.get("SCOUT_ACCOUNT") or _current_account
        )
        accounts_dir = base / ACCOUNTS_SUBDIR
        data_p = accounts_dir / acct
        config_dir = root_p / "config"
        return cls(
            root=root_p,
            config_dir=config_dir,
            default_config=config_dir / "default.yaml",
            local_config=config_dir / "local.yaml",
            account=acct,
            accounts_dir=accounts_dir,
            data_dir=data_p,
            raw_dir=data_p / "raw",
            profiles_dir=data_p / "profiles",
            log_dir=data_p / "logs",
            export_dir=data_p / "exports",
            state_dir=data_p / "state",
            db_path=data_p / "db" / "scout.sqlite3",
        )

    # ── 账号管理 ────────────────────────────────────────────

    def list_accounts(self) -> list[str]:
        """已存在的账号槽位（有数据目录的）。"""
        if not self.accounts_dir.is_dir():
            return []
        return sorted(
            p.name for p in self.accounts_dir.iterdir()
            if p.is_dir() and (p / "db" / "scout.sqlite3").is_file()
        )

    def account_dirs(self, name: str) -> Path:
        return self.accounts_dir / validate_account(name)

    def legacy_paths(self) -> tuple[Path, ...]:
        """升级前的旧布局（数据直接在 data/ 下）。用来做一次性迁移。"""
        base = self.accounts_dir.parent
        return (
            base / "db" / "scout.sqlite3",
            base / "raw",
            base / "profiles",
            base / "exports",
            base / "state",
        )

    # ── 目录创建 ────────────────────────────────────────────

    def all_dirs(self) -> tuple[Path, ...]:
        return (
            self.config_dir,
            self.accounts_dir,
            self.data_dir,
            self.raw_dir,
            self.profiles_dir,
            self.log_dir,
            self.export_dir,
            self.state_dir,
            self.db_path.parent,
        )

    def ensure(self) -> "Paths":
        for d in self.all_dirs():
            d.mkdir(parents=True, exist_ok=True)
        return self
