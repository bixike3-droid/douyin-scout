"""profile 独占锁。

为什么必须有：Playwright 的持久化 profile 目录不能被两个进程同时打开，
第二个进程会直接崩，而且报错信息很难懂。这个坑在真正跑起来之前不会暴露。

做法：在 profile 目录旁放一个 lock 文件，用 O_EXCL 创建保证原子性。
进程异常退出留下死锁时，按 mtime 判定过期后自动接管。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ProfileLockBusy(RuntimeError):
    def __init__(self, profile_dir: Path, holder: dict[str, Any]):
        super().__init__(
            f"profile 已被占用：{profile_dir}\n"
            f"  持有者 pid={holder.get('pid')} 启动于 {holder.get('started_at')}\n"
            f"  如果确认没有别的进程在跑，删除 {profile_dir / '.dsh-lock'} 后重试。"
        )
        self.profile_dir = profile_dir
        self.holder = holder


class ProfileLock:
    def __init__(self, profile_dir: str | Path, *, stale_minutes: int = 180):
        self.profile_dir = Path(profile_dir)
        self.lock_path = self.profile_dir / ".dsh-lock"
        self.stale_minutes = stale_minutes
        self._acquired = False

    def _write_holder(self) -> None:
        payload = {
            "pid": os.getpid(),
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "cwd": os.getcwd(),
        }
        fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        finally:
            os.close(fd)

    def _read_holder(self) -> dict[str, Any]:
        try:
            return json.loads(self.lock_path.read_text(encoding="utf-8"))
        except Exception:
            return {"pid": "unknown", "started_at": "unknown"}

    def _is_stale(self) -> bool:
        try:
            age_s = datetime.now(timezone.utc).timestamp() - self.lock_path.stat().st_mtime
        except OSError:
            return True
        return age_s > self.stale_minutes * 60

    def acquire(self) -> "ProfileLock":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._write_holder()
        except FileExistsError:
            if self._is_stale():
                self.lock_path.unlink(missing_ok=True)
                self._write_holder()
            else:
                raise ProfileLockBusy(self.profile_dir, self._read_holder()) from None
        self._acquired = True
        return self

    def release(self) -> None:
        if self._acquired:
            self.lock_path.unlink(missing_ok=True)
            self._acquired = False

    def __enter__(self) -> "ProfileLock":
        return self.acquire()

    def __exit__(self, *exc: object) -> None:
        self.release()

    @classmethod
    def status(cls, profile_dir: str | Path) -> dict[str, Any]:
        d = Path(profile_dir)
        lock = d / ".dsh-lock"
        if not lock.exists():
            return {"locked": False, "profile_dir": str(d)}
        try:
            holder = json.loads(lock.read_text(encoding="utf-8"))
        except Exception:
            holder = {}
        age_s = datetime.now(timezone.utc).timestamp() - lock.stat().st_mtime
        return {"locked": True, "profile_dir": str(d), "holder": holder, "age_s": int(age_s)}
