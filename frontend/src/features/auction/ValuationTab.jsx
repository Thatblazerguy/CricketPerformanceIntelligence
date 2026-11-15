import { useMemo, useState } from 'react';
import { auctionAnalytics } from '../../services/api';
import { Badge, ErrorState, Panel, PanelSkeleton, Select } from '../../components/ui';
import {
  ConfidenceBadge, ContextNotes, DASH, EMPTY_FILTERS, PlayerFilterBar, PriceRange, Prov, filterParams, fmtL, fmtNum, fmtPct,
  roleLabel, useAsync,
} from './auctionUi';

const SORTS = [
  { id: 'p50', label: 'Predicted price' }, { id: 'quality', label: 'Quality' }, { id: 'war', label: 'Bidding-war probability' },
  { id: 'premium', label: 'Market premium (low→high = value)' }, { id: 'scarcity', label: 'Scarcity' }, { id: 'base', label: 'Base price' },
  { id: 'lot', label: 'Auction order' }, { id: 'actual', label: 'Actual price (replays)' }, { id: 'name', label: 'Name' },
];

export default function ValuationTab({ context, onPlayer }) {
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [sort, setSort] = useState('p50');
  const [page, setPage] = useState(1);
  const params = useMemo(() => ({ ...filterParams(filters), sort, desc: !['premium', 'lot', 'name'].includes(sort), page, page_size: 30 }), [filters, sort, page]);
  const { data, error, loading } = useAsync(() => auctionAnalytics.players(context, params), [context, JSON.stringify(params)]);
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const max = data ? Math.max(1, ...data.items.map(r => Math.max(r.predicted.p90 || 0, r.actual?.price_lakh || 0))) : 1;

  return (
    <div className="space-y-4">
      <PlayerFilterBar filters={filters} setFilters={f => { setFilters(f); setPage(1); }} records={data?.total} total={data?.total} />
      {error && <ErrorState message={error} />}
      {!data && loading && <PanelSkeleton rows={8} />}
      {data && (
        <Panel title="Player valuations" subtitle="Click a player for the full valuation, evidence, alternatives and franchise interest."
          actions={<><Prov kind="model">Predicted = model</Prov><Prov kind="actual">Actual = record</Prov>
            <Select value={sort} onChange={v => { setSort(v); setPage(1); }} options={SORTS} className="w-56" /></>}
          bodyClassName={`p-0 ${loading ? 'opacity-60' : ''}`}>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead className="bg-surface-raised text-left text-2xs text-slate-500">
                <tr>
                  <th className="px-4 py-2.5">Player</th><th className="px-3">Profile</th><th className="px-3 text-right">Base</th>
                  <th className="px-3">Predicted range (p10–p90)</th><th className="px-3 text-right">Market value</th>
                  <th className="px-3 text-right">Quality</th><th className="px-3 text-right">Scarcity</th><th className="px-3 text-right">P(war)</th>
                  <th className="px-3 text-right">P(sold)</th><th className="px-3">Confidence</th><th className="px-3 text-right">Actual</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map(r => (
                  <tr key={r.key} onClick={() => onPlayer(r.key)} className="cursor-pointer border-b border-line-soft transition-colors hover:bg-surface-hover">
                    <td className="px-4 py-2.5"><div className="font-medium text-white">{r.name}</div>
                      <div className="text-2xs text-slate-500">{r.set_code ? `Set ${r.set_code} · ` : ''}{r.lot_number ? `Lot ${r.lot_number} · ` : ''}{r.ipl_matches ?? 0} IPL matches{r.identity_status !== 'MATCHED' && r.identity_status ? ` · identity ${r.identity_status.toLowerCase()}` : ''}</div></td>
                    <td className="px-3"><div className="flex flex-wrap gap-1"><Badge>{roleLabel(r.role)}</Badge>{r.overseas && <Badge variant="blue">OS</Badge>}{(r.tags || []).slice(0, 2).map(t => <Badge key={t}>{t.replace(/_/g, ' ')}</Badge>)}</div></td>
                    <td className="num px-3 text-right">{fmtL(r.base_lakh)}</td>
                    <td className="px-3"><PriceRange p10={r.predicted.p10} p50={r.predicted.p50} p90={r.predicted.p90} actual={r.actual?.price_lakh} base={r.base_lakh} max={max} /></td>
                    <td className="num px-3 text-right">{fmtL(r.market_value_lakh)}</td>
                    <td className="num px-3 text-right">{fmtNum(r.quality, 0)}</td>
                    <td className="num px-3 text-right" title={r.scarcity?.group}>{fmtNum(r.scarcity?.score, 0)}</td>
                    <td className="num px-3 text-right">{fmtPct(r.bidding_war_probability)}</td>
                    <td className="num px-3 text-right">{fmtPct(r.sale_probability)}</td>
                    <td className="px-3"><ConfidenceBadge value={r.confidence} /></td>
                    <td className="num px-3 text-right">{r.actual ? (r.actual.status === 'SOLD' ? fmtL(r.actual.price_lakh) : <span className="text-slate-500">{r.actual.status.toLowerCase()}</span>) : DASH}</td>
                  </tr>))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between px-5 py-3 text-2xs text-slate-500">
            <span className="num">{data.total.toLocaleString()} players · page {page} / {pages}</span>
            <div className="flex gap-1">
              <button className="btn btn-secondary btn-xs" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</button>
              <button className="btn btn-secondary btn-xs" disabled={page >= pages} onClick={() => setPage(p => p + 1)}>Next</button>
            </div>
          </div>
        </Panel>
      )}
      <p className="text-2xs leading-relaxed text-slate-500">Range bar: shaded = predicted 80% range, bar = median, grey tick = base price, diamond = actual sale (replays only). Quality is pool-relative and role-specific; players with too little evidence show {DASH} rather than a guessed score.</p>
    </div>
  );
}

export { ContextNotes };
