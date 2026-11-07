/** Role-aware, format-aware comparison backed by the player analytics API. */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { getPlayers, getPlayer, getPlayerAnalytics, getPlayerFilterMetadata, getScoutingOptions } from '../../services/api';
import { LoadingSpinner, EmptyState, PageHeader } from '../../components/ui';
import { BarChart, RadarChart } from '../../components/charts';

const FORMATS = ['Test', 'ODI', 'T20', 'T20I', 'MDM', 'ODM'];
const COLORS = ['#818cf8', '#34d399', '#fbbf24'];
const BATTER_ROLES = ['Specialist Batter', 'Wicketkeeper-Batter', 'Batting All-Rounder', 'Bowling All-Rounder'];
const BOWLER_ROLES = ['Specialist Bowler', 'Batting All-Rounder', 'Bowling All-Rounder'];
const FAMOUS_COMPARISONS = [
  { name: 'Virat Kohli vs Rohit Sharma', p1: 'Virat Kohli', p2: 'Rohit Sharma' },
  { name: 'MS Dhoni vs AB de Villiers', p1: 'MS Dhoni', p2: 'AB de Villiers' },
  { name: 'Andre Russell vs Kieron Pollard', p1: 'Andre Russell', p2: 'Kieron Pollard' },
  { name: 'KL Rahul vs Rishabh Pant', p1: 'KL Rahul', p2: 'Rishabh Pant' },
];

const isBatter = role => BATTER_ROLES.includes(role);
const isBowler = role => BOWLER_ROLES.includes(role);
const fmt = value => value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
const selectClass = 'w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 focus:border-indigo-500 focus:outline-none';

function PlayerPicker({ onSelect, currentIds }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (query.trim().length < 2) { setResults([]); return; }
    let active = true;
    const timer = setTimeout(() => {
      setLoading(true);
      getPlayers({ name: query.trim(), page_size: 20 }).then(data => { if (active) setResults(data.players || []); })
        .catch(() => { if (active) setResults([]); }).finally(() => { if (active) setLoading(false); });
    }, 250);
    return () => { active = false; clearTimeout(timer); };
  }, [query]);
  return <div className="relative w-full max-w-xl">
    <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-slate-300">Add a player (up to 3)</label>
    <input className={selectClass} placeholder="Search player name or alias…" value={query} onFocus={() => setOpen(true)} onChange={e => { setQuery(e.target.value); setOpen(true); }} />
    {loading && <span className="absolute right-3 top-9 text-xs text-slate-500">Searching…</span>}
    {open && query.trim().length >= 2 && <div className="absolute z-30 mt-1 max-h-64 w-full overflow-y-auto rounded-lg border border-slate-700 bg-slate-900 shadow-xl">
      {results.filter(p => !currentIds.includes(p.id)).map(player => <button key={player.id} onClick={() => { onSelect(player); setQuery(''); setOpen(false); }} className="flex w-full justify-between border-b border-slate-800 px-3 py-2 text-left text-sm hover:bg-indigo-900/40"><span>{player.name}</span><span className="text-xs text-slate-500">{player.primary_role || 'Role unclassified'}</span></button>)}
      {!results.filter(p => !currentIds.includes(p.id)).length && <p className="p-3 text-xs text-slate-500">No matching players found.</p>}
      <button className="w-full p-2 text-xs text-slate-400 hover:text-white" onClick={() => setOpen(false)}>Close</button>
    </div>}
  </div>;
}

function MetricTiles({ title, rows, color }) {
  return <div className="space-y-2"><h4 className="text-xs font-semibold uppercase tracking-wider text-slate-400">{title}</h4><div className="grid grid-cols-2 gap-2">{rows.map(([label, value]) => <div key={label} className="rounded-lg border border-slate-800 bg-slate-800/50 p-2.5"><span className="block text-[10px] text-slate-500">{label}</span><strong className={`text-sm ${color}`}>{fmt(value)}</strong></div>)}</div></div>;
}

function PlayerCard({ item, discipline, onRemove, format }) {
  const a = item.analytics;
  const batting = a?.batting || {};
  const bowling = a?.bowling || {};
  const batPhases = a?.phases || [];
  const bowlPhases = a?.bowling_phases || [];
  const role = a?.primary_role || item.player.primary_role || 'Role unclassified';
  const showBat = isBatter(role) && discipline !== 'bowling';
  const showBowl = isBowler(role) && discipline !== 'batting';
  const phases = showBowl && !showBat ? bowlPhases : batPhases;
  return <article className="min-w-[280px] flex-1 rounded-xl border border-slate-800 bg-slate-900 p-4">
    <div className="mb-4 flex items-start justify-between border-b border-slate-800 pb-3"><div><Link to={`/players/${item.player.id}`} className="font-semibold text-white hover:text-indigo-300">{a?.player_name || item.player.name}</Link><p className="mt-1 text-xs text-slate-500">{role} · {format}</p><p className="text-[10px] text-slate-600">{a?.role_source || 'Role metadata'}{a?.role_confidence ? ` · ${a.role_confidence} confidence` : ''}</p></div><button onClick={onRemove} title="Remove player" className="text-slate-500 hover:text-red-300">×</button></div>
    <div className="space-y-4">
      {showBat && <MetricTiles title={role.toLowerCase().includes('all-rounder') ? 'Batting contribution' : 'Batting'} color="text-indigo-200" rows={[["Runs", batting.runs], ['Innings', batting.innings], ['Average', batting.average], ['Strike rate', batting.strike_rate], ['Boundary %', batting.boundary_percentage], ['Dot-ball %', batting.dot_ball_percentage]]} />}
      {showBowl && <MetricTiles title={role.toLowerCase().includes('all-rounder') ? 'Bowling contribution' : 'Bowling'} color="text-emerald-200" rows={[["Wickets", bowling.wickets], ['Overs', bowling.overs_display], ['Economy', bowling.economy_rate], ['Bowling average', bowling.bowling_average], ['Bowling strike rate', bowling.bowling_strike_rate], ['Dot-ball %', bowling.dot_ball_percentage], ['Boundary % conceded', bowling.boundary_percentage]]} />}
      {!showBat && !showBowl && <p className="text-xs text-slate-500">This role is not eligible for the selected {discipline} comparison.</p>}
      {phases.length > 0 && (discipline === 'all' || (discipline === 'batting' && showBat) || (discipline === 'bowling' && showBowl)) && <div className="border-t border-slate-800 pt-3"><h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">{showBowl && !showBat ? 'Bowling phase profile' : 'Batting phase profile'}</h4><div className="space-y-1.5">{phases.map(p => <div key={p.phase} className="flex justify-between gap-2 text-[11px]"><span className="text-slate-500">{p.phase.replaceAll('_', ' ')}</span><span className="text-slate-300">{showBowl && !showBat ? `${p.wickets ?? '—'} wkts · ${fmt(p.economy)} econ · ${fmt(p.dot_ball_percentage)}% dots` : `${fmt(p.runs)} runs · ${fmt(p.strike_rate)} SR`}</span></div>)}</div></div>}
      <p className="text-[10px] text-slate-600">{batting.matches ?? bowling.matches ?? '—'} match sample · filters applied on match dates in CPI analytics</p>
    </div>
  </article>;
}

export default function PlayerComparison() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedIds, setSelectedIds] = useState(searchParams.get('players')?.split(',').filter(Boolean) || []);
  const [players, setPlayers] = useState([]);
  const [analyticsById, setAnalyticsById] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [metadata, setMetadata] = useState(null);
  const [scoutingOptions, setScoutingOptions] = useState(null);
  const [discipline, setDiscipline] = useState('all');
  const [metric, setMetric] = useState('strike_rate');
  const [draft, setDraft] = useState({ format: 'T20', gender: 'all', competition: '', season: '', start_year: '', end_year: '', team_id: '', vs_team_id: '', venue_id: '' });
  const [filters, setFilters] = useState(draft);

  useEffect(() => {
    Promise.all([getPlayerFilterMetadata(), getScoutingOptions()]).then(([m, s]) => { setMetadata(m); setScoutingOptions(s); }).catch(err => setError(err.message || 'Could not load comparison filters.'));
  }, []);

  const patchDraft = (key, value) => setDraft(prev => ({ ...prev, [key]: value }));
  const applyFilters = () => {
    if (draft.start_year && draft.end_year && Number(draft.start_year) > Number(draft.end_year)) { setError('From year must be less than or equal to To year.'); return; }
    setError(''); setFilters({ ...draft });
  };
  const resetFilters = () => { const initial = { format: 'T20', gender: 'all', competition: '', season: '', start_year: '', end_year: '', team_id: '', vs_team_id: '', venue_id: '' }; setDraft(initial); setFilters(initial); setError(''); };

  const loadSelected = useCallback(async () => {
    if (!selectedIds.length) { setPlayers([]); setAnalyticsById({}); return; }
    setLoading(true); setError('');
    try {
      const loaded = await Promise.all(selectedIds.map(async id => {
        const [player, analytics] = await Promise.all([
          getPlayer(id), getPlayerAnalytics(id, { ...filters, start_year: filters.start_year || undefined, end_year: filters.end_year || undefined }),
        ]);
        return { player, analytics };
      }));
      setPlayers(loaded.map(row => row.player));
      setAnalyticsById(Object.fromEntries(loaded.map(row => [row.player.id, row.analytics])));
    } catch (err) { setError(err.message || 'Could not load player comparison.'); }
    finally { setLoading(false); }
  }, [selectedIds.join(','), JSON.stringify(filters)]);
  useEffect(() => { loadSelected(); }, [loadSelected]);

  const updateIds = next => { setSelectedIds(next); setSearchParams(next.length ? { players: next.join(',') } : {}); };
  const addPlayer = player => { if (!selectedIds.includes(player.id) && selectedIds.length < 3) updateIds([...selectedIds, player.id]); };
  const removePlayer = id => updateIds(selectedIds.filter(candidate => candidate !== id));
  const loadPreset = async (p1, p2) => {
    try { const [a, b] = await Promise.all([getPlayers({ name: p1, page_size: 1 }), getPlayers({ name: p2, page_size: 1 })]); if (a.players?.[0] && b.players?.[0]) updateIds([a.players[0].id, b.players[0].id]); }
    catch (err) { setError(err.message || 'Could not load this comparison preset.'); }
  };

  const rows = useMemo(() => players.map(player => ({ player, analytics: analyticsById[player.id] })).filter(item => item.analytics), [players, analyticsById]);
  const compatible = rows.filter(({ analytics }) => discipline === 'batting' ? isBatter(analytics.primary_role) : discipline === 'bowling' ? isBowler(analytics.primary_role) : true);
  const battingEligible = rows.filter(({ analytics }) => isBatter(analytics.primary_role));
  const bowlingEligible = rows.filter(({ analytics }) => isBowler(analytics.primary_role));
  const metricOptions = discipline === 'bowling'
    ? [['wickets', 'Wickets'], ['economy_rate', 'Economy'], ['bowling_average', 'Bowling average'], ['bowling_strike_rate', 'Bowling strike rate'], ['dot_ball_percentage', 'Dot-ball %'], ['boundary_percentage', 'Boundary % conceded']]
    : [['runs', 'Runs'], ['average', 'Batting average'], ['strike_rate', 'Strike rate'], ['boundary_percentage', 'Boundary %'], ['dot_ball_percentage', 'Dot-ball %'], ['balls_faced', 'Balls faced']];
  useEffect(() => { if (!metricOptions.some(([key]) => key === metric)) setMetric(metricOptions[0][0]); }, [discipline]);

  const getDisciplineValues = (analytics, side) => side === 'bowling' ? analytics.bowling : analytics.batting;
  const radarMetrics = discipline === 'bowling'
    ? [{ key: 'economy_rate', label: 'Economy', lowerIsBetter: true }, { key: 'bowling_average', label: 'Bowl avg', lowerIsBetter: true }, { key: 'bowling_strike_rate', label: 'Bowl SR', lowerIsBetter: true }, { key: 'dot_ball_percentage', label: 'Dot %' }, { key: 'boundary_percentage', label: 'Boundary %', lowerIsBetter: true }]
    : [{ key: 'average', label: 'Bat avg' }, { key: 'strike_rate', label: 'Bat SR' }, { key: 'boundary_percentage', label: 'Boundary %' }, { key: 'dot_ball_percentage', label: 'Dot %', lowerIsBetter: true }];

  const exportCsv = () => {
    const csvRows = [['Player', 'Role', 'Format', 'Gender', 'Matches', 'Batting runs', 'Batting average', 'Batting strike rate', 'Wickets', 'Bowling average', 'Economy', 'Bowling strike rate']];
    rows.forEach(({ player, analytics }) => csvRows.push([player.name, analytics.primary_role, filters.format, filters.gender, analytics.batting.matches ?? analytics.bowling.matches ?? '', analytics.batting.runs ?? '', analytics.batting.average ?? '', analytics.batting.strike_rate ?? '', analytics.bowling.wickets ?? '', analytics.bowling.bowling_average ?? '', analytics.bowling.economy_rate ?? '', analytics.bowling.bowling_strike_rate ?? '']));
    const escape = value => `"${String(value ?? '').replaceAll('"', '""')}"`;
    const blob = new Blob([csvRows.map(row => row.map(escape).join(',')).join('\n')], { type: 'text/csv;charset=utf-8' });
    const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = `player_comparison_${new Date().toISOString().slice(0, 10)}.csv`; link.click(); URL.revokeObjectURL(link.href);
  };

  const years = metadata?.years || [];
  const teams = metadata?.teams || [];
  const venues = metadata?.venues || [];
  const seasons = scoutingOptions?.seasons || [];
  const competitions = scoutingOptions?.competitions || [];
  const filterSelect = (label, key, options, placeholder) => <label key={key} className="text-xs text-slate-400">{label}<select className={`${selectClass} mt-1`} value={draft[key]} onChange={e => patchDraft(key, e.target.value)}><option value="">{placeholder}</option>{options.map(option => typeof option === 'string' ? <option key={option} value={option}>{option}</option> : <option key={option.id} value={option.id}>{option.name}</option>)}</select></label>;

  return <div>
    <PageHeader title="Player Comparison" subtitle="Compare players on the same format, gender and match sample. Bowling comparisons use bowling performance only; batting comparisons use batting performance only." />

    <section className="mb-6 rounded-xl border border-slate-800 bg-slate-900 p-5">
      <h2 className="mb-3 text-sm font-semibold text-indigo-300">Comparison filters</h2>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        {filterSelect('Format', 'format', (metadata?.formats?.length ? metadata.formats : FORMATS), 'Select format')}
        {filterSelect('Gender', 'gender', ['all', 'male', 'female'], 'All genders')}
        {filterSelect('Competition', 'competition', competitions, 'All competitions')}
        {filterSelect('Season', 'season', seasons, 'All seasons')}
        {filterSelect('Playing team', 'team_id', teams, 'Any team')}
        {filterSelect('Opponent', 'vs_team_id', teams, 'All opponents')}
        {filterSelect('Venue', 'venue_id', venues, 'All venues')}
        {filterSelect('From year', 'start_year', years.map(String), 'Earliest')}
        {filterSelect('To year', 'end_year', years.map(String), 'Latest')}
        <label className="text-xs text-slate-400">Comparison focus<select className={`${selectClass} mt-1`} value={discipline} onChange={e => setDiscipline(e.target.value)}><option value="all">Role-aware overview</option><option value="batting">Batting</option><option value="bowling">Bowling</option></select></label>
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3"><p className="text-xs text-slate-500">Filters query match-level CPI analytics and apply to batting, bowling and phase data.</p><div className="flex gap-2"><button onClick={resetFilters} className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 hover:bg-slate-800">Reset</button><button onClick={applyFilters} className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500">Apply filters</button></div></div>
    </section>

    <section className="mb-6 rounded-xl border border-slate-800 bg-slate-900 p-5">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-4"><PlayerPicker onSelect={addPlayer} currentIds={selectedIds} /><span className="text-xs text-slate-500">{selectedIds.length}/3 selected</span></div>
      <div className="border-t border-slate-800 pt-3"><p className="mb-2 text-xs font-medium text-slate-400">Quick comparisons</p><div className="flex flex-wrap gap-2">{FAMOUS_COMPARISONS.map(preset => <button key={preset.name} onClick={() => loadPreset(preset.p1, preset.p2)} className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-slate-300 hover:border-indigo-500">{preset.name}</button>)}</div></div>
    </section>

    {error && <div role="alert" className="mb-4 flex items-center justify-between rounded-lg border border-red-900/60 bg-red-950/30 p-3 text-sm text-red-300"><span>{error}</span><button onClick={loadSelected} className="underline">Retry</button></div>}
    {selectedIds.length === 0 ? <EmptyState message="Search and select players to compare their batting and bowling profiles." /> : loading ? <div className="py-12"><LoadingSpinner /></div> : rows.length === 0 ? <EmptyState message="No analytics are available for the selected players and filters." /> : <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-xs text-slate-500">{filters.format} · {filters.gender === 'all' ? 'All genders' : filters.gender === 'male' ? "Men's" : "Women's"}{filters.start_year || filters.end_year ? ` · ${filters.start_year || 'earliest'}–${filters.end_year || 'latest'}` : ''}{filters.competition ? ` · ${filters.competition}` : ''}</p><button onClick={exportCsv} className="rounded border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-700">Export comparison CSV</button></div>
      {discipline === 'all' ? <div className="grid gap-4 xl:grid-cols-2">
        <div className="space-y-4"><BarChart title="Batting average comparison" subtitle="Specialist batters, wicketkeeper-batters and all-rounders; specialist bowlers are excluded." data={battingEligible.map(({ player, analytics }, index) => ({ label: player.name, value: analytics.batting.average, color: COLORS[index % COLORS.length] }))} formatter={fmt} /><RadarChart title="Batting profile" subtitle="Batting-eligible roles only." series={battingEligible.map(({ player, analytics }) => ({ name: player.name, values: analytics.batting || {} }))} metrics={[{ key: 'average', label: 'Bat avg' }, { key: 'strike_rate', label: 'Bat SR' }, { key: 'boundary_percentage', label: 'Boundary %' }, { key: 'dot_ball_percentage', label: 'Dot %', lowerIsBetter: true }]} /></div>
        <div className="space-y-4"><BarChart title="Bowling economy comparison" subtitle="Specialist bowlers and all-rounders; specialist batters are excluded." data={bowlingEligible.map(({ player, analytics }, index) => ({ label: player.name, value: analytics.bowling.economy_rate, color: COLORS[index % COLORS.length] }))} formatter={fmt} /><RadarChart title="Bowling profile" subtitle="Bowling-eligible roles only. No batting metrics are included." series={bowlingEligible.map(({ player, analytics }) => ({ name: player.name, values: analytics.bowling || {} }))} metrics={[{ key: 'economy_rate', label: 'Economy', lowerIsBetter: true }, { key: 'bowling_average', label: 'Bowl avg', lowerIsBetter: true }, { key: 'bowling_strike_rate', label: 'Bowl SR', lowerIsBetter: true }, { key: 'dot_ball_percentage', label: 'Dot %' }, { key: 'boundary_percentage', label: 'Boundary %', lowerIsBetter: true }]} /></div>
      </div> : <div className="grid gap-4 xl:grid-cols-2">
        <div className="space-y-2"><label className="text-xs text-slate-400">{discipline === 'bowling' ? 'Bowling' : 'Batting'} metric to compare<select className={`${selectClass} mt-1 max-w-xs`} value={metric} onChange={e => setMetric(e.target.value)}>{metricOptions.map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label><BarChart title={`${metricOptions.find(([key]) => key === metric)?.[1] || 'Metric'} comparison`} subtitle={`Only players with a role suitable for ${discipline} are included.`} data={compatible.map(({ player, analytics }, index) => ({ label: player.name, value: getDisciplineValues(analytics, discipline)?.[metric], color: COLORS[index % COLORS.length] }))} formatter={fmt} /></div>
        <RadarChart title={`${discipline === 'bowling' ? 'Bowling' : 'Batting'} profile`} subtitle="Role-compatible players only; each axis is normalized within this comparison. Bowling axes use bowling statistics exclusively." series={compatible.map(({ player, analytics }) => ({ name: player.name, values: getDisciplineValues(analytics, discipline) || {} }))} metrics={radarMetrics} />
      </div>}
      {discipline !== 'all' && compatible.length < rows.length && <p className="rounded-lg border border-amber-900/50 bg-amber-950/20 p-3 text-xs text-amber-200">{rows.length - compatible.length} selected player(s) excluded because their classified role is not eligible for {discipline} comparisons.</p>}
      <div className="flex flex-col gap-4 overflow-x-auto pb-2 md:flex-row">{rows.map(item => <PlayerCard key={item.player.id} item={item} discipline={discipline} format={filters.format} onRemove={() => removePlayer(item.player.id)} />)}</div>
    </div>}
  </div>;
}
