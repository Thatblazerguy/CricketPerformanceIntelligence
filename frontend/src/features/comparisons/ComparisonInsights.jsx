/**
 * Rate-normalised comparison with cohort percentiles.
 * Data: GET /players/compare/metrics (cohort aggregates cached server-side).
 */
import { useEffect, useMemo, useState } from 'react';
import { getPlayerComparisonMetrics } from '../../services/api';
import { Callout, DataTable, ErrorState, Panel, PanelSkeleton, SampleBadge, Segmented } from '../../components/ui';
import { GroupedBarChart, MultiSeriesLine, PALETTE, PercentileBars, RadarChart, ScatterChart } from '../../components/charts';
import { DASH, fmtAvg, fmtDec, fmtEcon, fmtInt, fmtPct, fmtSR, phaseLabel } from '../../lib/format';

const COLORS = [PALETTE[0], PALETTE[1], PALETTE[2], PALETTE[3]];
const BAT = [
  { key: 'average', label: 'Average', fmt: fmtAvg },
  { key: 'strike_rate', label: 'Strike rate', fmt: fmtSR },
  { key: 'boundary_percentage', label: 'Boundary %', fmt: v => fmtPct(v) },
  { key: 'dot_percentage', label: 'Dot % (lower better)', fmt: v => fmtPct(v) },
  { key: 'balls_per_dismissal', label: 'Balls / dismissal', fmt: v => fmtDec(v, 1) },
];
const BOWL = [
  { key: 'economy', label: 'Economy (lower better)', fmt: fmtEcon },
  { key: 'average', label: 'Average (lower better)', fmt: fmtAvg },
  { key: 'strike_rate', label: 'Strike rate (lower better)', fmt: v => fmtDec(v, 1) },
  { key: 'dot_percentage', label: 'Dot %', fmt: v => fmtPct(v) },
  { key: 'boundary_percentage', label: 'Boundary % conceded (lower better)', fmt: v => fmtPct(v) },
];
const MIN_SEASON_BALLS = 60;

export default function ComparisonInsights({ ids, filters }) {
  const [minBalls, setMinBalls] = useState('300');
  const [side, setSide] = useState('batting');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const key = JSON.stringify([ids, filters.format, filters.gender, filters.competition, filters.start_year, filters.end_year, minBalls]);
  const load = () => {
    if (!ids.length) return;
    setLoading(true); setError(null);
    getPlayerComparisonMetrics(ids, { format: filters.format || 'T20', gender: filters.gender && filters.gender !== 'all' ? filters.gender : undefined, competition: filters.competition, start_year: filters.start_year, end_year: filters.end_year, min_balls: minBalls })
      .then(setData).catch(e => setError(e.message || 'Could not load comparison metrics.')).finally(() => setLoading(false));
  };
  useEffect(load, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const players = useMemo(() => (data?.players || []).map((p, i) => ({ ...p, color: COLORS[i % COLORS.length] })), [data]);
  if (!ids.length) return null;
  if (loading && !data) return <div className="grid gap-4 lg:grid-cols-2"><PanelSkeleton rows={6} /><PanelSkeleton rows={6} /></div>;
  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!data) return null;

  const metrics = side === 'batting' ? BAT : BOWL;
  const stat = p => (side === 'batting' ? p.batting : p.bowling);
  const pct = p => (side === 'batting' ? p.batting_percentiles : p.bowling_percentiles);
  const eligible = players.filter(p => pct(p));
  const excluded = players.filter(p => !pct(p));
  const cohortN = side === 'batting' ? data.cohort.batters : data.cohort.bowlers;
  const ballsKey = side === 'batting' ? 'balls' : 'legal_balls';
  const idSet = new Set(ids);
  const scatter = side === 'batting'
    ? data.scatter.batting.map(r => { const p = players.find(x => x.player_id === r.player_id); return { ...r, name: p?.player_name, highlight: Boolean(p), color: p?.color || 'var(--chart-muted)', muted: !p, detail: `${fmtInt(r.balls)} balls` }; })
    : data.scatter.bowling.map(r => { const p = players.find(x => x.player_id === r.player_id); return { ...r, name: p?.player_name, highlight: Boolean(p), color: p?.color || 'var(--chart-muted)', muted: !p, detail: `${fmtInt(r.legal_balls)} balls` }; });
  const phases = ['powerplay', 'middle', 'death'];
  const phaseRate = (p, ph) => p.phases.find(x => x.side === side && x.phase === ph);

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3 border-t border-line pt-5">
        <div>
          <h2 className="text-base font-semibold text-white">Normalised comparison & cohort percentiles</h2>
          <p className="mt-0.5 text-xs text-slate-500">{data.format} · percentiles against every {side === 'batting' ? 'batter' : 'bowler'} with {fmtInt(data.cohort.min_balls)}+ balls under the same filters ({fmtInt(cohortN)} players). Rate metrics only — no totals — so different workloads compare fairly. Uses format, gender, competition and year filters (season, team, opponent and venue filters apply to the cards below).</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Segmented label="Discipline" value={side} onChange={setSide} options={[{ id: 'batting', label: 'Batting' }, { id: 'bowling', label: 'Bowling' }]} />
          <Segmented label="Cohort minimum balls" value={minBalls} onChange={setMinBalls} options={[{ id: '120', label: '120+ balls' }, { id: '300', label: '300+' }, { id: '600', label: '600+' }]} />
        </div>
      </div>
      {excluded.length > 0 && <Callout tone="warn">{excluded.map(p => p.player_name).join(', ')} {excluded.length === 1 ? 'has' : 'have'} fewer than {data.cohort.min_balls} {side === 'batting' ? 'balls faced' : 'balls bowled'} in this sample, so {excluded.length === 1 ? 'is' : 'are'} excluded from percentile charts (raw figures still shown below).</Callout>}

      <Panel title={`Side-by-side ${side}`} subtitle="Raw rates with cohort percentile in brackets (100 = best). Sample sizes shown first." bodyClassName="p-3">
        <DataTable dense pageSize={0} rows={players} rowKey={p => p.player_id} columns={[
          { key: 'player_name', label: 'Player', sortable: false, render: p => <span className="inline-flex items-center gap-2"><i className="h-2 w-2 rounded-full" style={{ backgroundColor: p.color }} />{p.player_name}</span> },
          { key: 'sample', label: 'Sample', sortable: false, render: p => stat(p) ? <SampleBadge n={stat(p)[ballsKey]} unit="balls" low={data.cohort.min_balls} ok={data.cohort.min_balls * 2} /> : DASH },
          { key: 'outs', label: side === 'batting' ? 'Outs' : 'Wkts', align: 'right', sortable: false, render: p => fmtInt(side === 'batting' ? p.batting?.dismissals : p.bowling?.wickets) },
          ...metrics.map(m => ({ key: m.key, label: m.label.replace(' (lower better)', ''), align: 'right', sortable: false, render: p => stat(p) ? <span>{m.fmt(stat(p)[m.key])}{pct(p)?.[m.key] != null && <span className="ml-1 text-2xs text-slate-500">({Math.round(pct(p)[m.key])})</span>}</span> : DASH })),
        ]} />
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <RadarChart scaled title={`${side === 'batting' ? 'Batting' : 'Bowling'} percentile profile`} subtitle="Cohort percentiles; larger area = stronger relative to peers."
          metrics={metrics.map(m => ({ key: m.key, label: m.label.replace(' (lower better)', '').replace(' conceded', '') }))}
          series={eligible.map(p => ({ name: p.player_name, color: p.color, values: pct(p), display: Object.fromEntries(metrics.map(m => [m.key, `${m.fmt(stat(p)[m.key])} · ${Math.round(pct(p)[m.key])}th pct`])) }))} />
        <PercentileBars title="Percentile ladder" subtitle="Each marker is a player's position in the cohort for that metric." sample={cohortN} sampleUnit="cohort players"
          metrics={metrics} players={eligible.map(p => ({ name: p.player_name, color: p.color, percentiles: pct(p), raw: Object.fromEntries(metrics.map(m => [m.key, m.fmt(stat(p)[m.key])])) }))}
          footnote={data.method} />
      </div>

      <ScatterChart title={side === 'batting' ? 'Cohort map: average vs strike rate' : 'Cohort map: economy vs strike rate'}
        subtitle={`Every qualifying ${side === 'batting' ? 'batter' : 'bowler'} in the cohort (grey); selected players highlighted.${side === 'bowling' ? ' Bottom-left is best (cheap and frequent wickets).' : ' Top-right is best.'}`}
        data={scatter} xKey={side === 'batting' ? 'average' : 'economy'} yKey="strike_rate" xLabel={side === 'batting' ? 'Batting average' : 'Economy (runs/over)'} yLabel={side === 'batting' ? 'Strike rate' : 'Balls per wicket'}
        formatX={v => fmtDec(v, side === 'batting' ? 0 : 1)} formatY={v => fmtDec(v, 0)} height={320}
        footnote={`${scatter.filter(r => idSet.has(r.player_id)).length} of ${ids.length} selected players meet the cohort minimum.`} />

      <div className="grid gap-4 lg:grid-cols-2">
        {['T20', 'T20I', 'ODI', 'ODM'].includes(data.format) ? (
          <GroupedBarChart title={side === 'batting' ? 'Strike rate by phase' : 'Economy by phase'} subtitle={side === 'batting' ? 'Runs per 100 balls in each phase.' : 'Runs per over in each phase.'}
            categories={phases.map(ph => phaseLabel(data.format, ph))}
            series={players.map(p => ({ name: p.player_name, color: p.color, values: phases.map(ph => { const r = phaseRate(p, ph); return r && r.balls >= 30 ? r.rate : null; }) }))}
            formatter={v => fmtDec(v, side === 'batting' ? 0 : 1)} yLabel={side === 'batting' ? 'Strike rate' : 'Economy'} footnote="Phases with fewer than 30 balls for a player are omitted." />
        ) : <Callout>Phase comparison is available for limited-overs formats only.</Callout>}
        {side === 'batting' ? (
          <GroupedBarChart title="Strike rate vs pace and spin" subtitle="Based on stored bowler type (pace/spin). Bars need 30+ balls."
            categories={['Pace', 'Spin']}
            series={players.map(p => ({ name: p.player_name, color: p.color, values: ['Pace', 'Spin'].map(t => { const r = p.pace_spin.find(x => x.bowling_type === t); return r && r.balls >= 30 ? r.strike_rate : null; }) }))}
            formatter={v => fmtDec(v, 0)} yLabel="Strike rate"
            footnote={players.map(p => `${p.player_name}: ${p.pace_spin.map(r => `${r.bowling_type} ${fmtInt(r.balls)}b, avg ${fmtAvg(r.average)}`).join(' · ') || 'no classified deliveries'}`).join(' | ')} />
        ) : (
          <Panel title="Bowling workload" subtitle="Balls bowled and wickets in this sample.">
            <div className="space-y-2">{players.map(p => <div key={p.player_id} className="flex items-center justify-between text-sm"><span className="inline-flex items-center gap-2"><i className="h-2 w-2 rounded-full" style={{ backgroundColor: p.color }} />{p.player_name}</span><span className="num text-slate-300">{p.bowling ? `${p.bowling.overs} ov · ${p.bowling.wickets} wkts` : 'Did not bowl'}</span></div>)}</div>
          </Panel>
        )}
      </div>

      <MultiSeriesLine categorical title={side === 'batting' ? 'Strike rate by season' : 'Economy by season'} subtitle={`Season rates where the player had ${MIN_SEASON_BALLS}+ balls; thinner seasons are omitted rather than plotted.`}
        xLabel="Season" yLabel={side === 'batting' ? 'Strike rate' : 'Economy'} yFormatter={v => fmtDec(v, side === 'batting' ? 0 : 1)} yMin={undefined}
        series={players.map(p => ({ name: p.player_name, color: p.color, allowSingle: true, points: p.seasons.filter(s => s.side === side && s.balls >= MIN_SEASON_BALLS).map(s => ({ x: s.season, y: s.rate, label: `${s.season} · ${fmtInt(s.balls)} balls` })) }))} />
    </section>
  );
}
