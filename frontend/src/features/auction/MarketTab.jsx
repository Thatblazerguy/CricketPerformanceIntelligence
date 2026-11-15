import { useMemo, useState } from 'react';
import { auctionAnalytics } from '../../services/api';
import { BarChart, PALETTE, ScatterChart } from '../../components/charts';
import { Badge, Callout, ErrorState, KpiGrid, Panel, PanelSkeleton } from '../../components/ui';
import {
  ContextNotes, EMPTY_FILTERS, PlayerFilterBar, PriceRange, Prov, filterParams, fmtL, fmtNum, fmtPct, roleLabel, useAsync,
} from './auctionUi';

const ROLE_COLOR = { BAT: PALETTE[0], BOWL: PALETTE[5], AR: PALETTE[2], WK: PALETTE[3] };

export default function MarketTab({ context, onPlayer }) {
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const params = useMemo(() => filterParams(filters), [filters]);
  const { data, error, loading } = useAsync(() => auctionAnalytics.market(context, params), [context, JSON.stringify(params)]);
  const [xAxis, setXAxis] = useState('quality');

  if (error) return <ErrorState message={error} />;
  const s = data?.summary;
  return (
    <div className="space-y-5">
      <PlayerFilterBar filters={filters} setFilters={setFilters} records={data?.records} total={data?.pool_total} />
      {loading && !data && <><PanelSkeleton rows={2} /><p className="text-xs text-slate-500">First load of a replay retrains the models on earlier seasons only (≈20–40 s); later loads are cached.</p></>}
      {data && (
        <div className={`space-y-5 transition-opacity ${loading ? 'opacity-60' : ''}`}>
          <ContextNotes context={data.context} />
          <KpiGrid items={[
            { label: 'Players in pool', value: s.players.toLocaleString(), sub: `${s.domestic} domestic · ${s.overseas} overseas${s.nationality_unknown ? ` · ${s.nationality_unknown} unknown` : ''}` },
            { label: 'Estimated market value', value: fmtL(s.estimated_market_value_lakh), sub: 'Sum of predicted p50', highlight: true },
            { label: 'Open squad slots', value: s.open_squad_slots, sub: `${s.franchises} franchises` },
            { label: 'Purse available', value: fmtL(s.purse_available_lakh), sub: `${s.purse_known_franchises}/${s.franchises} purses known` },
            { label: 'Likely bidding wars', value: s.high_demand_players, sub: 'P(≥3× base) ≥ 30%' },
            { label: 'Model', value: data.model?.trained_on?.startsWith('seasons before') ? 'Leak-free' : 'Production', sub: data.model?.trained_on },
          ]} />
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <ScatterChart title={xAxis === 'quality' ? 'Player quality vs predicted price' : 'Base price vs predicted price'}
              subtitle="Each point is a pool player. Click to open the valuation. Colour = role."
              data={data.scatter.map(p => ({ ...p, x: xAxis === 'quality' ? p.quality : p.base, group: roleLabel(p.role), color: ROLE_COLOR[p.role] || PALETTE[7],
                size: 3 + (p.war || 0) * 5, detail: `${roleLabel(p.role)} · ${p.overseas ? 'Overseas' : 'Domestic'}${p.actual ? ` · actual ${fmtL(p.actual)}` : ''}` }))}
              xKey="x" yKey="p50" xLabel={xAxis === 'quality' ? 'Quality (0–100)' : 'Base price (L)'} yLabel="Predicted price (L)"
              formatX={v => Math.round(v)} formatY={v => Math.round(v)} height={340} onPointClick={p => onPlayer(p.key)}
              footnote={<span>Point size grows with bidding-war probability. <button className="underline" onClick={() => setXAxis(xAxis === 'quality' ? 'base' : 'quality')}>Switch x-axis to {xAxis === 'quality' ? 'base price' : 'quality'}</button>. Players without evidence have no quality and are omitted from the quality view.</span>} />
            <BarChart title="Predicted spend by role" subtitle="Sum of predicted p50 prices for filtered players" unit="Predicted"
              data={data.by_role.map(r => ({ label: `${roleLabel(r.role)} (${r.players})`, value: r.total_predicted_lakh, color: ROLE_COLOR[r.role],
                detail: `median ${fmtL(r.median_predicted_lakh)} · ${r.high_demand} likely bidding wars` }))}
              formatter={v => fmtL(v)} />
          </div>
          <Panel title="Role scarcity in this pool" subtitle="Computed from the actual pool: how many comparable-quality players exist in each profile. Fewer alternatives → higher scarcity."
            actions={<Prov kind="calculated" />}>
            <div className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
              {data.scarcity_groups.map(g => (
                <div key={g.group} className="flex items-center justify-between gap-2 border-b border-line-soft py-1.5 text-xs">
                  <span className="text-slate-300">{g.group}</span>
                  <span className="num text-slate-400">{g.players} players · <b className={g.quality_60_plus <= 2 ? 'text-neg-soft' : 'text-slate-200'}>{g.quality_60_plus}</b> rated 60+ · {fmtL(g.median_predicted_lakh)} median</span>
                </div>))}
            </div>
          </Panel>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <PlayerList title="Top projected valuations" rows={data.top_projected} onPlayer={onPlayer} />
            <PlayerList title="Potential bidding wars" subtitle="Highest probability of closing at ≥3× base" rows={data.bidding_wars} onPlayer={onPlayer} metric={r => fmtPct(r.bidding_war_probability)} metricLabel="P(war)" />
            <PlayerList title="Potentially undervalued" subtitle="Quality ≥ 50 with predicted price lowest relative to performance-implied value" rows={data.undervalued} onPlayer={onPlayer} metric={r => `${fmtNum(r.market_premium, 2)}×`} metricLabel="Premium" />
            <PlayerList title="Potentially overvalued" subtitle="Predicted price ≥ 1.25× performance-implied value" rows={data.overvalued} onPlayer={onPlayer} metric={r => `${fmtNum(r.market_premium, 2)}×`} metricLabel="Premium" />
            <PlayerList title="Emerging talent" subtitle="≤10 IPL matches, ranked by quality" rows={data.emerging} onPlayer={onPlayer} metric={r => fmtNum(r.quality, 0)} metricLabel="Quality" />
            <PlayerList title="High-risk purchases" subtitle="Low-confidence valuations (thin evidence), by predicted price" rows={data.high_risk} onPlayer={onPlayer} />
          </div>
          <Callout>{Object.entries(data.definitions).map(([k, v]) => <span key={k} className="mr-3 inline-block"><b className="text-slate-200">{k.replace(/_/g, ' ')}:</b> {v}</span>)}</Callout>
          <p className="text-2xs text-slate-500">Sale probability: {data.sale_probability_basis}.</p>
        </div>
      )}
    </div>
  );
}

export function PlayerList({ title, subtitle, rows, onPlayer, metric, metricLabel }) {
  const max = Math.max(...rows.map(r => r.predicted.p90 || r.predicted.p50 || 0), ...rows.map(r => r.actual?.price_lakh || 0), 1);
  return (
    <Panel title={title} subtitle={subtitle} actions={<Prov kind="model" />} bodyClassName="p-0">
      {!rows.length ? <p className="px-5 py-6 text-xs text-slate-500">No players match.</p> : (
        <ul className="divide-y divide-line-soft">
          {rows.map(r => (
            <li key={r.key}>
              <button onClick={() => onPlayer(r.key)} className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-5 py-2.5 text-left transition-colors hover:bg-surface-hover sm:grid-cols-[minmax(0,1fr)_9rem_auto]">
                <span className="min-w-0">
                  <span className="block truncate text-[13px] font-medium text-white">{r.name}</span>
                  <span className="block truncate text-2xs text-slate-500">{roleLabel(r.role)} · {r.overseas ? 'Overseas' : r.overseas === false ? 'Domestic' : 'Origin unknown'} · base {fmtL(r.base_lakh)}{r.actual ? ` · actual ${r.actual.status === 'SOLD' ? fmtL(r.actual.price_lakh) : r.actual.status}` : ''}</span>
                </span>
                <span className="hidden sm:block"><PriceRange compact p10={r.predicted.p10} p50={r.predicted.p50} p90={r.predicted.p90} actual={r.actual?.price_lakh} base={r.base_lakh} max={max} /></span>
                <span className="text-right">
                  <span className="num block text-[13px] text-slate-100">{metric ? metric(r) : fmtL(r.predicted.p50)}</span>
                  <span className="block text-3xs text-slate-500">{metricLabel || 'Predicted'}</span>
                </span>
              </button>
            </li>))}
        </ul>
      )}
    </Panel>
  );
}

export { Badge };
