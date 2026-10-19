-- 0020_work_images.sql —— 图文作品（图片 + 音乐）
--
-- 抖音作品不只有视频：图文作品没有 play_addr，只有 images 列表。
-- 之前的播放卡遇到这种就只会提示"没有可用的播放地址"，这里补上图片与类型。

ALTER TABLE works ADD COLUMN images_json TEXT;
ALTER TABLE works ADD COLUMN media_type TEXT;
