"""账号数据自检。

**为什么需要这个**

账号隔离靠"一个账号一个数据目录"保证。但还有一种出错方式目录隔离挡不住：

    数据目录是 A 号的，但浏览器 profile 里登录的是 B 号。

这时候所有采集都会写进 A 号的库 —— 两套数据混在一起，而且**无声无息**。

所以每次开跑之前对一次账：库里记的 `self_sec_uid`，和当前登录的号，是不是同一个。
不一致就**明确报错停下**，而不是继续往里写。

这条检查的价值在于：它把一个"事后才发现、且不可逆"的错误，变成一个
"开跑时就拦下、可以立刻处理"的错误。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AccountCheck:
    ok: bool
    status: str          # ok | unknown | mismatch | no_login
    message: str
    stored_sec_uid: str = ""
    stored_nickname: str = ""
    live_sec_uid: str = ""
    live_nickname: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "message": self.message,
            "stored_sec_uid": self.stored_sec_uid,
            "stored_nickname": self.stored_nickname,
            "live_sec_uid": self.live_sec_uid,
            "live_nickname": self.live_nickname,
        }


def stored_identity(ctx) -> tuple[str, str]:
    """库里记录的"这套数据属于谁"。"""
    sec = ctx.cursors.get("self_sec_uid") or ""
    nick = ""
    if sec:
        user = ctx.users.get(sec) or {}
        nick = user.get("nickname") or ""
    return sec, nick


def check_account(ctx, *, live_sec_uid: str = "", live_nickname: str = "") -> AccountCheck:
    """对账。

    不传 live 信息时只检查"库里有没有身份记录"；
    传了就做真正的比对（由调用方先调一次 profile/self 拿到当前登录身份）。
    """
    stored_sec, stored_nick = stored_identity(ctx)

    if not live_sec_uid:
        if not stored_sec:
            return AccountCheck(
                ok=True, status="unknown",
                message="这个账号目录还没记录过身份（首次采集后会自动记录）",
            )
        return AccountCheck(
            ok=True, status="no_login", stored_sec_uid=stored_sec,
            stored_nickname=stored_nick,
            message=f"数据属于「{stored_nick or stored_sec[:16]}」；本次未校验登录态",
        )

    if not stored_sec:
        return AccountCheck(
            ok=True, status="unknown",
            live_sec_uid=live_sec_uid, live_nickname=live_nickname,
            message=f"首次为「{live_nickname or live_sec_uid[:16]}」记录身份",
        )

    if stored_sec != live_sec_uid:
        return AccountCheck(
            ok=False, status="mismatch",
            stored_sec_uid=stored_sec, stored_nickname=stored_nick,
            live_sec_uid=live_sec_uid, live_nickname=live_nickname,
            message=(
                f"账号不匹配！这个数据目录属于「{stored_nick or stored_sec[:16]}」，"
                f"但当前登录的是「{live_nickname or live_sec_uid[:16]}」。\n"
                f"继续跑会把两个号的数据混在一起，而且不可逆。\n"
                f"处理办法（二选一）：\n"
                f"  1. 换个数据目录：scout --account <新名字> ...  （推荐）\n"
                f"  2. 确认要在这个目录里采这个号：scout account adopt"
            ),
        )

    return AccountCheck(
        ok=True, status="ok",
        stored_sec_uid=stored_sec, stored_nickname=stored_nick,
        live_sec_uid=live_sec_uid, live_nickname=live_nickname,
        message=f"账号一致：「{stored_nick or stored_sec[:16]}」",
    )


def adopt(ctx, sec_uid: str, nickname: str = "") -> None:
    """显式把当前登录的号认领为这个数据目录的主人。

    只在用户明确知道后果时调用（`scout account adopt`）——
    它会覆盖原来的身份记录，但**不会清理已有的混合数据**。
    """
    ctx.cursors.set("self_sec_uid", sec_uid)
    if nickname:
        ctx.users.upsert({"sec_uid": sec_uid, "nickname": nickname})
