/**
 * Batter vs bowler matchup intelligence.
 * Data: GET /matchups/player-analysis (+ player-venues). Every figure is derived
 * server-side from the deliveries between the two players in one pass, so every
 * split adds up to the headline numbers.
 */
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getMatchupPlayerVenues, getPlayerMatchup } from '../../services/api';
import { useUrlFilters } from '../../hooks/useFilters';
import { Badge, Button, Callout, DashboardSkeleton, DataTable, EmptyState, ErrorState, FilterBar, FilterField, MatchLink, Panel, SampleBadge, Select, StatCard, Tabs } from '../../components/ui';
import { matchUrl } from '../../components/MatchLink';
import { BarChart, ColumnChart, DonutChart, GroupedBarChart, MultiSeriesLine, PALETTE } from '../../components/charts';
import { DASH, FORMATS, fmtDec, fmtPct, phaseLabel } from '../../lib/format';
import { MethodNote, Unavailable } from '../competition/shared';
import { COLOR_A, COLOR_B, ContributionNote, DateField, InsightCards, PlayerPicker } from './matchupUi';

const DEFAULTS = { batter: '', bowler: '', pformat: '', competition: '', season: '', date_from: '', date_to: '', venue_id: '', innings: '', side: '', recent: '', tab: 'overview' };
const TABS = [
  { id: 'overview', label: 'Head-to-head' }, { id: 'phases', label: 'Phases & overs' }, { id: 'context', label: 'Context & venues' },
  { id: 'trends', label: 'Trends' }, { id: 'encounters', label: 'Match by match' }, { id: 'insights', label: 'Insights' },
];
const PRESETS = [['Virat Kohli', 'Jasprit Bumrah'], ['Rohit Sharma', 'Trent Boult'], ['MS Dhoni', 'Sunil Narine'], ['David Warner', 'Ravichandran Ashwin'], ['Jos Buttler', 'Rashid Khan']];
const SIDE_LABEL = { home: 'Home', away: 'Away', neutral: 'Neutral', unclassified: 'Unclassified' };
const sr = v => fmtDec(v, 1);

export default function PlayerMatchup() {
  const [f, setFilter, reset, active, setFilters] = useUrlFilters(DEFAULTS);
  const [names, setNames] = useState({});
  const [venues, setVenues] = useState([]);
  const [seasonOpts, setSeasonOpts] = useState([]);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const params = useMemo(() => ({ batter_id: f.batter, bowler_id: f.bowler, format: f.pformat, competition: f.competition, season: f.season, date_from: f.date_from,
    date_to: f.date_to, venue_id: f.venue_id, innings: f.innings, side: f.side, recent: f.recent }), [f]);
  const key = JSON.stringify({ ...params });
  const load = () => {
    if (!f.batter || !f.bowler) { setData(null); return; }
    setLoading(true); setError(null);
    getPlayerMatchup(params).then(r => {
      setData(r);
      setNames({ batter: r.batter.name, bowler: r.bowler.name });
      setSeasonOpts(s => [...new Set([...s, ...r.seasons.map(x => x.season)])].sort().reverse());
    }).catch(e => setError(e.message)).finally(() => setLoading(false));
  };
  useEffect(load, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!f.batter || !f.bowler) { setVenues([]); return; }
    getMatchupPlayerVenues({ batter_id: f.batter, bowler_id: f.bowler, format: f.pformat }).then(r => setVenues(r.venues)).catch(() => setVenues([]));
  }, [f.batter, f.bowler, f.pformat]);
  useEffect(() => { setSeasonOpts([]); }, [f.batter, f.bowler]);

  const pickPreset = async ([bat, bowl]) => {
    const { getPlayers } = await import('../../services/api');
    const [a, b] = await Promise.all([getPlayers({ name: bat, page_size: 5 }), getPlayers({ name: bowl, page_size: 5 })]);
    const pa = a.players.find(p => p.name === bat) || a.players[0], pb = b.players.find(p => p.name === bowl) || b.players[0];
    if (pa && pb) { setNames({ batter: pa.name, bowler: pb.name }); setFilters({ batter: pa.id, bowler: pb.id, venue_id: '', tab: 'overview' }); }
  };

  return (
    <div>
      <FilterBar onReset={reset} active={active - (f.tab !== 'overview' ? 1 : 0)}
        note="Balls faced exclude wides. Average uses bowler-credited dismissals. Super overs are excluded. Phases are only compared within a format family (T20/T20I, ODI/one-day).">
        <PlayerPicker label="Batter" accent={COLOR_A} value={f.batter ? { id: f.batter, name: names.batter } : null} onChange={p => { setNames(n => ({ ...n, batter: p?.name })); setFilters({ batter: p?.id || '', venue_id: '' }); }} />
        <Button size="sm" variant="ghost" className="h-9 self-end" icon="refresh" aria-label="Swap batter and bowler" title="Swap roles (view the reverse matchup)"
          disabled={!f.batter || !f.bowler} onClick={() => { setNames(n => ({ batter: n.bowler, bowler: n.batter })); setFilters({ batter: f.bowler, bowler: f.batter, venue_id: '' }); }}>Swap</Button>
        <PlayerPicker label="Bowler" accent={COLOR_B} value={f.bowler ? { id: f.bowler, name: names.bowler } : null} onChange={p => { setNames(n => ({ ...n, bowler: p?.name })); setFilters({ bowler: p?.id || '', venue_id: '' }); }} />
        <FilterField label="Format"><Select value={f.pformat} onChange={v => setFilters({ pformat: v, season: '', venue_id: '' })} options={FORMATS} placeholder="All formats" /></FilterField>
        <FilterField label="Competition">
          <input key={f.competition} type="search" defaultValue={f.competition} placeholder="e.g. Premier League" aria-label="Competition"
            onBlur={e => e.target.value.trim() !== f.competition && setFilter('competition', e.target.value.trim())}
            onKeyDown={e => e.key === 'Enter' && setFilter('competition', e.currentTarget.value.trim())} className="h-9 w-40 px-3 text-[13px]" />
        </FilterField>
        <FilterField label="Season"><Select value={f.season} onChange={v => setFilter('season', v)} options={seasonOpts} placeholder="All" className="w-28" /></FilterField>
        <DateField label="From date" value={f.date_from} onChange={v => setFilter('date_from', v)} />
        <DateField label="To date" value={f.date_to} onChange={v => setFilter('date_to', v)} />
        <FilterField label="Venue" className="min-w-[12rem]"><Select value={f.venue_id} onChange={v => setFilter('venue_id', v)} placeholder="All venues" className="max-w-[16rem]" options={venues.map(v => ({ id: v.id, label: `${v.name}${v.city ? `, ${v.city}` : ''}` }))} /></FilterField>
        <FilterField label="Batter at"><Select value={f.side} onChange={v => setFilter('side', v)} placeholder="Home & away" options={[{ id: 'home', label: 'Home' }, { id: 'away', label: 'Away' }, { id: 'neutral', label: 'Neutral' }]} /></FilterField>
        <FilterField label="Innings"><Select value={f.innings} onChange={v => setFilter('innings', v)} placeholder="All" options={[{ id: '1', label: '1st' }, { id: '2', label: '2nd' }, { id: '3', label: '3rd' }, { id: '4', label: '4th' }]} className="w-24" /></FilterField>
        <FilterField label="Encounters"><Select value={f.recent} onChange={v => setFilter('recent', v)} placeholder="All" options={[{ id: '5', label: 'Last 5' }, { id: '10', label: 'Last 10' }, { id: '20', label: 'Last 20' }]} className="w-24" /></FilterField>
      </FilterBar>

      {(!f.batter || !f.bowler) && (
        <div className="panel">
          <EmptyState icon="matchups" message="Choose a batter and a bowler." hint="Search any two players in the database. Every number is computed from their ball-by-ball meetings."
            action={<div className="flex flex-wrap justify-center gap-2">{PRESETS.map(p => <Button key={p.join()} size="xs" variant="secondary" onClick={() => pickPreset(p)}>{p[0].split(' ').pop()} v {p[1].split(' ').pop()}</Button>)}</div>} />
        </div>
      )}
      {loading && <DashboardSkeleton />}
      {error && <ErrorState message={error} onRetry={load} />}
      {data && !loading && !error && <Analysis d={data} f={f} setFilter={setFilter} venueName={venues.find(v => v.id === f.venue_id)?.name} />}
    </div>
  );
}

function Analysis({ d, f, setFilter, venueName }) {
  const o = d.overall;
  const chips = [f.pformat || 'All formats', f.competition && `“${f.competition}”`, f.season && `Season ${f.season}`, (f.date_from || f.date_to) && `${f.date_from || '…'} → ${f.date_to || '…'}`,
    venueName && `at ${venueName}`, f.side && `batter ${f.side}`, f.innings && `innings ${f.innings}`, f.recent && `last ${f.recent}`].filter(Boolean);
  return (
    <div className="space-y-5 animate-fade-in">
      <ContributionNote>
        <span className="num font-medium text-slate-300">{d.matches} match{d.matches === 1 ? '' : 'es'} · {o.balls} balls contribute</span>
        {chips.map(c => <Badge key={c} variant="indigo">{c}</Badge>)}
        {d.formats_mixed && <Badge variant="amber">mixes {d.formats.map(x => x.format).join(' + ')} — choose a format to isolate one</Badge>}
      </ContributionNote>

      <section className="panel-hero p-6 sm:p-7">
        <div className="relative flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <Link to={`/players/${d.batter.id}`} className="text-[26px] font-semibold tracking-tight hover:underline" style={{ color: COLOR_A }}>{d.batter.name}</Link>
              <span className="text-slate-500">vs</span>
              <Link to={`/players/${d.bowler.id}`} className="text-[26px] font-semibold tracking-tight hover:underline" style={{ color: COLOR_B }}>{d.bowler.name}</Link>
            </div>
            <p className="mt-1.5 text-[13px] text-slate-400">
              {d.bowler.style || (d.bowler.type ? `${d.bowler.type} bowler` : 'Bowling style not recorded')}
              {d.first_met && ` · met ${d.matches} times, ${d.first_met.slice(0, 4)}–${d.last_met.slice(0, 4)}`}
            </p>
          </div>
          <SampleBadge n={o.balls} unit="balls" low={30} ok={120} />
        </div>
        {o.balls > 0 && (
          <div className="relative mt-6 grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4 lg:grid-cols-8">
            {[['Runs', o.runs], ['Balls', o.balls], ['Dismissals', o.dismissals, o.other_dismissals ? `+${o.other_dismissals} not credited` : 'bowler-credited'], ['Strike rate', sr(o.strike_rate)],
              ['Average', fmtDec(o.average)], ['Balls / dismissal', fmtDec(o.balls_per_dismissal, 1)], ['Dot %', fmtPct(o.dot_percentage)], ['Boundary %', fmtPct(o.boundary_percentage), `${o.fours}×4 · ${o.sixes}×6`]].map(([l, v, s]) => (
              <div key={l} className="min-w-0"><div className="text-2xs text-slate-500">{l}</div><div className="display-num text-[24px] leading-tight text-white">{v ?? DASH}</div>{s && <div className="truncate text-3xs text-slate-500">{s}</div>}</div>
            ))}
          </div>
        )}
      </section>

      {o.balls === 0 ? <div className="panel"><EmptyState message="These players have not faced each other under the selected filters." hint="Try All formats, clear the venue or date range, or swap roles." /></div> : (
        <>
          <Tabs tabs={TABS} value={f.tab || 'overview'} onChange={v => setFilter('tab', v)} />
          {f.tab === 'phases' ? <Phases d={d} />
            : f.tab === 'context' ? <Context d={d} f={f} setFilter={setFilter} />
              : f.tab === 'trends' ? <Trends d={d} />
                : f.tab === 'encounters' ? <ByMatch d={d} />
                  : f.tab === 'insights' ? <Panel title="Matchup insights" subtitle="Generated from the calculations on this page; each states its sample and statistical basis. Historical observations, not predictions."><InsightCards items={d.insights} /></Panel>
                    : <Overview d={d} setFilter={setFilter} />}
          <MethodNote items={[...d.notes, d.context.note]} />
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ overview */

function Overview({ d, setFilter }) {
  const o = d.overall;
  const dis = d.dismissals;
  const base = d.context.batter_vs_type;
  const dist = d.scoring_distribution.filter(x => x.label !== 'other' || x.balls);
  return (
    <div className="space-y-5">
      <Panel title="Key insights" actions={<Button size="xs" variant="ghost" iconRight="arrowRight" onClick={() => setFilter('tab', 'insights')}>All insights</Button>}>
        <InsightCards items={d.insights} limit={4} />
      </Panel>
      <div className="grid gap-4 lg:grid-cols-3">
        <ColumnChart className="lg:col-span-2" title="Scoring distribution" subtitle="Balls faced by outcome; the line shows the runs each outcome produced."
          data={dist.map(x => ({ label: x.label === '0' ? 'Dot' : x.label === 'other' ? '5+/all-run' : `${x.label}${x.label === '4' || x.label === '6' ? ' (bdy)' : ''}`, value: x.balls, line: x.runs }))}
          barLabel="Balls" lineLabel="Runs" yLabel="Balls" y2Label="Runs" sample={o.balls} sampleUnit="balls" />
        <DonutChart title="Dismissal methods" subtitle={`${dis.total} dismissal${dis.total === 1 ? '' : 's'} on this bowler's deliveries; ${dis.bowler_credited} credited to the bowler.`}
          data={Object.entries(dis.by_type).map(([k, v], i) => ({ label: k, value: v, color: PALETTE[i % PALETTE.length] }))} centerLabel="OUTS" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Bowler vs batter" subtitle="From the bowler's side of the contest.">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <StatCard label="Economy" value={fmtDec(o.economy)} sub={`${o.runs_conceded} runs off ${o.legal_balls} legal balls`} />
            <StatCard label="Dismissal every" value={o.balls_per_dismissal ? `${fmtDec(o.balls_per_dismissal, 1)} b` : DASH} sub="bowler-credited" />
            <StatCard label="Dot-ball %" value={fmtPct(o.dot_percentage)} />
            <StatCard label="Boundary every" value={o.fours + o.sixes ? `${fmtDec(o.balls / (o.fours + o.sixes), 1)} b` : DASH} />
            <StatCard label="Wides / no-balls" value={`${o.wides} / ${o.no_balls}`} sub="wides never count as balls faced" />
            <StatCard label="Boundary share of runs" value={fmtPct(o.boundary_run_percentage)} />
          </div>
        </Panel>
        <Panel title={`Against ${d.bowler.type || 'this type of'} bowling generally`}
          subtitle={base ? `${d.batter.name} against all ${d.bowler.type} bowlers under the same filters (${d.context.baseline_formats.join(', ')}).` : 'Baseline unavailable.'}>
          {base ? (
            <table className="w-full text-[13px]"><thead><tr className="text-2xs text-slate-500"><th className="py-1 text-left font-medium">Metric</th><th className="text-right font-medium">vs {d.bowler.name}</th><th className="text-right font-medium">vs all {d.bowler.type}</th></tr></thead>
              <tbody className="num">
                {[['Strike rate', o.strike_rate, base.strike_rate, sr], ['Balls / dismissal', o.all_dismissals ? o.balls / o.all_dismissals : null, base.balls_per_dismissal, v => fmtDec(v, 1)], ['Dot %', o.dot_percentage, base.dot_percentage, fmtPct], ['Boundary %', o.boundary_percentage, base.boundary_percentage, fmtPct], ['Balls', o.balls, base.balls, v => Number(v).toLocaleString()]].map(([l, a, b, fm]) => (
                  <tr key={l} className="border-t border-line-soft"><td className="py-2 text-slate-400">{l}</td><td className="text-right text-slate-100">{a == null ? DASH : fm(a)}</td><td className="text-right text-slate-400">{b == null ? DASH : fm(b)}</td></tr>
                ))}
              </tbody></table>
          ) : <Unavailable title="Bowling-type baseline" reason="This bowler has no verified pace/spin classification, so no like-for-like comparison is drawn." />}
          {base && <p className="mt-2 text-3xs text-slate-500">Balls/dismissal here counts all dismissals while on strike (including run outs), matching the baseline's definition.</p>}
        </Panel>
      </div>
      {dis.events.length > 0 && (
        <Panel title="Dismissal log" subtitle="Each dismissal opens its match." bodyClassName="p-3">
          <DataTable dense pageSize={10} rows={dis.events} rowKey={(r, i) => `${r.match_id}-${i}`} rowHref={r => matchUrl(r.match_id, { tab: 'scorecard', playerId: d.batter.id, focus: 'batting' })} columns={[
            { key: 'date', label: 'Date', render: r => <MatchLink id={r.match_id} className="text-slate-100">{r.date}</MatchLink> },
            { key: 'type', label: 'How out' }, { key: 'credited', label: 'Bowler credited', render: r => (r.credited ? 'Yes' : 'No') },
            { key: 'over', label: 'Ball', align: 'right' }, { key: 'phase', label: 'Phase', render: r => r.phase || DASH },
          ]} />
        </Panel>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------- phases */

function Phases({ d }) {
  const [fam, setFam] = useState(d.phases[0]?.family);
  const p = d.phases.find(x => x.family === fam) || d.phases[0];
  if (!p) return <Unavailable title="Phase analysis" reason="Phases are defined for limited-overs cricket only; these players met only in multi-day matches under the filters." />;
  const fmt = fam === 'T20' ? 'T20' : 'ODI';
  return (
    <div className="space-y-5">
      {d.phases.length > 1 && <Callout>Phases are compared within one format family at a time. <span className="ml-2 inline-flex gap-1">{d.phases.map(x => <Button key={x.family} size="xs" variant={x.family === fam ? 'primary' : 'ghost'} onClick={() => setFam(x.family)}>{x.family} ({x.balls} balls)</Button>)}</span></Callout>}
      <div className="grid gap-4 lg:grid-cols-3">
        {p.phases.map(ph => (
          <Panel key={ph.phase} title={phaseLabel(fmt, ph.phase)} actions={<SampleBadge n={ph.balls} unit="balls" low={18} ok={60} />}>
            {ph.balls ? (
              <div className="grid grid-cols-3 gap-3">
                {[['Runs', ph.runs], ['SR', sr(ph.strike_rate)], ['Outs', ph.dismissals], ['Dot %', fmtPct(ph.dot_percentage)], ['Bdy %', fmtPct(ph.boundary_percentage)], ['Econ', fmtDec(ph.economy)]].map(([l, v]) => (
                  <div key={l}><div className="text-3xs text-slate-500">{l}</div><div className="num text-[17px] font-semibold text-slate-50">{v}</div></div>
                ))}
              </div>
            ) : <p className="text-sm text-slate-500">No balls in this phase.</p>}
          </Panel>
        ))}
      </div>
      <GroupedBarChart title="Strike rate vs dot % by phase" categories={p.phases.map(x => phaseLabel(fmt, x.phase))} formatter={v => fmtDec(v, 0)}
        series={[{ name: 'Strike rate', color: COLOR_A, values: p.phases.map(x => x.strike_rate) }, { name: 'Dot %', color: COLOR_B, values: p.phases.map(x => x.dot_percentage) }]} />
      <ColumnChart title="Over by over" subtitle={`${fam} family. Bars = runs off the bat; line = balls faced in that over.`} data={p.overs.map(x => ({ label: String(x.over), value: x.runs, line: x.balls, markers: x.dismissals || undefined }))}
        barLabel="Runs" lineLabel="Balls" xLabel="Over" yLabel="Runs" y2Label="Balls" sample={p.balls} sampleUnit="balls" markerLabel="Dismissals" />
    </div>
  );
}

/* ---------------------------------------------------------- context & venues */

function SplitTable({ rows, labelKey, label, renderLabel, href }) {
  return (
    <DataTable dense pageSize={10} rows={rows} rowKey={r => String(r[labelKey])} rowHref={href} columns={[
      { key: labelKey, label, render: renderLabel || (r => <span className="text-slate-100">{r[labelKey]}</span>) },
      { key: 'matches', label: 'M', align: 'right' }, { key: 'balls', label: 'Balls', align: 'right' }, { key: 'runs', label: 'Runs', align: 'right' },
      { key: 'dismissals', label: 'Outs', align: 'right' }, { key: 'strike_rate', label: 'SR', align: 'right', render: r => sr(r.strike_rate) },
      { key: 'average', label: 'Avg', align: 'right', render: r => fmtDec(r.average) }, { key: 'dot_percentage', label: 'Dot %', align: 'right', render: r => fmtPct(r.dot_percentage) },
      { key: 'economy', label: 'Econ', align: 'right', render: r => fmtDec(r.economy) },
    ]} />
  );
}

function Context({ d, f, setFilter }) {
  const v = d.context.venue;
  const bo = d.context.bowler_overall, ba = d.context.batter_overall;
  return (
    <div className="space-y-5">
      {v ? (
        <>
          <Callout tone={d.overall.balls < 30 ? 'warn' : 'info'}>Venue focus: <strong>{v.venue?.canonical_name}</strong>. The head-to-head above is limited to this ground ({d.overall.balls} balls). Below, each player's record at the ground against everyone, compared with their record everywhere under the same filters.</Callout>
          <div className="grid gap-4 md:grid-cols-2">
            <Panel title={`${d.batter.name} at this venue`} subtitle={`All bowlers · ${v.batter.innings} innings`}>
              <CompareRows rows={[['Strike rate', v.batter.strike_rate, ba.strike_rate, sr], ['Average', v.batter.average, ba.average, fmtDec], ['Balls / dismissal', v.batter.balls_per_dismissal, ba.balls_per_dismissal, v2 => fmtDec(v2, 1)], ['Dot %', v.batter.dot_percentage, ba.dot_percentage, fmtPct], ['Boundary %', v.batter.boundary_percentage, ba.boundary_percentage, fmtPct], ['Runs', v.batter.runs, ba.runs, x => x]]} />
              <PhaseMini rows={v.batter.phases} kind="bat" />
            </Panel>
            <Panel title={`${d.bowler.name} at this venue`} subtitle={`All batters · ${v.bowler.innings} innings`}>
              <CompareRows rows={[['Economy', v.bowler.economy, bo.economy, fmtDec], ['Average', v.bowler.average, bo.average, fmtDec], ['Strike rate', v.bowler.strike_rate, bo.strike_rate, v2 => fmtDec(v2, 1)], ['Dot %', v.bowler.dot_percentage, bo.dot_percentage, fmtPct], ['Wickets', v.bowler.wickets, bo.wickets, x => x]]} />
              <PhaseMini rows={v.bowler.phases} kind="bowl" />
            </Panel>
          </div>
        </>
      ) : <Callout>Pick a venue (filter bar, or <strong>Focus</strong> below) to see each player's record at that ground and this matchup there.</Callout>}
      <Panel title="By venue" subtitle="Where they have met. Focus a ground to analyse it." bodyClassName="p-3" actions={f.venue_id && <Button size="xs" variant="ghost" onClick={() => setFilter('venue_id', '')}>Clear venue</Button>}>
        <DataTable dense pageSize={10} rows={d.venues} rowKey={r => r.venue_id || 'none'} columns={[
          { key: 'venue', label: 'Venue', render: r => (r.venue_id ? <Link to={`/venues/${r.venue_id}`} className="text-slate-100 hover:text-accent-soft">{r.venue}</Link> : DASH) },
          { key: 'matches', label: 'M', align: 'right' }, { key: 'balls', label: 'Balls', align: 'right' }, { key: 'runs', label: 'Runs', align: 'right' },
          { key: 'dismissals', label: 'Outs', align: 'right' }, { key: 'strike_rate', label: 'SR', align: 'right', render: r => sr(r.strike_rate) },
          { key: 'last_date', label: 'Last met', render: r => <MatchLink id={r.last_match_id} className="text-slate-300">{r.last_date}</MatchLink> },
          { key: 'focus', label: '', sortable: false, render: r => r.venue_id && <Button size="xs" variant={f.venue_id === r.venue_id ? 'primary' : 'ghost'} onClick={() => setFilter('venue_id', r.venue_id)}>Focus</Button> },
        ]} />
      </Panel>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Home vs away (batter's side)" subtitle="Evidence-based home/away; matches without evidence are 'unclassified'." bodyClassName="p-3">
          <SplitTable rows={d.home_away} labelKey="side" label="Side" renderLabel={r => SIDE_LABEL[r.side] || r.side} />
        </Panel>
        <Panel title="First vs second innings" bodyClassName="p-3"><SplitTable rows={d.innings_split} labelKey="innings" label="Innings" renderLabel={r => `Innings ${r.innings}`} /></Panel>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="By competition" bodyClassName="p-3"><SplitTable rows={d.competitions} labelKey="competition" label="Competition" /></Panel>
        <Panel title="By format" bodyClassName="p-3"><SplitTable rows={d.formats} labelKey="format" label="Format" /></Panel>
      </div>
    </div>
  );
}

function CompareRows({ rows }) {
  return (
    <table className="w-full text-[13px]"><thead><tr className="text-2xs text-slate-500"><th className="py-1 text-left font-medium">Metric</th><th className="text-right font-medium">At venue</th><th className="text-right font-medium">Everywhere</th></tr></thead>
      <tbody className="num">{rows.map(([l, a, b, fm]) => <tr key={l} className="border-t border-line-soft"><td className="py-2 text-slate-400">{l}</td><td className="text-right text-slate-100">{a == null ? DASH : fm(a)}</td><td className="text-right text-slate-400">{b == null ? DASH : fm(b)}</td></tr>)}</tbody></table>
  );
}

function PhaseMini({ rows, kind }) {
  const used = rows.filter(r => r.balls);
  if (!used.length) return null;
  return (
    <div className="mt-3 grid grid-cols-3 gap-2 border-t border-line-soft pt-3">
      {used.map(r => <div key={r.phase}><div className="text-3xs capitalize text-slate-500">{r.phase}</div><div className="num text-[14px] font-semibold text-slate-100">{kind === 'bat' ? `SR ${sr(r.strike_rate)}` : `Econ ${fmtDec(r.economy)}`}</div><div className="num text-3xs text-slate-500">{r.balls} b · {kind === 'bat' ? r.dismissals : r.wickets} {kind === 'bat' ? 'out' : 'wkts'}</div></div>)}
    </div>
  );
}

/* --------------------------------------------------------------------- trends */

function Trends({ d }) {
  const rf = d.recent_form;
  return (
    <div className="space-y-5">
      <MultiSeriesLine title="Strike rate over time" subtitle="Cumulative strike rate across meetings (line) and each innings' strike rate (points)." categorical yLabel="Strike rate"
        series={[{ name: 'Cumulative SR', color: COLOR_A, points: d.cumulative.map(c => ({ x: c.date, y: c.strike_rate })) },
          { name: 'Innings SR', color: 'var(--chart-muted)', points: d.cumulative.map(c => ({ x: c.date, y: c.innings_strike_rate })) }]} />
      <div className="grid gap-4 lg:grid-cols-2">
        <GroupedBarChart title="Runs and dismissals by year" categories={d.years.map(y => String(y.year))} formatter={v => Math.round(v)}
          series={[{ name: 'Runs', color: COLOR_A, values: d.years.map(y => y.runs) }, { name: 'Balls', color: 'var(--chart-muted)', values: d.years.map(y => y.balls) }]} />
        <BarChart title="Dismissals by year" data={d.years.map(y => ({ label: String(y.year), value: y.dismissals }))} color={COLOR_B} formatter={v => v} />
      </div>
      <Panel title={`Recent form — last ${rf.innings} meetings`} subtitle={`SR ${sr(rf.strike_rate)} from ${rf.balls} balls (overall ${sr(d.overall.strike_rate)}). Small window — indicative only.`} bodyClassName="p-3">
        <EncounterTable rows={rf.rows} d={d} pageSize={0} />
      </Panel>
      <Panel title="Season by season" bodyClassName="p-3"><SplitTable rows={[...d.seasons].reverse()} labelKey="season" label="Season" /></Panel>
    </div>
  );
}

/* ---------------------------------------------------------------- by match */

function EncounterTable({ rows, d, pageSize = 15 }) {
  return (
    <DataTable dense pageSize={pageSize} rows={rows} rowKey={r => `${r.match_id}-${r.innings}`}
      rowHref={r => matchUrl(r.match_id, { tab: 'scorecard', innings: r.innings, playerId: d.batter.id, focus: 'batting' })}
      rowLabel={r => `Open match ${r.batter_team} v ${r.bowler_team}, ${r.date}`}
      searchKeys={pageSize ? ['competition', 'venue', 'batter_team', 'bowler_team', 'season'] : undefined} searchPlaceholder="Search competition, venue, team…"
      columns={[
        { key: 'date', label: 'Date', render: r => <MatchLink id={r.match_id} context={{ tab: 'scorecard', innings: r.innings, playerId: d.batter.id, focus: 'batting' }} className="font-medium text-slate-100">{r.date}</MatchLink> },
        { key: 'fixture', label: 'Match', sortable: false, render: r => <span className="text-slate-300">{r.batter_team} <span className="text-slate-500">v</span> {r.bowler_team}</span> },
        { key: 'competition', label: 'Competition', render: r => <span className="text-slate-400">{r.competition || DASH} {r.season}</span> },
        { key: 'venue', label: 'Venue', render: r => <span className="text-slate-400">{r.venue || DASH}</span> },
        { key: 'innings', label: 'Inns', align: 'right' },
        { key: 'balls', label: 'Balls', align: 'right' }, { key: 'runs', label: 'Runs', align: 'right', render: r => <span className="font-semibold text-white">{r.runs}</span> },
        { key: 'strike_rate', label: 'SR', align: 'right', render: r => sr(r.strike_rate) },
        { key: 'boundaries', label: '4s/6s', align: 'right', sortValue: r => r.fours + r.sixes, render: r => `${r.fours}/${r.sixes}` },
        { key: 'dismissal', label: 'Out', render: r => (r.dismissal ? <span className={r.dismissal_credited ? 'text-neg-soft' : 'text-warn-soft'}>{r.dismissal}{!r.dismissal_credited && ' (not credited)'}</span> : <span className="text-slate-600">not out</span>) },
      ]} />
  );
}

function ByMatch({ d }) {
  const exportCsv = () => {
    const cols = ['date', 'format', 'competition', 'season', 'venue', 'batter_team', 'bowler_team', 'innings', 'balls', 'runs', 'fours', 'sixes', 'dots', 'strike_rate', 'dismissal', 'match_id'];
    const esc = v => (v == null ? '' : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
    const csv = [cols.join(','), ...d.by_match.map(r => cols.map(c => esc(r[c])).join(','))].join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    a.download = `${d.batter.name}-vs-${d.bowler.name}.csv`.replace(/\s+/g, '_');
    a.click();
    URL.revokeObjectURL(a.href);
  };
  return (
    <Panel title="Match by match" subtitle="One row per innings in which they met, newest first. Click any row to open the scorecard." bodyClassName="p-3"
      actions={<><SampleBadge n={d.by_match.length} unit="innings" /><Button size="xs" variant="ghost" icon="download" onClick={exportCsv}>CSV</Button></>}>
      <EncounterTable rows={d.by_match} d={d} />
    </Panel>
  );
}
