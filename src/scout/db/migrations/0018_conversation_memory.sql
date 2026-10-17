-- 0018_conversation_memory.sql —— 长会话压缩摘要（2026-10-17）
--
-- 只存"较早对话"的压缩结果；原文仍完整保留在 conversation_messages，
-- 摘要失真时可按 conversation_id + turns 回溯原文。

CREATE TABLE IF NOT EXISTS conversation_memory (
    conversation_id INTEGER PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
    summary         TEXT NOT NULL,
    turns           INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT NOT NULL
);
