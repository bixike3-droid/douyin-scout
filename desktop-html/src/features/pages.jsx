import React, { useEffect, useState } from 'react';
import {
  ArrowUpRight, BarChart3, ChevronLeft, ChevronRight, CircleAlert, Database, Download, FileText,
  Flame, FolderOpen, Loader2, Plus, RefreshCw, Search, Users, X,
} from 'lucide-react';
import { api, dateLabel } from '../api.js';
import { FileTile, Markdown, Modal } from '../ui/media.jsx';
import { Badge, Button, Card, EmptyState, Field, Input, Textarea, cn } from '../ui/kit.jsx';

const EMPTY = '—';
const number = (value) => (value === null || value === undefined
  ? EMPTY
  : typeof value === 'number' ? value.toLocaleString('zh-CN') : value);

/* ------------------------------------------------------------- 通用件 */

function PageHeader({ title, subtitle, children }) {
  return (
    <header className="mb-6 flex items-center justify-between gap-5">
      <div>
        <h1 className="text-[21px] font-[560] tracking-[-0.5px] text-text">{title}</h1>
        <p className="mt-1.5 text-[12px] leading-relaxed text-muted">{subtitle}</p>
      </div>
      <div className="flex shrink-0 items-center gap-2">{children}</div>
    </header>
  );
}

function Toolbar({ value, onChange, placeholder, children }) {
  return (
    <div className="mb-4 flex items-center justify-between gap-4">
      <label className="flex max-w-[340px] flex-1 items-center gap-2 rounded-[9px] border border-line bg-bg px-2.5 py-2 text-muted transition-[border-color,box-shadow] focus-within:border-[color-mix(in_srgb,var(--accent)_55%,var(--line))] focus-within:shadow-[0_0_0_3px_color-mix(in_srgb,var(--accent)_18%,transparent)]">
        <Search size={15} />
        <input
          className="w-full min-w-0 border-0 bg-transparent text-[12px] text-text outline-none placeholder:text-muted"
          placeholder={placeholder}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      </label>
      <div className="flex items-center gap-2.5">{children}</div>
    </div>
  );
}

function Loader() {
  return (
    <div className="grid place-items-center py-24 text-muted">
      <Loader2 className="spin" size={20} />
    </div>
  );
}

function Pager({ label, onPrev, onNext, canPrev, canNext }) {
  return (
    <div className="mt-4 flex items-center justify-end gap-2 text-[11px] text-muted">
      <span className="mr-3">{label}</span>
      <button
        type="button"
        aria-label="上一页"
        disabled={!canPrev}
        onClick={onPrev}
        className="grid h-7 w-7 place-items-center rounded-md border border-line text-secondary transition-colors hover:bg-subtle disabled:opacity-40"
      >
        <ChevronLeft size={14} />
      </button>
      <button
        type="button"
        aria-label="下一页"
        disabled={!canNext}
        onClick={onNext}
        className="grid h-7 w-7 place-items-center rounded-md border border-line text-secondary transition-colors hover:bg-subtle disabled:opacity-40"
      >
        <ChevronRight size={14} />
      </button>
    </div>
  );
}

function StatusTag({ value }) {
  const tone = ['complete', 'done'].includes(value) ? 'success' : value === 'failed' ? 'danger' : ['running', 'running'].includes(value) ? 'accent' : 'neutral';
  return <Badge tone={tone}>{STATES[value] || value || EMPTY}</Badge>;
}

const STATES = {
  pending: '等待执行', running: '执行中', done: '已完成', complete: '已完成',
  failed: '失败', cancelled: '已停止', notice: '互动通知', profile: '账号资料',
  works: '作品采集', likers: '点赞名单', comments: '评论采集',
};

/* -------------------------------------------------------------- 素材库 */

export function Library({ openFile, openConversation, job, startJob, notify }) {
  const [data, setData] = useState(null);
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);

  async function load() {
    try { setData(await api(`/library?${new URLSearchParams({ query, offset, count: 40 })}`)); } catch (error) { notify(error.message); }
  }
  useEffect(() => { const timer = setTimeout(load, 180); return () => clearTimeout(timer); }, [query, offset, job?.state]);

  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <div className="mx-auto w-full max-w-[1180px] px-8 py-7">
        <PageHeader title="素材库" subtitle="对话中的原始文件，以及逐项保存的素材观察。">
          <Button variant="secondary" size="sm" onClick={load}>
            <RefreshCw size={14} /> 刷新素材
          </Button>
        </PageHeader>

        <Toolbar value={query} onChange={(value) => { setQuery(value); setOffset(0); }} placeholder="搜索文件名称">
          <span className="text-[11px] text-muted">{data?.total || 0} 个附件</span>
        </Toolbar>

        {!data ? <Loader /> : !data.rows.length ? (
          <EmptyState
            icon={FolderOpen}
            title="把素材放进对话里"
            desc="拖入图片、视频、文档或压缩包，源镜会保存原件和分析进度。"
            action={<Button variant="secondary" size="sm" onClick={() => openConversation(null)}>回到工作台</Button>}
          />
        ) : (
          <div className="flex flex-col divide-y divide-line rounded-[12px] border border-line bg-bg">
            {data.rows.map((item) => (
              <div key={item.id} className="flex items-center gap-5 px-4 py-3.5 transition-colors hover:bg-subtle/60">
                <FileTile item={item} onOpen={openFile} />
                <div className="min-w-0 flex-1">
                  <strong className="block text-[12px] font-medium text-text">
                    {item.workspace?.total
                      ? `${item.workspace.total} 项素材`
                      : { image: '图片', video: '视频', archive: '压缩包' }[item.kind] || '文件'}
                  </strong>
                  <span className="mt-1.5 block text-[11px] text-muted">
                    {item.workspace?.visual_total
                      ? `总览 ${item.workspace.overviewed}/${item.workspace.visual_total} · 细看 ${item.workspace.inspected}`
                      : ({ ready: '已读取', partial: '部分读取', pending: '等待处理', failed: '待继续处理' }[item.status] || '原件已保留')}
                  </span>
                </div>
                <time className="shrink-0 text-[11px] text-muted">{dateLabel(item.created_at)}</time>
                <Button variant="ghost" size="sm" onClick={() => openConversation(item.conversation_id)}>
                  打开会话 <ArrowUpRight size={13} />
                </Button>
              </div>
            ))}
          </div>
        )}

        {data?.total ? (
          <Pager
            label={`${offset + 1}–${Math.min(offset + 40, data.total)} / ${data.total}`}
            canPrev={!!offset}
            canNext={offset + 40 < data.total}
            onPrev={() => setOffset(Math.max(0, offset - 40))}
            onNext={() => setOffset(offset + 40)}
          />
        ) : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------ 数据 / 受众 / 任务 */

const VIEWS = {
  works: {
    title: '作品数据', subtitle: '作品表现、互动数据和可追溯的指标来源。', icon: BarChart3,
    columns: [['作品', 'description'], ['播放', 'play_count'], ['点赞', 'digg_count'], ['评论', 'comment_count'], ['分享', 'share_count'], ['发布时间', 'create_time']],
  },
  users: {
    title: '互动受众', subtitle: '从真实互动出发，了解内容正在吸引谁。', icon: Users,
    columns: [['互动者', 'nickname'], ['互动作品', 'interaction_works'], ['粉丝', 'follower_count'], ['已采样作品', 'sample_count'], ['资料状态', 'data_status']],
  },
  tasks: {
    title: '执行记录', subtitle: '查看采集任务、执行状态与未完成的工作。', icon: Database,
    columns: [['任务', 'kind'], ['目标', 'target'], ['状态', 'state'], ['尝试次数', 'attempts'], ['更新时间', 'updated_at']],
  },
};

const SEGMENTS = [
  ['raw', '全部互动者'], ['active', '有效互动'], ['repeated', '多作品互动'],
  ['incomplete', '资料待补'], ['unsampled', '尚未采样'],
];

const FIELD_LABEL = {
  sec_uid: '账号编号', aweme_id: '作品编号', metric_note: '指标来源', signature: '简介',
  error: '异常信息', last_error: '异常信息', content_notes: '内容备注',
};

export function DataPage({ view, startJob, busy, notify }) {
  const info = VIEWS[view];
  const [data, setData] = useState(null);
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);
  const [segment, setSegment] = useState('raw');
  const [detail, setDetail] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [selected, setSelected] = useState([]);

  async function load() {
    try { setData(await api(`/page/${view}?${new URLSearchParams({ search: query, page, segment })}`)); } catch (error) { notify(error.message); }
  }
  useEffect(() => { setPage(0); setSelected([]); setDetail(null); }, [view]);
  useEffect(() => { const timer = setTimeout(load, 180); return () => clearTimeout(timer); }, [view, query, page, segment, busy]);

  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <div className="mx-auto w-full max-w-[1180px] px-8 py-7">
        <PageHeader title={info.title} subtitle={info.subtitle}>
          <Button variant="secondary" size="sm" onClick={load}>
            <RefreshCw size={14} /> 刷新
          </Button>
          {view !== 'tasks' ? (
            <Button size="sm" disabled={busy} onClick={() => startJob('collect', { kinds: 'quick' })}>
              <RefreshCw size={14} /> 同步互动数据
            </Button>
          ) : null}
        </PageHeader>

        {view === 'users' ? (
          <div className="mb-4 flex gap-1 border-b border-line">
            {SEGMENTS.map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => { setSegment(key); setPage(0); }}
                className={cn(
                  'relative -mb-px border-b-2 px-3 pb-2.5 pt-1 text-[12px] transition-colors',
                  segment === key ? 'border-accent font-medium text-text' : 'border-transparent text-muted hover:text-secondary',
                )}
              >
                {label}
              </button>
            ))}
          </div>
        ) : null}

        <Toolbar
          value={query}
          onChange={(value) => { setQuery(value); setPage(0); }}
          placeholder={view === 'users' ? '搜索昵称或账号 ID' : '搜索内容或编号'}
        >
          {selected.length ? (
            <Button variant="secondary" size="sm" disabled={busy} onClick={() => startJob('collect', { kinds: 'deep', targets: selected })}>
              补充 {selected.length} 人资料
            </Button>
          ) : null}
          <span className="text-[11px] text-muted">{data?.total || 0} 条记录</span>
        </Toolbar>

        {!data ? <Loader /> : !data.rows.length ? (
          <EmptyState
            icon={info.icon}
            title="这里还没有记录"
            desc={view === 'tasks' ? '采集任务执行后，状态会显示在这里。' : '登录抖音并同步数据后，可以在这里查看。'}
          />
        ) : (
          <div className="overflow-auto rounded-[12px] border border-line bg-bg">
            <table className="w-full border-collapse text-left text-[12px]">
              <thead>
                <tr>
                  {view === 'users' ? <th className="w-9" /> : null}
                  {info.columns.map(([label, key]) => (
                    <th key={key} className="whitespace-nowrap bg-[color-mix(in_srgb,var(--subtle)_80%,var(--bg))] px-3.5 py-2.5 text-[10.5px] font-medium uppercase tracking-[0.4px] text-muted">
                      {label}
                    </th>
                  ))}
                  <th className="bg-[color-mix(in_srgb,var(--subtle)_80%,var(--bg))]" />
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row, index) => (
                  <tr key={row.aweme_id || row.sec_uid || row.id || index} className="transition-colors hover:bg-subtle/60">
                    {view === 'users' ? (
                      <td className="pl-3.5">
                        <input
                          type="checkbox"
                          aria-label={`选择 ${row.nickname || row.sec_uid}`}
                          checked={selected.includes(row.sec_uid)}
                          onChange={(event) => setSelected((values) => (
                            event.target.checked ? [...values, row.sec_uid] : values.filter((value) => value !== row.sec_uid)
                          ))}
                          className="h-3.5 w-3.5 accent-[var(--accent)]"
                        />
                      </td>
                    ) : null}
                    {info.columns.map(([, key], columnIndex) => (
                      <td key={key} className={cn('max-w-[340px] border-t border-line px-3.5 py-3 align-middle leading-relaxed text-text', columnIndex === 0 && 'min-w-[160px]')}>
                        {['create_time', 'updated_at'].includes(key) ? (
                          dateLabel(typeof row[key] === 'number' ? row[key] * 1000 : row[key])
                        ) : ['state', 'kind'].includes(key) ? (
                          <StatusTag value={row[key]} />
                        ) : (
                          <span className={columnIndex === 0 ? 'line-clamp-2' : ''}>{number(row[key])}</span>
                        )}
                      </td>
                    ))}
                    <td className="border-t border-line px-3 py-3 text-right">
                      <button type="button" onClick={() => setDetail(row)} className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11.5px] text-secondary transition-colors hover:bg-subtle hover:text-text">
                        详情 <ChevronRight size={12} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {data?.total ? (
          <Pager
            label={`第 ${data.page + 1} 页 · 共 ${data.total} 条`}
            canPrev={!!data.page}
            canNext={(data.page + 1) * data.page_size < data.total}
            onPrev={() => setPage(data.page - 1)}
            onNext={() => setPage(data.page + 1)}
          />
        ) : null}

        {detail ? (
          <Modal title={detail.description || detail.nickname || '记录详情'} onClose={() => setDetail(null)}>
            <div className="max-h-[70vh] overflow-auto px-6 py-5">
              {view === 'works' ? (
                <div className="mb-5 flex gap-2.5">
                  <Button variant="secondary" size="sm" onClick={() => { setMetrics(detail); setDetail(null); }}>补录后台指标</Button>
                  <Button variant="secondary" size="sm" disabled={busy} onClick={() => startJob('comments', { aweme_id: detail.aweme_id })}>同步评论</Button>
                </div>
              ) : null}
              <dl className="grid grid-cols-[110px_1fr] gap-x-4 gap-y-3 text-[12px]">
                {Object.entries(detail)
                  .filter(([, value]) => value !== null && value !== '' && typeof value !== 'object')
                  .map(([key, value]) => (
                    <React.Fragment key={key}>
                      <dt className="text-muted">{Object.fromEntries(info.columns.map(([label, k]) => [k, label]))[key] || FIELD_LABEL[key] || key}</dt>
                      <dd className="break-words text-text">{String(value)}</dd>
                    </React.Fragment>
                  ))}
              </dl>
            </div>
          </Modal>
        ) : null}

        {metrics ? (
          <MetricsDialog
            row={metrics}
            onClose={() => setMetrics(null)}
            onSave={() => { setMetrics(null); load(); notify('指标已保存'); }}
            notify={notify}
          />
        ) : null}
      </div>
    </div>
  );
}

function MetricsDialog({ row, onClose, onSave, notify }) {
  const [values, setValues] = useState({
    aweme_id: row.aweme_id,
    measured_at: new Date().toLocaleDateString('en-CA'),
    source: '',
    notes: '',
  });
  const [saving, setSaving] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    try {
      await api('/metrics', { method: 'PUT', body: values });
      onSave();
    } catch (error) {
      notify(error.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="补录后台指标" subtitle="填写实际观测值，缺失项可以留空。" onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-4 overflow-auto px-6 py-5">
        <div className="grid grid-cols-2 gap-4">
          {[['播放', 'play_count'], ['点赞', 'digg_count'], ['评论', 'comment_count'], ['分享', 'share_count']].map(([label, key]) => (
            <Field key={key} label={label}>
              <Input
                type="number"
                min="0"
                placeholder="未填写"
                value={values[key] ?? ''}
                onChange={(event) => setValues({ ...values, [key]: event.target.value === '' ? null : Number(event.target.value) })}
              />
            </Field>
          ))}
        </div>
        <Field label="观测日期">
          <Input type="date" required value={values.measured_at} onChange={(event) => setValues({ ...values, measured_at: event.target.value })} />
        </Field>
        <Field label="指标来源">
          <Input required placeholder="例如：抖音后台截图名称" value={values.source} onChange={(event) => setValues({ ...values, source: event.target.value })} />
        </Field>
        <Field label="备注">
          <Textarea rows={2} value={values.notes} onChange={(event) => setValues({ ...values, notes: event.target.value })} />
        </Field>
        <div className="flex justify-end gap-2.5 pt-1">
          <Button variant="secondary" onClick={onClose}>取消</Button>
          <Button type="submit" disabled={saving}>{saving ? '保存中…' : '保存指标'}</Button>
        </div>
      </form>
    </Modal>
  );
}

/* ------------------------------------------------------------ 对标账号 */

export function Benchmarks({ startJob, busy, notify }) {
  const [rows, setRows] = useState([]);
  const [url, setUrl] = useState('');

  async function load() {
    try { setRows(await api('/benchmarks')); } catch (error) { notify(error.message); }
  }
  useEffect(() => { load(); }, [busy]);

  async function add(event) {
    event.preventDefault();
    try {
      await api('/benchmarks', { method: 'POST', body: { url } });
      setUrl('');
      load();
    } catch (error) { notify(error.message); }
  }

  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <div className="mx-auto w-full max-w-[1180px] px-8 py-7">
        <PageHeader title="对标账号" subtitle="记录值得持续观察的账号，查看它们的内容与更新。">
          <Button size="sm" disabled={busy || !rows.length} onClick={() => startJob('benchmark', {})}>
            <RefreshCw size={14} /> 检查更新
          </Button>
        </PageHeader>

        <form onSubmit={add} className="mb-6 flex gap-3">
          <Input
            className="max-w-[560px] flex-1"
            placeholder="粘贴抖音主页链接或账号 ID"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
          />
          <Button variant="secondary" size="sm" type="submit" disabled={!url.trim()}>
            <Plus size={14} /> 添加账号
          </Button>
        </form>

        {!rows.length ? (
          <EmptyState icon={Users} title="建立你的观察名单" desc="添加对标账号，积累内容参考与选题线索。" />
        ) : (
          <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(290px,1fr))]">
            {rows.map((row) => (
              <Card key={row.sec_uid} className="transition-[transform,box-shadow] hover:-translate-y-0.5 hover:shadow-[var(--shadow-2)]">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2.5">
                    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[11px] border border-line bg-[color-mix(in_srgb,var(--accent)_10%,var(--bg))] text-[13px] font-semibold text-accent">
                      {(row.display_name || row.nickname || '账')[0]}
                    </span>
                    <div className="min-w-0">
                      <strong className="block truncate text-[13px] font-[550] text-text">{row.display_name || row.nickname || '对标账号'}</strong>
                      <p className="mt-1 truncate text-[10px] text-muted">{row.sec_uid}</p>
                    </div>
                  </div>
                  <button
                    type="button"
                    aria-label="移出观察名单"
                    onClick={async () => {
                      await api(`/benchmarks/${encodeURIComponent(row.sec_uid)}`, { method: 'DELETE' });
                      load();
                    }}
                    className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-muted transition-colors hover:bg-subtle hover:text-danger"
                  >
                    <X size={14} />
                  </button>
                </div>

                <div className="mt-3.5 flex items-center justify-between border-t border-line pt-3 text-[11px] text-muted">
                  <span>已记录 {row.works?.length || 0} 条作品</span>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => startJob('benchmark', { sec_uid: row.sec_uid })}
                    className="inline-flex items-center gap-1 text-secondary transition-colors hover:text-text disabled:opacity-40"
                  >
                    同步更新 <ChevronRight size={12} />
                  </button>
                </div>

                {(row.works || []).slice(0, 3).map((work) => (
                  <div key={work.aweme_id} className="mt-2.5 flex items-start justify-between gap-3 border-t border-line pt-2.5 text-[11px]">
                    <p className="line-clamp-2 leading-relaxed text-secondary">{work.description || '未命名作品'}</p>
                    <span className="whitespace-nowrap text-muted">点赞 {number(work.digg_count)}</span>
                  </div>
                ))}
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ 分析报告 */

export function Reports({ notify, startJob, busy }) {
  const [workspace, setWorkspace] = useState(null);
  const [report, setReport] = useState(null);
  const [content, setContent] = useState('');
  const [editing, setEditing] = useState(false);
  const [reviewed, setReviewed] = useState(false);

  async function load() {
    try { setWorkspace(await api('/enterprise')); } catch (error) { notify(error.message); }
  }
  useEffect(() => { load(); }, [busy]);

  async function open(id) {
    try {
      const value = await api(`/reports/${id}`);
      setReport(value);
      setContent(value.revisions?.at(-1)?.content || value.rendered || JSON.stringify(value.output, null, 2));
      setReviewed(value.revisions?.at(-1)?.reviewed || false);
    } catch (error) { notify(error.message); }
  }

  async function save() {
    try {
      await api(`/reports/${report.id}`, { method: 'POST', body: { content, reason: 'HTML 工作台修改', reviewed } });
      notify('修改已保存');
      setReport(null);
      load();
    } catch (error) { notify(error.message); }
  }

  function exportMarkdown() {
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([content], { type: 'text/markdown' }));
    link.download = `${report.title || '传播方案'}.md`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  const rows = workspace?.reports || [];

  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <div className="mx-auto w-full max-w-[1180px] px-8 py-7">
        <PageHeader title="分析报告" subtitle="保存的方案、复盘和修改记录。">
          <Button size="sm" disabled={busy} onClick={() => startJob('enterprise', {})}>
            <Plus size={14} /> 生成报告
          </Button>
        </PageHeader>

        {!rows.length ? (
          <EmptyState icon={FileText} title="把分析沉淀成可执行的方案" desc="对话生成的传播方案和复盘会保存在这里。" />
        ) : (
          <div className="flex flex-col gap-2.5">
            {rows.map((row) => (
              <button
                key={row.id}
                type="button"
                onClick={() => open(row.id)}
                className="flex items-center gap-4 rounded-[12px] border border-line bg-bg px-4 py-4 text-left transition-[transform,box-shadow,border-color] duration-150 hover:-translate-y-0.5 hover:border-[color-mix(in_srgb,var(--accent)_28%,var(--line))] hover:shadow-[var(--shadow-2)]"
              >
                <span className="grid h-11 w-11 shrink-0 place-items-center rounded-[11px] bg-[color-mix(in_srgb,var(--accent)_9%,var(--subtle))] text-accent">
                  <FileText size={20} />
                </span>
                <span className="min-w-0 flex-1">
                  <strong className="block truncate text-[13px] font-medium text-text">{row.title || `传播方案 ${row.id}`}</strong>
                  <small className="mt-1.5 block text-[11px] text-muted">
                    {dateLabel(row.created_at)} · {row.reviewed ? '已复核' : '待复核'}
                  </small>
                </span>
                <ChevronRight size={16} className="text-muted" />
              </button>
            ))}
          </div>
        )}

        {report ? (
          <Modal
            title={report.title || '传播方案'}
            onClose={() => setReport(null)}
            className="h-[calc(100dvh-90px)] w-[min(1000px,100%)]"
            actions={(
              <>
                <Button variant="secondary" size="sm" onClick={() => setEditing(!editing)}>{editing ? '预览' : '编辑'}</Button>
                <Button variant="secondary" size="sm" onClick={exportMarkdown}><Download size={13} /> 导出</Button>
              </>
            )}
          >
            <div className="min-h-0 flex-1 overflow-auto px-8 py-6 text-[13px] leading-[1.9] text-text">
              {editing ? (
                <textarea
                  value={content}
                  onChange={(event) => setContent(event.target.value)}
                  className="h-full min-h-[420px] w-full resize-none border-0 bg-transparent text-[13px] leading-[1.9] text-text outline-none"
                />
              ) : (
                <Markdown text={content} />
              )}
            </div>
            <footer className="flex shrink-0 items-center justify-between border-t border-line px-6 py-3">
              <label className="flex cursor-pointer items-center gap-2 text-[12px] text-secondary">
                <input type="checkbox" checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} className="h-3.5 w-3.5 accent-[var(--accent)]" />
                已人工复核
              </label>
              <Button size="sm" onClick={save}>保存修改</Button>
            </footer>
          </Modal>
        ) : null}
      </div>
    </div>
  );
}


/* ------------------------------------------------------------ 实时热点 */

const MARK_TONE = {
  可用: 'bg-[color-mix(in_srgb,var(--accent)_14%,var(--bg))] text-accent',
  参考: 'bg-subtle text-secondary',
  无关: 'bg-subtle text-muted',
};

export function Hot({ job, busy, startJob, onAsk, notify }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  function load() {
    api('/hot')
      .then((value) => setData(value))
      .catch((error) => notify(error.message))
      .finally(() => setLoading(false));
  }

  // 抓取任务结束后重新读一次（网关会把带 AI 评估的结果留在内存里）
  useEffect(() => { load(); }, [job?.state]);

  const topics = data?.topics || [];
  const refreshing = job?.kind === 'hot' && job?.state === 'running';
  const stamp = data?.fetched_at ? data.fetched_at.replace('T', ' ').slice(0, 16) : '';

  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <div className="mx-auto w-full max-w-[1180px] px-8 py-7">
        <PageHeader title="实时热点" subtitle="抖音实时热榜，并按企业资料标出哪些能直接做内容。">
          <Button variant="secondary" size="sm" disabled={refreshing || busy} onClick={() => startJob('hot')}>
            {refreshing ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
            {refreshing ? '正在获取…' : '刷新热点'}
          </Button>
        </PageHeader>

        {data?.note ? <p className="mb-4 text-[11px] text-muted">{data.note}</p> : null}

        {data?.error ? (
          <div className="mb-4 flex items-start gap-2 rounded-[10px] border border-[color-mix(in_srgb,var(--danger)_28%,var(--line))] bg-[color-mix(in_srgb,var(--danger)_7%,var(--bg))] px-3.5 py-3 text-[12px] leading-relaxed text-danger">
            <CircleAlert size={14} className="mt-px shrink-0" />
            {data.error}
          </div>
        ) : null}

        {loading ? <Loader /> : !topics.length ? (
          <EmptyState
            icon={Flame}
            title="还没有热点数据"
            desc="点「刷新热点」会打开抖音热榜抓一次，并按企业资料给每条打可用性标记。"
            action={<Button size="sm" disabled={busy} onClick={() => startJob('hot')}>刷新热点</Button>}
          />
        ) : (
          <ol className="m-0 list-none overflow-hidden rounded-[12px] border border-line bg-bg p-0">
            {topics.map((topic, index) => (
              <li
                key={`${topic.word}-${index}`}
                className="flex items-center gap-4 border-b border-line px-4 py-3 last:border-b-0 transition-colors hover:bg-subtle/60"
              >
                <span className={cn('w-5 shrink-0 text-center font-mono text-[11px]', index < 3 ? 'text-accent' : 'text-muted')}>
                  {index + 1}
                </span>
                <button
                  type="button"
                  onClick={() => onAsk(`借势分析抖音热点：「${topic.word}」${topic.heat ? `（当前热度 ${topic.heat}）` : ''}，结合我的账号定位给一个能直接执行的选题。`)}
                  className="min-w-0 flex-1 text-left"
                >
                  <strong className="block truncate text-[12.5px] font-medium text-text">{topic.word}</strong>
                  {topic.why ? <small className="mt-1 block truncate text-[11px] text-muted">{topic.why}</small> : null}
                </button>
                {topic.mark ? (
                  <span className={cn('shrink-0 rounded-full px-2 py-[3px] text-[10.5px]', MARK_TONE[topic.mark] || MARK_TONE['参考'])}>
                    {topic.mark}
                  </span>
                ) : null}
                <span className="w-[72px] shrink-0 text-right text-[11px] text-muted">{topic.heat ? number(topic.heat) : EMPTY}</span>
                <ArrowUpRight size={13} className="shrink-0 text-muted" />
              </li>
            ))}
          </ol>
        )}

        {topics.length ? (
          <p className="mt-4 text-[11px] text-muted">
            {stamp ? `抓取时间 ${stamp}` : ''}
            {data?.usable ? ` · 其中 ${data.usable} 条可直接用` : ''}
            {' · 点任意一条交给团队拆解'}
          </p>
        ) : null}
      </div>
    </div>
  );
}
