/**
 * Compare 2–4 venues under the same scope: scores, batting first vs chasing,
 * toss impact, bowling and pace vs spin, phase scoring and inferred tendencies.
 * Data: GET /competition/venues (pickers) and GET /competition/venues/compare.
 */
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { compareVenues, getVenueDirectory } from '../../services/api';
import { Badge, DashboardSkeleton, EmptyState, ErrorState, MatchLink, PageHeader, Panel } from '../../components/ui';
import { GroupedBarChart, PALETTE } from '../../components/charts';
import { DASH, fmtDec, fmtPct } from '../../lib/format';
import { BackLink, CiBar, EntityPicker, ScopeFilters, isNum, useScope, useScopeSearch } from '../competition/shared';

const COLORS = [PALETTE[0], PALETTE[1], PALETTE[2], PALETTE[4]];
const PHASES = ['powerplay', 'middle', 'death'];
const PHASE = { powerplay: 'Powerplay', middle: 'Middle', death: 'Death' };

export default function VenueCompare() {
  const scope = useScope({ ids: '', team: '' });
  const search = useScopeSearch(['ids']);
  const ids = useMemo(() => (scope.filters.ids ? scope.filters.ids.split(',').filter(Boolean) : []), [scope.filters.ids]);
  const [venues, setVenues] = useState([]);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const setIds = list => scope.setFilter('ids', list.filter(Boolean).join(','));

  useEffect(() => {
    getVenueDirectory({ ...scope.params, team_id: scope.filters.team })
      .then(r => setVenues(r.venues.map(v => ({ id: v.venue_id, name: v.venue, matches: v.matches })))).catch(() => setVenues([]));
  }, [scope.key, scope.filters.team]); // eslint-disable-line react-hooks/exhaustive-deps
  const load = () => {
    if (ids.length < 2) { setData(null); return; }
    setLoading(true); setError(null);
    compareVenues(ids, { ...scope.params, team_id: scope.filters.team }).then(setData).catch(e => setError(e.message)).finally(() => setLoading(false));
  };
  useEffect(load, [ids.join(','), scope.key, scope.filters.team]); // eslint-disable-line react-hooks/exhaustive-deps

  const slots = [...ids, ...(ids.length < 4 ? [''] : [])];
  return (
    <div>
      <BackLink to={`/venues${search}`}>All venues</BackLink>
      <PageHeader eyebrow="Venue Analytics" title="Compare venues" subtitle="Two to four grounds under the same filters — which venues favour batting, chasing, the toss winner, pace or spin?" />
      <ScopeFilters scope={scope}>
        {slots.map((v, i) => (
          <EntityPicker key={`${i}-${v}`} label={`Venue ${String.fromCharCode(65 + i)}`} items={venues.filter(x => x.id === v || !ids.includes(x.id))} value={v} allowEmpty={i >= 2}
            onChange={val => { const next = [...ids]; if (val) next[i] = val; else next.splice(i, 1); setIds(next); }} labelOf={x => `${x.name} (${x.matches})`} className="min-w-[14rem] flex-1 basis-[16rem]" />
        ))}
      </ScopeFilters>
      {ids.length < 2 && <div className="panel"><EmptyState icon="venues" message="Choose at least two venues." hint="Pick from the selectors above, or tick venues in the Venue Analytics database." /></div>}
      {loading && <DashboardSkeleton />}
      {error && <ErrorState message={error} onRetry={load} />}
      {data && !loading && !error && ids.length >= 2 && <Comparison venues={data.venues} search={search} />}
    </div>
  );
}

function Comparison({ venues, search }) {
  const lim = venues[0]?.limited_overs;
  const names = venues.map(v => v.venue.name);
  const short = venues.map(v => v.venue.name.split(',')[0]);
  const style = (v, s, k) => v.conditions.pace_spin.styles.find(x => x.style === s)?.[k];
  const metrics = [
    ['Scoring', [
      ['Matches', v => v.overview.matches, x => x, null],
      [lim ? 'Avg 1st-innings score' : 'Avg innings-1 score', v => v.overview.average_first_innings, x => fmtDec(x, 1), 'high'],
      [lim ? 'Avg 2nd-innings score' : 'Avg innings-2 score', v => v.overview.average_second_innings, x => fmtDec(x, 1), 'high'],
      ['Runs per over', v => v.overview.run_rate, fmtDec, 'high'],
      ['Wickets per innings', v => v.overview.wickets_per_innings, fmtDec, 'high'],
      ['Sixes per innings', v => v.conditions.measured.sixes_per_innings, fmtDec, 'high'],
      ['Highest total', v => v.overview.highest_total?.runs, x => x, 'high', null, v => v.overview.highest_total?.match_id],
    ]],
    ['Results', [
      [lim ? 'Batting-first win %' : 'Innings-1 side win %', v => v.toss.batting_first.value, fmtPct, 'high', v => v.toss.batting_first.n],
      [lim ? 'Chasing win %' : 'Other side win %', v => v.toss.chasing.value, fmtPct, 'high', v => v.toss.chasing.n],
      ['Toss-winner win %', v => v.toss.toss_winner.value, fmtPct, 'high', v => v.toss.toss_winner.n],
      ['Chose to field %', v => v.toss.chose_field.chosen_percentage, fmtPct, null],
      lim && ['Avg successful chase target', v => v.batting_first_vs_chasing?.chasing.average_successful_target, x => fmtDec(x, 1), 'high'],
    ].filter(Boolean)],
    ['Bowling', [
      ['Pace economy', v => style(v, 'pace', 'economy'), fmtDec, 'low'],
      ['Spin economy', v => style(v, 'spin', 'economy'), fmtDec, 'low'],
      ['Pace strike rate', v => style(v, 'pace', 'strike_rate'), x => fmtDec(x, 1), 'low'],
      ['Spin strike rate', v => style(v, 'spin', 'strike_rate'), x => fmtDec(x, 1), 'low'],
      ['Spin share of wickets', v => style(v, 'spin', 'wicket_share'), fmtPct, null],
      ['Style coverage', v => v.conditions.pace_spin.coverage_percentage, fmtPct, null],
    ]],
  ];
  return (
    <div className="space-y-5 animate-fade-in">
      <div className={`grid gap-4 sm:grid-cols-2 ${venues.length > 2 ? 'xl:grid-cols-4' : ''}`}>
        {venues.map((v, i) => (
          <div key={v.venue.id} className="panel relative overflow-hidden p-4">
            <span className="absolute inset-x-0 top-0 h-0.5" style={{ backgroundColor: COLORS[i] }} />
            <Link to={`/venues/${v.venue.id}${search}`} className="block truncate text-[15px] font-semibold text-white hover:text-accent-soft" title={v.venue.name}>{v.venue.name}</Link>
            <p className="text-2xs text-slate-500">{[v.venue.city, v.venue.country].filter(Boolean).join(', ')} · {v.overview.matches} matches</p>
            <div className="mt-3 space-y-3">
              <CiBar compact label={lim ? 'Batting first wins' : 'Innings-1 side wins'} p={v.toss.batting_first} color={COLORS[i]} />
              <CiBar compact label="Toss winner wins" p={v.toss.toss_winner} color={COLORS[i]} />
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">{v.conditions.inferred.tags.map(t => <Badge key={t.tag} variant={t.tone === 'bat' ? 'green' : t.tone === 'bowl' ? 'blue' : 'default'}>{t.tag}</Badge>)}</div>
          </div>
        ))}
      </div>
      <Panel title="Side-by-side" subtitle="Best value in each row is highlighted. Bracketed numbers are decided-match samples." bodyClassName="overflow-x-auto p-0">
        <table className="w-full min-w-[40rem] text-[13px]">
          <thead className="bg-surface-raised"><tr><th className="px-4 py-2 text-left text-3xs font-medium uppercase tracking-wide text-slate-500">Metric</th>{short.map((n, i) => <th key={i} className="px-4 py-2 text-right text-3xs font-medium uppercase tracking-wide" style={{ color: COLORS[i] }} title={names[i]}>{n}</th>)}</tr></thead>
          <tbody>
            {metrics.map(([group, rows]) => [
              <tr key={group}><td colSpan={venues.length + 1} className="eyebrow bg-surface-sunken/60 px-4 py-1.5">{group}</td></tr>,
              ...rows.map(([label, get, f, better, n, link]) => {
                const vals = venues.map(get);
                const nums = vals.filter(isNum).map(Number);
                const best = better && nums.length > 1 ? (better === 'high' ? Math.max(...nums) : Math.min(...nums)) : null;
                return (
                  <tr key={label} className="border-t border-line-soft">
                    <td className="px-4 py-2 text-slate-300">{label}</td>
                    {vals.map((x, i) => <td key={i} className={`num px-4 py-2 text-right ${isNum(x) && Number(x) === best ? 'font-semibold text-white' : 'text-slate-400'}`}>{isNum(x) ? (link ? <MatchLink id={link(venues[i])}>{f(x)}</MatchLink> : f(x)) : DASH}{n && <span className="ml-1 text-3xs text-slate-600">({n(venues[i])})</span>}</td>)}
                  </tr>
                );
              }),
            ])}
          </tbody>
        </table>
      </Panel>
      <div className="grid gap-4 lg:grid-cols-2">
        <GroupedBarChart title="Average scores" categories={lim ? ['1st innings', '2nd innings'] : ['Innings 1', 'Innings 2']} formatter={x => fmtDec(x, 0)} yLabel="Runs"
          series={venues.map((v, i) => ({ name: short[i], color: COLORS[i], values: [v.overview.average_first_innings, v.overview.average_second_innings] }))} />
        <GroupedBarChart title={lim ? 'Batting first vs chasing' : 'Result by innings order'} subtitle="Win % of decided matches; 50% = no edge." categories={[lim ? 'Batting first' : 'Innings-1 side', lim ? 'Chasing' : 'Other side', 'Toss winner']} formatter={x => `${Math.round(x)}%`} yLabel="Win %"
          series={venues.map((v, i) => ({ name: short[i], color: COLORS[i], values: [v.toss.batting_first.value, v.toss.chasing.value, v.toss.toss_winner.value] }))} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <GroupedBarChart title="Pace vs spin economy" subtitle="Runs per over by bowling type (classified bowlers only)." categories={['Pace', 'Spin']} formatter={x => fmtDec(x, 1)} yLabel="Economy"
          series={venues.map((v, i) => ({ name: short[i], color: COLORS[i], values: [style(v, 'pace', 'economy'), style(v, 'spin', 'economy')] }))} />
        {lim ? (
          <GroupedBarChart title="Scoring rate by phase" subtitle="Runs per over across both innings (ball-weighted)." categories={PHASES.map(p => PHASE[p])} formatter={x => fmtDec(x, 1)} yLabel="Runs per over"
            series={venues.map((v, i) => ({ name: short[i], color: COLORS[i], values: PHASES.map(p => { const rows = (v.conditions.phases || []).filter(x => x.phase === p && x.balls); const b = rows.reduce((a, x) => a + x.balls, 0); return b ? rows.reduce((a, x) => a + x.run_rate * x.balls, 0) / b : null; }) }))} />
        ) : <Panel title="Scoring rate by phase"><p className="text-sm text-slate-500">Phases apply to limited-overs formats only.</p></Panel>}
      </div>
      <p className="text-2xs text-slate-500">Inferred tags on the venue cards come from scoring outcomes relative to the format baseline; they are not pitch reports.</p>
    </div>
  );
}
