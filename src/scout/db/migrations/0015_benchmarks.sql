-- 0015_benchmarks.sql —— 对标账号（登记 + 更新检查状态）
--
-- 只登记"看谁"。对标账号的作品与点赞人的作品同一处理：
-- 直接进 works 表（author_sec_uid 归属，is_mine 保持 0），
-- 不为对标单独建作品表 —— 查询按"对标名单"过滤即可。

CREATE TABLE IF NOT EXISTS benchmark_accounts (
    sec_uid         TEXT PRIMARY KEY,
    nickname        TEXT NOT NULL DEFAULT '',
    note            TEXT NOT NULL DEFAULT '',
    added_at        TEXT NOT NULL,
    last_checked_at TEXT,
    last_new_count  INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT NOT NULL DEFAULT ''
);
