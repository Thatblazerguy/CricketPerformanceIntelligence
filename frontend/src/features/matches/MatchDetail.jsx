import { useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { getMatchDetails, getMatchWinProbability } from '../../services/api';
import { ErrorState, LoadingSpinner, PageHeader } from '../../components/ui';
import MatchCentreLink from '../../components/MatchCentreLink';
import WinProbabilityPanel from './WinProbabilityPanel';

const TABS = ['Summary', 'Scorecard', 'Commentary', 'Partnerships', 'Analysis'];
const fmt = value => value == null ? 'N/A' : value;
const pct = (value, total) => total ? `${Math.min(100, value / total * 100)}%` : '0%';

function DataTable({ headers, children }) {
  return <div className="overflow-x-auto"><table className="w-full min-w-[680px] text-sm"><thead className="bg-slate-800/80 text-left text-xs uppercase tracking-wide text-slate-400"><tr>{headers.map(h => <th key={h} className="px-3 py-3">{h}</th>)}</tr></thead><tbody>{children}</tbody></table></div>;
}
function Cell({ children, right = false, className = '', colSpan }) { return <td colSpan={colSpan} className={`border-t border-slate-800 px-3 py-2.5 text-slate-300 ${right ? 'text-right tabular-nums' : ''} ${className}`}>{children}</td>; }

function Summary({ data, probabilityProps }) {
  const allBatters = data.innings.flatMap(i => i.scorecard.batting.map(b => ({ ...b, team: i.batting_team })));
  const allBowlers = data.innings.flatMap(i => i.scorecard.bowling.map(b => ({ ...b, team: i.batting_team })));
  const topBatter = [...allBatters].sort((a, b) => b.runs - a.runs)[0];
  const bestBowler = [...allBowlers].sort((a, b) => b.wickets - a.wickets || a.runs - b.runs)[0];
  const bestStand = data.innings.flatMap(i => i.scorecard.partnerships).sort((a, b) => b.runs - a.runs)[0];
  const m = data.match;
  const resultText = m.winner ? `${m.winner} won${m.result_margin_runs ? ` by ${m.result_margin_runs} runs` : m.result_margin_wickets ? ` by ${m.result_margin_wickets} wickets` : ''}` : (m.result_type || 'Result unavailable');
  return <div className="space-y-5">
    <section className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5">
      <div className="text-xs uppercase tracking-[.18em] text-indigo-300">{m.competition || m.match_format} · {m.start_date}</div>
      <h2 className="mt-2 text-2xl font-bold text-white">{m.team1 || 'Team 1'} <span className="text-slate-500">vs</span> {m.team2 || 'Team 2'}</h2>
      <p className="mt-1 text-sm text-slate-400">{m.venue || 'Venue unavailable'} · {m.match_format} · {m.result_type || 'Result unavailable'}</p>
      <p className="mt-4 text-indigo-200">{resultText}</p>
      <p className="mt-1 text-sm text-slate-400">Toss: {m.toss_winner ? `${m.toss_winner} chose to ${m.toss_decision || '—'}` : 'Unavailable'}{m.player_of_match?.length ? ` · Player of the Match: ${m.player_of_match.join(', ')}` : ''}</p>
    </section>
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{data.innings.map(i => <div key={i.innings_number} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4"><div className="text-sm text-slate-400">{i.batting_team || `Innings ${i.innings_number}`}{i.is_super_over ? ' · Super Over' : ''}</div><div className="mt-2 text-2xl font-bold text-white">{i.scorecard.total}/{i.scorecard.wickets}<span className="ml-2 text-sm font-normal text-slate-400">({i.scorecard.overs} ov)</span></div></div>)}</div>
    <div className="grid gap-3 md:grid-cols-3">
      {[['Highest scorer', topBatter ? `${topBatter.player} · ${topBatter.runs}` : null], ['Best bowling', bestBowler ? `${bestBowler.player} · ${bestBowler.wickets}/${bestBowler.runs}` : null], ['Highest partnership', bestStand ? `${bestStand.batters.join(' & ')} · ${bestStand.runs} runs` : null]].map(([label, value]) => <div key={label} className="rounded-xl border border-slate-800 bg-slate-900/50 p-4"><div className="text-xs uppercase tracking-wide text-slate-500">{label}</div><div className="mt-2 font-semibold text-slate-100">{value || 'N/A'}</div></div>)}
    </div>
    <WinProbabilityPanel {...probabilityProps} matchData={data} />
    {!data.integrity?.stored_innings_totals_available && <p className="text-xs text-slate-500">Totals are reconstructed from ball-by-ball records. {data.integrity?.note}</p>}
  </div>;
}

function Scorecard({ innings, matchId, focusPlayerId, focusSide }) {
  const s = innings.scorecard;
  const extras = ['byes', 'legbyes', 'wides', 'noballs', 'penalty'].filter(k => s.extras[k]).map(k => `${k === 'noballs' ? 'no-balls' : k} ${s.extras[k]}`).join(', ');
  return <section className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/50">
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 bg-slate-900 px-4 py-3"><h3 className="font-semibold text-white">{innings.batting_team || `Innings ${innings.innings_number}`}{innings.is_super_over ? ' · Super Over' : ''}</h3><div className="font-mono text-lg font-bold text-white">{s.total}/{s.wickets} <span className="text-sm font-normal text-slate-400">({s.overs} overs)</span></div></div>
    <DataTable headers={['Batter', 'Dismissal', 'R', 'B', '4s', '6s', 'SR']}>
      {s.batting.map((b, idx) => <tr id={b.player_id && focusSide !== 'bowling' ? `player-${b.player_id}` : undefined} key={`${b.player}-${idx}`} className={focusPlayerId === b.player_id && focusSide !== 'bowling' ? 'bg-indigo-950/40' : ''}><Cell className="font-medium text-white">{b.player || 'Unknown batter'}</Cell><Cell>{b.dismissal}</Cell><Cell right className="font-semibold"><MatchCentreLink matchId={matchId} context={{ tab: 'scorecard', innings: innings.innings_number, playerId: b.player_id, focus: 'batting' }}>{b.runs}</MatchCentreLink></Cell><Cell right>{b.balls}</Cell><Cell right>{b.fours}</Cell><Cell right>{b.sixes}</Cell><Cell right>{fmt(b.strike_rate)}</Cell></tr>)}
      <tr className="bg-slate-900/70"><Cell className="font-semibold text-slate-100">Extras</Cell><Cell>{extras || 'None recorded'}</Cell><Cell right className="font-semibold text-slate-100">{Object.values(s.extras).reduce((a, b) => a + b, 0)}</Cell><Cell colSpan={4} /></tr>
      <tr className="bg-slate-900/70"><Cell className="font-semibold text-white">Total</Cell><Cell>{s.wickets} wickets · {s.overs} overs</Cell><Cell right className="font-bold text-white">{s.total}</Cell><Cell colSpan={4} /></tr>
    </DataTable>
    {!!innings.did_not_bat?.length && <div className="border-t border-slate-800 px-4 py-3 text-sm text-slate-400"><span className="font-medium text-slate-300">Did not bat:</span> {innings.did_not_bat.join(', ')}</div>}
    {s.fall_of_wickets.length > 0 && <div className="border-t border-slate-800 px-4 py-3 text-sm"><span className="font-medium text-slate-300">Fall of wickets:</span> <span className="text-slate-400">{s.fall_of_wickets.map(w => `${w.score}-${w.wicket} (${w.batter || 'batter'}, ${w.over || 'over unavailable'})`).join(' · ')}</span></div>}
    <div className="border-t border-slate-800"><div className="px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Bowling</div><DataTable headers={['Bowler', 'O', 'M', 'R', 'W', 'Econ', 'Wd', 'Nb']}>
      {s.bowling.map((b, idx) => <tr id={b.player_id && focusSide === 'bowling' ? `player-${b.player_id}` : undefined} key={`${b.player}-${idx}`} className={focusPlayerId === b.player_id && focusSide === 'bowling' ? 'bg-indigo-950/40' : ''}><Cell className="font-medium text-white">{b.player || 'Unknown bowler'}</Cell><Cell right>{b.overs}</Cell><Cell right>{b.maidens}</Cell><Cell right className="font-semibold"><MatchCentreLink matchId={matchId} context={{ tab: 'analysis', innings: innings.innings_number, playerId: b.player_id, focus: 'bowling' }}>{b.runs}</MatchCentreLink></Cell><Cell right>{b.wickets}</Cell><Cell right>{fmt(b.economy)}</Cell><Cell right>{b.wides}</Cell><Cell right>{b.no_balls}</Cell></tr>)}
    </DataTable></div>
  </section>;
}

function Commentary({ innings }) {
  return <div className="space-y-5">{innings.map(i => <section key={i.innings_number} className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/50"><h3 className="bg-slate-900 px-4 py-3 font-semibold text-white">{i.batting_team || `Innings ${i.innings_number}`} · {i.scorecard.total}/{i.scorecard.wickets}</h3><div className="max-h-[70vh] overflow-auto"><DataTable headers={['Over.Ball', 'Batter', 'Bowler', 'Event', 'Total']}>
    {i.deliveries.map((d, idx) => { const extras = d.extra_types?.map(e => `${e.type} ${e.runs}`).join(', '); const wickets = d.wickets?.map(w => `${w.player_out || 'Wicket'} (${w.kind}${w.fielder ? `, fielder ${w.fielder}` : ''})`).join('; '); const event = [d.batter_runs ? `${d.batter_runs} batter run${d.batter_runs === 1 ? '' : 's'}` : null, extras, wickets].filter(Boolean).join(' · ') || 'No run'; return <tr id={`delivery-${i.innings_number}-${idx}`} key={idx}><Cell className="whitespace-nowrap font-mono text-slate-400">{d.over}.{d.ball}{!d.legal ? '*' : ''}</Cell><Cell>{d.batter || '—'}</Cell><Cell>{d.bowler || '—'}</Cell><Cell>{event}</Cell><Cell right className="font-semibold text-white">{d.total_runs}</Cell></tr>; })}
  </DataTable></div></section>)}</div>;
}

function Partnerships({ innings, matchId, selectedPartnership }) {
  return <div className="space-y-5">{innings.map(i => {
    const selected = i.scorecard.partnerships.find(p => selectedPartnership === String(p.number));
    return <section key={i.innings_number} className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/50"><h3 className="bg-slate-900 px-4 py-3 font-semibold text-white">{i.batting_team || `Innings ${i.innings_number}`}</h3><DataTable headers={['Wicket / stand', 'Batters', 'Runs', 'Balls']}>
      {i.scorecard.partnerships.map(p => <tr id={`partnership-${i.innings_number}-${p.number}`} key={p.number} className={selectedPartnership === String(p.number) ? 'bg-indigo-950/40' : ''}><Cell><MatchCentreLink matchId={matchId} context={{ tab: 'partnerships', innings: i.innings_number, partnership: p.number }}>{p.ended_at_wicket ? `Through wicket ${p.ended_at_wicket}` : 'Unbroken stand'}</MatchCentreLink></Cell><Cell>{p.batters.join(' & ') || 'Names unavailable'}</Cell><Cell right className="font-semibold text-white"><MatchCentreLink matchId={matchId} context={{ tab: 'partnerships', innings: i.innings_number, partnership: p.number }}>{p.runs}</MatchCentreLink></Cell><Cell right>{p.balls}</Cell></tr>)}
      {i.scorecard.partnerships.length === 0 && <tr><Cell colSpan={4}>No partnership data available.</Cell></tr>}
    </DataTable>{selected && <div className="border-t border-slate-800 p-4"><h4 className="mb-2 text-sm font-medium text-slate-200">Stand {selected.number} · delivery breakdown</h4><DataTable headers={['Over.Ball', 'Batter', 'Bowler', 'Batter runs', 'Extras', 'Total', 'Event']}>
      {selected.delivery_breakdown.map((d, idx) => <tr key={idx}><Cell className="font-mono text-slate-400">{d.over || '—'}</Cell><Cell>{d.batter || '—'}</Cell><Cell>{d.bowler || '—'}</Cell><Cell right>{d.batter_runs}</Cell><Cell>{d.extras.map(e => `${e.type} ${e.runs}`).join(', ') || '—'}</Cell><Cell right className="font-semibold text-white">{d.total_runs}</Cell><Cell className="text-rose-300">{d.wickets.map(w => `${w.player || 'Wicket'} (${w.kind})`).join(', ') || '—'}</Cell></tr>)}
    </DataTable></div>}</section>;
  })}</div>;
}

function Analysis({ innings, focusPlayerId, focusSide }) {
  return <div className="space-y-5">{innings.map(i => { const maxRuns = Math.max(1, ...i.scorecard.overs_progression.map(o => o.runs)); return <section key={i.innings_number} className="rounded-xl border border-slate-800 bg-slate-900/50 p-4"><h3 className="font-semibold text-white">{i.batting_team || `Innings ${i.innings_number}`} · scoring analysis</h3>
    <div className="mt-4 space-y-2"><div className="text-xs uppercase tracking-wide text-slate-500">Over-by-over runs · cumulative run rate</div>{i.scorecard.overs_progression.map(o => <div key={o.over} className="grid grid-cols-[3.5rem_1fr_8rem] items-center gap-3 text-xs"><span className="text-slate-400">Over {o.over}</span><div className="h-5 rounded bg-slate-800"><div className="flex h-full items-center rounded bg-indigo-500/80 px-2 text-white" style={{ width: pct(o.runs, maxRuns), minWidth: o.runs ? '2rem' : 0 }}>{o.runs || ''}</div></div><span className="text-right tabular-nums text-slate-400">{o.score} · RR {o.run_rate}{o.wickets ? ` · ${o.wickets} W` : ''}</span></div>)}</div>
    <div className="mt-5"><div className="mb-2 text-xs uppercase tracking-wide text-slate-500">Phase / innings progression</div><DataTable headers={['Phase', 'Runs', 'Legal balls', 'Wickets', 'Economy']}>
      {i.scorecard.phases.map(p => <tr key={p.phase}><Cell className="text-white">{p.phase}</Cell><Cell right>{p.runs}</Cell><Cell right>{p.legal_balls}</Cell><Cell right>{p.wickets}</Cell><Cell right>{fmt(p.economy)}</Cell></tr>)}
    </DataTable>{['Test', 'MDM'].includes(i.match_format) && <p className="mt-2 text-xs text-slate-500">Session data is unavailable; these are innings-progression bands, not powerplay or death phases.</p>}</div>
    <div className="mt-5 grid gap-4 lg:grid-cols-2"><div><div className="mb-2 text-xs uppercase tracking-wide text-slate-500">Batting vs bowling figures</div><DataTable headers={['Batter', 'Runs', 'SR']}>{i.scorecard.batting.map((b, idx) => <tr id={b.player_id && focusSide !== 'bowling' ? `player-${b.player_id}` : undefined} className={focusPlayerId === b.player_id && focusSide !== 'bowling' ? 'bg-indigo-950/40' : ''} key={idx}><Cell>{b.player}</Cell><Cell right>{b.runs}</Cell><Cell right>{fmt(b.strike_rate)}</Cell></tr>)}</DataTable></div><div><div className="mb-2 text-xs uppercase tracking-wide text-slate-500">Bowling impact</div><DataTable headers={['Bowler', 'Wickets', 'Runs', 'Economy']}>{i.scorecard.bowling.map((b, idx) => <tr id={b.player_id && focusSide === 'bowling' ? `player-${b.player_id}` : undefined} className={focusPlayerId === b.player_id && focusSide === 'bowling' ? 'bg-indigo-950/40' : ''} key={idx}><Cell>{b.player}</Cell><Cell right>{b.wickets}</Cell><Cell right>{b.runs}</Cell><Cell right>{fmt(b.economy)}</Cell></tr>)}</DataTable>{focusSide === 'bowling' && i.scorecard.bowling.filter(b => b.player_id === focusPlayerId).map(b => <div key={b.player_id} className="mt-3 rounded-lg border border-indigo-900/60 p-3"><h4 className="mb-2 text-xs font-semibold text-indigo-200">{b.player} · over-by-over spell figures</h4><div className="flex flex-wrap gap-2">{b.over_breakdown.map(over => <span key={over.over} className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-300">Over {over.over}: {over.runs} runs, {over.legal_balls} legal, {over.wickets} bowler wickets</span>)}</div></div>)}</div></div>
  </section>; })}</div>;
}

export default function MatchDetail() {
  const { id } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null); const [error, setError] = useState(null); const [loading, setLoading] = useState(true); const [tab, setTab] = useState('Summary');
  const [probability, setProbability] = useState(null); const [selectedReplaySequence, setSelectedReplaySequence] = useState(0); const [playing, setPlaying] = useState(false);
  async function load() { setLoading(true); setError(null); try { setData(await getMatchDetails(id)); } catch (e) { setError(e.message || 'Could not load match detail.'); } finally { setLoading(false); } }
  useEffect(() => { load(); }, [id]);
  useEffect(() => { let mounted = true; setProbability(null); setSelectedReplaySequence(0); setPlaying(false); getMatchWinProbability(id).then(value => { if (mounted) setProbability(value); }).catch(() => { if (mounted) setProbability({ status: 'not_precomputed', points: [] }); }); return () => { mounted = false; }; }, [id]);
  useEffect(() => {
    if (!playing || !probability?.points?.length) return;
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
    if (!contextualPlayerId && !selectedPartnership) return;
    const targetId = contextualPlayerId ? `player-${contextualPlayerId}` : `partnership-${selectedInnings}-${selectedPartnership}`;
    const timer = setTimeout(() => document.getElementById(targetId)?.scrollIntoView({ block: 'center', behavior: 'smooth' }), 80);
    return () => clearTimeout(timer);
  }, [data, tab, contextualPlayerId, selectedInnings, selectedPartnership]);
  if (loading) return <LoadingSpinner message="Loading match scorecard…" />;
  if (error) return <div><ErrorState message={error} /><button onClick={load} className="mt-3 text-indigo-300">Retry</button></div>;
  const m = data.match;
  const chooseTab = nextTab => {
    const params = new URLSearchParams(searchParams);
    params.set('tab', nextTab.toLowerCase());
    setSearchParams(params);
    setTab(nextTab);
  };
  const jumpToDelivery = point => {
    setSelectedReplaySequence(point.sequence);
    chooseTab('Commentary');
    setTimeout(() => document.getElementById(`delivery-${point.innings_number}-${point.delivery_index}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' }), 100);
  };
  const probabilityProps = { data: probability, selectedSequence: selectedReplaySequence, setSelectedSequence: setSelectedReplaySequence, onReplay: jumpToDelivery, playing, setPlaying };
  return <div className="space-y-5"><Link to="/matches" className="text-sm text-indigo-300">← Matches</Link><PageHeader title={`${m.team1 || 'Team 1'} vs ${m.team2 || 'Team 2'}`} subtitle={`${m.competition || 'Match'} · ${m.start_date} · ${m.venue || 'Venue unavailable'} · ${m.match_format}`} />
    <nav className="flex gap-2 overflow-x-auto border-b border-slate-800 pb-2">{TABS.map(item => <button key={item} onClick={() => chooseTab(item)} className={`shrink-0 rounded-lg px-4 py-2 text-sm ${tab === item ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:bg-slate-900 hover:text-white'}`}>{item}</button>)}</nav>
    {tab === 'Summary' && <Summary data={data} probabilityProps={probabilityProps} />}
    {tab === 'Scorecard' && <div className="space-y-5"><WinProbabilityPanel {...probabilityProps} matchData={data} />{shownInnings.map(i => <Scorecard key={i.innings_number} innings={i} matchId={id} focusPlayerId={contextualPlayerId} focusSide={focusSide} />)}</div>}
    {tab === 'Commentary' && <Commentary innings={shownInnings} />}
    {tab === 'Partnerships' && <Partnerships innings={shownInnings} matchId={id} selectedPartnership={selectedPartnership} />}
    {tab === 'Analysis' && <Analysis innings={shownInnings} focusPlayerId={contextualPlayerId} focusSide={focusSide} />}
  </div>;
}
