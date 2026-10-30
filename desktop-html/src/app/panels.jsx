import React from 'react';
import { LogIn, ShieldCheck, ShieldOff } from 'lucide-react';
import { Modal } from '../ui/media.jsx';
import { Button, Separator } from '../ui/kit.jsx';
import { UserAvatar } from '../ui/avatar.jsx';
import { SettingsPage } from '../settings.jsx';

/* 账号区的三个弹窗：账号与安全、隐私说明、设置。
   统一由 Modal 提供磨砂遮罩、圆角与右上角关闭键。 */

export function AccountPanel({ account, loginSaved, onLogin, busy, onClose }) {
  const name = account?.nickname || '';
  return (
    <Modal
      title="账号与安全"
      subtitle="登录态只保存在本机，不会上传。"
      onClose={onClose}
      className="w-[min(560px,100%)]"
    >
      <div className="max-h-[70vh] overflow-y-auto px-6 py-5">
        <div className="flex items-center gap-3.5">
          <UserAvatar src={account?.avatar_url} name={name} size={52} />
          <div className="min-w-0">
            <p className="truncate text-[14px] font-medium text-text">{name || '尚未登录抖音'}</p>
            <p className="mt-1 text-[11px] text-muted">
              {loginSaved ? '登录态已保存，采集时会自动复用' : '还没有保存登录态'}
            </p>
          </div>
        </div>

        {account?.sec_uid ? (
          <p className="mt-3 break-all rounded-[8px] bg-subtle px-3 py-2 text-[10.5px] leading-relaxed text-muted">
            账号 ID：{account.sec_uid}
          </p>
        ) : null}

        <div className="mt-4 flex items-center gap-2">
          <Button size="sm" disabled={busy} onClick={() => { onLogin(); onClose(); }}>
            <LogIn size={14} /> {loginSaved ? '重新登录 / 切换账号' : '登录抖音'}
          </Button>
          {busy ? <span className="text-[10.5px] text-muted">有任务正在执行，完成后再登录</span> : null}
        </div>

        <Separator className="my-4" />

        <ul className="flex flex-col gap-2 text-[11px] leading-relaxed text-muted">
          <li>· 扫码会在系统浏览器里打开，登录态保存在本机浏览器配置目录。</li>
          <li>· 切换账号会先清除旧 cookie；档 A（登录态）建议使用小号。</li>
          <li>· 只有你主动采集或调用在线模型时才会联网。</li>
        </ul>
      </div>
    </Modal>
  );
}

const PRIVACY = [
  ['只保存在本机', '采集、解析、报告生成都在本地完成；数据放在账号自己的目录里，没有云端账号。'],
  ['采集哪些数据', '只读取你登录后可见的公开互动与作品信息：昵称、头像、简介、粉丝数、点赞与评论记录，以及你自己的作品指标。'],
  ['留多久', '归档正文 7 天、日志 30 天、已完成任务 14 天，可按设置调整；互动者可单独删除其本地数据。'],
  ['什么时候联网', '只有你主动调用在线模型时发送必要摘要；检查更新只读取版本号，不发送本机数据。'],
  ['不做什么', '不实现请求签名、不伪造浏览器指纹、不破解验证码、不使用代理池或并发；自动化访问是否被平台允许由你自行确认。'],
];

export function PrivacyPanel({ onClose }) {
  return (
    <Modal
      title="隐私说明"
      subtitle="数据从哪来、存在哪、留多久。"
      onClose={onClose}
      className="w-[min(640px,100%)]"
    >
      <div className="max-h-[72vh] overflow-y-auto px-6 py-5">
        <div className="flex flex-col gap-4">
          {PRIVACY.map(([heading, body]) => (
            <section key={heading}>
              <h3 className="flex items-center gap-2 text-[12px] font-medium text-text">
                <ShieldCheck size={14} className="text-accent" />
                {heading}
              </h3>
              <p className="mt-1.5 pl-[22px] text-[11.5px] leading-relaxed text-secondary">{body}</p>
            </section>
          ))}
        </div>
        <div className="mt-5 flex items-start gap-2 rounded-[8px] border border-line bg-subtle/60 px-3 py-2.5 text-[10.5px] leading-relaxed text-muted">
          <ShieldOff size={13} className="mt-0.5 shrink-0" />
          <p>完整条款（含保留期限、删除方式与已知缺口）见随源码分发的 docs/privacy.md。</p>
        </div>
      </div>
    </Modal>
  );
}

export function SettingsPanel({
  settings, onSettings, profile, onProfile, preferences, onTheme, native, notify, busy, onClose,
}) {
  return (
    <Modal
      title="设置"
      subtitle="模型服务、企业资料与本地数据。"
      onClose={onClose}
      className="h-[min(88vh,900px)] w-[min(980px,100%)]"
    >
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        <SettingsPage
          embedded
          settings={settings}
          onSettings={onSettings}
          profile={profile}
          onProfile={onProfile}
          preferences={preferences}
          onTheme={onTheme}
          native={native}
          notify={notify}
          busy={busy}
        />
      </div>
    </Modal>
  );
}
