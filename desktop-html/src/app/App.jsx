import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  CircleAlert, FolderArchive, History, Loader2, MessageSquare, FileText,
  Target, Users, X, BarChart3, FolderOpen,
} from 'lucide-react';
import { api, authToken, nativeBridge, uploadFile, dateLabel } from '../api.js';
import { FilePreview, Gallery } from '../ui/media.jsx';
import { Library, DataPage, Benchmarks, Reports } from '../features/pages.jsx';
import { SettingsPage } from '../settings.jsx';
import TitleBar from './TitleBar.jsx';
import Sidebar from './Sidebar.jsx';
import Workspace from '../features/workspace/Workspace.jsx';

const NAVIGATION = [
  ['workspace', '工作台', MessageSquare],
  ['library', '素材库', FolderOpen],
  ['works', '作品数据', BarChart3],
  ['users', '互动受众', Users],
  ['reports', '分析报告', FileText],
  ['benchmarks', '对标账号', Target],
  ['tasks', '执行记录', History],
];

export default function App() {
  const [boot, setBoot] = useState(null);
  const [bootError, setBootError] = useState('');
  const [view, setView] = useState('workspace');
  const [conversation, setConversation] = useState(null);
  const [cid, setCid] = useState(null);
  const [recent, setRecent] = useState([]);
  const [settings, setSettings] = useState({});
  const [profile, setProfile] = useState({});
  const [preferences, setPreferences] = useState({ theme: 'light' });
  const [job, setJob] = useState(null);
  const [draft, setDraft] = useState('');
  const [uploads, setUploads] = useState([]);
  const [native, setNative] = useState(null);
  const [collapsed, setCollapsed] = useState(false);
  const [toast, setToast] = useState('');
  const [connection, setConnection] = useState('connecting');
  const [preview, setPreview] = useState(null);
  const [gallery, setGallery] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [historySearch, setHistorySearch] = useState('');
  const [inspector, setInspector] = useState(false);
  const [pendingSteer, setPendingSteer] = useState(false);
  const [sending, setSending] = useState(false);

  const currentCid = useRef(cid);
  const jobRef = useRef(job);
  const fileInput = useRef(null);
  const uploadQueue = useRef([]);
  const uploadWorkers = useRef(0);
  const toastTimer = useRef(null);
  currentCid.current = cid;
  jobRef.current = job;

  const busy = job?.state === 'running';
  const active = busy && job?.conversation_id === cid;

  const notify = useCallback((message) => {
    setToast(String(message));
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(''), 4200);
  }, []);

  const refreshRecent = useCallback(async () => {
    try { setRecent(await api('/conversations')); } catch (error) { notify(error.message); }
  }, [notify]);

  /* ------------------------------------------------------------ 会话 ---- */

  async function loadConversation(id, changeView = true) {
    setInspector(false);
    if (changeView) setView('workspace');
    if (!id) {
      setCid(null);
      setConversation(null);
      setDraft('');
      api('/preferences', { method: 'PUT', body: { last_conversation: null } }).catch(() => {});
      return;
    }
    currentCid.current = id;
    setCid(id);
    setConversation(null);
    try {
      const data = await api(`/conversations/${id}`);
      if (currentCid.current === id) setConversation(data);
      api('/preferences', { method: 'PUT', body: { last_conversation: id } }).catch(() => {});
    } catch (error) { notify(error.message); }
  }

  async function renameConversation() {
    const title = window.prompt('对话名称', conversation?.title || '');
    if (!title?.trim()) return;
    try {
      const data = await api(`/conversations/${cid}`, { method: 'PATCH', body: { title } });
      setConversation(data);
      refreshRecent();
    } catch (error) { notify(error.message); }
  }

  async function changeTheme(theme) {
    setPreferences((value) => ({ ...value, theme }));
    try { await api('/preferences', { method: 'PUT', body: { theme } }); } catch (error) { notify(error.message); }
  }

  /** 输入区直接切模型：写回 llm.local.yaml（api_key 传空 = 保留原值） */
  async function pickModel(model) {
    if (!model || model === settings?.model) return;
    const previous = settings;
    setSettings((value) => ({ ...value, model }));
    try {
      setSettings(await api('/settings', { method: 'PUT', body: { api_key: '', model } }));
    } catch (error) {
      setSettings(previous);
      notify(error.message);
    }
  }

  /* ------------------------------------------------------------ 任务 ---- */

  async function startJob(kind, options = {}) {
    try {
      const result = await api('/jobs', { method: 'POST', body: { kind, options } });
      setJob((previous) => (previous?.id === result.id ? { ...result, ...previous } : result));
      const current = await api('/job');
      setJob(current);
      if (current?.state !== 'running' && current?.conversation_id && ['chat', 'chat_fork', 'chat_compact'].includes(kind)) {
        const data = await api(`/conversations/${current.conversation_id}`);
        setCid(data.id);
        currentCid.current = data.id;
        setConversation(data);
        setView('workspace');
      }
      notify(kind === 'login' ? '请在弹出的浏览器中扫码登录' : kind === 'gallery' ? '开始建立素材缩略图' : '任务已开始');
      return result;
    } catch (error) {
      notify(error.message);
      return null;
    }
  }

  async function send(textOverride, extra = {}) {
    const text = typeof textOverride === 'string' ? textOverride : draft;
    if ((!text.trim() && !uploads.length) || sending) return;

    if (busy) {
      if (active && job.ready && !uploads.length) {
        try {
          setPendingSteer(true);
          await api('/jobs/steer', { method: 'POST', body: { text } });
        } catch (error) {
          setPendingSteer(false);
          notify(error.message);
        }
      } else {
        notify('已有任务正在执行，可以先停止或继续当前会话');
      }
      return;
    }
    if (uploads.some((item) => item.status !== 'ready')) {
      notify('请等待文件添加完成，或移除失败的文件');
      return;
    }
    if (!settings.configured) {
      notify('请先保存 DeepSeek Key');
      setView('settings');
      return;
    }

    setSending(true);
    try {
      const staged = [...uploads];
      const result = await api('/jobs', { method: 'POST', body: { kind: 'chat', options: { request: text, conversation_id: cid, upload_ids: staged.map((item) => item.id), ...extra } } });
      setJob((previous) => (previous?.id === result.id ? { ...result, ...previous } : result));
      setCid(result.conversation_id);
      currentCid.current = result.conversation_id;
      setView('workspace');
      setConversation((previous) => ({
        ...(previous || {}),
        id: result.conversation_id,
        title: previous?.title || text.slice(0, 80) || '附件分析',
        messages: [...(previous?.messages || []), {
          id: `pending-${result.id}`,
          role: 'user',
          content: text || '请阅读并分析这些附件。',
          attachments: staged,
          status: 'pending',
        }],
      }));
      setDraft('');
      setUploads([]);
      refreshRecent();
      const current = await api('/job');
      setJob(current);
      if (current?.id === result.id && current.state !== 'running') {
        setConversation(await api(`/conversations/${result.conversation_id}`));
      }
    } catch (error) {
      notify(error.message);
    } finally {
      setSending(false);
    }
  }

  const stopJob = () => api('/jobs/stop', { method: 'POST' }).catch((error) => notify(error.message));

  /* ------------------------------------------------------------ 附件 ---- */

  function addNative(items) {
    setUploads((values) => [...values, ...items.map((item) => ({ ...item, upload: true }))]);
    setView('workspace');
  }

  async function drainUploads() {
    while (uploadWorkers.current < 2 && uploadQueue.current.length) {
      const { file, localId } = uploadQueue.current.shift();
      uploadWorkers.current += 1;
      uploadFile(file, (progress) => setUploads((values) => values.map((item) => (item.localId === localId ? { ...item, progress } : item))))
        .then((result) => setUploads((values) => values.map((item) => (item.localId === localId ? { ...result, localId, upload: true } : item))))
        .catch((error) => {
          setUploads((values) => values.map((item) => (item.localId === localId ? { ...item, status: 'error' } : item)));
          notify(error.message);
        })
        .finally(() => { uploadWorkers.current -= 1; drainUploads(); });
    }
  }

  function addBrowserFiles(files) {
    const selected = [...files].map((file) => {
      const localId = crypto.randomUUID();
      uploadQueue.current.push({ file, localId });
      return { localId, name: file.name, size: file.size, upload: true, status: 'uploading', progress: 0 };
    });
    setUploads((values) => [...values, ...selected]);
    setView('workspace');
    drainUploads();
  }

  function removeUpload(item) {
    if (item.status === 'uploading') { notify('文件添加完成后可移除'); return; }
    setUploads((values) => values.filter((value) => value !== item));
    if (item.id) api(`/uploads/${item.id}`, { method: 'DELETE' }).catch(() => {});
  }

  async function pickFiles() {
    if (native) native.pickFiles((value) => { try { addNative(JSON.parse(value)); } catch { /* ignore */ } });
    else fileInput.current?.click();
  }

  function openFile(item) {
    if (item.kind === 'archive' && !item.upload) setGallery(item);
    else setPreview(item);
  }

  /* ------------------------------------------------------------ 启动 ---- */

  useEffect(() => {
    let cancelled = false;
    api('/bootstrap').then((data) => {
      if (cancelled) return;
      setBoot(data);
      setSettings(data.settings);
      setProfile(data.profile);
      setRecent(data.conversations);
      setPreferences(data.preferences);
      setJob(data.job);
      const id = data.preferences.last_conversation || (data.job?.state === 'running' ? data.job.conversation_id : null);
      if (id) {
        setCid(id);
        currentCid.current = id;
        api(`/conversations/${id}`)
          .then((value) => !cancelled && setConversation(value))
          .catch(() => setCid(null));
      }
    }).catch((error) => setBootError(error.message));
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    nativeBridge().then((bridge) => {
      if (!bridge) return;
      setNative(bridge);
      bridge.filesDropped.connect((value) => { try { addNative(JSON.parse(value)); } catch { /* ignore */ } });
      bridge.dragState.connect(setDragging);
      bridge.initialFiles((value) => {
        try {
          const files = JSON.parse(value);
          if (files.length) addNative(files);
        } catch { /* ignore */ }
      });
    }).catch(() => {});
  }, []);

  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)');
    const apply = () => {
      document.documentElement.dataset.theme = preferences.theme === 'system'
        ? (media.matches ? 'dark' : 'light')
        : preferences.theme || 'light';
    };
    apply();
    media.addEventListener('change', apply);
    return () => media.removeEventListener('change', apply);
  }, [preferences.theme]);

  useEffect(() => {
    let closed = false;
    let socket;
    let timer;

    function connect() {
      socket = new WebSocket(`ws://${location.host}/api/events?token=${encodeURIComponent(authToken())}`);
      socket.onopen = () => setConnection('connected');
      socket.onclose = () => {
        if (closed) return;
        setConnection('reconnecting');
        timer = setTimeout(connect, 1800);
      };
      socket.onerror = () => socket.close();
      socket.onmessage = async (message) => {
        const event = JSON.parse(message.data);
        if (event.type === 'snapshot') { setJob(event.job); return; }
        setJob((previous) => {
          if (!previous || (event.job_id && previous.id !== event.job_id)) {
            if (event.type !== 'started') return previous;
            previous = {
              id: event.job_id, kind: event.kind, conversation_id: event.conversation_id,
              state: 'running', tools: [], confirmations: {}, started_at: Date.now() / 1000,
            };
          }
          const next = { ...previous, conversation_id: event.conversation_id || previous.conversation_id };
          if (event.message) next.message = event.message;
          if (event.type === 'answer_delta') next.answer = (next.answer || '') + (event.delta || '');
          if (event.type === 'thinking') next.reasoning = (next.reasoning || '') + (event.delta || '');
          if (event.type === 'codex_ready') next.ready = event.ready;
          if (event.type === 'tool') {
            const tools = [...(previous.tools || [])].map((item) => ({ ...item }));
            if (event.phase === 'start') {
              tools.push({ tool: event.tool, name: event.name || event.tool, status: 'running' });
              next.message = `${event.name || event.tool}执行中…`;
            }
            if (event.phase === 'done') {
              const index = tools.findLastIndex((item) => item.tool === event.tool && item.status === 'running');
              if (index >= 0) tools[index] = { ...tools[index], status: event.ok ? 'complete' : 'failed', summary: event.summary };
              next.message = event.summary || '继续处理…';
            }
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
            setDraft((value) => (value.trim() === event.text ? '' : value));
            if (currentCid.current === event.conversation_id) {
              setConversation((value) => (value
                ? { ...value, messages: [...value.messages, { id: event.message_id, role: 'user', content: event.text, status: 'complete' }] }
                : value));
            }
            notify('要求已追加，继续执行');
          } else {
            notify(event.error || '追加要求未送达，输入已保留');
          }
        }

        if (event.type === 'result' || event.type === 'error') {
          setPendingSteer(false);
          refreshRecent();
          const result = event.result || {};
          if (result.conversation) {
            if (event.conversation_id === currentCid.current || ['chat_fork', 'chat_compact'].includes(jobRef.current?.kind)) {
              setCid(result.conversation.id);
              currentCid.current = result.conversation.id;
              setConversation(result.conversation);
              setView('workspace');
            }
          } else if (event.conversation_id && currentCid.current === event.conversation_id) {
            api(`/conversations/${event.conversation_id}`).then(setConversation).catch(() => {});
          }
          if (event.type === 'error') notify(event.message);
          api('/bootstrap').then((data) => { setBoot(data); setSettings(data.settings); setProfile(data.profile); }).catch(() => {});
        }
      };
    }

    connect();
    return () => { closed = true; clearTimeout(timer); socket?.close(); };
  }, [notify, refreshRecent]);

  useEffect(() => {
    const handler = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'n') { event.preventDefault(); loadConversation(null); }
      if ((event.ctrlKey || event.metaKey) && event.key === ',') { event.preventDefault(); setView('settings'); }
      if (event.key === 'Escape') setInspector(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  useEffect(() => {
    const handler = (event) => {
      api('/jobs/confirm', { method: 'POST', body: event.detail }).catch((error) => notify(error.message));
    };
    window.addEventListener('scout:confirm', handler);
    return () => window.removeEventListener('scout:confirm', handler);
  }, [notify]);

  /* ------------------------------------------------------------ 渲染 ---- */

  if (bootError) {
    return (
      <div className="grid h-[100dvh] place-items-center bg-bg text-secondary">
        <div className="flex flex-col items-center gap-3 text-center">
          <CircleAlert size={30} className="text-danger" />
          <h2 className="text-[18px] font-medium text-text">本地工作空间暂未连接</h2>
          <p className="max-w-[420px] text-[12.5px] leading-relaxed">{bootError}</p>
          <button
            type="button"
            onClick={() => location.reload()}
            className="mt-1 rounded-[9px] border border-line px-4 py-2 text-[12.5px] text-text hover:bg-subtle"
          >
            重新连接
          </button>
        </div>
      </div>
    );
  }

  if (!boot) {
    return (
      <div className="grid h-[100dvh] place-items-center bg-bg">
        <div className="flex flex-col items-center gap-3">
          <img src="/brand.png" alt="" className="h-14 w-14" />
          <strong className="text-[19px] font-[550] tracking-[4px] text-text">源镜</strong>
          <span className="flex items-center gap-2 text-[12px] text-muted">
            <Loader2 size={14} className="spin" />
            正在打开工作空间
          </span>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`grid h-[100dvh] min-w-[760px] overflow-hidden bg-bg ${collapsed ? 'grid-cols-[66px_minmax(0,1fr)]' : 'grid-cols-[230px_minmax(0,1fr)]'} grid-rows-[44px_minmax(0,1fr)]`}
      onDragOver={(event) => { if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); setDragging(true); } }}
      onDragLeave={(event) => { if (!event.relatedTarget) setDragging(false); }}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        if (event.dataTransfer.files.length) addBrowserFiles(event.dataTransfer.files);
      }}
    >
      <TitleBar project={profile?.name || boot?.overview?.self?.nickname} native={native} />

      <Sidebar
        navigation={NAVIGATION}
        view={view}
        onNavigate={setView}
        collapsed={collapsed}
        onToggle={() => setCollapsed(!collapsed)}
        recent={recent}
        activeCid={cid}
        busy={busy}
        runningCid={job?.conversation_id}
        search={historySearch}
        onSearch={setHistorySearch}
        onOpenConversation={loadConversation}
        onNewConversation={() => loadConversation(null)}
        onLogin={() => startJob('login')}
        account={boot?.overview?.self?.nickname}
        loginSaved={!!boot?.overview?.login?.saved}
        dateLabel={dateLabel}
      />

      <main className="col-start-2 row-start-2 contents">
        {view === 'workspace' ? (
          <Workspace
            conversation={conversation}
            cid={cid}
            job={job}
            active={active}
            busy={busy}
            settings={settings}
            connection={connection}
            draft={draft}
            onDraft={setDraft}
            uploads={uploads}
            onRemoveUpload={removeUpload}
            onPickFiles={pickFiles}
            onAddFiles={addBrowserFiles}
            onSend={send}
            onStop={stopJob}
            sending={sending}
            pendingSteer={pendingSteer}
            onOpenFile={openFile}
            onOpenSettings={() => setView('settings')}
            onPickModel={pickModel}
            inspector={inspector}
            onToggleInspector={() => setInspector(!inspector)}
            onOpenRunningJob={(id) => loadConversation(id)}
            onResume={() => startJob('chat', { request: conversation.chat_run.request, conversation_id: cid, chat_run_id: conversation.chat_run.id })}
            onRename={renameConversation}
            onFork={() => startJob('chat_fork', { conversation_id: cid })}
            onCompact={() => startJob('chat_compact', { conversation_id: cid })}
          />
        ) : (
          <div className="col-start-2 row-start-2 flex min-h-0 min-w-0 flex-col bg-bg">
            {view === 'library' ? (
              <Library openFile={openFile} openConversation={loadConversation} startJob={startJob} job={job} notify={notify} />
            ) : ['works', 'users', 'tasks'].includes(view) ? (
              <DataPage key={view} view={view} startJob={startJob} busy={busy} notify={notify} />
            ) : view === 'benchmarks' ? (
              <Benchmarks startJob={startJob} busy={busy} notify={notify} />
            ) : view === 'reports' ? (
              <Reports startJob={startJob} busy={busy} notify={notify} />
            ) : (
              <SettingsPage
                settings={settings}
                onSettings={setSettings}
                profile={profile}
                onProfile={setProfile}
                preferences={preferences}
                onTheme={changeTheme}
                native={native}
                notify={notify}
                busy={busy}
              />
            )}
          </div>
        )}
      </main>

      <input
        className="hidden"
        type="file"
        multiple
        ref={fileInput}
        onChange={(event) => { addBrowserFiles(event.target.files); event.target.value = ''; }}
      />

      {preview ? (
        <FilePreview key={`${preview.id}-${preview.asset_id || ''}`} item={preview} onClose={() => setPreview(null)} onGallery={setGallery} />
      ) : null}

      {gallery ? (
        <Gallery
          item={gallery}
          onClose={() => setGallery(null)}
          job={job}
          startJob={startJob}
          onOpen={setPreview}
          onAnalyze={(item) => {
            setGallery(null);
            loadConversation(item.conversation_id || cid);
            setDraft(`请分析附件 ${item.id} 的全部素材，先完成总览，再按任务查看原图与视频细节。`);
          }}
        />
      ) : null}

      {dragging ? (
        <div
          className="pointer-events-none fixed inset-[45px_8px_8px_8px] z-[200] grid place-items-center rounded-[13px] border-2 border-dashed border-accent bg-[color-mix(in_srgb,var(--bg)_93%,transparent)]"
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => { if (event.target === event.currentTarget) setDragging(false); }}
        >
          <div className="text-center text-accent">
            <FolderArchive size={45} strokeWidth={1.2} />
            <h2 className="mt-4 text-[21px] font-medium">把文件放到这里</h2>
            <p className="mt-3 text-[13px] text-muted">图片、视频、文档与压缩包</p>
          </div>
        </div>
      ) : null}

      {toast ? (
        <div role="status" className="fixed bottom-7 left-1/2 z-[300] flex max-w-[660px] -translate-x-1/2 items-center gap-4 rounded-[12px] border border-line bg-bg px-4 py-3 text-[12.5px] leading-relaxed text-text shadow-[var(--shadow-2)]">
          <span>{toast}</span>
          <button type="button" aria-label="关闭提示" onClick={() => setToast('')} className="grid h-5 w-5 place-items-center rounded text-muted hover:text-text">
            <X size={13} />
          </button>
        </div>
      ) : null}
    </div>
  );
}
