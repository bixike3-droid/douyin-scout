-- 0002_notice_runs.sql —— 点赞人名单的采集完整性记录
--
-- 为什么需要：如果假设「网页能看到完整名单」，那就必须能证明"这次确实拿完了"，
-- 而不是拿了一页就当全量。每跑一轮通知流采集记一行：
-- 翻了几轮、看到多少条、新增多少条、有没有触到底、为什么停。

CREATE TABLE IF NOT EXISTS notice_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT    NOT NULL,
    finished_at  TEXT    NOT NULL DEFAULT '',
    tier         TEXT    NOT NULL DEFAULT 'a',
    url          TEXT    NOT NULL DEFAULT '',
    rounds       INTEGER NOT NULL DEFAULT 0,   -- 实际滚动/翻页轮数
    captured     INTEGER NOT NULL DEFAULT 0,   -- 收到的响应数
    edges_seen   INTEGER NOT NULL DEFAULT 0,   -- 本轮看到的点赞边（含重复）
    new_edges    INTEGER NOT NULL DEFAULT 0,   -- 真正新增的点赞边
    distinct_likers INTEGER NOT NULL DEFAULT 0,-- 本轮涉及的不同点赞人
    reached_end  INTEGER NOT NULL DEFAULT 0,   -- 是否触到"没有更多了"
    stop_reason  TEXT    NOT NULL DEFAULT '',
    raw_ids      TEXT    NOT NULL DEFAULT ''   -- 逗号分隔的 raw_blobs.id
);
CREATE INDEX IF NOT EXISTS idx_notice_runs_started ON notice_runs(started_at DESC);

-- 累积覆盖视图：每个点赞人第一次和最后一次被看到
CREATE VIEW IF NOT EXISTS v_liker_coverage AS
SELECT
    sec_uid,
    COUNT(*)                       AS like_count,
    MIN(discovered_at)             AS first_seen_at,
    MAX(discovered_at)             AS last_seen_at,
    COUNT(DISTINCT aweme_id)       AS distinct_works
FROM like_edges
GROUP BY sec_uid;
