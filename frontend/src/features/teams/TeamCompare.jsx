/**
 * Two-team comparison across identical metrics and scope, plus head-to-head.
 * Data: GET /competition/teams (pickers) and GET /competition/teams/compare.
 */
import { matchUrl } from '../../components/MatchLink';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { compareTeams, getTeamDirectory } from '../../services/api';
import { DashboardSkeleton, DataTable, EmptyState, ErrorState, MatchLink, PageHeader, Panel, SampleBadge } from '../../components/ui';
import { GroupedBarChart, PALETTE } from '../../components/charts';
import { DASH, fmtDec, fmtPct } from '../../lib/format';
import { BackLink, CiBar, EntityPicker, FormStrip, InsightList, ScopeFilters, VersusRow, isNum, recordLine, resultLabel, useScope, useScopeSearch } from '../competition/shared';

const A = PALETTE[0], B = PALETTE[1];
const PHASE = { powerplay: 'Powerplay', middle: 'Middle', death: 'Death' };

export default function TeamCompare() {
  const scope = useScope({ a: '', b: '' });
  const search = useScopeSearch(['a', 'b']);
  const { a, b } = scope.filters;
  const [teams, setTeams] = useState([]);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => { getTeamDirectory(scope.params).then(r => setTeams(r.teams.map(t => ({ id: t.team_id, name: t.team, matches: t.matches })))).catch(() => setTeams([])); }, [scope.key]); // eslint-disable-line react-hooks/exhaustive-deps
  const load = () => {
    if (!a || !b || a === b) { setData(null); return; }
    setLoading(true); setError(null);
    compareTeams(a, b, scope.params).then(setData).catch(e => setError(e.message)).finally(() => setLoading(false));
  };
  useEffect(load, [a, b, scope.key]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div>
      <BackLink to={`/teams${search}`}>All teams</BackLink>
      <PageHeader eyebrow="Team Analytics" title="Compare teams" subtitle="Two teams, the same scope, the same metrics — plus their head-to-head record." />
      <ScopeFilters scope={scope}>
        <EntityPicker label="Team A" items={teams} value={a} onChange={v => scope.setFilter('a', v)} labelOf={t => `${t.name} (${t.matches})`} />
        <EntityPicker label="Team B" items={teams.filter(t => t.id !== a)} value={b} onChange={v => scope.setFilter('b', v)} labelOf={t => `${t.name} (${t.matches})`} />
      </ScopeFilters>
      {(!a || !b) && <div className="panel"><EmptyState icon="compare" message="Choose two teams to compare." hint="Both teams are measured under the same format and filters, so every number is like-for-like." /></div>}
      {loading && <DashboardSkeleton />}
      {error && <ErrorState message={error} onRetry={load} />}
      {data && !loading && !error && <Comparison d={data} search={search} />}
    </div>
  );
}

function Comparison({ d, search }) {
  const { a, b } = d, h2h = d.head_to_head;
  const lim = a.limited_overs;
  const rows = useMemo(() => {
    const r = [
      ['Results', [
        ['Matches', x => x.overview.record.matches, v => v, null],
        ['Win %', x => x.overview.record.win_percentage, fmtPct, 'high', x => `n=${x.overview.record.decided}`],
        ['Home win %', x => x.home_away.sides.home.record.win_percentage, fmtPct, 'high', x => `n=${x.home_away.sides.home.record.decided}`],
        ['Away win %', x => x.home_away.sides.away.record.win_percentage, fmtPct, 'high', x => `n=${x.home_away.sides.away.record.decided}`],
        lim && ['Bat-first win %', x => x.situations.order.batting_first.win_percentage, fmtPct, 'high'],
        lim && ['Chasing win %', x => x.situations.order.chasing.win_percentage, fmtPct, 'high'],
        lim && ['Close-match win %', x => x.situations.close.record.win_percentage, fmtPct, 'high'],
      ]],
      ['Batting', [
        ['Avg score', x => x.batting.overall.average_score, v => fmtDec(v, 1), 'high'],
        ['Run rate', x => x.batting.overall.run_rate, fmtDec, 'high'],
        ['Runs per wicket', x => x.batting.overall.runs_per_wicket, fmtDec, 'high'],
        ['Boundary %', x => x.batting.overall.boundary_percentage, fmtPct, 'high'],
        ['Dot %', x => x.batting.overall.dot_percentage, fmtPct, 'low'],
        ['Highest total', x => x.batting.overall.highest, v => v, 'high'],
      ]],
      ['Bowling', [
        ['Economy', x => x.bowling.overall.run_rate, fmtDec, 'low'],
        ['Wickets / innings', x => x.bowling.overall.wickets_per_innings, fmtDec, 'high'],
        ['Strike rate', x => x.bowling.overall.balls_per_wicket, v => fmtDec(v, 1), 'low'],
        ['Bowling avg', x => x.bowling.overall.runs_per_wicket, fmtDec, 'low'],
        ['Scoring suppression %', x => x.bowling.suppression.suppression_percentage, v => `${v > 0 ? '+' : ''}${fmtDec(v, 1)}`, 'high'],
        ['Spin economy', x => x.bowling.pace_spin.styles.find(s => s.style === 'spin')?.economy, fmtDec, 'low'],
        ['Pace economy', x => x.bowling.pace_spin.styles.find(s => s.style === 'pace')?.economy, fmtDec, 'low'],
      ]],
    ];
    return r.map(([g, items]) => [g, items.filter(Boolean)]);
  }, [lim]);
  return (
    <div className="space-y-5 animate-fade-in">
      <div className="grid gap-4 md:grid-cols-2">
        {[[a, A], [b, B]].map(([t, c]) => (
          <div key={t.team.id} className="panel relative overflow-hidden p-5">
            <span className="absolute inset-x-0 top-0 h-0.5" style={{ backgroundColor: c }} />
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0"><Link to={`/teams/${t.team.id}${search}`} className="text-lg font-semibold text-white hover:text-accent-soft">{t.team.name}</Link><p className="mt-0.5 text-2xs text-slate-500">{recordLine(t.overview.record)}</p></div>
              <FormStrip items={t.form.last10.slice(0, 5).map(r => ({ result: r.result, match_id: r.match_id, label: `${resultLabel(r.result)} v ${r.opponent}, ${r.date}` }))} size="sm" />
            </div>
            <div className="mt-4"><CiBar label="Win %" p={t.overview.record.win} color={c} /></div>
          </div>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-5">
        <Panel className="lg:col-span-3" title="Tale of the tape" subtitle="Brighter bar = better value for that metric.">
          <div className="mb-1 grid grid-cols-[1fr_auto_1fr] text-3xs"><span className="truncate text-right" style={{ color: A }}>{a.team.name}</span><span className="w-32 sm:w-40" /><span className="truncate" style={{ color: B }}>{b.team.name}</span></div>
          {rows.map(([group, items]) => (
            <div key={group} className="border-t border-line-soft pt-2 first:border-0">
              <div className="eyebrow mb-1 mt-1 text-center">{group}</div>
              {items.map(([label, get, f, better, sub]) => <VersusRow key={label} label={label} a={get(a)} b={get(b)} format={f} better={better} aColor={A} bColor={B} sub={sub ? `${sub(a)} · ${sub(b)}` : null} />)}
            </div>
          ))}
        </Panel>
        <GroupedBarChart className="lg:col-span-2" title="Win % by situation" subtitle="Decided matches only; 50% = break-even." formatter={v => `${Math.round(v)}%`} yLabel="Win %"
          categories={lim ? ['Overall', 'Home', 'Away', 'Bat 1st', 'Chasing', 'Close'] : ['Overall', 'Home', 'Away']}
          series={[a, b].map((t, i) => ({ name: t.team.name, color: i ? B : A, values: [t.overview.record.win_percentage, t.home_away.sides.home.record.win_percentage, t.home_away.sides.away.record.win_percentage,
            ...(lim ? [t.situations.order.batting_first.win_percentage, t.situations.order.chasing.win_percentage, t.situations.close.record.win_percentage] : [])] }))} height={300} />
      </div>
      {lim && a.batting.phases && b.batting.phases && (
        <div className="grid gap-4 lg:grid-cols-2">
          <GroupedBarChart title="Batting run rate by phase" categories={a.batting.phases.map(p => PHASE[p.phase])} formatter={v => fmtDec(v, 1)} yLabel="Runs per over"
            series={[{ name: a.team.name, color: A, values: a.batting.phases.map(p => p.run_rate) }, { name: b.team.name, color: B, values: b.batting.phases.map(p => p.run_rate) }, { name: 'Format', color: 'var(--chart-muted)', values: a.batting.phases.map(p => p.baseline_run_rate) }]} />
          <GroupedBarChart title="Runs conceded per over by phase" subtitle="Lower is better." categories={a.bowling.phases.map(p => PHASE[p.phase])} formatter={v => fmtDec(v, 1)} yLabel="Runs per over"
            series={[{ name: a.team.name, color: A, values: a.bowling.phases.map(p => p.run_rate) }, { name: b.team.name, color: B, values: b.bowling.phases.map(p => p.run_rate) }, { name: 'Format', color: 'var(--chart-muted)', values: a.bowling.phases.map(p => p.baseline_run_rate) }]} />
        </div>
      )}
      <GroupedBarChart title="Home vs away win %" subtitle="Evidence-based classification; unclassified matches excluded." categories={['Home', 'Away', 'Neutral']} formatter={v => `${Math.round(v)}%`} yLabel="Win %"
        series={[a, b].map((t, i) => ({ name: t.team.name, color: i ? B : A, values: ['home', 'away', 'neutral'].map(s => t.home_away.sides[s].record.win_percentage) }))}
        footnote={`Decided samples — ${a.team.name}: ${['home', 'away', 'neutral'].map(s => a.home_away.sides[s].record.decided).join(' / ')}; ${b.team.name}: ${['home', 'away', 'neutral'].map(s => b.home_away.sides[s].record.decided).join(' / ')}.`} />
      <Panel title="Head-to-head" subtitle="Matches between the two teams under the selected filters." actions={<SampleBadge n={h2h.matches} />}>
        {!h2h.matches ? <p className="text-sm text-slate-500">These teams have not met under the selected filters.</p> : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-6">
              <div className="num text-3xl font-semibold"><span style={{ color: A }}>{h2h.a.won}</span><span className="mx-2 text-slate-600">–</span><span style={{ color: B }}>{h2h.b.won}</span></div>
              <div className="text-2xs text-slate-500">{[h2h.a.tied && `${h2h.a.tied} tied`, h2h.a.drawn && `${h2h.a.drawn} drawn`, h2h.a.no_result && `${h2h.a.no_result} no result`].filter(Boolean).join(' · ') || 'No ties, draws or no-results'}</div>
              <div className="min-w-[12rem] flex-1">
                <div className="chart-hbar flex h-2.5 overflow-hidden rounded-full bg-slate-800">{h2h.a.decided > 0 && <><span style={{ width: `${h2h.a.won / h2h.a.decided * 100}%`, backgroundColor: A }} /><span style={{ width: `${h2h.b.won / h2h.a.decided * 100}%`, backgroundColor: B }} /></>}</div>
              </div>
            </div>
            <InsightList items={[
              { tone: 'neutral', text: `${a.team.name} average ${fmtDec(h2h.a_batting.average_score, 1)} (RPO ${fmtDec(h2h.a_batting.run_rate)}) in this fixture; ${b.team.name} ${fmtDec(h2h.b_batting.average_score, 1)} (RPO ${fmtDec(h2h.b_batting.run_rate)}).` },
              h2h.a.decided < 10 && { tone: 'neutral', text: `Only ${h2h.a.decided} decided meetings — head-to-head records this small are weak evidence of a matchup edge.` },
            ].filter(Boolean)} />
            <DataTable dense pageSize={0} rows={h2h.recent} rowKey={r => r.match_id} rowHref={r => matchUrl(r.match_id)} rowLabel={r => `Open match, ${r.date}`} columns={[
              { key: 'date', label: 'Date', render: r => <MatchLink id={r.match_id} className="text-slate-100">{r.date}</MatchLink> },
              { key: 'result', label: `${a.team.name}`, render: r => <span className={r.result === 'won' ? 'text-pos' : r.result === 'lost' ? 'text-neg' : 'text-slate-400'}>{resultLabel(r.result)}</span> },
              { key: 'score', label: 'Score', render: r => <span className="num">{r.score ?? DASH} <span className="text-slate-500">v</span> {r.opponent_score ?? DASH}</span> },
              { key: 'margin', label: 'Margin', render: r => r.margin ?? DASH },
              { key: 'venue', label: 'Venue', render: r => (r.venue_id ? <Link className="hover:text-accent-soft" to={`/venues/${r.venue_id}${search}`}>{r.venue}</Link> : r.venue) },
              { key: 'match_id', label: '', sortable: false, render: r => <MatchLink id={r.match_id} className="text-2xs text-slate-500">Scorecard →</MatchLink> },
            ]} />
          </div>
        )}
      </Panel>
      <div className="grid gap-4 md:grid-cols-2">
        {[a, b].map(t => <Panel key={t.team.id} title={`${t.team.name} — key findings`}><InsightList items={t.insights} /></Panel>)}
      </div>
      {!isNum(a.overview.record.win_percentage) && <p className="text-2xs text-slate-500">Some metrics are blank because a team has no decided matches in this scope.</p>}
    </div>
  );
}
