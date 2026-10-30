import React from 'react';
import { cn } from '../ui/kit.jsx';

/* 无边框窗口的缩放边条。
   WebView2 子控件会截走 WM_NCHITTEST，原生边框命中不到，
   所以由这圈透明把手把按下事件交给桥，让系统进入缩放循环。 */
const EDGES = [
  ['top', 'left-2 right-2 top-0 h-[5px] cursor-ns-resize'],
  ['bottom', 'left-2 right-2 bottom-0 h-[5px] cursor-ns-resize'],
  ['left', 'top-2 bottom-2 left-0 w-[5px] cursor-ew-resize'],
  ['right', 'top-2 bottom-2 right-0 w-[5px] cursor-ew-resize'],
  ['topleft', 'left-0 top-0 h-[10px] w-[10px] cursor-nwse-resize'],
  ['topright', 'right-0 top-0 h-[10px] w-[10px] cursor-nesw-resize'],
  ['bottomleft', 'left-0 bottom-0 h-[10px] w-[10px] cursor-nesw-resize'],
  ['bottomright', 'right-0 bottom-0 h-[10px] w-[10px] cursor-nwse-resize'],
];

export function WindowEdges({ native }) {
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-[240]">
      {EDGES.map(([direction, className]) => (
        <div
          key={direction}
          data-resize={direction}
          className={cn('pointer-events-auto absolute', className)}
          onMouseDown={(event) => {
            if (event.button !== 0) return;
            event.preventDefault();
            native.windowAction(`resize:${direction}`);
          }}
        />
      ))}
    </div>
  );
}
