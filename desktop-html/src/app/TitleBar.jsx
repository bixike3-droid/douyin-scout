import React from 'react';
import { Minus, Square, X } from 'lucide-react';

/**
 * 自绘标题栏：品牌 + 当前项目 + 窗口按钮。
 * 拖拽/最大化走原生桥（native.windowAction），窗口按钮是纯 HTML，
 * 所以 hover/按下的过渡由 CSS 控制，和网页里完全一样。
 */
export default function TitleBar({ project, native }) {
  const interactive = (target) => target.closest('button,input,a,select');

  const onMouseDown = (event) => {
    if (event.button === 0 && !interactive(event.target)) native?.windowAction('drag');
  };
  const onDoubleClick = (event) => {
    if (!interactive(event.target)) native?.windowAction('maximize');
  };

  return (
    <header
      className="col-span-full flex h-[44px] select-none items-center gap-3 border-b border-line bg-[color-mix(in_srgb,var(--sidebar)_88%,var(--bg))] pl-[18px]"
      onMouseDown={onMouseDown}
      onDoubleClick={onDoubleClick}
    >
      <div className="flex items-center gap-2.5 whitespace-nowrap">
        <img src="/brand.png" alt="" className="h-5 w-5 rounded-[5px]" />
        <span className="text-[13px] font-[550] tracking-[0.5px] text-text">源镜</span>
        <span className="border-l border-line pl-3 text-[11px] tracking-[0.4px] text-muted">工作空间</span>
      </div>

      <span className="pointer-events-none mx-auto rounded-full border border-line bg-[color-mix(in_srgb,var(--bg)_55%,transparent)] px-2.5 py-[3px] text-[11px] tracking-[0.3px] text-muted">
        {project || '本地工作空间'}
      </span>

      {native ? (
        <div className="ml-auto flex h-full">
          <button
            aria-label="最小化"
            onClick={() => native.windowAction('minimize')}
            className="grid h-full w-[46px] place-items-center text-secondary transition-[background-color,color,transform] duration-150 hover:bg-[color-mix(in_srgb,var(--muted)_20%,transparent)] hover:text-text active:scale-90"
          >
            <Minus size={14} />
          </button>
          <button
            aria-label="最大化或还原"
            onClick={() => native.windowAction('maximize')}
            className="grid h-full w-[46px] place-items-center text-secondary transition-[background-color,color,transform] duration-150 hover:bg-[color-mix(in_srgb,var(--muted)_20%,transparent)] hover:text-text active:scale-90"
          >
            <Square size={11} />
          </button>
          <button
            aria-label="关闭窗口"
            onClick={() => native.windowAction('close')}
            className="grid h-full w-[46px] place-items-center text-secondary transition-[background-color,color,transform] duration-150 hover:bg-[#c9474b] hover:text-white active:scale-90 active:bg-[#b03c40]"
          >
            <X size={16} />
          </button>
        </div>
      ) : null}
    </header>
  );
}
