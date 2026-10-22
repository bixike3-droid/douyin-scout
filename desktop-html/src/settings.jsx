import React, { useEffect, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import {
  Settings2, Sun, Moon, Monitor, ShieldCheck, FileText, Database, FolderOpen, Check, Loader2,
} from 'lucide-react';
import { api, modelName } from './api.js';
import {
  Badge, Button, Card, Field, Input, Select, Segmented, Separator, Textarea, cn,
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
    dark: 'border-[#2d3240] bg-[#22252d]',
    system: 'border-[#e2e5ed] bg-[linear-gradient(90deg,#fafbfe_50%,#22252d_50%)]',
  }[value];
  const rail = { light: 'bg-[#e8ebf2]', dark: 'bg-[#181b21]', system: 'bg-[#c9cfdd]/70' }[value];
  const bar = { light: 'bg-[#dfe4ef]', dark: 'bg-[#434958]', system: 'bg-[#ffffff]/45' }[value];
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
  settings, onSettings, profile, onProfile, preferences, onTheme, native, notify, busy,
}) {
  const [tab, setTab] = useState('model');
  const [values, setValues] = useState({ ...settings, api_key: '' });
  const [enterprise, setEnterprise] = useState(profile || {});
  const [saving, setSaving] = useState(false);

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
    <div className="standard-page">
      <div className="mx-auto flex w-full max-w-[860px] flex-col gap-5 pb-10">
        <header>
          <h1 className="text-[22px] font-[550] tracking-[-0.4px] text-text">设置</h1>
          <p className="mt-2 text-[12px] leading-relaxed text-muted">配置模型服务、工作资料和本地界面。</p>
        </header>

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

                  <Field label="对话引擎">
                    <Select
                      aria-label="对话引擎"
                      value={values.agent_engine || 'native'}
                      onChange={(agent_engine) => setValues({ ...values, agent_engine })}
                    >
                      <option value="native">源镜</option>
                      <option value="codex">Codex · 试用</option>
                    </Select>
                  </Field>
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
                Qt 版与 HTML 版可共用已有数据；原版启动入口仍保留。
              </p>
            </div>
          </Card>
        ) : null}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
