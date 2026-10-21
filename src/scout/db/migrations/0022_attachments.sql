CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    message_id INTEGER REFERENCES conversation_messages(id),
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    size INTEGER NOT NULL,
    digest TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    text_content TEXT NOT NULL DEFAULT '',
    visuals_json TEXT NOT NULL DEFAULT '[]',
    analysis TEXT NOT NULL DEFAULT '',
    limitations TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attachments_conversation ON attachments(conversation_id,message_id);
