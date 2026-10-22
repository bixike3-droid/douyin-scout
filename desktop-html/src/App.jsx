import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { MessageSquare, SquarePen, FolderOpen, BarChart3, Users, History, Target, FileText, Settings, PanelLeftClose, PanelLeftOpen, Plus, ArrowUp, Square, Minus, X, ChevronDown, MoreHorizontal, Search, ArrowDown, Sparkles, Image as ImageIcon, Loader2, CircleAlert, Check, ArrowUpRight, RefreshCw, FolderArchive, Paperclip, Copy, ListChecks, PanelRightOpen, ExternalLink } from 'lucide-react';
import { api, authToken, nativeBridge, uploadFile, modelName, dateLabel } from './api.js';
import { IconButton, Modal, FileTile, FilePreview, Gallery, Markdown, Thought, ToolSteps, CopyButton, Choices, parseChoices } from './components.jsx';
import { Library, DataPage, Benchmarks, Reports } from './pages.jsx';
import { SettingsPage } from './settings.jsx';

const navigation = [
  ['workspace', '工作台', MessageSquare], ['library', '素材库', FolderOpen],
  ['works', '作品数据', BarChart3], ['users', '互动受众', Users],
  ['reports', '分析报告', FileText], ['benchmarks', '对标账号', Target], ['tasks', '执行记录', History],
];
const starters = [
  { icon: ImageIcon, title: '分析一组素材', text: '请帮我梳理这些素材，分析主要内容，并给出适合的使用方向。', note: '图片、视频与压缩包' },
  { icon: BarChart3, title: '复盘作品表现', text: '请结合当前账号的作品与互动数据，分析表现、受众反馈和下一步优化方向。', note: '从数据中发现线索' },
  { icon: Sparkles, title: '制定内容方案', text: '请结合企业资料、现有作品和受众信息，帮我制定一份可执行的内容传播方案。', note: '把想法变成行动' },
];

export default function App() {
  const [boot, setBoot] = useState(null), [bootError, setBootError] = useState(''), [view, setView] = useState('workspace');
  const [conversation, setConversation] = useState(null), [cid, setCid] = useState(null), [recent, setRecent] = useState([]);
  const [settings, setSettings] = useState({}), [profile, setProfile] = useState({}), [preferences, setPreferences] = useState({ theme: 'light' });
  const [job, setJob] = useState(null), [draft, setDraft] = useState(''), [uploads, setUploads] = useState([]), [native, setNative] = useState(null);
  const [collapsed, setCollapsed] = useState(false), [toast, setToast] = useState(''), [connection, setConnection] = useState('connecting');
  const [preview, setPreview] = useState(null), [gallery, setGallery] = useState(null), [dragging, setDragging] = useState(false), [historySearch, setHistorySearch] = useState('');
  const [menu, setMenu] = useState(false), [inspector, setInspector] = useState(false), [pendingSteer, setPendingSteer] = useState(false), [sending, setSending] = useState(false), [unfollowed, setUnfollowed] = useState(false);
  const currentCid = useRef(cid), jobRef = useRef(job), uploadRef = useRef(uploads), textarea = useRef(null), scroller = useRef(null), fileInput = useRef(null), follow = useRef(true), uploadQueue = useRef([]), uploadWorkers = useRef(0), toastTimer = useRef(null);
  currentCid.current = cid; jobRef.current = job; uploadRef.current = uploads;
  const busy = job?.state === 'running';
  const active = busy && job?.conversation_id === cid;
  const messages = conversation?.messages || [];
  const label = navigation.find(item => item[0] === view)?.[1] || '设置';

  const notify = useCallback(message => { setToast(String(message)); clearTimeout(toastTimer.current); toastTimer.current = setTimeout(() => setToast(''), 4200); }, []);
  const refreshRecent = useCallback(async () => { try { setRecent(await api('/conversations')); } catch (e) { notify(e.message); } }, [notify]);
  async function loadConversation(id, changeView = true) {
    setMenu(false); setInspector(false); follow.current = true;
    if (changeView) setView('workspace');
    if (!id) { setCid(null); setConversation(null); setDraft(''); api('/preferences', { method: 'PUT', body: { last_conversation: null } }).catch(() => {}); return; }
    currentCid.current = id; setCid(id); setConversation(null);
    try {
      const data = await api(`/conversations/${id}`);
      if (currentCid.current === id) setConversation(data);
      api('/preferences', { method: 'PUT', body: { last_conversation: id } }).catch(() => {});
    } catch (e) { notify(e.message); }
  }
  useEffect(() => {
    let cancelled = false;
    api('/bootstrap').then(data => {
      if (cancelled) return;
      setBoot(data); setSettings(data.settings); setProfile(data.profile); setRecent(data.conversations); setPreferences(data.preferences); setJob(data.job);
      const id = data.preferences.last_conversation || (data.job?.state === 'running' ? data.job.conversation_id : null);
      if (id) { setCid(id); currentCid.current = id; api(`/conversations/${id}`).then(value => !cancelled && setConversation(value)).catch(() => setCid(null)); }
    }).catch(e => setBootError(e.message));
    return () => { cancelled = true; };
  }, []);
  useEffect(() => {
    nativeBridge().then(bridge => {
      if (!bridge) return;
      setNative(bridge);
      bridge.filesDropped.connect(value => { try { addNative(JSON.parse(value)); } catch {} });
      bridge.dragState.connect(setDragging);
      bridge.initialFiles(value => { try { const files = JSON.parse(value); if (files.length) addNative(files); } catch {} });
    }).catch(() => {});
  }, []);
  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)');
    const apply = () => { document.documentElement.dataset.theme = preferences.theme === 'system' ? (media.matches ? 'dark' : 'light') : preferences.theme || 'light'; };
    apply(); media.addEventListener('change', apply); return () => media.removeEventListener('change', apply);
  }, [preferences.theme]);
  useEffect(() => {
    let closed = false, ws, timer;
    function connect() {
      ws = new WebSocket(`ws://${location.host}/api/events?token=${encodeURIComponent(authToken())}`);
      ws.onopen = () => setConnection('connected');
      ws.onclose = () => { if (!closed) { setConnection('reconnecting'); timer = setTimeout(connect, 1800); } };
      ws.onerror = () => ws.close();
      ws.onmessage = async message => {
        const event = JSON.parse(message.data);
        if (event.type === 'snapshot') { setJob(event.job); return; }
        setJob(previous => {
          if (!previous || (event.job_id && previous.id !== event.job_id)) {
            if (event.type !== 'started') return previous;
            previous = { id: event.job_id, kind: event.kind, conversation_id: event.conversation_id, state: 'running', tools: [], confirmations: {}, started_at: Date.now() / 1000 };
          }
          const next = { ...previous, conversation_id: event.conversation_id || previous.conversation_id };
          if (event.message) next.message = event.message;
          if (event.type === 'answer_delta') next.answer = (next.answer || '') + (event.delta || '');
          if (event.type === 'thinking') next.reasoning = (next.reasoning || '') + (event.delta || '');
          if (event.type === 'codex_ready') next.ready = event.ready;
          if (event.type === 'tool') {
            const tools = [...(previous.tools || [])].map(x => ({ ...x }));
            if (event.phase === 'start') { tools.push({ tool: event.tool, name: event.name || event.tool, status: 'running' }); next.message = `${event.name || event.tool}执行中…`; }
            if (event.phase === 'done') { const i = tools.findLastIndex(x => x.tool === event.tool && x.status === 'running'); if (i >= 0) tools[i] = { ...tools[i], status: event.ok ? 'complete' : 'failed', summary: event.summary }; next.message = event.summary || '继续处理…'; }
            next.tools = tools;
            const confirmations = { ...(previous.confirmations || {}) };
            if (event.phase === 'confirm') confirmations[event.request_id] = event;
            if (event.phase === 'confirm_done') delete confirmations[event.request_id];
            next.confirmations = confirmations;
          }
          if (event.type === 'artifacts') next.artifacts = event.artifacts;
          if (event.type === 'result' || event.type === 'error') { next.state = event.state || 'complete'; next.ready = false; }
          if (event.type === 'steer_done' && event.accepted) next.answer = '';
          return next;
        });
        if (event.type === 'steer_done') {
          setPendingSteer(false);
          if (event.accepted) {
            setDraft(value => value.trim() === event.text ? '' : value);
            if (currentCid.current === event.conversation_id) setConversation(value => value ? { ...value, messages: [...value.messages, { id: event.message_id, role: 'user', content: event.text, status: 'complete' }] } : value);
            notify('要求已追加，继续执行');
          } else notify(event.error || '追加要求未送达，输入已保留');
        }
        if (event.type === 'result' || event.type === 'error') {
          setPendingSteer(false);
          refreshRecent();
          const result = event.result || {};
          if (result.conversation) { if (event.conversation_id === currentCid.current || ['chat_fork', 'chat_compact'].includes(jobRef.current?.kind)) { setCid(result.conversation.id); currentCid.current = result.conversation.id; setConversation(result.conversation); setView('workspace'); } }
          else if (event.conversation_id && currentCid.current === event.conversation_id) api(`/conversations/${event.conversation_id}`).then(setConversation).catch(() => {});
          if (event.type === 'error') notify(event.message);
          api('/bootstrap').then(data => { setBoot(data); setSettings(data.settings); setProfile(data.profile); }).catch(() => {});
        }
      };
    }
    connect(); return () => { closed = true; clearTimeout(timer); ws?.close(); };
  }, [notify, refreshRecent]);
  useEffect(() => {
    if (follow.current && scroller.current) scroller.current.scrollTop = !messages.length && !active ? 0 : scroller.current.scrollHeight;
  }, [job?.answer, job?.reasoning, job?.tools?.length, messages.length, cid]);
  useEffect(() => {
    const handler = e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'n') { e.preventDefault(); loadConversation(null); }
      if ((e.ctrlKey || e.metaKey) && e.key === ',') { e.preventDefault(); setView('settings'); }
      if (e.key === 'Escape') { setMenu(false); }
    };
    window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler);
  }, []);
  useEffect(() => { if (textarea.current) { textarea.current.style.height = 'auto'; textarea.current.style.height = `${Math.min(180, textarea.current.scrollHeight)}px`; } }, [draft]);

  function addNative(items) { setUploads(values => [...values, ...items.map(x => ({ ...x, upload: true }))]); setView('workspace'); textarea.current?.focus(); }
  async function drainUploads() {
    while (uploadWorkers.current < 2 && uploadQueue.current.length) {
      const { file, localId } = uploadQueue.current.shift(); uploadWorkers.current++;
      uploadFile(file, progress => setUploads(values => values.map(x => x.localId === localId ? { ...x, progress } : x)))
        .then(result => setUploads(values => values.map(x => x.localId === localId ? { ...result, localId, upload: true } : x)))
        .catch(e => { setUploads(values => values.map(x => x.localId === localId ? { ...x, status: 'error' } : x)); notify(e.message); })
        .finally(() => { uploadWorkers.current--; drainUploads(); });
    }
  }
  function addBrowserFiles(files) {
    const selected = [...files].map(file => { const localId = crypto.randomUUID(); uploadQueue.current.push({ file, localId }); return { localId, name: file.name, size: file.size, upload: true, status: 'uploading', progress: 0 }; });
    setUploads(values => [...values, ...selected]); setView('workspace'); drainUploads();
  }
  function removeUpload(item) {
    if (item.status === 'uploading') { notify('文件添加完成后可移除'); return; }
    setUploads(values => values.filter(x => x !== item)); if (item.id) api(`/uploads/${item.id}`, { method: 'DELETE' }).catch(() => {});
  }
  async function pickFiles() {
    if (native) native.pickFiles(value => { try { addNative(JSON.parse(value)); } catch {} });
    else fileInput.current?.click();
  }
  async function startJob(kind, options = {}) {
    try {
      const result = await api('/jobs', { method: 'POST', body: { kind, options } }); setJob(previous => previous?.id === result.id ? { ...result, ...previous } : result);
      const current = await api('/job'); setJob(current);
      if (current?.state !== 'running' && current?.conversation_id && ['chat', 'chat_fork', 'chat_compact'].includes(kind)) { const data = await api(`/conversations/${current.conversation_id}`); setCid(data.id); currentCid.current = data.id; setConversation(data); setView('workspace'); }
      notify(kind === 'login' ? '请在弹出的浏览器中扫码登录' : kind === 'gallery' ? '开始建立素材缩略图' : '任务已开始'); return result;
    } catch (e) { notify(e.message); return null; }
  }
  async function send(textOverride, extra = {}) {
    const text = typeof textOverride === 'string' ? textOverride : draft;
    if ((!text.trim() && !uploads.length) || sending) return;
    if (busy) {
      if (active && job.ready && !uploads.length) {
        try { setPendingSteer(true); await api('/jobs/steer', { method: 'POST', body: { text } }); } catch (e) { setPendingSteer(false); notify(e.message); }
      } else notify('已有任务正在执行，可以先停止或继续当前会话');
      return;
    }
    if (uploads.some(x => x.status !== 'ready')) { notify('请等待文件添加完成，或移除失败的文件'); return; }
    if (!settings.configured) { notify('请先保存 DeepSeek Key'); setView('settings'); return; }
    setSending(true); follow.current = true;
    try {
      const staged = [...uploads];
      const result = await api('/jobs', { method: 'POST', body: { kind: 'chat', options: { request: text, conversation_id: cid, upload_ids: staged.map(x => x.id), ...extra } } });
      setJob(previous => previous?.id === result.id ? { ...result, ...previous } : result); setCid(result.conversation_id); currentCid.current = result.conversation_id; setView('workspace');
      setConversation(previous => ({ ...(previous || {}), id: result.conversation_id, title: previous?.title || text.slice(0, 80) || '附件分析', messages: [...(previous?.messages || []), { id: `pending-${result.id}`, role: 'user', content: text || '请阅读并分析这些附件。', attachments: staged, status: 'pending' }] }));
      setDraft(''); setUploads([]); refreshRecent();
      const current = await api('/job'); setJob(current);
      if (current?.id === result.id && current.state !== 'running') { setConversation(await api(`/conversations/${result.conversation_id}`)); }
    } catch (e) { notify(e.message); } finally { setSending(false); }
  }
  function openFile(item) { if (item.kind === 'archive' && !item.upload) setGallery(item); else setPreview(item); }
  async function renameConversation() {
    setMenu(false);
    const title = prompt('对话名称', conversation?.title || '');
    if (!title?.trim()) return;
    try { const data = await api(`/conversations/${cid}`, { method: 'PATCH', body: { title } }); setConversation(data); refreshRecent(); } catch (e) { notify(e.message); }
  }
  async function changeTheme(theme) { setPreferences(value => ({ ...value, theme })); await api('/preferences', { method: 'PUT', body: { theme } }); }

  if (bootError) return <div className="fatal"><CircleAlert size={32} /><h2>本地工作空间暂未连接</h2><p>{bootError}</p><button onClick={() => location.reload()}>重新连接</button></div>;
  if (!boot) return <div className="splash"><img src="/brand.png" /><strong>源镜</strong><span><Loader2 size={14} className="spin" />正在打开工作空间</span></div>;
  return <div className={`desktop-app ${collapsed ? 'sidebar-collapsed' : ''}`} onDragOver={e => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); setDragging(true); } }} onDragLeave={e => { if (!e.relatedTarget) setDragging(false); }} onDrop={e => { e.preventDefault(); setDragging(false); if (e.dataTransfer.files.length) addBrowserFiles(e.dataTransfer.files); }}>
    <header className="app-chrome" onMouseDown={e => { if (e.button === 0 && !e.target.closest('button,input,a')) native?.windowAction('drag'); }} onDoubleClick={e => { if (!e.target.closest('button,input,a')) native?.windowAction('maximize'); }}><div className="app-brand"><img src="/brand.png" /><span>源镜</span><b>工作空间</b></div><span className="chrome-context">{profile.name || '本地工作空间'}</span>{native && <div className="window-controls"><button aria-label="最小化" onClick={() => native.windowAction('minimize')}><Minus size={14} /></button><button aria-label="最大化或还原" onClick={() => native.windowAction('maximize')}><Square size={11} /></button><button className="close-window" aria-label="关闭窗口" onClick={() => native.windowAction('close')}><X size={16} /></button></div>}</header>
    <aside className="sidebar"><div className="sidebar-top"><button className="new-chat" onClick={() => loadConversation(null)} title="新建对话 · Ctrl+N"><SquarePen size={17} /><span>新建对话</span><kbd>⌃ N</kbd></button><IconButton icon={collapsed ? PanelLeftOpen : PanelLeftClose} label={collapsed ? '展开侧边栏' : '收起侧边栏'} onClick={() => setCollapsed(!collapsed)} /></div><nav>{navigation.map(([key, title, Icon]) => <button key={key} title={title} className={view === key ? 'active' : ''} onClick={() => setView(key)}><Icon size={17} strokeWidth={1.65} /><span>{title}</span>{key === 'library' && <b className="nav-dot" />}</button>)}</nav><div className="history-section"><div className="history-heading"><span>最近对话</span><label><Search size={14} /><input aria-label="搜索历史对话" placeholder="搜索" value={historySearch} onChange={e => setHistorySearch(e.target.value)} /></label></div><div className="history-list">{recent.filter(item => item.title.toLowerCase().includes(historySearch.toLowerCase())).map(item => <button key={item.id} title={item.title} className={cid === item.id && view === 'workspace' ? 'selected' : ''} onClick={() => loadConversation(item.id)}><span>{item.title}</span>{busy && job.conversation_id === item.id ? <Loader2 size={12} className="spin" /> : <time>{dateLabel(item.updated_at)}</time>}</button>)}{!recent.length && <p className="history-empty">你的对话会保存在这里</p>}</div></div><div className="sidebar-bottom"><button className={view === 'settings' ? 'active sidebar-settings' : 'sidebar-settings'} onClick={() => setView('settings')}><Settings size={17} /><span>设置</span></button><button className="account-card" disabled={busy} onClick={() => startJob('login')} title="登录或切换抖音账号"><span className="avatar">{(boot.overview?.self?.nickname || '本')[0]}</span><span><strong>{boot.overview?.self?.nickname || '本地工作空间'}</strong><small><i className={boot.overview?.login?.saved ? 'connected-dot' : ''} />{boot.overview?.login?.saved ? '抖音登录态已保存' : '登录抖音账号'}</small></span><ChevronDown size={14} /></button></div></aside>
    <main className="main-panel">{view === 'workspace' ? <>
      <header className="workspace-header"><div className="breadcrumb"><span>工作台</span><ChevronDown size={11} className="breadcrumb-chevron" /><strong>{conversation?.title || '新对话'}</strong></div><div className="workspace-actions">{busy && job.conversation_id !== cid && <button className="active-job-button" onClick={() => loadConversation(job.conversation_id)}><Loader2 size={13} className="spin" />查看执行中的任务</button>}<span className={`local-status ${connection === 'connected' ? '' : 'offline'}`}><i />{connection === 'connected' ? '本地已连接' : '正在重新连接'}</span><IconButton icon={ListChecks} label="查看执行记录" disabled={!conversation?.chat_run && !job} onClick={() => setInspector(!inspector)} /><div className="menu-anchor"><IconButton icon={MoreHorizontal} label="会话操作" disabled={!cid || busy} onClick={() => setMenu(!menu)} />{menu && <><div className="menu-dismiss" onClick={() => setMenu(false)} /><div className="dropdown-menu"><button onClick={renameConversation}>重命名</button><button disabled={!conversation?.codex} onClick={() => { setMenu(false); startJob('chat_fork', { conversation_id: cid }); }}>另开方案</button><button disabled={!conversation?.codex} onClick={() => { setMenu(false); startJob('chat_compact', { conversation_id: cid }); }}>整理上下文</button></div></>}</div></div></header>
      <div className="workspace-layout"><section className="conversation-panel"><div className="conversation-scroll" ref={scroller} onScroll={e => { const element = e.currentTarget; follow.current = element.scrollHeight - element.scrollTop - element.clientHeight < 110; setUnfollowed(!follow.current); }}>
        {!messages.length && !active ? <div className="welcome"><div className="welcome-mark"><img src="/brand.png" /></div><span className="eyebrow">你的内容工作伙伴</span><h1>今天，想完成什么？</h1><p>把资料、素材和想法交给源镜，一起找到下一步。</p><div className="starter-grid">{starters.map(({ icon: Icon, title, text, note }) => <button key={title} onClick={() => { setDraft(text); textarea.current?.focus(); }}><Icon size={21} strokeWidth={1.45} /><strong>{title}</strong><span>{note}</span><ArrowUpRight size={15} className="starter-arrow" /></button>)}</div><div className="welcome-file-hint"><FolderArchive size={15} />也可以直接拖入图片、视频、文档或压缩包</div></div> : <div className="messages">{messages.map((message, index) => {
          const parsed = parseChoices(message.content), user = message.role === 'user', error = message.role === 'error';
          return <article key={message.id || index} className={`message ${user ? 'user-message' : 'assistant-message'} ${error ? 'error-message' : ''}`}><div className="message-meta">{user ? <span>你</span> : <><span className="assistant-mark"><img src="/brand.png" /></span><strong>{error ? '执行提示' : '源镜'}</strong></>}<CopyButton text={message.content} /></div>{!!message.attachments?.filter(a => !a.generated).length && <div className="message-files">{message.attachments.filter(a => !a.generated).map(item => <FileTile key={item.id || item.name} item={item} onOpen={openFile} />)}</div>}{!user && message.reasoning && <Thought text={message.reasoning} />}<div className={user ? 'user-bubble' : 'markdown'}>{user ? <p>{message.content}</p> : <Markdown text={parsed.text} />}</div>{parsed.questions.length > 0 && <Choices questions={parsed.questions} onSend={send} />}{!!message.attachments?.filter(a => a.generated).length && <div className="artifact-grid">{message.attachments.filter(a => a.generated).map(item => <FileTile key={item.id} item={item} onOpen={openFile} />)}</div>}</article>;
        })}{active && <article className="message assistant-message streaming"><div className="message-meta"><span className="assistant-mark"><img src="/brand.png" /></span><strong>源镜</strong><span className="running-label"><i />正在处理</span></div><Thought text={job.reasoning} running={!job.answer} /><ToolSteps items={job.tools} running />{job.answer ? <div className="markdown"><Markdown text={parseChoices(job.answer).text.replace(/```choices[\s\S]*$/, '')} /></div> : <div className="current-activity"><Loader2 size={14} className="spin" /><span>{job.message || '正在准备…'}</span></div>}{Object.values(job.confirmations || {}).map(item => <div className="confirmation" key={item.request_id}><div><CircleAlert size={19} /><strong>允许执行「{item.name}」？</strong></div><details><summary>查看操作内容</summary><pre>{item.detail}</pre></details><div className="row"><button className="primary" onClick={() => api('/jobs/confirm', { method: 'POST', body: { request_id: item.request_id, approved: true } })}>允许这次</button><button className="secondary" onClick={() => api('/jobs/confirm', { method: 'POST', body: { request_id: item.request_id, approved: false } })}>拒绝</button></div></div>)}{!!job.artifacts?.length && <div className="artifact-grid">{job.artifacts.map(item => <FileTile key={item.id} item={item} onOpen={openFile} />)}</div>}</article>}{!active && conversation?.chat_run && !['complete', 'partial'].includes(conversation.chat_run.status) && <div className="resume-card"><div><CircleAlert size={18} /><span><strong>{conversation.chat_run.status === 'cancelled' ? '任务已停止' : '还有未完成的工作'}</strong><small>已有执行记录和素材进度已保存</small></span></div><button className="secondary" disabled={conversation.chat_run.status === 'needs_review' || busy} onClick={() => startJob('chat', { request: conversation.chat_run.request, conversation_id: cid, chat_run_id: conversation.chat_run.id })}>继续任务 <ArrowUpRight size={14} /></button></div>}</div>}
      </div>{unfollowed && <button className="scroll-bottom" onClick={() => { follow.current = true; scroller.current.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' }); }}><ArrowDown size={15} />回到底部</button>}
      <div className="composer-area"><div className={`composer ${dragging ? 'dragging' : ''}`}><div className="composer-attachments">{uploads.map(item => <FileTile compact key={item.localId || item.id} item={item} onOpen={openFile} onRemove={() => removeUpload(item)} />)}</div><textarea ref={textarea} aria-label="发送给源镜的消息" value={draft} onChange={e => setDraft(e.target.value)} onPaste={e => { const files = [...(e.clipboardData?.items || [])].filter(item => item.kind === 'file').map(item => item.getAsFile()).filter(Boolean); if (files.length) { e.preventDefault(); addBrowserFiles(files); } }} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }} placeholder={active && job.ready ? '补充要求，按 Enter 追加到当前任务…' : '说说你的想法，或拖入文件…'} rows={2} /><div className="composer-toolbar"><div className="row"><IconButton icon={Plus} label="添加文件" onClick={pickFiles} /><button className="model-chip" title="更改模型" onClick={() => setView("settings")}>{modelName(settings.model)}<ChevronDown size={12} /></button>{settings.agent_engine === 'codex' && <span className="engine-chip">Codex</span>}</div><div className="row"><span className="composer-hint">{active ? job.ready ? 'Enter 追加要求' : '正在执行任务' : 'Enter 发送'}</span>{active && draft.trim() && job.ready && <button className="text-button steer-action" disabled={pendingSteer} onClick={() => send()}>{pendingSteer ? '正在送达…' : '追加要求'}</button>}<button className={`send-button ${active ? 'stop-button' : ''}`} aria-label={active ? '停止生成' : '发送消息'} disabled={sending || (!active && !draft.trim() && !uploads.length)} onClick={() => active ? api('/jobs/stop', { method: 'POST' }).catch(e => notify(e.message)) : send()}>{sending ? <Loader2 size={17} className="spin" /> : active ? <Square size={13} fill="currentColor" /> : <ArrowUp size={19} />}</button></div></div></div><div className="composer-footnote"><span>内容仅供参考，重要信息请核实。</span><span>{active ? job.message?.slice(0, 45) : 'Shift + Enter 换行'}</span></div></div></section>
      {inspector && <aside className="inspector"><header><strong>执行记录</strong><IconButton icon={X} label="关闭执行记录" onClick={() => setInspector(false)} /></header>{conversation?.chat_run ? <><div className="inspector-summary"><span>状态</span><b>{({ complete: '已完成', cancelled: '已停止', failed: '未完成', running: '执行中', partial: '部分完成', needs_review: '待核对' }[conversation.chat_run.status]) || conversation.chat_run.status}</b><span>操作次数</span><b>{conversation.chat_run.tool_count}</b></div>{conversation.chat_run.calls?.map(item => <details key={item.id}><summary>{item.result?.ok ? <Check size={13} /> : <CircleAlert size={13} />}{item.tool}</summary><pre>{JSON.stringify(item.result || { status: item.status }, null, 2)}</pre></details>)}</> : <ToolSteps items={job?.tools} />}</aside>}
      </div>
    </> : view === 'library' ? <Library openFile={openFile} openConversation={loadConversation} startJob={startJob} job={job} notify={notify} /> : ['works', 'users', 'tasks'].includes(view) ? <DataPage key={view} view={view} startJob={startJob} busy={busy} notify={notify} /> : view === 'benchmarks' ? <Benchmarks startJob={startJob} busy={busy} notify={notify} /> : view === 'reports' ? <Reports startJob={startJob} busy={busy} notify={notify} /> : <SettingsPage settings={settings} onSettings={setSettings} profile={profile} onProfile={setProfile} preferences={preferences} onTheme={changeTheme} native={native} notify={notify} busy={busy} />}</main>
    <input className="hidden-file" type="file" multiple ref={fileInput} onChange={e => { addBrowserFiles(e.target.files); e.target.value = ''; }} />
    {preview && <FilePreview key={`${preview.id}-${preview.asset_id || ''}`} item={preview} onClose={() => setPreview(null)} onGallery={setGallery} />}
    {gallery && <Gallery item={gallery} onClose={() => setGallery(null)} job={job} startJob={startJob} onOpen={setPreview} onAnalyze={item => { setGallery(null); loadConversation(item.conversation_id || cid); setDraft(`请分析附件 ${item.id} 的全部素材，先完成总览，再按任务查看原图与视频细节。`); }} />}
    {dragging && <div className="drop-overlay" onDragOver={e => e.preventDefault()} onDragLeave={e => { if (e.target === e.currentTarget) setDragging(false); }}><div><FolderArchive size={45} strokeWidth={1.2} /><h2>把文件放到这里</h2><p>图片、视频、文档与压缩包</p></div></div>}
    {toast && <div role="status" className="toast"><span>{toast}</span><button aria-label="关闭提示" onClick={() => setToast('')}><X size={13} /></button></div>}
  </div>;
}
