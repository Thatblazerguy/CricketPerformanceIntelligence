/**
 * Venue Analytics hub: a database of grounds in the selected scope with
 * scoring, toss and batting-order tendencies, and multi-venue comparison.
 * Data: GET /competition/venues (backend/app/analytics/venue_analytics.py).
 */
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getTeamDirectory, getVenueDirectory } from '../../services/api';
import { Button, DashboardSkeleton, MatchLink, DataTable, EmptyState, ErrorState, MetricStrip, PageHeader, Panel, SampleBadge, Segmented } from '../../components/ui';
import { BarChart, PALETTE, ScatterChart } from '../../components/charts';
import { DASH, fmtDec, fmtInt, fmtPct } from '../../lib/format';
import { EntityPicker, ScopeFilters, isNum, useScope, useScopeSearch } from '../competition/shared';

export default function VenueAnalytics() {
  const scope = useScope({ team: '' });
  const search = useScopeSearch();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [teams, setTeams] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [minMatches, setMinMatches] = useState('10');
  const [picked, setPicked] = useState([]);
  const limited = ['T20', 'T20I', 'ODI', 'ODM'].includes(scope.filters.format);

  const load = () => {
    setLoading(true); setError(null);
    getVenueDirectory({ ...scope.params, team_id: scope.filters.team }).then(setData).catch(e => setError(e.message)).finally(() => setLoading(false));
  };
  useEffect(load, [scope.key, scope.filters.team]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { getTeamDirectory(scope.params).then(r => setTeams(r.teams.map(t => ({ id: t.team_id, name: t.team, matches: t.matches })))).catch(() => setTeams([])); }, [scope.key]); // eslint-disable-line react-hooks/exhaustive-deps

  const venues = data?.venues || [];
  const eligible = useMemo(() => venues.filter(v => v.matches >= Number(minMatches)), [venues, minMatches]);
  const total = venues.reduce((a, v) => a + v.matches, 0);
  const pooled = (key, weight) => {
    const rows = venues.filter(v => isNum(v[key]) && v[weight]);
    const w = rows.reduce((a, v) => a + v[weight], 0);
    return w ? rows.reduce((a, v) => a + v[key] * v[weight], 0) / w : null;
  };
  const togglePick = id => setPicked(p => (p.includes(id) ? p.filter(x => x !== id) : p.length >= 4 ? p : [...p, id]));
  const profileLink = id => `/venues/${id}${search}`;

  return (
    <div>
      <PageHeader eyebrow="Competitions" title="Venue Analytics"
        subtitle="How does each ground influence the way cricket is played and won? Toss impact, batting first vs chasing, scoring conditions and trends — measured from match records, with inferred tendencies clearly labelled."
        actions={<Button as={Link} to={`/venues/compare${search}`} icon="compare" size="sm">Compare venues</Button>} />
      <ScopeFilters scope={scope} note="Team filter restricts every venue to matches involving that team. Percentages exclude ties, draws and no-results.">
        {teams.length > 0 && <EntityPicker label="Team" items={teams} value={scope.filters.team} onChange={v => scope.setFilter('team', v)} allowEmpty labelOf={t => `${t.name} (${t.matches})`} />}
      </ScopeFilters>
      {loading && <DashboardSkeleton />}
      {error && <ErrorState message={error} onRetry={load} />}
      {!loading && !error && !venues.length && <div className="panel"><EmptyState message="No venues for this selection." hint="Try another format or widen the date range." /></div>}
      {!loading && !error && venues.length > 0 && (
        <div className="space-y-5 animate-fade-in">
          <MetricStrip items={[
            { label: 'Venues', value: fmtInt(venues.length), sub: `${eligible.length} with ${minMatches}+ matches` },
            { label: 'Matches', value: fmtInt(total) },
            { label: 'Avg 1st-innings score', value: fmtDec(pooled('average_first_innings', 'first_innings_sample'), 1), sub: 'all venues, complete matches' },
            { label: 'Batting-first win %', value: fmtPct(pooled('batting_first_win_percentage', 'decided')), sub: 'all venues, decided matches' },
            { label: 'Toss-winner win %', value: fmtPct(pooled('toss_winner_win_percentage', 'decided')) },
          ]} />
          <div className="grid gap-4 xl:grid-cols-5">
            <ScatterChart className="xl:col-span-3" title={limited ? 'Scoring vs batting-first success' : 'Scoring vs innings-one success'}
              subtitle={`Each point is a venue with ${minMatches}+ matches. Right = higher first-innings scores; up = batting first wins more often. Click to open the profile.`}
              data={eligible.filter(v => isNum(v.average_first_innings) && isNum(v.batting_first_win_percentage)).map(v => ({ ...v, name: v.venue, size: Math.sqrt(v.matches), color: v.batting_first_win_percentage >= 55 ? PALETTE[0] : v.batting_first_win_percentage <= 45 ? PALETTE[1] : PALETTE[6],
                detail: `${v.matches} matches · ${v.city || v.country || ''}`, highlight: picked.includes(v.venue_id) }))}
              xKey="average_first_innings" yKey="batting_first_win_percentage" xLabel="Avg first-innings score" yLabel="Batting-first win %"
              formatX={v => Number(v).toFixed(0)} formatY={v => `${Math.round(v)}%`} references={[{ value: 50, label: '50% line' }]} onPointClick={r => navigate(profileLink(r.venue_id))} height={340}
              footnote="Indigo = batting first wins ≥55%; teal = chasing wins ≥55%; grey = balanced. Point size scales with matches." />
            <BarChart className="xl:col-span-2" title="Highest-scoring venues" subtitle={`Average first-innings score, ${minMatches}+ matches.`} limit={12}
              data={[...eligible].filter(v => isNum(v.average_first_innings)).sort((a, b) => b.average_first_innings - a.average_first_innings).map(v => ({ label: v.venue, value: v.average_first_innings, detail: `n=${v.first_innings_sample} · RPO ${fmtDec(v.run_rate)}` }))}
              formatter={v => fmtDec(v, 1)} unit="Avg 1st inns" color={PALETTE[2]}
              actions={<Segmented size="xs" label="Minimum matches" value={minMatches} onChange={setMinMatches} options={[{ id: '5', label: '5+' }, { id: '10', label: '10+' }, { id: '25', label: '25+' }]} />} />
          </div>
          <Panel title="Venue database" subtitle="Select 2–4 venues to compare, or open a venue for its full profile." bodyClassName="p-3"
            actions={picked.length >= 2 && <Button size="sm" variant="primary" icon="compare" onClick={() => navigate(`/venues/compare${search}${search ? '&' : '?'}ids=${picked.join(',')}`)}>Compare {picked.length} venues</Button>}>
            <DataTable dense pageSize={25} rows={venues} rowKey={r => r.venue_id} searchKeys={['venue', 'city', 'country']} searchPlaceholder="Search venue, city or country…" initialSort={{ key: 'matches', dir: 'desc' }}
              rowClassName={r => (picked.includes(r.venue_id) ? 'bg-accent-muted/30' : '')} columns={[
                { key: 'pick', label: '', sortable: false, render: r => <input type="checkbox" aria-label={`Select ${r.venue} for comparison`} checked={picked.includes(r.venue_id)} onChange={() => togglePick(r.venue_id)} disabled={!picked.includes(r.venue_id) && picked.length >= 4} /> },
                { key: 'venue', label: 'Venue', render: r => <div className="max-w-[18rem]"><Link to={profileLink(r.venue_id)} className="block truncate font-medium text-slate-100 hover:text-accent-soft">{r.venue}</Link><span className="text-3xs text-slate-500">{[r.city, r.country].filter(Boolean).join(', ')}</span></div> },
                { key: 'matches', label: 'M', align: 'right' },
                { key: 'average_first_innings', label: limited ? 'Avg 1st' : 'Avg inns 1', align: 'right', render: r => fmtDec(r.average_first_innings, 1) },
                limited && { key: 'average_second_innings', label: 'Avg 2nd', align: 'right', render: r => fmtDec(r.average_second_innings, 1) },
                { key: 'run_rate', label: 'RPO', align: 'right', render: r => fmtDec(r.run_rate) },
                { key: 'wickets_per_innings', label: 'Wkts/inn', align: 'right', render: r => fmtDec(r.wickets_per_innings, 1) },
                { key: 'batting_first_win_percentage', label: limited ? 'Bat 1st W%' : 'Inns-1 W%', align: 'right', render: r => <span className="inline-flex items-center gap-1.5">{fmtPct(r.batting_first_win_percentage)}{r.decided < 10 && <SampleBadge n={r.decided} unit="dec." />}</span> },
                { key: 'toss_winner_win_percentage', label: 'Toss W%', align: 'right', render: r => <span title={isNum(r.toss_p_value) ? `p=${r.toss_p_value}` : ''} className={isNum(r.toss_p_value) && r.toss_p_value < 0.05 ? 'font-semibold text-warn' : ''}>{fmtPct(r.toss_winner_win_percentage)}</span>, title: 'Toss winner match-win %; amber = significant at p<0.05' },
                { key: 'chose_field_percentage', label: 'Chose field', align: 'right', render: r => fmtPct(r.chose_field_percentage) },
                { key: 'spin_economy', label: 'Spin econ', align: 'right', render: r => fmtDec(r.spin_economy) },
                { key: 'pace_economy', label: 'Pace econ', align: 'right', render: r => fmtDec(r.pace_economy) },
                { key: 'highest_total', label: 'High', align: 'right', render: r => (r.highest_total != null ? <MatchLink id={r.highest_total_match_id}>{r.highest_total}</MatchLink> : DASH) },
                { key: 'last_played', label: 'Last match', align: 'right', render: r => <MatchLink id={r.last_match_id}>{r.last_played}</MatchLink> },
              ].filter(Boolean)} />
          </Panel>
        </div>
      )}
    </div>
  );
}
