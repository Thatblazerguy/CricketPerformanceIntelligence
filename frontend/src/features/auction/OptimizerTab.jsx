/**
 * Purse optimisation and purchase-scenario comparison for one franchise.
 */
import { useEffect, useMemo, useState } from 'react';
import { auctionAnalytics } from '../../services/api';
import { GroupedBarChart } from '../../components/charts';
import { Badge, Button, Callout, ErrorState, FilterField, KpiGrid, LoadingSpinner, Panel, Select } from '../../components/ui';
import { DASH, Prov, fmtL, fmtNum, fmtPct, roleLabel, useAsync } from './auctionUi';

const PLANS = [
  { id: 'balanced', label: 'Balanced (p50 prices)' }, { id: 'conservative', label: 'Conservative (p75 prices)' },
];

export default function OptimizerTab({ context, onPlayer }) {
  const list = useAsync(() => auctionAnalytics.franchises(context), [context]);
  const [code, setCode] = useState('');
  const [plan, setPlan] = useState('balanced');
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (list.data && !code) setCode(list.data.franchises.find(f => f.purse.known)?.code || ''); }, [list.data]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setResult(null), [context, code, plan]);

  async function run() {
    setBusy(true); setError('');
    try { setResult(await auctionAnalytics.optimize({ context, franchise: code, plan, draws: 16 })); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  const alloc = result?.budget_allocation ? Object.entries(result.budget_allocation) : [];
  return (
    <div className="space-y-5">
      <Panel title="Budget allocation optimizer" subtitle="A mixed-integer program chooses purchases together with the resulting best XI, so a player who only duplicates an existing strength gains little. Constraints: purse, minimum/maximum squad, overseas squad and XI limits, a wicketkeeper.">
        <div className="flex flex-wrap items-end gap-3">
          <FilterField label="Franchise"><Select value={code} onChange={setCode} options={(list.data?.franchises || []).map(f => ({ id: f.code, label: `${f.code} · ${fmtL(f.purse.purse_lakh)}${f.purse.known ? '' : ' (purse unknown)'}` }))} /></FilterField>
          <FilterField label="Price assumption"><Select value={plan} onChange={setPlan} options={PLANS} /></FilterField>
          <Button variant="primary" onClick={run} disabled={busy || !code}>{busy ? 'Optimising…' : 'Optimise purse'}</Button>
        </div>
        <p className="mt-3 text-2xs text-slate-500">Prices are CPI predicted prices (model estimates). The plan is re-solved under 16 random price draws from each player's predicted range to show how robust each pick and each role budget is.</p>
      </Panel>
      {error && <ErrorState message={error} />}
      {busy && <LoadingSpinner message="Solving the squad optimisation under price uncertainty…" />}
      {result && !result.feasible && <Callout tone="warn">{result.reason}</Callout>}
      {result?.feasible && (
        <>
          <KpiGrid items={[
            { label: 'Purse', value: fmtL(result.purse_lakh) },
            { label: 'Expected spend', value: fmtL(result.expected_spend_lakh), highlight: true },
            { label: 'Expected remaining', value: fmtL(result.expected_remaining_lakh) },
            { label: 'Best XI now', value: fmtNum(result.xi_before, 0) },
            { label: 'Best XI after plan', value: fmtNum(result.xi_after, 0), tone: 'pos' },
            { label: 'Purchases', value: result.recommended.length },
          ]} />
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
            <Panel title="Recommended purchases" subtitle="Robustness = share of price draws in which the optimiser still picks the player" actions={<Prov kind="model" />} bodyClassName="p-0">
              <table className="w-full text-[13px]"><thead className="text-left text-2xs uppercase text-slate-500"><tr><th className="px-5 py-2">Player</th><th>Role</th><th className="text-right">Quality</th><th className="text-right">Expected price</th><th className="px-5 text-right">Robustness</th></tr></thead>
                <tbody>{result.recommended.sort((a, b) => b.expected_price_lakh - a.expected_price_lakh).map(r => (
                  <tr key={r.player_id || r.name} onClick={() => onPlayer(r.player_id || `name:${r.name}`)} className="cursor-pointer border-t border-line-soft hover:bg-surface-hover">
                    <td className="px-5 py-2 text-white">{r.name}{r.overseas && <Badge variant="blue" className="ml-1.5">OS</Badge>}</td><td className="text-slate-400">{roleLabel(r.role)}</td>
                    <td className="num text-right">{fmtNum(r.quality, 0)}</td><td className="num text-right">{fmtL(r.expected_price_lakh)}</td>
                    <td className="num px-5 text-right"><span className={r.robustness >= 0.7 ? 'text-pos-soft' : r.robustness >= 0.4 ? 'text-slate-200' : 'text-warn-soft'}>{fmtPct(r.robustness)}</span></td></tr>))}</tbody></table>
            </Panel>
            <GroupedBarChart title="Budget allocation by role" subtitle="Interquartile range of spend across price draws (lakh)"
              categories={alloc.map(([k]) => k)} series={[{ name: '25th pct', values: alloc.map(([, v]) => v.p25_lakh) }, { name: 'Median', values: alloc.map(([, v]) => v.median_lakh) }, { name: '75th pct', values: alloc.map(([, v]) => v.p75_lakh) }]}
              formatter={v => fmtL(v)} height={280} footnote={result.method} />
          </div>
          <ScenarioCompare context={context} code={code} />
        </>
      )}
      {!result && !busy && code && <ScenarioCompare context={context} code={code} />}
    </div>
  );
}

/** Compare up to three purchase scenarios on purse, needs and the best squad still reachable. */
function ScenarioCompare({ context, code }) {
  const players = useAsync(() => auctionAnalytics.players(context, { page_size: 200, sort: 'p50' }), [context]);
  const [scenarios, setScenarios] = useState([{ name: 'Scenario A', purchases: [] }, { name: 'Scenario B', purchases: [] }]);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const options = useMemo(() => (players.data?.items || []).map(p => ({ id: p.key, label: `${p.name} · ${fmtL(p.predicted.p50)}` })), [players.data]);
  const byKey = useMemo(() => Object.fromEntries((players.data?.items || []).map(p => [p.key, p])), [players.data]);
  const update = (i, fn) => setScenarios(s => s.map((x, j) => (j === i ? fn(x) : x)));

  async function compare() {
    setBusy(true); setError('');
    try { setResult(await auctionAnalytics.compare({ context, franchise: code, scenarios: scenarios.filter(s => s.purchases.length) })); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return (
    <Panel title="Purchase scenario comparison" subtitle="Each scenario is judged on the squad it produces and on the best squad still reachable with the purse it leaves — cheaper is not assumed better.">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {scenarios.map((s, i) => (
          <div key={i} className="rounded-2xl border border-line p-4">
            <p className="mb-2 text-[13px] font-semibold text-white">{s.name}</p>
            {s.purchases.map((p, j) => (
              <div key={j} className="mb-1.5 flex items-center gap-2 text-xs">
                <span className="min-w-0 flex-1 truncate text-slate-300">{byKey[p.player_key]?.name || p.player_key}</span>
                <input type="number" value={p.price_lakh ?? ''} onChange={e => update(i, x => ({ ...x, purchases: x.purchases.map((q, k) => (k === j ? { ...q, price_lakh: e.target.value === '' ? null : Number(e.target.value) } : q)) }))}
                  placeholder={String(Math.round(byKey[p.player_key]?.predicted.p50 || 0))} className="h-8 w-24 text-xs" aria-label="Price in lakh" />
                <button className="text-slate-500 hover:text-white" onClick={() => update(i, x => ({ ...x, purchases: x.purchases.filter((_, k) => k !== j) }))} aria-label="Remove">×</button>
              </div>))}
            <Select value="" onChange={v => v && update(i, x => ({ ...x, purchases: [...x.purchases, { player_key: v, price_lakh: null }] }))} placeholder="+ Add player" options={options} className="mt-1 w-full" />
            <p className="mt-1.5 text-2xs text-slate-500">Leave a price blank to use the predicted p50.</p>
          </div>))}
      </div>
      <div className="mt-3 flex gap-2">
        <Button variant="primary" onClick={compare} disabled={busy || !scenarios.some(s => s.purchases.length)}>{busy ? 'Evaluating…' : 'Compare scenarios'}</Button>
        {scenarios.length < 3 && <Button onClick={() => setScenarios(s => [...s, { name: `Scenario ${String.fromCharCode(65 + s.length)}`, purchases: [] }])}>Add scenario</Button>}
      </div>
      {error && <div className="mt-3"><ErrorState message={error} /></div>}
      {result && (
        <div className="mt-4 overflow-x-auto"><table className="w-full text-xs">
          <thead className="text-left text-2xs uppercase text-slate-500"><tr><th className="py-2">Scenario</th><th className="text-right">Spend</th><th className="text-right">Purse left</th><th className="text-right">XI after buys</th><th className="text-right">Best reachable XI</th><th>Critical needs still open</th><th>Then buy</th></tr></thead>
          <tbody>{result.results.map(r => (
            <tr key={r.name} className="border-t border-line-soft align-top">
              <td className="py-2 font-medium text-white">{r.name}{r.verdict && <Badge variant="green" className="ml-1.5">{r.verdict}</Badge>}{r.warnings.map(w => <p key={w} className="text-warn-soft">{w}</p>)}</td>
              <td className="num text-right">{fmtL(r.spend_lakh)}</td><td className="num text-right">{fmtL(r.purse_left_lakh)}</td>
              <td className="num text-right">{fmtNum(r.xi_after_purchases, 0)}</td><td className="num text-right">{fmtNum(r.best_reachable_xi, 0)}</td>
              <td className="max-w-[14rem] text-slate-400">{r.open_critical_needs.join(', ') || DASH}<br /><span className="text-slate-500">reserve needed {fmtL(r.reserve_for_critical_needs.total_lakh)}</span></td>
              <td className="max-w-[16rem] text-slate-400">{r.follow_up_purchases.join(', ') || DASH}</td>
            </tr>))}</tbody></table>
          <p className="mt-2 text-2xs text-slate-500">Current best XI: {fmtNum(result.xi_now, 0)}. "Best reachable XI" re-runs the optimiser on the purse each scenario leaves, using predicted prices for the rest of the pool.</p>
        </div>
      )}
    </Panel>
  );
}
