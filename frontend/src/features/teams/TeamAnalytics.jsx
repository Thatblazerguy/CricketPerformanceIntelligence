/**
 * Team Analytics hub: every team in the selected scope, ranked and plotted,
 * with entry points to individual profiles and two-team comparison.
 * Data: GET /competition/teams (backend/app/analytics/team_analytics.py).
 */
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getTeamDirectory } from '../../services/api';
import { Button, DashboardSkeleton, MatchLink, DataTable, EmptyState, ErrorState, MetricStrip, PageHeader, Panel, SampleBadge, Segmented } from '../../components/ui';
import { BarChart, PALETTE, ScatterChart } from '../../components/charts';
import { DASH, fmtDec, fmtInt, fmtPct } from '../../lib/format';
import { FormStrip, ScopeFilters, isNum, useScope, useScopeSearch } from '../competition/shared';

export default function TeamAnalytics() {
  const scope = useScope();
  const search = useScopeSearch();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [minDecided, setMinDecided] = useState('10');
  const [picked, setPicked] = useState([]);

  const load = () => {
    setLoading(true); setError(null);
    getTeamDirectory(scope.params).then(setData).catch(e => setError(e.message)).finally(() => setLoading(false));
  };
  useEffect(load, [scope.key]); // eslint-disable-line react-hooks/exhaustive-deps

  const teams = data?.teams || [];
  const eligible = useMemo(() => teams.filter(t => t.decided >= Number(minDecided)), [teams, minDecided]);
  const totalMatches = useMemo(() => Math.round(teams.reduce((a, t) => a + t.matches, 0) / 2), [teams]);
  const limited = ['T20', 'T20I', 'ODI', 'ODM'].includes(scope.filters.format);
  const togglePick = id => setPicked(p => (p.includes(id) ? p.filter(x => x !== id) : [...p.slice(-1), id]));
  const open = id => navigate(`/teams/${id}${search}`);

  return (
    <div>
      <PageHeader eyebrow="Competitions" title="Team Analytics"
        subtitle="How well does each team perform, and under what conditions? Results, home and away, batting and bowling by phase, chasing and defending — all from match and ball-by-ball records."
        actions={<Button as={Link} to={`/teams/compare${search}`} icon="compare" variant="secondary" size="sm">Compare two teams</Button>} />
      <ScopeFilters scope={scope} note="Filters apply to every Team and Venue Analytics view and carry between them. Win % = wins ÷ (wins + losses)." />
      {loading && <DashboardSkeleton />}
      {error && <ErrorState message={error} onRetry={load} />}
      {!loading && !error && !teams.length && <div className="panel"><EmptyState message="No matches for this selection." hint="Try another format or widen the date range." /></div>}
      {!loading && !error && teams.length > 0 && (
        <div className="space-y-5 animate-fade-in">
          <MetricStrip items={[
            { label: 'Teams', value: fmtInt(teams.length) },
            { label: 'Matches', value: fmtInt(totalMatches) },
            { label: `Teams with ${minDecided}+ decided`, value: fmtInt(eligible.length) },
            { label: 'Best win %', value: eligible[0] ? fmtPct(Math.max(...eligible.map(t => t.win_percentage ?? 0))) : DASH, sub: eligible.length ? [...eligible].sort((a, b) => b.win_percentage - a.win_percentage)[0].team : null, tone: 'pos' },
            { label: 'Best net RPO', value: eligible.length ? fmtDec(Math.max(...eligible.filter(t => isNum(t.net_run_rate)).map(t => t.net_run_rate))) : DASH, sub: eligible.length ? [...eligible].filter(t => isNum(t.net_run_rate)).sort((a, b) => b.net_run_rate - a.net_run_rate)[0]?.team : null },
          ]} />
          <div className="grid gap-4 xl:grid-cols-5">
            <ScatterChart className="xl:col-span-3" title="Batting vs bowling quadrant"
              subtitle={`Each point is a team (${minDecided}+ decided matches). Right = scores faster; lower = concedes less. Bottom-right is the strongest quadrant. Click a point to open the profile.`}
              data={eligible.filter(t => isNum(t.run_rate) && isNum(t.economy)).map(t => ({ ...t, name: t.team, color: (t.win_percentage ?? 0) >= 55 ? PALETTE[1] : (t.win_percentage ?? 0) <= 45 ? PALETTE[5] : PALETTE[0],
                detail: `${t.matches} matches · win ${fmtPct(t.win_percentage)}`, highlight: picked.includes(t.team_id) }))}
              xKey="run_rate" yKey="economy" xLabel="Runs per over scored" yLabel="Runs per over conceded" formatX={v => Number(v).toFixed(1)} formatY={v => Number(v).toFixed(1)}
              onPointClick={r => open(r.team_id)} height={330}
              footnote="Colour: teal ≥55% wins, red ≤45%, indigo in between." />
            <BarChart className="xl:col-span-2" title="Win % leaders" subtitle={`Teams with ${minDecided}+ decided matches.`} limit={12}
              data={[...eligible].sort((a, b) => (b.win_percentage ?? -1) - (a.win_percentage ?? -1)).map(t => ({ label: t.team, value: t.win_percentage, detail: `${t.won}–${t.lost} (n=${t.decided})` }))}
              formatter={v => fmtPct(v)} unit="Win %" color={PALETTE[1]}
              actions={<Segmented size="xs" label="Minimum decided matches" value={minDecided} onChange={setMinDecided} options={[{ id: '5', label: '5+' }, { id: '10', label: '10+' }, { id: '30', label: '30+' }]} />} />
          </div>
          <Panel title="Team directory" subtitle="Select up to two rows to compare, or open a team for its full profile. Home/away columns count only matches with verified home/away evidence." bodyClassName="p-3"
            actions={picked.length === 2 && <Button size="sm" variant="primary" icon="compare" onClick={() => navigate(`/teams/compare${search}${search ? '&' : '?'}a=${picked[0]}&b=${picked[1]}`)}>Compare selected</Button>}>
            <DataTable dense pageSize={25} rows={teams} rowKey={r => r.team_id} searchKeys={['team']} searchPlaceholder="Search teams…" initialSort={{ key: 'matches', dir: 'desc' }}
              rowClassName={r => (picked.includes(r.team_id) ? 'bg-accent-muted/30' : '')} columns={[
                { key: 'pick', label: '', sortable: false, render: r => <input type="checkbox" aria-label={`Select ${r.team} for comparison`} checked={picked.includes(r.team_id)} onChange={() => togglePick(r.team_id)} /> },
                { key: 'team', label: 'Team', render: r => <Link to={`/teams/${r.team_id}${search}`} className="font-medium text-slate-100 hover:text-accent-soft">{r.team}</Link> },
                { key: 'matches', label: 'M', align: 'right' },
                { key: 'won', label: 'W', align: 'right' },
                { key: 'lost', label: 'L', align: 'right' },
                { key: 'other', label: 'T/D/NR', align: 'right', render: r => r.tied + r.drawn + r.no_result, title: 'Ties, draws and no-results' },
                { key: 'win_percentage', label: 'Win %', align: 'right', render: r => <span className="inline-flex items-center gap-1.5">{fmtPct(r.win_percentage)}{r.decided < 10 && <SampleBadge n={r.decided} unit="dec." />}</span> },
                { key: 'home_win_percentage', label: 'Home W%', align: 'right', render: r => (r.home_decided ? <span title={`n=${r.home_decided}`}>{fmtPct(r.home_win_percentage)}</span> : <span className="text-slate-600">{DASH}</span>) },
                { key: 'away_win_percentage', label: 'Away W%', align: 'right', render: r => (r.away_decided ? <span title={`n=${r.away_decided}`}>{fmtPct(r.away_win_percentage)}</span> : <span className="text-slate-600">{DASH}</span>) },
                limited && { key: 'batting_first_win_percentage', label: 'Bat 1st W%', align: 'right', render: r => fmtPct(r.batting_first_win_percentage) },
                limited && { key: 'chasing_win_percentage', label: 'Chase W%', align: 'right', render: r => fmtPct(r.chasing_win_percentage) },
                { key: 'run_rate', label: 'RPO', align: 'right', render: r => fmtDec(r.run_rate) },
                { key: 'economy', label: 'Conc.', align: 'right', render: r => fmtDec(r.economy), title: 'Runs per over conceded' },
                { key: 'net_run_rate', label: 'Net', align: 'right', render: r => <span className={r.net_run_rate > 0 ? 'text-pos' : r.net_run_rate < 0 ? 'text-neg' : ''}>{isNum(r.net_run_rate) ? `${r.net_run_rate > 0 ? '+' : ''}${fmtDec(r.net_run_rate)}` : DASH}</span>, title: 'Runs per over scored minus conceded' },
                { key: 'form', label: 'Last 5', sortable: false, render: r => <FormStrip items={r.form.map((x, i) => ({ result: x, match_id: r.form_match_ids?.[i] }))} size="sm" /> },
                { key: 'last_played', label: 'Last match', align: 'right', render: r => <MatchLink id={r.last_match_id}>{r.last_played}</MatchLink> },
              ].filter(Boolean)} />
          </Panel>
        </div>
      )}
    </div>
  );
}
