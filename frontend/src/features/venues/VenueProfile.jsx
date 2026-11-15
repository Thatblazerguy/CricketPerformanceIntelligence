/**
 * Individual venue profile: overview, toss analysis, batting first vs chasing,
 * playing conditions (measured vs inferred) and trends.
 * Data: GET /competition/venues/{id}.
 */
import { matchUrl } from '../../components/MatchLink';
import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { getTeamDirectory, getVenueProfile } from '../../services/api';
import { Badge, Button, Callout, DashboardSkeleton, DataTable, EmptyState, ErrorState, KpiGrid, MatchLink, Panel, SampleBadge, Tabs } from '../../components/ui';
import { ColumnChart, GroupedBarChart, Histogram, MultiSeriesLine, PALETTE, StackedBar } from '../../components/charts';
import { DASH, fmtDec, fmtInt, fmtPct } from '../../lib/format';
import {
  BackLink, BaselineDelta, CiBar, EntityPicker, InsightList, MethodNote, PaceSpin, ProfileHero, ScopeChips, ScopeFilters,
  Unavailable, isNum, useScope, useScopeSearch, withUnit,
} from '../competition/shared';

const TABS = [
  { id: 'overview', label: 'Overview' }, { id: 'toss', label: 'Toss analysis' }, { id: 'order', label: 'Batting first vs chasing' },
  { id: 'conditions', label: 'Pitch & conditions' }, { id: 'trends', label: 'Venue trends' },
];
const PHASE = { powerplay: 'Powerplay', middle: 'Middle overs', death: 'Death overs' };
const pfmt = p => (isNum(p) ? (p < 0.001 ? 'p<0.001' : `p=${Number(p).toFixed(3)}`) : 'p n/a');

export default function VenueProfile() {
  const { id } = useParams();
  const [sp, setSp] = useSearchParams();
  const scope = useScope({ team: '' });
  const search = useScopeSearch(['tab']);
  const tab = sp.get('tab') || 'overview';
  const setTab = t => { const n = new URLSearchParams(sp); n.set('tab', t); setSp(n, { replace: true }); };
  const [data, setData] = useState(null);
  const [teams, setTeams] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const team = scope.filters.team;

  const load = () => {
    setLoading(true); setError(null);
    getVenueProfile(id, { ...scope.params, team_id: team }).then(setData).catch(e => setError(e.message)).finally(() => setLoading(false));
  };
  useEffect(load, [id, scope.key, team]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { getTeamDirectory(scope.params).then(r => setTeams(r.teams.map(t => ({ id: t.team_id, name: t.team, matches: t.matches })))).catch(() => setTeams([])); }, [scope.key]); // eslint-disable-line react-hooks/exhaustive-deps

  const o = data?.overview;
  return (
    <div>
      <BackLink to={`/venues${search}`}>All venues</BackLink>
      <ScopeFilters scope={scope}>
        {teams.length > 0 && <EntityPicker label="Team" items={teams} value={team} onChange={v => scope.setFilter('team', v)} allowEmpty labelOf={t => `${t.name} (${t.matches})`} />}
      </ScopeFilters>
      {loading && !data && <DashboardSkeleton />}
      {error && <ErrorState message={error} onRetry={load} />}
      {data && !error && (
        <div className={loading ? 'pointer-events-none opacity-60 transition-opacity' : 'transition-opacity'}>
          <ProfileHero eyebrow="Venue profile" title={data.venue.name} subtitle={[data.venue.city, data.venue.country].filter(Boolean).join(', ') || 'Location not recorded'}
            meta={<><ScopeChips scope={data.scope} extra={team && teams.find(t => t.id === team) ? `${teams.find(t => t.id === team).name} matches only` : null} />{o.matches > 0 && <Badge><MatchLink id={o.first_match_id}>{o.first_played}</MatchLink> → <MatchLink id={o.last_match_id}>{o.last_played}</MatchLink></Badge>}</>}
            aside={<Button as={Link} size="sm" icon="compare" to={`/venues/compare${search}${search ? '&' : '?'}ids=${data.venue.id}`}>Compare</Button>}>
            {o.matches > 0 && (
              <div className="grid grid-cols-2 gap-x-8 gap-y-4 sm:grid-cols-4">
                <HeroStat label="Matches" value={fmtInt(o.matches)} sub={[o.outcomes.tie && `${o.outcomes.tie} tied`, o.outcomes.draw && `${o.outcomes.draw} drawn`, o.outcomes.no_result && `${o.outcomes.no_result} no result`].filter(Boolean).join(' · ') || 'all decided'} />
                <HeroStat label={data.limited_overs ? 'Avg 1st innings' : 'Avg innings 1'} value={fmtDec(o.average_first_innings, 1)} sub={`format ${fmtDec(data.baseline.average_first_innings, 1)}`} />
                <HeroStat label={data.limited_overs ? 'Batting-first wins' : 'Innings-1 side wins'} value={fmtPct(data.toss.batting_first.value)} sub={`n=${data.toss.batting_first.n} decided`} />
                <HeroStat label="Toss-winner wins" value={fmtPct(data.toss.toss_winner.value)} sub={pfmt(data.toss.p_value)} />
              </div>
            )}
          </ProfileHero>
          {!o.matches ? <div className="panel"><EmptyState message="No matches at this venue with the selected filters." hint="Try another format or remove the season/team filter." /></div> : (
            <>
              <Tabs tabs={TABS} value={tab} onChange={setTab} className="mb-5" />
              <div key={tab} className="animate-fade-in space-y-5">
                {tab === 'overview' && <Overview d={data} />}
                {tab === 'toss' && <Toss d={data} />}
                {tab === 'order' && (data.limited_overs ? <BatFirstChase d={data} /> : <Unavailable title="Batting first vs chasing" reason="Chasing analysis applies to two-innings limited-overs matches. For multi-day cricket see innings-by-innings scoring under Pitch & conditions and results under Toss analysis." />)}
                {tab === 'conditions' && <Conditions d={data} />}
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

function HeroStat({ label, value, sub }) {
  return <div><div className="eyebrow mb-1">{label}</div><div className="num text-3xl font-semibold tracking-tight text-white">{value}</div>{sub && <div className="mt-1 text-2xs text-slate-500">{sub}</div>}</div>;
}

function TotalCard({ label, rec }) {
  return {
    label, value: rec ? <MatchLink id={rec.match_id}>{`${rec.runs}${rec.wickets < 10 ? `/${rec.wickets}` : ''}`}</MatchLink> : DASH,
    sub: rec ? `${rec.team} · ${rec.date}` : null,
  };
}

/* ---------------------------------------------------------------- overview */

function Overview({ d }) {
  const o = d.overview, b = d.baseline, sd = d.batting_first_vs_chasing?.score_distribution;
  return (
    <>
      <KpiGrid items={[
        { label: d.limited_overs ? 'Avg 1st-inns score' : 'Avg innings-1 score', value: fmtDec(o.average_first_innings, 1), sub: `n=${o.first_innings_sample} · format ${fmtDec(b.average_first_innings, 1)}`, highlight: true },
        { label: d.limited_overs ? 'Avg 2nd-inns score' : 'Avg innings-2 score', value: fmtDec(o.average_second_innings, 1), sub: `n=${o.second_innings_sample} · format ${fmtDec(b.average_second_innings, 1)}` },
        TotalCard({ label: 'Highest team total', rec: o.highest_total }),
        TotalCard({ label: 'Lowest team total', rec: o.lowest_total }),
        d.limited_overs && { label: 'Highest successful chase', value: o.highest_successful_chase != null ? <MatchLink id={o.highest_successful_chase_match_id}>{o.highest_successful_chase}</MatchLink> : DASH },
        d.limited_overs && { label: 'Lowest total defended', value: o.lowest_defended_total != null ? <MatchLink id={o.lowest_defended_total_match_id}>{o.lowest_defended_total}</MatchLink> : DASH },
        { label: 'Wickets / innings', value: fmtDec(o.wickets_per_innings), sub: `format ${fmtDec(b.wickets_per_innings)}` },
        { label: 'Runs per over', value: fmtDec(o.run_rate), sub: `format ${fmtDec(b.run_rate)}` },
      ]} cols="grid-cols-2 sm:grid-cols-4" />
      <div className="grid gap-4 lg:grid-cols-5">
        <Panel className="lg:col-span-3" title="What this ground does to a match" subtitle="Measured findings first; inferred tendencies are labelled. Significance via exact binomial tests.">
          <InsightList items={d.insights} />
          {o.excluded_incomplete_matches > 0 && <p className="mt-4 text-2xs text-slate-500">{o.excluded_incomplete_matches} match(es) excluded from score averages (no result or reduced overs){o.super_over_ties ? `; ${o.super_over_ties} tie(s) went to a super over (excluded from scoring)` : ''}.</p>}
        </Panel>
        <div className="panel space-y-5 p-4 lg:col-span-2">
          <h3 className="text-[13px] font-semibold text-slate-100">Who wins here?</h3>
          <CiBar label={d.toss.label_first} p={d.toss.batting_first} color={PALETTE[0]} sub={`format ${fmtPct(b.batting_first_win_percentage)}`} />
          <CiBar label="Toss winner" p={d.toss.toss_winner} color={PALETTE[2]} sub={`format ${fmtPct(b.toss_winner_win_percentage)}`} />
        </div>
      </div>
      {sd && <Histogram title="Score distribution" subtitle={`Complete innings at this venue, bin width ${sd.bin_width} runs.`} bins={sd.bins}
        series={[{ name: '1st innings', color: PALETTE[0], values: sd.bins.map(x => x.first_innings) }, { name: '2nd innings', color: PALETTE[1], values: sd.bins.map(x => x.second_innings) }]} xLabel="Innings total" yLabel="Innings" />}
    </>
  );
}

/* ---------------------------------------------------------------- toss */

function Toss({ d }) {
  const t = d.toss;
  return (
    <>
      <div className={`panel flex items-start gap-3 border-l-2 p-4 ${t.verdict_tone === 'neutral' ? 'border-l-slate-500' : t.verdict_tone === 'pos' ? 'border-l-pos' : 'border-l-neg'}`}>
        <div className="min-w-0">
          <div className="eyebrow mb-1">Does the toss matter here?</div>
          <p className="text-[15px] font-medium leading-relaxed text-slate-100">{t.verdict}</p>
          <p className="mt-1 text-2xs text-slate-500">{t.method}</p>
        </div>
      </div>
      <KpiGrid items={[
        { label: 'Tosses recorded', value: fmtInt(t.tosses), sub: `${t.decided_after_toss} decided matches` },
        { label: 'Chose to bat', value: fmtPct(t.chose_bat.chosen_percentage), sub: `${t.chose_bat.chosen} tosses` },
        { label: 'Chose to field', value: fmtPct(t.chose_field.chosen_percentage), sub: `${t.chose_field.chosen} tosses` },
        { label: 'Toss winner won', value: fmtPct(t.toss_winner.value), sub: `${t.toss_winner_won}/${t.decided_after_toss} · ${pfmt(t.p_value)}`, highlight: true },
        { label: `${t.label_first} won`, value: fmtInt(t.batting_first_wins), sub: fmtPct(t.batting_first.value) },
        { label: `${t.label_second} won`, value: fmtInt(t.chasing_wins), sub: fmtPct(t.chasing.value) },
      ]} />
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="panel space-y-5 p-4">
          <h3 className="text-[13px] font-semibold text-slate-100">Win % after the toss decision</h3>
          <CiBar label="Toss winner chose to bat → won" p={t.chose_bat.win} color={PALETTE[0]} sub={pfmt(t.chose_bat.p_value)} />
          <CiBar label="Toss winner chose to field → won" p={t.chose_field.win} color={PALETTE[1]} sub={pfmt(t.chose_field.p_value)} />
          <CiBar label="Toss winner won (any decision)" p={t.toss_winner} color={PALETTE[2]} sub={pfmt(t.p_value)} />
          <p className="text-2xs text-slate-500">Bars show the point estimate, shaded 95% interval and the 50% line. An interval that crosses 50% means no reliable advantage.</p>
        </div>
        <div className="panel space-y-5 p-4">
          <h3 className="text-[13px] font-semibold text-slate-100">Toss winner vs match winner</h3>
          <StackedBar className="!border-0 !p-0" percent rows={[
            { label: 'Toss decision', segments: [{ name: 'Bat', value: t.chose_bat.chosen, color: PALETTE[0] }, { name: 'Field', value: t.chose_field.chosen, color: PALETTE[1] }] },
            { label: 'Match result (decided)', segments: [{ name: `${t.label_first} won`, value: t.batting_first_wins, color: PALETTE[0] }, { name: `${t.label_second} won`, value: t.chasing_wins, color: PALETTE[1] }] },
            { label: 'Toss winner…', segments: [{ name: 'won the match', value: t.toss_winner_won, color: PALETTE[2] }, { name: 'lost the match', value: t.decided_after_toss - t.toss_winner_won, color: 'var(--chart-dim)' }] },
          ]} />
          {t.alignment && (
            <Callout tone={t.alignment.aligned ? 'info' : 'warn'}>
              Results here favour teams that {t.alignment.favoured_by_results === 'bat' ? 'bat first' : 'chase'}; captains most often choose to {t.alignment.most_chosen}.{' '}
              {t.alignment.aligned ? 'Toss decisions are aligned with the historical outcome.' : 'The popular decision runs against the historical outcome.'}
              {isNum(t.batting_first_p_value) && t.batting_first_p_value >= 0.05 && ' (The batting-order lean itself is not statistically significant.)'}
            </Callout>
          )}
        </div>
      </div>
    </>
  );
}

/* ---------------------------------------------------------- bat first / chase */

function BatFirstChase({ d }) {
  const x = d.batting_first_vs_chasing, bf = x.batting_first, ch = x.chasing;
  return (
    <>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Batting first" eyebrow="Setting a target">
          <CiBar label="Win % batting first" p={bf.win} color={PALETTE[0]} />
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Mini label="Average score" value={fmtDec(bf.average_score, 1)} sub={`n=${bf.sample}`} />
            <Mini label="Median score" value={fmtDec(bf.median_score, 0)} />
            <Mini label="Successful defences" value={fmtInt(bf.successful_defences)} />
            <Mini label="Avg winning total" value={fmtDec(bf.average_winning_total, 1)} sub={`n=${bf.winning_sample}`} />
            <Mini label="Avg losing total" value={fmtDec(bf.average_losing_total, 1)} sub={`n=${bf.losing_sample}`} />
            <Mini label="Lowest defended" value={d.overview.lowest_defended_total != null ? <MatchLink id={d.overview.lowest_defended_total_match_id}>{d.overview.lowest_defended_total}</MatchLink> : DASH} />
          </div>
        </Panel>
        <Panel title="Chasing" eyebrow="Pursuing a target">
          <CiBar label="Successful chase %" p={withUnit(ch.success, 'chases')} color={PALETTE[1]} />
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Mini label="Average 2nd-inns score" value={fmtDec(ch.average_score, 1)} sub={`n=${ch.sample}`} />
            <Mini label="Avg target chased" value={fmtDec(ch.average_successful_target, 1)} />
            <Mini label="Highest chase" value={ch.highest_successful_chase != null ? <MatchLink id={ch.highest_successful_chase_match_id}>{ch.highest_successful_chase}</MatchLink> : DASH} sub={ch.highest_target_chased ? `target ${ch.highest_target_chased}` : null} />
            <Mini label="Lowest chase" value={ch.lowest_successful_chase != null ? <MatchLink id={ch.lowest_successful_chase_match_id}>{ch.lowest_successful_chase}</MatchLink> : DASH} />
            <Mini label="Wickets in hand" value={fmtDec(ch.average_wickets_in_hand, 1)} sub="avg in wins" />
            <Mini label="Balls to spare" value={fmtDec(ch.average_balls_remaining, 1)} sub="avg in wins" />
          </div>
        </Panel>
      </div>
      <ColumnChart title="Par-score curve" subtitle="Bars: matches by first-innings score band. Line: how often the side batting first won from that score."
        data={x.par_curve.map(p => ({ label: p.label, value: p.matches, line: p.batting_first_win_percentage }))} barLabel="Matches" lineLabel="Bat-first win %"
        yLabel="Matches" y2Label="Win %" formatter={v => fmtInt(v)} lineFormatter={v => `${Math.round(v)}%`} color={PALETTE[6]} lineColor={PALETTE[0]} sample={bf.sample} sampleUnit="matches" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Histogram title="Wickets in hand in successful chases" bins={ch.wickets_in_hand_distribution.map(w => ({ label: String(w.wickets), count: w.chases }))} xLabel="Wickets remaining" yLabel="Chases" color={PALETTE[1]} sample={ch.success.k} sampleUnit="chases" />
        <Histogram title="When successful chases finish" subtitle="Over in which the winning run came." bins={ch.completion_over_distribution.map(w => ({ label: w.label, count: w.chases }))} xLabel="Overs" yLabel="Chases" color={PALETTE[3]} sample={ch.success.k} sampleUnit="chases" />
      </div>
      <Histogram title="Score distribution: first vs second innings" subtitle={`Complete innings, bin width ${x.score_distribution.bin_width} runs.`} bins={x.score_distribution.bins}
        series={[{ name: '1st innings', color: PALETTE[0], values: x.score_distribution.bins.map(b => b.first_innings) }, { name: '2nd innings', color: PALETTE[1], values: x.score_distribution.bins.map(b => b.second_innings) }]} xLabel="Innings total" yLabel="Innings" />
      <p className="text-2xs text-slate-500">{x.note}</p>
    </>
  );
}

function Mini({ label, value, sub }) {
  return <div className="rounded-lg border border-line bg-surface-sunken/60 px-3 py-2"><div className="truncate text-3xs uppercase tracking-wide text-slate-500">{label}</div><div className="num mt-0.5 text-base font-semibold text-slate-100">{value}</div>{sub && <div className="truncate text-3xs text-slate-500">{sub}</div>}</div>;
}

/* ---------------------------------------------------------------- conditions */

function Conditions({ d }) {
  const c = d.conditions, m = c.measured, inf = c.inferred;
  const measuredRows = [
    ['Runs per over', m.run_rate, m.baseline_run_rate, v => fmtDec(v), true],
    ['Wickets per innings', m.wickets_per_innings, m.baseline_wickets_per_innings, v => fmtDec(v), true],
    ['Boundary % of balls', m.boundary_percentage, m.baseline_boundary_percentage, v => fmtPct(v), true],
    ['Sixes per innings', m.sixes_per_innings, m.baseline_sixes_per_innings, v => fmtDec(v), true],
    ['Fours per innings', m.fours_per_innings, null, v => fmtDec(v), true],
    ['Balls per six', m.balls_per_six, null, v => fmtDec(v, 1), true],
    ['Dot-ball %', m.dot_percentage, null, v => fmtPct(v), true],
    ['Runs per wicket', m.runs_per_wicket, null, v => fmtDec(v), true],
  ];
  const phases = c.phases || [];
  return (
    <>
      <div className="grid gap-4 lg:grid-cols-5">
        <Panel className="lg:col-span-3" eyebrow="Measured" title="Scoring conditions" subtitle={`From ${fmtInt(m.balls)} legal balls across ${m.innings} innings. Δ = difference from the format baseline (all venues, same filters).`}>
          <table className="w-full text-[13px]">
            <thead><tr className="text-left text-3xs uppercase tracking-wide text-slate-500"><th className="py-1.5 font-medium">Metric</th><th className="text-right font-medium">Venue (Δ)</th><th className="text-right font-medium">Format</th></tr></thead>
            <tbody>{measuredRows.map(([l, v, bl, f, neutral]) => (
              <tr key={l} className="border-t border-line-soft"><td className="py-2 text-slate-300">{l}</td><td className="text-right"><BaselineDelta value={v} baseline={bl} format={f} neutral={neutral} /></td><td className="num text-right text-slate-500">{isNum(bl) ? f(bl) : DASH}</td></tr>
            ))}</tbody>
          </table>
        </Panel>
        <section className="panel relative overflow-hidden p-4 lg:col-span-2" style={{ backgroundImage: 'repeating-linear-gradient(135deg, rgba(255,255,255,0.012) 0 8px, transparent 8px 16px)' }}>
          <div className="mb-2 flex items-center justify-between"><span className="eyebrow text-warn-soft/90">Inferred · not measured</span><Badge variant={inf.confidence === 'high' ? 'green' : inf.confidence === 'moderate' ? 'amber' : 'red'}>{inf.confidence} confidence</Badge></div>
          <h3 className="text-[13px] font-semibold text-slate-100">Playing tendencies</h3>
          {inf.tags.length ? (
            <ul className="mt-3 space-y-3">{inf.tags.map(t => (
              <li key={t.tag}><span className={`inline-flex rounded-md border px-2 py-0.5 text-xs font-medium ${t.tone === 'bat' ? 'border-pos/30 text-pos-soft' : t.tone === 'bowl' ? 'border-electric/30 text-electric-soft' : 'border-line-strong text-slate-300'}`}>{t.tag}</span><p className="mt-1 text-2xs leading-relaxed text-slate-400">{t.evidence}</p></li>
            ))}</ul>
          ) : <p className="mt-3 text-sm text-slate-500">Nothing stands out from the format baseline.</p>}
          <p className="mt-4 border-t border-line-soft pt-3 text-2xs leading-relaxed text-slate-500">{inf.disclaimer}</p>
        </section>
      </div>
      {d.limited_overs && phases.length > 0 ? (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <GroupedBarChart title="Phase scoring rate" subtitle="Runs per over by phase in each innings vs the format baseline." categories={['powerplay', 'middle', 'death'].map(p => PHASE[p])} formatter={v => fmtDec(v, 1)} yLabel="Runs per over"
              series={[{ name: '1st innings', color: PALETTE[0], values: ['powerplay', 'middle', 'death'].map(p => phases.find(x => x.phase === p && x.innings === 1)?.run_rate) },
                { name: '2nd innings', color: PALETTE[1], values: ['powerplay', 'middle', 'death'].map(p => phases.find(x => x.phase === p && x.innings === 2)?.run_rate) },
                { name: 'Format', color: 'var(--chart-muted)', values: ['powerplay', 'middle', 'death'].map(p => phases.find(x => x.phase === p)?.baseline_run_rate) }]} />
            <GroupedBarChart title="Wickets by phase" subtitle="Average wickets falling in each phase per innings." categories={['powerplay', 'middle', 'death'].map(p => PHASE[p])} formatter={v => fmtDec(v, 2)} yLabel="Wickets"
              series={[1, 2].map(n => ({ name: `${n === 1 ? '1st' : '2nd'} innings`, color: n === 1 ? PALETTE[0] : PALETTE[1], values: ['powerplay', 'middle', 'death'].map(p => phases.find(x => x.phase === p && x.innings === n)?.wickets_per_innings) }))} />
          </div>
          <Panel title="Phase detail" bodyClassName="p-3">
            <DataTable dense pageSize={0} rows={phases} rowKey={p => `${p.phase}-${p.innings}`} columns={[
              { key: 'phase', label: 'Phase', render: p => PHASE[p.phase] }, { key: 'innings', label: 'Innings', align: 'right' }, { key: 'sample', label: 'n', align: 'right' },
              { key: 'average_runs', label: 'Avg runs', align: 'right', render: p => fmtDec(p.average_runs, 1) },
              { key: 'run_rate', label: 'RPO (Δ format)', align: 'right', render: p => <BaselineDelta value={p.run_rate} baseline={p.baseline_run_rate} neutral /> },
              { key: 'wickets_per_innings', label: 'Wkts/inn', align: 'right', render: p => fmtDec(p.wickets_per_innings) },
              { key: 'boundary_percentage', label: 'Bnd %', align: 'right', render: p => fmtPct(p.boundary_percentage) },
            ]} />
          </Panel>
        </>
      ) : <Unavailable title="Phase scoring" reason="Powerplay/middle/death phases exist only for limited-overs formats." />}
      <div className="grid gap-4 lg:grid-cols-2">
        <PaceSpin ps={c.pace_spin} title="Pace vs spin effectiveness" />
        <Panel title="Innings-by-innings scoring" subtitle="How scoring changes as the match progresses (complete innings)." bodyClassName="p-3">
          <DataTable dense pageSize={0} rows={c.by_innings} rowKey={r => r.innings} columns={[
            { key: 'innings', label: 'Innings', render: r => `Innings ${r.innings}` }, { key: 'sample', label: 'n', align: 'right' },
            { key: 'average_score', label: 'Avg score', align: 'right', render: r => fmtDec(r.average_score, 1) },
            { key: 'run_rate', label: 'RPO', align: 'right', render: r => fmtDec(r.run_rate) },
            { key: 'wickets_per_innings', label: 'Wkts/inn', align: 'right', render: r => fmtDec(r.wickets_per_innings) },
          ]} />
        </Panel>
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- trends */

function Trends({ d, search }) {
  const t = d.trends, sb = t.scoring_bands;
  return (
    <>
      <div className="grid gap-4 lg:grid-cols-2">
        <MultiSeriesLine categorical title="Historical scoring trend" subtitle="Average complete-innings score by season." height={250} xLabel="Season" yLabel="Runs" yFormatter={v => fmtDec(v, 0)}
          series={[{ name: '1st innings', color: PALETTE[0], points: t.seasons.map(s => ({ x: s.season, y: s.average_first_innings })) }, { name: '2nd innings', color: PALETTE[1], points: t.seasons.map(s => ({ x: s.season, y: s.average_second_innings })) }]} />
        <ColumnChart title="Results by season" subtitle={`Bars: matches. Line: ${d.limited_overs ? 'batting-first' : 'innings-1 side'} win %.`} data={t.seasons.map(s => ({ label: s.season, value: s.matches, line: s.batting_first_win_percentage }))}
          barLabel="Matches" lineLabel="Bat-first win %" formatter={v => fmtInt(v)} lineFormatter={v => `${Math.round(v)}%`} color={PALETTE[6]} lineColor={PALETTE[0]} yLabel="Matches" y2Label="Win %" />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="panel space-y-5 p-4">
          <h3 className="text-[13px] font-semibold text-slate-100">High- and low-scoring matches</h3>
          <CiBar label={`First innings ≥ ${sb.high_threshold ?? DASH}`} p={sb.high_scoring} color={PALETTE[2]} reference={25} sub="typical venue ≈25%" />
          <CiBar label={`First innings ≤ ${sb.low_threshold ?? DASH}`} p={sb.low_scoring} color={PALETTE[3]} reference={25} sub="typical venue ≈25%" />
          <p className="text-2xs text-slate-500">{sb.note}</p>
        </div>
        <ColumnChart className="lg:col-span-2" title="Seasonal (calendar month) differences" subtitle="Bars: matches. Line: average first-innings score in that month."
          data={t.months.map(m => ({ label: m.month, value: m.matches, line: m.average_first_innings }))} barLabel="Matches" lineLabel="Avg 1st inns" formatter={v => fmtInt(v)} lineFormatter={v => fmtDec(v, 0)} color={PALETTE[6]} lineColor={PALETTE[2]} yLabel="Matches" y2Label="Runs" />
      </div>
      <Unavailable title="Day vs night matches" reason={t.day_night.reason} />
      <Panel title="Recent venue form" subtitle={t.recent_summary ? `Last ${t.recent.length} matches: avg 1st innings ${fmtDec(t.recent_summary.average_first_innings, 1)} vs ${fmtDec(t.overall_summary.average_first_innings, 1)} overall; batting first won ${fmtPct(t.recent_summary.batting_first_win_percentage)} (n=${t.recent_summary.decided}).` : null} bodyClassName="p-3">
        <DataTable dense pageSize={0} rows={t.recent} rowKey={r => r.match_id} rowHref={r => matchUrl(r.match_id)} rowLabel={r => `Open match ${r.team1} v ${r.team2}, ${r.date}`} columns={[
          { key: 'date', label: 'Date', render: r => <MatchLink id={r.match_id} className="text-slate-100">{r.date}</MatchLink> }, { key: 'teams', label: 'Match', sortable: false, render: r => `${r.team1} v ${r.team2}` },
          { key: 'first_innings', label: '1st inns', align: 'right' }, { key: 'second_innings', label: '2nd inns', align: 'right' },
          { key: 'winner', label: 'Winner', render: r => r.winner ? <span>{r.winner} <span className="text-slate-500">{r.margin}</span></span> : <span className="text-slate-500">{r.margin ?? DASH}</span> },
          { key: 'batting_first_won', label: 'Won by', render: r => (r.batting_first_won === null ? DASH : r.batting_first_won ? <Badge variant="indigo">bat first</Badge> : <Badge variant="green">chasing</Badge>) },
          { key: 'match_id', label: '', sortable: false, render: r => <MatchLink id={r.match_id} className="text-2xs text-slate-500">Scorecard →</MatchLink> },
        ]} />
      </Panel>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Highest totals" bodyClassName="p-3"><TotalsTable rows={t.highest_totals} /></Panel>
        <Panel title="Lowest completed totals" subtitle="All out or full quota, complete matches." bodyClassName="p-3"><TotalsTable rows={t.lowest_totals} /></Panel>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Team records at this venue" bodyClassName="p-3">
          <DataTable dense pageSize={10} rows={t.teams} rowKey={r => r.team_id} searchKeys={['team']} searchPlaceholder="Search teams…" initialSort={{ key: 'matches', dir: 'desc' }} columns={[
            { key: 'team', label: 'Team', render: r => <Link className="text-slate-100 hover:text-accent-soft" to={`/teams/${r.team_id}${search}`}>{r.team}</Link> },
            { key: 'matches', label: 'M', align: 'right' }, { key: 'won', label: 'W', align: 'right' }, { key: 'lost', label: 'L', align: 'right' },
            { key: 'win_percentage', label: 'Win %', align: 'right', render: r => <span className="inline-flex items-center gap-1.5">{fmtPct(r.win_percentage)}{r.won + r.lost < 10 && <SampleBadge n={r.won + r.lost} unit="dec." />}</span> },
            { key: 'average_score', label: 'Avg score', align: 'right', render: r => fmtDec(r.average_score, 1) },
          ]} />
        </Panel>
        <Panel title="Competition-specific trends" bodyClassName="p-3">
          <DataTable dense pageSize={10} rows={t.competitions} rowKey={r => r.competition} initialSort={{ key: 'matches', dir: 'desc' }} columns={[
            { key: 'competition', label: 'Competition', render: r => <span className="block max-w-[14rem] truncate" title={r.competition}>{r.competition}</span> },
            { key: 'matches', label: 'M', align: 'right' },
            { key: 'average_first_innings', label: 'Avg 1st', align: 'right', render: r => fmtDec(r.average_first_innings, 1) },
            { key: 'run_rate', label: 'RPO', align: 'right', render: r => fmtDec(r.run_rate) },
            { key: 'batting_first_win_percentage', label: 'Bat 1st W%', align: 'right', render: r => fmtPct(r.batting_first_win_percentage) },
          ]} />
        </Panel>
      </div>
    </>
  );
}

function TotalsTable({ rows }) {
  return (
    <DataTable dense pageSize={0} rows={rows} rowKey={(r, i) => `${r.match_id}-${r.innings}-${i}`} columns={[
      { key: 'runs', label: 'Total', align: 'right', render: r => <MatchLink id={r.match_id} className="font-semibold text-slate-100">{r.runs}{r.wickets < 10 ? `/${r.wickets}` : ''}</MatchLink> },
      { key: 'team', label: 'Team' }, { key: 'opponent', label: 'v' }, { key: 'innings', label: 'Inns', align: 'right' }, { key: 'date', label: 'Date', align: 'right' },
    ]} />
  );
}
