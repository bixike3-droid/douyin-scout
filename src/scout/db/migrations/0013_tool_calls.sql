-- 工具调用审计：每个成员调了什么工具、参数、结果、耗时。
-- 执行器在每次调用后写入；权限拒绝也记录（denied）。
CREATE TABLE IF NOT EXISTS tool_calls(
  id INTEGER PRIMARY KEY,
  conversation_id INTEGER,
  agent TEXT NOT NULL DEFAULT '',
  tool TEXT NOT NULL,
  args_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'complete',
  summary TEXT NOT NULL DEFAULT '',
  duration_ms INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
