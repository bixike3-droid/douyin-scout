-- Recovery records are separate from the bounded model context.
CREATE TABLE IF NOT EXISTS conversation_memory_progress (
    conversation_id INTEGER PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
    covered_message_id INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS chat_runs (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    user_message_id INTEGER NOT NULL UNIQUE REFERENCES conversation_messages(id),
    agent TEXT NOT NULL,
    account_uid TEXT NOT NULL DEFAULT '',
    request TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    context_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    model_calls INTEGER NOT NULL DEFAULT 0,
    tool_count INTEGER NOT NULL DEFAULT 0,
    elapsed_ms INTEGER NOT NULL DEFAULT 0,
    delegate_calls INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_runs_conversation ON chat_runs(conversation_id,id);
CREATE TABLE IF NOT EXISTS chat_invocations (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES chat_runs(id),
    position INTEGER NOT NULL,
    provider_call_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    arguments TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'selected',
    approved INTEGER,
    expires_at REAL,
    result_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(run_id,position)
);
CREATE TABLE IF NOT EXISTS model_calls (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER REFERENCES conversations(id),
    run_ref TEXT NOT NULL DEFAULT '',
    purpose TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    retries INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
