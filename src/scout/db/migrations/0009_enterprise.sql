-- Enterprise context, immutable analysis inputs, manual review and metric snapshots.
CREATE TABLE IF NOT EXISTS enterprise_profile (
    id INTEGER PRIMARY KEY CHECK (id=1),
    data_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS enterprise_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aweme_id TEXT NOT NULL REFERENCES works(aweme_id),
    measured_at TEXT NOT NULL,
    source TEXT NOT NULL,
    play_count INTEGER CHECK(play_count>=0),
    digg_count INTEGER CHECK(digg_count>=0),
    comment_count INTEGER CHECK(comment_count>=0),
    share_count INTEGER CHECK(share_count>=0),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_enterprise_metrics_work ON enterprise_metrics(aweme_id,measured_at DESC,id DESC);
CREATE TABLE IF NOT EXISTS enterprise_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    model TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    input_json TEXT NOT NULL,
    output_json TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_enterprise_reports_cache ON enterprise_reports(input_digest,prompt_version,model);
CREATE TABLE IF NOT EXISTS enterprise_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL REFERENCES enterprise_reports(id),
    created_at TEXT NOT NULL,
    content TEXT NOT NULL,
    reason TEXT NOT NULL,
    reviewed INTEGER NOT NULL CHECK(reviewed IN (0,1))
);
