-- 补列：早期版本的 0025 建表时没有 attachment_map_json，
-- 而那些库已经把 0025 记为已执行，不会重跑，这里单独补一次。
-- 新库在 0025 就已经有这列，本语句会报 duplicate column name，
-- 迁移器（migrate.migrate）把这种错误视为已完成。
ALTER TABLE conversation_branches ADD COLUMN attachment_map_json TEXT NOT NULL DEFAULT '{}';
