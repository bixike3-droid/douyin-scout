-- 0006_retention.sql —— 数据保留策略
--
-- 起因：查了一遍数据生命周期，发现三件事：
--   1. 归档只增不减（871 个文件 88MB，全部是当天的）
--   2. request_logs / event_logs 只增不减
--   3. 有人取消点赞后，like_edges 里那条**还在** —— 数据会慢慢偏离现实
--   4. tasks 表 done 的任务永远留着
--
-- 这次加上保留策略需要的字段。
--
-- 一条重要的设计取舍：**删正文，保留元数据**。
-- raw_blobs 只占几 MB，raw/ 下的正文占 88MB。
-- 把正文删掉、但留下 sha256/url/byte_size/collected_at，
-- "曾经采过什么" 仍然可追溯，代价只有几字节。
-- 直接删 raw_blobs 行会让 works.raw_blob_id 变成悬空引用，更糟。

-- 正文已被清理的标记（空 = 正文还在）
ALTER TABLE raw_blobs ADD COLUMN pruned_at TEXT NOT NULL DEFAULT '';
ALTER TABLE raw_blobs ADD COLUMN pruned_bytes INTEGER NOT NULL DEFAULT 0;

-- 点赞边最后一次"被再次确认"的时间。
-- 采集时拿到完整名单 → 更新这个字段；
-- 太久没被确认的边说明对方可能取消点赞了。
ALTER TABLE like_edges ADD COLUMN last_confirmed_at TEXT NOT NULL DEFAULT '';
-- 陈旧标记。**只标记不删除** —— 可能是接口偶发，删了就找不回来。
ALTER TABLE like_edges ADD COLUMN is_stale INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_raw_blobs_collected ON raw_blobs(collected_at);
CREATE INDEX IF NOT EXISTS idx_like_edges_confirmed ON like_edges(last_confirmed_at);
CREATE INDEX IF NOT EXISTS idx_tasks_finished ON tasks(finished_at);
