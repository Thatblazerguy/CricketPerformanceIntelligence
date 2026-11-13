/**
 * Full-match workflow: teams → XIs → conditions → validate → run → results.
 * Playing XIs live only here (session.js) and are validated against the CPI player database.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { getMatchSimOptions, getSimJob, startMatchSim, startMonteCarloSim, validateMatchSim } from '../../../services/api';
import { localIssues, requestBody } from './session';
import XiEditor from './XiEditor';
import MatchResult, { PlayerLink } from './MatchResult';
import MonteCarloResults from './MonteCarloResults';
import { TEAM_COLORS } from './charts';

const field = 'mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none';
const FORMATS = [['T20', 'T20 (franchise/domestic)'], ['T20I', 'T20 International'], ['ODI', 'ODI'], ['ODM', 'One-day (domestic)'], ['Test', 'Test / first-class']];
const PITCH = { balanced: 'Balanced', batting: 'Batting-friendly', bowling: 'Bowling-friendly', spin: 'Spin-friendly (turning)', seam: 'Seam-friendly (pace)' };
const WEATHER = { clear: 'Clear', overcast: 'Overcast (helps pace)', dew: 'Evening dew (from 2nd innings)' };

function Step({ n, title, status, children, right }) {
  const tone = status === 'done' ? 'bg-emerald-600 text-white' : status === 'blocked' ? 'bg-red-700 text-white' : 'bg-indigo-600 text-white';
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
          <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${tone}`}>{status === 'done' ? '✓' : n}</span>{title}
        </h2>
        {right}
      </div>
      {children}
    </section>
  );
}

function useJob() {
  const [job, setJob] = useState(null);
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  async function run(start, onDone) {
    clearTimeout(timer.current);
    setJob({ status: 'queued', progress: 0, message: 'Starting…' });
    try {
      let current = await start();
      setJob(current);
      const poll = async () => {
        try {
          current = await getSimJob(current.id);
          setJob(current);
          if (current.status === 'done') onDone(current.result);
          else if (current.status !== 'error') timer.current = setTimeout(poll, 500);
        } catch (e) { setJob({ status: 'error', error: e.message }); }
      };
      timer.current = setTimeout(poll, 300);
    } catch (e) { setJob({ status: 'error', error: e.message }); }
  }
  return { job, run, busy: job && !['done', 'error'].includes(job.status) };
}

function TeamCard({ k, team, issues, flags, onEdit, editing }) {
  const players = team.players || [];
  const matched = players.filter(p => p.id).length;
  const captain = players.find(p => p.is_captain);
  const keeper = players.find(p => p.is_wicketkeeper);
  return (
    <div className={`rounded-xl border p-3 ${editing ? 'border-indigo-500 bg-indigo-950/20' : 'border-slate-800 bg-slate-950/60'}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: TEAM_COLORS[k] }}>Team {k}</p>
          <p className="text-base font-bold text-white">{team.name || `Team ${k}`}</p>
          <p className="text-xs text-slate-400">{players.length}/11 players · {matched} matched{captain ? ` · C ${captain.name}` : ''}{keeper ? ` · WK ${keeper.name}` : ''}</p>
        </div>
        <button type="button" onClick={onEdit} className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${editing ? 'bg-slate-800 text-slate-200' : 'bg-indigo-600 text-white hover:bg-indigo-500'}`}>
          {editing ? 'Close editor' : players.length ? 'Edit XI' : 'Upload XI'}
        </button>
      </div>
      {players.length > 0 && (
        <ol className="mt-2 flex flex-wrap gap-1 text-[11px]">
          {players.map((p, i) => (
            <li key={`${p.id || p.input_name}-${i}`} className={`rounded border px-1.5 py-0.5 ${flags[i] ? 'border-red-800 bg-red-950/40 text-red-200' : 'border-slate-800 bg-slate-900 text-slate-300'}`}>
              <span className="mr-1 font-mono text-slate-500">{i + 1}</span>{p.id ? <PlayerLink id={p.id} name={p.name} /> : (p.input_name || p.name)}
            </li>
          ))}
        </ol>
      )}
      {issues.length > 0 && <ul className="mt-2 space-y-0.5 text-[11px] text-amber-300">{issues.map((m, i) => <li key={i}>• {m}</li>)}</ul>}
    </div>
  );
}

export default function FullMatchSimulator({ sim }) {
  const { session, update, setTeam, setConditions } = sim;
  const [editing, setEditing] = useState(session.teams.A.players.length ? null : 'A');
  const [options, setOptions] = useState(null);
  const [venueQuery, setVenueQuery] = useState('');
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState('');
  const [resultTab, setResultTab] = useState(session.monteCarlo && !session.match ? 'mc' : 'match');
  const { job, run, busy } = useJob();

  const family = session.format === 'Test' ? 'Test' : ['ODI', 'ODM'].includes(session.format) ? 'ODI' : 'T20';
  useEffect(() => { getMatchSimOptions(session.format).then(setOptions).catch(e => setError(e.message)); }, [family]); // eslint-disable-line react-hooks/exhaustive-deps

  const local = useMemo(() => localIssues(session.teams), [session.teams]);
  const names = { A: session.teams.A.name || 'Team A', B: session.teams.B.name || 'Team B' };
  const validation = session.validation;
  const valid = validation?.valid && !local.blocking;
  const maxSims = options?.limits?.max_simulations || 1000;
  const venues = useMemo(() => {
    const q = venueQuery.trim().toLowerCase();
    const list = options?.venues || [];
    return (q ? list.filter(v => `${v.name} ${v.city || ''} ${v.country || ''}`.toLowerCase().includes(q)) : list).slice(0, 60);
  }, [options, venueQuery]);

  async function validate() {
    setValidating(true); setError('');
    try {
      const report = await validateMatchSim(requestBody(session));
      update({ validation: report });
    } catch (e) { setError(e.message); } finally { setValidating(false); }
  }

  const runMatch = () => run(() => startMatchSim(requestBody(session)), result => { update({ match: { ...result, names } }); setResultTab('match'); });
  const runMc = () => run(() => startMonteCarloSim(requestBody(session, { simulations: Math.min(Number(session.simulations) || 500, maxSims) })),
    result => { update({ monteCarlo: { ...result, names } }); setResultTab('mc'); });

  const swapSides = () => update(s => ({ teams: { A: s.teams.B, B: s.teams.A }, validation: null, match: null, monteCarlo: null }));

  return (
    <div className="space-y-4">
      <Step n={1} title="Teams and Playing XIs" status={local.blocking ? 'blocked' : 'done'}
        right={<button type="button" onClick={swapSides} className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800">⇄ Swap sides</button>}>
        <p className="mb-3 text-xs text-slate-400">The Match Simulator is the single place to upload Playing XIs. Lineups stay here for this browser session; every name is matched to the CPI player database.</p>
        <div className="grid gap-3 lg:grid-cols-2">
          {['A', 'B'].map(k => (
            <TeamCard key={k} k={k} team={session.teams[k]} issues={local.issues[k]} flags={local.playerFlags[k]}
              editing={editing === k} onEdit={() => setEditing(editing === k ? null : k)} />
          ))}
        </div>
        {editing && (
          <div className="mt-3">
            <XiEditor key={editing} teamKey={editing} team={session.teams[editing]} format={session.format}
              flags={local.playerFlags[editing]} onChange={t => setTeam(editing, t)} onDone={() => setEditing(editing === 'A' && !session.teams.B.players.length ? 'B' : null)} />
          </div>
        )}
      </Step>

      <Step n={2} title="Format and conditions" status="done">
        <div className="grid gap-3 md:grid-cols-4">
          <label className="text-xs text-slate-400">Format
            <select className={field} value={session.format} onChange={e => update({ format: e.target.value, overs: '', validation: null })}>
              {FORMATS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          {session.format !== 'Test' ? (
            <label className="text-xs text-slate-400">Overs per side
              <input className={field} type="number" min="1" max={family === 'T20' ? 20 : 50} placeholder={family === 'T20' ? '20' : '50'} value={session.overs}
                onChange={e => update({ overs: e.target.value, validation: null })} />
            </label>
          ) : <div className="text-xs text-slate-400">Test rules<p className="mt-2 text-[11px] text-slate-500">Four innings, 450-over budget (5 × 90), follow-on at 200, declarations, draws.</p></div>}
          <label className="text-xs text-slate-400 md:col-span-2">Venue (historical CPI venues for this format)
            <div className="mt-1 flex gap-2">
              <input className={`${field} mt-0`} placeholder="Search venues…" value={venueQuery} onChange={e => setVenueQuery(e.target.value)} />
              <select className={`${field} mt-0`} value={session.conditions.venue_id || ''} onChange={e => {
                const v = (options?.venues || []).find(x => x.id === e.target.value);
                setConditions({ venue_id: e.target.value, venue_name: v?.name || '' });
              }}>
                <option value="">Neutral (no venue effect)</option>
                {session.conditions.venue_id && !venues.some(v => v.id === session.conditions.venue_id) && <option value={session.conditions.venue_id}>{session.conditions.venue_name}</option>}
                {venues.map(v => <option key={v.id} value={v.id}>{v.name}{v.city ? `, ${v.city}` : ''} · {v.matches} matches</option>)}
              </select>
            </div>
          </label>
          <label className="text-xs text-slate-400">Pitch
            <select className={field} value={session.conditions.pitch} onChange={e => setConditions({ pitch: e.target.value })}>
              {Object.entries(PITCH).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label className="text-xs text-slate-400">Weather
            <select className={field} value={session.conditions.weather} onChange={e => setConditions({ weather: e.target.value })}>
              {Object.entries(WEATHER).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label className="text-xs text-slate-400">Toss won by
            <select className={field} value={session.conditions.toss_winner} onChange={e => setConditions({ toss_winner: e.target.value })}>
              <option value="random">Random (each simulation)</option><option value="A">{names.A}</option><option value="B">{names.B}</option>
            </select>
          </label>
          <label className="text-xs text-slate-400">Toss decision
            <select className={field} value={session.conditions.toss_decision} onChange={e => setConditions({ toss_decision: e.target.value })}>
              <option value="auto">Historical tendency{validation?.toss_field_probability != null ? ` (field ${Math.round(validation.toss_field_probability * 100)}%)` : ''}</option>
              <option value="bat">Bat first</option><option value="field">Field first</option>
            </select>
          </label>
          {session.format !== 'Test' && (
            <label className="flex items-center gap-2 pt-5 text-xs text-slate-300">
              <input type="checkbox" checked={!!session.conditions.super_over} onChange={e => setConditions({ super_over: e.target.checked })} className="h-4 w-4 accent-indigo-500" />
              Super over decides ties
            </label>
          )}
          <label className="text-xs text-slate-400">Seed (optional, for reproducible runs)
            <input className={field} type="number" min="0" placeholder="Random" value={session.seed} onChange={e => update({ seed: e.target.value })} />
          </label>
          {session.format !== 'Test' && (
            <label className="text-xs text-slate-400">Win-probability runs per over (100–5,000)
              <input className={field} type="number" min="100" max="5000" step="100" placeholder={family === 'T20' ? '500' : '250'} value={session.wp_simulations}
                onChange={e => update({ wp_simulations: e.target.value })} />
            </label>
          )}
          <label className="text-xs text-slate-400">Monte Carlo simulations (max {maxSims.toLocaleString()})
            <input className={field} type="number" min="10" max={maxSims} step="100" value={session.simulations}
              onChange={e => update({ simulations: e.target.value })} />
          </label>
        </div>
        <p className="mt-2 text-[11px] text-slate-500">Venue effects come only from historical CPI matches at that ground. Pitch and weather are scenario settings applied as modest, documented multipliers.</p>
      </Step>

      <Step n={3} title="Validate" status={validation ? (valid ? 'done' : 'blocked') : 'todo'}
        right={<button type="button" disabled={validating || local.blocking} onClick={validate} className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50">{validating ? 'Checking against CPI…' : 'Validate setup'}</button>}>
        {local.blocking && <p className="text-xs text-amber-300">Fix the lineup issues above first: each side needs 11 matched, unique players.</p>}
        {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
        {!validation && !local.blocking && <p className="text-xs text-slate-400">Checks both XIs against CPI: identities, duplicates, men's/women's mix, batting-order roles, bowling resources under the over limits, data coverage and venue history.</p>}
        {validation && (
          <div className="space-y-3">
            {validation.errors?.length > 0 && <ul className="space-y-1 rounded-lg border border-red-800/60 bg-red-950/30 p-3 text-xs text-red-200">{validation.errors.map((m, i) => <li key={i}>✕ {m}</li>)}</ul>}
            {validation.warnings?.length > 0 && <ul className="space-y-1 rounded-lg border border-amber-800/50 bg-amber-950/20 p-3 text-xs text-amber-200">{validation.warnings.map((m, i) => <li key={i}>! {m}</li>)}</ul>}
            {validation.valid && <p className="text-xs text-emerald-300">✓ Ready to simulate: {validation.gender === 'female' ? "women's" : "men's"} {validation.family} model calibrated on {validation.calibration?.deliveries?.toLocaleString()} deliveries since {validation.calibration?.since?.slice(0, 4)}{validation.venue ? ` · venue ${validation.venue.name} (${validation.venue.matches} matches)` : ''}.</p>}
            {validation.teams?.A && (
              <div className="grid gap-3 lg:grid-cols-2">
                {['A', 'B'].map(k => {
                  const t = validation.teams[k];
                  return (
                    <div key={k} className="rounded-lg border border-slate-800 bg-slate-950/60 p-3 text-xs">
                      <p className="font-semibold" style={{ color: TEAM_COLORS[k] }}>{t.name}</p>
                      <div className="overflow-x-auto"><table className="mt-2 w-full min-w-[420px]">
                        <thead><tr className="text-[10px] uppercase text-slate-500"><th className="text-left">#</th><th className="text-left">Player</th><th className="text-left">CPI role</th><th className="text-right">Avg / SR</th><th className="text-right">Econ</th></tr></thead>
                        <tbody className="text-slate-300">
                          {t.players.map(p => (
                            <tr key={p.id}><td className="pr-1 font-mono text-slate-500">{p.position}</td>
                              <td><PlayerLink id={p.id} name={p.name} />{p.is_captain ? ' (c)' : ''}{p.is_wicketkeeper ? ' †' : ''}</td>
                              <td className="text-slate-400">{p.role}{p.bowling_type ? ` · ${p.bowling_type}` : ''}</td>
                              <td className="whitespace-nowrap text-right font-mono">{p.batting_average ?? '—'} / {p.strike_rate ?? '—'}</td>
                              <td className="text-right font-mono">{p.economy ?? '—'}</td></tr>
                          ))}
                        </tbody>
                      </table></div>
                      <p className="mt-2 text-[11px] text-slate-400">Bowling options: {t.bowling_options.map(b => `${b.name}${b.frontline ? '' : ' (part-time)'}`).join(', ')}</p>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </Step>

      <Step n={4} title="Run" status={session.match || session.monteCarlo ? 'done' : 'todo'}>
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" disabled={!valid || busy} onClick={runMatch} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-50">Simulate one match (ball by ball)</button>
          <button type="button" disabled={!valid || busy} onClick={runMc} className="rounded-lg border border-indigo-600 bg-indigo-950/50 px-4 py-2 text-sm font-semibold text-indigo-200 hover:bg-indigo-900/60 disabled:opacity-50">
            Run Monte Carlo ({Math.min(Number(session.simulations) || 500, maxSims).toLocaleString()} matches)
          </button>
          {!valid && <span className="text-xs text-slate-500">Validate the setup to enable runs.</span>}
        </div>
        {job && (
          <div className="mt-3">
            {job.status === 'error' ? (
              <div role="alert" className="rounded-lg border border-red-800/60 bg-red-950/30 p-3 text-xs text-red-200">
                {job.error}{job.report?.errors?.length ? <ul className="mt-1">{job.report.errors.map((m, i) => <li key={i}>✕ {m}</li>)}</ul> : null}
              </div>
            ) : job.status !== 'done' && (
              <div>
                <div className="flex justify-between text-[11px] text-slate-400"><span>{job.message}</span><span>{Math.round((job.progress || 0) * 100)}%</span></div>
                <div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-800"><div className="h-full rounded-full bg-indigo-500 transition-[width]" style={{ width: `${Math.max(3, (job.progress || 0) * 100)}%` }} /></div>
              </div>
            )}
          </div>
        )}
      </Step>

      {(session.match || session.monteCarlo) && (
        <section aria-label="Results" className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="mr-2 text-sm font-semibold text-white">5 · Results</h2>
            {session.match && <button type="button" onClick={() => setResultTab('match')} className={`rounded-lg border px-3 py-1.5 text-xs ${resultTab === 'match' ? 'border-indigo-500 bg-indigo-600 text-white' : 'border-slate-700 text-slate-300'}`}>Simulated match</button>}
            {session.monteCarlo && <button type="button" onClick={() => setResultTab('mc')} className={`rounded-lg border px-3 py-1.5 text-xs ${resultTab === 'mc' ? 'border-indigo-500 bg-indigo-600 text-white' : 'border-slate-700 text-slate-300'}`}>Monte Carlo</button>}
          </div>
          {resultTab === 'match' && session.match && <MatchResult result={session.match} names={session.match.names || names} />}
          {resultTab === 'mc' && session.monteCarlo && <MonteCarloResults mc={session.monteCarlo} names={session.monteCarlo.names || names} />}
        </section>
      )}
    </div>
  );
}
