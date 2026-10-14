CREATE TABLE IF NOT EXISTS collection_coverage (
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    state TEXT NOT NULL,
    item_count INTEGER NOT NULL DEFAULT 0,
    item_limit INTEGER NOT NULL DEFAULT 0,
    next_cursor INTEGER NOT NULL DEFAULT 0,
    pages INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    hint TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(kind, target)
);

CREATE TABLE IF NOT EXISTS collection_items (
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    item_id TEXT NOT NULL,
    PRIMARY KEY(kind, target, item_id)
);

-- One observable user/work relationship, independent of notification source.
CREATE VIEW IF NOT EXISTS v_valid_interactions AS
SELECT le.sec_uid, le.aweme_id,
       MIN(le.discovered_at) AS first_observed_at,
       MAX(le.last_confirmed_at) AS last_confirmed_at
FROM like_edges le
JOIN users u ON u.sec_uid=le.sec_uid
JOIN works w ON w.aweme_id=le.aweme_id
WHERE le.sec_uid<>'' AND le.aweme_id<>'' AND w.is_mine=1
  AND le.notice_kind='digg' AND le.is_stale=0
  AND le.sec_uid<>w.author_sec_uid
GROUP BY le.sec_uid, le.aweme_id;

CREATE VIEW IF NOT EXISTS v_audience_quality AS
SELECT u.sec_uid,
       COALESCE(i.interaction_works,0) AS interaction_works,
       COALESCE(s.sample_count,0) AS sample_count,
       CASE WHEN COALESCE(i.interaction_works,0)>=2 THEN '多作品互动'
            WHEN COALESCE(i.interaction_works,0)=1 THEN '单作品互动'
            ELSE '无有效关联' END AS priority_reason,
       CASE WHEN COALESCE(i.interaction_works,0)=0 THEN '暂不纳入分析'
            WHEN TRIM(u.nickname)='' OR u.follower_count IS NULL OR u.follower_count<0 THEN '资料待补'
            ELSE '基础资料可用' END AS data_status,
       (CASE WHEN COALESCE(i.interaction_works,0)=0 THEN '缺少当前本人作品的有效互动关联；' ELSE '' END ||
        CASE WHEN TRIM(u.nickname)='' THEN '昵称缺失；' ELSE '' END ||
        CASE WHEN u.follower_count IS NULL THEN '粉丝数未知；' ELSE '' END ||
        CASE WHEN u.follower_count<0 THEN '粉丝数异常，按未知处理；' ELSE '' END ||
        CASE WHEN COALESCE(s.sample_count,0)=0 THEN '暂无作品样本，不能据此判断观众价值；' ELSE '' END) AS quality_reason
FROM users u
LEFT JOIN (SELECT sec_uid, COUNT(*) AS interaction_works FROM v_valid_interactions GROUP BY sec_uid) i
  ON i.sec_uid=u.sec_uid
LEFT JOIN (
    SELECT l.sec_uid, COUNT(*) AS sample_count FROM user_work_listings l
    JOIN works w ON w.aweme_id=l.aweme_id
    WHERE w.author_sec_uid=l.sec_uid AND w.author_sec_uid<>'' GROUP BY l.sec_uid
) s ON s.sec_uid=u.sec_uid;
