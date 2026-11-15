/**
 * Innings-level batting and bowling dashboards for the player profile.
 * All aggregates come from GET /players/{id}/innings-log; this file only shapes
 * them for display.
 */
import { matchUrl } from '../../components/MatchLink';
import { useEffect, useMemo, useState } from 'react';
import { getPlayerInningsLog } from '../../services/api';
import { Callout, DashboardSkeleton, DataTable, EmptyState, ErrorState, KpiGrid, MatchLink, Panel, SampleBadge, Segmented } from '../../components/ui';
import { BarChart, ColumnChart, DonutChart, Histogram, MultiSeriesLine, PALETTE } from '../../components/charts';
import { DASH, fmtAvg, fmtDec, fmtEcon, fmtInt, fmtPct, fmtSR } from '../../lib/format';

const cache = new Map();
const inflight = new Map();
const fetchLog = (key, playerId, params) => {
  if (!inflight.has(key)) inflight.set(key, getPlayerInningsLog(playerId, params).then(d => { cache.set(key, d); return d; }).finally(() => inflight.delete(key)));
  return inflight.get(key);
};

function useInningsLog(playerId, params) {
  const key = JSON.stringify([playerId, params]);
  const [state, setState] = useState(() => cache.get(key) ? { data: cache.get(key), loading: false, error: null } : { data: null, loading: true, error: null });
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    if (cache.has(key)) { setState({ data: cache.get(key), loading: false, error: null }); return undefined; }
    let live = true;
    setState(s => ({ ...s, loading: true, error: null }));
    fetchLog(key, playerId, params)
      .then(d => { if (live) setState({ data: d, loading: false, error: null }); })
      .catch(e => { if (live) setState({ data: null, loading: false, error: e.message || 'Could not load innings records.' }); });
    return () => { live = false; };
  }, [key, nonce]); // eslint-disable-line react-hooks/exhaustive-deps
  return { ...state, retry: () => { cache.delete(key); setNonce(n => n + 1); } };
}

function FilterContext({ data }) {
  return <Callout>{data.ignored_filters_note} Opponent, venue, season, year and format filters from the profile are applied.</Callout>;
}

/* =============================================================== batting */

export function BattingDeepDive({ playerId, params }) {
  const { data, loading, error, retry } = useInningsLog(playerId, params);
  const [progress, setProgress] = useState('innings');
  if (loading) return <DashboardSkeleton panels={4} />;
  if (error) return <ErrorState message={error} onRetry={retry} />;
  const b = data?.batting;
  if (!b?.summary?.innings) return <EmptyState message="No batting innings for the selected filters." hint="Try widening the format, year or opponent filters." />;
  const s = b.summary, c = b.consistency;
  const inns = b.innings;
  return (
    <div className="space-y-5">
      <FilterContext data={data} />
      <KpiGrid items={[
        { label: 'Innings', value: fmtInt(s.innings), sub: `${fmtInt(s.not_outs)} not out` },
        { label: 'Runs', value: fmtInt(s.runs), sub: `${fmtInt(s.balls)} balls faced` },
        { label: 'Average', value: fmtAvg(s.average), sub: 'runs / dismissal', highlight: true },
        { label: 'Strike rate', value: fmtSR(s.strike_rate), sub: 'runs / 100 balls', highlight: true },
        { label: 'Highest', value: s.highest_score ? <MatchLink id={s.highest_score.match_id}>{`${s.highest_score.runs}${s.highest_score.not_out ? '*' : ''}`}</MatchLink> : DASH, sub: s.highest_score ? `v ${s.highest_score.opponent || '—'} · ${s.highest_score.date}` : null },
        { label: '100s / 50s', value: `${s.hundreds} / ${s.fifties}` },
        { label: '4s / 6s', value: `${fmtInt(s.fours)} / ${fmtInt(s.sixes)}` },
        { label: 'Boundary %', value: fmtPct(s.boundary_percentage), sub: 'of balls faced' },
        { label: 'Dot-ball %', value: fmtPct(s.dot_percentage), sub: 'of balls faced' },
        { label: 'Balls / dismissal', value: fmtDec(s.balls_per_dismissal, 1) },
        { label: 'Boundary runs', value: fmtPct(s.boundary_runs_percentage), sub: 'share of runs from 4s & 6s' },
        { label: 'Median score', value: c.median_runs ?? DASH, sub: `mean ${fmtDec(c.mean_runs_per_innings, 1)}` },
      ]} />

      <ColumnChart
        title={progress === 'innings' ? 'Runs by innings with 10-innings rolling average' : progress === 'cumulative' ? 'Cumulative runs' : 'Season-by-season runs and average'}
        subtitle={progress === 'innings' ? 'Bars: runs in each innings (chronological). Line: average over the trailing 10 innings (runs ÷ dismissals in window); blank until 10 innings or when no dismissal falls in the window.'
          : progress === 'cumulative' ? 'Running total of career runs across innings in the selected filters.' : 'Bars: runs per season. Line: batting average in that season.'}
        sample={progress === 'season' ? b.seasons.length : inns.length} sampleUnit={progress === 'season' ? 'seasons' : 'innings'}
        actions={<Segmented label="Progression view" value={progress} onChange={setProgress} options={[{ id: 'innings', label: 'Innings' }, { id: 'cumulative', label: 'Cumulative' }, { id: 'season', label: 'Season' }]} />}
        data={progress === 'season'
          ? b.seasons.map(x => ({ label: x.season, value: x.runs, line: x.average, tip: <SeasonTip x={x} /> }))
          : progress === 'cumulative'
            ? inns.map(r => ({ label: r.innings_index, value: r.cumulative_runs, tip: <InningsTip r={r} extra={[['Career runs', fmtInt(r.cumulative_runs)], ['Average to date', fmtAvg(r.career_average_to_date)]]} /> }))
            : inns.map(r => ({ label: r.innings_index, value: r.runs, line: r.rolling_avg_10, color: r.runs >= 50 ? PALETTE[1] : PALETTE[0], tip: <InningsTip r={r} extra={[['Rolling avg (10)', fmtAvg(r.rolling_avg_10)]]} /> }))}
        barLabel={progress === 'cumulative' ? 'Cumulative runs' : 'Runs'} lineLabel={progress === 'season' ? 'Season average' : 'Rolling average (10)'}
        xLabel={progress === 'season' ? 'Season' : 'Innings number'} yLabel="Runs" y2Label={progress === 'cumulative' ? undefined : 'Average'}
        formatter={v => fmtInt(v)} lineFormatter={v => fmtDec(v, 0)} height={260}
        footnote={progress === 'innings' ? 'Green bars mark 50+ scores. Hover a bar for the match, opponent and balls faced.' : undefined} />

      <div className="grid gap-4 lg:grid-cols-2">
        <BarChart title="Scoring distribution off the bat" subtitle="Share of balls faced by runs scored off the bat on that ball." sample={b.scoring_distribution.balls_faced} sampleUnit="balls"
          data={b.scoring_distribution.outcomes.map((o, i) => ({ label: `${o.outcome === 'Dot' ? 'Dot balls' : `${o.outcome} run${o.outcome === '1' ? '' : 's'}`} · ${fmtInt(o.balls)} balls`, value: o.percentage, color: o.outcome === 'Dot' ? 'var(--chart-muted)' : PALETTE[i % PALETTE.length] }))}
          formatter={v => fmtPct(v)} unit="Share of balls" footnote={b.scoring_distribution.note} />
        <Histogram title="Runs per innings distribution" subtitle="How often each score band occurs (bin width 10 runs)." bins={b.runs_histogram} xLabel="Runs in innings" yLabel="Innings" sample={c.innings} sampleUnit="innings" />
      </div>

      <Panel title="Consistency profile" subtitle="Derived from runs in each innings. Standard deviation uses n−1; coefficient of variation = SD ÷ mean (lower = steadier).">
        <KpiGrid cols="grid-cols-2 sm:grid-cols-4 lg:grid-cols-8" items={[
          { label: 'Mean / innings', value: fmtDec(c.mean_runs_per_innings, 1) },
          { label: 'Median', value: c.median_runs ?? DASH },
          { label: 'Std deviation', value: fmtDec(c.std_dev, 1) },
          { label: 'Coeff. variation', value: fmtDec(c.coefficient_of_variation, 2) },
          { label: 'Under 10', value: fmtPct(c.under_10_percentage), sub: `${c.under_10_count} innings`, tone: 'neg' },
          { label: '30+', value: fmtPct(c['30_plus_percentage']), sub: `${c['30_plus_count']} innings` },
          { label: '50+', value: fmtPct(c['50_plus_percentage']), sub: `${c['50_plus_count']} innings`, tone: 'pos' },
          { label: '100+', value: fmtPct(c['100_plus_percentage']), sub: `${c['100_plus_count']} innings`, tone: 'pos' },
        ]} />
        {c.innings < 20 && <p className="mt-3 text-2xs text-amber-300">Fewer than 20 innings — distribution measures are unstable at this sample size.</p>}
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <DonutChart title="How dismissals happened" subtitle="Dismissals that ended the innings, by type." data={b.dismissals.map(d => ({ label: d.type, value: d.count }))} sample={s.dismissals} sampleUnit="dismissals" centerLabel="OUTS" />
        <Panel title="Record by batting position" subtitle="Position = order of first appearance at the crease in the innings (openers 1 and 2)." bodyClassName="p-3">
          <DataTable dense pageSize={0} rows={b.batting_positions} rowKey={r => r.position} initialSort={{ key: 'position', dir: 'asc' }} columns={[
            { key: 'position', label: 'Pos', align: 'right' },
            { key: 'innings', label: 'Inns', align: 'right' },
            { key: 'runs', label: 'Runs', align: 'right', render: r => fmtInt(r.runs) },
            { key: 'average', label: 'Avg', align: 'right', render: r => fmtAvg(r.average) },
            { key: 'strike_rate', label: 'SR', align: 'right', render: r => fmtSR(r.strike_rate) },
            { key: 'sample', label: 'Sample', sortable: false, render: r => <SampleBadge n={r.innings} unit="inns" /> },
          ]} />
        </Panel>
      </div>

      <StyleSplit split={b.vs_bowling_style} />

      <Panel title="Season summary" bodyClassName="p-3">
        <DataTable dense pageSize={0} rows={b.seasons} rowKey={r => r.season} initialSort={{ key: 'season', dir: 'desc' }} columns={[
          { key: 'season', label: 'Season' },
          { key: 'innings', label: 'Inns', align: 'right' },
          { key: 'runs', label: 'Runs', align: 'right', render: r => fmtInt(r.runs) },
          { key: 'balls', label: 'Balls', align: 'right', render: r => fmtInt(r.balls) },
          { key: 'average', label: 'Avg', align: 'right', render: r => fmtAvg(r.average) },
          { key: 'strike_rate', label: 'SR', align: 'right', render: r => fmtSR(r.strike_rate) },
          { key: 'fifties', label: '50s', align: 'right' },
          { key: 'hundreds', label: '100s', align: 'right' },
          { key: 'fours', label: '4s', align: 'right' },
          { key: 'sixes', label: '6s', align: 'right' },
        ]} />
      </Panel>

      <Panel title="Innings log" subtitle="Every innings in the filtered sample. Click a score to open the match scorecard focused on this player." bodyClassName="p-3">
        <DataTable rows={[...inns].reverse()} rowKey={r => r.innings_id} rowHref={r => matchUrl(r.match_id)} rowLabel={r => `Open match v ${r.opponent || 'opponent'}, ${r.start_date}`} searchKeys={['opponent', 'venue', 'season', 'dismissal_type']} searchPlaceholder="Search opponent, venue, season…" pageSize={20} maxHeight="32rem"
          columns={[
            { key: 'start_date', label: 'Date', render: r => <MatchLink id={r.match_id} className="text-slate-100">{r.start_date}</MatchLink> },
            { key: 'opponent', label: 'Opponent', render: r => r.opponent || DASH },
            { key: 'venue', label: 'Venue', render: r => <span className="block max-w-[14rem] truncate" title={r.venue}>{r.venue || DASH}</span> },
            { key: 'position', label: 'Pos', align: 'right' },
            { key: 'runs', label: 'Runs', align: 'right', render: r => <MatchLink id={r.match_id} className="font-semibold text-white">{r.runs}{r.dismissed ? '' : '*'}</MatchLink>, className: r => r.runs >= 50 ? 'text-pos' : '' },
            { key: 'balls', label: 'Balls', align: 'right' },
            { key: 'strike_rate', label: 'SR', align: 'right', render: r => fmtSR(r.strike_rate) },
            { key: 'fours', label: '4s', align: 'right' },
            { key: 'sixes', label: '6s', align: 'right' },
            { key: 'dismissal_type', label: 'Dismissal', render: r => r.dismissal_type ? `${r.dismissal_type}${r.dismissed_by ? ` · ${r.dismissed_by}` : ''}` : <span className="text-slate-500">not out</span> },
          ]} />
      </Panel>
    </div>
  );
}

function InningsTip({ r, extra = [] }) {
  return (
    <div>
      <div className="mb-0.5 font-semibold text-white">{r.start_date} · v {r.opponent || 'Unknown'}</div>
      <div className="text-slate-400">{r.venue}</div>
      <div className="num mt-1 text-slate-100">{r.runs}{r.dismissed ? '' : '*'} ({r.balls} balls) · SR {fmtSR(r.strike_rate)}</div>
      {extra.map(([k, v]) => <div key={k} className="flex justify-between gap-3"><span className="text-slate-400">{k}</span><span className="num">{v}</span></div>)}
    </div>
  );
}

function SeasonTip({ x }) {
  return (
    <div>
      <div className="mb-0.5 font-semibold text-white">Season {x.season}</div>
      <div className="num">{fmtInt(x.runs)} runs · {x.innings} inns</div>
      <div className="num">Avg {fmtAvg(x.average)} · SR {fmtSR(x.strike_rate)}</div>
    </div>
  );
}

function StyleSplit({ split }) {
  const [metric, setMetric] = useState('strike_rate');
  const meta = { strike_rate: ['Strike rate', fmtSR], average: ['Average', fmtAvg], dot_percentage: ['Dot %', v => fmtPct(v)], boundary_percentage: ['Boundary %', v => fmtPct(v)] };
  const charted = split.styles.filter(s => s.balls >= 30);
  return (
    <div className="grid gap-4 lg:grid-cols-5">
      <BarChart className="lg:col-span-2" title={`${meta[metric][0]} by detailed bowling style`} subtitle="Only styles with 30+ balls faced are charted; all styles appear in the table."
        sample={split.classified_balls} sampleUnit="classified balls"
        data={charted.map(s => ({ label: `${s.style} · ${fmtInt(s.balls)} b`, value: s[metric], detail: `${s.dismissals} dismissals` }))} formatter={meta[metric][1]} unit={meta[metric][0]} />
      <Panel className="lg:col-span-3" title="Against detailed bowling styles"
        subtitle={`Style coverage: ${fmtPct(split.coverage_percentage)} of balls faced come from bowlers with a stored style (${fmtInt(split.unclassified_balls)} unclassified).`}
        actions={<Segmented size="xs" label="Charted metric" value={metric} onChange={setMetric} options={Object.entries(meta).map(([id, [label]]) => ({ id, label }))} />} bodyClassName="p-3"
        footer={split.note}>
        <DataTable dense pageSize={0} rows={split.styles} rowKey={r => r.style} initialSort={{ key: 'balls', dir: 'desc' }} maxHeight="22rem" columns={[
          { key: 'style', label: 'Bowling style' },
          { key: 'balls', label: 'Balls', align: 'right', render: r => fmtInt(r.balls) },
          { key: 'runs', label: 'Runs', align: 'right', render: r => fmtInt(r.runs) },
          { key: 'dismissals', label: 'Outs', align: 'right' },
          { key: 'average', label: 'Avg', align: 'right', render: r => fmtAvg(r.average) },
          { key: 'strike_rate', label: 'SR', align: 'right', render: r => fmtSR(r.strike_rate) },
          { key: 'dot_percentage', label: 'Dot %', align: 'right', render: r => fmtPct(r.dot_percentage) },
          { key: 'boundary_percentage', label: 'Bnd %', align: 'right', render: r => fmtPct(r.boundary_percentage) },
        ]} rowClassName={r => r.balls < 30 ? 'opacity-60' : ''} />
      </Panel>
    </div>
  );
}

/* =============================================================== bowling */

export function BowlingDeepDive({ playerId, params, bowlingStyle }) {
  const { data, loading, error, retry } = useInningsLog(playerId, params);
  const [view, setView] = useState('match');
  const w = data?.bowling;
  const inns = useMemo(() => w?.innings || [], [w]);
  if (loading) return <DashboardSkeleton panels={4} />;
  if (error) return <ErrorState message={error} onRetry={retry} />;
  if (!w?.summary?.innings) return <EmptyState message="No bowling innings for the selected filters." />;
  const s = w.summary, c = w.consistency;
  return (
    <div className="space-y-5">
      <FilterContext data={data} />
      {bowlingStyle && <p className="text-xs text-slate-400">Stored bowling style: <span className="text-slate-200">{bowlingStyle}</span></p>}
      <KpiGrid items={[
        { label: 'Innings', value: fmtInt(s.innings) },
        { label: 'Overs', value: s.overs, sub: `${fmtInt(s.legal_balls)} legal balls` },
        { label: 'Wickets', value: fmtInt(s.wickets), sub: `${fmtDec(s.wickets_per_innings, 2)} per innings`, highlight: true },
        { label: 'Economy', value: fmtEcon(s.economy), sub: 'runs / over', highlight: true },
        { label: 'Average', value: fmtAvg(s.average), sub: 'runs / wicket' },
        { label: 'Strike rate', value: fmtDec(s.strike_rate, 1), sub: 'balls / wicket' },
        { label: 'Dot-ball %', value: fmtPct(s.dot_percentage) },
        { label: 'Boundary % conceded', value: fmtPct(s.boundary_percentage) },
        { label: 'Maidens', value: fmtInt(s.maidens) },
        { label: '4w / 5w', value: `${s.four_wicket_hauls} / ${s.five_wicket_hauls}` },
        { label: 'Best figures', value: s.best_figures ? <MatchLink id={s.best_figures.match_id}>{s.best_figures.figures}</MatchLink> : DASH, sub: s.best_figures ? `v ${s.best_figures.opponent || '—'} · ${s.best_figures.date}` : null },
        { label: 'Runs conceded', value: fmtInt(s.runs) },
      ]} />

      {view === 'match' ? (
        <ColumnChart title="Match-by-match bowling" subtitle="Bars: runs conceded per innings. Red dots: wickets taken. Line: 5-innings rolling economy."
          sample={inns.length} sampleUnit="innings"
          actions={<Segmented label="Trend view" value={view} onChange={setView} options={[{ id: 'match', label: 'By innings' }, { id: 'cumulative', label: 'Cumulative' }, { id: 'season', label: 'Season' }]} />}
          data={inns.map(r => ({ label: r.innings_index, value: r.runs, line: r.rolling_economy_5, markers: r.wickets, tip: <BowlTip r={r} /> }))}
          barLabel="Runs conceded" lineLabel="Rolling economy (5)" markerLabel="Wicket" xLabel="Innings number" yLabel="Runs" y2Label="Economy"
          formatter={v => fmtInt(v)} lineFormatter={v => fmtDec(v, 1)} height={270} />
      ) : view === 'cumulative' ? (
        <MultiSeriesLine title="Cumulative wickets" subtitle="Running total of bowler-credited wickets."
          sample={inns.length} sampleUnit="innings" xLabel="Innings number" yLabel="Wickets"
          actions={<Segmented label="Trend view" value={view} onChange={setView} options={[{ id: 'match', label: 'By innings' }, { id: 'cumulative', label: 'Cumulative' }, { id: 'season', label: 'Season' }]} />}
          series={[{ name: 'Wickets', points: inns.map(r => ({ x: r.innings_index, y: r.cumulative_wickets, tip: <BowlTip r={r} extra={[['Career wickets', r.cumulative_wickets]]} /> })) }]} yFormatter={v => fmtInt(v)} />
      ) : (
        <ColumnChart title="Season wickets and economy" subtitle="Bars: wickets per season. Line: economy in that season."
          sample={w.seasons.length} sampleUnit="seasons"
          actions={<Segmented label="Trend view" value={view} onChange={setView} options={[{ id: 'match', label: 'By innings' }, { id: 'cumulative', label: 'Cumulative' }, { id: 'season', label: 'Season' }]} />}
          data={w.seasons.map(x => ({ label: x.season, value: x.wickets, line: x.economy, tip: <div><div className="font-semibold text-white">Season {x.season}</div><div className="num">{x.wickets} wkts · {x.overs} ov · econ {fmtEcon(x.economy)} · avg {fmtAvg(x.average)}</div></div> }))}
          barLabel="Wickets" lineLabel="Economy" xLabel="Season" yLabel="Wickets" y2Label="Economy" formatter={v => fmtInt(v)} lineFormatter={v => fmtDec(v, 1)} color={PALETTE[2]} lineColor={PALETTE[3]} />
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <DonutChart title="Dismissal types" subtitle="Bowler-credited wickets by mode." data={w.dismissal_types.map(d => ({ label: d.type, value: d.count }))} sample={s.wickets} sampleUnit="wickets" centerLabel="WICKETS" />
        <BarChart title="Wickets per innings" subtitle="How many innings produced each wicket count." sample={s.innings} sampleUnit="innings"
          data={w.wickets_per_innings_distribution.map((d, i) => ({ label: `${d.wickets} wicket${d.wickets === '1' ? '' : 's'}`, value: d.innings, color: PALETTE[Math.min(i, PALETTE.length - 1)] }))} formatter={v => `${fmtInt(v)} inns`} unit="Innings" />
        <Histogram title="Runs conceded per innings" subtitle="Distribution of bowling runs conceded in an innings (bin width shown on axis)." bins={w.runs_conceded_histogram} xLabel="Runs conceded" yLabel="Innings" color={PALETTE[3]} sample={s.innings} sampleUnit="innings" />
      </div>

      <Panel title="Consistency" subtitle="Per-innings variation; economy bands use innings economy.">
        <KpiGrid cols="grid-cols-2 sm:grid-cols-4" items={[
          { label: 'Economy std dev', value: fmtDec(c.economy_std_dev, 2) },
          { label: 'Innings with a wicket', value: fmtPct(c.innings_with_wicket_percentage) },
          { label: 'Economy under 6', value: fmtPct(c.economy_under_6_percentage), tone: 'pos' },
          { label: 'Economy over 9', value: fmtPct(c.economy_over_9_percentage), tone: 'neg' },
        ]} />
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Bowling by venue" subtitle="Top venues by balls bowled in this sample." bodyClassName="p-3">
          <DataTable dense pageSize={10} rows={w.venues} rowKey={r => r.venue_id} initialSort={{ key: 'legal_balls', dir: 'desc' }} columns={[
            { key: 'venue', label: 'Venue', render: r => <span className="block max-w-[12rem] truncate" title={r.venue}>{r.venue}</span> },
            { key: 'innings', label: 'Inns', align: 'right' },
            { key: 'legal_balls', label: 'Overs', align: 'right', render: r => r.overs },
            { key: 'wickets', label: 'Wkts', align: 'right' },
            { key: 'economy', label: 'Econ', align: 'right', render: r => fmtEcon(r.economy) },
            { key: 'average', label: 'Avg', align: 'right', render: r => fmtAvg(r.average) },
          ]} />
        </Panel>
        <Panel title="Season summary" bodyClassName="p-3">
          <DataTable dense pageSize={10} rows={w.seasons} rowKey={r => r.season} initialSort={{ key: 'season', dir: 'desc' }} columns={[
            { key: 'season', label: 'Season' },
            { key: 'innings', label: 'Inns', align: 'right' },
            { key: 'legal_balls', label: 'Overs', align: 'right', render: r => r.overs },
            { key: 'wickets', label: 'Wkts', align: 'right' },
            { key: 'economy', label: 'Econ', align: 'right', render: r => fmtEcon(r.economy) },
            { key: 'average', label: 'Avg', align: 'right', render: r => fmtAvg(r.average) },
            { key: 'dot_percentage', label: 'Dot %', align: 'right', render: r => fmtPct(r.dot_percentage) },
          ]} />
        </Panel>
      </div>

      <Panel title="Bowling innings log" subtitle={w.note} bodyClassName="p-3">
        <DataTable rows={[...inns].reverse()} rowKey={r => r.innings_id} rowHref={r => matchUrl(r.match_id)} rowLabel={r => `Open match v ${r.opponent || 'opponent'}, ${r.start_date}`} searchKeys={['opponent', 'venue', 'season']} searchPlaceholder="Search opponent, venue, season…" pageSize={20} maxHeight="32rem"
          columns={[
            { key: 'start_date', label: 'Date', render: r => <MatchLink id={r.match_id} className="text-slate-100">{r.start_date}</MatchLink> },
            { key: 'opponent', label: 'Opponent', render: r => r.opponent || DASH },
            { key: 'venue', label: 'Venue', render: r => <span className="block max-w-[14rem] truncate" title={r.venue}>{r.venue || DASH}</span> },
            { key: 'legal_balls', label: 'O', align: 'right', render: r => r.overs },
            { key: 'maidens', label: 'M', align: 'right' },
            { key: 'runs', label: 'R', align: 'right' },
            { key: 'wickets', label: 'W', align: 'right', render: r => <MatchLink id={r.match_id} className="font-semibold text-white">{r.wickets}</MatchLink>, className: r => r.wickets >= 3 ? 'text-pos' : '' },
            { key: 'economy', label: 'Econ', align: 'right', render: r => fmtEcon(r.economy) },
            { key: 'dots', label: 'Dots', align: 'right' },
            { key: 'boundaries', label: '4s+6s', align: 'right' },
          ]} />
      </Panel>
    </div>
  );
}

function BowlTip({ r, extra = [] }) {
  return (
    <div>
      <div className="mb-0.5 font-semibold text-white">{r.start_date} · v {r.opponent || 'Unknown'}</div>
      <div className="num text-slate-100">{r.figures} ({r.overs} ov) · econ {fmtEcon(r.economy)}</div>
      <div className="num text-slate-400">{r.dots} dots · {r.boundaries} boundaries</div>
      {extra.map(([k, v]) => <div key={k} className="flex justify-between gap-3"><span className="text-slate-400">{k}</span><span className="num">{v}</span></div>)}
    </div>
  );
}
