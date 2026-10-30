import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import {
  ChevronDown, FileText, Loader2, PanelLeftClose, PanelLeftOpen, Search, Settings, ShieldCheck, SquarePen,
} from 'lucide-react';
import { cn } from '../ui/kit.jsx';
import { UserAvatar } from '../ui/avatar.jsx';

const SPRING = { type: 'spring', stiffness: 380, damping: 34, mass: 0.85 };
const FADE = { duration: 0.14, ease: [0.16, 1, 0.3, 1] };

/** 折叠时淡出、展开时浮入的小标签 */
function Reveal({ show, children, className }) {
  return (
    <AnimatePresence initial={false}>
      {show ? (
        <motion.span
          initial={{ opacity: 0, x: -6 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -6 }}
          transition={FADE}
          className={cn('block overflow-hidden whitespace-nowrap', className)}
        >
          {children}
        </motion.span>
      ) : null}
    </AnimatePresence>
  );
}

function NavItem({ icon: Icon, label, active, collapsed, onClick }) {
  return (
    <button
      type="button"
      title={label}
      onClick={onClick}
      className={cn(
        'group relative flex min-h-[34px] w-full items-center gap-2.5 rounded-[9px] px-2.5 text-[12.5px] transition-colors duration-150',
        collapsed && 'justify-center px-0',
        active ? 'font-medium text-text' : 'text-secondary hover:bg-[color-mix(in_srgb,var(--hover)_78%,transparent)] hover:text-text',
      )}
    >
      {active ? (
        <motion.span
          layoutId="nav-active"
          className="absolute inset-0 rounded-[9px] bg-[var(--active)] shadow-[0_1px_2px_rgb(16_18_22/0.06)]"
          transition={{ type: 'spring', stiffness: 520, damping: 42 }}
        />
      ) : null}
      <Icon size={17} strokeWidth={1.65} className={cn('relative shrink-0', active && 'text-accent')} />
      <Reveal show={!collapsed} className="relative truncate">
        {label}
      </Reveal>
    </button>
  );
}

function MenuItem({ icon: Icon, label, hint, onClick }) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="flex w-full items-center gap-2.5 rounded-[8px] px-2.5 py-2 text-left text-[12px] text-secondary transition-colors hover:bg-subtle hover:text-text"
    >
      <Icon size={15} className="text-muted" />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {hint ? <span className="shrink-0 text-[10px] text-muted">{hint}</span> : null}
    </button>
  );
}

export default function Sidebar({
  navigation, view, onNavigate, collapsed, onToggle,
  recent, activeCid, busy, runningCid, search, onSearch,
  onOpenConversation, onNewConversation, onOpenPanel, account, loginSaved, dateLabel,
}) {
  const reduce = useReducedMotion();
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState(null);
  const accountRef = useRef(null);

  function toggleMenu() {
    const rect = accountRef.current?.getBoundingClientRect();
    if (rect) {
      setAnchor({
        left: Math.max(8, Math.min(rect.left, window.innerWidth - 236)),
        bottom: Math.max(8, window.innerHeight - rect.top + 8),
      });
    }
    setOpen((value) => !value);
  }

  function choose(panel) {
    setOpen(false);
    onOpenPanel(panel);
  }

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => { if (event.key === 'Escape') setOpen(false); };
    const onResize = () => setOpen(false);
    document.addEventListener('keydown', onKey);
    window.addEventListener('resize', onResize);
    return () => {
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', onResize);
    };
  }, [open]);
  const filtered = recent.filter((item) => (item.title || '').toLowerCase().includes(search.toLowerCase()));

  return (
    <motion.aside
      initial={false}
      animate={{ width: collapsed ? 66 : 230 }}
      transition={reduce ? { duration: 0 } : SPRING}
      className="col-start-1 row-start-2 flex min-h-0 flex-col overflow-hidden border-r border-line bg-[color-mix(in_srgb,var(--sidebar)_92%,var(--bg))]"
    >
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
          <SquarePen size={17} className="shrink-0" />
          <Reveal show={!collapsed} className="truncate">新建对话</Reveal>
          <Reveal show={!collapsed} className="ml-auto shrink-0">
            <kbd className="rounded-[5px] border border-line bg-subtle px-[5px] py-[3px] font-mono text-[10px] text-muted">⌃N</kbd>
          </Reveal>
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

      <AnimatePresence initial={false}>
        {collapsed ? (
          <motion.div key="spacer" className="flex-1" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
        ) : (
          <motion.div
            key="recent"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={FADE}
            className="mx-3 flex min-h-[80px] flex-1 flex-col overflow-hidden border-t border-line pt-3.5"
          >
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
                    active ? 'bg-[var(--active)] text-text shadow-[0_1px_2px_rgb(16_18_22/0.06)]' : 'text-secondary hover:bg-[color-mix(in_srgb,var(--hover)_78%,transparent)] hover:text-text',
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
        </motion.div>
        )}
      </AnimatePresence>

      <div className={cn('px-3 pb-3 pt-2', collapsed && 'px-2.5')}>
        <button
          ref={accountRef}
          type="button"
          data-testid="account-menu"
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={toggleMenu}
          title="账号与设置"
          className={cn(
            'flex w-full items-center gap-2.5 rounded-[10px] px-2 py-2.5 text-left transition-colors duration-150',
            'hover:bg-[color-mix(in_srgb,var(--hover)_70%,transparent)]',
            open && 'bg-[color-mix(in_srgb,var(--hover)_70%,transparent)]',
            collapsed && 'justify-center px-0',
          )}
        >
          <UserAvatar src={account?.avatar_url} name={account?.nickname} size={30} />
          <Reveal show={!collapsed} className="min-w-0 flex-1">
            <strong className="block truncate text-[11px] font-medium text-text">
              {account?.nickname || '本地工作空间'}
            </strong>
            <small className="mt-1 flex items-center gap-1.5 text-[10px] text-muted">
              <i className={cn('h-1 w-1 rounded-full', loginSaved ? 'bg-[#659a7c]' : 'bg-muted')} />
              {loginSaved ? '抖音已登录' : '抖音未登录'}
            </small>
          </Reveal>
          <Reveal show={!collapsed} className="shrink-0">
            <ChevronDown
              size={14}
              className={cn('text-muted transition-transform duration-150', open && 'rotate-180')}
            />
          </Reveal>
        </button>
      </div>

      {createPortal(
        <AnimatePresence>
          {open ? (
            <>
              <motion.div
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                transition={{ duration: 0.12 }}
                className="fixed inset-0 z-[70]"
                onClick={() => setOpen(false)}
              />
              <motion.div
                role="menu"
                aria-label="账号与设置"
                initial={{ opacity: 0, y: 8, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 8, scale: 0.98 }}
                transition={{ duration: 0.14, ease: [0.16, 1, 0.3, 1] }}
                style={anchor || { left: 8, bottom: 72 }}
                className="fixed z-[71] w-[228px] overflow-hidden rounded-[12px] border border-line bg-bg p-1.5 shadow-[0_18px_48px_rgb(10_14_24/0.18)]"
              >
                <MenuItem icon={ShieldCheck} label="账号与安全" hint={loginSaved ? '已登录' : '未登录'}
                          onClick={() => choose('account')} />
                <MenuItem icon={FileText} label="隐私说明" onClick={() => choose('privacy')} />
                <MenuItem icon={Settings} label="设置" onClick={() => choose('settings')} />
              </motion.div>
            </>
          ) : null}
        </AnimatePresence>,
        document.body,
      )}
    </motion.aside>
  );
}
