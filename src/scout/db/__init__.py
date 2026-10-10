"""SQLite 存储层。

设计取舍：
- 用标准库 sqlite3，不用 ORM。迁移是显式编号的 .sql 文件，可审计、可回放。
- 单写者、WAL、autocommit。所有需要原子性的操作写成单条 SQL。
- 任何写操作都必须是幂等的（upsert），重复采集不产生脏数据。
"""

from .connect import Database, connect
from .migrate import applied_versions, migrate, pending_versions

__all__ = ["Database", "connect", "migrate", "applied_versions", "pending_versions"]
