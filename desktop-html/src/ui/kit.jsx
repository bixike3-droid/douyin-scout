import React, { forwardRef } from 'react';

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

export const Select = forwardRef(function Select({ className, children, ...rest }, ref) {
  return (
    <select ref={ref} className={cn(CONTROL, 'cursor-pointer appearance-none pr-8', className)} {...rest}>
      {children}
    </select>
  );
});

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
