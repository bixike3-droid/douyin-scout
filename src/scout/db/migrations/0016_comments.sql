-- 0016_comments.sql —— 作品评论（P2.3 阶段 2）
--
-- 归口约定：每条评论必须挂到具体作品（aweme_id），不存无主数据。
-- 作者资料仍走 users 表（与点赞人共用同一套画像与快照）。

CREATE TABLE IF NOT EXISTS comments (
    comment_id    TEXT PRIMARY KEY,
    aweme_id      TEXT NOT NULL,
    sec_uid       TEXT NOT NULL DEFAULT '',
    text          TEXT NOT NULL DEFAULT '',
    digg_count    INTEGER,
    reply_count   INTEGER,
    create_time   INTEGER,
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    raw_blob_id   INTEGER REFERENCES raw_blobs(id)
);

CREATE INDEX IF NOT EXISTS idx_comments_aweme ON comments(aweme_id, digg_count DESC);
CREATE INDEX IF NOT EXISTS idx_comments_uid   ON comments(sec_uid);
