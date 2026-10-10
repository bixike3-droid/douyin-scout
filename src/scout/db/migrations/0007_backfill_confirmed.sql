-- 0007_backfill_confirmed.sql —— 回填"点赞边确认时间"
--
-- 背景：0006 给 like_edges 加了 last_confirmed_at（默认空串），
-- 用来判断"这条边是不是很久没被再次确认了"（对方可能取消点赞）。
--
-- 问题是：**已有数据的这个字段全是空的**，于是第一次清理会把
-- 全部 28 条边都判成陈旧 —— 这是假信号，会让人误以为所有人都取消了点赞。
--
-- 正确做法：把已有边的 last_confirmed_at 回填成 discovered_at
-- （它被采集到的那一刻，就算"确认"过一次）。
-- 这样陈旧判断从"真实的时间点"开始算，而不是从"加字段的那一刻"。

UPDATE like_edges
SET last_confirmed_at = discovered_at
WHERE (last_confirmed_at IS NULL OR last_confirmed_at = '')
  AND discovered_at IS NOT NULL
  AND discovered_at != '';
