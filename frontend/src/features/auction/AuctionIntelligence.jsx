import { useEffect, useState } from 'react';
import {
  createAuctionScenario, getAuctionScenario, getAuctionScenarios,
  getAuctionHistorySummary, importBundledAuctionSources, trainAuctionPriceModel,
  previewAuctionRetentionsCsv, importAuctionRetentionsCsv,
  previewAuctionPoolCsv, importAuctionPoolCsv,
  runAuctionScenario,
  parseAuctionRules, confirmAuctionRules, generateAuctionXI,
} from '../../services/api';
import { BarChart, LineChart, ScatterChart, RangeChart } from '../../components/charts';

const box = 'bg-slate-900 border border-slate-800 rounded-xl p-4';
const field = 'w-full mt-1 px-3 py-2 rounded bg-slate-800 border border-slate-700 text-sm text-slate-100';

export default function AuctionIntelligence() {
  const [scenarios, setScenarios] = useState([]);
  const [selected, setSelected] = useState('');
  const [detail, setDetail] = useState(null);
  const [name, setName] = useState('');
  const [season, setSeason] = useState('2026');
  const [type, setType] = useState('MEGA');
  const [retentionFile, setRetentionFile] = useState(null);
  const [poolFile, setPoolFile] = useState(null);
  const [retentionPreview, setRetentionPreview] = useState(null);
  const [poolPreview, setPoolPreview] = useState(null);
  const [history, setHistory] = useState(null);
  const [scenarioResult, setScenarioResult] = useState(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [rulesFile, setRulesFile] = useState(null);
  const [rulesDraft, setRulesDraft] = useState({ maximum_squad_size: 25, overseas_squad_limit: 8, overseas_xi_limit: 4 });
  const [xiTeam, setXiTeam] = useState('');
  const [xiStyle, setXiStyle] = useState('balanced');
  const [xiResult, setXiResult] = useState(null);
  const [predictionSearch, setPredictionSearch] = useState('');
  const [predictionPage, setPredictionPage] = useState(0);

  async function refresh(id = selected) {
    const list = await getAuctionScenarios();
    setScenarios(list);
    const current = id || list[0]?.id || '';
    setSelected(current);
    setScenarioResult(null);
    if (current) { const d = await getAuctionScenario(current); setDetail(d); setRulesDraft(d.rules || { maximum_squad_size: 25, overseas_squad_limit: 8, overseas_xi_limit: 4 }); setXiTeam(d.teams?.[0]?.id || ''); setXiResult(null); }
    else setDetail(null);
  }

  useEffect(() => {
    refresh('').catch(e => setError(e.message));
    getAuctionHistorySummary().then(setHistory).catch(e => setError(e.message));
  }, []);

  async function run(action) {
    setBusy(true); setError(''); setMessage('');
    try { await action(); }
    catch (e) { setError(e.message || 'Auction operation failed.'); }
    finally { setBusy(false); }
  }

  async function create() {
    if (!name.trim()) throw new Error('Enter a scenario name.');
    const scenario = await createAuctionScenario({ name, season, auction_type: type });
    setName(''); await refresh(scenario.id); setMessage('Scenario created. Upload the retention list and player pool CSVs.');
  }

  async function previewRetentions() {
    if (!selected || !retentionFile) throw new Error('Choose an auction scenario and retention-list CSV.');
    const report = await previewAuctionRetentionsCsv(selected, retentionFile);
    setRetentionPreview(report);
    setMessage(`Retention preview: ${report.accepted_rows} matched, ${report.rejected_rows} need attention.`);
  }
  async function importRetentions() {
    const result = await importAuctionRetentionsCsv(selected, retentionFile);
    setRetentionPreview(result); setMessage(`Retention import: ${result.accepted_rows} imported, ${result.rejected_rows} rejected.`);
    await refresh(selected);
  }
  async function previewPool() {
    if (!selected || !poolFile) throw new Error('Choose an auction scenario and player-pool CSV.');
    const report = await previewAuctionPoolCsv(selected, poolFile);
    setPoolPreview(report); setMessage(`Player-pool preview: ${report.accepted_rows} matched, ${report.rejected_rows} need attention.`);
  }
  async function importPool() {
    const result = await importAuctionPoolCsv(selected, poolFile);
    setPoolPreview(result); setMessage(`Player-pool import: ${result.accepted_rows} imported, ${result.rejected_rows} rejected. Unmatched names were preserved as basic/minimal player records when safe to do so.`);
    await refresh(selected);
  }
  async function trainFromHistory() {
    await importBundledAuctionSources();
    const trained = await trainAuctionPriceModel();
    setHistory(await getAuctionHistorySummary());
    setMessage(`Trained ${trained.version} using ${trained.training_rows} historical auction transactions.`);
  }
  async function executeScenario() {
    if (!selected) throw new Error('Choose an auction scenario first.');
    const result = await runAuctionScenario(selected);
    setScenarioResult(result);
    if (result.ready) setMessage('Scenario analysis complete. Team role needs and franchise-specific bid estimates are ready.');
  }
  const predictions = scenarioResult?.player_predictions || [];
  const matchingPredictions = predictions.filter(p => !predictionSearch ||
    `${p.player_name} ${p.role}`.toLowerCase().includes(predictionSearch.toLowerCase()));
  const predictionPageSize = 50;
  const predictionPageCount = Math.ceil(matchingPredictions.length / predictionPageSize);
  const visiblePredictions = matchingPredictions.slice(predictionPage * predictionPageSize, (predictionPage + 1) * predictionPageSize);
  async function uploadRules() { const response = await parseAuctionRules(selected, rulesFile); setRulesDraft(current => ({ ...current, ...response.proposed_rules })); setMessage(`Extracted ${Object.keys(response.proposed_rules).length} rule limits. Review and confirm them below.`); }
  async function saveRules() { const result = await confirmAuctionRules(selected, rulesDraft); setMessage(`Rules confirmed as version ${result.rules_version}.`); await refresh(selected); }
  async function runXI() { if (!xiTeam) throw new Error('Select a franchise with retained or purchased players.'); setXiResult(await generateAuctionXI(selected, xiTeam, xiStyle)); }

  const renderReport = (report, nameKey = 'canonical_name') => report && <div className="mt-3 rounded-lg bg-slate-950 border border-slate-800 p-3 text-xs max-h-48 overflow-auto space-y-1">
    <p className="text-emerald-300">Accepted: {report.accepted_rows} · Rejected: {report.rejected_rows}</p>
    {report.accepted?.slice(0, 30).map(row => <p key={`${row.row}-${row.player_id}`} className="text-slate-300">Row {row.row}: {row[nameKey] || row.player_name}{row.franchise ? ` · ${row.franchise}` : ''}</p>)}
    {report.rejected?.slice(0, 30).map(row => <p key={`${row.row}-${row.player_name}`} className="text-rose-300">Row {row.row}: {row.player_name || 'Player'} · {row.reason || row.reasons?.join(', ')}</p>)}
  </div>;

  return <div className="space-y-5">
    <header><p className="text-xs uppercase tracking-widest text-indigo-300 font-bold">CPI · Recruitment</p><h1 className="text-2xl font-bold mt-1">Auction Intelligence</h1><p className="text-sm text-slate-400 mt-1">Upload the complete retention list and auction player pool. Franchise records are created from the retention file.</p></header>
    {error && <div role="alert" className="border border-rose-800 bg-rose-950/40 text-rose-200 rounded-lg p-3 text-sm">{error}</div>}
    {message && <div role="status" className="border border-emerald-900 bg-emerald-950/30 text-emerald-200 rounded-lg p-3 text-sm">{message}</div>}

    <section className={box}>
      <div className="flex flex-wrap justify-between gap-3 items-end"><div><h2 className="font-semibold">Auction scenario</h2><p className="text-xs text-slate-500 mt-1">Select an existing season or create one before importing the two CSV files.</p></div>
        <label className="text-xs text-slate-400">Active scenario<select className={`${field} min-w-64`} value={selected} onChange={e => { refresh(e.target.value).catch(x => setError(x.message)); }}><option value="">Choose a scenario</option>{scenarios.map(x => <option key={x.id} value={x.id}>{x.season} · {x.name} · {x.status}</option>)}</select></label>
      </div>
      <div className="grid sm:grid-cols-4 gap-3 mt-4 items-end">
        <label className="text-xs text-slate-400">Scenario name<input className={field} value={name} onChange={e => setName(e.target.value)} placeholder="2026 IPL Auction" /></label>
        <label className="text-xs text-slate-400">Season<input className={field} value={season} onChange={e => setSeason(e.target.value)} /></label>
        <label className="text-xs text-slate-400">Auction type<select className={field} value={type} onChange={e => setType(e.target.value)}><option>MEGA</option><option>MINI</option><option>CUSTOM</option></select></label>
        <button disabled={busy} onClick={() => run(create)} className="rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 py-2 text-sm font-semibold">Create scenario</button>
      </div>
    </section>

    {selected && <section className="grid xl:grid-cols-2 gap-4">
      <div className={box}>
        <h2 className="font-semibold">1. Full retention list CSV</h2>
        <p className="text-xs text-slate-500 mt-1">Required columns: player/name and team/franchise. Optional: retention price, category and order. Teams are created from this file; no manual purse or squad entry is needed.</p>
        <input className={field} type="file" accept=".csv,text/csv" aria-label="Full retention list CSV" onChange={e => { setRetentionFile(e.target.files?.[0] || null); setRetentionPreview(null); }} />
        <div className="flex gap-2 mt-3"><button disabled={busy || !retentionFile} onClick={() => run(previewRetentions)} className="rounded border border-slate-700 px-3 py-2 text-xs disabled:opacity-40">Preview retention CSV</button><button disabled={busy || !retentionFile || !retentionPreview?.accepted_rows} onClick={() => run(importRetentions)} className="rounded bg-indigo-600 px-3 py-2 text-xs disabled:opacity-40">Import retention list</button></div>
        {renderReport(retentionPreview)}
      </div>
      <div className={box}>
        <h2 className="font-semibold">2. Player pool CSV</h2>
        <p className="text-xs text-slate-500 mt-1">Required columns: player/name and base price. Names and aliases are matched to CPI identities through Cricsheet names.csv. Unclear matches are flagged instead of merged.</p>
        <input className={field} type="file" accept=".csv,text/csv" aria-label="Auction player pool CSV" onChange={e => { setPoolFile(e.target.files?.[0] || null); setPoolPreview(null); }} />
        <div className="flex gap-2 mt-3"><button disabled={busy || !poolFile} onClick={() => run(previewPool)} className="rounded border border-slate-700 px-3 py-2 text-xs disabled:opacity-40">Preview player-pool CSV</button><button disabled={busy || !poolFile || !poolPreview?.accepted_rows} onClick={() => run(importPool)} className="rounded bg-indigo-600 px-3 py-2 text-xs disabled:opacity-40">Import player pool</button></div>
        {renderReport(poolPreview, 'player_name')}
      </div>
    </section>}

    {selected && <section className={box}>
      <h2 className="font-semibold">Rules & Squad Setup</h2>
      <p className="text-xs text-slate-500 mt-1">Scenario {detail?.season} · editable limits are stored in versioned auction rules.</p>
      <div className="grid sm:grid-cols-3 gap-3 mt-3">{[['maximum_squad_size','Maximum squad size'],['overseas_squad_limit','Overseas squad limit'],['overseas_xi_limit','Overseas Playing XI limit']].map(([key,label]) => <label key={key} className="text-xs text-slate-400">{label}<input className={field} type="number" min="0" value={rulesDraft[key] ?? ''} onChange={e => setRulesDraft(v => ({...v,[key]:Number(e.target.value)}))} /></label>)}</div>
      <div className="flex flex-wrap gap-2 items-center mt-3"><input className="text-xs text-slate-400" type="file" accept=".pdf,.docx,.csv,.txt" onChange={e => setRulesFile(e.target.files?.[0] || null)} /><button disabled={busy || !rulesFile} onClick={() => run(uploadRules)} className="rounded border border-slate-700 px-3 py-2 text-xs">Extract rules</button><button disabled={busy} onClick={() => run(saveRules)} className="rounded bg-indigo-600 px-3 py-2 text-xs">Confirm rules</button><span className="text-xs text-slate-500">Default IPL limits: 25 squad · 8 overseas squad · 4 overseas XI</span></div>
    </section>}

    {selected && detail?.teams?.length > 0 && <section className={box}>
      <div className="flex flex-wrap items-end gap-3"><div className="mr-auto"><h2 className="font-semibold">AI Predicted Playing XI</h2><p className="text-xs text-slate-500 mt-1">Generated only from the franchise's current retained and purchased squad.</p></div>
        <label className="text-xs text-slate-400">Franchise<select className={`${field} min-w-52`} value={xiTeam} onChange={e => setXiTeam(e.target.value)}>{detail.teams.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
        <label className="text-xs text-slate-400">Scenario style<select className={field} value={xiStyle} onChange={e => setXiStyle(e.target.value)}>{['balanced','batting-heavy','bowling-heavy','spin-friendly','pace-friendly'].map(s => <option key={s}>{s}</option>)}</select></label>
        <button disabled={busy} onClick={() => run(runXI)} className="rounded bg-indigo-600 px-3 py-2 text-xs font-semibold">Generate XI</button>
      </div>
      {xiResult && <div className="mt-4 grid lg:grid-cols-[2fr_1fr] gap-4"><div className="rounded-lg border border-slate-800 overflow-hidden"><div className="px-3 py-2 border-b border-slate-800 text-xs text-slate-400">{xiResult.validation_status === 'INCOMPLETE' ? 'Generated · validation incomplete' : 'Validated'} · {xiResult.confidence} confidence · Rules v{xiResult.rules_version} · Known overseas {xiResult.overseas_selected}/{xiResult.overseas_limit}</div>{xiResult.validation_warnings?.map(w => <p key={w} className="px-3 py-2 text-xs text-amber-300 bg-amber-950/30">{w}</p>)}{xiResult.players.map(p => <div key={p.player_id} className="px-3 py-2 border-b border-slate-800/60 flex gap-3 text-sm"><span className="text-slate-500 w-5">{p.batting_order}.</span><div><p className="text-slate-200">{p.name} <span className="text-xs text-slate-500">{p.role || 'role unknown'}{p.overseas ? ' · overseas' : ''}{p.nationality_known === false ? ' · nationality unknown' : ''} · {p.confidence}</span></p><p className="text-xs text-slate-500">{p.reason || p.limitations}</p></div></div>)}</div><div className="space-y-3"><div className="rounded-lg border border-slate-800 p-3"><h3 className="text-xs font-semibold">Near misses</h3>{xiResult.near_misses.map(p => <p key={p.player_id} className="text-xs text-slate-400 mt-2">{p.name} · {p.reason}</p>)}</div><div className="rounded-lg border border-amber-900/70 p-3"><h3 className="text-xs font-semibold text-amber-200">Gaps & limitations</h3>{xiResult.weaknesses.map(x => <p key={x} className="text-xs text-amber-100/80 mt-2">{x}</p>)}<p className="text-xs text-slate-500 mt-2">{xiResult.limitations}</p></div></div></div>}
    </section>}

    {detail && <section className="grid sm:grid-cols-3 gap-3">
      {[['Franchises from retention file', detail.teams?.length || 0], ['Players in pool', detail.available_players || 0], ['Scenario status', detail.status]].map(([label, value]) => <div className={box} key={label}><p className="text-xs text-slate-500">{label}</p><p className="text-xl font-semibold mt-1">{value}</p></div>)}
    </section>}

    {selected && <section className={box}>
      <div className="flex flex-wrap justify-between gap-3 items-center"><div><h2 className="font-semibold">Run Scenario</h2><p className="text-xs text-slate-500 mt-1">Compare team requirements, purse and squad constraints to estimate credible bidders and likely auction prices.</p></div><button disabled={busy} onClick={() => run(executeScenario)} className="rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 px-4 py-2 text-sm font-semibold">{busy ? 'Analyzing…' : 'Run Scenario'}</button></div>
      {scenarioResult && !scenarioResult.ready && <div role="status" className="mt-4 rounded-lg border border-amber-900 bg-amber-950/30 p-3 text-sm text-amber-200"><p>{scenarioResult.message}</p>{scenarioResult.message?.toLowerCase().includes('train') && <button disabled={busy} onClick={() => run(trainFromHistory)} className="mt-2 rounded bg-amber-900/70 px-3 py-1.5 text-xs">Import previous data & train model</button>}</div>}
      {scenarioResult?.ready && <>
        <div className="mt-4 rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-400">Model {scenarioResult.model.version} · chronological holdout MAE {scenarioResult.model.holdout_mae_lakh} lakh. {scenarioResult.assumptions.target_note} {scenarioResult.assumptions.price_note}</div>
        <div className="mt-4 grid grid-cols-1 xl:grid-cols-2 gap-4">
          <BarChart title="Highest expected auction closes" subtitle="Top ten pool players by current scenario estimate; INR crore." data={[...predictions].sort((a,b) => b.predicted_final_price_cr-a.predicted_final_price_cr).slice(0,10).map(p => ({label:p.player_name,value:p.predicted_final_price_cr}))} formatter={value => `₹${Number(value).toFixed(2)} cr`} color="#818cf8" />
          <BarChart title="Player demand intensity" subtitle="Highest demand scores in the available pool; score is the model's 0–100 scenario measure." data={[...predictions].sort((a,b) => b.demand_score-a.demand_score).slice(0,10).map(p => ({label:p.player_name,value:p.demand_score}))} formatter={value => `${Math.round(value)} / 100`} color="#fbbf24" />
          <BarChart title="Remaining franchise purse" subtitle="Current available balance after retention and recorded purchases; INR crore." data={scenarioResult.teams.map(t => ({label:t.franchise,value:t.remaining_purse_cr}))} formatter={value => `₹${Number(value).toFixed(1)} cr`} color="#34d399" />
          <LineChart title="Historical auction data by year" subtitle="Imported auction history records, including sold and unsold rows." data={(history?.years || []).map(row => ({label:row.year,value:row.count}))} formatter={value => Math.round(value).toLocaleString()} color="#22d3ee" />
          <ScatterChart title="Demand vs expected auction close" subtitle="Each point is one available player in this scenario; point size scales with feasible competing franchises." data={predictions.map(p=>({name:p.player_name,x:p.demand_score,y:p.predicted_final_price_cr,size:4+Math.min(5,Number(p.realistic_competing_franchises)||0),group:p.competition_level,color:p.competition_level==='Extreme'?'#fb7185':p.competition_level==='High'?'#fbbf24':'#818cf8',detail:`${p.role} · ${p.realistic_competing_franchises} realistic bidders · ${p.competition_level}`}))} xKey="x" yKey="y" xLabel="Demand score (0–100)" yLabel="Predicted close (₹ cr)" formatX={value=>Number(value).toFixed(0)} formatY={value=>`₹${Number(value).toFixed(1)}`} />
          <ScatterChart title="Individual value vs competitive close" subtitle="Shows the uplift from competition over individual valuation; no player-specific adjustment is added in the chart." data={predictions.map(p=>({name:p.player_name,x:p.individual_valuation_cr,y:p.predicted_final_price_cr,group:p.competition_level,color:p.competition_level==='Extreme'?'#fb7185':p.competition_level==='High'?'#fbbf24':'#34d399',detail:`${p.realistic_competing_franchises} realistic bidders · ${p.scarcity_score} scarcity`}))} xKey="x" yKey="y" xLabel="Individual valuation (₹ cr)" yLabel="Predicted close (₹ cr)" formatX={value=>`₹${Number(value).toFixed(1)}`} formatY={value=>`₹${Number(value).toFixed(1)}`} />
          <RangeChart title="Price ranges for highest-demand players" subtitle="Model-provided confidence intervals in crore; median/estimate marker is the expected final close." data={[...predictions].sort((a,b)=>b.demand_score-a.demand_score).slice(0,10).map(p=>({label:`${p.player_name} · ${p.realistic_competing_franchises} bidders`,low:p.confidence_interval_cr?.low,value:p.predicted_final_price_cr,high:p.confidence_interval_cr?.high}))} formatter={value=>`₹${Number(value).toFixed(2)} cr`} />
        </div>
        <section className="mt-4 rounded-lg border border-indigo-900/70 bg-slate-950/40 p-3">
          <div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="font-semibold">Competitive Player Price Predictions</h3><p className="text-xs text-slate-500 mt-1">{predictions.length} available players · expected close combines historical valuation with feasible bidders and pool scarcity.</p></div><input aria-label="Search price predictions" className="rounded bg-slate-800 border border-slate-700 px-3 py-2 text-xs" placeholder="Search player or role" value={predictionSearch} onChange={e => { setPredictionSearch(e.target.value); setPredictionPage(0); }} /></div>
          <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[1200px] text-left text-xs"><thead className="text-slate-500 border-b border-slate-800"><tr><th className="py-2 pr-3">Player</th><th className="py-2 pr-3">Expected final</th><th className="py-2 pr-3">Confidence interval</th><th className="py-2 pr-3">Individual value</th><th className="py-2 pr-3">Recent form</th><th className="py-2 pr-3">Competition</th><th className="py-2 pr-3">Demand / scarcity</th><th className="py-2">Likely competing franchises</th></tr></thead><tbody>{visiblePredictions.map(p => <tr key={p.player_id} className="border-b border-slate-800/60 align-top"><td className="py-2 pr-3"><span className="font-medium text-slate-200">{p.player_name}</span><span className="block text-slate-500 mt-1">{p.role} · {p.quality_sample}</span></td><td className="py-2 pr-3 text-indigo-200 font-semibold">₹{p.predicted_final_price_cr} cr<span className="block text-slate-500 font-normal">Base ₹{p.base_price_cr} cr</span></td><td className="py-2 pr-3 text-slate-300">₹{p.confidence_interval_cr.low}–{p.confidence_interval_cr.high} cr<span className="block text-slate-500">{p.confidence} confidence</span></td><td className="py-2 pr-3 text-slate-300">₹{p.individual_valuation_cr} cr</td><td className="py-2 pr-3 text-slate-300"><span className="text-indigo-200">{p.recent_form?.sample_matches || 0} matches</span><span className="block max-w-64 text-slate-500 mt-1">{p.recent_form?.assessment || 'Recent form unavailable'}</span></td><td className="py-2 pr-3"><span className="text-amber-200">{p.competition_level}</span><span className="block text-slate-500 mt-1">{p.realistic_competing_franchises} bidders</span></td><td className="py-2 pr-3 text-slate-300">{p.demand_score} / {p.scarcity_score}<span className="block text-slate-500 mt-1">{p.comparable_alternatives} similar alternatives</span></td><td className="py-2 text-slate-400">{p.most_likely_competitors.length ? p.most_likely_competitors.map(t => `${t.franchise} (₹${t.willingness_to_pay_cr} cr)`).join(' · ') : 'No franchise currently meets the need and capacity checks'}</td></tr>)}</tbody></table>{!visiblePredictions.length && <p className="py-5 text-center text-sm text-slate-500">No players match this search.</p>}</div>
          <div className="mt-3 flex items-center justify-between text-xs text-slate-500"><span>Showing {matchingPredictions.length ? predictionPage * predictionPageSize + 1 : 0}–{Math.min((predictionPage + 1) * predictionPageSize, matchingPredictions.length)} of {matchingPredictions.length}</span><div className="flex gap-2"><button disabled={predictionPage === 0} onClick={() => setPredictionPage(p => Math.max(0, p - 1))} className="rounded border border-slate-700 px-3 py-1.5 disabled:opacity-40">Previous</button><button disabled={predictionPage + 1 >= predictionPageCount} onClick={() => setPredictionPage(p => Math.min(predictionPageCount - 1, p + 1))} className="rounded border border-slate-700 px-3 py-1.5 disabled:opacity-40">Next</button></div></div>
        </section>
        <div className="mt-4 space-y-4">{scenarioResult.teams.map(team => <article key={team.team_id} className="rounded-lg border border-slate-800 p-4">
          <div className="flex flex-wrap justify-between gap-2"><div><h3 className="font-semibold">{team.franchise}</h3><p className="text-xs text-slate-500 mt-1">{team.retained_count} retained · ₹{team.remaining_purse_cr} cr purse · {team.squad_slots_remaining} squad slots · {team.overseas_slots_remaining} overseas slots · roles: {Object.entries(team.retained_role_counts).map(([r,n]) => `${r} ${n}`).join(' · ') || 'not classified'}</p></div><div className="flex flex-wrap gap-1">{team.needs.map(need => <span key={need.role} className="rounded bg-amber-950/50 border border-amber-900 px-2 py-1 text-[11px] text-amber-200">Needs {need.players_needed} {need.role}{need.players_needed === 1 ? '' : 's'}</span>)}{!team.needs.length && <span className="text-xs text-emerald-300">No role gaps against current targets</span>}</div></div>
          {team.recommendations.length > 0 ? <div className="mt-3 overflow-x-auto"><table className="w-full text-left text-xs"><thead className="text-slate-500 border-b border-slate-800"><tr><th className="py-2 pr-3">Player</th><th className="py-2 pr-3">Role needed</th><th className="py-2 pr-3">Base</th><th className="py-2 pr-3">Estimated team bid</th><th className="py-2 pr-3">Need priority</th><th className="py-2">Confidence</th></tr></thead><tbody>{team.recommendations.map(player => <tr key={player.player_id} className="border-b border-slate-800/60"><td className="py-2 pr-3 font-medium text-slate-200">{player.player_name}</td><td className="py-2 pr-3 text-slate-400">{player.role}</td><td className="py-2 pr-3 text-slate-400">₹{player.base_price_cr} cr</td><td className="py-2 pr-3 text-indigo-200">₹{player.estimated_bid_cr} cr <span className="text-slate-500">({player.estimated_bid_lakh} lakh)</span></td><td className="py-2 pr-3 text-slate-400">{player.need_priority}%</td><td className="py-2 text-slate-400">{player.confidence} · {player.historical_team_sales} past sales</td></tr>)}</tbody></table></div> : <p className="mt-3 text-xs text-slate-500">No recommendations available. Check that the retention and player-pool CSVs include roles and unfilled target roles.</p>}
        </article>)}</div>
        <p className="mt-3 text-[11px] text-slate-500">Bid amounts are learned historical estimates by franchise, role, base price and prior sale history. They are not confirmed team budgets or guaranteed future bids.</p>
      </>}
    </section>}

    <section className={box}>
      <div className="flex flex-wrap justify-between gap-3 items-center"><div><h2 className="font-semibold">Previous auction data model</h2><p className="text-xs text-slate-500 mt-1">Train on the bundled historical auction sources. This does not require another CSV upload.</p></div><button disabled={busy} onClick={() => run(trainFromHistory)} className="rounded bg-indigo-600 px-3 py-2 text-xs font-semibold disabled:opacity-50">Import previous data & train</button></div>
      <div className="flex flex-wrap gap-5 mt-3 text-xs text-slate-400"><span>{history?.records ?? '—'} historical records</span><span>{history?.sold_auction_rows ?? 0} sold-price rows</span><span>{history?.latest_price_model ? `Latest model ${history.latest_price_model.version} · holdout MAE ${history.latest_price_model.evaluation.mae_lakh} lakh` : 'Model not trained yet'}</span></div>
      {history?.latest_price_model?.evaluation && <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 mt-4">
        <BarChart title="Chronological holdout error" subtitle="Reported evaluation metrics in INR lakh. Lower MAE/RMSE indicates smaller price error." data={[
          {label:'MAE',value:history.latest_price_model.evaluation.mae_lakh},
          {label:'RMSE',value:history.latest_price_model.evaluation.rmse_lakh},
          ...(history.latest_price_model.evaluation.baseline_median_mae_lakh != null ? [{label:'Median baseline MAE',value:history.latest_price_model.evaluation.baseline_median_mae_lakh,color:'#64748b'}] : []),
        ]} formatter={value => `${Number(value).toFixed(1)} lakh`} color="#818cf8" />
        <BarChart title="Training and validation sample size" subtitle={`Validation starts in ${history.latest_price_model.evaluation.validation_start_year ?? 'unknown year'}; chronological holdout.`} data={[
          {label:'Training rows',value:history.latest_price_model.training_rows},
          {label:'Validation rows',value:history.latest_price_model.validation_rows},
        ]} formatter={value => Math.round(value).toLocaleString()} color="#34d399" />
        {history.latest_price_model.evaluation.r2 != null && <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-4"><p className="text-sm font-semibold text-slate-200">Holdout R²</p><p className="mt-2 text-3xl font-bold text-indigo-300">{Number(history.latest_price_model.evaluation.r2).toFixed(3)}</p><p className="mt-1 text-xs text-slate-500">Calculated on {history.latest_price_model.validation_rows} held-out auction transactions.</p></div>}
      </div>}
    </section>
  </div>;
}
