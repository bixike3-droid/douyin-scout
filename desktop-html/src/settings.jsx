import React, { useEffect, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import {
  Settings2, Sun, Moon, Monitor, ShieldCheck, FileText, Database, FolderOpen, Check, Loader2,
  RefreshCw, Download, ArrowUpRight,
} from 'lucide-react';
import { api, modelName, size } from './api.js';
import {
  Badge, Button, Card, Field, Input, Select, Segmented, Separator, Switch, Textarea, cn,
} from './ui/kit.jsx';

const EMPTY = '—';
const TABS = [
  ['model', '模型与外观'],
  ['profile', '企业资料'],
  ['storage', '本地数据'],
];

const THEMES = [
  ['light', '浅色', Sun],
  ['dark', '深色', Moon],
  ['system', '跟随系统', Monitor],
];

function ThemeTile({ value, active, icon: Icon, label, onSelect }) {
  const stage = {
    light: 'border-[#e2e5ed] bg-[#fafbfe]',
    dark: 'border-[#2e2e2e] bg-[#1a1a1a]',
    system: 'border-[#e2e5ed] bg-[linear-gradient(90deg,#fafbfe_50%,#1a1a1a_50%)]',
  }[value];
  const rail = { light: 'bg-[#e8ebf2]', dark: 'bg-[#111111]', system: 'bg-[#c9cfdd]/70' }[value];
  const bar = { light: 'bg-[#dfe4ef]', dark: 'bg-[#3a3a3a]', system: 'bg-[#ffffff]/45' }[value];
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={() => onSelect(value)}
      className={cn(
        'relative w-[134px] rounded-[10px] border p-1.5 text-left transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent/60',
        active ? 'border-accent bg-accent-soft' : 'border-line bg-bg hover:border-secondary/45',
      )}
    >
      <span className={cn('relative block h-[68px] overflow-hidden rounded-[6px] border', stage)}>
        <i className={cn('absolute inset-y-0 left-0 w-6', rail)} />
        <b className={cn('absolute left-9 right-3 top-4 block h-1.5 rounded-sm', bar)} />
        <b className={cn('absolute left-9 right-10 top-8 block h-1.5 rounded-sm', bar)} />
        <b className={cn('absolute left-9 right-16 top-12 block h-1.5 rounded-sm', bar)} />
      </span>
      <span className="flex items-center gap-1.5 px-1.5 pb-1 pt-2.5 text-[11px] text-secondary">
        <Icon size={13} />
        {label}
      </span>
      {active ? <Check size={13} className="absolute bottom-2.5 right-2.5 text-accent" /> : null}
    </button>
  );
}

export function SettingsPage({
  settings, onSettings, profile, onProfile, preferences, onTheme, native, notify, busy, embedded = false,
}) {
  const [tab, setTab] = useState('model');
  const [values, setValues] = useState({ ...settings, api_key: '' });
  const [enterprise, setEnterprise] = useState(profile || {});
  const [saving, setSaving] = useState(false);
  const [media, setMedia] = useState(null);
  const [update, setUpdate] = useState(null);
  const [checking, setChecking] = useState(false);
  const [updateError, setUpdateError] = useState('');

  useEffect(() => { api('/media').then(setMedia).catch(() => {}); }, [tab]);
  useEffect(() => { api('/update').then(setUpdate).catch(() => {}); }, [tab]);

  const download = update?.download || {};
  useEffect(() => {
    if (download.state !== 'downloading') return undefined;
    const timer = setInterval(() => { api('/update').then(setUpdate).catch(() => {}); }, 900);
    return () => clearInterval(timer);
  }, [download.state]);

  async function checkUpdate() {
    setChecking(true);
    setUpdateError('');
    try {
      setUpdate(await api('/update?check=1'));
    } catch (error) {
      setUpdateError(error.message);
    } finally {
      setChecking(false);
    }
  }

  async function startDownload() {
    setUpdateError('');
    try {
      setUpdate(await api('/update/download', { method: 'POST' }));
    } catch (error) {
      setUpdateError(error.message);
    }
  }

  async function applyUpdate() {
    try {
      await api('/update/apply', { method: 'POST' });
      notify('更新包已就绪，程序即将退出…');
      if (native) setTimeout(() => native.windowAction('close'), 1200);
    } catch (error) {
      notify(error.message);
    }
  }

  async function skipVersion(version) {
    try {
      await api('/preferences', { method: 'PUT', body: { update_skipped: version } });
      setUpdate(await api('/update'));
    } catch (error) {
      notify(error.message);
    }
  }

  async function changeAuto(value) {
    try {
      await api('/preferences', { method: 'PUT', body: { update_auto: value } });
      setUpdate(await api('/update'));
    } catch (error) {
      notify(error.message);
    }
  }

  useEffect(() => { setValues({ ...settings, api_key: '' }); }, [settings]);
  useEffect(() => { setEnterprise(profile || {}); }, [profile]);

  async function save(event) {
    event.preventDefault();
    setSaving(true);
    try {
      if (tab === 'model') {
        const data = await api('/settings', { method: 'PUT', body: values });
        onSettings(data);
        setValues({ ...data, api_key: '' });
      } else {
        const data = await api('/enterprise', { method: 'PUT', body: enterprise });
        onProfile(data.profile);
      }
      notify('设置已保存');
    } catch (error) {
      notify(error.message);
    } finally {
      setSaving(false);
    }
  }

  const configured = !!settings?.configured;
  const reduce = useReducedMotion();
  const enter = reduce
    ? { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 } }
    : { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 }, exit: { opacity: 0, y: -4 } };

  return (
    <div className={embedded ? 'flex flex-col gap-4' : 'standard-page'}>
      <div className={embedded
        ? 'flex w-full flex-col gap-5 pb-2'
        : 'mx-auto flex w-full max-w-[860px] flex-col gap-5 pb-10'}>
        {embedded ? null : (
          <header>
            <h1 className="text-[22px] font-[550] tracking-[-0.4px] text-text">设置</h1>
            <p className="mt-2 text-[12px] leading-relaxed text-muted">配置模型服务、工作资料和本地界面。</p>
          </header>
        )}

        <Segmented value={tab} options={TABS} onChange={setTab} className="self-start" />

        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={tab}
            initial={enter.initial}
            animate={enter.animate}
            exit={enter.exit}
            transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
          >
        {tab === 'model' ? (
          <div className="flex flex-col gap-4">
            <form onSubmit={save}>
              <Card
                icon={Settings2}
                title="模型服务"
                desc="源镜使用你配置的 DeepSeek 服务。"
                action={
                  <Badge tone={configured ? 'success' : 'neutral'}>
                    <i className={cn('h-1.5 w-1.5 rounded-full', configured ? 'bg-[#5d9375]' : 'bg-muted')} />
                    {configured ? '已配置' : '未配置'}
                  </Badge>
                }
                footer={
                  <div className="flex items-center justify-between gap-4">
                    <span className="flex items-center gap-1.5 text-[11px] text-muted">
                      <ShieldCheck size={13} />
                      密钥保存在本机配置中
                    </span>
                    <Button type="submit" disabled={saving || busy}>
                      {saving ? <Loader2 size={14} className="spin" /> : null}
                      {saving ? '保存中…' : '保存模型设置'}
                    </Button>
                  </div>
                }
              >
                <div className="flex flex-col gap-4">
                  <Field label="API Key" hint={configured ? settings?.masked : ''}>
                    <Input
                      aria-label="API Key"
                      type="password"
                      autoComplete="off"
                      placeholder={configured ? '留空保留当前 Key' : '输入 DeepSeek API Key'}
                      value={values.api_key}
                      onChange={(event) => setValues({ ...values, api_key: event.target.value })}
                    />
                  </Field>

                  <div className="grid grid-cols-2 gap-4">
                    <Field label="模型">
                      <Select
                        aria-label="模型"
                        value={values.model || 'deepseek-flash'}
                        onChange={(model) => setValues({ ...values, model })}
                      >
                        {!['deepseek-flash', 'deepseek-v4-pro'].includes(values.model) && values.model ? (
                          <option>{values.model}</option>
                        ) : null}
                        <option value="deepseek-flash">DeepSeek Flash</option>
                        <option value="deepseek-v4-pro">DeepSeek V4 Pro</option>
                      </Select>
                    </Field>
                    <Field label="思考强度">
                      <Select
                        aria-label="思考强度"
                        value={values.reasoning_effort || 'high'}
                        onChange={(reasoning_effort) => setValues({ ...values, reasoning_effort })}
                      >
                        <option value="low">低</option>
                        <option value="high">中</option>
                        <option value="max">高</option>
                      </Select>
                    </Field>
                  </div>
                </div>
              </Card>
            </form>

            <Card icon={Sun} title="界面外观" desc="选择适合当前环境的显示方式。">
              <div className="flex flex-wrap gap-3.5">
                {THEMES.map(([key, label, Icon]) => (
                  <ThemeTile
                    key={key}
                    value={key}
                    label={label}
                    icon={Icon}
                    active={preferences?.theme === key}
                    onSelect={onTheme}
                  />
                ))}
              </div>
            </Card>
          </div>
        ) : null}

        {tab === 'profile' ? (
          <form onSubmit={save}>
            <Card
              icon={FileText}
              title="工作资料"
              desc="这些资料会作为分析背景，可随时补充。"
              footer={
                <div className="flex justify-end">
                  <Button type="submit" disabled={saving}>
                    {saving ? '保存中…' : '保存企业资料'}
                  </Button>
                </div>
              }
            >
              <div className="flex flex-col gap-4">
                <div className="grid grid-cols-2 gap-4">
                  {[['企业／项目名称', 'name'], ['所在地', 'location']].map(([label, key]) => (
                    <Field key={key} label={label}>
                      <Input
                        value={enterprise[key] || ''}
                        onChange={(event) => setEnterprise({ ...enterprise, [key]: event.target.value })}
                      />
                    </Field>
                  ))}
                </div>
                {[
                  ['传播目标', 'goal'],
                  ['目标受众', 'audience'],
                  ['特色与优势', 'features'],
                  ['产品与服务', 'offer'],
                  ['约束与注意事项', 'constraints'],
                  ['资料来源', 'source'],
                ].map(([label, key]) => (
                  <Field key={key} label={label}>
                    <Textarea
                      rows={2}
                      value={enterprise[key] || ''}
                      onChange={(event) => setEnterprise({ ...enterprise, [key]: event.target.value })}
                    />
                  </Field>
                ))}
                <label className="flex cursor-pointer items-center gap-2.5 text-[12px] text-secondary">
                  <input
                    type="checkbox"
                    className="h-3.5 w-3.5 accent-[var(--accent)]"
                    checked={!!enterprise.account_confirmed}
                    onChange={(event) => setEnterprise({ ...enterprise, account_confirmed: event.target.checked })}
                  />
                  已确认当前抖音账号与本项目对应
                </label>
              </div>
            </Card>
          </form>
        ) : null}

        {tab === 'storage' ? (
          <>
          <Card icon={Database} title="本地工作空间" desc="对话、附件、素材观察和执行记录保存在本机。">
            <dl className="grid grid-cols-[104px_1fr] gap-x-5 gap-y-3.5 text-[12px]">
              <dt className="text-muted">配置位置</dt>
              <dd className="break-all text-text">{settings?.config_file || EMPTY}</dd>
              <dt className="text-muted">模型服务</dt>
              <dd className="break-all text-text">{settings?.base_url || EMPTY}</dd>
              <dt className="text-muted">采集浏览器</dt>
              <dd className="text-text">{settings?.browser || 'Chromium'}</dd>
              <dt className="text-muted">当前模型</dt>
              <dd className="text-text">{modelName(settings?.model) || EMPTY}</dd>
            </dl>
            <Separator className="my-5" />
            <div className="flex items-center justify-between gap-4">
              {native ? (
                <Button variant="secondary" onClick={() => native.openDataFolder()}>
                  <FolderOpen size={15} />
                  打开数据目录
                </Button>
              ) : (
                <span className="text-[11px] text-muted">当前环境不支持直接打开目录</span>
              )}
              <p className="text-right text-[11px] leading-relaxed text-muted">
                数据存在本机，换新版或重装都不会动已有作品、受众与报告。
              </p>
            </div>
            <Separator className="my-5" />
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-[12px] text-text">作品媒体</p>
                <p className="mt-1 text-[11px] text-muted">
                  {media ? (media.files ? `显式保存的副本 · ${media.files} 个 · ${size(media.bytes)}` : '尚未保存任何作品视频') : '读取中…'}
                </p>
              </div>
              <Button
                variant="secondary"
                size="sm"
                disabled={!media?.files}
                onClick={async () => {
                  try {
                    await api('/media', { method: 'DELETE' });
                    setMedia(await api('/media'));
                  } catch (error) {
                    notify(error.message);
                  }
                }}
              >
                清空
              </Button>
            </div>
          </Card>

          <Card icon={RefreshCw} title="版本与更新" desc="启动时可自动检查；下载完成后程序退出，由可见的批处理窗口完成替换并重新打开。">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[12px] text-text">当前版本 v{update?.current || EMPTY}</p>
                <p className="mt-1 text-[11px] text-muted">
                  {update ? (update.installed ? '安装版 · 支持自动更新' : '源码运行 · 只提示新版本，不自动替换') : '读取中…'}
                </p>
              </div>
              <Button variant="secondary" size="sm" disabled={checking} onClick={checkUpdate}>
                {checking ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                {checking ? '检查中…' : '检查更新'}
              </Button>
            </div>

            {updateError ? <p className="mt-3 text-[11px] text-danger">{updateError}</p> : null}

            {update?.latest && update.newer ? (
              <div className="mt-3.5 rounded-[10px] border border-line bg-subtle/40 px-3.5 py-3">
                <div className="flex items-baseline justify-between gap-3">
                  <p className="text-[12px] text-text">发现新版本 v{update.latest.version}</p>
                  <span className="text-[11px] text-muted">
                    {update.latest.zip_size ? size(update.latest.zip_size) : ''}
                  </span>
                </div>
                {update.latest.notes ? (
                  <p className="mt-1.5 line-clamp-4 whitespace-pre-line text-[11px] leading-relaxed text-secondary">
                    {update.latest.notes}
                  </p>
                ) : null}

                {download.state === 'downloading' ? (
                  <div className="mt-3">
                    <div className="h-[6px] overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--accent)_14%,var(--bg))]">
                      <div
                        className="h-full rounded-full bg-[var(--accent)] transition-[width] duration-300"
                        style={{ width: `${download.total ? Math.min(100, Math.round((download.received * 100) / download.total)) : 8}%` }}
                      />
                    </div>
                    <p className="mt-1.5 text-[10.5px] text-muted">
                      正在下载 {size(download.received)}{download.total ? ` / ${size(download.total)}` : ''}
                    </p>
                  </div>
                ) : null}

                {download.state === 'failed' ? (
                  <p className="mt-2 text-[11px] text-danger">{download.error || '下载失败'}</p>
                ) : null}

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {download.state === 'ready' ? (
                    <Button size="sm" disabled={!update.installed || !download.verified} onClick={applyUpdate}>
                      <Download size={13} /> 更新并重启
                    </Button>
                  ) : (
                    <Button size="sm" disabled={download.state === 'downloading'} onClick={startDownload}>
                      {download.state === 'downloading' ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                      {download.state === 'downloading' ? '下载中…' : download.state === 'failed' ? '重新下载' : '下载更新'}
                    </Button>
                  )}
                  <Button variant="ghost" size="sm" onClick={() => skipVersion(update.latest.version)}>
                    跳过此版本
                  </Button>
                  {update.latest.page ? (
                    <Button variant="ghost" size="sm" onClick={() => window.open(update.latest.page, '_blank', 'noopener')}>
                      <ArrowUpRight size={13} /> 发布页
                    </Button>
                  ) : null}
                </div>

                {download.state === 'ready' ? (
                  <p className="mt-2 text-[10.5px] text-muted">
                    {!download.verified
                      ? '更新源没有提供 sha256，出于安全考虑只能到发布页手动下载。'
                      : update.installed
                        ? '点击后程序退出，批处理窗口会完成替换并重新打开；窗口保持可见。'
                        : '源码运行无法自动替换，请到发布页下载安装包。'}
                  </p>
                ) : null}
              </div>
            ) : update?.latest ? (
              <p className="mt-3 text-[11px] text-muted">已是最新版本 v{update.current}</p>
            ) : update?.checked_at ? (
              <p className="mt-3 text-[11px] text-muted">检查失败：无法连接更新服务器</p>
            ) : null}

            <Separator className="my-4" />
            <div className="flex items-center justify-between gap-4">
              <label className="flex items-center gap-2.5 text-[12px] text-secondary">
                <Switch
                  checked={update?.auto_check !== false}
                  onChange={changeAuto}
                  label="启动时检查更新"
                />
                启动时检查更新
              </label>
              <span className="text-[10.5px] text-muted">
                {update?.skipped ? `已跳过 v${update.skipped}` : ''}
              </span>
            </div>
          </Card>
          </>
        ) : null}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
