import React from 'react';
import { AreaTrend, BarList, ColumnTrend, Meter, StatTile, compact } from '../../ui/charts.jsx';

/*
 * 数据页顶部的概览：先给结论（数字），再给趋势（图）。
 * 图只画单一序列，播放与点赞分成两张小图（小倍数），避免双轴。
 */

const interactionRate = (totals) => {
  const interactions = (totals.digg || 0) + (totals.comment || 0) + (totals.share || 0);
  return totals.play ? (interactions * 100) / totals.play : 0;
};

export function DataInsights({ view, data }) {
  if (!data) return null;
  return view === 'works'
    ? <WorksInsights data={data.works} />
    : <AudienceInsights data={data.audience} />;
}

function Section({ title, hint, children }) {
  return (
    <section className="mb-5 rounded-[12px] border border-line bg-bg px-4 py-4">
      <div className="mb-3.5 flex items-baseline justify-between gap-3">
        <h2 className="text-[12.5px] font-medium text-text">{title}</h2>
        {hint ? <span className="text-[10.5px] text-muted">{hint}</span> : null}
      </div>
      {children}
    </section>
  );
}

function Empty({ text }) {
  return <p className="py-6 text-center text-[11.5px] text-muted">{text}</p>;
}

function WorksInsights({ data }) {
  const weeks = data.weeks || [];
  if (!data.total) {
    return <Section title="数据概览" hint="近 12 周"><Empty text="同步本人作品后，这里会出现播放与点赞趋势。" /></Section>;
  }
  const labels = weeks.map((week) => week.label);
  return (
    <Section title="数据概览" hint="近 12 周 · 全部本人作品">
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        <StatTile label="本人作品" value={data.total} suffix=" 条" />
        <StatTile label="总播放" value={data.totals.play} />
        <StatTile label="总点赞" value={data.totals.digg} />
        <StatTile label="互动率" value={interactionRate(data.totals)} decimals={1} suffix="%" hint="(赞+评+转) ÷ 播放" />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <p className="mb-1 text-[11px] text-secondary">每周播放</p>
          <AreaTrend values={weeks.map((week) => week.play)} labels={labels} name="播放" height={128} />
        </div>
        <div>
          <p className="mb-1 text-[11px] text-secondary">每周点赞</p>
          <AreaTrend values={weeks.map((week) => week.digg)} labels={labels} name="点赞" height={128} />
        </div>
      </div>

      {data.top?.length ? (
        <div className="mt-4 border-t border-line pt-3.5">
          <p className="mb-2.5 text-[11px] text-secondary">点赞最高的作品</p>
          <BarList
            name="点赞"
            labelWidth={190}
            items={data.top.map((item) => ({ label: item.description, count: item.digg }))}
            format={(value) => compact(value)}
          />
        </div>
      ) : null}
    </Section>
  );
}

function AudienceInsights({ data }) {
  const followers = (data.followers || []).filter((item) => item.count > 0);
  if (!data.total) {
    return <Section title="受众概览" hint="全部互动者"><Empty text="采集到点赞人后，这里会出现受众结构与互动趋势。" /></Section>;
  }
  return (
    <Section title="受众概览" hint="全部互动者 · 近 30 天活跃">
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        <StatTile label="互动者" value={data.total} suffix=" 人" />
        <StatTile label="互动记录" value={data.edges} suffix=" 条" />
        <StatTile label="人均互动作品" value={data.per_user} decimals={1} suffix=" 条" />
        <Meter label="资料完整度" value={data.complete_pct} hint={`${data.profiled} / ${data.total} 人已补齐资料`} />
      </div>

      <div className="mt-4 grid gap-5 lg:grid-cols-2">
        <div>
          <p className="mb-2.5 text-[11px] text-secondary">粉丝量分布</p>
          {followers.length ? <BarList name="人数" items={followers} unit=" 人" /> : <Empty text="还没有粉丝量数据。" />}
        </div>
        <div>
          <p className="mb-2.5 text-[11px] text-secondary">互动深度（按作品数）</p>
          <BarList name="人数" items={data.depth || []} unit=" 人" />
        </div>
      </div>

      <div className="mt-4 border-t border-line pt-3.5">
        <p className="mb-1 text-[11px] text-secondary">近 30 天新增互动</p>
        <ColumnTrend items={data.activity || []} name="新增互动" unit=" 条" height={116} />
      </div>
    </Section>
  );
}
