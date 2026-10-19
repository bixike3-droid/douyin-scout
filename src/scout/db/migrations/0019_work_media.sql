-- 0019_work_media.sql —— 作品可直接播放的视频地址
--
-- 抖音的 play_addr 是带时效签名的 CDN 地址（几小时后过期），
-- 所以只当作「最近一次抓到的地址」缓存，过期后重新采一次即可。
-- 实际播放前会下载到本地缓存，本地文件不受签名过期影响。

ALTER TABLE works ADD COLUMN play_url TEXT;
ALTER TABLE works ADD COLUMN play_url_expires INTEGER;
