/** One simulated match: result, scorecards, figures, progression, phases, win probability and turning points. */
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { OverBars, Panel, TEAM_COLORS, WinProbabilityChart, WormChart } from './charts';

const th = 'px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-500';
const td = 'px-2 py-1.5';
const PHASE_LABEL = { powerplay: 'Powerplay', middle: 'Middle overs', death: 'Death overs', new_ball: 'New ball (0-20)', old_ball: 'Old ball (80+)', super_over: 'Super over' };

export function PlayerLink({ id, name, className = '' }) {
  if (!id) return <span className={className}>{name || '—'}</span>;
  return <Link to={`/players/${id}`} className={`text-slate-100 hover:text-indigo-300 ${className}`}>{name}</Link>;
}

export function TeamLink({ name, teamId, className = '', style }) {
  if (!name) return null;
  return <Link to={`/venues?team=${encodeURIComponent(teamId || name)}`} className={`hover:underline ${className}`} style={style} title="Open team records">{name}</Link>;
}

function Batting({ rows, extras, total, wickets, overs, idByName }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] text-xs">
        <thead><tr className="border-b border-slate-800"><th className={th}>Batter</th><th className={th}>Dismissal</th>{['R', 'B', '4s', '6s', 'SR'].map(h => <th key={h} className={`${th} text-right`}>{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-slate-800/70">
          {rows.map(r => (
            <tr key={r.player_id} className={r.dismissal === 'did not bat' ? 'text-slate-500' : 'text-slate-300'}>
              <td className={td}><PlayerLink id={r.player_id} name={r.player} className="font-medium" /></td>
              <td className={`${td} text-slate-400`}>{r.dismissal}</td>
              <td className={`${td} text-right font-mono font-semibold text-white`}>{r.runs ?? ''}</td>
              <td className={`${td} text-right font-mono`}>{r.balls ?? ''}</td>
              <td className={`${td} text-right font-mono`}>{r.fours ?? ''}</td>
              <td className={`${td} text-right font-mono`}>{r.sixes ?? ''}</td>
              <td className={`${td} text-right font-mono`}>{r.strike_rate ?? ''}</td>
            </tr>
          ))}
          <tr className="text-slate-400"><td className={td}>Extras</td><td className={td} colSpan={6}>
            {Object.values(extras || {}).reduce((a, b) => a + b, 0)} (wd {extras?.wides || 0}, nb {extras?.noballs || 0}, b {extras?.byes || 0}, lb {extras?.legbyes || 0})
          </td></tr>
          <tr className="font-semibold text-white"><td className={td}>Total</td><td className={td} colSpan={6}>{total}/{wickets} ({overs} ov)</td></tr>
        </tbody>
      </table>
    </div>
  );
}

function Bowling({ rows }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[480px] text-xs">
        <thead><tr className="border-b border-slate-800"><th className={th}>Bowler</th>{['O', 'M', 'R', 'W', 'Econ', 'Wd', 'Nb'].map(h => <th key={h} className={`${th} text-right`}>{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-slate-800/70 text-slate-300">
          {rows.map(r => (
            <tr key={r.player_id}>
              <td className={td}><PlayerLink id={r.player_id} name={r.player} className="font-medium" /></td>
              <td className={`${td} text-right font-mono`}>{r.overs}</td>
              <td className={`${td} text-right font-mono`}>{r.maidens}</td>
              <td className={`${td} text-right font-mono`}>{r.runs}</td>
              <td className={`${td} text-right font-mono font-semibold text-white`}>{r.wickets}</td>
              <td className={`${td} text-right font-mono`}>{r.economy ?? '—'}</td>
              <td className={`${td} text-right font-mono`}>{r.wides}</td>
              <td className={`${td} text-right font-mono`}>{r.no_balls}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function InningsCard({ inn }) {
  const card = inn.scorecard;
  const idByName = Object.fromEntries((card.batting || []).map(b => [b.player, b.player_id]));
  const maxPart = Math.max(1, ...(card.partnerships || []).map(p => p.runs));
  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-5">
        <Panel title={`${inn.batting_team} batting`} subtitle={inn.target ? `Target ${inn.target}` : inn.declared ? 'Declared' : inn.follow_on ? 'Following on' : null} className="xl:col-span-3">
          <Batting rows={card.batting} extras={inn.extras_detail} total={inn.runs} wickets={inn.wickets} overs={inn.overs} idByName={idByName} />
        </Panel>
        <Panel title={`${inn.bowling_team} bowling`} className="xl:col-span-2"><Bowling rows={card.bowling} /></Panel>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Fall of wickets">
          {card.fall_of_wickets?.length ? (
            <ol className="flex flex-wrap gap-1.5 text-[11px]">
              {card.fall_of_wickets.map(f => (
                <li key={f.wicket} className="rounded border border-slate-800 bg-slate-950 px-2 py-1 text-slate-300">
                  <span className="font-mono text-white">{f.wicket}-{f.score}</span> <PlayerLink id={idByName[f.batter]} name={f.batter} /> <span className="text-slate-500">({f.over})</span>
                </li>
              ))}
            </ol>
          ) : <p className="text-xs text-slate-500">No wickets fell.</p>}
        </Panel>
        <Panel title="Partnerships">
          <div className="space-y-1.5">
            {(card.partnerships || []).map(p => (
              <div key={p.number} className="text-[11px]">
                <div className="flex justify-between text-slate-400"><span>{p.number}. {p.batters.join(' & ')}</span><span className="font-mono text-slate-200">{p.runs} ({p.balls})</span></div>
                <div className="mt-0.5 h-1.5 rounded bg-slate-800"><div className="h-full rounded" style={{ width: `${(100 * p.runs) / maxPart}%`, background: TEAM_COLORS[inn.batting] }} /></div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
      <div className="grid gap-4 lg:grid-cols-5">
        <Panel title="Over by over" subtitle="Bars are runs per over; red dots are wickets" className="lg:col-span-3"><OverBars overs={card.overs_progression} color={TEAM_COLORS[inn.batting]} /></Panel>
        <Panel title="Phase analysis" className="lg:col-span-2">
          <div className="overflow-x-auto"><table className="w-full min-w-[340px] text-xs">
            <thead><tr className="border-b border-slate-800"><th className={th}>Phase</th>{['Runs', 'Wkts', 'RR', '4s/6s', 'Dot %'].map(h => <th key={h} className={`${th} text-right`}>{h}</th>)}</tr></thead>
            <tbody className="divide-y divide-slate-800/70 text-slate-300">
              {(card.phases || []).map(p => (
                <tr key={p.phase}>
                  <td className={td}>{PHASE_LABEL[p.phase] || p.phase}</td>
                  <td className={`${td} text-right font-mono text-white`}>{p.runs}</td>
                  <td className={`${td} text-right font-mono`}>{p.wickets}</td>
                  <td className={`${td} text-right font-mono`}>{p.run_rate ?? '—'}</td>
                  <td className={`${td} text-right font-mono`}>{p.fours}/{p.sixes}</td>
                  <td className={`${td} text-right font-mono`}>{p.dot_pct ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </Panel>
      </div>
      {!card.reconciliation?.balanced && <p className="text-xs text-red-300">Scorecard did not reconcile: {JSON.stringify(card.reconciliation)}</p>}
    </div>
  );
}

export default function MatchResult({ result, names }) {
  const [tab, setTab] = useState(0);
  const innings = result.innings || [];
  const main = innings.filter(i => !i.super_over);
  const potm = result.player_of_match;
  const wp = result.win_probability || {};
  const current = innings[Math.min(tab, innings.length - 1)];
  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-indigo-900/50 bg-gradient-to-r from-slate-900 via-indigo-950/30 to-slate-900 p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-widest text-indigo-300">Simulated result · seed {result.seed}</p>
            <h2 className="mt-1 text-xl font-bold text-white">{result.result}</h2>
            <p className="mt-1 text-xs text-slate-400">{result.toss?.winner_name} won the toss and chose to {result.toss?.decision}.</p>
            <div className="mt-3 flex flex-wrap gap-3">
              {main.map(i => (
                <div key={i.number} className="rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2">
                  <p className="text-[10px] uppercase tracking-wider"><TeamLink name={i.batting_team} style={{ color: TEAM_COLORS[i.batting] }} />{main.length > 2 ? ` · inn ${i.number}` : ''}</p>
                  <p className="font-mono text-lg font-bold text-white">{i.runs}/{i.wickets}{i.declared ? 'd' : ''} <span className="text-xs font-normal text-slate-400">({i.overs} ov)</span></p>
                </div>
              ))}
              {innings.some(i => i.super_over) && (
                <div className="rounded-lg border border-amber-800/50 bg-amber-950/20 px-3 py-2 text-xs text-amber-200">
                  Super over{innings.filter(i => i.super_over).length > 2 ? 's' : ''}: {innings.filter(i => i.super_over).map(i => `${i.batting_team} ${i.runs}/${i.wickets}`).join(' · ')}
                </div>
              )}
            </div>
          </div>
          {potm && (
            <div className="rounded-xl border border-amber-700/40 bg-amber-950/20 p-3 text-sm">
              <p className="text-[10px] font-semibold uppercase tracking-widest text-amber-300">Player of the match</p>
              <PlayerLink id={potm.player_id} name={potm.name} className="mt-1 block text-base font-bold" />
              <p className="text-xs text-slate-400"><TeamLink name={names[potm.team]} /></p>
              <p className="mt-1 font-mono text-xs text-slate-300">
                {potm.balls ? `${potm.runs} (${potm.balls})` : ''}{potm.balls && potm.bowled ? ' · ' : ''}{potm.bowled ? `${potm.wickets}/${potm.conceded}` : ''}{potm.field ? ` · ${potm.field} ct/ro` : ''}
              </p>
            </div>
          )}
        </div>
        <ul className="mt-4 space-y-1 text-sm text-slate-300">{(result.summary || []).slice(1).map((s, i) => <li key={i}>{s}</li>)}</ul>
      </section>

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel className="xl:col-span-2" title="Win probability"
          subtitle={wp.method === 'simulation' ? `Always ${names.A}'s chance. After each over the rest of the match is re-simulated ${wp.simulations_per_point.toLocaleString()} times with both XIs; match conditions are inferred from the balls bowled so far. Shaded: 95% interval. Ties count half.` : wp.available ? 'CPI trained win-probability model (match state only).' : wp.reason}>
          {wp.available && <WinProbabilityChart points={wp.points} names={names} />}
        </Panel>
        <Panel title="Turning points" subtitle="Largest swings in win probability">
          {(result.turning_points || []).length ? (
            <ol className="space-y-2 text-xs">
              {result.turning_points.map((t, i) => {
                const swing = t.delta_team_a;
                const favoured = swing >= 0 ? 'A' : 'B';
                return (
                  <li key={i} className="rounded-lg border border-slate-800 bg-slate-950/60 p-2">
                    <div className="flex justify-between"><span className="font-semibold text-slate-200">Inn {t.innings}, {t.from_over + 1 < t.over ? `overs ${t.from_over + 1}-${t.over}` : `over ${t.over}`}</span>
                      <span className="font-mono" style={{ color: TEAM_COLORS[favoured] }}>{swing >= 0 ? '+' : ''}{(swing * 100).toFixed(0)} pts {names.A}</span></div>
                    <p className="text-slate-400">{t.batting_team} {t.score}. {t.summary}{t.events.length ? `; ${t.events.join(', ')}` : ''}</p>
                  </li>
                );
              })}
            </ol>
          ) : <p className="text-xs text-slate-500">Not available for this match.</p>}
        </Panel>
      </div>

      <Panel title="Run progression" subtitle="Cumulative runs by over; rings mark wickets"><WormChart innings={innings} /></Panel>

      <div className="flex flex-wrap gap-1 border-b border-slate-800" role="tablist">
        {innings.map((i, idx) => (
          <button key={i.number} role="tab" aria-selected={tab === idx} type="button" onClick={() => setTab(idx)}
            className={`border-b-2 px-3 py-2 text-xs font-semibold ${tab === idx ? 'border-indigo-500 text-indigo-300' : 'border-transparent text-slate-400 hover:text-slate-200'}`}>
            {i.super_over ? 'Super over: ' : ''}{i.batting_team} {i.runs}/{i.wickets}
          </button>
        ))}
      </div>
      {current && <InningsCard inn={current} />}

      <Panel title="Match impact" subtitle="Runs plus tempo vs the match scoring rate, 20-25 per wicket plus economy, 8 per catch, stumping or run-out">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-xs">
            <thead><tr className="border-b border-slate-800"><th className={th}>Player</th><th className={th}>Team</th>{['Impact', 'Bat', 'Bowl', 'Field'].map(h => <th key={h} className={`${th} text-right`}>{h}</th>)}</tr></thead>
            <tbody className="divide-y divide-slate-800/70 text-slate-300">
              {(result.impact || []).slice(0, 10).map(p => (
                <tr key={p.player_id}>
                  <td className={td}><PlayerLink id={p.player_id} name={p.name} /></td>
                  <td className={td}><TeamLink name={names[p.team]} style={{ color: TEAM_COLORS[p.team] }} /></td>
                  <td className={`${td} text-right font-mono font-semibold text-white`}>{p.impact}</td>
                  <td className={`${td} text-right font-mono`}>{p.innings ? `${p.runs} (${p.balls})` : '—'}</td>
                  <td className={`${td} text-right font-mono`}>{p.bowled ? `${p.wickets}/${p.conceded} (${Math.floor(p.bowled / 6)}.${p.bowled % 6})` : '—'}</td>
                  <td className={`${td} text-right font-mono`}>{p.field || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
