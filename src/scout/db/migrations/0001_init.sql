-- 0001_init.sql —— 初始 schema
--
-- 设计原则：
--   1. 所有外部字段用 TEXT 存原始值，解析失败不丢数据。
--   2. 所有写入走 upsert（幂等），重复采集不产生脏数据。
--   3. user_snapshots 保留历史快照，趋势分析靠它，不能只存当前值。
--   4. raw_blobs 是所有解析结果的溯源锚点：任何一条数据都能追回原始响应。

-- ── 迁移记录（由 migrate.py 维护）────────────────────────
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

-- ── 原始响应归档索引 ─────────────────────────────────────
-- 正文落盘在 data/raw/YYYY-MM-DD/，这里只存索引。永不删除是默认策略。
CREATE TABLE IF NOT EXISTS raw_blobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256       TEXT    NOT NULL UNIQUE,
    path         TEXT    NOT NULL,
    url          TEXT    NOT NULL DEFAULT '',
    tier         TEXT    NOT NULL DEFAULT '',
    content_type TEXT    NOT NULL DEFAULT '',
    byte_size    INTEGER NOT NULL DEFAULT 0,
    collected_at TEXT    NOT NULL,
    source       TEXT    NOT NULL DEFAULT '',   -- probe | collect | replay
    note         TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_raw_blobs_collected ON raw_blobs(collected_at DESC);

-- ── 账号 ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    sec_uid            TEXT PRIMARY KEY,          -- 抖音的稳定用户标识（关键桥梁）
    uid                TEXT NOT NULL DEFAULT '',
    douyin_id          TEXT NOT NULL DEFAULT '',  -- 抖音号
    nickname           TEXT NOT NULL DEFAULT '',
    signature          TEXT NOT NULL DEFAULT '',
    avatar_url         TEXT NOT NULL DEFAULT '',
    gender             INTEGER,                   -- 0 未知 1 男 2 女
    region             TEXT NOT NULL DEFAULT '',
    ip_location        TEXT NOT NULL DEFAULT '',
    follower_count     INTEGER,
    following_count    INTEGER,
    total_favorited    INTEGER,
    aweme_count        INTEGER,
    verification       TEXT NOT NULL DEFAULT '',
    is_verified        INTEGER NOT NULL DEFAULT 0,
    -- 采集状态机：pending → ok | no_profile | login_wall | blocked | error
    profile_state      TEXT    NOT NULL DEFAULT 'pending',
    profile_attempts   INTEGER NOT NULL DEFAULT 0,
    profile_tier       TEXT    NOT NULL DEFAULT '',
    profile_fetched_at TEXT,
    discovered_from    TEXT    NOT NULL DEFAULT '',  -- 从哪个作品/通知发现
    first_seen_at      TEXT    NOT NULL,
    last_seen_at       TEXT    NOT NULL,
    raw_blob_id        INTEGER REFERENCES raw_blobs(id)
);
CREATE INDEX IF NOT EXISTS idx_users_state   ON users(profile_state, last_seen_at);
CREATE INDEX IF NOT EXISTS idx_users_fans    ON users(follower_count DESC);
CREATE INDEX IF NOT EXISTS idx_users_douyin  ON users(douyin_id);

-- ── 用户快照（趋势分析靠它）──────────────────────────────
CREATE TABLE IF NOT EXISTS user_snapshots (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    sec_uid        TEXT NOT NULL,
    day            TEXT NOT NULL,                 -- 本地日期 YYYY-MM-DD
    follower_count INTEGER,
    following_count INTEGER,
    total_favorited INTEGER,
    aweme_count    INTEGER,
    captured_at    TEXT NOT NULL,
    UNIQUE(sec_uid, day)
);
CREATE INDEX IF NOT EXISTS idx_user_snapshots_uid ON user_snapshots(sec_uid, day);

-- ── 作品 ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS works (
    aweme_id        TEXT PRIMARY KEY,
    author_sec_uid  TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    create_time     INTEGER,                      -- 秒级时间戳
    duration_ms     INTEGER,
    digg_count      INTEGER,
    comment_count   INTEGER,
    share_count     INTEGER,
    collect_count   INTEGER,
    play_count      INTEGER,
    music_title     TEXT NOT NULL DEFAULT '',
    hashtags_json   TEXT NOT NULL DEFAULT '[]',
    cover_url       TEXT NOT NULL DEFAULT '',
    share_url       TEXT NOT NULL DEFAULT '',
    is_top          INTEGER NOT NULL DEFAULT 0,
    is_mine         INTEGER NOT NULL DEFAULT 0,   -- 是否自己账号的作品
    first_seen_at   TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL,
    stats_fetched_at TEXT,
    raw_blob_id     INTEGER REFERENCES raw_blobs(id)
);
CREATE INDEX IF NOT EXISTS idx_works_author  ON works(author_sec_uid, create_time DESC);
CREATE INDEX IF NOT EXISTS idx_works_ctime   ON works(create_time DESC);
CREATE INDEX IF NOT EXISTS idx_works_mine    ON works(is_mine, create_time DESC);

-- ── 点赞边：谁赞了哪个作品 ───────────────────────────────
-- 空串占位而非 NULL，让 UNIQUE 约束真正生效（SQLite 中 NULL 互不相等）。
CREATE TABLE IF NOT EXISTS like_edges (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sec_uid       TEXT NOT NULL,
    aweme_id      TEXT NOT NULL DEFAULT '',
    notice_id     TEXT NOT NULL DEFAULT '',
    notice_kind   TEXT NOT NULL DEFAULT 'digg',   -- digg | comment | follow
    discovered_at TEXT NOT NULL,
    tier          TEXT NOT NULL DEFAULT 'a',
    raw_blob_id   INTEGER REFERENCES raw_blobs(id),
    UNIQUE(sec_uid, aweme_id, notice_id)
);
CREATE INDEX IF NOT EXISTS idx_like_edges_uid     ON like_edges(sec_uid, discovered_at DESC);
CREATE INDEX IF NOT EXISTS idx_like_edges_aweme   ON like_edges(aweme_id);
CREATE INDEX IF NOT EXISTS idx_like_edges_disc    ON like_edges(discovered_at DESC);

-- ── 用户作品列表归属（不是作品本身，是"这个用户主页上出现过它"）──
CREATE TABLE IF NOT EXISTS user_work_listings (
    sec_uid      TEXT NOT NULL,
    aweme_id     TEXT NOT NULL,
    position     INTEGER,
    listed_at    TEXT NOT NULL,
    raw_blob_id  INTEGER REFERENCES raw_blobs(id),
    PRIMARY KEY (sec_uid, aweme_id)
);

-- ── 任务队列（断点续采的核心）────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT NOT NULL,        -- fetch_notice | fetch_profile | fetch_user_works
    target        TEXT NOT NULL,        -- sec_uid 或 URL
    tier          TEXT NOT NULL,        -- a | b
    priority      INTEGER NOT NULL DEFAULT 100,   -- 数字越小越优先
    state         TEXT NOT NULL DEFAULT 'pending',-- pending|running|done|failed|blocked
    attempts      INTEGER NOT NULL DEFAULT 0,
    max_attempts  INTEGER NOT NULL DEFAULT 5,
    available_at  TEXT NOT NULL,
    claimed_at    TEXT,
    finished_at   TEXT,
    last_error    TEXT NOT NULL DEFAULT '',
    payload_json  TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    UNIQUE(kind, target, tier)
);
CREATE INDEX IF NOT EXISTS idx_tasks_ready ON tasks(state, available_at, priority);

-- ── 分页游标 ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cursor_state (
    name       TEXT PRIMARY KEY,
    cursor     TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

-- ── 请求遥测（每个请求一行，出问题能回溯）────────────────
CREATE TABLE IF NOT EXISTS request_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    tier         TEXT NOT NULL DEFAULT '',
    task_id      INTEGER,
    method       TEXT NOT NULL DEFAULT 'GET',
    url          TEXT NOT NULL,
    status       INTEGER,
    ok           INTEGER NOT NULL DEFAULT 0,
    byte_size    INTEGER NOT NULL DEFAULT 0,
    duration_ms  INTEGER,
    empty_result INTEGER NOT NULL DEFAULT 0,
    error        TEXT NOT NULL DEFAULT '',
    raw_blob_id  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_request_logs_ts   ON request_logs(ts DESC);
CREATE INDEX IF NOT EXISTS idx_request_logs_tier ON request_logs(tier, ts DESC);
CREATE INDEX IF NOT EXISTS idx_request_logs_bad  ON request_logs(ok, empty_result, ts DESC);

-- ── 配额账本（按本地日期分桶）────────────────────────────
CREATE TABLE IF NOT EXISTS quota_ledger (
    day         TEXT NOT NULL,
    tier        TEXT NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0,
    limit_value INTEGER,
    PRIMARY KEY (day, tier)
);

-- ── 熔断状态 ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS circuit_state (
    key               TEXT PRIMARY KEY,       -- 例如 'tier_b'
    state             TEXT NOT NULL DEFAULT 'closed',  -- closed|open|half_open
    reason            TEXT NOT NULL DEFAULT '',
    opened_at         TEXT,
    cooldown_until    TEXT,
    open_count        INTEGER NOT NULL DEFAULT 0,      -- 连续熔断次数，用于加倍冷却
    consecutive_empty INTEGER NOT NULL DEFAULT 0,
    consecutive_error INTEGER NOT NULL DEFAULT 0,
    updated_at        TEXT NOT NULL
);

-- ── 事件日志（人看的运维记录）────────────────────────────
CREATE TABLE IF NOT EXISTS event_logs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    level     TEXT NOT NULL DEFAULT 'info',
    scope     TEXT NOT NULL DEFAULT '',
    message   TEXT NOT NULL DEFAULT '',
    data_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_event_logs_ts ON event_logs(ts DESC);

-- ── 去重缓存（带 TTL 的 KV；采集前先查这里，命中就不重抓）──
CREATE TABLE IF NOT EXISTS kv_cache (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    expires_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_kv_cache_exp ON kv_cache(expires_at);

-- ── 便捷视图：待办用户队列 ───────────────────────────────
CREATE VIEW IF NOT EXISTS v_user_backlog AS
SELECT
    u.sec_uid,
    u.nickname,
    u.profile_state,
    u.profile_attempts,
    u.last_seen_at,
    (SELECT COUNT(*) FROM like_edges le WHERE le.sec_uid = u.sec_uid) AS like_count
FROM users u
WHERE u.profile_state IN ('pending', 'error', 'blocked')
ORDER BY like_count DESC, u.last_seen_at ASC;
