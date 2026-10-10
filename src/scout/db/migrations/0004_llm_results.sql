-- 0004_llm_results.sql —— AI 分析结果
--
-- 为什么要存库、而不是每次现调：
--   1. 花钱。同一个人同样输入，不该重复调用大模型。
--   2. 可对比。prompt 改了、模型换了，得能对比哪版好。
--   3. 可追溯。评分结论要能追到当时的输入和模型版本。
--
-- input_digest = 喂给模型的输入内容哈希。输入没变就不重跑；
-- 用户资料或作品变了，digest 变，自然会重新分析。

CREATE TABLE IF NOT EXISTS llm_results (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_kind       TEXT NOT NULL,          -- user | self_work
    subject_id         TEXT NOT NULL,          -- sec_uid / aweme_id
    task               TEXT NOT NULL,          -- profile | review | plan
    prompt_version     TEXT NOT NULL,          -- prompt 模板版本号
    model              TEXT NOT NULL,
    input_digest       TEXT NOT NULL,
    input_summary      TEXT NOT NULL DEFAULT '',
    output_json        TEXT NOT NULL DEFAULT '{}',
    raw_text           TEXT NOT NULL DEFAULT '',
    prompt_tokens      INTEGER,
    completion_tokens  INTEGER,
    duration_ms        INTEGER,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    UNIQUE(subject_kind, subject_id, task, prompt_version, input_digest)
);
CREATE INDEX IF NOT EXISTS idx_llm_results_subject
    ON llm_results(subject_kind, subject_id, task, created_at DESC);

-- 最近一次分析结果（面板直接读这个视图）
CREATE VIEW IF NOT EXISTS v_llm_latest AS
SELECT r.*
FROM llm_results r
JOIN (
    SELECT subject_kind, subject_id, task, MAX(created_at) AS newest
    FROM llm_results
    GROUP BY subject_kind, subject_id, task
) m
  ON m.subject_kind = r.subject_kind
 AND m.subject_id = r.subject_id
 AND m.task = r.task
 AND m.newest = r.created_at;
