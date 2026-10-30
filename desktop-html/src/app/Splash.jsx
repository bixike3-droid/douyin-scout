import React from 'react';
import { motion, useReducedMotion } from 'motion/react';
import lockupLight from '../brand/lockup-light.png';
import lockupDark from '../brand/lockup-dark.png';

/* 启动页：品牌 + 真实阶段文案。
   最长停留由调用方控制；这里不伪造进度，只做呼吸感与流光。 */
export function Splash({ stage, leaving, belowTitle = false }) {
  const reduce = useReducedMotion();
  const position = belowTitle ? 'inset-x-0 bottom-0 top-[44px]' : 'inset-0';

  return (
    <motion.div
      role="status"
      aria-live="polite"
      className={`fixed ${position} z-[400] grid place-items-center bg-[var(--canvas)]`}
      initial={false}
      animate={{ opacity: leaving ? 0 : 1 }}
      transition={{ duration: reduce ? 0 : 0.26, ease: 'easeInOut' }}
      style={{ pointerEvents: leaving ? 'none' : 'auto' }}
    >
      <div className="flex flex-col items-center gap-7">
        <div className="relative overflow-hidden">
          <motion.div
            initial={reduce ? false : { opacity: 0, y: 10, scale: 0.965 }}
            animate={{ opacity: 1, y: 0, scale: leaving && !reduce ? 1.03 : 1 }}
            transition={{ duration: reduce ? 0 : 0.62, ease: [0.16, 1, 0.3, 1] }}
          >
            <img src={lockupLight} alt="源镜" className="brand-lockup-light h-[132px] w-auto" />
            <img src={lockupDark} alt="源镜" className="brand-lockup-dark h-[132px] w-auto" />
          </motion.div>
          {reduce ? null : (
            <motion.span
              aria-hidden="true"
              className="pointer-events-none absolute inset-0"
              style={{
                background: 'linear-gradient(110deg, transparent 38%, color-mix(in srgb, var(--text) 30%, transparent) 50%, transparent 62%)',
                backgroundSize: '240% 100%',
                WebkitMaskImage: `url(${lockupLight})`,
                maskImage: `url(${lockupLight})`,
                WebkitMaskRepeat: 'no-repeat',
                maskRepeat: 'no-repeat',
                WebkitMaskSize: 'contain',
                maskSize: 'contain',
                WebkitMaskPosition: 'center',
                maskPosition: 'center',
              }}
              animate={{ backgroundPosition: ['190% 0%', '-90% 0%'] }}
              transition={{ duration: 1.6, ease: 'easeInOut', repeat: Infinity, repeatDelay: 1.0 }}
            />
          )}
        </div>

        <div className="flex flex-col items-center gap-3">
          <div className="flex items-center gap-2.5 text-[12px] text-secondary">
            <span className="flex gap-1" aria-hidden="true">
              {[0, 1, 2].map((index) => (
                <motion.i
                  key={index}
                  className="h-1 w-1 rounded-full bg-accent"
                  animate={reduce ? {} : { opacity: [0.25, 1, 0.25] }}
                  transition={{ duration: 1.2, repeat: Infinity, delay: index * 0.18, ease: 'easeInOut' }}
                />
              ))}
            </span>
            {stage}
          </div>

          <div className="h-[2px] w-[188px] overflow-hidden rounded-full bg-[var(--line)]" aria-hidden="true">
            <motion.span
              className="block h-full w-1/3 rounded-full bg-[var(--accent)]"
              animate={reduce ? { opacity: [0.4, 1, 0.4] } : { x: ['-120%', '320%'] }}
              transition={{ duration: 1.35, repeat: Infinity, ease: 'easeInOut' }}
            />
          </div>
        </div>
      </div>
    </motion.div>
  );
}
