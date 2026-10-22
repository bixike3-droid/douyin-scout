import React, { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { X, FileText, FileArchive, Film, Download, Copy, Check, ChevronDown, ChevronRight, Loader2, Image as ImageIcon, CircleAlert, Search, Play, ZoomIn, ZoomOut, ArrowUpRight } from 'lucide-react';
import { api, fileUrl, uploadUrl, size } from './api.js';

export function IconButton({ icon: Icon, label, className = '', ...props }) {
  return <button className={`icon-button ${className}`} title={label} aria-label={label} {...props}><Icon size={17} strokeWidth={1.65} /></button>;
}
export function Modal({ title, subtitle, children, onClose, className = '', actions }) {
  useEffect(() => { const listener = e => e.key === 'Escape' && onClose(); document.addEventListener('keydown', listener); return () => document.removeEventListener('keydown', listener); }, [onClose]);
  return <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && onClose()}><section role="dialog" aria-modal="true" aria-label={title} className={`modal ${className}`}><header className="modal-header"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div><div className="row">{actions}<IconButton icon={X} label="关闭" onClick={onClose} /></div></header>{children}</section></div>;
}
export function FileTile({ item, onOpen, onRemove, compact = false }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [item.id, item.status]);
  const kind = item.kind || (/\.(jpg|jpeg|png|webp|gif|heic|avif)$/i.test(item.name) ? 'image' : /\.(mp4|mov|mkv|webm)$/i.test(item.name) ? 'video' : /\.(zip|7z|rar|tar|gz)$/i.test(item.name) ? 'archive' : 'document');
  const Icon = kind === 'archive' ? FileArchive : kind === 'video' ? Film : kind === 'image' ? ImageIcon : FileText;
  const thumbnail = item.upload ? uploadUrl(item.id) : fileUrl(item.id, { variant: 'thumbnail', ...(item.asset_id ? { asset_id: item.asset_id } : {}) });
  const media = kind === 'image' || kind === 'video';
  return <div className={`file-tile ${media ? 'media-tile' : ''} ${compact ? 'compact' : ''}`}>
    <button className="file-main" onClick={() => onOpen?.({ ...item, kind })} title={item.name}>
      {media && !failed && item.id ? <div className="file-thumbnail"><img loading="lazy" src={item.localUrl || thumbnail} onError={() => setFailed(true)} alt={item.name} />{kind === 'video' && <span className="play-badge"><Play size={13} fill="currentColor" /></span>}</div> : <span className={`file-symbol ${kind}`}><Icon size={23} strokeWidth={1.4} /></span>}
      <span className="file-info"><strong>{item.name?.split(/[\\/]/).pop()}</strong><small>{item.status === 'uploading' ? `正在添加 ${item.progress || 0}%` : item.status === 'error' ? '添加失败' : `${item.name?.split('.').pop()?.toUpperCase() || 'FILE'} · ${size(item.size || 0)}`}</small></span>
      {item.status === 'uploading' && <span className="upload-progress" style={{ width: `${item.progress || 0}%` }} />}
    </button>
    {onRemove && <button className="file-remove" aria-label={`移除 ${item.name}`} onClick={onRemove}><X size={12} /></button>}
  </div>;
}
export function FilePreview({ item, onClose, onGallery }) {
  const [text, setText] = useState(null), [error, setError] = useState(''), [zoom, setZoom] = useState(1);
  const [next, setNext] = useState(0), [more, setMore] = useState(false), [compatible, setCompatible] = useState(false), [videoError, setVideoError] = useState(false);
  const src = item.upload ? uploadUrl(item.id, false) : fileUrl(item.id, { ...(item.asset_id ? { asset_id: item.asset_id } : {}), ...(compatible ? { variant: 'web-video' } : {}) });
  const isPdf = /\.pdf$/i.test(item.name), isText = /\.(txt|csv|tsv|md|json|yaml|yml|log|py|js|ts|html|css|xml|sql|rtf)$/i.test(item.name);
  async function read(offset = 0) {
    try {
      const query = new URLSearchParams({ offset, ...(item.asset_id ? { asset_id: item.asset_id } : {}) });
      const result = await api(`/files/${item.id}/text?${query}`);
      setText(previous => offset ? previous + result.text : result.text); setNext(result.next_offset); setMore(result.has_more);
    } catch (e) { setError(e.message); }
  }
  useEffect(() => { if (isText && !item.upload) read(); }, [item.id]);
  return <Modal title={item.name?.split(/[\\/]/).pop()} subtitle={`${size(item.size || 0)}${item.asset_id ? ` · ${item.asset_id}` : ''}`} onClose={onClose} className="preview-modal" actions={<>
    {item.kind === 'image' && <><IconButton icon={ZoomOut} label="缩小" onClick={() => setZoom(x => Math.max(.25, x - .25))} /><span className="zoom-label">{Math.round(zoom * 100)}%</span><IconButton icon={ZoomIn} label="放大" onClick={() => setZoom(x => x + .25)} /></>}
    {!item.upload && <a className="icon-button" title="保存文件" href={fileUrl(item.id, { download: true, ...(item.asset_id ? { asset_id: item.asset_id } : {}) })} download><Download size={17} /></a>}
  </>}>
    <div className={`preview-stage ${item.kind === 'image' || item.kind === 'video' ? 'media-stage' : ''}`}>
      {item.kind === 'image' ? <img className="preview-image" src={src} style={{ maxWidth: zoom === 1 ? '100%' : 'none', width: zoom === 1 ? 'auto' : `${zoom * 85}%` }} /> :
       item.kind === 'video' ? <div className="video-stage">{!videoError ? <video key={src} src={src} controls autoPlay preload="metadata" onError={() => setVideoError(true)} /> : <div className="empty-state"><Film size={35} /><h3>当前视频编码需要兼容预览</h3><p>原始文件已保留，可以生成浏览器可播放的版本。</p><button className="primary" onClick={() => { setCompatible(true); setVideoError(false); }}>生成兼容预览</button></div>}{compatible && <p className="muted center">首次准备兼容预览可能需要一些时间</p>}</div> :
       item.kind === 'archive' ? <div className="empty-state"><FileArchive size={42} strokeWidth={1.2} /><h3>浏览压缩包中的素材</h3><p>查看完整目录、缩略图，以及每项素材的观察进度。</p>{!item.upload && <button className="primary" onClick={() => { onClose(); onGallery(item); }}>打开素材工作台 <ArrowUpRight size={15} /></button>}</div> :
       isPdf ? <iframe title="PDF 预览" src={src} /> :
       isText && !item.upload ? <div className="text-preview">{error ? <p className="error-text">{error}</p> : text === null ? <Loader2 className="spin" /> : <><pre>{text}</pre>{more && <button className="secondary" onClick={() => read(next)}>继续读取</button>}</>}</div> :
       <div className="empty-state"><FileText size={42} strokeWidth={1.2} /><h3>{item.name?.split('.').pop()?.toUpperCase()} 文件</h3><p>文件已保留，可以交给源镜继续读取和分析。</p>{!item.upload && <a className="primary" href={fileUrl(item.id, { download: true })} download><Download size={16} />保存文件</a>}</div>}
    </div>
  </Modal>;
}
export function Gallery({ item, onClose, job, startJob, onOpen, onAnalyze }) {
  const [data, setData] = useState(null), [query, setQuery] = useState(''), [kind, setKind] = useState(''), [error, setError] = useState('');
  async function load(append = false) {
    try {
      const offset = append ? data?.rows?.length || 0 : 0;
      const result = await api(`/attachments/${item.id}/assets?${new URLSearchParams({ query, kind, offset, count: 60 })}`);
      setData(previous => ({ ...result, rows: append ? [...previous.rows, ...result.rows] : result.rows }));
    } catch (e) { setError(e.message); }
  }
  useEffect(() => { const timer = setTimeout(() => load(), 180); return () => clearTimeout(timer); }, [item.id, query, kind]);
  useEffect(() => { if (job?.state !== 'running') { load(); return; } const timer = setInterval(() => load(), 1800); return () => clearInterval(timer); }, [job?.id, job?.state, query, kind]);
  const progress = data?.progress || {}, busy = job?.state === 'running';
  return <Modal title={item.name} subtitle="素材工作台" onClose={onClose} className="gallery-modal" actions={<button className="secondary" disabled={busy} onClick={() => onAnalyze(data?.attachment || item)}>交给源镜分析</button>}>
    <div className="gallery-summary"><div><b>{progress.total || 0}</b><span>项素材</span></div><div><b>{progress.images || 0}</b><span>图片</span></div><div><b>{progress.videos || 0}</b><span>视频</span></div><div className="coverage"><span>总览覆盖 <b>{progress.overviewed || 0} / {progress.visual_total || 0}</b></span><div className="progress-track"><i style={{ width: `${progress.visual_total ? (progress.overviewed || 0) / progress.visual_total * 100 : 0}%` }} /></div></div></div>
    <div className="gallery-toolbar"><div className="segmented">{[['', '全部'], ['image', '图片'], ['video', '视频'], ['text', '文档']].map(([value, label]) => <button key={value} className={kind === value ? 'selected' : ''} onClick={() => setKind(value)}>{label}</button>)}</div><label className="search-field"><Search size={15} /><input placeholder="搜索文件名或画面内容" value={query} onChange={e => setQuery(e.target.value)} /></label></div>
    <div className="gallery-body">{error && <p className="error-text">{error}</p>}{data && !data.rows.length && !progress.thumbnails ? <div className="empty-state"><ImageIcon size={38} strokeWidth={1.3} /><h3>准备完整的素材目录</h3><p>建立缩略图后，可以逐项查看图片和视频。</p><button className="primary" disabled={busy} onClick={() => startJob('gallery', { attachment_id: item.id, conversation_id: data.attachment.conversation_id })}>{busy ? <><Loader2 size={15} className="spin" />正在建立缩略图</> : '建立素材缩略图'}</button></div> : <div className="asset-grid">{data?.rows.filter(a => a.state !== 'directory').map(asset => <button className="asset-card" key={asset.asset_id} onClick={() => onOpen({ ...asset, id: item.id, asset_id: asset.asset_id, kind: asset.kind })}><div className="asset-thumbnail">{asset.thumbnail_path ? <img src={fileUrl(item.id, { asset_id: asset.asset_id, variant: 'thumbnail' })} loading="lazy" /> : <span>{asset.kind === 'video' ? <Film /> : <ImageIcon />}</span>}{asset.kind === 'video' && <span className="play-badge"><Play size={15} fill="currentColor" /></span>}<small>{asset.asset_id}</small></div><strong>{asset.name.split(/[\\/]/).pop()}</strong><p>{asset.observation || (asset.state === 'blocked' ? '暂不可读取' : asset.thumbnail_path ? '可查看原件' : '等待生成缩略图')}</p></button>)}</div>}{data?.rows.length < data?.total && <button className="load-more secondary" onClick={() => load(true)}>继续加载 · {data.rows.length} / {data.total}</button>}</div>
    <footer className="modal-footer"><span>{busy ? job.message : `缩略图 ${progress.thumbnails || 0}/${progress.visual_total || 0} · 原件细看 ${progress.inspected || 0} · 失败 ${progress.failed || 0}`}</span><span>总览与原图细看分别记录</span></footer>
  </Modal>;
}
function Diagram({ code }) {
  const element = useRef(null), [error, setError] = useState(false);
  useEffect(() => {
    let cancelled = false;
    async function render() {
      if (!window.mermaid) await new Promise((resolve, reject) => { const script = document.createElement('script'); script.src = '/mermaid.js'; script.onload = resolve; script.onerror = reject; document.head.appendChild(script); });
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
  return <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
    code: ({ className, children, ...props }) => className === 'language-mermaid' ? <Diagram code={String(children)} /> : <code className={className} {...props}>{children}</code>,
    a: ({ href, children }) => <a href={/^https?:\/\//i.test(href || '') ? href : '#'} rel="noreferrer" target="_blank">{children}</a>,
  }}>{text}</ReactMarkdown>;
}
export function parseChoices(content) {
  let questions = [];
  const text = (content || '').replace(/```choices\s*([\s\S]*?)```/g, (_, json) => { try { questions = JSON.parse(json).questions || []; } catch {} return ''; });
  return { text, questions };
}
export function Choices({ questions, onSend }) {
  const [selected, setSelected] = useState({}), [done, setDone] = useState(false);
  if (done) return null;
  return <div className="choices">{questions.map((question, index) => <div key={index}><span>{question.title}</span><div className="choice-options">{question.options?.map(option => <button key={option} className={selected[index]?.includes(option) ? 'selected' : ''} onClick={() => setSelected(values => ({ ...values, [index]: question.multi ? (values[index]?.includes(option) ? values[index].filter(x => x !== option) : [...(values[index] || []), option]) : [option] }))}>{option}</button>)}</div></div>)}<button className="text-button" disabled={!questions.every((q, i) => selected[i]?.length)} onClick={() => { onSend(questions.map((q, i) => `${q.title}：${selected[i].join('、')}`).join('\n')); setDone(true); }}>继续 <ChevronRight size={14} /></button></div>;
}
export function Thought({ text, running }) {
  const [open, setOpen] = useState(false);
  if (!text && !running) return null;
  return <div className="thought"><button onClick={() => setOpen(!open)}>{running ? <Loader2 size={14} className="spin" /> : <Check size={14} />}{running ? '正在思考' : '思考过程'}<ChevronDown className={open ? 'rotated' : ''} size={13} /></button>{open && <div className="thought-content"><Markdown text={text || '正在整理信息…'} /></div>}</div>;
}
export function ToolSteps({ items = [], running }) {
  const [open, setOpen] = useState(false);
  if (!items.length) return null;
  const current = [...items].reverse().find(t => t.status === 'running');
  return <div className="tool-steps"><button onClick={() => setOpen(!open)}>{current ? <Loader2 size={14} className="spin" /> : <Check size={14} />}<span>{current ? `${current.name}…` : `已执行 ${items.length} 项操作`}</span><ChevronDown size={13} /></button>{open && <div className="tool-details">{items.map((item, i) => <div key={i}>{item.status === 'running' ? <Loader2 size={13} className="spin" /> : item.status === 'failed' ? <CircleAlert size={13} /> : <Check size={13} />}<div><strong>{item.name || item.tool}</strong>{item.summary && <p>{item.summary}</p>}</div></div>)}</div>}</div>;
}
export function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  return <IconButton icon={copied ? Check : Copy} label={copied ? '已复制' : '复制内容'} onClick={async () => { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1600); }} />;
}
