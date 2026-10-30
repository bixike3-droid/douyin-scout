import React, { useEffect, useState } from 'react';
import { cn } from './kit.jsx';

/** 抖音头像：加载失败时退回昵称首字。 */
export function UserAvatar({ src, name, size = 30, className }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  const initial = (name || '本').trim()[0] || '本';
  const box = {
    width: size,
    height: size,
    borderRadius: Math.max(8, Math.round(size * 0.34)),
    fontSize: Math.max(11, Math.round(size * 0.4)),
  };
  if (src && !failed) {
    return (
      <img
        src={src}
        alt={name ? `${name} 的头像` : '账号头像'}
        style={box}
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
        className={cn('shrink-0 border border-line object-cover', className)}
      />
    );
  }
  return (
    <span
      style={box}
      aria-hidden="true"
      className={cn(
        'grid shrink-0 place-items-center border border-line bg-[color-mix(in_srgb,var(--accent)_12%,var(--bg))] font-semibold text-accent',
        className,
      )}
    >
      {initial}
    </span>
  );
}
