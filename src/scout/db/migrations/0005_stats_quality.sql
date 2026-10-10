-- 0005_stats_quality.sql —— 统计数据的可信度与时效
--
-- 起因：页面上出现过"转发是点赞的 8 倍""评论多于点赞"这种数字。
-- 查证结论是：**这些数字就是抖音接口返回的，我们没有算错**。
-- 但两个真问题暴露出来了：
--   1. 页面把一个可能过期的数字当成"当前事实"展示，却不标时效
--   2. 反常数字没有校验，直接当正常数据用
--
-- 所以加两样东西：
--   stats_anomaly     —— 合理性校验结果（空 = 正常）
--   stats_fetched_at  —— 已有，记录这组统计是什么时候取的

ALTER TABLE works ADD COLUMN stats_anomaly TEXT NOT NULL DEFAULT '';

-- 快查"哪些作品的统计已经过时"
CREATE INDEX IF NOT EXISTS idx_works_stats_age ON works(stats_fetched_at);
