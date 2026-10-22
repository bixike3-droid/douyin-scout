-- 补列：同 0026，早期版本的 0025 在执行后又被追加了 tools_digest，
-- 已记过 0025 的库不会重跑，这里单独补一次。
-- 新库已有该列，会报 duplicate column name，迁移器视为已完成。
ALTER TABLE codex_sessions ADD COLUMN tools_digest TEXT NOT NULL DEFAULT '';
