-- 热搜词条关联的代表视频与相关视频。
-- 一条视频可以出现在多个话题下，所以用关系表，不往 works 上加列。
CREATE TABLE IF NOT EXISTS hot_video_links (
    sentence_id TEXT NOT NULL,
    aweme_id    TEXT NOT NULL,
    rank        INTEGER NOT NULL DEFAULT 0,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (sentence_id, aweme_id)
);
CREATE INDEX IF NOT EXISTS idx_hot_video_links_sid ON hot_video_links(sentence_id, rank);
