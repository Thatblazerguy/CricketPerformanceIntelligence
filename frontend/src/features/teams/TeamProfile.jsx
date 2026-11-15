/**
 * Individual team profile: overview, home vs away, batting, bowling, match
 * situations and trends. Data: GET /competition/teams/{id}.
 */
import { useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { getTeamProfile } from '../../services/api';
import { Badge, Button, Callout, DashboardSkeleton, DataTable, EmptyState, ErrorState, KpiGrid, MatchLink, Panel, SampleBadge, Segmented, Tabs } from '../../components/ui';
import { ColumnChart, DonutChart, GroupedBarChart, Histogram, MultiSeriesLine, PALETTE } from '../../components/charts';
import { matchUrl } from '../../components/MatchLink';
import { DASH, fmtDec, fmtInt, fmtPct } from '../../lib/format';
import {
  BackLink, BaselineDelta, CiBar, EntityPicker, FormStrip, InsightList, MethodNote, PaceSpin, ProfileHero, ScopeChips, ScopeFilters,
  Unavailable, VersusRow, isNum, recordLine, resultLabel, useScope, useScopeSearch, withUnit,
} from '../competition/shared';

const TABS = [
  { id: 'overview', label: 'Overview' }, { id: 'homeaway', label: 'Home vs Away' }, { id: 'batting', label: 'Batting' },
  { id: 'bowling', label: 'Bowling' }, { id: 'situations', label: 'Match situations' }, { id: 'trends', label: 'Trends & form' },
];
const SIDE_COLORS = { home: PALETTE[1], away: PALETTE[0], neutral: PALETTE[2], unclassified: PALETTE[6] };
const PHASE = { powerplay: 'Powerplay', middle: 'Middle overs', death: 'Death overs' };

export default function TeamProfile() {
  const { id } = useParams();
  const [sp, setSp] = useSearchParams();
  const scope = useScope({ opponent: '' });
  const search = useScopeSearch(['tab', 'opponent']);
  const tab = sp.get('tab') || 'overview';
  const setTab = t => { const n = new URLSearchParams(sp); n.set('tab', t); setSp(n, { replace: true }); };
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [opponents, setOpponents] = useState([]);
  const opponent = scope.filters.opponent;

  const load = () => {
    setLoading(true); setError(null);
    getTeamProfile(id, { ...scope.params, opponent_id: opponent }).then(setData).catch(e => setError(e.message)).finally(() => setLoading(false));
  };
  useEffect(load, [id, scope.key, opponent]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!data || opponent) return;
    setOpponents((data.situations.opposition || []).map(o => ({ id: o.team_id, name: o.team, matches: o.matches })));
  }, [data, opponent]);

  const rec = data?.overview.record;
  return (
    <div>
      <BackLink to={`/teams${search}`}>All teams</BackLink>
      <ScopeFilters scope={scope}>
        {opponents.length > 0 && <EntityPicker label="Opponent" items={opponents} value={opponent} onChange={v => scope.setFilter('opponent', v)} allowEmpty labelOf={o => `${o.name} (${o.matches})`} />}
      </ScopeFilters>
      {loading && !data && <DashboardSkeleton />}
      {error && <ErrorState message={error} onRetry={load} />}
      {data && !error && (
        <div className={loading ? 'pointer-events-none opacity-60 transition-opacity' : 'transition-opacity'}>
          <ProfileHero eyebrow="Team profile" title={data.team.name}
            subtitle={rec.matches ? `${recordLine(rec)} · ${data.overview.first_played} → ${data.overview.last_played}` : 'No matches in this selection'}
            meta={<><ScopeChips scope={data.scope} extra={opponent && opponents.find(o => o.id === opponent) ? `vs ${opponents.find(o => o.id === opponent).name}` : null} />{data.team.country && <Badge variant="green">Verified country · {data.team.country}</Badge>}</>}
            aside={<Button as={Link} size="sm" icon="compare" to={`/teams/compare${search}${search ? '&' : '?'}a=${data.team.id}`}>Compare</Button>}>
            {rec.matches > 0 && (
              <div className="flex flex-wrap items-end gap-x-8 gap-y-4">
                <div><div className="eyebrow mb-1">Win %</div><div className="num text-4xl font-semibold tracking-tight text-white">{fmtPct(rec.win_percentage)}</div><div className="mt-1 text-2xs text-slate-500">{rec.win.ci95 ? `95% CI ${rec.win.ci95[0]}–${rec.win.ci95[1]}% · n=${rec.decided} decided` : 'No decided matches'}</div></div>
                <div><div className="eyebrow mb-1.5">Last 10</div><FormStrip items={[...data.form.last10].reverse().map(r => ({ result: r.result, match_id: r.match_id, label: `${resultLabel(r.result)} v ${r.opponent}, ${r.date}` }))} /></div>
                <div className="min-w-[14rem] flex-1"><StackedBarInline r={rec} /></div>
              </div>
            )}
          </ProfileHero>
          {!rec.matches ? <div className="panel"><EmptyState message="No matches for this team with the selected filters." hint="National sides play T20I/ODI/Test; franchise and domestic sides play T20/ODM/MDM." /></div> : (
            <>
              <Tabs tabs={TABS} value={tab} onChange={setTab} className="mb-5" />
              <div key={tab} className="animate-fade-in space-y-5">
                {tab === 'overview' && <Overview d={data} />}
                {tab === 'homeaway' && <HomeAway d={data} search={search} />}
                {tab === 'batting' && <Batting d={data} />}
                {tab === 'bowling' && <Bowling d={data} />}
                {tab === 'situations' && <Situations d={data} search={search} />}
                {tab === 'trends' && <Trends d={data} search={search} />}
              </div>
              <MethodNote items={data.notes} />
            </>
          )}
        </div>
      )}
    </div>
  );
}

function StackedBarInline({ r }) {
  const parts = [['Won', r.won, 'bg-pos'], ['Lost', r.lost, 'bg-neg'], ['Tied', r.tied, 'bg-warn'], ['Drawn', r.drawn, 'bg-slate-500'], ['No result', r.no_result, 'bg-slate-700']].filter(p => p[1]);
  return (
    <div>
      <div className="chart-hbar flex h-2.5 overflow-hidden rounded-full bg-slate-800">{parts.map(([l, v, c]) => <span key={l} title={`${l}: ${v}`} className={`h-full ${c}`} style={{ width: `${v / r.matches * 100}%` }} />)}</div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 text-3xs text-slate-500">{parts.map(([l, v, c]) => <span key={l} className="inline-flex items-center gap-1"><i className={`h-1.5 w-1.5 rounded-full ${c}`} />{l} {v}</span>)}</div>
    </div>
  );
}

/* ---------------------------------------------------------------- overview */

function Overview({ d }) {
  const o = d.overview, bat = o.batting, bowl = o.bowling;
  const seasons = d.trends.seasons;
  return (
    <>
      <KpiGrid items={[
        { label: 'Matches', value: fmtInt(o.record.matches), sub: recordLine(o.record).split(' · ').slice(1).join(' · ') },
        { label: 'Win %', value: fmtPct(o.record.win_percentage), sub: `n=${o.record.decided} decided`, highlight: true },
        { label: 'Batting average', value: fmtDec(bat.runs_per_wicket), sub: 'runs per wicket lost' },
        { label: 'Scoring rate', value: fmtDec(bat.run_rate), sub: `runs/over · format ${fmtDec(d.baseline.run_rate)}` },
        d.limited_overs && { label: 'Avg 1st-inns score', value: fmtDec(o.average_first_innings_score, 1), sub: `n=${d.batting.first_innings.complete_innings} complete` },
        d.limited_overs && { label: 'Avg 2nd-inns score', value: fmtDec(o.average_second_innings_score, 1), sub: `n=${d.batting.second_innings.complete_innings} complete` },
        !d.limited_overs && { label: 'Avg innings score', value: fmtDec(bat.average_score, 1), sub: `n=${bat.complete_innings} complete` },
        { label: 'Avg wickets lost', value: fmtDec(bat.wickets_per_innings), sub: 'per completed innings' },
        { label: 'Avg wickets taken', value: fmtDec(bowl.wickets_per_innings), sub: 'per opponent innings' },
        { label: 'Highest total', value: bat.highest != null ? <MatchLink id={bat.highest_match_id}>{bat.highest}</MatchLink> : DASH },
        { label: 'Lowest total', value: bat.lowest != null ? <MatchLink id={bat.lowest_match_id}>{bat.lowest}</MatchLink> : DASH, sub: 'all out / full quota' },
        { label: 'Conceded per over', value: fmtDec(bowl.run_rate), sub: `bowling avg ${fmtDec(bowl.runs_per_wicket)}` },
      ]} cols="grid-cols-2 sm:grid-cols-3 lg:grid-cols-6" />
      <div className="grid gap-4 lg:grid-cols-5">
        <Panel className="lg:col-span-3" title="Analyst summary" subtitle="Only patterns that clear minimum samples are stated; significance uses two-proportion tests.">
          <InsightList items={d.insights} />
          {o.excluded_incomplete_matches > 0 && <p className="mt-4 text-2xs text-slate-500">{o.excluded_incomplete_matches} match(es) excluded from score averages (no result or reduced overs){o.super_over_ties ? `; ${o.super_over_ties} tie(s) went to a super over` : ''}.</p>}
        </Panel>
        <DonutChart className="lg:col-span-2" title="Result split" data={[{ label: 'Won', value: o.record.won, color: PALETTE[1] }, { label: 'Lost', value: o.record.lost, color: PALETTE[5] }, { label: 'Tied', value: o.record.tied, color: PALETTE[2] }, { label: 'Drawn', value: o.record.drawn, color: PALETTE[6] }, { label: 'No result', value: o.record.no_result, color: 'var(--chart-dim)' }]} centerLabel="MATCHES" sample={o.record.matches} sampleUnit="matches" />
      </div>
      <ColumnChart title="Win/loss trend by season" subtitle="Bars: wins. Line: win % of decided matches." sample={seasons.length} sampleUnit="seasons"
        data={seasons.map(s => ({ label: s.season, value: s.won, line: s.win_percentage, tip: <div><div className="font-semibold text-white">{s.season}</div><div className="num text-slate-300">{s.won}W {s.lost}L{s.tied ? ` ${s.tied}T` : ''}{s.drawn ? ` ${s.drawn}D` : ''}{s.no_result ? ` ${s.no_result}NR` : ''} · {fmtPct(s.win_percentage)}</div></div> }))}
        barLabel="Wins" lineLabel="Win %" yLabel="Wins" y2Label="Win %" formatter={v => fmtInt(v)} lineFormatter={v => `${Math.round(v)}%`} color={PALETTE[1]} />
    </>
  );
}

/* ---------------------------------------------------------------- home/away */

function HomeAway({ d, search }) {
  const ha = d.home_away, sides = ha.sides;
  const order = ['home', 'away', 'neutral'];
  const methods = ha.methods || {};
  const totalClassified = (methods.verified_country || 0) + (methods.fixture_concentration || 0);
  const h = sides.home, a = sides.away;
  const rows = [
    { label: 'Batting avg score', k: s => s.batting.average_score, f: v => fmtDec(v, 1), better: 'high' },
    { label: 'Scoring rate (RPO)', k: s => s.batting.run_rate, f: v => fmtDec(v), better: 'high' },
    { label: 'Runs per wicket (bat)', k: s => s.batting.runs_per_wicket, f: v => fmtDec(v), better: 'high' },
    { label: 'Boundary % (bat)', k: s => s.batting.boundary_percentage, f: v => fmtPct(v), better: 'high' },
    { label: 'Avg score conceded', k: s => s.bowling.average_score, f: v => fmtDec(v, 1), better: 'low' },
    { label: 'Economy (RPO conceded)', k: s => s.bowling.run_rate, f: v => fmtDec(v), better: 'low' },
    { label: 'Wickets taken / innings', k: s => s.bowling.wickets_per_innings, f: v => fmtDec(v), better: 'high' },
    { label: 'Bowling avg', k: s => s.bowling.runs_per_wicket, f: v => fmtDec(v), better: 'low' },
  ];
  const p = ha.significance_p;
  const gap = isNum(h.record.win_percentage) && isNum(a.record.win_percentage) ? h.record.win_percentage - a.record.win_percentage : null;
  return (
    <>
      <Callout tone={methods.none ? 'warn' : 'info'}>
        {ha.method_note} Classified {totalClassified} of {d.overview.record.matches} matches ({methods.verified_country || 0} via verified country, {methods.fixture_concentration || 0} via home-ground detection){methods.none ? `; ${methods.none} unclassified and excluded below.` : '.'}
      </Callout>
      <div className="grid gap-4 md:grid-cols-3">
        {order.map(s => (
          <div key={s} className="panel p-4">
            <div className="mb-3 flex items-center justify-between"><span className="eyebrow" style={{ color: SIDE_COLORS[s] }}>{s}</span><SampleBadge n={sides[s].record.matches} /></div>
            <CiBar label="Win %" p={sides[s].record.win} color={SIDE_COLORS[s]} sub={recordLine(sides[s].record).split(' · ').slice(1).join(' · ')} />
          </div>
        ))}
      </div>
      <Panel title="Is there a home advantage?" subtitle="Two-proportion z-test of home vs away win rate (decided matches only).">
        {h.record.decided >= 10 && a.record.decided >= 10 ? (
          <p className="text-sm leading-relaxed text-slate-300">
            {d.team.name} win <b className="text-white">{fmtPct(h.record.win_percentage)}</b> at home and <b className="text-white">{fmtPct(a.record.win_percentage)}</b> away — a gap of <b className="text-white">{fmtDec(Math.abs(gap), 1)} points</b> {gap >= 0 ? 'in favour of home' : 'in favour of away'}.{' '}
            {p !== null && p < 0.05 ? <span className="text-pos">This difference is statistically significant (p{p < 0.001 ? '<0.001' : `=${p.toFixed(3)}`}).</span>
              : <span className="text-slate-400">It is not statistically significant (p={p?.toFixed(3) ?? DASH}); treat it as within normal variation.</span>}
          </p>
        ) : <p className="text-sm text-slate-400">Need at least 10 decided home and 10 decided away matches to test (home n={h.record.decided}, away n={a.record.decided}).</p>}
      </Panel>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Home vs away — performance" subtitle="Teal = home, indigo = away; the brighter bar is the better value.">
          <div className="mb-2 grid grid-cols-[1fr_auto_1fr] text-3xs uppercase tracking-wide text-slate-500"><span className="text-right" style={{ color: SIDE_COLORS.home }}>Home</span><span className="w-32 sm:w-40" /><span style={{ color: SIDE_COLORS.away }}>Away</span></div>
          {rows.map(r => <VersusRow aColor={SIDE_COLORS.home} bColor={SIDE_COLORS.away} key={r.label} label={r.label} a={r.k(h)} b={r.k(a)} format={r.f} better={r.better} />)}
        </Panel>
        {d.limited_overs ? (
          <GroupedBarChart title="Chasing vs defending in each condition" subtitle="Win % when batting first and when chasing, at home and away."
            categories={['Batting first', 'Chasing']}
            series={['home', 'away', 'neutral'].map(s => ({ name: s[0].toUpperCase() + s.slice(1), color: SIDE_COLORS[s], values: [sides[s].order?.batting_first.win_percentage, sides[s].order?.chasing.win_percentage] }))}
            formatter={v => `${Math.round(v)}%`} yLabel="Win %"
            footnote={`Samples (decided) — home: ${h.order?.batting_first.decided ?? 0} bat first / ${h.order?.chasing.decided ?? 0} chasing; away: ${a.order?.batting_first.decided ?? 0} / ${a.order?.chasing.decided ?? 0}.`} />
        ) : (
          <GroupedBarChart title="Batting and bowling by condition" subtitle="Average innings score made and conceded." categories={['Home', 'Away', 'Neutral']}
            series={[{ name: 'Avg score', color: PALETTE[0], values: order.map(s => sides[s].batting.average_score) }, { name: 'Avg conceded', color: PALETTE[5], values: order.map(s => sides[s].bowling.average_score) }]} formatter={v => fmtDec(v, 0)} yLabel="Runs" />
        )}
      </div>
      <Panel title="Home grounds" subtitle="Venues classified as home for this team, with its record there." bodyClassName="p-3">
        <DataTable dense pageSize={0} rows={ha.grounds} rowKey={r => r.venue_id} emptyMessage="No home matches classified." columns={[
          { key: 'venue', label: 'Venue', render: r => <Link className="text-slate-100 hover:text-accent-soft" to={`/venues/${r.venue_id}${search}`}>{r.venue}</Link> },
          { key: 'matches', label: 'M', align: 'right' }, { key: 'won', label: 'W', align: 'right' }, { key: 'lost', label: 'L', align: 'right' },
          { key: 'win_percentage', label: 'Win %', align: 'right', render: r => fmtPct(r.win_percentage) },
        ]} />
      </Panel>
    </>
  );
}


/* ---------------------------------------------------------------- batting */

function PhaseTable({ phases, side }) {
  return (
    <DataTable dense pageSize={0} rows={phases} rowKey={p => p.phase} columns={[
      { key: 'phase', label: 'Phase', render: p => PHASE[p.phase] },
      { key: 'innings', label: 'Inns', align: 'right' },
      { key: 'average_runs', label: side === 'bat' ? 'Avg runs' : 'Avg conceded', align: 'right', render: p => fmtDec(p.average_runs, 1) },
      { key: 'run_rate', label: 'RPO', align: 'right', render: p => <BaselineDelta value={p.run_rate} baseline={p.baseline_run_rate} lowerIsBetter={side === 'bowl'} /> },
      { key: 'baseline_run_rate', label: 'Format', align: 'right', render: p => fmtDec(p.baseline_run_rate) },
      { key: 'wickets_per_innings', label: side === 'bat' ? 'Wkts lost/inn' : 'Wkts taken/inn', align: 'right', render: p => fmtDec(p.wickets_per_innings) },
      { key: 'runs_per_wicket', label: 'Runs/wkt', align: 'right', render: p => fmtDec(p.runs_per_wicket) },
      { key: 'boundary_percentage', label: 'Bnd %', align: 'right', render: p => fmtPct(p.boundary_percentage) },
    ]} />
  );
}

function Batting({ d }) {
  const b = d.batting, o = b.overall;
  const dist = mergeBins(b.score_distribution.scored, b.score_distribution.conceded);
  return (
    <>
      <KpiGrid items={[
        { label: 'Avg runs / innings', value: fmtDec(o.average_score, 1), sub: `median ${fmtDec(o.median_score, 0)} · n=${o.complete_innings}`, highlight: true },
        { label: 'Run rate', value: fmtDec(o.run_rate), sub: `format ${fmtDec(d.baseline.run_rate)}` },
        { label: 'Boundary %', value: fmtPct(o.boundary_percentage), sub: `${fmtPct(o.boundary_run_percentage)} of runs in boundaries` },
        { label: 'Dot-ball %', value: fmtPct(o.dot_percentage) },
        { label: 'Sixes / innings', value: fmtDec(o.sixes_per_innings), sub: `fours ${fmtDec(o.fours_per_innings)}` },
        { label: 'All-out rate', value: fmtPct(o.all_out_percentage), sub: 'of complete innings' },
      ]} />
      {d.limited_overs && b.phases ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <GroupedBarChart title="Phase scoring vs format" subtitle="Runs per over by phase; format = all teams under the same filters." categories={b.phases.map(p => PHASE[p.phase])}
            series={[{ name: d.team.name, color: PALETTE[0], values: b.phases.map(p => p.run_rate) }, { name: 'Format', color: 'var(--chart-muted)', values: b.phases.map(p => p.baseline_run_rate) }]} formatter={v => fmtDec(v, 1)} yLabel="Runs per over" />
          <GroupedBarChart title="Wicket-loss pattern by phase" subtitle="Average wickets lost in each phase per innings." categories={b.phases.map(p => PHASE[p.phase])}
            series={[{ name: 'Wickets lost / innings', color: PALETTE[5], values: b.phases.map(p => p.wickets_per_innings) }]} formatter={v => fmtDec(v, 2)} yLabel="Wickets" />
        </div>
      ) : <Unavailable title="Phase analysis" reason="Powerplay/middle/death phases apply to limited-overs formats only; multi-day innings have no standard phases." />}
      {d.limited_overs && b.phases && <Panel title="Phase detail — batting" bodyClassName="p-3"><PhaseTable phases={b.phases} side="bat" /></Panel>}
      {d.limited_overs ? (
        <Panel title="Setting a target vs chasing" subtitle="Batting in innings 1 (setting) vs innings 2 (chasing). Complete innings only for averages.">
          <div className="mb-2 grid grid-cols-[1fr_auto_1fr] text-3xs uppercase tracking-wide text-slate-500"><span className="text-right text-accent-soft">Setting (1st)</span><span className="w-32 sm:w-40" /><span className="text-pos">Chasing (2nd)</span></div>
          {[['Avg score', 'average_score', v => fmtDec(v, 1)], ['Median score', 'median_score', v => fmtDec(v, 0)], ['Run rate', 'run_rate', v => fmtDec(v)], ['Runs per wicket', 'runs_per_wicket', v => fmtDec(v)], ['Wickets lost / inn', 'wickets_per_innings', v => fmtDec(v), 'low'], ['Boundary %', 'boundary_percentage', v => fmtPct(v)], ['Dot %', 'dot_percentage', v => fmtPct(v), 'low']]
            .map(([l, k, f, better = 'high']) => <VersusRow key={k} label={l} a={b.first_innings[k]} b={b.second_innings[k]} format={f} better={k === 'average_score' || k === 'median_score' ? null : better} sub={k === 'average_score' ? `n=${b.first_innings.complete_innings} / ${b.second_innings.complete_innings}` : null} />)}
          <p className="mt-3 text-2xs text-slate-500">Chasing totals are capped by the target, so lower chasing averages are expected; compare run rate and wickets instead. Chase win rates are under Match situations.</p>
        </Panel>
      ) : (
        <Panel title="Scoring by innings" bodyClassName="p-3">
          <DataTable dense pageSize={0} rows={b.by_innings.filter(r => r.innings)} rowKey={r => r.innings} columns={[
            { key: 'innings', label: 'Innings', render: r => `Innings ${r.innings}` }, { key: 'complete_innings', label: 'n', align: 'right' },
            { key: 'average_score', label: 'Avg score', align: 'right', render: r => fmtDec(r.average_score, 1) }, { key: 'run_rate', label: 'RPO', align: 'right', render: r => fmtDec(r.run_rate) },
            { key: 'runs_per_wicket', label: 'Runs/wkt', align: 'right', render: r => fmtDec(r.runs_per_wicket) }, { key: 'wickets_per_innings', label: 'Wkts/inn', align: 'right', render: r => fmtDec(r.wickets_per_innings) },
          ]} />
        </Panel>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <Histogram title="Innings totals: scored vs conceded" subtitle={`Complete innings, bin width ${b.score_distribution.bin_width} runs.`} bins={dist}
          series={[{ name: 'Scored', color: PALETTE[0], values: dist.map(x => x.a) }, { name: 'Conceded', color: PALETTE[5], values: dist.map(x => x.b) }]} xLabel="Innings total" yLabel="Innings" />
        <Histogram title="Wickets lost per innings" subtitle="How often the innings ends with each number of wickets down (complete innings)."
          bins={b.wicket_distribution.map(w => ({ label: String(w.wickets), count: w.innings }))} xLabel="Wickets lost" yLabel="Innings" color={PALETTE[5]} />
      </div>
    </>
  );
}

function mergeBins(a = [], b = []) {
  const m = new Map();
  a.forEach(x => m.set(x.bin_start, { label: x.label, start: x.bin_start, a: x.count, b: 0 }));
  b.forEach(x => { const r = m.get(x.bin_start) || { label: x.label, start: x.bin_start, a: 0, b: 0 }; r.b = x.count; m.set(x.bin_start, r); });
  return [...m.values()].sort((x, y) => x.start - y.start);
}

/* ---------------------------------------------------------------- bowling */

function Bowling({ d }) {
  const w = d.bowling, o = w.overall, sup = w.suppression, ps = w.pace_spin;
  return (
    <>
      <KpiGrid items={[
        { label: 'Wickets / innings', value: fmtDec(o.wickets_per_innings), sub: `n=${o.complete_innings} complete`, highlight: true },
        { label: 'Economy', value: fmtDec(o.run_rate), sub: `format ${fmtDec(d.baseline.run_rate)}` },
        { label: 'Strike rate', value: fmtDec(o.balls_per_wicket, 1), sub: 'balls per wicket' },
        { label: 'Bowling average', value: fmtDec(o.runs_per_wicket), sub: 'runs per wicket' },
        { label: 'Avg runs conceded', value: fmtDec(o.average_score, 1), sub: 'per opponent innings' },
        { label: 'Scoring suppression', value: isNum(sup.suppression_percentage) ? `${sup.suppression_percentage > 0 ? '+' : ''}${sup.suppression_percentage}%` : DASH, sub: `${fmtDec(sup.opponent_run_rate_against)} vs their usual ${fmtDec(sup.opponent_usual_run_rate)}`, tone: sup.suppression_percentage > 0 ? 'pos' : sup.suppression_percentage < 0 ? 'neg' : undefined, title: sup.note },
      ]} />
      {d.limited_overs && w.phases ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <GroupedBarChart title="Runs conceded per over by phase" subtitle="Lower is better. Format = all teams under the same filters." categories={w.phases.map(p => PHASE[p.phase])}
            series={[{ name: d.team.name, color: PALETTE[5], values: w.phases.map(p => p.run_rate) }, { name: 'Format', color: 'var(--chart-muted)', values: w.phases.map(p => p.baseline_run_rate) }]} formatter={v => fmtDec(v, 1)} yLabel="Runs per over" />
          <GroupedBarChart title="Wickets taken by phase" subtitle="Average wickets taken in each phase per opponent innings." categories={w.phases.map(p => PHASE[p.phase])}
            series={[{ name: 'Wickets / innings', color: PALETTE[1], values: w.phases.map(p => p.wickets_per_innings) }]} formatter={v => fmtDec(v, 2)} yLabel="Wickets" />
        </div>
      ) : <Unavailable title="Phase bowling" reason="Phases apply to limited-overs formats only." />}
      {d.limited_overs && w.phases && <Panel title="Phase detail — bowling" bodyClassName="p-3"><PhaseTable phases={w.phases} side="bowl" /></Panel>}
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title={d.limited_overs ? 'Defending vs bowling first' : 'Bowling by innings'} subtitle={d.limited_overs ? 'Bowling in innings 2 (defending a total) vs innings 1 (before chasing).' : 'Opponent innings 1 vs 2.'}>
          <div className="mb-2 grid grid-cols-[1fr_auto_1fr] text-3xs uppercase tracking-wide text-slate-500"><span className="text-right text-accent-soft">{d.limited_overs ? 'Defending' : 'Opp. inns 2'}</span><span className="w-32 sm:w-40" /><span className="text-pos">{d.limited_overs ? 'Bowling first' : 'Opp. inns 1'}</span></div>
          {[['Avg conceded', 'average_score', v => fmtDec(v, 1), 'low'], ['Economy', 'run_rate', v => fmtDec(v), 'low'], ['Wickets / innings', 'wickets_per_innings', v => fmtDec(v), 'high'], ['Strike rate', 'balls_per_wicket', v => fmtDec(v, 1), 'low'], ['Bowling avg', 'runs_per_wicket', v => fmtDec(v), 'low'], ['Dot %', 'dot_percentage', v => fmtPct(v), 'high'], ['Bowled-out %', 'all_out_percentage', v => fmtPct(v), 'high']]
            .map(([l, k, f, better]) => <VersusRow key={k} label={l} a={w.defending[k]} b={w.bowling_first[k]} format={f} better={k === 'average_score' ? null : better} />)}
          {d.limited_overs && <p className="mt-3 text-2xs text-slate-500">When defending, the chase stops at the target, so conceded totals are capped; economy and wickets are the fairer comparison.</p>}
        </Panel>
        <PaceSpin ps={ps} />
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- situations */

function Situations({ d, search }) {
  const s = d.situations;
  return (
    <>
      {d.limited_overs ? (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="panel space-y-5 p-4">
              <h3 className="text-[13px] font-semibold text-slate-100">Batting first vs chasing</h3>
              <CiBar label="Win % batting first" p={s.order.batting_first.win} color={PALETTE[0]} sub={recordLine(s.order.batting_first).split(' · ').slice(1).join(' · ')} />
              <CiBar label="Win % chasing" p={s.order.chasing.win} color={PALETTE[1]} sub={recordLine(s.order.chasing).split(' · ').slice(1).join(' · ')} />
            </div>
            <div className="panel space-y-5 p-4">
              <h3 className="text-[13px] font-semibold text-slate-100">Close matches</h3>
              <CiBar label="Win % in close matches" p={s.close.record.win} color={PALETTE[2]} sub={recordLine(s.close.record).split(' · ').slice(1).join(' · ')} />
              <p className="text-2xs leading-relaxed text-slate-500">{s.close.definition}</p>
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <Panel title="Successful chases" subtitle="Complete matches only, so targets are real first-innings totals.">
              <CiBar label="Chase success rate" p={withUnit(s.chases.success, 'chases')} color={PALETTE[1]} />
              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Mini label="Avg target chased" value={fmtDec(s.chases.average_successful_target, 1)} />
                <Mini label="Highest target chased" value={s.chases.highest_successful_target != null ? <MatchLink id={s.chases.highest_successful_target_match_id}>{s.chases.highest_successful_target}</MatchLink> : DASH} />
                <Mini label="Avg target failed" value={fmtDec(s.chases.average_failed_target, 1)} />
                <Mini label="Balls left (wins)" value={fmtDec(s.chases.average_balls_remaining_in_wins, 1)} />
                <Mini label="Wickets in hand (wins)" value={fmtDec(s.chases.average_wickets_in_hand_in_wins, 1)} />
              </div>
            </Panel>
            <Panel title="Defending totals" subtitle="Batting first in complete matches.">
              <CiBar label="Defence success rate" p={withUnit(s.defences.success, 'defences')} color={PALETTE[0]} />
              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Mini label="Avg total defended" value={fmtDec(s.defences.average_defended_total, 1)} />
                <Mini label="Lowest total defended" value={s.defences.lowest_defended_total != null ? <MatchLink id={s.defences.lowest_defended_total_match_id}>{s.defences.lowest_defended_total}</MatchLink> : DASH} />
                <Mini label="Avg total chased down" value={fmtDec(s.defences.average_breached_total, 1)} />
              </div>
            </Panel>
          </div>
        </>
      ) : <Unavailable title="Batting first vs chasing" reason="Chase/defence analysis applies to two-innings limited-overs matches. Multi-day results are shown by opponent below; draws are listed separately." />}
      <Panel title="Performance against each opponent" subtitle="Sortable. Click an opponent to filter the whole profile to that head-to-head." bodyClassName="p-3">
        <DataTable dense pageSize={15} rows={s.opposition} rowKey={r => r.team_id} searchKeys={['team']} searchPlaceholder="Search opponents…" initialSort={{ key: 'matches', dir: 'desc' }} columns={[
          { key: 'team', label: 'Opponent', render: r => <Link className="text-slate-100 hover:text-accent-soft" to={`?${new URLSearchParams({ ...Object.fromEntries(new URLSearchParams(search)), opponent: r.team_id, tab: 'overview' })}`}>{r.team}</Link> },
          { key: 'matches', label: 'M', align: 'right' }, { key: 'won', label: 'W', align: 'right' }, { key: 'lost', label: 'L', align: 'right' },
          { key: 'win_percentage', label: 'Win %', align: 'right', render: r => <span className="inline-flex items-center gap-1.5">{fmtPct(r.win_percentage)}{r.won + r.lost < 10 && <SampleBadge n={r.won + r.lost} unit="dec." />}</span> },
          { key: 'average_score', label: 'Avg score', align: 'right', render: r => fmtDec(r.average_score, 1) },
          { key: 'average_conceded', label: 'Avg conceded', align: 'right', render: r => fmtDec(r.average_conceded, 1) },
          { key: 'run_rate', label: 'RPO', align: 'right', render: r => fmtDec(r.run_rate) },
          { key: 'economy', label: 'Conc.', align: 'right', render: r => fmtDec(r.economy) },
          { key: 'last_played', label: 'Last', align: 'right', render: r => <MatchLink id={r.last_match_id}>{r.last_played}</MatchLink> },
        ]} />
      </Panel>
    </>
  );
}

function Mini({ label, value }) {
  return <div className="rounded-lg border border-line bg-surface-sunken/60 px-3 py-2"><div className="truncate text-3xs uppercase tracking-wide text-slate-500">{label}</div><div className="num mt-0.5 text-base font-semibold text-slate-100">{value}</div></div>;
}

/* ---------------------------------------------------------------- trends */

function Trends({ d, search }) {
  const t = d.trends;
  const [metric, setMetric] = useState('rates');
  const series = useMemo(() => (metric === 'rates'
    ? [{ name: 'Scored (RPO)', color: PALETTE[0], points: t.seasons.map(s => ({ x: s.season, y: s.run_rate })) }, { name: 'Conceded (RPO)', color: PALETTE[5], points: t.seasons.map(s => ({ x: s.season, y: s.economy })) }]
    : [{ name: 'Avg score', color: PALETTE[0], points: t.seasons.map(s => ({ x: s.season, y: s.average_score })) }, { name: 'Avg conceded', color: PALETTE[5], points: t.seasons.map(s => ({ x: s.season, y: s.average_conceded })) }]), [t, metric]);
  return (
    <>
      <div className="grid gap-4 lg:grid-cols-2">
        <MultiSeriesLine title="Rolling form" subtitle="Win % over the previous 10 decided matches, in date order. Dashed line = overall win %." height={250}
          series={[{ name: 'Rolling 10-match win %', color: PALETTE[1], points: t.rolling.map(r => ({ x: r.match_index, y: r.win_percentage, label: r.date })) }]}
          references={isNum(d.overview.record.win_percentage) ? [{ value: d.overview.record.win_percentage, label: `Overall ${fmtPct(d.overview.record.win_percentage)}` }] : []}
          xLabel="Decided match #" yLabel="Win %" yFormatter={v => `${Math.round(v)}%`} yMin={0} emptyText="Needs at least 10 decided matches." />
        <MultiSeriesLine categorical title="Scoring trend by season" subtitle={metric === 'rates' ? 'Runs per over scored vs conceded.' : 'Average complete-innings score made vs conceded.'} height={250}
          series={series} xLabel="Season" yLabel={metric === 'rates' ? 'Runs per over' : 'Runs'} yFormatter={v => fmtDec(v, 1)}
          actions={<Segmented size="xs" label="Trend metric" value={metric} onChange={setMetric} options={[{ id: 'rates', label: 'Run rates' }, { id: 'scores', label: 'Scores' }]} />} />
      </div>
      <Panel title="Last 10 matches" bodyClassName="p-3">
        <DataTable dense pageSize={0} rows={d.form.last10} rowKey={r => r.match_id} rowHref={r => matchUrl(r.match_id)} rowLabel={r => `Open match v ${r.opponent}, ${r.date}`} columns={[
          { key: 'date', label: 'Date', render: r => <MatchLink id={r.match_id} className="text-slate-100">{r.date}</MatchLink> },
          { key: 'result', label: 'Result', render: r => <span className={r.result === 'won' ? 'text-pos' : r.result === 'lost' ? 'text-neg' : 'text-slate-400'}>{resultLabel(r.result)}</span> },
          { key: 'opponent', label: 'Opponent' },
          { key: 'score', label: 'Score', render: r => <span className="num">{r.score ?? DASH} <span className="text-slate-500">v</span> {r.opponent_score ?? DASH}</span> },
          { key: 'margin', label: 'Margin', render: r => <span className="text-slate-400">{r.margin ?? DASH}{r.close && <Badge variant="amber" className="ml-2">close</Badge>}</span> },
          { key: 'batted_first', label: 'Order', render: r => (r.batted_first === null ? DASH : r.batted_first ? 'Batted 1st' : 'Chased') },
          { key: 'venue', label: 'Venue', render: r => (r.venue_id ? <Link className="hover:text-accent-soft" to={`/venues/${r.venue_id}${search}`}>{r.venue}</Link> : r.venue) },
          { key: 'match_id', label: '', sortable: false, render: r => <MatchLink id={r.match_id} className="text-2xs text-slate-500">Scorecard →</MatchLink> },
        ]} />
      </Panel>
      <Panel title="Season table" bodyClassName="p-3">
        <DataTable dense pageSize={0} rows={t.seasons} rowKey={r => r.season} initialSort={{ key: 'season', dir: 'desc' }} columns={[
          { key: 'season', label: 'Season' }, { key: 'matches', label: 'M', align: 'right' }, { key: 'won', label: 'W', align: 'right' }, { key: 'lost', label: 'L', align: 'right' },
          { key: 'win_percentage', label: 'Win %', align: 'right', render: r => fmtPct(r.win_percentage) },
          { key: 'average_score', label: 'Avg score', align: 'right', render: r => fmtDec(r.average_score, 1) },
          { key: 'run_rate', label: 'RPO', align: 'right', render: r => fmtDec(r.run_rate) },
          { key: 'economy', label: 'Conc.', align: 'right', render: r => fmtDec(r.economy) },
          { key: 'batting_average', label: 'Bat avg', align: 'right', render: r => fmtDec(r.batting_average) },
          { key: 'bowling_average', label: 'Bowl avg', align: 'right', render: r => fmtDec(r.bowling_average) },
        ]} />
      </Panel>
    </>
  );
}
