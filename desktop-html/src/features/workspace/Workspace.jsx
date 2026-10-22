import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  ArrowDown, ArrowUp, ArrowUpRight, ChevronDown, CircleAlert, FolderArchive, Image as ImageIcon,
  ListChecks, Loader2, MoreHorizontal, Plus, Square, X, BarChart3, Sparkles,
} from 'lucide-react';
import {
  Choices, CopyButton, FileTile, Markdown, Thought, ToolSteps, parseChoices,
} from '../../components.jsx';
import { Button, cn } from '../../ui/kit.jsx';

const STARTERS = [
  { icon: ImageIcon, title: '分析一组素材', text: '请帮我梳理这些素材，分析主要内容，并给出适合的使用方向。', note: '图片、视频与压缩包' },
  { icon: BarChart3, title: '复盘作品表现', text: '请结合当前账号的作品与互动数据，分析表现、受众反馈和下一步优化方向。', note: '从数据中发现线索' },
  { icon: Sparkles, title: '制定内容方案', text: '请结合企业资料、现有作品和受众信息，帮我制定一份可执行的内容传播方案。', note: '把想法变成行动' },
];

const STATUS_TEXT = {
  complete: '已完成', cancelled: '已停止', failed: '未完成',
  running: '执行中', partial: '部分完成', needs_review: '待核对',
};

/* --------------------------------------------------------------- 欢迎页 */

function Welcome({ onPick, onDropHint }) {
  const [draftSeed, setDraftSeed] = useState(null);
  return (
    <div className="mx-auto max-w-[700px] px-6 pb-6 pt-[clamp(40px,10vh,120px)] text-center">
      <div
        className="mx-auto mb-[22px] grid h-[62px] w-[62px] place-items-center rounded-[19px] border border-line shadow-[0_6px_22px_rgb(20_30_60/0.07)]"
        style={{ background: 'linear-gradient(160deg, color-mix(in srgb, var(--accent) 10%, var(--bg)), var(--bg))' }}
      >
        <img src="/brand.png" alt="" className="h-10 w-10" />
      </div>
      <span className="mb-3.5 block text-[10.5px] tracking-[2.4px] text-muted">你的内容工作伙伴</span>
      <h1 className="text-[30px] font-[560] leading-[1.45] tracking-[-1px] text-text">今天，想完成什么？</h1>
      <p className="mt-3 text-[13px] leading-relaxed text-muted">把资料、素材和想法交给源镜，一起找到下一步。</p>

      <div className="mt-8 grid grid-cols-3 gap-3 text-left">
        {STARTERS.map(({ icon: Icon, title, text, note }, index) => (
          <button
            key={title}
            type="button"
            onClick={() => onPick(text)}
            style={{ animationDelay: `${0.16 + index * 0.05}s` }}
            className="group relative min-h-[118px] animate-[rise-in_.42s_cubic-bezier(.22,1,.36,1)_both] rounded-[14px] border border-line bg-bg p-4 pb-4 pt-[18px] text-left transition-[transform,box-shadow,border-color] duration-150 hover:-translate-y-[3px] hover:border-[color-mix(in_srgb,var(--accent)_34%,var(--line))] hover:shadow-[0_10px_28px_rgb(20_30_60/0.09)]"
          >
            <Icon size={21} strokeWidth={1.45} className="mb-3.5 text-accent" />
            <strong className="block text-[13.5px] font-[550] text-text">{title}</strong>
            <span className="mt-1.5 block text-[11px] leading-relaxed text-muted">{note}</span>
            <ArrowUpRight size={15} className="absolute right-3.5 top-5 text-muted opacity-0 transition-opacity group-hover:opacity-100" />
          </button>
        ))}
      </div>

      <button
        type="button"
        onClick={onPick}
        className="mx-auto mt-[22px] flex items-center gap-1.5 text-[11px] text-muted transition-colors hover:text-secondary"
      >
        <FolderArchive size={15} />
        也可以直接拖入图片、视频、文档或压缩包
      </button>
    </div>
  );
}

/* ---------------------------------------------------------------- 消息 */

function Message({ message, onOpen }) {
  const user = message.role === 'user';
  const error = message.role === 'error';
  const parsed = parseChoices(message.content || '');
  const files = (message.attachments || []).filter((item) => !item.generated);
  const generated = (message.attachments || []).filter((item) => item.generated);

  return (
    <article className={cn('group mb-6', user && 'ml-auto w-fit max-w-[85%]')}>
      <div className={cn('mb-[7px] flex min-h-[24px] items-center gap-2 text-[11.5px] text-secondary', user && 'justify-end')}>
        {user ? (
          <span>你</span>
        ) : (
          <>
            <img src="/brand.png" alt="" className="h-[19px] w-[19px]" />
            <strong className="font-[550]">{error ? '执行提示' : '源镜'}</strong>
          </>
        )}
        <span className="opacity-0 transition-opacity group-hover:opacity-100">
          <CopyButton text={message.content || ''} />
        </span>
      </div>

      {files.length ? (
        <div className={cn('mb-3 flex flex-wrap gap-2.5', user && 'justify-end')}>
          {files.map((item) => <FileTile key={item.id || item.name} item={item} onOpen={onOpen} />)}
        </div>
      ) : null}

      {!user && message.reasoning ? <Thought text={message.reasoning} /> : null}

      {user ? (
        <div className="whitespace-pre-wrap break-words rounded-[14px_14px_4px_14px] border border-[color-mix(in_srgb,var(--accent)_14%,var(--line))] bg-[color-mix(in_srgb,var(--accent)_9%,var(--bg))] px-[15px] py-[11px] text-[13.5px] leading-[1.8] text-text">
          {message.content}
        </div>
      ) : (
        <div className={cn('text-[13.5px] leading-[1.9] text-text', error && 'rounded-[10px] border border-[color-mix(in_srgb,var(--danger)_20%,var(--line))] bg-[color-mix(in_srgb,var(--danger)_5%,var(--bg))] px-4 py-3.5')}>
          <Markdown text={parsed.text} />
        </div>
      )}

      {parsed.questions.length ? <Choices questions={parsed.questions} onSend={() => {}} /> : null}

      {generated.length ? (
        <div className="mt-4 flex flex-wrap gap-2.5">
          {generated.map((item) => <FileTile key={item.id} item={item} onOpen={onOpen} />)}
        </div>
      ) : null}
    </article>
  );
}

function StreamingMessage({ job }) {
  return (
    <article className="mb-6">
      <div className="mb-[7px] flex min-h-[24px] items-center gap-2 text-[11.5px] text-secondary">
        <img src="/brand.png" alt="" className="h-[19px] w-[19px]" />
        <strong className="font-[550]">源镜</strong>
        <span className="flex items-center gap-1.5 text-[11px] text-muted">
          <i className="h-1 w-1 animate-pulse rounded-full bg-accent" />
          正在处理
        </span>
      </div>
      <Thought text={job.reasoning} running={!job.answer} />
      <ToolSteps items={job.tools} running />
      {job.answer ? (
        <div className="text-[13.5px] leading-[1.9] text-text">
          <Markdown text={parseChoices(job.answer).text.replace(/```choices[\s\S]*$/, '')} />
        </div>
      ) : (
        <div className="flex items-center gap-2 py-2 text-[12px] text-muted">
          <Loader2 size={14} className="spin" />
          <span>{job.message || '正在准备…'}</span>
        </div>
      )}
      {Object.values(job.confirmations || {}).map((item) => (
        <div key={item.request_id} className="my-3.5 rounded-[12px] border border-[color-mix(in_srgb,#c79d56_35%,var(--line))] bg-[color-mix(in_srgb,#e8c78b_7%,var(--bg))] p-4">
          <div className="mb-3 flex items-center gap-2 text-[13px] text-text">
            <CircleAlert size={18} />
            <strong>允许执行「{item.name}」？</strong>
          </div>
          <details className="text-[11.5px] text-secondary">
            <summary className="cursor-pointer">查看操作内容</summary>
            <pre className="mt-2 max-h-[220px] overflow-auto whitespace-pre-wrap rounded-[6px] bg-bg p-2.5 text-[11px]">{item.detail}</pre>
          </details>
          <div className="mt-3.5 flex gap-2">
            <Button size="sm" onClick={() => window.dispatchEvent(new CustomEvent('scout:confirm', { detail: { request_id: item.request_id, approved: true } }))}>允许这次</Button>
            <Button size="sm" variant="secondary" onClick={() => window.dispatchEvent(new CustomEvent('scout:confirm', { detail: { request_id: item.request_id, approved: false } }))}>拒绝</Button>
          </div>
        </div>
      ))}
      {job.artifacts?.length ? (
        <div className="mt-4 flex flex-wrap gap-2.5">
          {job.artifacts.map((item) => <FileTile key={item.id} item={item} onOpen={() => {}} />)}
        </div>
      ) : null}
    </article>
  );
}

/* -------------------------------------------------------------- 输入区 */

function Composer({
  draft, onDraft, uploads, onRemoveUpload, onOpenFile, onPickFiles, onAddFiles,
  onSend, onStop, sending, active, ready, pendingSteer, model, engine, onOpenSettings, hint,
}) {
  const textarea = useRef(null);
  const canSend = active ? !!ready : draft.trim().length > 0 || uploads.length > 0;

  useLayoutEffect(() => {
    const node = textarea.current;
    if (!node) return;
    node.style.height = 'auto';
    node.style.height = `${Math.min(180, node.scrollHeight)}px`;
  }, [draft]);

  const handlePaste = (event) => {
    const files = [...(event.clipboardData?.items || [])]
      .filter((item) => item.kind === 'file')
      .map((item) => item.getAsFile())
      .filter(Boolean);
    if (files.length) {
      event.preventDefault();
      onAddFiles(files);
    }
  };

  return (
    <div className="mx-auto w-full max-w-[760px] shrink-0 px-[26px] pb-3.5 pt-1">
      <div
        className={cn(
          'overflow-hidden rounded-[18px] border bg-bg shadow-[0_6px_24px_rgb(20_30_60/0.07)] transition-[border-color,box-shadow] duration-150',
          'border-[color-mix(in_srgb,var(--muted)_28%,var(--line))] focus-within:border-[color-mix(in_srgb,var(--accent)_45%,var(--line))]',
          'focus-within:shadow-[0_6px_26px_rgb(20_30_60/0.1),0_0_0_3px_color-mix(in_srgb,var(--accent)_22%,transparent)]',
        )}
      >
        {uploads.length ? (
          <div className="flex gap-2.5 overflow-x-auto px-3.5 pt-3.5">
            {uploads.map((item) => (
              <FileTile
                compact
                key={item.localId || item.id}
                item={item}
                onOpen={onOpenFile}
                onRemove={() => onRemoveUpload(item)}
              />
            ))}
          </div>
        ) : null}

        <textarea
          ref={textarea}
          aria-label="发送给源镜的消息"
          rows={2}
          value={draft}
          onChange={(event) => onDraft(event.target.value)}
          onPaste={handlePaste}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              onSend();
            }
          }}
          placeholder={active && ready ? '补充要求，按 Enter 追加到当前任务…' : '说说你的想法，或拖入文件…'}
          className="block min-h-[74px] max-h-[180px] w-full resize-none border-0 bg-transparent px-4 pb-1.5 pt-4 text-[13.5px] leading-[1.85] text-text outline-none placeholder:text-muted"
        />

        <div className="flex items-center justify-between px-3 pb-2.5 pt-1">
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              aria-label="添加文件"
              onClick={onPickFiles}
              className="grid h-8 w-8 place-items-center rounded-[8px] text-secondary transition-colors hover:bg-subtle hover:text-text"
            >
              <Plus size={17} />
            </button>
            <button
              type="button"
              title="更改模型"
              onClick={onOpenSettings}
              className="flex items-center gap-1.5 rounded-full border border-line bg-subtle px-2 py-1 text-[10.5px] text-secondary transition-colors hover:border-[color-mix(in_srgb,var(--accent)_30%,var(--line))] hover:text-text"
            >
              {model}
              <ChevronDown size={12} />
            </button>
            {engine === 'codex' ? (
              <span className="rounded border border-line px-1.5 py-[3px] text-[10px] text-muted">Codex</span>
            ) : null}
          </div>

          <div className="flex items-center gap-2.5">
            <span className="text-[10px] text-muted">
              {active ? (ready ? 'Enter 追加要求' : '正在执行任务') : 'Enter 发送'}
            </span>
            {active && draft.trim() && ready ? (
              <button
                type="button"
                disabled={pendingSteer}
                onClick={onSend}
                className="rounded-md px-1.5 py-1 text-[11px] text-accent transition-opacity hover:opacity-80 disabled:opacity-50"
              >
                {pendingSteer ? '正在送达…' : '追加要求'}
              </button>
            ) : null}
            <button
              type="button"
              aria-label={active ? '停止生成' : '发送消息'}
              disabled={sending || !canSend}
              onClick={active ? onStop : onSend}
              className={cn(
                'grid h-8 w-8 place-items-center rounded-full transition-[transform,filter,opacity] duration-150',
                active ? 'bg-text text-bg' : 'bg-accent text-white',
                'hover:-translate-y-px hover:brightness-105 disabled:pointer-events-none disabled:opacity-30',
              )}
            >
              {sending ? <Loader2 size={15} className="spin" /> : active ? <Square size={12} fill="currentColor" /> : <ArrowUp size={18} />}
            </button>
          </div>
        </div>
      </div>

      <div className="flex justify-between gap-3 px-1 pt-2 text-[10px] text-muted">
        <span>内容仅供参考，重要信息请核实。</span>
        <span className="truncate">{hint || 'Shift + Enter 换行'}</span>
      </div>
    </div>
  );
}

/* --------------------------------------------------------- 执行记录面板 */

function Inspector({ conversation, job, onClose }) {
  const run = conversation?.chat_run;
  return (
    <aside className="flex w-[300px] shrink-0 flex-col overflow-auto border-l border-line bg-subtle px-4 pb-5">
      <header className="flex items-center justify-between py-3 text-[12.5px] text-text">
        <strong className="font-[550]">执行记录</strong>
        <button type="button" aria-label="关闭执行记录" onClick={onClose} className="grid h-6 w-6 place-items-center rounded-md text-muted hover:bg-hover hover:text-text">
          <X size={14} />
        </button>
      </header>
      {run ? (
        <>
          <div className="grid grid-cols-2 gap-2 border-t border-line py-3 text-[11.5px]">
            <span className="text-muted">状态</span>
            <b className="text-right font-medium text-text">{STATUS_TEXT[run.status] || run.status}</b>
            <span className="text-muted">操作次数</span>
            <b className="text-right font-medium text-text">{run.tool_count}</b>
          </div>
          {(run.calls || []).map((item) => (
            <details key={item.id} className="border-t border-line py-2.5 text-[11px]">
              <summary className="flex cursor-pointer items-center gap-1.5 text-secondary">
                {item.result?.ok ? '✓' : '!'}
                {item.tool}
              </summary>
              <pre className="mt-2 max-h-[300px] overflow-auto whitespace-pre-wrap break-all rounded-md bg-bg p-2.5 font-mono text-[10px] text-secondary">
                {JSON.stringify(item.result || { status: item.status }, null, 2)}
              </pre>
            </details>
          ))}
        </>
      ) : (
        <ToolSteps items={job?.tools} />
      )}
    </aside>
  );
}

/* -------------------------------------------------------------- 工作区 */

export default function Workspace({
  conversation, cid, job, active, busy, settings, connection,
  draft, onDraft, uploads, onRemoveUpload, onPickFiles, onAddFiles,
  onSend, onStop, sending, pendingSteer, onOpenFile, onOpenSettings,
  inspector, onToggleInspector, onOpenRunningJob, onResume, onRename, onFork, onCompact,
}) {
  const scroller = useRef(null);
  const follow = useRef(true);
  const [unfollowed, setUnfollowed] = useState(false);
  const [menu, setMenu] = useState(false);
  const messages = conversation?.messages || [];

  useEffect(() => {
    const node = scroller.current;
    if (!node) return;
    if (follow.current) node.scrollTop = node.scrollHeight;
  }, [job?.answer, job?.reasoning, job?.tools?.length, messages.length, cid]);

  const onScroll = (event) => {
    const node = event.currentTarget;
    follow.current = node.scrollHeight - node.scrollTop - node.clientHeight < 110;
    setUnfollowed(!follow.current);
  };

  const toBottom = () => {
    follow.current = true;
    setUnfollowed(false);
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' });
  };

  const seed = (text) => {
    onDraft(text);
    document.querySelector('textarea[aria-label="发送给源镜的消息"]')?.focus();
  };

  const run = conversation?.chat_run;
  const showResume = !active && run && !['complete', 'partial'].includes(run.status);

  return (
    <main className="col-start-2 row-start-2 flex min-h-0 min-w-0 flex-col bg-bg">
      <header className="flex h-[52px] shrink-0 items-center justify-between gap-4 border-b border-line bg-[color-mix(in_srgb,var(--bg)_92%,var(--sidebar))] px-5">
        <div className="flex min-w-0 items-center gap-2 text-[11.5px]">
          <span className="whitespace-nowrap text-muted">工作台</span>
          <ChevronDown size={11} className="rotate-[-90deg] text-muted" />
          <strong className="truncate font-[550] text-text">{conversation?.title || '新对话'}</strong>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {busy && job.conversation_id !== cid ? (
            <button
              type="button"
              onClick={() => onOpenRunningJob(job.conversation_id)}
              className="flex items-center gap-1.5 rounded-full bg-accent-soft px-2.5 py-1 text-[10.5px] text-accent"
            >
              <Loader2 size={12} className="spin" />
              查看执行中的任务
            </button>
          ) : null}
          <span className="mr-1 flex items-center gap-1.5 rounded-full border border-line px-2 py-1 text-[10.5px] text-muted">
            <i className={cn('h-1 w-1 rounded-full', connection === 'connected' ? 'bg-[#6da98b]' : 'bg-[#d29a55]')} />
            {connection === 'connected' ? '本地已连接' : '正在重新连接'}
          </span>
          <button
            type="button"
            aria-label="查看执行记录"
            disabled={!run && !job}
            onClick={onToggleInspector}
            className="grid h-8 w-8 place-items-center rounded-[8px] text-secondary transition-colors hover:bg-subtle hover:text-text disabled:opacity-40"
          >
            <ListChecks size={16} />
          </button>
          <button
            type="button"
            aria-label="会话操作"
            disabled={!cid || busy}
            onClick={() => setMenu(!menu)}
            className="grid h-8 w-8 place-items-center rounded-[8px] text-secondary transition-colors hover:bg-subtle hover:text-text disabled:opacity-40"
          >
            <MoreHorizontal size={16} />
          </button>
          {menu ? (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setMenu(false)} />
              <div className="absolute right-4 top-[48px] z-20 min-w-[160px] rounded-[11px] border border-line bg-bg p-1.5 shadow-[var(--shadow-2)]">
                {[
                  ['重命名', onRename, false],
                  ['另开方案', onFork, !conversation?.codex],
                  ['整理上下文', onCompact, !conversation?.codex],
                ].map(([label, action, disabled]) => (
                  <button
                    key={label}
                    type="button"
                    disabled={disabled}
                    onClick={() => { setMenu(false); action?.(); }}
                    className="block w-full rounded-[7px] px-2.5 py-2 text-left text-[12px] text-secondary transition-colors hover:bg-subtle hover:text-text disabled:opacity-40"
                  >
                    {label}
                  </button>
                ))}
              </div>
            </>
          ) : null}
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <section className="relative flex min-h-0 min-w-0 flex-1 flex-col">
          <div ref={scroller} onScroll={onScroll} className="flex-1 overflow-auto [scrollbar-gutter:stable]">
            {messages.length || active ? (
              <div className="mx-auto max-w-[760px] px-[26px] pb-6 pt-7">
                {messages.map((message, index) => (
                  <Message key={message.id || index} message={message} onOpen={onOpenFile} />
                ))}
                {active ? <StreamingMessage job={job} /> : null}
                {showResume ? (
                  <div className="mt-2 flex items-center justify-between gap-5 rounded-[12px] border border-[color-mix(in_srgb,var(--accent)_18%,var(--line))] bg-[color-mix(in_srgb,var(--accent)_5%,var(--subtle))] px-4 py-3.5">
                    <div className="flex items-center gap-2.5 text-secondary">
                      <CircleAlert size={17} />
                      <span>
                        <strong className="block text-[12px] font-medium text-text">
                          {run.status === 'cancelled' ? '任务已停止' : '还有未完成的工作'}
                        </strong>
                        <small className="mt-1 block text-[11px] text-muted">已有执行记录和素材进度已保存</small>
                      </span>
                    </div>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={run.status === 'needs_review' || busy}
                      onClick={onResume}
                    >
                      继续任务 <ArrowUpRight size={13} />
                    </Button>
                  </div>
                ) : null}
              </div>
            ) : (
              <Welcome onPick={seed} />
            )}
          </div>

          {unfollowed ? (
            <button
              type="button"
              onClick={toBottom}
              className="absolute bottom-3 left-1/2 z-[2] flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-line bg-bg px-3 py-2 text-[11px] text-secondary shadow-[var(--shadow-2)]"
            >
              <ArrowDown size={14} />
              回到底部
            </button>
          ) : null}

          <Composer
            draft={draft}
            onDraft={onDraft}
            uploads={uploads}
            onRemoveUpload={onRemoveUpload}
            onOpenFile={onOpenFile}
            onPickFiles={onPickFiles}
            onAddFiles={onAddFiles}
            onSend={onSend}
            onStop={onStop}
            sending={sending}
            active={active}
            ready={!!job?.ready}
            pendingSteer={pendingSteer}
            model={settings?.model === 'deepseek-flash' ? 'DeepSeek Flash' : settings?.model === 'deepseek-v4-pro' ? 'DeepSeek V4 Pro' : (settings?.model || 'DeepSeek')}
            engine={settings?.agent_engine}
            onOpenSettings={onOpenSettings}
            hint={active ? job?.message?.slice(0, 45) : ''}
          />
        </section>

        {inspector ? <Inspector conversation={conversation} job={job} onClose={onToggleInspector} /> : null}
      </div>
    </main>
  );
}
