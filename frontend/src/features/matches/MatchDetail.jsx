/**
 * Match centre: scorecards, ball-by-ball timeline, partnerships and analysis.
 * Every figure comes from GET /matches/{id}/details, which reconstructs innings
 * from stored deliveries (backend/app/analytics/scorecard.py).
 */
import { useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { getMatchDetails, getMatchWinProbability } from '../../services/api';
import { Badge, DataTable, ErrorState, Panel, PlayerLink, Segmented, Skeleton, Tabs } from '../../components/ui';
import Icon from '../../components/icons';
import { ColumnChart, GroupedBarChart, MultiSeriesLine, PALETTE, StackedBar } from '../../components/charts';
import MatchCentreLink from '../../components/MatchCentreLink';
import WinProbabilityPanel from './WinProbabilityPanel';
import { DASH, fmtDec, fmtEcon, fmtPct, fmtSR } from '../../lib/format';

const TABS = ['Summary', 'Scorecard', 'Commentary', 'Partnerships', 'Analysis'];
const INNINGS_COLORS = [PALETTE[0], PALETTE[2], PALETTE[3], PALETTE[4]];
const isLimited = f => ['T20', 'T20I', 'ODI', 'ODM'].includes(f);
const mainInnings = innings => innings.filter(i => !i.is_super_over);
const label = i => `${i.batting_team || `Innings ${i.innings_number}`}${i.is_super_over ? ' (super over)' : ''}`;

/* -------------------------------------------------------------- summary */

function resultText(m) {
  if (m.winner) return `${m.winner} won${m.result_margin_runs ? ` by ${m.result_margin_runs} runs` : m.result_margin_wickets ? ` by ${m.result_margin_wickets} wickets` : ''}`;
  return m.result_type ? m.result_type[0].toUpperCase() + m.result_type.slice(1) : 'Result unavailable';
}

function WormChart({ innings, format }) {
  const main = mainInnings(innings);
  const chase = main.find(i => i.scorecard.target);
  return (
    <MultiSeriesLine title="Run progression (worm)" subtitle="Cumulative score at the end of each over. Red markers: overs in which wickets fell."
      xLabel="Over" yLabel="Runs" sample={main.reduce((a, i) => a + i.scorecard.overs_progression.length, 0)} sampleUnit="overs"
      references={chase ? [{ label: `Target ${chase.scorecard.target}`, value: chase.scorecard.target, color: 'var(--chart-ref)' }] : []}
      series={main.map((inn, k) => ({
        name: `${label(inn)} ${inn.scorecard.total}/${inn.scorecard.wickets}`,
        color: INNINGS_COLORS[k % INNINGS_COLORS.length],
        points: [{ x: 0, y: 0, label: 'Start' }, ...inn.scorecard.overs_progression.map(o => ({
          x: o.over, y: o.score, marker: o.wickets > 0,
          tip: <OverTip o={o} team={inn.batting_team} />,
        }))],
      }))}
      footnote={isLimited(format) ? null : 'Multi-day innings are long; use the Analysis tab for over-by-over detail.'} />
  );
}

function OverTip({ o, team }) {
  return (
    <div>
      <div className="mb-0.5 font-semibold text-white">{team} · end of over {o.over}</div>
      <div className="num">{o.score}/{o.wickets_total} · {o.runs} runs this over{o.wickets ? ` · ${o.wickets} wkt` : ''}</div>
      <div className="num text-slate-400">Run rate {fmtDec(o.run_rate)}{o.required_run_rate != null ? ` · required ${fmtDec(o.required_run_rate)}` : ''}</div>
      {o.bowlers?.length > 0 && <div className="text-slate-400">Bowler: {o.bowlers.join(', ')}</div>}
      {(o.fours || o.sixes) ? <div className="num text-slate-400">{o.fours} fours · {o.sixes} sixes{o.extras ? ` · ${o.extras} extras` : ''}</div> : null}
    </div>
  );
}

function KeyEvents({ innings }) {
  const events = mainInnings(innings).flatMap(i => (i.scorecard.key_events || []).map(e => ({ ...e, team: i.batting_team, innings: i.innings_number })));
  if (!events.length) return null;
  return (
    <Panel title="Turning points" subtitle="Detected from recorded events only: two or more wickets inside two consecutive overs (collapse), or an over of 12+ runs that is at least double the innings' mean runs per over.">
      <ol className="space-y-2">
        {events.sort((a, b) => a.innings - b.innings || a.over - b.over).map((e, i) => (
          <li key={i} className="flex flex-wrap items-center gap-2 text-sm">
            <Badge variant={e.type === 'collapse' ? 'red' : 'green'}>{e.type === 'collapse' ? 'Wickets' : 'Big over'}</Badge>
            <span className="text-slate-300">{e.team} · {e.detail}</span>
            <span className="num text-xs text-slate-500">score {e.score} after over {e.over}</span>
          </li>
        ))}
      </ol>
    </Panel>
  );
}

const extrasOf = s => Object.values(s.extras || {}).reduce((a, b) => a + b, 0);
const runRate = s => (s.legal_balls ? s.total * 6 / s.legal_balls : null);

/** Broadcast-style scoreboard: teams, innings scores, result, toss and venue. */
function MatchHero({ m, innings }) {
  const main = mainInnings(innings);
  const supers = innings.filter(i => i.is_super_over);
  const teams = [m.team1, m.team2].filter(Boolean);
  // Group innings by batting team so multi-day matches read "245 & 198/6".
  const byTeam = teams.map(t => ({ team: t, inns: main.filter(i => i.batting_team === t) }));
  const unassigned = main.filter(i => !teams.includes(i.batting_team));
  const r = resultText(m);
  return (
    <section className="panel relative overflow-hidden">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 bg-[radial-gradient(80%_120%_at_0%_0%,rgb(var(--accent)/0.10),transparent_55%),radial-gradient(60%_100%_at_100%_100%,rgb(var(--electric)/0.06),transparent_60%)]" />
      <div className="relative flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5 text-2xs text-slate-400 sm:px-6">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <Badge variant="indigo">{m.match_format}</Badge>
          <span className="truncate font-medium text-slate-200">{m.competition || 'Match'}</span>
          {m.season && <><span className="text-slate-600">·</span><span>Season {m.season}</span></>}
        </div>
        <div className="flex items-center gap-1.5"><Icon name="calendar" size={13} className="text-slate-500" /><span className="num">{m.start_date}</span></div>
      </div>
      <div className="relative grid gap-px sm:grid-cols-2">
        {byTeam.map(({ team, inns }) => {
          const won = m.winner === team;
          return (
            <div key={team} className={`flex items-center justify-between gap-4 px-4 py-5 sm:px-6 ${won ? '' : 'opacity-[0.86]'}`}>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h2 className={`truncate text-lg font-semibold tracking-tight sm:text-xl ${won ? 'text-white' : 'text-slate-300'}`}>{team}</h2>
                  {won && <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-pos/15 text-pos" title="Winner"><Icon name="check" size={12} strokeWidth={2.5} /></span>}
                </div>
                <div className="mt-1 text-2xs text-slate-500">{inns.length ? inns.map(i => `Innings ${i.innings_number}`).join(' · ') : 'Did not bat'}</div>
              </div>
              <div className="text-right">
                {inns.length ? inns.map((i, k) => (
                  <div key={i.innings_number} className={k ? 'mt-1' : ''}>
                    <span className={`mono-num font-semibold ${k === inns.length - 1 ? 'text-[1.75rem] leading-none text-white sm:text-[2rem]' : 'text-base text-slate-400'}`}>{i.scorecard.total}{i.scorecard.wickets < 10 ? `/${i.scorecard.wickets}` : ''}</span>
                    {k === inns.length - 1 && <div className="num mt-1 text-2xs text-slate-500">{i.scorecard.overs} ov · RR {fmtDec(runRate(i.scorecard))}{i.scorecard.target ? ` · target ${i.scorecard.target}` : ''}</div>}
                  </div>
                )) : <span className="text-sm text-slate-600">—</span>}
              </div>
            </div>
          );
        })}
        {unassigned.map(i => (
          <div key={i.innings_number} className="flex items-center justify-between gap-4 px-4 py-4 sm:px-6">
            <span className="text-sm text-slate-300">{label(i)}</span>
            <span className="mono-num text-xl font-semibold text-white">{i.scorecard.total}/{i.scorecard.wickets}</span>
          </div>
        ))}
      </div>
      <div className="relative flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-t border-line bg-surface-sunken/50 px-4 py-3 sm:px-6">
        <p className={`text-sm font-medium ${m.winner ? 'text-pos-soft' : 'text-slate-300'}`}>{r}{supers.length ? <span className="ml-2 text-2xs font-normal text-slate-500">({supers.length} super over innings)</span> : null}</p>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-slate-400">
          <span className="inline-flex items-center gap-1.5"><Icon name="venues" size={13} className="text-slate-500" />{m.venue || 'Venue unavailable'}</span>
          <span>Toss: {m.toss_winner ? `${m.toss_winner}, chose to ${m.toss_decision || '—'}` : 'unavailable'}</span>
          {m.player_of_match?.length > 0 && <span className="inline-flex items-center gap-1.5 text-slate-300"><span className="eyebrow !text-3xs">POTM</span>{m.player_of_match.join(', ')}</span>}
        </div>
      </div>
    </section>
  );
}

function Summary({ data, probabilityProps }) {
  const m = data.match;
  const main = mainInnings(data.innings);
  const allBatters = data.innings.flatMap(i => i.scorecard.batting.map(b => ({ ...b, team: i.batting_team })));
  const allBowlers = data.innings.flatMap(i => i.scorecard.bowling.map(b => ({ ...b, team: i.batting_team })));
  const topBatters = [...allBatters].sort((a, b) => b.runs - a.runs || a.balls - b.balls).slice(0, 4);
  const topBowlers = [...allBowlers].sort((a, b) => b.wickets - a.wickets || a.runs - b.runs).slice(0, 4);
  const bestStand = data.innings.flatMap(i => i.scorecard.partnerships.map(p => ({ ...p, team: i.batting_team }))).sort((a, b) => b.runs - a.runs)[0];
  return (
    <div className="space-y-5">

      <WormChart innings={data.innings} format={m.match_format} />

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Top batting contributions" bodyClassName="p-3">
          <DataTable dense pageSize={0} rows={topBatters} rowKey={(r, i) => `${r.player_id}-${i}`} columns={[
            { key: 'player', label: 'Batter', sortable: false, render: r => <div><PlayerLink id={r.player_id} name={r.player} /><div className="text-2xs text-slate-500">{r.team}</div></div> },
            { key: 'runs', label: 'R', align: 'right', sortable: false, render: r => <span className="font-semibold text-white">{r.runs}{r.dismissal === 'not out' ? '*' : ''}</span> },
            { key: 'balls', label: 'B', align: 'right', sortable: false },
            { key: 'strike_rate', label: 'SR', align: 'right', sortable: false, render: r => fmtSR(r.strike_rate) },
          ]} />
        </Panel>
        <Panel title="Top bowling figures" bodyClassName="p-3">
          <DataTable dense pageSize={0} rows={topBowlers} rowKey={(r, i) => `${r.player_id}-${i}`} columns={[
            { key: 'player', label: 'Bowler', sortable: false, render: r => <div><PlayerLink id={r.player_id} name={r.player} /><div className="text-2xs text-slate-500">v {r.team}</div></div> },
            { key: 'fig', label: 'Figures', align: 'right', sortable: false, render: r => <span className="font-semibold text-white">{r.wickets}/{r.runs}</span> },
            { key: 'overs', label: 'O', align: 'right', sortable: false },
            { key: 'economy', label: 'Econ', align: 'right', sortable: false, render: r => fmtEcon(r.economy) },
          ]} />
        </Panel>
        <Panel title="Highest partnership">
          {bestStand ? (
            <div>
              <div className="num text-2xl font-semibold text-white">{bestStand.runs}<span className="ml-1 text-sm font-normal text-slate-400">runs · {bestStand.balls} balls</span></div>
              <div className="mt-1 text-sm text-slate-300">{bestStand.batters.join(' & ')}</div>
              <div className="mt-1 text-xs text-slate-500">{bestStand.team} · wicket {bestStand.number} · RR {fmtDec(bestStand.run_rate)}</div>
            </div>
          ) : <p className="text-sm text-slate-500">No partnership data.</p>}
        </Panel>
      </div>
      <KeyEvents innings={data.innings} />
      <WinProbabilityPanel {...probabilityProps} matchData={data} />
      {!data.integrity?.stored_innings_totals_available && <p className="text-2xs text-slate-500">Totals are reconstructed from ball-by-ball records. {data.integrity?.note}</p>}
    </div>
  );
}

/* ------------------------------------------------------------ scorecard */

function Scorecard({ innings, matchId, focusPlayerId, focusSide }) {
  const s = innings.scorecard;
  const extrasTotal = Object.values(s.extras).reduce((a, b) => a + b, 0);
  const extras = [['b', 'byes'], ['lb', 'legbyes'], ['w', 'wides'], ['nb', 'noballs'], ['p', 'penalty']].filter(([, k]) => s.extras[k]).map(([abbr, k]) => `${abbr} ${s.extras[k]}`).join(', ');
  const focus = (id, side) => focusPlayerId && focusPlayerId === id && (side === 'bowling' ? focusSide === 'bowling' : focusSide !== 'bowling');
  return (
    <section className="panel overflow-hidden">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-line bg-gradient-to-b from-surface-raised to-surface px-4 py-3.5 sm:px-5">
        <div className="min-w-0">
          <div className="eyebrow mb-1">Innings {innings.innings_number}{innings.is_super_over ? ' · super over' : ''}</div>
          <h3 className="truncate text-base font-semibold tracking-tight text-white">{innings.batting_team || `Innings ${innings.innings_number}`}</h3>
        </div>
        <div className="text-right">
          <span className="mono-num text-2xl font-semibold leading-none text-white">{s.total}/{s.wickets}</span>
          <div className="num mt-1 text-2xs text-slate-500">{s.overs} overs · RR {fmtDec(runRate(s))} · extras {extrasOf(s)}{s.target ? ` · target ${s.target}` : ''}</div>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-[13px]">
          <thead className="text-3xs uppercase tracking-[0.08em] text-slate-500"><tr className="border-b border-line">{['Batter', 'Dismissal', 'R', 'B', '4s', '6s', 'SR'].map((h, i) => <th key={h} className={`px-3 py-2 font-semibold first:pl-4 last:pr-4 sm:first:pl-5 sm:last:pr-5 ${i > 1 ? 'text-right' : 'text-left'} ${h === 'R' ? 'text-slate-300' : ''}`}>{h}</th>)}</tr></thead>
          <tbody>
            {s.batting.map((b, idx) => (
              <tr id={b.player_id && focusSide !== 'bowling' ? `player-${b.player_id}` : undefined} key={`${b.player}-${idx}`} className={`border-t border-line-soft transition-colors hover:bg-surface-hover/50 ${focus(b.player_id, 'batting') ? 'bg-accent-muted/40' : ''}`}>
                <td className="py-2 pl-4 pr-3 sm:pl-5"><PlayerLink id={b.player_id} name={b.player || 'Unknown batter'} className="font-medium" />{b.dismissal === 'not out' && <span className="ml-1 text-accent-soft">*</span>}</td>
                <td className={`max-w-[18rem] truncate px-3 py-2 text-2xs ${b.dismissal === 'not out' ? 'text-pos-soft' : 'text-slate-500'}`} title={b.dismissal}>{b.dismissal}</td>
                <td className="num px-3 py-2 text-right text-[15px] font-semibold text-white"><MatchCentreLink matchId={matchId} context={{ tab: 'commentary', innings: innings.innings_number, playerId: b.player_id, focus: 'batting' }} className="!text-white !decoration-white/20">{b.runs}</MatchCentreLink></td>
                <td className="num px-3 py-2 text-right text-slate-300">{b.balls}</td>
                <td className="num px-3 py-2 text-right text-slate-300">{b.fours}</td>
                <td className="num px-3 py-2 text-right text-slate-300">{b.sixes}</td>
                <td className={`num py-2 pl-3 pr-4 text-right sm:pr-5 ${b.balls >= 10 && b.strike_rate >= 150 ? 'text-pos-soft' : 'text-slate-300'}`}>{fmtSR(b.strike_rate)}</td>
              </tr>
            ))}
            <tr className="border-t border-line bg-surface-sunken/50"><td className="py-2 pl-4 pr-3 text-slate-300 sm:pl-5">Extras</td><td className="num px-3 py-2 text-2xs text-slate-500">{extras || 'none recorded'}</td><td className="num px-3 py-2 text-right font-semibold text-slate-200">{extrasTotal}</td><td colSpan={4} /></tr>
            <tr className="border-t border-line-strong bg-surface-sunken/50"><td className="py-2.5 pl-4 pr-3 font-semibold text-white sm:pl-5">Total</td><td className="num px-3 py-2.5 text-2xs text-slate-400">{s.wickets} wkts · {s.overs} ov · RR {fmtDec(runRate(s))}</td><td className="mono-num px-3 py-2.5 text-right text-base font-bold text-white">{s.total}</td><td colSpan={4} /></tr>
          </tbody>
        </table>
      </div>
      {!!innings.did_not_bat?.length && <div className="border-t border-line px-4 py-2.5 text-xs text-slate-400 sm:px-5"><span className="eyebrow mr-2">Did not bat</span>{innings.did_not_bat.join(', ')}</div>}
      {s.fall_of_wickets.length > 0 && (
        <div className="border-t border-line px-4 py-3 sm:px-5">
          <div className="eyebrow mb-2">Fall of wickets</div>
          <ol className="flex flex-wrap gap-1.5">
            {s.fall_of_wickets.map(w => (
              <li key={w.wicket} className="inline-flex items-baseline gap-1.5 rounded-md border border-line bg-surface-sunken px-2 py-1 text-2xs" title={`${w.batter || 'Batter'} · over ${w.over || '—'}`}>
                <span className="mono-num font-semibold text-slate-100">{w.score}-{w.wicket}</span>
                <span className="max-w-[9rem] truncate text-slate-400">{w.batter || 'batter'}</span>
                <span className="num text-slate-600">{w.over || '—'}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
      <div className="border-t border-line">
        <div className="eyebrow px-4 pb-1 pt-3 sm:px-5">Bowling</div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-[13px]">
            <thead className="text-3xs uppercase tracking-[0.08em] text-slate-500"><tr className="border-b border-line">{['Bowler', 'O', 'M', 'R', 'W', 'Econ', 'Dots', 'Dot %', '4s', '6s', 'Wd', 'Nb'].map((h, i) => <th key={h} className={`px-3 py-2 font-semibold first:pl-4 last:pr-4 sm:first:pl-5 sm:last:pr-5 ${i ? 'text-right' : 'text-left'} ${h === 'W' ? 'text-slate-300' : ''}`}>{h}</th>)}</tr></thead>
            <tbody>
              {s.bowling.map((b, idx) => (
                <tr id={b.player_id && focusSide === 'bowling' ? `player-${b.player_id}` : undefined} key={`${b.player}-${idx}`} className={`border-t border-line-soft transition-colors hover:bg-surface-hover/50 ${focus(b.player_id, 'bowling') ? 'bg-accent-muted/40' : ''}`}>
                  <td className="py-2 pl-4 pr-3 sm:pl-5"><PlayerLink id={b.player_id} name={b.player || 'Unknown bowler'} className="font-medium" /></td>
                  <td className="num px-3 py-2 text-right text-slate-300">{b.overs}</td>
                  <td className="num px-3 py-2 text-right text-slate-300">{b.maidens}</td>
                  <td className="num px-3 py-2 text-right text-slate-300">{b.runs}</td>
                  <td className="num px-3 py-2 text-right text-[15px] font-semibold text-white"><MatchCentreLink matchId={matchId} context={{ tab: 'analysis', innings: innings.innings_number, playerId: b.player_id, focus: 'bowling' }} className="!text-white !decoration-white/20">{b.wickets}</MatchCentreLink></td>
                  <td className="num px-3 py-2 text-right text-slate-300">{fmtEcon(b.economy)}</td>
                  <td className="num px-3 py-2 text-right text-slate-300">{b.dots ?? DASH}</td>
                  <td className="num px-3 py-2 text-right text-slate-300">{fmtPct(b.dot_percentage)}</td>
                  <td className="num px-3 py-2 text-right text-slate-300">{b.fours ?? DASH}</td>
                  <td className="num px-3 py-2 text-right text-slate-300">{b.sixes ?? DASH}</td>
                  <td className="num px-3 py-2 text-right text-slate-300">{b.wides}</td>
                  <td className="num py-2 pl-3 pr-4 text-right text-slate-300 sm:pr-5">{b.no_balls}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

/* ----------------------------------------------------------- commentary */

function Commentary({ innings, focusPlayerId }) {
  const [filter, setFilter] = useState(focusPlayerId ? 'player' : 'all');
  const keep = d => filter === 'all' || (filter === 'wickets' ? d.wickets?.length > 0 : filter === 'boundaries' ? d.four || d.six : (d.batter_id === focusPlayerId || d.bowler_id === focusPlayerId));
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <Segmented label="Delivery filter" value={filter} onChange={setFilter} options={[{ id: 'all', label: 'All balls' }, { id: 'wickets', label: 'Wickets' }, { id: 'boundaries', label: 'Boundaries' }, ...(focusPlayerId ? [{ id: 'player', label: 'Focused player' }] : [])]} />
        <span className="text-2xs text-slate-500">* marks a delivery that is not a legal ball (wide / no-ball).</span>
      </div>
      {innings.map(i => {
        const overs = [];
        i.deliveries.forEach((d, idx) => { if (!keep(d)) return; const last = overs[overs.length - 1]; if (!last || last.over !== d.over) overs.push({ over: d.over, balls: [] }); overs[overs.length - 1].balls.push({ ...d, idx }); });
        const progression = Object.fromEntries(i.scorecard.overs_progression.map(o => [o.over, o]));
        return (
          <section key={i.innings_number} className="panel overflow-hidden">
            <div className="flex items-center justify-between border-b border-line bg-gradient-to-b from-surface-raised to-surface px-4 py-3"><h3 className="font-semibold tracking-tight text-white">{label(i)}</h3><span className="mono-num text-base font-semibold text-white">{i.scorecard.total}/{i.scorecard.wickets}</span></div>
            <div className="max-h-[70vh] divide-y divide-line/70 overflow-auto">
              {overs.length === 0 && <p className="px-4 py-6 text-sm text-slate-500">No deliveries match this filter.</p>}
              {overs.map(o => (
                <div key={o.over} className="grid gap-2 px-4 py-3 sm:grid-cols-[7rem_1fr]">
                  <div className="text-xs">
                    <div className="font-semibold text-slate-200">Over {o.over}</div>
                    {progression[o.over] && <div className="num text-slate-500">{progression[o.over].runs} runs · {progression[o.over].score}/{progression[o.over].wickets_total}</div>}
                    {progression[o.over]?.bowlers?.length > 0 && <div className="truncate text-slate-500">{progression[o.over].bowlers.join(', ')}</div>}
                  </div>
                  <div className="space-y-1">
                    {o.balls.map(d => {
                      const extras = d.extra_types?.map(e => `${e.type} ${e.runs}`).join(', ');
                      const wk = d.wickets?.map(w => `${w.player_out || 'Wicket'} ${w.kind}${w.fielder ? ` (${w.fielder})` : ''}`).join('; ');
                      const chip = d.wickets?.length ? 'bg-neg text-on-accent' : d.six ? 'bg-accent text-on-accent' : d.four ? 'bg-electric/80 text-white' : !d.legal ? 'border border-warn/40 text-warn' : d.total_runs ? 'bg-slate-700 text-slate-100' : 'bg-slate-800/80 text-slate-500';
                      return (
                        <div id={`delivery-${i.innings_number}-${d.idx}`} key={d.idx} className="flex items-start gap-2 text-sm">
                          <span className="num w-10 shrink-0 text-xs text-slate-500">{d.over}.{d.ball}{!d.legal ? '*' : ''}</span>
                          <span className={`num inline-flex h-5 min-w-[1.5rem] shrink-0 items-center justify-center rounded-full px-1.5 text-2xs font-semibold ${chip}`}>{d.wickets?.length ? 'W' : d.total_runs}</span>
                          <span className="text-slate-300"><span className="text-slate-400">{d.bowler || '—'} to</span> {d.batter || '—'}{d.batter_runs ? `, ${d.batter_runs} run${d.batter_runs === 1 ? '' : 's'}` : ', no run'}{extras ? ` · ${extras}` : ''}{wk ? <span className="text-neg"> · OUT: {wk}</span> : ''}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

/* --------------------------------------------------------- partnerships */

function Partnerships({ innings, matchId, selectedPartnership }) {
  return (
    <div className="space-y-5">
      {innings.map(i => {
        const ps = i.scorecard.partnerships;
        const selected = ps.find(p => selectedPartnership === String(p.number));
        return (
          <div key={i.innings_number} className="space-y-3">
            <StackedBar title={`${label(i)} · partnerships`} subtitle="Each bar is one partnership, split into each batter's runs off the bat plus extras. Right-hand figure: partnership runs (balls)."
              sample={ps.length} sampleUnit="stands"
              legend={[{ label: 'First batter', color: PALETTE[0] }, { label: 'Second batter', color: PALETTE[3] }, { label: 'Extras', color: 'var(--chart-muted)' }]}
              rows={ps.map(p => {
                const [a, b] = p.contributions || [];
                return {
                  label: `${p.ended_at_wicket ? `${p.number}${['st', 'nd', 'rd'][p.number - 1] || 'th'} wkt` : 'Unbroken'} · ${p.batters.join(' & ') || 'Names unavailable'}`,
                  sub: `${p.runs} (${p.balls}) · RR ${fmtDec(p.run_rate)}`,
                  segments: [
                    a && { name: 'First batter', value: a.runs, color: PALETTE[0], detail: `${a.player}: ${a.runs} off ${a.balls}` },
                    b && { name: 'Second batter', value: b.runs, color: PALETTE[3], detail: `${b.player}: ${b.runs} off ${b.balls}` },
                    { name: 'Extras', value: p.extras, color: 'var(--chart-muted)' },
                  ].filter(Boolean),
                };
              })} />
            <Panel title="Partnership detail" bodyClassName="p-3">
              <DataTable dense pageSize={0} rows={ps} rowKey={p => p.number} initialSort={{ key: 'number', dir: 'asc' }}
                rowClassName={p => (selectedPartnership === String(p.number) ? 'bg-accent-muted/30' : '')}
                columns={[
                  { key: 'number', label: 'Wkt', align: 'right', render: p => <span id={`partnership-${i.innings_number}-${p.number}`}>{p.number}</span> },
                  { key: 'batters', label: 'Batters', sortable: false, render: p => (p.contributions || []).map(c => <span key={c.player} className="mr-3"><PlayerLink id={c.player_id} name={c.player} /> <span className="num text-slate-500">{c.runs} ({c.balls})</span></span>) },
                  { key: 'runs', label: 'Runs', align: 'right', render: p => <MatchCentreLink matchId={matchId} context={{ tab: 'partnerships', innings: i.innings_number, partnership: p.number }}>{p.runs}</MatchCentreLink> },
                  { key: 'balls', label: 'Balls', align: 'right' },
                  { key: 'run_rate', label: 'RR', align: 'right', render: p => fmtDec(p.run_rate) },
                  { key: 'extras', label: 'Extras', align: 'right' },
                  { key: 'span', label: 'Score span', align: 'right', sortable: false, render: p => `${p.start_score} → ${p.end_score}` },
                ]} />
            </Panel>
            {selected && (
              <Panel title={`Stand ${selected.number} · delivery breakdown`} bodyClassName="p-3">
                <DataTable dense pageSize={0} rows={selected.delivery_breakdown} rowKey={(d, k) => k} columns={[
                  { key: 'over', label: 'Ball', sortable: false },
                  { key: 'batter', label: 'Batter', sortable: false },
                  { key: 'bowler', label: 'Bowler', sortable: false },
                  { key: 'batter_runs', label: 'Bat', align: 'right', sortable: false },
                  { key: 'extras', label: 'Extras', sortable: false, render: d => d.extras.map(e => `${e.type} ${e.runs}`).join(', ') || DASH },
                  { key: 'total_runs', label: 'Total', align: 'right', sortable: false },
                  { key: 'wickets', label: 'Event', sortable: false, render: d => <span className="text-neg">{d.wickets.map(w => `${w.player || 'Wicket'} (${w.kind})`).join(', ')}</span> },
                ]} />
              </Panel>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* -------------------------------------------------------------- analysis */

function Analysis({ innings, allInnings, format, focusPlayerId, focusSide }) {
  const main = mainInnings(allInnings);
  const chase = main.find(i => i.scorecard.target && isLimited(format));
  const [bowlMetric, setBowlMetric] = useState('economy');
  return (
    <div className="space-y-5">
      {isLimited(format) && main.length > 0 && (
        <MultiSeriesLine title="Run-rate progression" subtitle={`Cumulative run rate after each over${chase ? ', with the chasing side’s required run rate (runs needed × 6 ÷ balls left; undefined once the target is reached)' : ''}.`}
          xLabel="Over" yLabel="Runs per over" yFormatter={v => fmtDec(v, 1)}
          series={[
            ...main.map((inn, k) => ({ name: `${label(inn)} run rate`, color: INNINGS_COLORS[k % 4], points: inn.scorecard.overs_progression.map(o => ({ x: o.over, y: o.run_rate, tip: <OverTip o={o} team={inn.batting_team} /> })) })),
            ...(chase ? [{ name: `${label(chase)} required rate`, color: 'var(--c6)', dashed: true, points: chase.scorecard.overs_progression.filter(o => o.required_run_rate != null).map(o => ({ x: o.over, y: o.required_run_rate, tip: <OverTip o={o} team={chase.batting_team} /> })) }] : []),
          ]} />
      )}
      {innings.map((i, k) => {
        const s = i.scorecard;
        const bowlers = s.bowling.filter(b => b.legal_balls > 0);
        return (
          <section key={i.innings_number} className="space-y-4">
            <h3 className="text-sm font-semibold text-slate-200">{label(i)} · {s.total}/{s.wickets} ({s.overs})</h3>
            <ColumnChart title="Runs per over (Manhattan)" subtitle="Bars: runs in each over. Red dots: wickets. Line: cumulative run rate. Hover for the bowler — consecutive changes show bowling changes."
              data={s.overs_progression.map(o => ({ label: o.over, value: o.runs, line: o.run_rate, markers: o.wickets, tip: <OverTip o={o} team={i.batting_team} /> }))}
              barLabel="Runs in over" lineLabel="Run rate" xLabel="Over" yLabel="Runs" y2Label="Run rate" formatter={v => Math.round(v)} lineFormatter={v => fmtDec(v, 1)}
              color={INNINGS_COLORS[k % 4]} sample={s.overs_progression.length} sampleUnit="overs" />
            <div className="grid gap-4 lg:grid-cols-2">
              <Panel title="Phase breakdown" subtitle={isLimited(format) ? 'Format-specific phases (see PHASE_RULES.md). Dot % and boundary % use legal balls.' : 'Multi-day: innings split into thirds by overs — not sessions.'} bodyClassName="p-3">
                <DataTable dense pageSize={0} rows={s.phases} rowKey={p => p.phase} columns={[
                  { key: 'phase', label: 'Phase' },
                  { key: 'runs', label: 'Runs', align: 'right' },
                  { key: 'legal_balls', label: 'Balls', align: 'right' },
                  { key: 'wickets', label: 'Wkts', align: 'right' },
                  { key: 'economy', label: 'RR', align: 'right', render: p => fmtDec(p.economy) },
                  { key: 'dot_percentage', label: 'Dot %', align: 'right', render: p => fmtPct(p.dot_percentage) },
                  { key: 'boundary_percentage', label: 'Bnd %', align: 'right', render: p => fmtPct(p.boundary_percentage) },
                ]} />
              </Panel>
              <GroupedBarChart title="Bowler comparison" subtitle={bowlMetric === 'economy' ? 'Economy (runs per over) for each bowler.' : bowlMetric === 'dot' ? 'Dot-ball percentage (legal balls with no bowling runs).' : 'Boundary percentage conceded.'}
                actions={<Segmented size="xs" label="Bowler metric" value={bowlMetric} onChange={setBowlMetric} options={[{ id: 'economy', label: 'Econ' }, { id: 'dot', label: 'Dot %' }, { id: 'bnd', label: 'Bnd %' }]} />}
                categories={bowlers.map(b => (b.player || '').split(' ').slice(-1)[0])}
                series={[{ name: bowlMetric === 'economy' ? 'Economy' : bowlMetric === 'dot' ? 'Dot %' : 'Boundary %', color: bowlMetric === 'economy' ? PALETTE[3] : bowlMetric === 'dot' ? PALETTE[1] : PALETTE[5], values: bowlers.map(b => (bowlMetric === 'economy' ? b.economy : bowlMetric === 'dot' ? b.dot_percentage : b.boundary_percentage)) }]}
                formatter={v => (bowlMetric === 'economy' ? fmtDec(v, 1) : `${Math.round(v)}%`)} sample={bowlers.length} sampleUnit="bowlers" />
            </div>
            <Panel title="Bowling spells over by over" subtitle="Runs conceded by each bowler in each over they bowled; red cells contain a bowler-credited wicket." bodyClassName="p-3 overflow-x-auto">
              <table className="text-xs">
                <tbody>
                  {bowlers.map(b => (
                    <tr key={b.player_id} id={focusSide === 'bowling' && b.player_id === focusPlayerId ? `player-${b.player_id}` : undefined} className={focusSide === 'bowling' && b.player_id === focusPlayerId ? 'bg-accent-muted/30' : ''}>
                      <td className="whitespace-nowrap py-1 pr-3"><PlayerLink id={b.player_id} name={b.player} /> <span className="num text-slate-500">{b.wickets}/{b.runs}</span></td>
                      {b.over_breakdown.map(o => (
                        <td key={o.over} className="p-0.5">
                          <span title={`Over ${o.over}: ${o.runs} runs, ${o.legal_balls} legal balls, ${o.wickets} wicket(s)`} className={`num inline-flex h-7 w-9 flex-col items-center justify-center rounded ${o.wickets ? 'bg-neg-muted text-neg' : o.runs === 0 && o.legal_balls === 6 ? 'bg-pos-muted text-pos' : 'bg-slate-800 text-slate-300'}`}>
                            <span className="text-[9px] leading-none text-slate-500">{o.over}</span>{o.runs}{o.wickets ? `·${o.wickets}w` : ''}
                          </span>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          </section>
        );
      })}
    </div>
  );
}

/* ----------------------------------------------------------------- page */

export default function MatchDetail() {
  const { id } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null); const [error, setError] = useState(null); const [loading, setLoading] = useState(true); const [tab, setTab] = useState('Summary');
  const [probability, setProbability] = useState(null); const [selectedReplaySequence, setSelectedReplaySequence] = useState(0); const [playing, setPlaying] = useState(false);
  async function load() { setLoading(true); setError(null); try { setData(await getMatchDetails(id)); } catch (e) { setError(e.message || 'Could not load match detail.'); } finally { setLoading(false); } }
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { let mounted = true; setProbability(null); setSelectedReplaySequence(0); setPlaying(false); getMatchWinProbability(id).then(v => { if (mounted) setProbability(v); }).catch(() => { if (mounted) setProbability({ status: 'not_precomputed', points: [] }); }); return () => { mounted = false; }; }, [id]);
  useEffect(() => {
    if (!playing || !probability?.points?.length) return undefined;
    const timer = setInterval(() => setSelectedReplaySequence(index => {
      const next = index + 1;
      if (next >= probability.points.length) { setPlaying(false); return probability.points.length - 1; }
      return next;
    }), 900);
    return () => clearInterval(timer);
  }, [playing, probability]);
  useEffect(() => {
    const requested = searchParams.get('tab');
    setTab(TABS.find(item => item.toLowerCase() === requested) || 'Summary');
  }, [id, searchParams]);
  const innings = useMemo(() => data?.innings || [], [data]);
  const contextualPlayerId = searchParams.get('playerId');
  const focusSide = searchParams.get('focus');
  const selectedInnings = searchParams.get('innings');
  const shownInnings = selectedInnings ? innings.filter(i => String(i.innings_number) === selectedInnings) : innings;
  const selectedPartnership = searchParams.get('partnership');
  useEffect(() => {
    if (!contextualPlayerId && !selectedPartnership) return undefined;
    const targetId = contextualPlayerId ? `player-${contextualPlayerId}` : `partnership-${selectedInnings}-${selectedPartnership}`;
    const timer = setTimeout(() => document.getElementById(targetId)?.scrollIntoView({ block: 'center', behavior: 'smooth' }), 120);
    return () => clearTimeout(timer);
  }, [data, tab, contextualPlayerId, selectedInnings, selectedPartnership]);
  if (loading) return <div className="space-y-5"><Skeleton className="h-3 w-24" /><Skeleton className="h-[188px] rounded-xl" /><Skeleton className="h-10 w-2/3" /><div className="grid gap-4 lg:grid-cols-3">{Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-48 rounded-xl" />)}</div></div>;
  if (error) return <ErrorState message={error} onRetry={load} />;
  const m = data.match;
  const chooseTab = nextTab => {
    const params = new URLSearchParams(searchParams);
    params.set('tab', nextTab.toLowerCase());
    setSearchParams(params);
    setTab(nextTab);
  };
  const chooseInnings = value => {
    const params = new URLSearchParams(searchParams);
    if (value) params.set('innings', value); else params.delete('innings');
    setSearchParams(params);
  };
  const jumpToDelivery = point => {
    setSelectedReplaySequence(point.sequence);
    chooseTab('Commentary');
    setTimeout(() => document.getElementById(`delivery-${point.innings_number}-${point.delivery_index}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' }), 120);
  };
  const probabilityProps = { data: probability, selectedSequence: selectedReplaySequence, setSelectedSequence: setSelectedReplaySequence, onReplay: jumpToDelivery, playing, setPlaying };
  const main = mainInnings(innings);
  return (
    <div className="space-y-5">
      <Link to="/matches" className="inline-flex items-center gap-1 text-xs text-slate-500 transition-colors hover:text-slate-200"><Icon name="chevronLeft" size={13} />All matches</Link>
      <MatchHero m={m} innings={innings} />
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <Tabs className="min-w-0 lg:flex-1" tabs={TABS} value={tab} onChange={chooseTab} />
        {tab !== 'Summary' && innings.length > 1 && (
          <Segmented label="Innings" value={selectedInnings || ''} onChange={chooseInnings} options={[{ id: '', label: 'All innings' }, ...innings.map(i => ({ id: String(i.innings_number), label: `${i.innings_number}. ${(i.batting_team || '').split(' ').slice(-1)[0]}${i.is_super_over ? ' SO' : ''}` }))]} />
        )}
      </div>
      {tab === 'Summary' && <Summary data={data} probabilityProps={probabilityProps} />}
      {tab === 'Scorecard' && <div className="space-y-5">{shownInnings.map(i => <Scorecard key={i.innings_number} innings={i} matchId={id} focusPlayerId={contextualPlayerId} focusSide={focusSide} />)}<WinProbabilityPanel {...probabilityProps} matchData={data} /></div>}
      {tab === 'Commentary' && <Commentary innings={shownInnings} focusPlayerId={contextualPlayerId} />}
      {tab === 'Partnerships' && <Partnerships innings={shownInnings} matchId={id} selectedPartnership={selectedPartnership} />}
      {tab === 'Analysis' && <Analysis innings={shownInnings} allInnings={innings} format={m.match_format} focusPlayerId={contextualPlayerId} focusSide={focusSide} />}
    </div>
  );
}
