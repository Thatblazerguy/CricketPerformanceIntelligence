/**
 * Team vs team matchup intelligence.
 * Data: GET /matchups/team-analysis (+ team-options, team-venues, team-encounters).
 * Reuses the Team/Venue Analytics engine, so definitions match those pages exactly.
 */
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getCompetitionSeasons, getMatchupTeamOptions, getMatchupTeamVenues, getTeamEncounters, getTeamMatchup } from '../../services/api';
import { useUrlFilters } from '../../hooks/useFilters';
import { Badge, Button, Callout, DashboardSkeleton, DataTable, EmptyState, ErrorState, FilterBar, FilterField, MatchLink, Panel, SampleBadge, Select, Tabs } from '../../components/ui';
import { matchUrl } from '../../components/MatchLink';
import { ColumnChart, GroupedBarChart } from '../../components/charts';
import { DASH, FORMATS, fmtDec, fmtPct } from '../../lib/format';
import { EntityPicker, FormStrip, MethodNote, Unavailable, VersusRow, isNum, recordLine, resultLabel } from '../competition/shared';
import { COLOR_A, COLOR_B, ContributionNote, DateField, InsightCards, PropRow, RivalryBar } from './matchupUi';

const DEFAULTS = { a: '', b: '', format: 'T20', gender: 'male', competition: '', season: '', date_from: '', date_to: '', venue_id: '', side: '', order: '', recent: '', tab: 'overview' };
const TABS = [
  { id: 'overview', label: 'Overview' }, { id: 'toss', label: 'Toss & innings' }, { id: 'batbowl', label: 'Batting vs bowling' },
  { id: 'venue', label: 'Venue intelligence' }, { id: 'trends', label: 'Trends' }, { id: 'encounters', label: 'Recent encounters' }, { id: 'insights', label: 'Insights' },
];
const PHASE = { powerplay: 'Powerplay', middle: 'Middle', death: 'Death' };

export default function TeamMatchup() {
  const [f, setFilter, reset, active, setFilters] = useUrlFilters(DEFAULTS);
  const scope = useMemo(() => ({ format: f.format || 'T20', gender: f.gender === 'female' ? 'female' : 'male', competition: f.competition, season: f.season }), [f.format, f.gender, f.competition, f.season]);
  const scopeKey = JSON.stringify(scope);
  const [teams, setTeams] = useState([]);
  const [opps, setOpps] = useState([]);
  const [seasons, setSeasons] = useState([]);
  const [venues, setVenues] = useState([]);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => { getMatchupTeamOptions(scope).then(r => setTeams(r.teams)).catch(() => setTeams([])); }, [scopeKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!f.a) { setOpps([]); return; }
    getMatchupTeamOptions({ ...scope, team_id: f.a }).then(r => setOpps(r.teams)).catch(() => setOpps([]));
  }, [f.a, scopeKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { getCompetitionSeasons({ format: scope.format, gender: scope.gender, competition: scope.competition }).then(r => setSeasons(r.seasons || [])).catch(() => setSeasons([])); }, [scope.format, scope.gender, scope.competition]);
  useEffect(() => {
    if (!f.a || !f.b) { setVenues([]); return; }
    getMatchupTeamVenues({ a: f.a, b: f.b, ...scope }).then(r => setVenues(r.venues)).catch(() => setVenues([]));
  }, [f.a, f.b, scopeKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const params = useMemo(() => ({ a: f.a, b: f.b, ...scope, date_from: f.date_from, date_to: f.date_to, venue_id: f.venue_id, side: f.side, order: f.order, recent: f.recent }),
    [f.a, f.b, scope, f.date_from, f.date_to, f.venue_id, f.side, f.order, f.recent]);
  const load = () => {
    if (!f.a || !f.b || f.a === f.b) { setData(null); return; }
    setLoading(true); setError(null);
    getTeamMatchup({ ...params, page_size: 10 }).then(setData).catch(e => setError(e.message)).finally(() => setLoading(false));
  };
  useEffect(load, [JSON.stringify(params)]); // eslint-disable-line react-hooks/exhaustive-deps

  const nameOf = id => teams.find(t => t.id === id)?.name || opps.find(t => t.id === id)?.name;
  return (
    <div>
      <FilterBar onReset={() => { reset(); }} active={active - (f.tab !== 'overview' ? 1 : 0)}
        note="Format and gender are always fixed so men's/women's and different formats never mix. Home/away and innings filters are relative to Team A.">
        <EntityPicker label="Team A" items={teams} value={f.a} onChange={v => setFilters({ a: v, b: v === f.b ? '' : f.b, venue_id: '' })} labelOf={t => `${t.name} (${t.matches})`} />
        <EntityPicker label="Team B (opponents of A)" items={(f.a ? opps : teams).filter(t => t.id !== f.a)} value={f.b} onChange={v => setFilters({ b: v, venue_id: '' })} labelOf={t => `${t.name} (${t.matches}${f.a ? ' vs A' : ''})`} />
        <FilterField label="Format"><Select value={f.format} onChange={v => setFilters({ format: v, season: '', a: '', b: '', venue_id: '' })} options={FORMATS} /></FilterField>
        <FilterField label="Gender"><Select value={f.gender || 'male'} onChange={v => setFilters({ gender: v, season: '', a: '', b: '', venue_id: '' })} options={[{ id: 'male', label: 'Men' }, { id: 'female', label: 'Women' }]} /></FilterField>
        <FilterField label="Competition">
          <input key={f.competition} type="search" defaultValue={f.competition} placeholder="e.g. Premier League" aria-label="Competition"
            onBlur={e => e.target.value.trim() !== f.competition && setFilters({ competition: e.target.value.trim(), season: '' })}
            onKeyDown={e => e.key === 'Enter' && setFilters({ competition: e.currentTarget.value.trim(), season: '' })} className="h-9 w-40 px-3 text-[13px]" />
        </FilterField>
        <FilterField label="Season"><Select value={f.season} onChange={v => setFilter('season', v)} options={seasons} placeholder="All" className="w-28" /></FilterField>
        <DateField label="From date" value={f.date_from} onChange={v => setFilter('date_from', v)} />
        <DateField label="To date" value={f.date_to} onChange={v => setFilter('date_to', v)} />
        <FilterField label="Venue" className="min-w-[12rem]"><Select value={f.venue_id} onChange={v => setFilter('venue_id', v)} placeholder="All venues" className="max-w-[16rem]"
          options={venues.map(v => ({ id: v.id, label: `${v.name}${v.h2h ? ` (${v.h2h} H2H)` : ''}` }))} /></FilterField>
        <FilterField label="Team A at"><Select value={f.side} onChange={v => setFilter('side', v)} placeholder="Home & away" options={[{ id: 'home', label: 'Home' }, { id: 'away', label: 'Away' }, { id: 'neutral', label: 'Neutral' }]} /></FilterField>
        <FilterField label="Innings"><Select value={f.order} onChange={v => setFilter('order', v)} placeholder="Either" options={[{ id: 'a_bat_first', label: 'A batting first' }, { id: 'a_chasing', label: 'A batting second' }]} /></FilterField>
        <FilterField label="Encounters"><Select value={f.recent} onChange={v => setFilter('recent', v)} placeholder="All" options={[{ id: '5', label: 'Last 5' }, { id: '10', label: 'Last 10' }, { id: '20', label: 'Last 20' }]} className="w-24" /></FilterField>
      </FilterBar>

      {(!f.a || !f.b) && <div className="panel"><EmptyState icon="teams" message="Choose two teams to analyse their rivalry."
        hint="Pick Team A first — Team B then lists A's actual opponents, most-played first. Every statistic is computed from the stored matches and ball-by-ball innings totals." /></div>}
      {loading && <DashboardSkeleton />}
      {error && <ErrorState message={error} onRetry={load} />}
      {data && !loading && !error && (
        <Analysis d={data} f={f} setFilter={setFilter} params={params} venueName={venues.find(v => v.id === f.venue_id)?.name} names={{ a: nameOf(f.a), b: nameOf(f.b) }} />
      )}
    </div>
  );
}

function Analysis({ d, f, setFilter, params, venueName }) {
  const A = d.teams.a, B = d.teams.b;
  const o = d.overview;
  const lim = d.limited_overs;
  const other = o.a.tied + o.a.drawn + o.a.no_result + o.a.unknown;
  const chips = [f.format, f.gender === 'female' ? 'Women' : 'Men', f.competition && `“${f.competition}”`, f.season && `Season ${f.season}`,
    (f.date_from || f.date_to) && `${f.date_from || '…'} → ${f.date_to || '…'}`, venueName && `at ${venueName}`,
    f.side && `${A.name} ${f.side}`, f.order && (f.order === 'a_bat_first' ? `${A.name} batting first` : `${A.name} batting second`), f.recent && `last ${f.recent}`].filter(Boolean);
  return (
    <div className="space-y-5 animate-fade-in">
      <ContributionNote>
        <span className="num font-medium text-slate-300">{o.matches} match{o.matches === 1 ? '' : 'es'} contribute to this analysis</span>
        {d.matches_before_view_filters !== o.matches && <span>({d.matches_before_view_filters} before home/away, innings or recency filters)</span>}
        {chips.map(c => <Badge key={c} variant="indigo">{c}</Badge>)}
      </ContributionNote>

      <section className="panel-hero p-6 sm:p-7">
        <div className="relative grid gap-6 lg:grid-cols-[1fr_auto_1fr] lg:items-center">
          <TeamSide t={A} r={o.a} m={o.a_margins} color={COLOR_A} />
          <div className="text-center">
            <div className="eyebrow mb-1">Head-to-head</div>
            <div className="display-num text-[44px] leading-none"><span style={{ color: COLOR_A }}>{o.a.won}</span><span className="mx-3 text-slate-600">–</span><span style={{ color: COLOR_B }}>{o.b.won}</span></div>
            <div className="mt-2 text-2xs text-slate-500">{o.matches} matches · {o.first_played ? `${o.first_played.slice(0, 4)}–${o.last_played.slice(0, 4)}` : 'no meetings'}</div>
          </div>
          <TeamSide t={B} r={o.b} m={o.b_margins} color={COLOR_B} right />
        </div>
        {o.matches > 0 && (
          <div className="relative mt-6 grid gap-4 md:grid-cols-[1fr_auto] md:items-end">
            <RivalryBar a={o.a.won} b={o.b.won} other={other} aLabel={A.name} bLabel={B.name} />
            <div className="flex items-center gap-2 text-2xs text-slate-500">
              <span>Last {o.form.length} ({A.name}):</span>
              <FormStrip items={o.form.map((r, i) => ({ result: r, match_id: o.form_match_ids[i], label: `${resultLabel(r)} — open match` }))} />
            </div>
          </div>
        )}
      </section>

      {o.matches === 0 ? <div className="panel"><EmptyState message="These teams have not met under the selected filters." hint="Widen the date range, clear the venue or competition filter, or check the format and gender." /></div> : (
        <>
          <Tabs tabs={TABS} value={f.tab || 'overview'} onChange={v => setFilter('tab', v)} />
          {f.tab === 'toss' ? <TossInnings d={d} />
            : f.tab === 'batbowl' ? <BattingBowling d={d} />
              : f.tab === 'venue' ? <VenueIntel d={d} f={f} setFilter={setFilter} />
                : f.tab === 'trends' ? <Trends d={d} />
                  : f.tab === 'encounters' ? <Encounters d={d} params={params} />
                    : f.tab === 'insights' ? <Panel title="Matchup insights" subtitle="Generated from the calculations above. Each shows its sample and statistical basis; these describe history and do not predict results."><InsightCards items={d.insights} /></Panel>
                      : <Overview d={d} setFilter={setFilter} />}
          <MethodNote items={d.notes} />
        </>
      )}
      {lim === false && <p className="text-2xs text-slate-500">Multi-day format: chase/defend, phase and collapse-recovery analysis use limited-overs definitions and are not shown.</p>}
    </div>
  );
}

function TeamSide({ t, r, m, color, right }) {
  return (
    <div className={`min-w-0 ${right ? 'lg:text-right' : ''}`}>
      <span className="mb-2 inline-block h-1 w-10 rounded-full" style={{ backgroundColor: color }} />
      <Link to={`/teams/${t.id}`} className="block truncate text-[22px] font-semibold tracking-tight text-white hover:text-accent-soft">{t.name}</Link>
      <div className="mt-1 text-2xs text-slate-500">{recordLine(r)}</div>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2" style={{ justifyContent: right ? 'flex-end' : undefined }}>
        <Mini label="Win %" value={fmtPct(r.win_percentage)} sub={`of ${r.decided} decided`} />
        <Mini label="Avg win by runs" value={m.average_runs_margin != null ? fmtDec(m.average_runs_margin, 1) : DASH} sub={`${m.by_runs} wins`} />
        <Mini label="Avg win by wkts" value={m.average_wickets_margin != null ? fmtDec(m.average_wickets_margin, 1) : DASH} sub={`${m.by_wickets} wins`} />
      </div>
    </div>
  );
}

const Mini = ({ label, value, sub }) => (
  <div className="min-w-0"><div className="text-3xs uppercase tracking-wide text-slate-500">{label}</div><div className="num text-[17px] font-semibold text-slate-50">{value}</div>{sub && <div className="text-3xs text-slate-500">{sub}</div>}</div>
);

/* ------------------------------------------------------------------ overview */

function Overview({ d, setFilter }) {
  const r = d.records;
  return (
    <div className="space-y-5">
      <Panel title="Key insights" subtitle="Top patterns from this head-to-head, each with its sample and statistical basis."
        actions={<Button size="xs" variant="ghost" iconRight="arrowRight" onClick={() => setFilter('tab', 'insights')}>All insights</Button>}>
        <InsightCards items={d.insights} limit={4} />
      </Panel>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Highest totals" subtitle="Any innings in this fixture. Click a row to open the match." bodyClassName="p-3">
          <TotalsList rows={r.highest_totals} />
        </Panel>
        <Panel title="Lowest completed totals" subtitle={r.lowest_note} bodyClassName="p-3">
          <TotalsList rows={r.lowest_totals} />
        </Panel>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Highest successful chase" bodyClassName="p-3">
          {r.highest_successful_chase ? <EncounterCard e={r.highest_successful_chase} headline={`${r.highest_successful_chase.team} chased ${r.highest_successful_chase.target}`} />
            : <p className="p-2 text-sm text-slate-500">{d.limited_overs ? 'No completed successful chase in this selection.' : 'Not applicable to multi-day cricket.'}</p>}
        </Panel>
        <Panel title="Most dominant victories" subtitle="Largest run margins, then largest wicket margins." bodyClassName="p-3 space-y-1">
          {r.dominant_victories.length ? r.dominant_victories.map(e => <EncounterCard key={`${e.kind}-${e.match_id}`} e={e} headline={e.result} />) : <p className="p-2 text-sm text-slate-500">No decided matches.</p>}
        </Panel>
        <Panel title="Closest finishes" subtitle="Ties, then smallest run margins, then chases won with fewest balls left." bodyClassName="p-3 space-y-1">
          {r.closest_finishes.length ? r.closest_finishes.map(e => <EncounterCard key={e.match_id} e={e} headline={e.result} />) : <p className="p-2 text-sm text-slate-500">No close matches by the format's definition.</p>}
        </Panel>
      </div>
      <Panel title={`${d.teams.a.name} by venue type`} subtitle="Evidence-based home/away (verified country or detected franchise home ground). Unclassified matches are kept separate.">
        <div className="grid gap-x-8 sm:grid-cols-2 lg:grid-cols-4">
          {['home', 'away', 'neutral', 'unclassified'].map(s => (
            <PropRow key={s} label={s[0].toUpperCase() + s.slice(1)} p={d.home_away[s].win} sub={recordLine(d.home_away[s])} />
          ))}
        </div>
      </Panel>
    </div>
  );
}

function TotalsList({ rows }) {
  if (!rows?.length) return <p className="p-2 text-sm text-slate-500">No qualifying innings.</p>;
  return (
    <ul>
      {rows.map((t, i) => (
        <li key={`${t.match_id}-${t.innings_number}`}>
          <MatchCardRow id={t.match_id} label={`${t.team} ${t.score} vs ${t.opponent}, ${t.date}`}>
            <span className="num w-5 text-2xs text-slate-500">{i + 1}</span>
            <span className="num w-20 text-[15px] font-semibold text-white">{t.score}</span>
            <span className="min-w-0 flex-1"><span className="block truncate text-[13px] text-slate-200">{t.team} <span className="text-slate-500">v {t.opponent}</span></span>
              <span className="block truncate text-3xs text-slate-500">{t.date} · {t.venue} · inns {t.innings_number}{t.overs ? ` · ${t.overs} ov` : ''}{t.reduced ? ' · reduced' : ''}</span></span>
            <Badge variant={t.won ? 'green' : 'default'}>{t.won ? 'won' : 'lost/other'}</Badge>
          </MatchCardRow>
        </li>
      ))}
    </ul>
  );
}

/** Whole-row match link used in compact lists (a single <a>, no nested interactive elements). */
function MatchCardRow({ id, label, children }) {
  const to = matchUrl(id);
  return <Link to={to} aria-label={`Open match: ${label}`} className="flex items-center gap-3 rounded-xl px-2.5 py-2 transition-colors hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60">{children}<span className="text-slate-600">›</span></Link>;
}

function EncounterCard({ e, headline }) {
  return (
    <MatchCardRow id={e.match_id} label={`${headline}, ${e.date}`}>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium text-slate-100">{headline}{e.kind === 'wickets' && isNum(e.balls_remaining) ? <span className="font-normal text-slate-500"> · {e.balls_remaining} balls left</span> : null}</span>
        <span className="block truncate text-3xs text-slate-500">{e.date} · {e.first_innings?.team} {e.first_innings?.score} · {e.second_innings?.team} {e.second_innings?.score ?? DASH} · {e.venue}</span>
      </span>
    </MatchCardRow>
  );
}

/* ------------------------------------------------------------- toss & innings */

function TossInnings({ d }) {
  const A = d.teams.a, B = d.teams.b;
  const t = d.toss_innings.toss, o = d.toss_innings.order, ob = d.toss_innings.order_by_team, cd = d.toss_innings.chase_defence;
  const base = d.baseline;
  return (
    <div className="space-y-5">
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Toss impact" subtitle={`Binomial test vs 50%: ${t.p_value != null ? `p=${t.p_value}` : 'n/a'}. Format-wide: ${fmtPct(base.toss_winner_win_percentage)}.`}>
          <PropRow label="Toss winner won the match" p={t.toss_winner_won} />
          <PropRow label="…after choosing to bat" p={t.by_decision.bat.toss_winner_won} sub={`chosen ${t.by_decision.bat.chosen} times`} />
          <PropRow label="…after choosing to field" p={t.by_decision.field.toss_winner_won} sub={`chosen ${t.by_decision.field.chosen} times`} />
        </Panel>
        <Panel title="Batting first vs chasing" subtitle={`Binomial test vs 50%: ${o.p_value != null ? `p=${o.p_value}` : 'n/a'}. Format-wide bat-first win %: ${fmtPct(base.batting_first_win_percentage)}.`}>
          <PropRow label="Side batting first won" p={o.batting_first_won} />
          <PropRow label="Side batting second won" p={o.chasing_won} />
          {o.chase_success && <PropRow label="Chase success (complete matches)" p={o.chase_success} />}
          {o.defend_success && <PropRow label="Defend success (complete matches)" p={o.defend_success} />}
        </Panel>
        <Panel title="Average innings scores" subtitle={`Complete matches only (n=${o.complete_matches}).`}>
          <div className="grid grid-cols-2 gap-4">
            <BigNum label="1st innings" value={fmtDec(o.average_first_innings, 1)} sub={`format ${fmtDec(base.average_first_innings, 1)}`} />
            <BigNum label="2nd innings" value={fmtDec(o.average_second_innings, 1)} sub={`format ${fmtDec(base.average_second_innings, 1)}`} />
          </div>
        </Panel>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Win % after the toss" subtitle="Each team's record when it won or lost the toss (decided matches).">
          {[[A, COLOR_A], [B, COLOR_B]].map(([tm, c]) => (
            <div key={tm.id} className="mb-3 last:mb-0">
              <div className="mb-1 flex items-center gap-2 text-[13px] font-medium text-slate-200"><span className="h-2 w-2 rounded-full" style={{ backgroundColor: c }} />{tm.name}</div>
              <PropRow label="Won the toss" p={t.teams[tm.id].won_toss.win} sub={recordLine(t.teams[tm.id].won_toss)} />
              <PropRow label="Lost the toss" p={t.teams[tm.id].lost_toss.win} sub={recordLine(t.teams[tm.id].lost_toss)} />
            </div>
          ))}
        </Panel>
        <GroupedBarChart title="Win % by batting order" subtitle="Decided matches in this fixture; 50% = even." formatter={v => `${Math.round(v)}%`} yLabel="Win %"
          categories={['Batting first', 'Batting second']}
          series={[[A, COLOR_A], [B, COLOR_B]].map(([tm, c]) => ({ name: tm.name, color: c, values: [ob[tm.id].batting_first.win_percentage, ob[tm.id].chasing.win_percentage] }))}
          footnote={`Samples — ${A.name}: ${ob[A.id].batting_first.decided} / ${ob[A.id].chasing.decided}; ${B.name}: ${ob[B.id].batting_first.decided} / ${ob[B.id].chasing.decided} decided.`} />
      </div>
      {cd && (
        <div className="grid gap-4 lg:grid-cols-2">
          {[[A, COLOR_A], [B, COLOR_B]].map(([tm]) => {
            const c = cd[tm.id];
            return (
              <Panel key={tm.id} title={`${tm.name} — chasing & defending`} subtitle="Complete (non-reduced) matches, so targets are real first-innings totals.">
                <PropRow label="Chase success" p={c.chases.success} sub={`avg successful target ${fmtDec(c.chases.average_successful_target, 1)} · highest ${c.chases.highest_successful_target ?? DASH}`} />
                <PropRow label="Defence success" p={c.defences.success} sub={`avg defended ${fmtDec(c.defences.average_defended_total, 1)} · lowest defended ${c.defences.lowest_defended_total ?? DASH}`} />
              </Panel>
            );
          })}
        </div>
      )}
    </div>
  );
}

const BigNum = ({ label, value, sub }) => (
  <div><div className="text-2xs text-slate-500">{label}</div><div className="display-num text-[28px] leading-tight text-white">{value}</div>{sub && <div className="text-3xs text-slate-500">{sub}</div>}</div>
);

/* --------------------------------------------------------- batting vs bowling */

function BattingBowling({ d }) {
  const A = d.teams.a, B = d.teams.b;
  const sa = d.batting_bowling[A.id], sb = d.batting_bowling[B.id];
  const rows = [
    ['Batting against the opponent', [
      ['Average score', x => x.batting.average_score, v => fmtDec(v, 1), 'high', x => `n=${x.batting.complete_innings}`],
      ['Run rate', x => x.batting.run_rate, fmtDec, 'high'],
      ['Runs per wicket', x => x.batting.runs_per_wicket, fmtDec, 'high'],
      ['Wickets lost / innings', x => x.batting.wickets_per_innings, fmtDec, 'low'],
      ['Boundary % of balls', x => x.batting.boundary_percentage, fmtPct, 'high'],
      ['Dot-ball %', x => x.batting.dot_percentage, fmtPct, 'low'],
      ['Highest total', x => x.batting.highest, v => v, 'high'],
      ['Lowest completed total', x => x.batting.lowest, v => v, 'high'],
      ['Avg 1st-innings score', x => x.batting_first_innings.average_score, v => fmtDec(v, 1), 'high'],
      ['Avg 2nd-innings score', x => x.batting_second_innings.average_score, v => fmtDec(v, 1), 'high'],
    ]],
    ['Bowling against the opponent', [
      ['Wickets taken', x => x.wickets_taken, v => v, 'high'],
      ['Economy (RPO conceded)', x => x.bowling.run_rate, fmtDec, 'low'],
      ['Wickets / innings', x => x.bowling.wickets_per_innings, fmtDec, 'high'],
      ['Balls per wicket', x => x.bowling.balls_per_wicket, v => fmtDec(v, 1), 'low'],
      ['Boundary % conceded', x => x.bowling.boundary_percentage, fmtPct, 'low'],
    ]],
  ];
  const col = d.collapses;
  return (
    <div className="space-y-5">
      <Panel title="Tale of the tape" subtitle="Each team's batting and bowling in this fixture only. Brighter bar = better value.">
        <div className="mb-1 grid grid-cols-[1fr_auto_1fr] text-3xs uppercase tracking-wide"><span className="truncate text-right" style={{ color: COLOR_A }}>{A.name}</span><span className="w-32 sm:w-40" /><span className="truncate" style={{ color: COLOR_B }}>{B.name}</span></div>
        {rows.map(([group, items]) => (
          <div key={group} className="border-t border-line-soft pt-2 first:border-0">
            <div className="eyebrow mb-1 mt-1 text-center">{group}</div>
            {items.map(([label, get, fm, better, sub]) => <VersusRow key={label} label={label} a={get(sa)} b={get(sb)} format={fm} better={better} aColor={COLOR_A} bColor={COLOR_B} sub={sub ? `${sub(sa)} · ${sub(sb)}` : null} />)}
          </div>
        ))}
      </Panel>
      {d.limited_overs && sa.batting_phases && (
        <div className="grid gap-4 lg:grid-cols-2">
          <GroupedBarChart title="Batting run rate by phase" subtitle="Runs per over in this fixture vs the format baseline." formatter={v => fmtDec(v, 1)} yLabel="RPO"
            categories={sa.batting_phases.map(p => PHASE[p.phase])}
            series={[{ name: A.name, color: COLOR_A, values: sa.batting_phases.map(p => p.run_rate) }, { name: B.name, color: COLOR_B, values: sb.batting_phases.map(p => p.run_rate) }, { name: 'Format', color: 'var(--chart-muted)', values: sa.batting_phases.map(p => p.baseline_run_rate) }]}
            footnote={`Balls — ${A.name}: ${sa.batting_phases.map(p => p.balls).join(' / ')}; ${B.name}: ${sb.batting_phases.map(p => p.balls).join(' / ')}.`} />
          <GroupedBarChart title="Wickets lost per innings by phase" subtitle="Lower is better for the batting side." formatter={v => fmtDec(v, 2)} yLabel="Wickets"
            categories={sa.batting_phases.map(p => PHASE[p.phase])}
            series={[{ name: A.name, color: COLOR_A, values: sa.batting_phases.map(p => p.wickets_per_innings) }, { name: B.name, color: COLOR_B, values: sb.batting_phases.map(p => p.wickets_per_innings) }]} />
        </div>
      )}
      <Panel title="Batting collapses & recoveries" subtitle={[col.definitions.collapse, col.definitions.recovery && `Recovery: ${col.definitions.recovery}`].filter(Boolean).join(' ')}>
        <div className="grid gap-5 md:grid-cols-2">
          {[[A, COLOR_A], [B, COLOR_B]].map(([tm, c]) => {
            const x = col.teams[tm.id];
            if (!x) return <p key={tm.id} className="text-sm text-slate-500">No ball-by-ball innings for {tm.name}.</p>;
            return (
              <div key={tm.id}>
                <div className="mb-2 flex items-center gap-2 text-[13px] font-medium text-slate-200"><span className="h-2 w-2 rounded-full" style={{ backgroundColor: c }} />{tm.name}</div>
                <div className="mb-3 flex gap-6"><BigNum label="Collapses" value={x.collapses} sub={`${fmtPct(x.collapse_rate)} of ${x.innings} innings`} />{d.limited_overs && <BigNum label="Recoveries" value={x.recoveries} sub="3+ PP wickets, still won" />}</div>
                <ul className="space-y-0.5">
                  {x.examples.map(e => <li key={e.match_id}><MatchLink id={e.match_id} className="text-xs text-slate-300">{e.date}: {e.from} → {e.to} ({e.runs} runs for 4 wkts){e.won ? ' · still won' : ''}</MatchLink></li>)}
                  {x.recovery_examples.map(e => <li key={`r-${e.match_id}`}><MatchLink id={e.match_id} className="text-xs text-pos-soft">{e.date}: recovered from {e.powerplay_wickets} powerplay wickets to win</MatchLink></li>)}
                </ul>
              </div>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}

/* ---------------------------------------------------------- venue intelligence */

function VenueIntel({ d, f, setFilter }) {
  const A = d.teams.a, B = d.teams.b;
  const v = d.venue;
  return (
    <div className="space-y-5">
      {!f.venue_id && <Callout>Choose a venue in the filter bar, or click <strong>Focus</strong> on a ground below, to see this rivalry at that ground alongside each team's record there against everyone.</Callout>}
      {v && (
        <>
          <Callout tone={v.head_to_head.matches < 10 ? 'warn' : 'info'}>{v.sample_note}{v.head_to_head.matches < 10 ? ' The head-to-head sample at this ground is small; treat differences as indicative only.' : ''}</Callout>
          <div className="grid gap-4 lg:grid-cols-3">
            <Panel title={`Head-to-head at ${v.venue.name}`} subtitle={`${v.venue.city || ''}${v.venue.country ? `, ${v.venue.country}` : ''}`}>
              <PropRow label="Side batting first won" p={v.head_to_head.order.batting_first_won} />
              {v.head_to_head.order.chase_success && <PropRow label="Chase success" p={v.head_to_head.order.chase_success} />}
              <PropRow label="Toss winner won" p={v.head_to_head.toss.toss_winner_won} />
              <div className="mt-3 grid grid-cols-2 gap-4">
                <BigNum label="Avg 1st inns" value={fmtDec(v.head_to_head.order.average_first_innings, 1)} />
                <BigNum label="Avg 2nd inns" value={fmtDec(v.head_to_head.order.average_second_innings, 1)} />
                <BigNum label="Highest" value={v.head_to_head.scoring.highest ?? DASH} />
                <BigNum label="Lowest completed" value={v.head_to_head.scoring.lowest ?? DASH} />
              </div>
            </Panel>
            <Panel title="Venue overall" subtitle={`All ${v.venue_overall.matches} matches at the ground under these filters (baseline).`}>
              <PropRow label="Side batting first won" p={v.venue_overall.order.batting_first_won} />
              {v.venue_overall.order.chase_success && <PropRow label="Chase success" p={v.venue_overall.order.chase_success} />}
              <PropRow label="Toss winner won" p={v.venue_overall.toss.toss_winner_won} sub={`chose to field ${v.venue_overall.toss.chose_field} · bat ${v.venue_overall.toss.chose_bat}`} />
              <div className="mt-3 grid grid-cols-2 gap-4">
                <BigNum label="Avg 1st inns" value={fmtDec(v.venue_overall.order.average_first_innings, 1)} />
                <BigNum label="Run rate" value={fmtDec(v.venue_overall.scoring.run_rate)} />
              </div>
            </Panel>
            <Panel title="Boundary & wicket patterns" subtitle="Head-to-head at the ground vs every match at the ground.">
              {[['Boundary % of balls', s => s.boundary_percentage, fmtPct], ['Dot-ball %', s => s.dot_percentage, fmtPct], ['Wickets / innings', s => s.wickets_per_innings, fmtDec], ['Run rate', s => s.run_rate, fmtDec], ['Sixes / innings', s => s.sixes_per_innings, fmtDec]].map(([l, g, fm]) => (
                <div key={l} className="flex justify-between border-b border-line-soft py-2 text-[13px] last:border-0"><span className="text-slate-400">{l}</span><span className="num text-slate-100">{fm(g(v.head_to_head.scoring))} <span className="text-slate-500">vs {fm(g(v.venue_overall.scoring))}</span></span></div>
              ))}
            </Panel>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {[[A, COLOR_A], [B, COLOR_B]].map(([tm, c]) => {
              const t = v.teams[tm.id];
              return (
                <Panel key={tm.id} title={`${tm.name} at this ground (all opponents)`} subtitle={recordLine(t.record)}>
                  <PropRow label="Win %" p={t.record.win} />
                  {t.order && <PropRow label="Batting first" p={t.order.batting_first.win} sub={recordLine(t.order.batting_first)} />}
                  {t.order && <PropRow label="Batting second" p={t.order.chasing.win} sub={recordLine(t.order.chasing)} />}
                  <div className="mt-2 text-2xs text-slate-500">Avg score {fmtDec(t.batting.average_score, 1)} · RR {fmtDec(t.batting.run_rate)} · highest {t.batting.highest ?? DASH}</div>
                  {t.seasons.length > 0 && <DataTable dense pageSize={0} rows={t.seasons} rowKey={r => r.season} columns={[
                    { key: 'season', label: 'Season' }, { key: 'matches', label: 'M', align: 'right' }, { key: 'won', label: 'W', align: 'right' }, { key: 'lost', label: 'L', align: 'right' },
                    { key: 'win_percentage', label: 'Win %', align: 'right', render: r => fmtPct(r.win_percentage), className: () => '' },
                  ]} maxHeight={220} />}
                </Panel>
              );
            })}
          </div>
        </>
      )}
      <Panel title="Head-to-head by ground" subtitle="Where these teams have met under the current filters." actions={f.venue_id && <Button size="xs" variant="ghost" onClick={() => setFilter('venue_id', '')}>Clear venue</Button>}>
        <DataTable dense pageSize={15} rows={d.venues} rowKey={r => r.venue_id} searchKeys={['venue', 'city']} searchPlaceholder="Search grounds…" columns={[
          { key: 'venue', label: 'Venue', render: r => <span><Link to={`/venues/${r.venue_id}`} className="text-slate-100 hover:text-accent-soft">{r.venue}</Link>{r.city && <span className="text-slate-500"> · {r.city}</span>}</span> },
          { key: 'matches', label: 'M', align: 'right' },
          { key: 'a_won', label: `${A.name} W`, align: 'right' },
          { key: 'b_won', label: `${B.name} W`, align: 'right' },
          { key: 'other', label: 'T/NR', align: 'right' },
          { key: 'average_first_innings', label: 'Avg 1st inns', align: 'right', render: r => fmtDec(r.average_first_innings, 1) },
          { key: 'last_played', label: 'Last met' },
          { key: 'focus', label: '', sortable: false, render: r => <Button size="xs" variant={f.venue_id === r.venue_id ? 'primary' : 'ghost'} onClick={() => setFilter('venue_id', r.venue_id)}>Focus</Button> },
        ]} />
      </Panel>
      {!v && !d.venues.length && <Unavailable title="Venue breakdown" reason="No venue is recorded for these matches." />}
    </div>
  );
}

/* --------------------------------------------------------------------- trends */

function Trends({ d }) {
  const A = d.teams.a, B = d.teams.b;
  const seasons = [...d.seasons].reverse();
  const cols = (key, label) => [
    { key, label, render: r => <span className="text-slate-100">{r[key]}</span> },
    { key: 'matches', label: 'M', align: 'right' },
    { key: 'a_won', label: `${A.name} W`, align: 'right' },
    { key: 'b_won', label: `${B.name} W`, align: 'right' },
    { key: 'other', label: 'T/NR/D', align: 'right', sortValue: r => r.tied + r.no_result + r.drawn, render: r => r.tied + r.no_result + r.drawn },
    { key: 'a_win_percentage', label: `${A.name} win %`, align: 'right', render: r => fmtPct(r.a_win_percentage) },
    { key: 'average_first_innings', label: 'Avg 1st inns', align: 'right', render: r => fmtDec(r.average_first_innings, 1) },
    { key: 'last_played', label: 'Last match', render: r => <MatchLink id={r.last_match_id} className="text-slate-300">{r.last_played}</MatchLink> },
  ];
  return (
    <div className="space-y-5">
      <GroupedBarChart title="Season-by-season results" subtitle="Wins per season in this fixture." categories={seasons.map(s => s.season)} stacked formatter={v => Math.round(v)} yLabel="Wins"
        series={[{ name: A.name, color: COLOR_A, values: seasons.map(s => s.a_won) }, { name: B.name, color: COLOR_B, values: seasons.map(s => s.b_won) }]} />
      {d.limited_overs && <ColumnChart title="Average first-innings score by season" subtitle="Complete matches only." data={seasons.map(s => ({ label: s.season, value: s.average_first_innings }))} formatter={v => fmtDec(v, 0)} yLabel="Runs"
        referenceY={d.baseline.average_first_innings} referenceLabel="Format avg" />}
      <Panel title="Season-wise head-to-head" bodyClassName="p-3"><DataTable dense pageSize={20} rows={d.seasons} rowKey={r => r.season} rowHref={r => matchUrl(r.last_match_id)} rowLabel={r => `Open the last match of season ${r.season}`} columns={cols('season', 'Season')} /></Panel>
      <Panel title="Competition-wise head-to-head" bodyClassName="p-3"><DataTable dense pageSize={20} rows={d.competitions} rowKey={r => r.competition} columns={cols('competition', 'Competition')} /></Panel>
    </div>
  );
}

/* ----------------------------------------------------------------- encounters */

function Encounters({ d, params }) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState(d.encounters);
  const [loading, setLoading] = useState(false);
  useEffect(() => { setPage(1); setData(d.encounters); }, [d]);
  useEffect(() => {
    if (page === 1) { setData(d.encounters); return; }
    setLoading(true);
    getTeamEncounters({ ...params, page, page_size: 10 }).then(setData).catch(() => {}).finally(() => setLoading(false));
  }, [page]); // eslint-disable-line react-hooks/exhaustive-deps
  const pages = Math.max(1, Math.ceil(data.total / data.page_size));
  const inn = i => (i ? <span className="num"><span className="text-slate-400">{i.team}</span> <span className="font-semibold text-white">{i.score}</span>{i.overs && <span className="text-slate-500"> ({i.overs})</span>}</span> : DASH);
  return (
    <Panel title="Recent encounters" subtitle="Newest first. Every row opens that match's details page." actions={<SampleBadge n={data.total} />} bodyClassName="p-3">
      <div className={loading ? 'opacity-60 transition-opacity' : ''}>
        <DataTable dense pageSize={0} rows={data.items} rowKey={r => r.match_id} rowHref={r => matchUrl(r.match_id)} rowLabel={r => `Open match: ${r.result}, ${r.date}`} columns={[
          { key: 'date', label: 'Date', render: r => <MatchLink id={r.match_id} className="font-medium text-slate-100">{r.date}</MatchLink> },
          { key: 'competition', label: 'Competition', render: r => <span>{r.competition || DASH} <span className="text-slate-500">{r.season}</span></span> },
          { key: 'venue', label: 'Venue', render: r => r.venue || DASH },
          { key: 'result', label: 'Result', render: r => <span className={r.winner_id === d.teams.a.id ? 'text-[var(--c1)]' : r.winner_id === d.teams.b.id ? 'text-[var(--c2)]' : 'text-slate-400'}>{r.result}{r.close && <Badge variant="amber" className="ml-1.5">close</Badge>}{r.reduced && <Badge className="ml-1.5">reduced</Badge>}</span> },
          { key: 'first', label: '1st innings', sortable: false, render: r => inn(r.first_innings) },
          { key: 'second', label: '2nd innings', sortable: false, render: r => inn(r.second_innings) },
          { key: 'toss', label: 'Toss', sortable: false, render: r => (r.toss_winner ? <span className="text-slate-400">{r.toss_winner}, {r.toss_decision}</span> : DASH) },
          ...(data.player_of_match_available ? [{ key: 'pom', label: 'Player of the match', sortable: false, render: r => r.player_of_match.map(p => p.name).join(', ') || DASH }] : []),
        ]} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 px-1 pt-3 text-2xs text-slate-500">
        <span>{!data.player_of_match_available && data.player_of_match_note}</span>
        {pages > 1 && <span className="flex items-center gap-1">
          <button className="btn btn-ghost btn-xs" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</button>
          <span className="num px-2">Page {page} of {pages}</span>
          <button className="btn btn-ghost btn-xs" disabled={page >= pages} onClick={() => setPage(p => p + 1)}>Next</button>
        </span>}
      </div>
    </Panel>
  );
}
