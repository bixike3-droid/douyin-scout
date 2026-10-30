import React, { useEffect, useMemo, useRef, useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';

/*
 * 轻量图表：手搓 SVG + motion，不引入图表库。
 *
 * 约定（来自可视化规范）：
 * - 单序列不放图例，标题已经说明画的是什么；>=2 条序列才需要图例。
 * - 线 2px、端点 8px 带 2px 底色描边；柱 <=24px、数据端 4px 圆角、基线直角。
 * - 网格 1px 实线，颜色比底色深一档；文字一律用文本色，不穿序列色。
 * - 折线用十字准星找最近点；柱状逐根悬停；键盘方向键等效。
 * - 每张图都附一个可展开的数据表，不把数值锁在悬停里。
 */

const PALETTE = { 1: 'var(--chart-1)', 2: 'var(--chart-2)' };

export function compact(value) {
  const number = Number(value) || 0;
  if (Math.abs(number) >= 100_000_000) return `${(number / 100_000_000).toFixed(number % 100_000_000 === 0 ? 0 : 1)} 亿`;
  if (Math.abs(number) >= 10_000) return `${(number / 10_000).toFixed(number % 10_000 === 0 ? 0 : 1)} 万`;
  if (Math.abs(number) >= 1_000) return number.toLocaleString('zh-CN');
  return String(number);
}

function niceMax(value) {
  if (!value || value <= 0) return 4;
  const exponent = Math.floor(Math.log10(value));
  const base = 10 ** exponent;
  for (const step of [1, 2, 2.5, 5, 10]) {
    if (value <= step * base) return step * base;
  }
  return 10 * base;
}

function useWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      setWidth(Math.max(0, Math.round(entry.contentRect.width)));
    });
    observer.observe(node);
    setWidth(Math.round(node.getBoundingClientRect().width));
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

function useCountUp(target, duration = 650) {
  const reduce = useReducedMotion();
  const [value, setValue] = useState(reduce ? target : 0);
  useEffect(() => {
    if (reduce) { setValue(target); return undefined; }
    let frame = 0;
    const start = performance.now();
    const tick = (now) => {
      const progress = Math.min(1, (now - start) / duration);
      setValue(Math.round(target * (1 - (1 - progress) ** 3)));
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, duration, reduce]);
  return value;
}

function smoothPath(points) {
  if (!points.length) return '';
  if (points.length === 1) return `M ${points[0][0]} ${points[0][1]}`;
  let path = `M ${points[0][0]} ${points[0][1]}`;
  for (let index = 0; index < points.length - 1; index += 1) {
    const p0 = points[index - 1] || points[index];
    const p1 = points[index];
    const p2 = points[index + 1];
    const p3 = points[index + 2] || p2;
    path += ` C ${p1[0] + (p2[0] - p0[0]) / 6} ${p1[1] + (p2[1] - p0[1]) / 6},`
          + ` ${p2[0] - (p3[0] - p1[0]) / 6} ${p2[1] - (p3[1] - p1[1]) / 6},`
          + ` ${p2[0]} ${p2[1]}`;
  }
  return path;
}

function roundedTop(x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, Math.max(0, height));
  if (height <= 0) return '';
  return `M ${x} ${y + height} L ${x} ${y + r} Q ${x} ${y} ${x + r} ${y}`
       + ` L ${x + width - r} ${y} Q ${x + width} ${y} ${x + width} ${y + r}`
       + ` L ${x + width} ${y + height} Z`;
}

/* ------------------------------------------------------------ 折线 / 面积 */

export function AreaTrend({ values, labels, height = 132, name, color = PALETTE[1], format = compact, unit = '' }) {
  const [ref, width] = useWidth();
  const [active, setActive] = useState(null);
  const reduce = useReducedMotion();
  const pad = { top: 12, right: 12, bottom: 20, left: 38 };
  const plotWidth = Math.max(10, width - pad.left - pad.right);
  const plotHeight = Math.max(10, height - pad.top - pad.bottom);
  const max = niceMax(Math.max(...values, 0));
  const count = Math.max(1, values.length - 1);

  const points = useMemo(() => values.map((value, index) => [
    pad.left + (plotWidth * index) / count,
    pad.top + plotHeight * (1 - Math.max(0, value) / max),
  ]), [values, plotWidth, plotHeight, max, count, pad.left, pad.top]);

  const line = smoothPath(points);
  const area = points.length
    ? `${line} L ${points[points.length - 1][0]} ${pad.top + plotHeight} L ${points[0][0]} ${pad.top + plotHeight} Z`
    : '';

  const pick = (event) => {
    const box = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - box.left;
    const index = Math.round(((x - pad.left) / plotWidth) * count);
    setActive(Math.min(values.length - 1, Math.max(0, index)));
  };

  const onKey = (event) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    const step = event.key === 'ArrowRight' ? 1 : -1;
    setActive((current) => {
      const next = (current ?? values.length - 1) + step;
      return Math.min(values.length - 1, Math.max(0, next));
    });
  };

  const spot = active === null ? null : points[active];

  return (
    <figure className="m-0">
      <div ref={ref} className="relative">
        <svg
          width="100%" height={height} viewBox={`0 0 ${Math.max(width, 1)} ${height}`}
          role="img" aria-label={`${name}，共 ${values.length} 个数据点`}
          tabIndex={0} onKeyDown={onKey} onPointerMove={pick} onPointerLeave={() => setActive(null)}
          onBlur={() => setActive(null)}
          className="block touch-none outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--chart-1)]/30"
        >
          {[0, 0.5, 1].map((ratio) => (
            <line
              key={ratio} x1={pad.left} x2={pad.left + plotWidth}
              y1={pad.top + plotHeight * ratio} y2={pad.top + plotHeight * ratio}
              stroke="var(--chart-grid)" strokeWidth="1"
            />
          ))}
          {[0, 0.5, 1].map((ratio) => (
            <text
              key={ratio} x={pad.left - 8} y={pad.top + plotHeight * ratio + 3.5}
              textAnchor="end" className="fill-[color:var(--muted)] text-[9.5px]"
            >
              {format(max * (1 - ratio))}
            </text>
          ))}

          {values.length ? (
            <>
              <motion.path
                d={area} fill="var(--chart-wash)" stroke="none"
                initial={reduce ? false : { opacity: 0 }} animate={{ opacity: 1 }}
                transition={{ duration: 0.5, ease: 'easeOut' }}
              />
              <motion.path
                d={line} fill="none" stroke={color} strokeWidth="2"
                strokeLinecap="round" strokeLinejoin="round"
                initial={reduce ? false : { pathLength: 0 }} animate={{ pathLength: 1 }}
                transition={{ duration: 0.8, ease: 'easeOut' }}
              />
              {spot ? (
                <>
                  <line x1={spot[0]} x2={spot[0]} y1={pad.top} y2={pad.top + plotHeight} stroke="var(--chart-grid)" strokeWidth="1" />
                  <circle cx={spot[0]} cy={spot[1]} r="4" fill={color} stroke="var(--bg)" strokeWidth="2" />
                </>
              ) : null}
            </>
          ) : null}

          {labels.length ? (
            <>
              <text x={pad.left} y={height - 4} className="fill-[color:var(--muted)] text-[9.5px]">{labels[0]}</text>
              <text x={pad.left + plotWidth} y={height - 4} textAnchor="end" className="fill-[color:var(--muted)] text-[9.5px]">
                {labels[labels.length - 1]}
              </text>
            </>
          ) : null}
        </svg>

        {active !== null ? (
          <div
            className="pointer-events-none absolute top-0 z-10 min-w-[86px] rounded-[7px] border border-line bg-bg px-2 py-1.5 shadow-[var(--shadow-2)]"
            style={{ left: Math.min(Math.max(0, (spot?.[0] || 0) - 43), Math.max(0, width - 96)) }}
          >
            <p className="text-[13px] font-[560] tabular-nums text-text">{format(values[active])}{unit}</p>
            <p className="mt-0.5 text-[10px] text-muted">{labels[active] || ''} · {name}</p>
          </div>
        ) : null}
      </div>
      <TableToggle labels={labels} rows={[{ name, values }]} format={(value) => `${format(value)}${unit}`} />
    </figure>
  );
}

/* ------------------------------------------------------------ 柱状（时间） */

export function ColumnTrend({ items, height = 120, name, unit = '', color = PALETTE[1] }) {
  const [ref, width] = useWidth();
  const [active, setActive] = useState(null);
  const reduce = useReducedMotion();
  const pad = { top: 10, right: 4, bottom: 20, left: 30 };
  const plotWidth = Math.max(10, width - pad.left - pad.right);
  const plotHeight = Math.max(10, height - pad.top - pad.bottom);
  const max = niceMax(Math.max(...items.map((item) => item.count), 0));
  const band = plotWidth / Math.max(1, items.length);
  const barWidth = Math.min(24, Math.max(3, band - 2));

  const onKey = (event) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    const step = event.key === 'ArrowRight' ? 1 : -1;
    setActive((current) => Math.min(items.length - 1, Math.max(0, (current ?? items.length - 1) + step)));
  };

  return (
    <figure className="m-0">
      <div ref={ref} className="relative">
        <svg
          width="100%" height={height} viewBox={`0 0 ${Math.max(width, 1)} ${height}`}
          role="img" aria-label={`${name}，共 ${items.length} 天`}
          tabIndex={0} onKeyDown={onKey} onBlur={() => setActive(null)}
          className="block outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--chart-1)]/30"
        >
          {[0, 0.5, 1].map((ratio) => (
            <line key={ratio} x1={pad.left} x2={pad.left + plotWidth}
                  y1={pad.top + plotHeight * ratio} y2={pad.top + plotHeight * ratio}
                  stroke="var(--chart-grid)" strokeWidth="1" />
          ))}
          {[0, 0.5, 1].map((ratio) => (
            <text key={ratio} x={pad.left - 6} y={pad.top + plotHeight * ratio + 3.5}
                  textAnchor="end" className="fill-[color:var(--muted)] text-[9.5px]">
              {compact(max * (1 - ratio))}
            </text>
          ))}

          {items.map((item, index) => {
            const barHeight = (plotHeight * Math.max(0, item.count)) / max;
            const x = pad.left + band * index + (band - barWidth) / 2;
            const y = pad.top + plotHeight - barHeight;
            const dim = active === null || active === index;
            const path = roundedTop(x, y, barWidth, barHeight, 4);
            return (
              <g key={item.date || item.label}
                 onPointerEnter={() => setActive(index)}
                 onPointerLeave={() => setActive(null)}>
                <rect x={pad.left + band * index} y={pad.top} width={band} height={plotHeight}
                      fill="transparent" />
                {barHeight > 0 ? (
                  <motion.path
                    d={path} fill={color} opacity={dim ? 1 : 0.45}
                    initial={reduce ? false : { scaleY: 0 }}
                    animate={{ scaleY: 1 }}
                    style={{ originY: 1, transformBox: 'fill-box' }}
                    transition={{ duration: 0.45, delay: Math.min(index * 0.012, 0.25), ease: 'easeOut' }}
                  />
                ) : null}
              </g>
            );
          })}

          {items.length ? (
            <>
              <text x={pad.left} y={height - 4} className="fill-[color:var(--muted)] text-[9.5px]">{items[0].label}</text>
              <text x={pad.left + plotWidth} y={height - 4} textAnchor="end" className="fill-[color:var(--muted)] text-[9.5px]">
                {items[items.length - 1].label}
              </text>
            </>
          ) : null}
        </svg>
        {active !== null ? (
          <div
            className="pointer-events-none absolute top-0 z-10 min-w-[86px] rounded-[7px] border border-line bg-bg px-2 py-1.5 shadow-[var(--shadow-2)]"
            style={{ left: Math.min(Math.max(0, pad.left + band * active + band / 2 - 43), Math.max(0, width - 96)) }}
          >
            <p className="text-[13px] font-[560] tabular-nums text-text">{items[active].count}{unit}</p>
            <p className="mt-0.5 text-[10px] text-muted">{items[active].label} · {name}</p>
          </div>
        ) : null}
      </div>
      <TableToggle labels={items.map((item) => item.label)} rows={[{ name, values: items.map((item) => item.count) }]} format={(value) => `${value}${unit}`} />
    </figure>
  );
}

/* ------------------------------------------------------------ 横向条形 */

export function BarList({ items, name, unit = '', format = (value) => value, labelWidth = 112 }) {
  const max = Math.max(...items.map((item) => item.count), 1);
  const reduce = useReducedMotion();
  return (
    <div className="flex flex-col gap-2">
      {items.map((item, index) => (
        <div key={item.label} className="items-center gap-3"
             style={{ display: 'grid', gridTemplateColumns: `${labelWidth}px 1fr auto` }}>
          <span className="truncate text-[11px] text-secondary" title={item.label}>{item.label}</span>
          <span className="relative block h-[7px] overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--chart-1)_12%,var(--bg))]">
            <motion.span
              className="absolute inset-y-0 left-0 rounded-full"
              style={{ background: 'var(--chart-1)' }}
              initial={reduce ? false : { width: 0 }}
              animate={{ width: `${(item.count / max) * 100}%` }}
              transition={{ duration: 0.6, delay: index * 0.05, ease: 'easeOut' }}
            />
          </span>
          <span className="min-w-[38px] text-right text-[11px] tabular-nums text-text">{format(item.count)}{unit}</span>
        </div>
      ))}
      <TableToggle labels={items.map((item) => item.label)} rows={[{ name, values: items.map((item) => item.count) }]} format={(value) => `${format(value)}${unit}`} />
    </div>
  );
}

/* ------------------------------------------------------------ 数字 / 进度 */

export function StatTile({ label, value, suffix = '', hint, decimals = 0 }) {
  const scale = 10 ** decimals;
  const shown = useCountUp(Math.round((Number(value) || 0) * scale)) / scale;
  const text = decimals
    ? shown.toFixed(decimals)
    : value >= 10_000 ? compact(shown) : shown.toLocaleString('zh-CN');
  return (
    <div className="rounded-[10px] border border-line bg-bg px-3.5 py-3">
      <p className="text-[10.5px] text-muted">{label}</p>
      <p className="mt-1 text-[19px] font-[560] tabular-nums tracking-[-0.4px] text-text">
        {text}{suffix}
      </p>
      {hint ? <p className="mt-1 text-[10px] text-muted">{hint}</p> : null}
    </div>
  );
}

export function Meter({ value, label, hint }) {
  const pct = Math.max(0, Math.min(100, Math.round(value || 0)));
  const reduce = useReducedMotion();
  return (
    <div className="rounded-[10px] border border-line bg-bg px-3.5 py-3">
      <div className="flex items-baseline justify-between">
        <p className="text-[10.5px] text-muted">{label}</p>
        <p className="text-[15px] font-[560] tabular-nums text-text">{pct}%</p>
      </div>
      <div className="mt-2 h-[7px] overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--chart-1)_12%,var(--bg))]">
        <motion.div
          className="h-full rounded-full"
          style={{ background: 'var(--chart-1)' }}
          initial={reduce ? false : { width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.7, ease: 'easeOut' }}
        />
      </div>
      {hint ? <p className="mt-1.5 text-[10px] text-muted">{hint}</p> : null}
    </div>
  );
}

function TableToggle({ labels, rows, format }) {
  return (
    <details className="mt-1.5 text-[10.5px] text-muted">
      <summary className="cursor-pointer select-none hover:text-secondary">数据表</summary>
      <div className="mt-1.5 max-h-[132px] overflow-auto rounded-[6px] border border-line">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr>
              <th className="bg-subtle/60 px-2 py-1 font-medium">时间</th>
              {rows.map((row) => (
                <th key={row.name} className="bg-subtle/60 px-2 py-1 font-medium">{row.name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {labels.map((label, index) => (
              <tr key={`${label}-${index}`} className="border-t border-line">
                <td className="px-2 py-1">{label}</td>
                {rows.map((row) => (
                  <td key={row.name} className="px-2 py-1 tabular-nums text-secondary">{format(row.values[index] ?? 0)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
