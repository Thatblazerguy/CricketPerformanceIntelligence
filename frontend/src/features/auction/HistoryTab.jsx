import { Fragment, useMemo, useState } from 'react';
import { auctionAnalytics } from '../../services/api';
import { BarChart, GroupedBarChart, MultiSeriesLine, PALETTE, ScatterChart } from '../../components/charts';
import { Badge, ErrorState, FilterBar, FilterField, KpiGrid, Panel, PanelSkeleton, Select } from '../../components/ui';
import { DASH, Prov, fmtL, fmtPct, roleLabel, useAsync, verificationKind } from './auctionUi';

const FRANCHISES = ['CSK', 'DC', 'GT', 'KKR', 'LSG', 'MI', 'PBKS', 'RCB', 'RR', 'SRH', 'DCH', 'KTK', 'PWI', 'RPS', 'GL'];
const YEARS = Array.from({ length: 19 }, (_, i) => 2008 + i);

export default function HistoryTab() {
  const [f, setF] = useState({ season_from: '2014', season_to: '2026', franchise: '', role: '', overseas: '' });
  const params = useMemo(() => ({ ...f, overseas: f.overseas === '' ? undefined : f.overseas }), [f]);
  const { data, error, loading } = useAsync(() => auctionAnalytics.history(params), [JSON.stringify(params)]);
  const set = k => v => setF(x => ({ ...x, [k]: v }));
  const active = Object.entries(f).filter(([k, v]) => v && !(k === 'season_from' && v === '2014') && !(k === 'season_to' && v === '2026')).length;

  return (
    <div className="space-y-5">
      <FilterBar onReset={() => setF({ season_from: '2014', season_to: '2026', franchise: '', role: '', overseas: '' })} active={active}
        note={data ? `${data.records.toLocaleString()} auction records (${data.sold_records.toLocaleString()} sold with a non-conflicting price) contribute to this view. All prices are recorded actuals, not CPI estimates.` : undefined}>
        <FilterField label="From"><Select value={f.season_from} onChange={set('season_from')} options={YEARS.map(String)} /></FilterField>
        <FilterField label="To"><Select value={f.season_to} onChange={set('season_to')} options={YEARS.map(String)} /></FilterField>
        <FilterField label="Franchise"><Select value={f.franchise} onChange={set('franchise')} placeholder="All" options={FRANCHISES} /></FilterField>
        <FilterField label="Role"><Select value={f.role} onChange={set('role')} placeholder="All" options={['BAT', 'BOWL', 'AR', 'WK'].map(id => ({ id, label: roleLabel(id) }))} /></FilterField>
        <FilterField label="Origin"><Select value={f.overseas} onChange={set('overseas')} placeholder="All" options={[{ id: 'false', label: 'Domestic' }, { id: 'true', label: 'Overseas' }]} /></FilterField>
      </FilterBar>
      {error && <ErrorState message={error} />}
      {!data && loading && <PanelSkeleton rows={8} />}
      {data && (
        <div className={`space-y-5 ${loading ? 'opacity-60' : ''}`}>
          <KpiGrid items={[
            { label: 'Sold (priced)', value: data.sold_records.toLocaleString() },
            { label: 'Total spend', value: fmtL(data.by_season.reduce((a, s) => a + (s.total_spend_lakh || 0), 0)), highlight: true },
            { label: 'Median multiple of base', value: data.base_multiple.median ? `${data.base_multiple.median}×` : DASH, sub: `${data.base_multiple.n} sales with base price` },
            { label: 'Sold at base', value: fmtPct(data.base_multiple.share_at_base) },
            { label: '≥3× base', value: fmtPct(data.base_multiple.share_3x_plus) },
            { label: 'Mega vs mini median', value: `${fmtL(data.mega_vs_mini.MEGA?.median_lakh)} / ${fmtL(data.mega_vs_mini.MINI?.median_lakh)}` },
          ]} />
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <MultiSeriesLine title="Auction inflation" subtitle="Average sale price as a share of the season purse — comparable across seasons with different purses"
              series={[{ name: 'Avg price ÷ purse', points: data.by_season.filter(s => s.avg_share_of_purse).map(s => ({ x: s.season, y: s.avg_share_of_purse * 100 })) }]}
              xLabel="Season" yLabel="% of purse" yFormatter={v => `${v.toFixed(1)}%`} xFormatter={v => String(v)} footnote="Seasons without a recorded purse (pre-2014) are omitted rather than estimated." />
            <GroupedBarChart title="Average and median price by season" categories={data.by_season.map(s => String(s.season))}
              series={[{ name: 'Average', values: data.by_season.map(s => s.avg_price_lakh) }, { name: 'Median', values: data.by_season.map(s => s.median_price_lakh) }]} formatter={v => fmtL(v)} yLabel="Lakh" />
            <BarChart title="Total spending per franchise" subtitle="Recorded auction purchases in the selected seasons" data={data.by_franchise.map(r => ({ label: r.franchise, value: r.spend_lakh, detail: `${r.purchases} purchases · avg ${fmtL(r.avg_lakh)}` }))} formatter={v => fmtL(v)} />
            <GroupedBarChart title="Role-wise spending by season" stacked categories={data.role_spend_by_season.map(r => String(r.season))}
              series={['BAT', 'BOWL', 'AR', 'WK'].map((k, i) => ({ name: roleLabel(k), color: [PALETTE[0], PALETTE[5], PALETTE[2], PALETTE[3]][i], values: data.role_spend_by_season.map(r => r[k] ?? null) }))}
              formatter={v => fmtL(v)} footnote="Records with unknown role are excluded from this chart." />
            <ScatterChart title="Base price vs final price" subtitle="Sales where the base price is recorded (2011, 2021–2026)" height={320}
              data={data.base_vs_final.map(r => ({ ...r, name: `${r.name} (${r.season})`, group: roleLabel(r.role), color: { BAT: PALETTE[0], BOWL: PALETTE[5], AR: PALETTE[2], WK: PALETTE[3] }[r.role] || PALETTE[7], detail: `${r.franchise || ''}` }))}
              xKey="base" yKey="final" xLabel="Base price (L)" yLabel="Final price (L)" formatX={v => Math.round(v)} formatY={v => Math.round(v)} />
            <Panel title="Price distribution by role" subtitle="Recorded sale prices (lakh)" actions={<Prov kind="actual" />}>
              <table className="w-full text-xs"><thead className="text-left text-2xs text-slate-500"><tr><th className="py-1">Role</th><th className="text-right">n</th><th className="text-right">p25</th><th className="text-right">Median</th><th className="text-right">p75</th><th className="text-right">p90</th><th className="text-right">Max</th></tr></thead>
                <tbody>{Object.entries(data.by_role).map(([k, d]) => <tr key={k} className="border-t border-line-soft"><td className="py-1.5 text-slate-200">{roleLabel(k)}</td>{['n', 'p25', 'median', 'p75', 'p90', 'max'].map(c => <td key={c} className="num text-right">{c === 'n' ? d.n : fmtL(d[c])}</td>)}</tr>)}</tbody></table>
              <div className="mt-4 grid grid-cols-2 gap-3 text-xs">{Object.entries(data.mega_vs_mini).map(([k, v]) => (
                <div key={k} className="rounded-2xl border border-line p-3"><p className="mb-1 font-medium text-white">{k === 'MEGA' ? 'Mega auctions' : 'Mini auctions'}</p>
                  <p className="text-slate-400">{v.sold} sales · median {fmtL(v.median_lakh)} · {fmtPct(v.median_share_of_purse, 2)} of purse · {fmtPct(v.share_over_5pct_purse)} cost ≥5% of a purse</p></div>))}</div>
            </Panel>
          </div>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <TopList title="Most expensive" rows={data.most_expensive} />
            <TopList title="Most expensive Indian players" rows={data.most_expensive_indian} />
            <TopList title="Most expensive overseas players" rows={data.most_expensive_overseas} />
          </div>
          <Panel title="Season summary" bodyClassName="p-0">
            <div className="overflow-x-auto"><table className="w-full text-xs"><thead className="bg-surface-raised text-left text-2xs text-slate-500"><tr><th className="px-4 py-2">Season</th><th>Type</th><th className="text-right">Sold</th><th className="text-right">Unsold recorded</th><th className="text-right">Spend</th><th className="text-right">Max</th><th className="text-right">Uncapped spend</th><th className="px-4 text-right">Purse</th></tr></thead>
              <tbody>{data.by_season.map(s => <tr key={s.season} className="border-t border-line-soft"><td className="px-4 py-1.5 text-slate-200">{s.season}</td><td>{s.auction_type}</td><td className="num text-right">{s.sold}</td><td className="num text-right">{s.unsold_recorded || DASH}</td><td className="num text-right">{fmtL(s.total_spend_lakh)}</td><td className="num text-right">{fmtL(s.max_price_lakh)}</td><td className="num text-right">{s.uncapped_known ? fmtL(s.uncapped_spend_lakh) : DASH}</td><td className="num px-4 text-right">{fmtL(s.purse_lakh)}</td></tr>)}</tbody></table></div>
          </Panel>
          <RecordsTable filters={f} />
          <ul className="list-disc space-y-1 pl-4 text-2xs text-slate-500">{data.notes.map(n => <li key={n}>{n}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

function TopList({ title, rows }) {
  return (
    <Panel title={title} actions={<Prov kind="actual" />} bodyClassName="p-0">
      <ul className="divide-y divide-line-soft">{rows.slice(0, 10).map(r => (
        <li key={r.id} className="flex justify-between gap-2 px-5 py-1.5 text-xs"><span className="truncate text-slate-200">{r.player} <span className="text-slate-500">{r.season} · {r.franchise}</span></span><span className="num text-slate-100">{fmtL(r.price_lakh)}</span></li>))}</ul>
    </Panel>
  );
}

function RecordsTable({ filters }) {
  const [season, setSeason] = useState('');
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState(null);
  const params = { season, status, search, franchise: filters.franchise, role: filters.role, overseas: filters.overseas === '' ? undefined : filters.overseas, page, page_size: 25 };
  const { data } = useAsync(() => auctionAnalytics.historyRecords(params), [JSON.stringify(params)]);
  const pages = data ? Math.max(1, Math.ceil(data.total / 25)) : 1;
  return (
    <Panel title="Auction records" subtitle="Every record carries its sources and verification status. Click a row for provenance." actions={<div className="flex flex-wrap gap-2">
      <input type="search" value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} placeholder="Player" className="h-8 w-36 text-xs" />
      <Select value={season} onChange={v => { setSeason(v); setPage(1); }} placeholder="All seasons" options={YEARS.map(String).reverse()} className="h-8" />
      <Select value={status} onChange={v => { setStatus(v); setPage(1); }} placeholder="Any status" options={['SOLD', 'UNSOLD']} className="h-8" /></div>} bodyClassName="p-0">
      {!data ? <div className="p-5"><PanelSkeleton rows={4} /></div> : (
        <>
          <div className="overflow-x-auto"><table className="w-full text-xs"><thead className="bg-surface-raised text-left text-2xs text-slate-500"><tr><th className="px-4 py-2">Season</th><th>Player</th><th>Status</th><th>Franchise</th><th>Role</th><th className="text-right">Base</th><th className="text-right">Price</th><th>Set</th><th className="px-4">Verification</th></tr></thead>
            <tbody>{data.items.map(r => (
              <Fragment key={r.id}>
                <tr onClick={() => setOpen(open === r.id ? null : r.id)} className="cursor-pointer border-t border-line-soft hover:bg-surface-hover">
                  <td className="num px-4 py-1.5">{r.season}</td><td className="text-slate-200">{r.player}{r.is_rtm && <Badge className="ml-1">RTM</Badge>}{!r.player_id && <Badge variant="amber" className="ml-1">unlinked</Badge>}</td>
                  <td>{r.status}</td><td>{r.franchise || DASH}{r.previous_franchise && r.previous_franchise !== r.franchise ? <span className="text-slate-500"> (from {r.previous_franchise})</span> : ''}</td>
                  <td>{roleLabel(r.role)}{r.overseas ? ' · OS' : ''}</td><td className="num text-right">{fmtL(r.base_lakh)}</td><td className="num text-right">{fmtL(r.price_lakh)}</td><td>{r.set_code || DASH}</td>
                  <td className="px-4"><Prov kind={verificationKind(r.verification)} /></td>
                </tr>
                {open === r.id && <tr className="bg-surface-sunken"><td colSpan={9} className="px-4 py-2 text-2xs text-slate-400">
                  {r.sources.map((s, i) => <div key={i}>{s.source} · {s.status} · {s.price_lakh != null ? fmtL(s.price_lakh) : 'no price'}{s.url && <> · <a className="underline" href={s.url} target="_blank" rel="noreferrer">source</a></>}{s.revision ? ` · rev ${s.revision}` : ''}</div>)}
                  {r.conflict_note && <div className="text-warn-soft">{r.conflict_note}</div>}
                  <div>Identity: {r.identity_status.toLowerCase()}</div></td></tr>}
              </Fragment>))}</tbody></table></div>
          <div className="flex items-center justify-between px-5 py-3 text-2xs text-slate-500"><span className="num">{data.total.toLocaleString()} records · page {page}/{pages}</span>
            <div className="flex gap-1"><button className="btn btn-secondary btn-xs" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</button><button className="btn btn-secondary btn-xs" disabled={page >= pages} onClick={() => setPage(p => p + 1)}>Next</button></div></div>
        </>
      )}
    </Panel>
  );
}
