/**
 * Data coverage dashboard: what the auction dataset can and cannot support.
 */
import { useState } from 'react';
import { auctionAnalytics } from '../../services/api';
import { Badge, Button, Callout, ErrorState, KpiGrid, Panel, PanelSkeleton } from '../../components/ui';
import { DASH, Prov, fmtL, useAsync } from './auctionUi';

export default function DataTab({ onChanged }) {
  const [reload, setReload] = useState(0);
  const { data, error } = useAsync(() => auctionAnalytics.coverage(), [reload]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  async function rebuild() {
    setBusy(true); setMsg('');
    try { const r = await auctionAnalytics.rebuild(); setMsg(`Rebuilt ${r.lots.lots.toLocaleString()} reconciled auction lots from ${Object.keys(r.imported).length} normalised sources.`); setReload(x => x + 1); onChanged?.(); }
    catch (e) { setMsg(e.message); } finally { setBusy(false); }
  }

  return (
    <div className="space-y-5">
      {error && <ErrorState message={error} />}
      {!data && !error && <PanelSkeleton rows={6} />}
      {data && (
        <>
          <KpiGrid items={[
            { label: 'Auction seasons', value: data.totals.seasons, sub: '2008–2026' },
            { label: 'Auction records', value: data.totals.total.toLocaleString(), sub: 'Reconciled lots' },
            { label: 'Sold', value: data.totals.sold.toLocaleString() },
            { label: 'Unsold recorded', value: data.totals.unsold.toLocaleString(), sub: '2021 (partial), 2022, 2023' },
            { label: 'Franchises', value: data.totals.franchises },
            { label: 'Price corroborated', value: `${data.totals.price_verified_pct}%`, sub: '≥2 independent sources agree', highlight: true },
          ]} />
          <Callout>Last rebuild: {data.totals.built_at?.slice(0, 16).replace('T', ' ') || DASH}. Coverage is reported per season below — CPI does not claim complete historical coverage. {data.totals.linked.toLocaleString()} of {data.totals.total.toLocaleString()} records are linked to a CPI player.</Callout>
          <Panel title="Coverage by season" subtitle="Records, outcomes, base-price availability, verification and known gaps" actions={<Button size="sm" onClick={rebuild} disabled={busy}>{busy ? 'Rebuilding…' : 'Re-import & reconcile'}</Button>} bodyClassName="p-0">
            <div className="overflow-x-auto"><table className="w-full text-xs">
              <thead className="bg-surface-raised text-left text-2xs uppercase text-slate-500"><tr><th className="px-4 py-2">Season</th><th>Type</th><th className="text-right">Sold</th><th className="text-right">Unsold</th><th className="text-right">Retained</th><th className="text-right">Pool reported</th><th className="text-right">Base known</th><th className="text-right">Corroborated</th><th className="text-right">Linked</th><th>Purse</th><th className="px-4">Gaps</th></tr></thead>
              <tbody>{[...data.per_season].reverse().map(s => (
                <tr key={s.season} className="border-t border-line-soft align-top">
                  <td className="px-4 py-1.5 text-white">{s.season}</td><td>{s.auction_type}</td><td className="num text-right">{s.sold}</td><td className="num text-right">{s.unsold || DASH}</td><td className="num text-right">{s.retained}</td>
                  <td className="num text-right">{s.pool_size_reported || DASH}</td><td className="num text-right">{s.sold ? `${Math.round(100 * s.sold_with_base / s.sold)}%` : DASH}</td>
                  <td className="num text-right">{s.price_verified_pct}%</td><td className="num text-right">{s.linked_pct}%</td>
                  <td>{Object.entries(s.purse_basis).map(([k, v]) => <Badge key={k} variant={k === 'sourced' ? 'green' : k === 'unknown' ? 'default' : 'amber'} className="mr-1">{k.replace(/_/g, ' ')} {v}</Badge>)}</td>
                  <td className="px-4 text-slate-400">{s.gaps.join('; ') || <span className="text-pos-soft">none flagged</span>}</td>
                </tr>))}</tbody></table></div>
          </Panel>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <Panel title="Sources and provenance" bodyClassName="p-0">
              <table className="w-full text-xs"><tbody>{data.sources.map(s => (
                <tr key={s.source_name} className="border-t border-line-soft"><td className="px-5 py-2"><div className="text-slate-200">{s.source_name}</div>{s.url && <a href={s.url} target="_blank" rel="noreferrer" className="text-2xs text-accent-soft underline">{s.url.slice(0, 70)}{s.url.length > 70 ? '…' : ''}</a>}</td>
                  <td className="num text-right">{s.n.toLocaleString()}</td><td className="num text-right">{s.min_y}–{s.max_y}</td><td className="num px-5 text-right text-slate-500">{s.last_import?.slice(0, 10)}</td></tr>))}</tbody></table>
              <div className="space-y-1 px-5 py-3 text-2xs text-slate-500">{Object.entries(data.definitions).map(([k, v]) => <p key={k}><Prov kind={k === 'corroborated' ? 'verified' : k === 'single_source' ? 'single' : k === 'conflict' ? 'conflict' : 'calculated'}>{k.replace('_', ' ')}</Prov> {v}</p>)}</div>
            </Panel>
            <Panel title="Known limitations" actions={<Badge variant="amber">{data.conflicts.length} price conflicts</Badge>}>
              <ul className="list-disc space-y-1 pl-4 text-xs text-slate-400">{data.not_available.map(n => <li key={n}>{n}</li>)}
                <li>Identity: {Object.entries(data.identity).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(' · ')} (unresolved names keep their records but contribute no performance features).</li></ul>
              <div className="mt-3 max-h-48 overflow-y-auto">{data.conflicts.map(c => <p key={`${c.season}-${c.player}`} className="border-t border-line-soft py-1 text-2xs text-slate-500"><span className="text-slate-300">{c.season} {c.player}</span> — {c.note}</p>)}</div>
            </Panel>
          </div>
          {msg && <Callout>{msg}</Callout>}
        </>
      )}
    </div>
  );
}

export { fmtL };
