/**
 * Historical backtesting: rolling-origin evaluation of CPI's auction price model
 * against actual results and simple baselines.
 */
import { useEffect, useMemo, useState } from 'react';
import { auctionAnalytics } from '../../services/api';
import { BarChart, GroupedBarChart, Histogram, MultiSeriesLine, PALETTE, ScatterChart } from '../../components/charts';
import { Badge, Button, Callout, ErrorState, KpiGrid, Panel, PanelSkeleton, Select } from '../../components/ui';
import { DASH, Prov, fmtL, fmtNum, fmtPct, roleLabel, useAsync } from './auctionUi';

const BASELINES = [['cpi', 'CPI model'], ['baseline_performance_only', 'Performance only'], ['baseline_role_median', 'Role median'], ['baseline_base_price', 'Base price']];

export default function BacktestTab() {
  const [version, setVersion] = useState('');
  const [reload, setReload] = useState(0);
  const { data, error, loading } = useAsync(() => auctionAnalytics.backtest(version || undefined), [version, reload]);
  const [season, setSeason] = useState('');
  const preds = useAsync(() => auctionAnalytics.backtestPredictions(season || undefined, data?.run?.version), [season, data?.run?.version]);
  const [job, setJob] = useState(null);

  useEffect(() => {
    if (job?.status !== 'started' && job?.status !== 'already running') return undefined;
    const t = setInterval(() => auctionAnalytics.backtestStatus().then(s => { if (!s.running) { setJob(s.last); setReload(x => x + 1); } }), 5000);
    return () => clearInterval(t);
  }, [job]);

  if (error) return <ErrorState message={error} />;
  if (!data) return <PanelSkeleton rows={8} />;
  if (!data.run) return <Callout>No backtest has been run yet. <Button size="sm" onClick={() => auctionAnalytics.backtestRun().then(setJob)}>Run backtest</Button></Callout>;
  const ev = data.run.evaluation;
  const pooled = ev.pooled;
  const seasons = ev.per_season.map(s => s.season);
  const items = preds.data?.items || [];
  const sold = items.filter(i => i.status === 'SOLD' && i.p50 != null);

  return (
    <div className={`space-y-5 ${loading ? 'opacity-60' : ''}`}>
      <Panel title="How the backtest works" actions={<div className="flex items-center gap-2">
        <Select value={version} onChange={setVersion} placeholder="Latest version" options={data.versions.filter(v => v.task === 'v2_backtest').map(v => ({ id: v.version, label: `${v.version} · MAE ${fmtL(v.pooled_mae_lakh)}` }))} className="h-8 w-80" />
        <Button size="sm" onClick={() => auctionAnalytics.backtestRun().then(setJob)} disabled={job?.status === 'started'}>{job?.status === 'started' ? 'Running…' : 'Re-run backtest'}</Button></div>}>
        <p className="text-xs leading-relaxed text-slate-400">{ev.protocol}. Target: {ev.target}. Excluded: {ev.excluded}. To predict a season, the model sees only earlier seasons; player features are computed from matches before that auction's date, and prior prices come only from earlier auctions — no future statistics, prices, purchases or classifications leak in.</p>
        {job?.status === 'failed' && <p className="mt-2 text-xs text-neg-soft">Backtest failed: {job.error}</p>}
      </Panel>
      <KpiGrid items={[
        { label: 'Sales evaluated', value: pooled.cpi.n.toLocaleString(), sub: `${seasons[0]}–${seasons[seasons.length - 1]}` },
        { label: 'CPI MAE', value: fmtL(pooled.cpi.mae_lakh), highlight: true, sub: `median error ${fmtL(pooled.cpi.median_ae_lakh)}` },
        { label: 'CPI RMSE', value: fmtL(pooled.cpi.rmse_lakh) },
        { label: '80% range coverage', value: fmtPct(pooled.cpi.coverage_80), sub: 'Target ≈ 80%', tone: Math.abs(pooled.cpi.coverage_80 - 0.8) <= 0.07 ? 'pos' : 'warn' },
        { label: 'Bias (mean)', value: fmtL(pooled.cpi.bias_lakh), sub: 'p50 is a median; right-skewed prices pull the mean' },
        { label: 'MAPE', value: `${fmtNum(pooled.cpi.mape_pct, 0)}%`, sub: 'Sale prices > 0 so MAPE is defined' },
      ]} />
      <Panel title="CPI vs baselines" subtitle="Same rolling protocol for every method. CPI must beat simple baselines before its predictions are trusted." actions={<Prov kind="calculated" />} bodyClassName="p-0">
        <table className="w-full text-[13px]"><thead className="bg-surface-raised text-left text-2xs uppercase text-slate-500"><tr><th className="px-5 py-2">Method</th><th className="text-right">n</th><th className="text-right">MAE</th><th className="text-right">RMSE</th><th className="text-right">Median AE</th><th className="text-right">Log MAE</th><th className="px-5">CPI better?</th></tr></thead>
          <tbody>{BASELINES.map(([k, label]) => { const m = pooled[k]; return m?.n ? (
            <tr key={k} className="border-t border-line-soft"><td className="px-5 py-2 text-white">{label}{k === 'baseline_base_price' && <span className="text-2xs text-slate-500"> (rows with known base)</span>}</td>
              <td className="num text-right">{m.n}</td><td className="num text-right">{fmtL(m.mae_lakh)}</td><td className="num text-right">{fmtL(m.rmse_lakh)}</td><td className="num text-right">{fmtL(m.median_ae_lakh)}</td><td className="num text-right">{fmtNum(m.log_mae, 3)}</td>
              <td className="px-5">{k === 'cpi' ? DASH : pooled.beats_baselines?.[k] ? <Badge variant="green">Yes</Badge> : <Badge variant="red">No</Badge>}</td></tr>) : null; })}
            {pooled.cpi_on_base_known_rows?.n && <tr className="border-t border-line-soft"><td className="px-5 py-2 text-slate-300">CPI on the same base-known rows</td><td className="num text-right">{pooled.cpi_on_base_known_rows.n}</td><td className="num text-right">{fmtL(pooled.cpi_on_base_known_rows.mae_lakh)}</td><td className="num text-right">{fmtL(pooled.cpi_on_base_known_rows.rmse_lakh)}</td><td className="num text-right">{fmtL(pooled.cpi_on_base_known_rows.median_ae_lakh)}</td><td className="num text-right">{fmtNum(pooled.cpi_on_base_known_rows.log_mae, 3)}</td><td className="px-5 text-2xs text-slate-500">like-for-like vs base price</td></tr>}
          </tbody></table>
      </Panel>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <MultiSeriesLine title="Season-over-season error" subtitle="MAE per test season (lower is better)" xFormatter={v => String(v)} yFormatter={v => fmtL(v)} xLabel="Test season" yLabel="MAE"
          series={BASELINES.slice(0, 3).map(([k, label], i) => ({ name: label, color: PALETTE[i], points: ev.per_season.map(s => ({ x: s.season, y: s[k]?.mae_lakh })) }))} />
        <GroupedBarChart title="Range coverage by season" subtitle="Share of actual prices inside CPI's 80% range" categories={seasons.map(String)}
          series={[{ name: 'Coverage', values: ev.per_season.map(s => (s.cpi.coverage_80 ?? 0) * 100) }]} formatter={v => `${v.toFixed(0)}%`} yLabel="%" />
      </div>
      <Panel title="Prediction vs reality" subtitle="Choose a test season to inspect individual predictions" actions={<Select value={season} onChange={setSeason} placeholder="All seasons" options={seasons.map(String).reverse()} className="h-8" />}>
        {preds.loading && <PanelSkeleton rows={4} />}
        {!preds.loading && (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <ScatterChart title="Predicted vs actual price" subtitle="Log-scale (log10 lakh). Points on the dashed diagonal are exact." height={340}
              data={sold.map(i => ({ name: `${i.player} (${i.season})`, x: Math.log10(i.actual_lakh), y: Math.log10(Math.max(i.p50, 1)), group: roleLabel(i.role), color: { BAT: PALETTE[0], BOWL: PALETTE[5], AR: PALETTE[2], WK: PALETTE[3] }[i.role] || PALETTE[7], detail: `actual ${fmtL(i.actual_lakh)} · predicted ${fmtL(i.p50)} (${fmtL(i.p10)}–${fmtL(i.p90)})` }))}
              xKey="x" yKey="y" xLabel="Actual (log10 L)" yLabel="Predicted p50 (log10 L)" formatX={v => fmtL(10 ** v, { short: true })} formatY={v => fmtL(10 ** v, { short: true })} />
            <Histogram title="Prediction error distribution" subtitle="log(predicted ÷ actual): 0 = exact, +0.69 = 2× too high" bins={errorBins(sold)} xLabel="Log error" />
          </div>
        )}
      </Panel>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <BarChart title="Accuracy by role" subtitle="MAE (lakh), pooled seasons" data={Object.entries(pooled.by_role || {}).map(([k, m]) => ({ label: `${roleLabel(k)} (${m.n})`, value: m.mae_lakh, detail: `coverage ${fmtPct(m.coverage_80)}` }))} formatter={v => fmtL(v)} />
        <BarChart title="Accuracy by franchise" subtitle="MAE for each buying franchise" data={Object.entries(pooled.by_franchise || {}).filter(([k]) => k !== 'None').sort((a, b) => a[1].mae_lakh - b[1].mae_lakh).map(([k, m]) => ({ label: `${k} (${m.n})`, value: m.mae_lakh }))} formatter={v => fmtL(v)} />
        <Panel title="Where the model is biased" subtitle="Median log error by segment (≥25 sales). Used to target the next model version." actions={<Prov kind="calculated" />}>
          {(pooled.error_diagnostics || []).map(d => <div key={d.segment} className="flex justify-between border-b border-line-soft py-1.5 text-xs"><span className="text-slate-300">{d.segment.replace('role=', 'Role: ').replace('overseas=True', 'Overseas').replace('overseas=False', 'Domestic')}</span><span className="num text-slate-400">{d.median_log_error > 0 ? '+' : ''}{d.median_log_error} · <span className={d.direction === 'unbiased' ? 'text-pos-soft' : 'text-warn-soft'}>{d.direction}</span></span></div>)}
        </Panel>
      </div>
      <Panel title="Sold / unsold classification" subtitle="Only seasons whose sources record unsold players can be evaluated. Probabilities are prior-shifted to open slots ÷ pool size when both are known before the auction." actions={<Badge variant="amber">Experimental</Badge>} bodyClassName="p-0">
        <table className="w-full text-xs"><thead className="bg-surface-raised text-left text-2xs uppercase text-slate-500"><tr><th className="px-5 py-2">Season</th><th className="text-right">n</th><th className="text-right">AUC</th><th className="text-right">Accuracy</th><th className="text-right">Majority-class acc.</th><th className="text-right">Brier</th><th className="text-right">Majority Brier</th><th className="text-right">Sold P / R / F1</th><th className="px-5">Beats naive?</th></tr></thead>
          <tbody>{ev.classification.map(c => c.skipped ? <tr key={c.season} className="border-t border-line-soft"><td className="px-5 py-2">{c.season}</td><td colSpan={8} className="text-slate-500">{c.skipped}</td></tr> : (
            <tr key={c.season} className="border-t border-line-soft"><td className="px-5 py-2 text-white">{c.season}</td><td className="num text-right">{c.n}</td><td className="num text-right">{fmtNum(c.auc, 3)}</td><td className="num text-right">{fmtPct(c.accuracy, 1)}</td><td className="num text-right">{fmtPct(c.majority_class_accuracy, 1)}</td>
              <td className="num text-right">{fmtNum(c.brier, 3)}</td><td className="num text-right">{fmtNum(c.majority_class_brier, 3)}</td><td className="num text-right">{fmtNum(c.sold_precision, 2)} / {fmtNum(c.sold_recall, 2)} / {fmtNum(c.sold_f1, 2)}</td>
              <td className="px-5">{c.accuracy > c.majority_class_accuracy && c.brier < c.majority_class_brier ? <Badge variant="green">Yes</Badge> : <Badge variant="red">No</Badge>}</td></tr>))}</tbody></table>
        <p className="px-5 py-3 text-2xs text-slate-500">{ev.classification.filter(c => !c.skipped).map(c => `${c.season}: ${c.expected_rate_basis}`).join(' · ')}. Sale probabilities are therefore labelled experimental throughout Auction Intelligence.</p>
      </Panel>
      <Panel title="Model versions" bodyClassName="p-0">
        <table className="w-full text-xs"><tbody>{data.versions.map(v => <tr key={v.version} className="border-t border-line-soft"><td className="px-5 py-1.5 text-slate-200">{v.version}</td><td>{v.task}</td><td className="num text-right">{v.rows}</td><td className="num text-right">{v.pooled_mae_lakh != null ? `MAE ${fmtL(v.pooled_mae_lakh)}` : DASH}</td><td className="num px-5 text-right text-slate-500">{v.created_at.slice(0, 16).replace('T', ' ')}</td></tr>)}</tbody></table>
        <p className="px-5 py-3 text-2xs text-slate-500">price_regression = the earlier RandomForest baseline (evaluated on a different, single split; not directly comparable). v2_backtest = rolling-origin evaluations; v2_price = the production model used for scenarios.</p>
      </Panel>
    </div>
  );
}

function errorBins(rows) {
  const edges = [-3, -2, -1.5, -1, -0.5, -0.25, 0.25, 0.5, 1, 1.5, 2, 3];
  const errs = rows.map(r => Math.log(Math.max(r.p50, 1) / r.actual_lakh));
  return edges.slice(0, -1).map((lo, i) => ({ label: `${lo}…${edges[i + 1]}`, count: errs.filter(e => e >= lo && (i === edges.length - 2 ? e <= edges[i + 1] : e < edges[i + 1])).length }));
}
