import React from 'react';
import {
  ChevronDown, Loader2, PanelLeftClose, PanelLeftOpen, Search, Settings, SquarePen,
} from 'lucide-react';
import { cn } from '../ui/kit.jsx';

function NavItem({ icon: Icon, label, active, collapsed, onClick }) {
  return (
    <button
      type="button"
      title={label}
      onClick={onClick}
      className={cn(
        'group flex min-h-[34px] w-full items-center gap-2.5 rounded-[9px] px-2.5 text-[12.5px] transition-colors duration-150',
        collapsed && 'justify-center px-0',
        active ? 'bg-bg font-medium text-text shadow-[0_1px_2px_rgb(16_18_22/0.06)]' : 'text-secondary hover:bg-[color-mix(in_srgb,var(--hover)_78%,transparent)] hover:text-text',
      )}
    >
      <Icon size={17} strokeWidth={1.65} className={cn('shrink-0', active && 'text-accent')} />
      {collapsed ? null : <span className="truncate">{label}</span>}
    </button>
  );
}

export default function Sidebar({
  navigation, view, onNavigate, collapsed, onToggle,
  recent, activeCid, busy, runningCid, search, onSearch,
  onOpenConversation, onNewConversation, onLogin, account, loginSaved, dateLabel,
}) {
  const filtered = recent.filter((item) => (item.title || '').toLowerCase().includes(search.toLowerCase()));

  return (
    <aside className="col-start-1 row-start-2 flex min-h-0 flex-col overflow-hidden border-r border-line bg-[color-mix(in_srgb,var(--sidebar)_92%,var(--bg))]">
      <div className={cn('flex items-center gap-2 px-3 pt-3.5', collapsed && 'flex-col px-2.5')}>
        <button
          type="button"
          onClick={onNewConversation}
          title="新建对话 · Ctrl+N"
          className={cn(
            'flex min-h-[36px] flex-1 items-center gap-2.5 rounded-[10px] border border-line bg-bg px-2.5 text-[12.5px] text-text shadow-[0_1px_2px_rgb(16_18_22/0.05)]',
            'transition-[transform,box-shadow,border-color] duration-150 hover:-translate-y-px hover:border-[color-mix(in_srgb,var(--accent)_30%,var(--line))] hover:shadow-[0_3px_10px_rgb(16_18_22/0.08)]',
            collapsed && 'w-9 flex-none justify-center px-0',
          )}
        >
          <SquarePen size={17} />
          {collapsed ? null : <span className="truncate">新建对话</span>}
          {collapsed ? null : <kbd className="ml-auto rounded-[5px] border border-line bg-subtle px-[5px] py-[3px] font-mono text-[10px] text-muted">⌃N</kbd>}
        </button>
        <button
          type="button"
          aria-label={collapsed ? '展开侧边栏' : '收起侧边栏'}
          onClick={onToggle}
          className="grid h-8 w-8 shrink-0 place-items-center rounded-[8px] text-secondary transition-colors hover:bg-[color-mix(in_srgb,var(--hover)_78%,transparent)] hover:text-text"
        >
          {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
        </button>
      </div>

      <nav className="flex flex-col gap-0.5 px-2.5 pb-2.5 pt-0.5">
        {navigation.map(([key, label, Icon]) => (
          <NavItem
            key={key}
            icon={Icon}
            label={label}
            active={view === key}
            collapsed={collapsed}
            onClick={() => onNavigate(key)}
          />
        ))}
      </nav>

      {collapsed ? (
        <div className="flex-1" />
      ) : (
        <div className="mx-3 flex min-h-[80px] flex-1 flex-col overflow-hidden border-t border-line pt-3.5">
          <div className="flex items-center justify-between px-1.5 pb-2 text-[10.5px] uppercase tracking-[0.5px] text-muted">
            <span>最近对话</span>
            <label className="flex items-center gap-1 rounded-md px-1 py-0.5 normal-case tracking-normal focus-within:bg-subtle">
              <Search size={13} />
              <input
                aria-label="搜索历史对话"
                placeholder="搜索"
                value={search}
                onChange={(event) => onSearch(event.target.value)}
                className="w-[52px] border-0 bg-transparent text-[11px] text-secondary outline-none placeholder:text-muted"
              />
            </label>
          </div>
          <div className="flex-1 overflow-auto pb-2">
            {filtered.map((item) => {
              const active = activeCid === item.id && view === 'workspace';
              return (
                <button
                  key={item.id}
                  type="button"
                  title={item.title}
                  onClick={() => onOpenConversation(item.id)}
                  className={cn(
                    'flex w-full items-center gap-2 rounded-[8px] px-2 py-2 text-left text-[12px] transition-colors duration-150',
                    active ? 'bg-bg text-text shadow-[0_1px_2px_rgb(16_18_22/0.06)]' : 'text-secondary hover:bg-[color-mix(in_srgb,var(--hover)_78%,transparent)] hover:text-text',
                  )}
                >
                  <span className="flex-1 truncate">{item.title}</span>
                  {busy && runningCid === item.id ? (
                    <Loader2 size={12} className="spin shrink-0" />
                  ) : (
                    <time className="shrink-0 text-[10px] text-muted">{dateLabel(item.updated_at)}</time>
                  )}
                </button>
              );
            })}
            {!filtered.length ? (
              <p className="px-2 py-2.5 text-[11px] leading-relaxed text-muted">你的对话会保存在这里</p>
            ) : null}
          </div>
        </div>
      )}

      <div className={cn('px-3 pb-3 pt-2', collapsed && 'px-2.5')}>
        <NavItem
          icon={Settings}
          label="设置"
          active={view === 'settings'}
          collapsed={collapsed}
          onClick={() => onNavigate('settings')}
        />
        <button
          type="button"
          onClick={onLogin}
          title="登录或切换抖音账号"
          className={cn(
            'mt-1.5 flex w-full items-center gap-2.5 rounded-[10px] px-2 py-2.5 text-left transition-colors duration-150 hover:bg-[color-mix(in_srgb,var(--hover)_70%,transparent)]',
            collapsed && 'justify-center px-0',
          )}
        >
          <span className="grid h-[30px] w-[30px] shrink-0 place-items-center rounded-[10px] border border-line bg-[color-mix(in_srgb,var(--accent)_12%,var(--bg))] text-[12px] font-semibold text-accent">
            {(account || '本')[0]}
          </span>
          {collapsed ? null : (
            <span className="min-w-0 flex-1">
              <strong className="block truncate text-[11px] font-medium text-text">{account || '本地工作空间'}</strong>
              <small className="mt-1 flex items-center gap-1.5 text-[10px] text-muted">
                <i className={cn('h-1 w-1 rounded-full', loginSaved ? 'bg-[#659a7c]' : 'bg-muted')} />
                {loginSaved ? '抖音登录态已保存' : '登录抖音账号'}
              </small>
            </span>
          )}
          {collapsed ? null : <ChevronDown size={14} className="text-muted" />}
        </button>
      </div>
    </aside>
  );
}
