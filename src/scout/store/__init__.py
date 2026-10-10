"""存储层：原始归档、实体仓储、遥测、缓存。

所有对数据库的写操作都通过这里，业务代码不直接写 SQL。
"""

from .cache import AbstractCache, SqliteCache, make_cache
from .raw_archive import RawArchive, RawRef
from .repo import Cursors, LikeEdges, NoticeRuns, Tasks, UserSnapshots, Users, Works
from .telemetry import Telemetry

__all__ = [
    "RawArchive",
    "RawRef",
    "Users",
    "Works",
    "LikeEdges",
    "UserSnapshots",
    "NoticeRuns",
    "Tasks",
    "Cursors",
    "Telemetry",
    "AbstractCache",
    "SqliteCache",
    "make_cache",
]
