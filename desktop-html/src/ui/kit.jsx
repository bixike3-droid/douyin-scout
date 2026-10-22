import React, { forwardRef, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { Check, ChevronDown } from 'lucide-react';

/** 合并 className（够用版，不引入 tailwind-merge） */
export const cn = (...parts) => parts.flat(Infinity).filter(Boolean).join(' ');

const FOCUS = 'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent/60 outline-none';

/* ---------------------------------------------------------------- Button */

const BUTTON_BASE =
  'inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-[8px] text-[12px] font-medium ' +
  'transition-[background-color,color,box-shadow,filter] duration-150 disabled:pointer-events-none disabled:opacity-45 ' + FOCUS;

const BUTTON_VARIANT = {
  primary: 'bg-accent text-white shadow-[0_1px_2px_rgba(16,18,22,0.12)] hover:brightness-105 active:brightness-95',
  secondary: 'border border-line bg-bg text-text hover:bg-subtle',
  ghost: 'text-secondary hover:bg-subtle hover:text-text',
  danger: 'bg-danger/10 text-danger hover:bg-danger/15',
};

const BUTTON_SIZE = {
  sm: 'h-8 px-3',
  md: 'h-9 px-4',
  lg: 'h-10 px-5',
  icon: 'h-8 w-8 p-0',
};

export const Button = forwardRef(function Button(
  { variant = 'primary', size = 'md', className, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(BUTTON_BASE, BUTTON_VARIANT[variant], BUTTON_SIZE[size], className)}
      {...rest}
    />
  );
});

/* ----------------------------------------------------------------- Forms */

const CONTROL =
  'w-full min-w-0 rounded-[8px] border border-line bg-bg px-3 py-2.5 text-[12px] text-text outline-none ' +
  'transition-colors duration-150 placeholder:text-muted hover:border-line focus:border-accent/60 ' +
  'focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent/25 disabled:opacity-50';

export const Input = forwardRef(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={cn(CONTROL, className)} {...rest} />;
});

export const Textarea = forwardRef(function Textarea({ className, rows = 3, ...rest }, ref) {
  return <textarea ref={ref} rows={rows} className={cn(CONTROL, 'resize-y leading-relaxed', className)} {...rest} />;
});

/* ---------------------------------------------------------------- Select */

/** 支持两种写法：<Select options={[{value,label}]} /> 或 <Select><option/></Select> */
function readOptions(children, options) {
  if (Array.isArray(options)) {
    return options.map((item) =>
      typeof item === 'string' || typeof item === 'number'
        ? { value: String(item), label: String(item), disabled: false }
        : {
            value: String(item.value ?? item.label),
            label: String(item.label ?? item.value),
            disabled: !!item.disabled,
          },
    );
  }
  const out = [];
  React.Children.forEach(children, (child) => {
    if (!React.isValidElement(child) || child.type !== 'option') return;
    const label = React.Children.toArray(child.props.children).join('');
    out.push({ value: String(child.props.value ?? label), label, disabled: !!child.props.disabled });
  });
  return out;
}

const OPTION_HEIGHT = 30;
const LIST_PADDING = 8;

const TRIGGER_FIELD = cn(CONTROL, 'flex cursor-pointer items-center justify-between gap-2 pr-2.5 text-left');
const TRIGGER_CHIP =
  'inline-flex max-w-[190px] items-center gap-1.5 rounded-full border border-line bg-subtle py-1 pl-2 pr-1.5 ' +
  'text-[10.5px] text-secondary transition-colors hover:border-accent/40 hover:text-text ' + FOCUS;

/** 自绘下拉：原生 select 的弹层由系统渲染，方角、不跟主题色、连箭头都会被 appearance-none 去掉。 */
export function Select({
  value,
  onChange,
  options,
  children,
  className,
  disabled,
  variant = 'field',
  placeholder = '请选择',
  ...rest
}) {
  const chip = variant === 'chip';
  const items = useMemo(() => readOptions(children, options), [children, options]);
  const selectedIndex = items.findIndex((item) => item.value === String(value ?? ''));
  const selected = selectedIndex >= 0 ? items[selectedIndex] : null;
  const reduce = useReducedMotion();

  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(Math.max(selectedIndex, 0));
  const [box, setBox] = useState(null);
  const triggerRef = useRef(null);
  const popupRef = useRef(null);

  useEffect(() => {
    if (open) setActive(Math.max(selectedIndex, 0));
  }, [open, selectedIndex]);

  // 弹层挂在 body 上（避免被卡片/滚动容器裁掉），位置用 fixed 算。
  const place = () => {
    const el = triggerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const want = Math.min(items.length * OPTION_HEIGHT + LIST_PADDING, 264);
    const below = window.innerHeight - rect.bottom - 8;
    const above = rect.top - 8;
    const dropUp = below < want && above > below;
    const width = Math.max(rect.width, chip ? 176 : 0);
    setBox({
      left: Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)),
      width,
      maxHeight: Math.max(96, Math.min(want, dropUp ? above : below)),
      ...(dropUp ? { bottom: window.innerHeight - rect.top + 6 } : { top: rect.bottom + 6 }),
    });
  };

  useEffect(() => {
    if (!open) return undefined;
    place();
    const onPointerDown = (event) => {
      if (triggerRef.current?.contains(event.target)) return;
      if (popupRef.current?.contains(event.target)) return;
      setOpen(false);
    };
    const onReflow = () => place();
    document.addEventListener('pointerdown', onPointerDown, true);
    window.addEventListener('resize', onReflow);
    window.addEventListener('scroll', onReflow, true);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true);
      window.removeEventListener('resize', onReflow);
      window.removeEventListener('scroll', onReflow, true);
    };
  }, [open]);

  const openList = () => {
    if (disabled || !items.length) return;
    place();
    setActive(Math.max(selectedIndex, 0));
    setOpen(true);
  };

  const commit = (item) => {
    if (!item || item.disabled) return;
    setOpen(false);
    triggerRef.current?.focus();
    if (item.value !== String(value ?? '')) onChange?.(item.value);
  };

  const step = (dir) => {
    const from = (active + dir + items.length) % items.length;
    return nearestEnabled(from, dir);
  };

  /** 从 start 开始沿 dir 方向找第一个可用项 */
  const nearestEnabled = (start, dir) => {
    let index = start;
    for (let i = 0; i < items.length; i += 1) {
      if (!items[index]?.disabled) return index;
      index = (index + dir + items.length) % items.length;
    }
    return active;
  };

  const reveal = (index) => {
    popupRef.current?.querySelector(`[data-index="${index}"]`)?.scrollIntoView({ block: 'nearest' });
  };

  const onKeyDown = (event) => {
    if (!open) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp' || event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openList();
      }
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      setOpen(false);
    } else if (event.key === 'Tab') {
      setOpen(false);
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const next = step(event.key === 'ArrowDown' ? 1 : -1);
      setActive(next);
      reveal(next);
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      const next =
        event.key === 'Home' ? nearestEnabled(0, 1) : nearestEnabled(items.length - 1, -1);
      setActive(next);
      reveal(next);
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      commit(items[active]);
    }
  };

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : openList())}
        onKeyDown={onKeyDown}
        className={cn(chip ? TRIGGER_CHIP : TRIGGER_FIELD, open && 'border-accent/60', className)}
        {...rest}
      >
        <span className={cn('truncate', !selected && 'text-muted')}>{selected ? selected.label : placeholder}</span>
        <ChevronDown
          size={chip ? 12 : 13}
          className={cn('shrink-0 text-muted transition-transform duration-150', open && 'rotate-180')}
        />
      </button>
      {createPortal(
        <AnimatePresence>
          {open ? (
            <motion.ul
              ref={popupRef}
              role="listbox"
              style={box || undefined}
              initial={reduce ? false : { opacity: 0, scale: 0.98, y: -4 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.98, y: -4 }}
              transition={{ duration: 0.12, ease: [0.16, 1, 0.3, 1] }}
              className="fixed z-50 m-0 list-none overflow-y-auto rounded-[10px] border border-line bg-bg p-1 shadow-2 outline-none"
            >
              {items.map((item, index) => (
                <li key={item.value} role="option" aria-selected={index === selectedIndex} data-index={index}>
                  <button
                    type="button"
                    disabled={item.disabled}
                    onPointerMove={() => setActive(index)}
                    onClick={() => commit(item)}
                    className={cn(
                      'flex w-full items-center gap-2 rounded-[6px] px-2.5 py-[6px] text-left text-[12px] transition-colors duration-100',
                      index === active && !item.disabled ? 'bg-hover text-text' : 'text-secondary',
                      index === selectedIndex && 'text-text',
                    )}
                  >
                    <span className="truncate">{item.label}</span>
                    {index === selectedIndex ? <Check size={13} className="ml-auto shrink-0 text-accent" /> : null}
                  </button>
                </li>
              ))}
            </motion.ul>
          ) : null}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
}

export function Field({ label, hint, children, className, error }) {
  return (
    <label className={cn('flex flex-col gap-2', className)}>
      <span className="flex items-center gap-2 text-[12px] font-medium text-text">
        {label}
        {hint ? <small className="text-[11px] font-normal text-muted">{hint}</small> : null}
      </span>
      {children}
      {error ? <small className="text-[11px] text-danger">{error}</small> : null}
    </label>
  );
}

export function Switch({ checked, onChange, disabled, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={!!checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative h-[22px] w-[38px] shrink-0 rounded-full transition-colors duration-150 disabled:opacity-40 ' + FOCUS,
        checked ? 'bg-accent' : 'bg-line',
      )}
    >
      <span
        className={cn(
          'absolute top-[3px] h-4 w-4 rounded-full bg-white shadow-[0_1px_3px_rgba(16,18,22,0.25)] transition-[left] duration-150',
          checked ? 'left-[19px]' : 'left-[3px]',
        )}
      />
    </button>
  );
}

export function Checkbox({ checked, onChange, children, className }) {
  return (
    <label className={cn('inline-flex cursor-pointer select-none items-center gap-2.5 text-[12px] text-secondary', className)}>
      <span
        className={cn(
          'grid h-4 w-4 place-items-center rounded-[4px] border transition-colors',
          checked ? 'border-accent bg-accent text-white' : 'border-line bg-bg',
        )}
      >
        {checked ? (
          <svg viewBox="0 0 16 16" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2.4">
            <path d="M3.5 8.5l3 3 6-6.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ) : null}
      </span>
      <input type="checkbox" className="sr-only" checked={!!checked} onChange={(e) => onChange(e.target.checked)} />
      {children}
    </label>
  );
}

/* ------------------------------------------------------------------ Card */

export function Card({ title, desc, icon: Icon, action, children, footer, className, bodyClassName }) {
  return (
    <section className={cn('overflow-hidden rounded-[12px] border border-line bg-bg', className)}>
      {title ? (
        <header className="flex items-start gap-3 border-b border-line px-6 py-4.5">
          {Icon ? <Icon size={17} className="mt-0.5 shrink-0 text-secondary" /> : null}
          <div className="min-w-0 flex-1">
            <h2 className="text-[13.5px] font-medium text-text">{title}</h2>
            {desc ? <p className="mt-1.5 text-[11px] leading-relaxed text-muted">{desc}</p> : null}
          </div>
          {action}
        </header>
      ) : null}
      <div className={cn('px-6 py-5', bodyClassName)}>{children}</div>
      {footer ? <div className="border-t border-line bg-subtle/40 px-6 py-3.5">{footer}</div> : null}
    </section>
  );
}

/* ------------------------------------------------------------------ Bits */

export function Badge({ tone = 'neutral', children, className }) {
  const tones = {
    neutral: 'bg-subtle text-secondary',
    accent: 'bg-accent-soft text-accent',
    success: 'bg-[#6da98b]/16 text-[#4d8a68]',
    danger: 'bg-danger/12 text-danger',
  };
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-medium', tones[tone], className)}>
      {children}
    </span>
  );
}

export function Segmented({ value, options, onChange, className }) {
  return (
    <div role="tablist" className={cn('inline-flex items-center gap-1 rounded-[9px] bg-subtle p-1', className)}>
      {options.map(([key, label]) => {
        const active = value === key;
        return (
          <button
            key={key}
            role="tab"
            type="button"
            aria-selected={active}
            onClick={() => onChange(key)}
            className={cn(
              'rounded-[6px] px-3.5 py-1.5 text-[12px] transition-colors duration-150 ' + FOCUS,
              active ? 'bg-bg text-text shadow-[0_1px_2px_rgba(16,18,22,0.08)]' : 'text-secondary hover:text-text',
            )}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

export function Separator({ className }) {
  return <hr className={cn('border-0 border-t border-line', className)} />;
}

export function Skeleton({ className }) {
  return <div className={cn('animate-pulse rounded-[6px] bg-subtle', className)} />;
}

export function EmptyState({ icon: Icon, title, desc, action }) {
  return (
    <div className="flex min-h-[220px] flex-col items-center justify-center gap-3 px-6 text-center">
      {Icon ? <Icon size={22} className="text-muted" /> : null}
      <h3 className="text-[14px] font-medium text-text">{title}</h3>
      {desc ? <p className="max-w-[380px] text-[12px] leading-relaxed text-muted">{desc}</p> : null}
      {action}
    </div>
  );
}
