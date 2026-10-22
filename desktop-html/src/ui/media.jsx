import React, { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  ArrowUpRight, Check, ChevronDown, ChevronRight, CircleAlert, Copy, Download, FileArchive,
  FileText, Film, Image as ImageIcon, Loader2, Play, Search, X, ZoomIn, ZoomOut,
} from 'lucide-react';
import { api, fileUrl, size, uploadUrl } from '../api.js';
import { Badge, Button, EmptyState, Segmented, cn } from './kit.jsx';

/* ------------------------------------------------------------ 基础件 */

export function IconButton({ icon: Icon, label, className, ...rest }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      className={cn('grid h-8 w-8 place-items-center rounded-[8px] text-secondary transition-colors hover:bg-subtle hover:text-text', className)}
      {...rest}
    >
      <Icon size={17} strokeWidth={1.65} />
    </button>
  );
}

export function Modal({ title, subtitle, children, onClose, className, actions }) {
  useEffect(() => {
    const listener = (event) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', listener);
    return () => document.removeEventListener('keydown', listener);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-[#11182755] p-6 backdrop-blur-[3px]"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn('flex max-h-[calc(100dvh-80px)] w-[min(600px,100%)] flex-col overflow-hidden rounded-[16px] border border-line bg-bg shadow-[0_30px_90px_rgb(10_14_24/0.28)]', className)}
      >
        <header className="flex shrink-0 items-center justify-between gap-4 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-[13.5px] font-medium text-text">{title}</h2>
            {subtitle ? <p className="mt-1.5 text-[11px] text-muted">{subtitle}</p> : null}
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {actions}
            <IconButton icon={X} label="关闭" onClick={onClose} />
          </div>
        </header>
        {children}
      </section>
    </div>
  );
}

/* ------------------------------------------------------------ 文件卡片 */

const KIND_BY_EXT = [
  [/\.(jpg|jpeg|png|webp|gif|heic|avif)$/i, 'image'],
  [/\.(mp4|mov|mkv|webm)$/i, 'video'],
  [/\.(zip|7z|rar|tar|gz)$/i, 'archive'],
];

export function FileTile({ item, onOpen, onRemove, compact = false }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [item.id, item.status]);

  const kind = item.kind || KIND_BY_EXT.find(([pattern]) => pattern.test(item.name || ''))?.[1] || 'document';
  const Icon = kind === 'archive' ? FileArchive : kind === 'video' ? Film : kind === 'image' ? ImageIcon : FileText;
  const thumbnail = item.upload
    ? uploadUrl(item.id)
    : fileUrl(item.id, { variant: 'thumbnail', ...(item.asset_id ? { asset_id: item.asset_id } : {}) });
  const media = kind === 'image' || kind === 'video';
  const name = (item.name || '').split(/[\\/]/).pop();
  const ext = (item.name || '').split('.').pop()?.toUpperCase() || 'FILE';
  const subtitle = item.status === 'uploading'
    ? `正在添加 ${item.progress || 0}%`
    : item.status === 'error' ? '添加失败' : `${ext} · ${size(item.size || 0)}`;

  return (
    <div className={cn('group relative shrink-0 self-start', compact ? 'w-[168px]' : 'w-[220px]')}>
      <button
        type="button"
        title={name}
        onClick={() => onOpen?.({ ...item, kind })}
        className={cn(
          'relative flex w-full overflow-hidden rounded-[10px] border border-line bg-subtle text-left transition-colors hover:bg-hover',
          media ? 'block p-0' : 'items-center gap-2.5 p-2.5',
        )}
      >
        {media && !failed && item.id ? (
          <div className={cn('relative w-full overflow-hidden bg-subtle', compact ? 'h-[70px]' : 'h-[123px]')}>
            <img
              loading="lazy"
              src={item.localUrl || thumbnail}
              alt={name}
              onError={() => setFailed(true)}
              className="h-full w-full object-cover"
            />
            {kind === 'video' ? (
              <span className="absolute left-1/2 top-1/2 grid h-[26px] w-[26px] -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-black/60 text-white">
                <Play size={12} fill="currentColor" />
              </span>
            ) : null}
          </div>
        ) : (
          <span className="grid h-9 w-8 shrink-0 place-items-center rounded-[6px] bg-hover text-secondary">
            <Icon size={21} strokeWidth={1.4} />
          </span>
        )}

        <span className={cn('block min-w-0', media ? 'px-2.5 py-2' : 'flex-1')}>
          <strong className="block truncate text-[11px] font-[550] text-text">{name}</strong>
          <small className="mt-1 block truncate text-[10px] text-muted">{subtitle}</small>
        </span>

        {item.status === 'uploading' ? (
          <span className="absolute inset-x-0 bottom-0 h-[2px] bg-accent transition-[width]" style={{ width: `${item.progress || 0}%` }} />
        ) : null}
      </button>

      {onRemove ? (
        <button
          type="button"
          aria-label={`移除 ${name}`}
          onClick={onRemove}
          className="absolute -right-1.5 -top-1.5 grid h-5 w-5 place-items-center rounded-full border border-line bg-bg text-muted opacity-0 shadow-sm transition-opacity hover:text-danger group-hover:opacity-100"
        >
          <X size={11} />
        </button>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------ 文件预览 */

export function FilePreview({ item, onClose, onGallery }) {
  const [text, setText] = useState(null);
  const [error, setError] = useState('');
  const [zoom, setZoom] = useState(1);
  const [next, setNext] = useState(0);
  const [more, setMore] = useState(false);
  const [compatible, setCompatible] = useState(false);
  const [videoError, setVideoError] = useState(false);

  const src = item.upload
    ? uploadUrl(item.id, false)
    : fileUrl(item.id, { ...(item.asset_id ? { asset_id: item.asset_id } : {}), ...(compatible ? { variant: 'web-video' } : {}) });
  const isPdf = /\.pdf$/i.test(item.name);
  const isText = /\.(txt|csv|tsv|md|json|yaml|yml|log|py|js|ts|html|css|xml|sql|rtf)$/i.test(item.name);
  const name = (item.name || '').split(/[\\/]/).pop();

  async function read(offset = 0) {
    try {
      const query = new URLSearchParams({ offset, ...(item.asset_id ? { asset_id: item.asset_id } : {}) });
      const result = await api(`/files/${item.id}/text?${query}`);
      setText((previous) => (offset ? previous + result.text : result.text));
      setNext(result.next_offset);
      setMore(result.has_more);
    } catch (failure) { setError(failure.message); }
  }

  useEffect(() => { if (isText && !item.upload) read(); }, [item.id]);

  const stage = 'flex min-h-0 flex-1 items-center justify-center overflow-auto p-5';

  return (
    <Modal
      title={name}
      subtitle={`${size(item.size || 0)}${item.asset_id ? ` · ${item.asset_id}` : ''}`}
      onClose={onClose}
      className="h-[min(820px,calc(100dvh-80px))] w-[min(1120px,100%)]"
      actions={(
        <>
          {item.kind === 'image' ? (
            <>
              <IconButton icon={ZoomOut} label="缩小" onClick={() => setZoom((value) => Math.max(0.25, value - 0.25))} />
              <span className="w-9 text-center text-[11px] text-muted">{Math.round(zoom * 100)}%</span>
              <IconButton icon={ZoomIn} label="放大" onClick={() => setZoom((value) => value + 0.25)} />
            </>
          ) : null}
          {!item.upload ? (
            <a
              title="保存文件"
              aria-label="保存文件"
              href={fileUrl(item.id, { download: true, ...(item.asset_id ? { asset_id: item.asset_id } : {}) })}
              download
              className="grid h-8 w-8 place-items-center rounded-[8px] text-secondary transition-colors hover:bg-subtle hover:text-text"
            >
              <Download size={17} />
            </a>
          ) : null}
        </>
      )}
    >
      <div className={cn(stage, (item.kind === 'image' || item.kind === 'video') && 'bg-[color-mix(in_srgb,var(--sidebar)_70%,var(--bg))]')}>
        {item.kind === 'image' ? (
          <img
            className="shrink-0 object-contain shadow-[0_6px_24px_rgb(0_0_0/0.08)]"
            src={src}
            alt={name}
            style={{ maxWidth: zoom === 1 ? '100%' : 'none', width: zoom === 1 ? 'auto' : `${zoom * 85}%` }}
          />
        ) : item.kind === 'video' ? (
          <div className="flex h-full w-full flex-col items-center justify-center">
            {!videoError ? (
              <video key={src} src={src} controls autoPlay preload="metadata" onError={() => setVideoError(true)} className="max-h-full max-w-full rounded-[8px] bg-black" />
            ) : (
              <EmptyState
                icon={Film}
                title="当前视频编码需要兼容预览"
                desc="原始文件已保留，可以生成浏览器可播放的版本。"
                action={<Button onClick={() => { setCompatible(true); setVideoError(false); }}>生成兼容预览</Button>}
              />
            )}
            {compatible ? <p className="mt-2.5 text-[11px] text-muted">首次准备兼容预览可能需要一些时间</p> : null}
          </div>
        ) : item.kind === 'archive' ? (
          <EmptyState
            icon={FileArchive}
            title="浏览压缩包中的素材"
            desc="查看完整目录、缩略图，以及每项素材的观察进度。"
            action={!item.upload ? (
              <Button onClick={() => { onClose(); onGallery(item); }}>
                打开素材工作台 <ArrowUpRight size={14} />
              </Button>
            ) : null}
          />
        ) : isPdf ? (
          <iframe title="PDF 预览" src={src} className="h-full w-full rounded-[4px] border-0" />
        ) : isText && !item.upload ? (
          <div className="h-full w-full overflow-auto text-[12px]">
            {error ? <p className="text-danger">{error}</p> : text === null ? <Loader2 className="spin" /> : (
              <>
                <pre className="whitespace-pre-wrap break-words font-mono leading-[1.8] text-text">{text}</pre>
                {more ? <Button variant="secondary" size="sm" onClick={() => read(next)}>继续读取</Button> : null}
              </>
            )}
          </div>
        ) : (
          <EmptyState
            icon={FileText}
            title={`${(item.name || '').split('.').pop()?.toUpperCase() || ''} 文件`}
            desc="文件已保留，可以交给源镜继续读取和分析。"
            action={!item.upload ? (
              <a href={fileUrl(item.id, { download: true })} download className="inline-flex items-center gap-2 rounded-[9px] bg-accent px-4 py-2 text-[12.5px] text-white">
                <Download size={15} /> 保存文件
              </a>
            ) : null}
          />
        )}
      </div>
    </Modal>
  );
}

/* ---------------------------------------------------------- 素材工作台 */

export function Gallery({ item, onClose, job, startJob, onOpen, onAnalyze }) {
  const [data, setData] = useState(null);
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('');
  const [error, setError] = useState('');

  async function load(append = false) {
    try {
      const offset = append ? data?.rows?.length || 0 : 0;
      const result = await api(`/attachments/${item.id}/assets?${new URLSearchParams({ query, kind, offset, count: 60 })}`);
      setData((previous) => ({ ...result, rows: append ? [...previous.rows, ...result.rows] : result.rows }));
    } catch (failure) { setError(failure.message); }
  }

  useEffect(() => { const timer = setTimeout(() => load(), 180); return () => clearTimeout(timer); }, [item.id, query, kind]);
  useEffect(() => {
    if (job?.state !== 'running') { load(); return undefined; }
    const timer = setInterval(() => load(), 1800);
    return () => clearInterval(timer);
  }, [job?.id, job?.state, query, kind]);

  const progress = data?.progress || {};
  const busy = job?.state === 'running';

  return (
    <Modal
      title={item.name}
      subtitle="素材工作台"
      onClose={onClose}
      className="h-[calc(100dvh-80px)] w-[min(1170px,100%)]"
      actions={<Button variant="secondary" size="sm" disabled={busy} onClick={() => onAnalyze(data?.attachment || item)}>交给源镜分析</Button>}
    >
      <div className="flex shrink-0 items-center gap-8 px-6 py-4">
        {[['项素材', progress.total], ['图片', progress.images], ['视频', progress.videos]].map(([label, value]) => (
          <div key={label} className="flex items-baseline gap-1.5">
            <b className="text-[21px] font-[550] tracking-[-1px] text-text">{value || 0}</b>
            <span className="text-[11px] text-muted">{label}</span>
          </div>
        ))}
        <div className="ml-auto min-w-[200px]">
          <span className="mb-2 flex items-center justify-between text-[11px] text-muted">
            总览覆盖
            <b className="font-medium text-secondary">{progress.overviewed || 0} / {progress.visual_total || 0}</b>
          </span>
          <div className="h-[3px] overflow-hidden rounded-full bg-hover">
            <i
              className="block h-full bg-accent"
              style={{ width: `${progress.visual_total ? ((progress.overviewed || 0) / progress.visual_total) * 100 : 0}%` }}
            />
          </div>
        </div>
      </div>

      <div className="flex shrink-0 items-center justify-between gap-4 px-6 pb-4">
        <Segmented
          value={kind}
          onChange={setKind}
          options={[['', '全部'], ['image', '图片'], ['video', '视频'], ['text', '文档']]}
        />
        <label className="flex w-[260px] items-center gap-2 rounded-[9px] border border-line bg-bg px-2.5 py-2 text-muted focus-within:border-[color-mix(in_srgb,var(--accent)_55%,var(--line))]">
          <Search size={14} />
          <input
            className="w-full min-w-0 border-0 bg-transparent text-[11.5px] text-text outline-none placeholder:text-muted"
            placeholder="搜索文件名或画面内容"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-6 pb-5">
        {error ? <p className="mb-3 text-[12px] text-danger">{error}</p> : null}

        {data && !data.rows.length && !progress.thumbnails ? (
          <EmptyState
            icon={ImageIcon}
            title="准备完整的素材目录"
            desc="建立缩略图后，可以逐项查看图片和视频。"
            action={(
              <Button disabled={busy} onClick={() => startJob('gallery', { attachment_id: item.id, conversation_id: data.attachment.conversation_id })}>
                {busy ? <><Loader2 size={14} className="spin" /> 正在建立缩略图</> : '建立素材缩略图'}
              </Button>
            )}
          />
        ) : (
          <div className="grid gap-x-3.5 gap-y-5 [grid-template-columns:repeat(auto-fill,minmax(175px,1fr))]">
            {(data?.rows || []).filter((asset) => asset.state !== 'directory').map((asset) => (
              <button
                key={asset.asset_id}
                type="button"
                onClick={() => onOpen({ ...asset, id: item.id, asset_id: asset.asset_id, kind: asset.kind })}
                className="group min-w-0 text-left"
              >
                <div className="relative aspect-[3/2] overflow-hidden rounded-[8px] border border-line bg-subtle">
                  {asset.thumbnail_path ? (
                    <img
                      src={fileUrl(item.id, { asset_id: asset.asset_id, variant: 'thumbnail' })}
                      loading="lazy"
                      alt={asset.name}
                      className="h-full w-full object-cover transition-transform duration-200 group-hover:scale-[1.03]"
                    />
                  ) : (
                    <span className="grid h-full w-full place-items-center text-muted">
                      {asset.kind === 'video' ? <Film size={18} /> : <ImageIcon size={18} />}
                    </span>
                  )}
                  {asset.kind === 'video' ? (
                    <span className="absolute left-1/2 top-1/2 grid h-[26px] w-[26px] -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-black/60 text-white">
                      <Play size={12} fill="currentColor" />
                    </span>
                  ) : null}
                  <small className="absolute left-1.5 top-1.5 rounded-[4px] bg-black/55 px-1.5 py-0.5 text-[8px] text-white">{asset.asset_id}</small>
                </div>
                <strong className="mt-2 block truncate text-[11px] font-medium text-text">{asset.name.split(/[\\/]/).pop()}</strong>
                <p className="mt-1 line-clamp-2 text-[10px] leading-relaxed text-muted">
                  {asset.observation || (asset.state === 'blocked' ? '暂不可读取' : asset.thumbnail_path ? '可查看原件' : '等待生成缩略图')}
                </p>
              </button>
            ))}
          </div>
        )}

        {data?.rows?.length < data?.total ? (
          <div className="mt-4 flex justify-center">
            <Button variant="secondary" size="sm" onClick={() => load(true)}>
              继续加载 · {data.rows.length} / {data.total}
            </Button>
          </div>
        ) : null}
      </div>

      <footer className="flex shrink-0 items-center justify-between border-t border-line px-6 py-3 text-[11px] text-muted">
        <span>{busy ? job.message : `缩略图 ${progress.thumbnails || 0}/${progress.visual_total || 0} · 原件细看 ${progress.inspected || 0} · 失败 ${progress.failed || 0}`}</span>
        <span>总览与原图细看分别记录</span>
      </footer>
    </Modal>
  );
}

/* ------------------------------------------------------------ Markdown */

function Diagram({ code }) {
  const element = useRef(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function render() {
      if (!window.mermaid) {
        await new Promise((resolve, reject) => {
          const script = document.createElement('script');
          script.src = '/mermaid.js';
          script.onload = resolve;
          script.onerror = reject;
          document.head.appendChild(script);
        });
      }
      window.mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'neutral' });
      const result = await window.mermaid.render(`diagram-${crypto.randomUUID()}`, code);
      if (!cancelled && element.current) element.current.innerHTML = result.svg;
    }
    render().catch(() => !cancelled && setError(true));
    return () => { cancelled = true; };
  }, [code]);

  return error ? <pre>{code}</pre> : <div className="diagram" ref={element} />;
}

export function Markdown({ text = '' }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code: ({ className, children, ...rest }) => (
            className === 'language-mermaid' ? <Diagram code={String(children)} /> : <code className={className} {...rest}>{children}</code>
          ),
          a: ({ href, children }) => (
            <a href={/^https?:\/\//i.test(href || '') ? href : '#'} rel="noreferrer" target="_blank">{children}</a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

export function parseChoices(content) {
  let questions = [];
  const text = (content || '').replace(/```choices\s*([\s\S]*?)```/g, (_, json) => {
    try { questions = JSON.parse(json).questions || []; } catch { /* ignore */ }
    return '';
  });
  return { text, questions };
}

export function Choices({ questions, onSend }) {
  const [selected, setSelected] = useState({});
  const [done, setDone] = useState(false);
  if (done) return null;

  return (
    <div className="mt-4 max-w-[580px] rounded-[11px] border border-line p-3.5">
      {questions.map((question, index) => (
        <div key={index} className="mb-2.5">
          <span className="mb-2 block text-[11px] text-muted">{question.title}</span>
          <div className="flex flex-wrap gap-1.5">
            {(question.options || []).map((option) => {
              const active = selected[index]?.includes(option);
              return (
                <button
                  key={option}
                  type="button"
                  onClick={() => setSelected((values) => ({
                    ...values,
                    [index]: question.multi
                      ? (values[index]?.includes(option) ? values[index].filter((item) => item !== option) : [...(values[index] || []), option])
                      : [option],
                  }))}
                  className={cn(
                    'rounded-[7px] border px-2.5 py-1.5 text-left text-[12px] transition-colors',
                    active
                      ? 'border-[color-mix(in_srgb,var(--accent)_30%,var(--line))] bg-accent-soft text-accent'
                      : 'border-line text-secondary hover:bg-subtle',
                  )}
                >
                  {option}
                </button>
              );
            })}
          </div>
        </div>
      ))}
      <button
        type="button"
        disabled={!questions.every((question, index) => selected[index]?.length)}
        onClick={() => {
          onSend(questions.map((question, index) => `${question.title}：${selected[index].join('、')}`).join('\n'));
          setDone(true);
        }}
        className="ml-auto flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] text-accent transition-opacity hover:opacity-80 disabled:opacity-40"
      >
        继续 <ChevronRight size={13} />
      </button>
    </div>
  );
}

export function Thought({ text, running }) {
  const [open, setOpen] = useState(false);
  if (!text && !running) return null;

  return (
    <div className="mb-3">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 py-1 text-[11px] text-muted transition-colors hover:text-secondary"
      >
        {running ? <Loader2 size={13} className="spin" /> : <Check size={13} />}
        {running ? '正在思考' : '思考过程'}
        <ChevronDown size={12} className={cn('transition-transform duration-150', open && 'rotate-180')} />
      </button>
      {open ? (
        <div className="mt-2.5 max-h-[340px] overflow-auto border-l-2 border-line pl-3.5 text-[12px] text-secondary">
          <Markdown text={text || '正在整理信息…'} />
        </div>
      ) : null}
    </div>
  );
}

export function ToolSteps({ items = [], running }) {
  const [open, setOpen] = useState(false);
  if (!items.length) return null;

  const current = [...items].reverse().find((item) => item.status === 'running');

  return (
    <div className="my-2 mb-3.5 rounded-[9px] border border-line bg-subtle px-3.5 py-2">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 py-0.5 text-left text-[11px] text-secondary"
      >
        {current ? <Loader2 size={13} className="spin" /> : <Check size={13} />}
        <span>{current ? `${current.name}…` : `已执行 ${items.length} 项操作`}</span>
        <ChevronDown size={12} className={cn('ml-auto transition-transform duration-150', open && 'rotate-180')} />
      </button>
      {open ? (
        <div className="pt-2.5">
          {items.map((item, index) => (
            <div key={index} className="my-2 flex gap-2.5 text-muted">
              {item.status === 'running' ? <Loader2 size={12} className="spin" /> : item.status === 'failed' ? <CircleAlert size={12} /> : <Check size={12} />}
              <div className="min-w-0">
                <strong className="block text-[11px] font-medium text-secondary">{item.name || item.tool}</strong>
                {item.summary ? <p className="mt-1 text-[11px] leading-relaxed text-muted">{item.summary}</p> : null}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  return (
    <IconButton
      icon={copied ? Check : Copy}
      label={copied ? '已复制' : '复制内容'}
      className="h-6 w-6"
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1600);
      }}
    />
  );
}

export { Badge };
