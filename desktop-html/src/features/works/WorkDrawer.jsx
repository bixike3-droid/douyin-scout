import React, { useEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'motion/react';
import {
  ArrowUpRight, ChevronLeft, ChevronRight, Download, Loader2, MessageSquare, PencilLine,
  RotateCcw, Send, Trash2, X,
} from 'lucide-react';
import { api, dateLabel, size, withToken } from '../../api.js';
import { Button, Separator } from '../../ui/kit.jsx';
import { IconButton } from '../../ui/media.jsx';

const value = (input) => (input === null || input === undefined ? '—' : typeof input === 'number' ? input.toLocaleString('zh-CN') : input);
const duration = (ms) => {
  if (!ms) return '—';
  const total = Math.round(ms / 1000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
};

/* ------------------------------------------------------------ 抽屉外壳 */

export function WorkDrawer({ row, onClose, notify, onEditMetrics, onCollectComments, busy, onSendToTeam, sendingToTeam }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const listener = (event) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', listener);
    return () => document.removeEventListener('keydown', listener);
  }, [onClose]);

  useEffect(() => {
    let live = true;
    setDetail(null);
    setError('');
    api(`/works/${encodeURIComponent(row.aweme_id)}`)
      .then((data) => { if (live) setDetail(data); })
      .catch((problem) => { if (live) setError(problem.message); });
    return () => { live = false; };
  }, [row.aweme_id, attempt]);

  const work = detail?.work;

  async function save() {
    setSaving(true);
    try {
      await api(`/works/${encodeURIComponent(row.aweme_id)}/save`, { method: 'POST' });
      setDetail(await api(`/works/${encodeURIComponent(row.aweme_id)}`));
      notify('已保存到本机');
    } catch (problem) {
      notify(problem.message);
    } finally {
      setSaving(false);
    }
  }

  async function forget() {
    try {
      await api(`/works/${encodeURIComponent(row.aweme_id)}/save`, { method: 'DELETE' });
      setDetail(await api(`/works/${encodeURIComponent(row.aweme_id)}`));
    } catch (problem) {
      notify(problem.message);
    }
  }

  return (
    <div className="fixed inset-0 z-[100] flex justify-end">
      <motion.div
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        transition={{ duration: 0.18 }}
        className="absolute inset-x-0 bottom-0 top-[44px] bg-[var(--overlay)] backdrop-blur-[2px]"
        onMouseDown={onClose}
      />
      <motion.aside
        role="dialog" aria-modal="true" aria-label={row.description || '作品详情'}
        initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
        transition={{ type: 'spring', stiffness: 340, damping: 36 }}
        className="relative flex h-full w-[min(600px,100%)] flex-col border-l border-line bg-bg shadow-[-30px_0_80px_rgb(10_14_24/0.18)]"
      >
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <p className="text-[10.5px] uppercase tracking-[0.5px] text-muted">
              {work?.is_mine ? '本人作品' : '作品'} · {row.aweme_id}
            </p>
            <h2 className="mt-1.5 line-clamp-2 text-[14px] font-[560] leading-relaxed text-text">
              {work?.description || row.description || '未命名作品'}
            </h2>
          </div>
          <IconButton icon={X} label="关闭" onClick={onClose} />
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {error ? (
            <div className="rounded-[12px] border border-line bg-subtle/50 px-4 py-6 text-center">
              <p className="text-[12.5px] text-text">{error}</p>
              <div className="mt-3 flex justify-center gap-2">
                <Button variant="secondary" size="sm" onClick={() => setAttempt((n) => n + 1)}>
                  <RotateCcw size={13} /> 重试
                </Button>
                {row.share_url ? (
                  <Button variant="ghost" size="sm" onClick={() => window.open(row.share_url, '_blank', 'noopener')}>
                    <ArrowUpRight size={13} /> 打开原页
                  </Button>
                ) : null}
              </div>
            </div>
          ) : !detail ? (
            <div className="grid h-[240px] place-items-center rounded-[12px] border border-line bg-subtle/40 text-muted">
              <Loader2 size={18} className="animate-spin" />
            </div>
          ) : (
            <>
              {work.media_kind === 'video' && detail.urls.media ? (
                <VideoStage key={`${work.aweme_id}-${attempt}`} src={withToken(detail.urls.media)}
                            poster={withToken(detail.urls.cover)} shareUrl={work.share_url} />
              ) : work.media_kind === 'image' ? (
                <Gallery images={detail.urls.images.map(withToken)} />
              ) : (
                <div className="grid h-[180px] place-items-center rounded-[12px] border border-line bg-subtle/40 text-[12px] text-muted">
                  这条作品没有可播放的媒体
                </div>
              )}

              <div className="mt-4 flex flex-wrap items-center gap-2">
                {work.media_kind === 'video' ? (
                  detail.saved ? (
                    <Button variant="secondary" size="sm" onClick={forget}>
                      <Trash2 size={13} /> 删除本机副本 · {size(detail.saved.bytes)}
                    </Button>
                  ) : (
                    <Button variant="secondary" size="sm" disabled={saving} onClick={save}>
                      {saving ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                      {saving ? '正在保存…' : '保存到本机'}
                    </Button>
                  )
                ) : null}
                {onSendToTeam ? (
                  <Button variant="secondary" size="sm" disabled={sendingToTeam} onClick={onSendToTeam}>
                    {sendingToTeam ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
                    {sendingToTeam ? '正在交给团队…' : '交给团队'}
                  </Button>
                ) : null}
                {work.share_url ? (
                  <Button variant="ghost" size="sm" onClick={() => window.open(work.share_url, '_blank', 'noopener')}>
                    <ArrowUpRight size={13} /> 打开原页
                  </Button>
                ) : null}
                {work.is_mine ? (
                  <>
                    <Button variant="ghost" size="sm" onClick={onEditMetrics}>
                      <PencilLine size={13} /> 补录指标
                    </Button>
                    <Button variant="ghost" size="sm" disabled={busy} onClick={onCollectComments}>
                      <MessageSquare size={13} /> 同步评论
                    </Button>
                  </>
                ) : null}
              </div>

              <Separator className="my-5" />
              <Metrics work={work} />

              <Separator className="my-5" />
              <Likers data={detail.likers} />

              {work.hashtags?.length ? (
                <>
                  <Separator className="my-5" />
                  <div className="flex flex-wrap gap-1.5">
                    {work.hashtags.map((tag) => (
                      <span key={tag} className="rounded-full border border-line px-2 py-0.5 text-[11px] text-secondary">
                        #{tag}
                      </span>
                    ))}
                  </div>
                </>
              ) : null}
            </>
          )}
        </div>
      </motion.aside>
    </div>
  );
}

/* ------------------------------------------------------------ 播放 / 画廊 */

function VideoStage({ src, poster, shareUrl }) {
  const [state, setState] = useState('loading');
  return (
    <div className="relative overflow-hidden rounded-[12px] border border-line bg-black">
      {state === 'loading' ? (
        <div className="absolute inset-0 grid place-items-center bg-black/60 text-[11.5px] text-white/80">
          <span className="inline-flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> 正在准备播放…</span>
        </div>
      ) : null}
      {state === 'failed' ? (
        <div className="absolute inset-0 z-10 grid place-items-center gap-2 bg-[#0b0f17]/90 px-6 text-center">
          <p className="text-[12px] leading-relaxed text-white/85">
            播放地址已失效或源站不可用。<br />重新打开可以再试一次。
          </p>
          {shareUrl ? (
            <button type="button" onClick={() => window.open(shareUrl, '_blank', 'noopener')}
                    className="mt-1 text-[12px] text-white underline underline-offset-4">
              在浏览器打开原页
            </button>
          ) : null}
        </div>
      ) : null}
      <video
        src={src} poster={poster || undefined} controls playsInline preload="metadata"
        className="max-h-[46vh] w-full bg-black object-contain"
        onCanPlay={() => setState('ready')}
        onError={() => setState('failed')}
      />
    </div>
  );
}

function Gallery({ images }) {
  const [index, setIndex] = useState(0);
  const trackRef = useRef(null);
  const total = images.length;

  const go = (next) => {
    const bounded = Math.min(Math.max(next, 0), total - 1);
    setIndex(bounded);
    const track = trackRef.current;
    if (track) track.scrollTo({ left: bounded * track.clientWidth, behavior: 'smooth' });
  };

  useEffect(() => {
    const listener = (event) => {
      if (event.key === 'ArrowLeft') go(index - 1);
      if (event.key === 'ArrowRight') go(index + 1);
    };
    window.addEventListener('keydown', listener);
    return () => window.removeEventListener('keydown', listener);
  }, [index, total]);

  useEffect(() => {
    const track = trackRef.current;
    if (!track) return undefined;
    let frame = 0;
    const onScroll = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const width = track.clientWidth || 1;
        setIndex(Math.min(total - 1, Math.max(0, Math.round(track.scrollLeft / width))));
      });
    };
    track.addEventListener('scroll', onScroll, { passive: true });
    return () => { track.removeEventListener('scroll', onScroll); cancelAnimationFrame(frame); };
  }, [total]);

  return (
    <div className="relative overflow-hidden rounded-[12px] border border-line bg-subtle/40">
      <div ref={trackRef} className="flex snap-x snap-mandatory overflow-x-auto scroll-smooth [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {images.map((url, position) => (
          <div key={url} className="grid h-[46vh] w-full shrink-0 snap-center place-items-center p-2">
            <img src={url} alt={`第 ${position + 1} 张`} loading={position < 2 ? 'eager' : 'lazy'}
                 className="max-h-full max-w-full rounded-[8px] object-contain" />
          </div>
        ))}
      </div>
      {total > 1 ? (
        <>
          <button type="button" aria-label="上一张" disabled={index === 0} onClick={() => go(index - 1)}
                  className="absolute left-2 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-full bg-black/45 text-white transition-opacity disabled:opacity-0">
            <ChevronLeft size={16} />
          </button>
          <button type="button" aria-label="下一张" disabled={index === total - 1} onClick={() => go(index + 1)}
                  className="absolute right-2 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-full bg-black/45 text-white transition-opacity disabled:opacity-0">
            <ChevronRight size={16} />
          </button>
          <span className="absolute bottom-2 right-3 rounded-full bg-black/50 px-2 py-0.5 text-[10.5px] text-white">
            {index + 1} / {total}
          </span>
        </>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------ 指标 / 互动人 */

function Metrics({ work }) {
  const cells = useMemo(() => ([
    ['播放', value(work.play_count)], ['点赞', value(work.digg_count)],
    ['评论', value(work.comment_count)], ['分享', value(work.share_count)],
    ['收藏', value(work.collect_count)], ['时长', duration(work.duration_ms)],
  ]), [work]);

  return (
    <div>
      <div className="grid grid-cols-3 gap-2.5">
        {cells.map(([label, text], position) => (
          <motion.div
            key={label}
            initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.04 * position, duration: 0.28, ease: 'easeOut' }}
            className="rounded-[10px] border border-line bg-subtle/40 px-3 py-2.5"
          >
            <p className="text-[10.5px] text-muted">{label}</p>
            <p className="mt-1 text-[16px] font-[560] tabular-nums tracking-[-0.3px] text-text">{text}</p>
          </motion.div>
        ))}
      </div>
      <dl className="mt-3.5 grid grid-cols-[72px_1fr] gap-x-4 gap-y-2 text-[11.5px]">
        <dt className="text-muted">发布时间</dt>
        <dd className="text-text">{work.create_time ? dateLabel(work.create_time * 1000) : '—'}</dd>
        <dt className="text-muted">音乐</dt>
        <dd className="break-words text-text">{work.music_title || '—'}</dd>
        <dt className="text-muted">数据时间</dt>
        <dd className="text-text">{work.stats_fetched_at ? dateLabel(work.stats_fetched_at) : '—'}</dd>
      </dl>
    </div>
  );
}

function Likers({ data }) {
  if (!data?.total) {
    return <p className="text-[11.5px] text-muted">还没有采集到这条作品的点赞人。</p>;
  }
  return (
    <div>
      <div className="mb-2.5 flex items-baseline justify-between">
        <h3 className="text-[12px] font-medium text-text">已采点赞人</h3>
        <span className="text-[11px] text-muted">共 {value(data.total)} 人</span>
      </div>
      <ul className="flex flex-wrap gap-1.5">
        {data.items.map((item, position) => (
          <motion.li
            key={item.sec_uid}
            initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: Math.min(position, 12) * 0.02, duration: 0.2 }}
            title={item.sec_uid}
            className="inline-flex max-w-[180px] items-center gap-1.5 rounded-full border border-line bg-bg px-2 py-1 text-[11px]"
          >
            {item.avatar_url ? (
              <img src={item.avatar_url} alt="" className="h-4 w-4 rounded-full object-cover" loading="lazy" />
            ) : (
              <span className="grid h-4 w-4 place-items-center rounded-full bg-subtle text-[8.5px] text-muted">
                {(item.nickname || '?')[0]}
              </span>
            )}
            <span className="truncate text-secondary">{item.nickname || item.sec_uid}</span>
          </motion.li>
        ))}
      </ul>
      {data.total > data.items.length ? (
        <p className="mt-2 text-[11px] text-muted">仅展示最近 {data.items.length} 位</p>
      ) : null}
    </div>
  );
}

export default WorkDrawer;
