import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getScoutingOptions, scoutingSearch } from '../../services/api';
import { LoadingSpinner, ErrorState, EmptyState, PageHeader } from '../../components/ui';
import { BarChart, DonutChart, PlayerScatterPlot, MultiLineChart } from '../../components/charts';

const CATEGORIES = [
  ['BATTERS', 'Batters'], ['BOWLERS', 'Bowlers'], ['ALL_ROUNDERS', 'All-Rounders'],
];
const INITIAL = {
  format: 'T20', gender: 'male', category: 'BATTERS', preset: 'Reliable Performer', role: '', nationality: '', competition: '', season: '', team_id: '',
  start_year: '', end_year: '', min_age: '', max_age: '', batting_style: '', bowling_style: '', pace_spin: '', bowling_arm: '', bowling_speed_category: '',
  minimum_matches: 5, minimum_innings: 5, minimum_balls_faced: 60, minimum_legal_balls: 60,
};
const METRICS = {
  BATTERS: ['batting_average', 'strike_rate', 'boundary_percentage', 'dot_ball_percentage'],
  BOWLERS: ['wickets_per_match', 'bowling_average', 'economy', 'bowling_strike_rate', 'dot_ball_percentage'],
  ALL_ROUNDERS: ['batting_average', 'strike_rate', 'bowling_average', 'economy', 'wickets_per_match'],
};
const CHART_METRICS = {
  BATTERS: ['runs','batting_average','strike_rate','boundary_percentage','fifties','hundreds','recent_form'],
  BOWLERS: ['wickets','bowling_average','economy','bowling_strike_rate','dot_ball_percentage','bowling_recent_form'],
  ALL_ROUNDERS: ['runs','batting_average','strike_rate','boundary_percentage','fifties','hundreds','wickets','bowling_average','economy','bowling_strike_rate','recent_form','bowling_recent_form'],
};
const label = value => value.replaceAll('_', ' ').replace(/\b\w/g, x => x.toUpperCase());
const fmt = value => value == null ? '—' : Number(value).toFixed(1);
const ROLE_COLORS = {'Specialist Batter':'#818cf8','Wicketkeeper-Batter':'#22d3ee','Specialist Bowler':'#fb7185','Batting All-Rounder':'#fbbf24','Bowling All-Rounder':'#c084fc'};

export default function Scouting() {
  const navigate = useNavigate();
  const [options, setOptions] = useState(null);
  const [form, setForm] = useState(INITIAL);
  const [weights, setWeights] = useState(null);
  const [customWeights, setCustomWeights] = useState(false);
  const [metricName, setMetricName] = useState('');
  const [metricMin, setMetricMin] = useState('');
  const [metricMax, setMetricMax] = useState('');
  const [result, setResult] = useState(null);
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState('score');
  const [sortDesc, setSortDesc] = useState(true);
  const [chartMetric, setChartMetric] = useState('batting_average');
  const [shortlist, setShortlist] = useState({});
  const [loading, setLoading] = useState(false);
  const [optionsLoading, setOptionsLoading] = useState(true);
  const [error, setError] = useState('');
  const [optionsError, setOptionsError] = useState('');
  const comparePlayers = useMemo(() => Object.values(shortlist), [shortlist]);

  useEffect(() => {
    getScoutingOptions().then(data => {
      setOptions(data);
      setWeights(data.presets?.BATTERS?.['Reliable Performer'] || null);
    }).catch(e => setOptionsError(e.message || 'Could not load scouting filters.')).finally(() => setOptionsLoading(false));
  }, []);

  // The API returns presets as { presetName: metricWeights }, not an array.
  // Passing that object to .map crashes React as soon as options load, leaving
  // the entire Scouting route blank.
  const presetNames = Object.keys(options?.presets?.[form.category] || {});
  const availableMetrics = METRICS[form.category];
  const availableChartMetrics = CHART_METRICS[form.category];
  const highlightedIds = Object.keys(shortlist);
  const scatterRows = result?.visualization?.points || [];
  const selectedChartPlayers = comparePlayers;
  const scatterData = [...scatterRows, ...selectedChartPlayers
    .filter(player => !scatterRows.some(point => point.player_id === player.player_id))
    .filter(player => player.stats?.batting_average != null && player.stats?.strike_rate != null)
    .map(player => ({ ...player, batting_average: player.stats.batting_average, strike_rate: player.stats.strike_rate }))];

  function update(field, value) {
    setForm(old => ({ ...old, [field]: value }));
    setShortlist({});
    setPage(1);
  }

  function changeCategory(category) {
    const preset = options?.presets?.[category] ? Object.keys(options.presets[category])[0] : '';
    setForm(old => ({ ...old, category, preset, role: '' }));
    setWeights(options?.presets?.[category]?.[preset] || null);
    setChartMetric(CHART_METRICS[category]?.[0] || 'overall_score');
    setCustomWeights(false);
    setShortlist({});
    setPage(1);
  }

  function changePreset(preset) {
    setForm(old => ({ ...old, preset }));
    setWeights(options?.presets?.[form.category]?.[preset] || {});
    setCustomWeights(preset === 'Custom');
    setShortlist({});
    setPage(1);
  }

  function changeWeight(key, value) {
    setWeights(old => ({ ...old, [key]: Number(value) }));
    setCustomWeights(true);
    setForm(old => ({ ...old, preset: 'Custom' }));
    setShortlist({});
  }

  async function search(e, requestedPage = 1, requestedSort = sortBy, requestedSortDesc = sortDesc) {
    e?.preventDefault();
    if (form.start_year && form.end_year && Number(form.start_year) > Number(form.end_year)) {
      setError('From Year must be less than or equal to To Year.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const metric_min = metricName && metricMin !== '' ? { [metricName]: Number(metricMin) } : {};
      const metric_max = metricName && metricMax !== '' ? { [metricName]: Number(metricMax) } : {};
      const payload = {
        ...form, page: requestedPage, page_size: 20, sort_by: requestedSort, sort_desc: requestedSortDesc,
        start_year: form.start_year ? Number(form.start_year) : null,
        end_year: form.end_year ? Number(form.end_year) : null,
        min_age: form.min_age ? Number(form.min_age) : null,
        max_age: form.max_age ? Number(form.max_age) : null,
        minimum_matches: Number(form.minimum_matches), minimum_innings: Number(form.minimum_innings),
        minimum_balls_faced: Number(form.minimum_balls_faced), minimum_legal_balls: Number(form.minimum_legal_balls),
        season: undefined,
        seasons: form.season ? [form.season] : null,
        weights: customWeights ? weights : null,
        metric_min, metric_max,
      };
      Object.keys(payload).forEach(key => (payload[key] === '' || payload[key] === undefined) && delete payload[key]);
      const data = await scoutingSearch(payload);
      setResult(data);
      setPage(requestedPage);
    } catch (e2) {
      setError(e2.message || 'Scouting search failed.');
    } finally {
      setLoading(false);
    }
  }

  function sort(metric) {
    const nextDesc = sortBy === metric ? !sortDesc : true;
    setSortBy(metric);
    setSortDesc(nextDesc);
    setPage(1);
    if (result) search(null, 1, metric, nextDesc);
  }

  const columns = form.category === 'BATTERS'
    ? [['runs', 'Runs'], ['batting_average', 'Average'], ['strike_rate', 'Strike Rate'], ['boundary_percentage', 'Boundary %']]
    : form.category === 'BOWLERS'
      ? [['wickets', 'Wickets'], ['bowling_average', 'Average'], ['economy', 'Economy'], ['bowling_strike_rate', 'Strike Rate']]
      : [['runs', 'Runs'], ['batting_average', 'Bat Avg'], ['strike_rate', 'Bat SR'], ['wickets', 'Wickets'], ['economy', 'Bowl Econ']];

  function exportCsv() {
    const rows = [['Rank', 'Player', 'Role', 'Matches', 'Innings', 'Runs', 'Wickets', 'Overall Score', 'Batting Score', 'Bowling Score', 'Confidence', ...Object.keys(result.candidates[0]?.stats || {})]];
    for (const candidate of result.candidates) rows.push([
      candidate.rank, candidate.player_name, candidate.role, candidate.matches, candidate.innings,
      candidate.runs ?? '', candidate.wickets ?? '', candidate.overall_score, candidate.batting_score ?? '', candidate.bowling_score ?? '', candidate.confidence,
      ...Object.keys(result.candidates[0]?.stats || {}).map(key => candidate.stats[key] ?? ''),
    ]);
    const csv = rows.map(row => row.map(value => `"${String(value).replaceAll('"', '""')}"`).join(',')).join('\n');
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    link.download = `cpi-scouting-${form.category.toLowerCase()}-${form.format}.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  const selectClass = 'w-full bg-slate-800 border border-slate-700 rounded px-2.5 py-2 text-xs text-slate-200';
  const inputClass = 'w-full bg-slate-800 border border-slate-700 rounded px-2.5 py-2 text-xs text-slate-200';

  return <div className="space-y-5">
    <PageHeader title="Scouting" subtitle="Format-specific, explainable player evaluation. Scores compare players within the selected role and competition filters." />

    <div className="grid grid-cols-1 xl:grid-cols-[340px_minmax(0,1fr)] gap-5">
      <form onSubmit={search} className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3 h-fit">
        <div className="grid grid-cols-2 gap-3">
          <label className="text-[11px] text-slate-400">Category<select className={`${selectClass} mt-1`} value={form.category} onChange={e => changeCategory(e.target.value)}>{CATEGORIES.map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>
          <label className="text-[11px] text-slate-400">Format<select className={`${selectClass} mt-1`} value={form.format} onChange={e => update('format', e.target.value)}>{(options?.formats || ['Test','ODI','T20I','T20','MDM','ODM']).map(x => <option key={x} value={x}>{x === 'T20' ? 'T20 Franchise/Domestic' : x === 'T20I' ? 'T20 International' : x === 'MDM' ? 'Multi-day Domestic' : x === 'ODM' ? 'One-day Domestic' : x}</option>)}</select></label>
        </div>
        <label className="block text-[11px] text-slate-400">Gender<select className={`${selectClass} mt-1`} value={form.gender} onChange={e => update('gender', e.target.value)}><option value="male">Men’s cricket</option><option value="female">Women’s cricket</option><option value="all">All genders</option></select></label>
        <label className="block text-[11px] text-slate-400">Scouting objective / preset<select className={`${selectClass} mt-1`} value={form.preset} onChange={e => changePreset(e.target.value)}>{presetNames.map(x => <option key={x} value={x}>{x}</option>)}{customWeights && <option value="Custom">Custom weights</option>}</select></label>
        <label className="block text-[11px] text-slate-400">Role filter<select className={`${selectClass} mt-1`} value={form.role} onChange={e => update('role', e.target.value)}><option value="">Any role in category</option>{(form.category === 'BATTERS' ? ['Specialist Batter','Wicketkeeper-Batter'] : form.category === 'BOWLERS' ? ['Specialist Bowler'] : ['Batting All-Rounder','Bowling All-Rounder']).map(x => <option key={x}>{x}</option>)}</select></label>
        <label className="block text-[11px] text-slate-400">Nationality<select className={`${selectClass} mt-1`} value={form.nationality} onChange={e => update('nationality', e.target.value)}><option value="">Any nationality</option><option value="Unknown">Unknown / unresolved</option>{(options?.nationalities || []).map(x => <option key={x}>{x}</option>)}</select></label>
        <div className="grid grid-cols-2 gap-3">
          <label className="text-[11px] text-slate-400">From year<input className={`${inputClass} mt-1`} type="number" value={form.start_year} onChange={e => update('start_year', e.target.value)} placeholder="Any" /></label>
          <label className="text-[11px] text-slate-400">To year<input className={`${inputClass} mt-1`} type="number" value={form.end_year} onChange={e => update('end_year', e.target.value)} placeholder="Any" /></label>
          <label className="text-[11px] text-slate-400">Min age<input className={`${inputClass} mt-1`} type="number" value={form.min_age} onChange={e => update('min_age', e.target.value)} placeholder="Known ages" /></label>
          <label className="text-[11px] text-slate-400">Max age<input className={`${inputClass} mt-1`} type="number" value={form.max_age} onChange={e => update('max_age', e.target.value)} placeholder="Known ages" /></label>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className="text-[11px] text-slate-400">Min matches<input className={`${inputClass} mt-1`} type="number" min="1" value={form.minimum_matches} onChange={e => update('minimum_matches', e.target.value)} /></label>
          <label className="text-[11px] text-slate-400">Min innings<input className={`${inputClass} mt-1`} type="number" min="1" value={form.minimum_innings} onChange={e => update('minimum_innings', e.target.value)} /></label>
          <label className="text-[11px] text-slate-400">Min batting balls<input className={`${inputClass} mt-1`} type="number" min="1" value={form.minimum_balls_faced} onChange={e => update('minimum_balls_faced', e.target.value)} /></label>
          <label className="text-[11px] text-slate-400">Min legal balls bowled<input className={`${inputClass} mt-1`} type="number" min="1" value={form.minimum_legal_balls} onChange={e => update('minimum_legal_balls', e.target.value)} /></label>
        </div>
        {form.category !== 'BOWLERS' && <label className="block text-[11px] text-slate-400">Batting style<select className={`${selectClass} mt-1`} value={form.batting_style} onChange={e => update('batting_style', e.target.value)}><option value="">Any</option>{(options?.batting_styles || []).map(x => <option key={x}>{x}</option>)}</select></label>}
        {form.category !== 'BATTERS' && <>
          <label className="block text-[11px] text-slate-400">Bowling style<select className={`${selectClass} mt-1`} value={form.bowling_style} onChange={e => update('bowling_style', e.target.value)}><option value="">Any</option>{(options?.bowling_styles || []).map(x => <option key={x}>{x}</option>)}</select></label>
          <div className="grid grid-cols-3 gap-2"><label className="block text-[11px] text-slate-400">Category<select className={`${selectClass} mt-1`} value={form.pace_spin} onChange={e => update('pace_spin', e.target.value)}><option value="">Any</option>{(options?.bowling_types || ['Pace','Spin']).map(x => <option key={x} value={x.toLowerCase()}>{x}</option>)}</select></label>
          <label className="block text-[11px] text-slate-400">Bowling arm<select className={`${selectClass} mt-1`} value={form.bowling_arm} onChange={e => update('bowling_arm', e.target.value)}><option value="">Any</option>{(options?.bowling_arms || []).map(x => <option key={x}>{x}</option>)}</select></label>
          <label className="block text-[11px] text-slate-400">Speed<select className={`${selectClass} mt-1`} value={form.bowling_speed_category} onChange={e => update('bowling_speed_category', e.target.value)}><option value="">Any</option>{(options?.bowling_speed_categories || []).map(x => <option key={x}>{x}</option>)}</select></label></div>
        </>}
        <div className="grid grid-cols-2 gap-3">
          <label className="text-[11px] text-slate-400">Team<select className={`${selectClass} mt-1`} value={form.team_id} onChange={e => update('team_id', e.target.value)}><option value="">Any</option>{(options?.teams || []).map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
          <label className="text-[11px] text-slate-400">Competition<select className={`${selectClass} mt-1`} value={form.competition} onChange={e => update('competition', e.target.value)}><option value="">Any</option>{(options?.competitions || []).map(x => <option key={x}>{x}</option>)}</select></label>
        </div>
        <label className="block text-[11px] text-slate-400">Season<select className={`${selectClass} mt-1`} value={form.season} onChange={e => update('season', e.target.value)}><option value="">Any</option>{(options?.seasons || []).map(x => <option key={x}>{x}</option>)}</select></label>
        <div className="grid grid-cols-[1fr_80px_80px] gap-2 items-end">
          <label className="text-[11px] text-slate-400">Metric range<select className={`${selectClass} mt-1`} value={metricName} onChange={e => setMetricName(e.target.value)}><option value="">None</option>{availableMetrics.map(x => <option key={x} value={x}>{label(x)}</option>)}</select></label>
          <label className="text-[10px] text-slate-500">Min<input className={`${inputClass} mt-1`} type="number" value={metricMin} onChange={e => setMetricMin(e.target.value)} /></label>
          <label className="text-[10px] text-slate-500">Max<input className={`${inputClass} mt-1`} type="number" value={metricMax} onChange={e => setMetricMax(e.target.value)} /></label>
        </div>
        {weights && <details className="border-t border-slate-800 pt-2">
          <summary className="text-xs font-semibold text-slate-300 cursor-pointer">Adjust preset weights</summary>
          <div className="pt-2 space-y-2">
            {Object.entries(weights).map(([key, value]) => <label key={key} className="block text-[10px] text-slate-400">{label(key)} · {Math.round(value * 100)}%
              <input type="range" min="0" max="1" step="0.01" value={value} onChange={e => changeWeight(key, e.target.value)} className="block w-full accent-indigo-500" />
            </label>)}
            {customWeights && <button type="button" onClick={() => changePreset(presetNames[0])} className="text-[10px] text-indigo-300">Reset to a preset</button>}
          </div>
        </details>}
        <button disabled={loading || optionsLoading} className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded py-2.5 text-sm font-semibold">{loading ? 'Scouting…' : 'Find & Rank Players'}</button>
        {optionsError && <p className="text-xs text-rose-400">{optionsError}</p>}
      </form>

      <section className="min-w-0">
        {loading && <LoadingSpinner message="Evaluating eligible players in the selected format…" />}
        {error && <ErrorState message={error} />}
        {result && !loading && <div className="space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <p className="text-sm text-slate-300"><b className="text-white">{result.total_eligible}</b> eligible · page {result.page} of {result.total_pages || 1} · {form.gender === 'all' ? 'All genders' : form.gender === 'female' ? 'Women' : 'Men'} · {form.format} {form.category.toLowerCase()}</p>
            <button onClick={exportCsv} disabled={!result.candidates.length} className="px-3 py-1.5 rounded border border-slate-700 bg-slate-800 text-xs text-slate-200 disabled:opacity-40">Export CSV</button>
          </div>
          <div className="bg-indigo-950/30 border border-indigo-900/60 rounded-lg px-3 py-2 text-[11px] text-indigo-200">{result.score_explanation}</div>
          {form.category !== 'BOWLERS' && <PlayerScatterPlot
            title="Batting profile · average vs strike rate"
            subtitle={`${result.visualization?.cohort_size || result.total_eligible} eligible players · ${form.gender === 'all' ? 'all genders' : form.gender} · ${form.format}${form.competition ? ` · ${form.competition}` : ''}${form.nationality ? ` · ${form.nationality}` : ''}. Dots are role-colored; select players in the table to highlight them.`}
            data={scatterData.map(row=>({...row,color:ROLE_COLORS[row.role] || '#64748b'}))}
            referenceX={result.visualization?.reference_average} referenceY={result.visualization?.reference_strike_rate}
            highlightedIds={highlightedIds} onPointClick={player=>navigate(`/players/${player.player_id}`)}
          />}
          {form.category !== 'BOWLERS' && result.visualization?.sampled && <p className="text-[11px] text-slate-500">Scatter displays a representative sample of {result.visualization.plot_limit.toLocaleString()} players for responsiveness; cohort benchmarks and distribution counts use the complete filtered set.</p>}
          {result.candidates.length > 0 && <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
            <BarChart title="Top role-fit scores" subtitle={`Current page · ${form.format} ${form.category.toLowerCase()} · normalized scouting score, not a forecast.`} data={result.candidates.slice(0,10).map(c=>({label:`${c.rank}. ${c.player_name}`,value:c.overall_score,color:ROLE_COLORS[c.role]}))} formatter={value=>`${Number(value).toFixed(1)} / 100`} color="#818cf8" />
            <div className="space-y-2"><label className="block text-xs text-slate-400">Compare candidates by<select className="ml-2 rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-slate-200" value={chartMetric} onChange={e=>setChartMetric(e.target.value)}>{availableChartMetrics.map(metric=><option key={metric} value={metric}>{label(metric)}</option>)}</select></label>
              <BarChart title={`${label(chartMetric)} comparison`} subtitle={`${selectedChartPlayers.length ? 'Selected shortlist' : 'Top-ranked candidates'} · actual ${form.format} values within the active category and competition filters. Missing observations are omitted.`} data={(selectedChartPlayers.length ? selectedChartPlayers : result.candidates.slice(0,10)).filter(c=>(c.stats?.[chartMetric] ?? c[chartMetric])!=null).map(c=>({label:c.player_name,value:c.stats?.[chartMetric] ?? c[chartMetric],color:ROLE_COLORS[c.role]}))} formatter={value=>Number(value).toFixed(1)} color="#34d399" />
            </div>
          </div>}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            <DonutChart title="Nationality mix" subtitle={`Filtered cohort · n=${result.visualization?.cohort_size || result.total_eligible}; unresolved players remain Unknown.`} data={result.visualization?.nationality || []} />
            <DonutChart title="Playing role mix" subtitle="CPI role classification among eligible players." data={result.visualization?.role || []} />
            <DonutChart title="Batting style mix" subtitle="Missing style metadata is grouped as Unknown." data={result.visualization?.batting_style || []} />
            <DonutChart title="Bowling style mix" subtitle="Only sourced bowling-style attributes; missing values remain Unknown." data={result.visualization?.bowling_style || []} />
            <DonutChart title="Player category mix" subtitle={`Role-derived categories in this ${form.category.replaceAll('_',' ').toLowerCase()} cohort.`} data={result.visualization?.player_category || []} />
          </div>
          {form.category !== 'BOWLERS' && <MultiLineChart title="Recent batting form · selected players" subtitle="Runs in each player's last five batting appearances within the active filters; matches are aligned by appearance order, not calendar date." series={selectedChartPlayers.slice(0,5).map(player=>({name:player.player_name,values:player.recent_match_runs||[]}))} />}
          {comparePlayers.length > 0 && <div className="bg-slate-900 border border-slate-800 rounded-lg p-3 overflow-x-auto">
            <p className="text-xs font-semibold text-white mb-2">Shortlist comparison</p>
            <table className="text-[11px] min-w-full"><thead><tr><th className="text-left p-1 text-slate-500">Metric</th>{comparePlayers.map(p => <th key={p.player_id} className="p-1 text-indigo-300">{p.player_name}</th>)}</tr></thead><tbody>
              {[...new Set(comparePlayers.flatMap(p => Object.keys(p.stats)))].map(metric => <tr key={metric} className="border-t border-slate-800"><td className="p-1 text-slate-400">{label(metric)}</td>{comparePlayers.map(p => <td key={p.player_id} className="p-1 text-center text-white">{fmt(p.stats[metric])}</td>)}</tr>)}
            </tbody></table>
          </div>}
          {!result.candidates.length ? <EmptyState message="No eligible players in this format and filter set. Reduce the sample thresholds or widen the filters." /> : <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-900">
            <table className="min-w-full text-xs text-left text-slate-300">
              <thead className="bg-slate-800 text-[10px] uppercase text-slate-400"><tr>
                <th className="p-2">Compare</th><th className="p-2">Rank</th><th className="p-2">Player</th>
                <th className="p-2 cursor-pointer" onClick={() => sort('matches')}>Matches ↕</th>
                {columns.map(([key, title]) => <th key={key} className="p-2 text-right cursor-pointer" onClick={() => sort(key)}>{title} ↕</th>)}
                <th className="p-2 text-right cursor-pointer" onClick={() => sort('score')}>Score ↕</th><th className="p-2">Sample</th>
              </tr></thead>
              <tbody>{result.candidates.map(c => <tr key={c.player_id} className="border-t border-slate-800 hover:bg-slate-800/40 align-top">
                <td className="p-2"><input aria-label={`Shortlist ${c.player_name}`} type="checkbox" checked={Boolean(shortlist[c.player_id])} onChange={e => setShortlist(old => { const next = { ...old }; if (e.target.checked) next[c.player_id] = c; else delete next[c.player_id]; return next; })} /></td>
                <td className="p-2 text-indigo-300 font-mono">{c.rank}</td>
                <td className="p-2 min-w-36"><Link className="text-white hover:text-indigo-300 font-semibold" to={`/players/${c.player_id}`}>{c.player_name}</Link><div className="text-[10px] text-slate-500 mt-0.5">{c.role}{c.stats.age != null ? ` · age ${c.stats.age}` : ''}</div>{c.bowling_type && <div className="mt-0.5 text-[10px] text-indigo-300">{c.bowling_style || 'Style not available'} · {c.bowling_type}{c.bowling_arm ? ` · ${c.bowling_arm}` : ''}{c.bowling_speed_category ? ` · ${c.bowling_speed_category}` : ''}</div>}<div className="mt-1 space-y-0.5">{c.strengths.slice(0,2).map((x,i)=><div key={i} className="text-[10px] text-emerald-300">+ {x}</div>)}{c.limitations.slice(0,1).map((x,i)=><div key={i} className="text-[10px] text-amber-300">! {x}</div>)}</div><details className="mt-1"><summary className="text-[10px] text-indigo-300 cursor-pointer">Metric scores & explanation</summary><div className="mt-1 space-y-0.5">{Object.entries(c.metric_scores).map(([metric, value]) => <div key={metric} className="text-[10px] text-slate-400">{label(metric)}: {fmt(value)}/100</div>)}<p className="text-[10px] text-slate-500 mt-1">{c.explanation}</p></div></details></td>
                <td className="p-2">{c.matches}<div className="text-[10px] text-slate-500">{form.category === 'BOWLERS' ? c.bowling_innings : c.innings} inns</div></td>
                {columns.map(([key]) => <td key={key} className="p-2 text-right">{fmt(c.stats[key] ?? c[key])}</td>)}
                <td className="p-2 text-right"><b className="text-indigo-300 text-sm">{c.overall_score.toFixed(1)}</b><div className="text-[10px] text-slate-500">/100</div>{form.category === 'ALL_ROUNDERS' && <div className="text-[10px] whitespace-nowrap">Bat {fmt(c.batting_score)} · Bowl {fmt(c.bowling_score)}</div>}</td>
                <td className="p-2"><span className={`px-1.5 py-0.5 rounded ${c.confidence.startsWith('High') ? 'bg-emerald-950 text-emerald-300' : c.confidence.startsWith('Medium') ? 'bg-amber-950 text-amber-300' : 'bg-slate-800 text-slate-400'}`}>{c.confidence}</span><div className="text-[10px] mt-1 text-slate-500">{form.category === 'BOWLERS' ? c.legal_balls : c.balls_faced} balls</div></td>
              </tr>)}</tbody>
            </table>
          </div>}
          <div className="flex justify-end gap-2"><button disabled={page <= 1 || loading} onClick={() => search(null, page - 1)} className="px-3 py-1.5 border border-slate-700 rounded text-xs disabled:opacity-40">Previous</button><button disabled={page >= result.total_pages || loading} onClick={() => search(null, page + 1)} className="px-3 py-1.5 border border-slate-700 rounded text-xs disabled:opacity-40">Next</button></div>
        </div>}
        {!result && !loading && !error && <EmptyState message="Choose a format and scouting objective, then run a search to see the ranked cohort." />}
      </section>
    </div>
  </div>;
}
