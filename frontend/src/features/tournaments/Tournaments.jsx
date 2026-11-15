/**
 * Tournament dashboards: season standings, leaders, head-to-head, venues and
 * season-on-season scoring trends. Data: GET /tournaments, /tournaments/detail.
 */
import { matchUrl } from '../../components/MatchLink';
import { useEffect, useMemo, useState } from 'react';
import { getTournamentDetail, getTournaments } from '../../services/api';
import { useUrlFilters } from '../../hooks/useFilters';
import { Callout, DashboardSkeleton, DataTable, EmptyState, ErrorState, FilterBar, FilterField, KpiGrid, MatchLink, PageHeader, Panel, PlayerLink, SampleBadge, Segmented, Select, Tabs } from '../../components/ui';
import { BarChart, GroupedBarChart, MultiSeriesLine, PALETTE } from '../../components/charts';
import { DASH, fmtAvg, fmtDec, fmtEcon, fmtInt, fmtPct, fmtSigned, fmtSR } from '../../lib/format';

const DEFAULTS = { gender: 'male', tournament: '', season: '' };

export default function Tournaments() {
  const [filters, setFilter, reset, active, setFilters] = useUrlFilters(DEFAULTS);
  const [list, setList] = useState(null);
  const [listError, setListError] = useState(null);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState('standings');

  useEffect(() => {
    let live = true;
    setList(null);
    getTournaments({ gender: filters.gender || undefined }).then(r => { if (live) setList(r.tournaments); }).catch(e => { if (live) setListError(e.message); });
    return () => { live = false; };
  }, [filters.gender]);

  const options = useMemo(() => (list || []).map(t => ({ id: `${t.name}|${t.format}|${t.gender}`, label: `${t.name} · ${t.format}${filters.gender ? '' : ` · ${t.gender}`} (${t.matches})`, t })), [list, filters.gender]);
  const selected = options.find(o => o.id === filters.tournament)?.t || options[0]?.t;

  const load = () => {
    if (!selected) return;
    setLoading(true); setError(null);
    getTournamentDetail({ name: selected.name, format: selected.format, gender: selected.gender, season: filters.season || undefined })
      .then(setDetail).catch(e => setError(e.message || 'Could not load tournament.')).finally(() => setLoading(false));
  };
  useEffect(load, [selected?.name, selected?.format, selected?.gender, filters.season]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div>
      <PageHeader eyebrow="Competitions" title="Tournament analytics" subtitle="Season standings, leading performers, head-to-head records and scoring trends reconstructed from stored ball-by-ball data." />
      <FilterBar onReset={reset} active={active}>
        <FilterField label="Gender"><Select value={filters.gender} onChange={v => setFilters({ gender: v, tournament: '', season: '' })} options={[{ id: 'male', label: 'Men' }, { id: 'female', label: 'Women' }]} placeholder="All" /></FilterField>
        <FilterField label="Competition" className="min-w-[16rem] flex-1">
          <Select value={selected ? `${selected.name}|${selected.format}|${selected.gender}` : ''} onChange={v => setFilters({ tournament: v, season: '' })} options={options} disabled={!list} />
        </FilterField>
        <FilterField label="Season"><Select value={detail?.season || filters.season} onChange={v => setFilter('season', v)} options={(selected?.seasons || []).map(s => ({ id: s, label: s }))} disabled={!selected} /></FilterField>
      </FilterBar>
      {listError && <ErrorState message={listError} />}
      {(!list || loading) && !error && <DashboardSkeleton />}
      {error && <ErrorState message={error} onRetry={load} />}
      {list && !list.length && <EmptyState message="No competitions with at least five stored matches." />}
      {detail && !loading && !error && (
        <div className="space-y-5">
          <SeasonHeadline detail={detail} />
          <Tabs value={tab} onChange={setTab} tabs={[{ id: 'standings', label: 'Standings' }, { id: 'leaders', label: 'Leaders' }, { id: 'h2h', label: 'Head-to-head' }, { id: 'matches', label: 'Results' }, { id: 'venues', label: 'Venues' }, { id: 'trends', label: 'Season trends' }]} />
          {tab === 'standings' && <Standings detail={detail} />}
          {tab === 'leaders' && <Leaders detail={detail} />}
          {tab === 'h2h' && <HeadToHead detail={detail} />}
          {tab === 'matches' && <Results detail={detail} />}
          {tab === 'venues' && <VenueBreakdown detail={detail} />}
          {tab === 'trends' && <Trends detail={detail} />}
        </div>
      )}
    </div>
  );
}

function SeasonHeadline({ detail }) {
  const t = detail.season_trends.find(x => x.season === detail.season);
  const topBat = detail.leading_batters[0], topBowl = detail.leading_bowlers[0];
  return (
    <KpiGrid items={[
      { label: 'Season', value: detail.season, sub: `${detail.name} · ${detail.format}` },
      { label: 'Matches', value: fmtInt(t?.matches) },
      { label: 'Avg 1st innings', value: fmtDec(t?.average_first_innings, 1) },
      { label: 'Run rate', value: fmtDec(t?.run_rate, 2) },
      { label: 'Most runs', value: topBat ? fmtInt(topBat.runs) : DASH, sub: topBat?.player },
      { label: 'Most wickets', value: topBowl ? fmtInt(topBowl.wickets) : DASH, sub: topBowl?.player },
    ]} />
  );
}

function Standings({ detail }) {
  return (
    <div className="space-y-4">
      <Callout>{detail.standings_note}</Callout>
      <Panel title={`${detail.season} results table`} bodyClassName="p-3">
        <DataTable pageSize={0} rows={detail.standings} rowKey={r => r.team_id} initialSort={{ key: 'position', dir: 'asc' }} columns={[
          { key: 'position', label: '#', align: 'right' },
          { key: 'team', label: 'Team', render: r => <span className="font-medium text-white">{r.team}</span> },
          { key: 'played', label: 'P', align: 'right' },
          { key: 'won', label: 'W', align: 'right', className: 'text-pos' },
          { key: 'lost', label: 'L', align: 'right', className: 'text-neg' },
          { key: 'tied', label: 'T', align: 'right' },
          { key: 'no_result', label: 'NR', align: 'right' },
          { key: 'points', label: 'Pts', align: 'right', render: r => <span className="font-semibold text-white">{r.points}</span> },
          { key: 'net_run_rate', label: 'NRR', align: 'right', render: r => fmtSigned(r.net_run_rate, 3), className: r => (r.net_run_rate > 0 ? 'text-pos' : r.net_run_rate < 0 ? 'text-neg' : '') },
          { key: 'win_percentage', label: 'Win %', align: 'right', render: r => fmtPct(r.win_percentage) },
          { key: 'for', label: 'For', align: 'right', sortable: false, render: r => `${fmtInt(r.runs_for)}/${r.overs_for}` },
          { key: 'against', label: 'Against', align: 'right', sortable: false, render: r => `${fmtInt(r.runs_against)}/${r.overs_against}` },
        ]} />
      </Panel>
      <GroupedBarChart title="Wins and losses by team" subtitle="Results across every stored match in the season." stacked
        categories={detail.standings.map(r => r.team.split(' ').map(w => w[0]).join(''))}
        series={[{ name: 'Won', color: PALETTE[1], values: detail.standings.map(r => r.won) }, { name: 'Lost', color: PALETTE[5], values: detail.standings.map(r => r.lost) }, { name: 'Tied / NR', color: 'var(--chart-muted)', values: detail.standings.map(r => r.tied + r.no_result) }]}
        formatter={v => fmtInt(v)} yLabel="Matches" footnote={`Team initials: ${detail.standings.map(r => `${r.team.split(' ').map(w => w[0]).join('')} = ${r.team}`).join(' · ')}`} />
    </div>
  );
}

function Leaders({ detail }) {
  const [metric, setMetric] = useState('runs');
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <BarChart title={metric === 'runs' ? 'Leading run-scorers' : 'Highest strike rates (100+ balls)'} subtitle={metric === 'runs' ? 'Runs off the bat in the season.' : 'Runs per 100 balls among batters with at least 100 balls faced.'}
          data={(metric === 'runs' ? detail.leading_batters : detail.leading_batters.filter(b => b.balls >= 100).sort((a, b) => b.strike_rate - a.strike_rate)).slice(0, 10).map(b => ({ label: `${b.player} · ${b.innings} inns`, value: metric === 'runs' ? b.runs : b.strike_rate }))}
          formatter={v => (metric === 'runs' ? fmtInt(v) : fmtSR(v))} color={PALETTE[0]}
          actions={<Segmented size="xs" label="Batting metric" value={metric} onChange={setMetric} options={[{ id: 'runs', label: 'Runs' }, { id: 'sr', label: 'Strike rate' }]} />} />
        <BarChart title="Leading wicket-takers" subtitle="Bowler-credited wickets in the season." data={detail.leading_bowlers.slice(0, 10).map(b => ({ label: `${b.player} · econ ${fmtEcon(b.economy)}`, value: b.wickets }))} formatter={v => fmtInt(v)} color={PALETTE[2]} />
      </div>
      <Panel title="Batting leaders" subtitle="Top 20 by runs." bodyClassName="p-3">
        <DataTable dense pageSize={0} rows={detail.leading_batters} rowKey={r => r.player_id} initialSort={{ key: 'runs', dir: 'desc' }} columns={[
          { key: 'player', label: 'Batter', render: r => <PlayerLink id={r.player_id} name={r.player} /> },
          { key: 'innings', label: 'Inns', align: 'right' },
          { key: 'runs', label: 'Runs', align: 'right', render: r => <span className="font-semibold text-white">{fmtInt(r.runs)}</span> },
          { key: 'balls', label: 'Balls', align: 'right' },
          { key: 'average', label: 'Avg', align: 'right', render: r => fmtAvg(r.average) },
          { key: 'strike_rate', label: 'SR', align: 'right', render: r => fmtSR(r.strike_rate) },
          { key: 'highest', label: 'HS', align: 'right', render: r => <MatchLink id={r.highest_match_id}>{r.highest}</MatchLink> },
          { key: 'fifties', label: '50s', align: 'right' },
          { key: 'hundreds', label: '100s', align: 'right' },
          { key: 'fours', label: '4s', align: 'right' },
          { key: 'sixes', label: '6s', align: 'right' },
        ]} />
      </Panel>
      <Panel title="Bowling leaders" subtitle="Top 20 by wickets (ties broken by economy)." bodyClassName="p-3">
        <DataTable dense pageSize={0} rows={detail.leading_bowlers} rowKey={r => r.player_id} initialSort={{ key: 'wickets', dir: 'desc' }} columns={[
          { key: 'player', label: 'Bowler', render: r => <PlayerLink id={r.player_id} name={r.player} /> },
          { key: 'innings', label: 'Inns', align: 'right' },
          { key: 'balls', label: 'Overs', align: 'right', render: r => r.overs },
          { key: 'wickets', label: 'Wkts', align: 'right', render: r => <span className="font-semibold text-white">{r.wickets}</span> },
          { key: 'runs', label: 'Runs', align: 'right' },
          { key: 'economy', label: 'Econ', align: 'right', render: r => fmtEcon(r.economy) },
          { key: 'average', label: 'Avg', align: 'right', render: r => fmtAvg(r.average) },
          { key: 'strike_rate', label: 'SR', align: 'right', render: r => fmtDec(r.strike_rate, 1) },
          { key: 'dot_percentage', label: 'Dot %', align: 'right', render: r => fmtPct(r.dot_percentage) },
          { key: 'best', label: 'Best', align: 'right', sortable: false, render: r => <MatchLink id={r.best_match_id}>{r.best}</MatchLink> },
        ]} />
      </Panel>
    </div>
  );
}

function HeadToHead({ detail }) {
  const { teams, cells } = detail.head_to_head;
  const get = (a, b) => cells.find(c => c.team_id === a && c.opponent_id === b);
  const initials = n => (n || '').split(' ').map(w => w[0]).join('');
  return (
    <Panel title="Head-to-head this season" subtitle="Row team's wins–losses against the column team. Tied and no-result games are shown after a slash." bodyClassName="p-3 overflow-x-auto">
      <table className="text-xs">
        <thead><tr><th className="sticky left-0 bg-surface" />{teams.map(t => <th key={t.team_id} title={t.team} className="px-2 py-1.5 text-center font-semibold text-slate-400">{initials(t.team)}</th>)}</tr></thead>
        <tbody>
          {teams.map(r => (
            <tr key={r.team_id} className="border-t border-line/60">
              <th className="sticky left-0 whitespace-nowrap bg-surface py-1.5 pr-3 text-left font-medium text-slate-200">{r.team}</th>
              {teams.map(c => {
                if (r.team_id === c.team_id) return <td key={c.team_id} className="bg-slate-900 px-2 py-1.5" />;
                const cell = get(r.team_id, c.team_id);
                if (!cell) return <td key={c.team_id} className="px-2 py-1.5 text-center text-slate-600">{DASH}</td>;
                const tone = cell.won > cell.lost ? 'bg-pos-muted/60 text-pos' : cell.won < cell.lost ? 'bg-neg-muted/50 text-neg' : 'text-slate-300';
                return <td key={c.team_id} className={`num px-2 py-1.5 text-center ${tone}`} title={`${r.team} v ${c.team}: won ${cell.won}, lost ${cell.lost}, other ${cell.other}`}>{cell.won}–{cell.lost}{cell.other ? `/${cell.other}` : ''}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function Results({ detail }) {
  return (
    <Panel title={`${detail.season} results`} subtitle="Every stored match in date order; open a match for the full scorecard and analysis." bodyClassName="p-3">
      <DataTable rows={detail.matches} rowKey={r => r.match_id} rowHref={r => matchUrl(r.match_id)} rowLabel={r => `Open match ${r.team1} v ${r.team2}, ${r.date}`} searchKeys={['team1', 'team2', 'venue', 'winner']} searchPlaceholder="Search team or venue…" pageSize={25} initialSort={{ key: 'date', dir: 'asc' }} columns={[
        { key: 'date', label: 'Date', render: r => <MatchLink id={r.match_id} className="text-slate-300">{r.date}</MatchLink> },
        { key: 'fixture', label: 'Match', sortable: false, render: r => <MatchLink id={r.match_id} className="text-slate-100">{r.team1} v {r.team2}</MatchLink> },
        { key: 'scores', label: 'Scores', sortable: false, render: r => <span className="num text-slate-400">{r.innings.map(i => `${(i.team || '').split(' ').map(w => w[0]).join('')} ${i.runs}/${i.wickets} (${i.overs})`).join(' · ')}</span> },
        { key: 'winner', label: 'Result', render: r => r.winner ? `${r.winner}${r.margin ? ` by ${r.margin}` : ''}` : (r.result_type || DASH) },
        { key: 'venue', label: 'Venue', render: r => <span className="block max-w-[14rem] truncate" title={r.venue}>{r.venue || DASH}</span> },
      ]} />
    </Panel>
  );
}

function VenueBreakdown({ detail }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <BarChart title="Average first-innings score by venue" subtitle="Season matches at each venue; small samples are flagged in the table." data={detail.venues.filter(v => v.average_first_innings != null).map(v => ({ label: `${v.venue} · n=${v.matches}`, value: v.average_first_innings }))} formatter={v => fmtDec(v, 1)} color={PALETTE[3]} />
      <Panel title="Venue summary" bodyClassName="p-3">
        <DataTable dense pageSize={0} rows={detail.venues} rowKey={r => r.venue_id} initialSort={{ key: 'matches', dir: 'desc' }} columns={[
          { key: 'venue', label: 'Venue', render: r => <span className="block max-w-[14rem] truncate" title={r.venue}>{r.venue}</span> },
          { key: 'matches', label: 'Matches', align: 'right', render: r => <SampleBadge n={r.matches} unit="" low={3} ok={6} /> },
          { key: 'average_first_innings', label: 'Avg 1st inns', align: 'right', render: r => fmtDec(r.average_first_innings, 1) },
          { key: 'batting_first_win_percentage', label: 'Bat-first win %', align: 'right', render: r => fmtPct(r.batting_first_win_percentage) },
        ]} />
      </Panel>
    </div>
  );
}

function Trends({ detail }) {
  const [metric, setMetric] = useState('scores');
  const t = detail.season_trends;
  const series = metric === 'scores'
    ? [{ name: 'Avg 1st innings', points: t.map(x => ({ x: x.season, y: x.average_first_innings })) }, { name: 'Avg 2nd innings', points: t.map(x => ({ x: x.season, y: x.average_second_innings })) }]
    : metric === 'rate' ? [{ name: 'Run rate', points: t.map(x => ({ x: x.season, y: x.run_rate })) }]
      : [{ name: 'Sixes per match', points: t.map(x => ({ x: x.season, y: x.sixes_per_match })) }, { name: 'Fours per match', points: t.map(x => ({ x: x.season, y: x.fours_per_match })) }, { name: 'Wickets per match', points: t.map(x => ({ x: x.season, y: x.wickets_per_match })) }];
  return (
    <div className="space-y-4">
      <MultiSeriesLine categorical title="Season-on-season scoring" subtitle="Every stored season of this competition. Super overs excluded." xLabel="Season" yLabel={metric === 'scores' ? 'Runs' : metric === 'rate' ? 'Runs per over' : 'Per match'}
        yFormatter={v => fmtDec(v, metric === 'rate' ? 2 : 0)} sample={t.length} sampleUnit="seasons" yMin={metric === 'scores' ? undefined : 0}
        actions={<Segmented label="Trend metric" value={metric} onChange={setMetric} options={[{ id: 'scores', label: 'Innings scores' }, { id: 'rate', label: 'Run rate' }, { id: 'events', label: 'Boundaries & wickets' }]} />}
        series={series} />
      <Panel title="Season comparison" bodyClassName="p-3">
        <DataTable dense pageSize={0} rows={t} rowKey={r => r.season} initialSort={{ key: 'season', dir: 'desc' }} columns={[
          { key: 'season', label: 'Season' },
          { key: 'matches', label: 'Matches', align: 'right' },
          { key: 'average_first_innings', label: 'Avg 1st', align: 'right', render: r => fmtDec(r.average_first_innings, 1) },
          { key: 'average_second_innings', label: 'Avg 2nd', align: 'right', render: r => fmtDec(r.average_second_innings, 1) },
          { key: 'run_rate', label: 'RR', align: 'right', render: r => fmtDec(r.run_rate, 2) },
          { key: 'sixes_per_match', label: '6s / match', align: 'right', render: r => fmtDec(r.sixes_per_match, 1) },
          { key: 'fours_per_match', label: '4s / match', align: 'right', render: r => fmtDec(r.fours_per_match, 1) },
          { key: 'wickets_per_match', label: 'Wkts / match', align: 'right', render: r => fmtDec(r.wickets_per_match, 1) },
          { key: 'highest_total', label: 'Highest', align: 'right', render: r => <MatchLink id={r.highest_total_match_id}>{r.highest_total}</MatchLink> },
        ]} />
      </Panel>
    </div>
  );
}
