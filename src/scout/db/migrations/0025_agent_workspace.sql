CREATE TABLE IF NOT EXISTS workspace_artifacts (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    run_id INTEGER REFERENCES chat_runs(id),
    message_id INTEGER REFERENCES conversation_messages(id),
    relative_path TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    size INTEGER NOT NULL,
    modified_ns INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(conversation_id,relative_path)
);
CREATE TABLE IF NOT EXISTS conversation_branches (
    conversation_id INTEGER PRIMARY KEY REFERENCES conversations(id),
    parent_conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    attachment_map_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
ALTER TABLE codex_sessions ADD COLUMN tools_digest TEXT NOT NULL DEFAULT '';
