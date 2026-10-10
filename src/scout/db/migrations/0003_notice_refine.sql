-- 0003_notice_refine.sql —— 点赞边补充字段
--
-- 实测发现（raw_id 407，真实接口 /aweme/v1/web/notice/）：
--   notice_list_v2[i].digg.from_user[]  才是点赞人，每个都带 sec_uid 和完整画像字段
--   notice_list_v2[i].digg.merge_count  这条通知聚合了多少人
--   notice_list_v2[i].digg.has_digg_list 为 true 时，from_user 只给了一部分，
--                                        需要点开「赞过的人」才能拿全
--
-- 记下这两个字段的意义：能区分"已经拿全了"和"还缺人"，
-- 从而只对真正缺人的条目做展开，不浪费配额。

ALTER TABLE like_edges ADD COLUMN merge_count       INTEGER;
ALTER TABLE like_edges ADD COLUMN has_more_likers   INTEGER NOT NULL DEFAULT 0;
ALTER TABLE like_edges ADD COLUMN notice_type       INTEGER;
ALTER TABLE like_edges ADD COLUMN source_url        TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_like_edges_incomplete
    ON like_edges(has_more_likers, aweme_id);

-- 需要补采的点赞边：聚合数大于实际拿到的人数
CREATE VIEW IF NOT EXISTS v_like_edges_incomplete AS
SELECT
    aweme_id,
    MAX(merge_count)  AS expected,
    COUNT(*)          AS have,
    MAX(notice_id)    AS notice_id
FROM like_edges
WHERE has_more_likers = 1
GROUP BY aweme_id
HAVING expected IS NULL OR expected > have;
