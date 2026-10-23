-- App-server identities live in the account database, outside personal Codex.
CREATE TABLE IF NOT EXISTS codex_sessions (
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    agent TEXT NOT NULL,
    provider_url TEXT NOT NULL,
    model TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    last_message_id INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(conversation_id,agent,provider_url,model)
);
CREATE TABLE IF NOT EXISTS codex_runs (
    run_id INTEGER PRIMARY KEY REFERENCES chat_runs(id),
    model TEXT NOT NULL,
    provider_url TEXT NOT NULL,
    thread_id TEXT NOT NULL DEFAULT '',
    turn_id TEXT NOT NULL DEFAULT '',
    input_sent INTEGER NOT NULL DEFAULT 0,
    usage_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS codex_events (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES codex_runs(run_id),
    method TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_codex_events_run ON codex_events(run_id,id);
