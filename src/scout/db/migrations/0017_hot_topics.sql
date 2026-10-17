-- 0017_hot_topics.sql —— 抖音热榜快照（2026-10-17）
--
-- 热榜不是搜索：直接调抖音官方 hot/search 接口。
-- 每抓一次存一份快照，用来做排名/热度变化与“接口失败时回落最近一次”。

CREATE TABLE IF NOT EXISTS hot_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at  TEXT NOT NULL,
    tier        TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT 'douyin',
    raw_blob_id INTEGER REFERENCES raw_blobs(id),
    item_count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS hot_entries (
    snapshot_id INTEGER NOT NULL REFERENCES hot_snapshots(id) ON DELETE CASCADE,
    rank        INTEGER NOT NULL,
    word        TEXT NOT NULL,
    hot_value   INTEGER,
    sentence_id TEXT,
    label       TEXT,
    PRIMARY KEY (snapshot_id, rank)
);

CREATE INDEX IF NOT EXISTS idx_hot_entries_word ON hot_entries(word);
CREATE INDEX IF NOT EXISTS idx_hot_snapshots_time ON hot_snapshots(fetched_at DESC);
