import { useEffect, useMemo, useState } from 'react';
import {
  compareBattingOrders,
  compareBowlingOptions,
  getPlayers,
  simulateInnings,
  analyseLiveMatchScreenshot,
  getSimulatorOptions,
  getSimulatorWinProbability,
} from '../../services/api';
import { PageHeader } from '../../components/ui';
import FullMatchSimulator from './simulator/FullMatchSimulator';
import { useSimSession } from './simulator/session';

const box = 'rounded-xl border border-slate-800 bg-slate-900 p-4';
const field = 'mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100';
const button = 'rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-50';

function Histogram({ rows }) {
  const max = Math.max(1, ...rows.map(x => x.count));
  return (
    <div className="flex h-44 items-end gap-1 border-b border-l border-slate-700 px-2 pt-2">
      {rows.map(x => (
        <div
          key={x.range_start}
          className="group relative flex-1"
          title={`${x.range_start}-${x.range_start + 9}: ${x.count}`}
        >
          <div
            className="w-full rounded-t bg-indigo-500/80 hover:bg-emerald-400"
            style={{ height: `${Math.max(2, x.count / max * 100)}%` }}
          />
          <span className="absolute -bottom-5 left-1/2 -translate-x-1/2 whitespace-nowrap text-[9px] text-slate-500">
            {x.range_start}
          </span>
        </div>
      ))}
    </div>
  );
}

function InningsTools({ sim }) {
  const [mode, setMode] = useState('simulate');
  const [state, setState] = useState({
    format: 'T20',
    team1_name: '',
    team2_name: '',
    score: 0,
    wickets: 0,
    legal_balls: 0,
    target_runs: '',
    target_overs: '',
    required_run_rate: '',
    innings_number: '',
    simulations: 1000,
    batting_order: [],
    bowlers: [],
    overs_bowled: {},
    seed: 7,
  });
  const [options, setOptions] = useState({ venues: [], competitions: [] });
  const [search, setSearch] = useState('');
  const [players, setPlayers] = useState([]);
  const [selectedBatters, setSelectedBatters] = useState([]);
  const [selectedBowlers, setSelectedBowlers] = useState([]);
  const [result, setResult] = useState(null);
  const [winProb, setWinProb] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [screenshot, setScreenshot] = useState(null);
  const [liveNames, setLiveNames] = useState({ teams: [], players: [] });
  const [selectedForOrder, setSelectedForOrder] = useState('');

  useEffect(() => {
    getSimulatorOptions().then(setOptions).catch(e => setError(e.message));
  }, []);

  const orders = useMemo(() => {
    if (selectedBatters.length < 2) return [];
    const original = selectedBatters.map(p => p.id);
    const promoted = [...original];
    const index = promoted.indexOf(selectedForOrder);
    if (index > 1) promoted.splice(0, 0, promoted.splice(index, 1)[0]);
    else if (index === 1) promoted.splice(0, 0, promoted.splice(1, 1)[0]);
    return [original, promoted];
  }, [selectedBatters, selectedForOrder]);

  const patch = (key, value) => setState(s => ({ ...s, [key]: value }));

  const setFromPlayer = (key, id) => {
    const p = [...selectedBatters, ...selectedBowlers, ...players].find(x => x.id === id);
    patch(key, id || null);
    if (key === 'batter_id' && p?.batting_style)
      patch('batter_hand', p.batting_style.toLowerCase().includes('left') ? 'left' : 'right');
    if (key === 'bowler_id' && p?.bowling_type)
      patch('bowling_category', p.bowling_type.toLowerCase());
    if (key === 'bowler_id' && p?.bowling_style)
      patch('bowling_subtype', p.bowling_style.toLowerCase());
  };

  async function findPlayers(e) {
    e?.preventDefault();
    setError('');
    try {
      const data = await getPlayers({ name: search, page: 1, page_size: 50 });
      setPlayers(data.players || []);
    } catch (err) {
      setError(err.message);
    }
  }

  function addPlayer(player, kind) {
    if (kind === 'bat') setSelectedBatters(x => x.some(p => p.id === player.id) ? x : [...x, player]);
    else setSelectedBowlers(x => x.some(p => p.id === player.id) ? x : [...x, player]);
  }

  async function run(action) {
    setBusy(true);
    setError('');
    setResult(null);
    try {
      setResult(await action());
    } catch (e) {
      // Surface 503 (OCR unavailable) with a clear message rather than the generic fallback.
      const msg = e.message || '';
      if (msg.toLowerCase().includes('vision') || msg.toLowerCase().includes('swift') || msg.includes('503')) {
        setError('Screenshot OCR is not available on this server (requires macOS Vision / Swift). Enter the match state manually.');
      } else {
        setError(msg || 'Simulator request failed.');
      }
    } finally {
      setBusy(false);
    }
  }

  function payload() {
    return {
      ...state,
      score: Number(state.score || 0),
      wickets: Number(state.wickets || 0),
      legal_balls: Number(state.legal_balls || 0),
      target_runs: state.target_runs ? Number(state.target_runs) : null,
      target_overs: state.target_overs ? Number(state.target_overs) : null,
      required_run_rate: state.required_run_rate !== '' && state.required_run_rate != null ? Number(state.required_run_rate) : null,
      innings_number: state.innings_number ? Number(state.innings_number) : null,
      batting_order: selectedBatters.map(p => p.id),
      bowlers: selectedBowlers.map(p => p.id),
      simulations: Number(state.simulations || 1000),
    };
  }

  async function uploadScreenshot() {
    if (!screenshot) return;
    await run(async () => {
      const response = await analyseLiveMatchScreenshot(screenshot);
      const x = response.extracted;
      setLiveNames({ teams: x.team_candidates || [], players: x.player_candidates || [] });
      setState(old => ({
        ...old,
        ...(x.format ? { format: x.format } : {}),
        ...(x.score != null ? { score: x.score } : {}),
        ...(x.wickets != null ? { wickets: x.wickets } : {}),
        ...(x.legal_balls != null ? { legal_balls: x.legal_balls } : {}),
        ...(x.target_runs != null ? { target_runs: x.target_runs } : {}),
        ...(x.required_run_rate != null ? { required_run_rate: x.required_run_rate } : {}),
        ...(x.innings_number != null ? { innings_number: x.innings_number } : {}),
      }));
      return { ...x, extraction_message: response.message };
    });
  }

  async function runMode() {
    const p = payload();
    if (mode === 'batting') {
      if (orders.length < 2 || orders[0].every((id, i) => id === orders[1][i])) {
        setError('Add at least three batters and promote one from position 3 or lower to compare orders.');
        return;
      }
      return run(() => compareBattingOrders(p, orders));
    }
    if (mode === 'bowling') {
      if (selectedBowlers.length < 2) {
        setError('Select at least two bowlers to compare.');
        return;
      }
      return run(() => compareBowlingOptions(p, selectedBowlers.map(x => x.id)));
    }
    if (mode === 'live') {
      if (!state.batter_id || !state.non_striker_id || selectedBowlers.length < 2) {
        setError('Confirm both current batters and add at least two available bowlers before requesting a recommendation.');
        return;
      }
      return run(() => compareBowlingOptions(p, selectedBowlers.map(x => x.id), state.overs_bowled || {}));
    }
    if (selectedBatters.length < 2 || selectedBowlers.length < 5) {
      setError('Select at least two available batters and five distinct bowlers to simulate a full innings while respecting over limits.');
      return;
    }
    // simulate mode: run innings then fetch ML win probability
    setWinProb(null);
    await run(async () => {
      const inningsResult = await simulateInnings(p);
      // Fire win-probability request; don't block on failure
      getSimulatorWinProbability(p)
        .then(wp => setWinProb(wp))
        .catch(() => setWinProb(null));
      return inningsResult;
    });
  }

  // Bug 1 fix: when a batter is selected via the live-mode dropdown, also add them to selectedBatters.
  // The bowler case adds to selectedBowlers similarly.
  const updatePlayerPool = (id, key, value) => {
    const p = liveNames.players.find(x => x.id === id);
    if (p) {
      if (key === 'batter_id' || key === 'non_striker_id') {
        setSelectedBatters(x => x.some(y => y.id === id) ? x : [...x, { id, name: p.name }]);
      } else {
        setSelectedBowlers(x => x.some(y => y.id === id) ? x : [...x, { id, name: p.name }]);
      }
    }
    patch(key, id || null);
  };

  // Load batting and bowling sides from the Match XIs (the simulator's single source of XIs).
  const teams = sim.session.teams;
  const xiReady = ['A', 'B'].every(k => teams[k].players?.some(p => p.id));
  const BOWLING_ROLES = ['Bowler', 'Specialist Bowler', 'All-Rounder', 'Bowling All-Rounder', 'Batting All-Rounder', 'All Rounder'];
  const loadFromMatchXis = (batKey) => {
    const bowlKey = batKey === 'A' ? 'B' : 'A';
    const batting = teams[batKey].players.filter(p => p.id).map(p => ({ id: p.id, name: p.name, primary_role: p.primary_role, batting_style: p.batting_style }));
    const pool = teams[bowlKey].players.filter(p => p.id && !p.is_wicketkeeper);
    let bowling = pool.filter(p => p.bowling_type || BOWLING_ROLES.includes(p.primary_role));
    if (bowling.length < 5) bowling = [...bowling, ...pool.slice().reverse().filter(p => !bowling.includes(p))].slice(0, 6);
    const bowlers = bowling.map(p => ({ id: p.id, name: p.name, primary_role: p.primary_role, bowling_type: p.bowling_type, bowling_style: p.bowling_style }));
    setSelectedBatters(batting);
    setSelectedBowlers(bowlers);
    setState(s => ({
      ...s, format: ['T20', 'T20I', 'ODI', 'ODM'].includes(sim.session.format) ? sim.session.format : s.format,
      team1_name: teams[batKey].name, team2_name: teams[bowlKey].name,
      batter_id: batting[0]?.id || null, non_striker_id: batting[1]?.id || null, bowler_id: bowlers[0]?.id || null,
    }));
  };

  return (
    <div className="space-y-5">
      <section className={`${box} flex flex-wrap items-center justify-between gap-3`}>
        <div>
          <p className="text-sm font-semibold text-white">Use the Match XIs</p>
          <p className="text-xs text-slate-400">{xiReady ? `${teams.A.name} and ${teams.B.name} are loaded in Full match. Pick the batting side to fill the batters and the opposing attack.` : 'Upload both Playing XIs under Full match first; they are shared with these tools.'}</p>
        </div>
        <div className="flex gap-2">
          {['A', 'B'].map(k => (
            <button key={k} type="button" disabled={!xiReady} onClick={() => loadFromMatchXis(k)}
              className="rounded-lg border border-indigo-700 bg-indigo-950/60 px-3 py-2 text-xs font-semibold text-indigo-200 hover:bg-indigo-900/70 disabled:opacity-40">
              {teams[k].name} batting
            </button>
          ))}
        </div>
      </section>

      <section className={box}>
        {/* Mode selector */}
        <div className="flex flex-wrap gap-2">
          {[
            ['simulate', 'Simulate innings'],
            ['batting', 'Optimise batting order'],
            ['bowling', 'Compare bowlers'],
            ['live', 'Analyse live match'],
          ].map(([key, label]) => (
            <button
              key={key}
              onClick={() => { setMode(key); setResult(null); setWinProb(null); setError(''); }}
              className={`rounded-lg border px-3 py-2 text-sm ${
                mode === key
                  ? 'border-indigo-500 bg-indigo-600 text-white'
                  : 'border-slate-700 bg-slate-950 text-slate-300'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Match state fields */}
        <div className="mt-4 grid gap-3 md:grid-cols-4">
          <label className="text-xs text-slate-400">
            Format
            <select className={field} value={state.format} onChange={e => patch('format', e.target.value)}>
              <option>T20</option>
              <option>T20I</option>
              <option>ODI</option>
              <option>ODM</option>
            </select>
          </label>

          <label className="text-xs text-slate-400">
            Team batting
            <input
              className={field}
              value={state.team1_name || ''}
              onChange={e => patch('team1_name', e.target.value)}
              placeholder="Name (for your reference)"
            />
          </label>

          <label className="text-xs text-slate-400">
            Opposition
            <input
              className={field}
              value={state.team2_name || ''}
              onChange={e => patch('team2_name', e.target.value)}
              placeholder="Name (for your reference)"
            />
          </label>

          {[
            ['score', 'Current score'],
            ['wickets', 'Wickets lost'],
            ['legal_balls', 'Legal balls bowled'],
            ['target_runs', 'Target (optional)'],
            ['target_overs', 'Innings overs (optional)'],
            ['required_run_rate', 'Required run rate (optional)'],
            ['innings_number', 'Innings number (optional)'],
            ['simulations', 'Simulations'],
          ].map(([key, label]) => (
            <label key={key} className="text-xs text-slate-400">
              {label}
              <input
                className={field}
                type="number"
                min="0"
                value={state[key]}
                onChange={e => patch(key, e.target.value)}
              />
            </label>
          ))}

          <label className="text-xs text-slate-400">
            Venue / ground
            <select
              className={field}
              value={state.venue_id || ''}
              onChange={e => patch('venue_id', e.target.value || null)}
            >
              <option value="">Not specified</option>
              {options.venues.map(v => (
                <option key={v.id} value={v.id}>{v.name}</option>
              ))}
            </select>
          </label>

          <label className="text-xs text-slate-400">
            Competition
            <select
              className={field}
              value={state.competition_id || ''}
              onChange={e => patch('competition_id', e.target.value || null)}
            >
              <option value="">Not specified</option>
              {options.competitions
                .filter(c => !c.format || c.format === state.format)
                .map(c => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
            </select>
          </label>
        </div>

        <p className="mt-3 text-xs text-slate-500">
          Simulation supports T20 and ODI rules. Overs input is total legal balls completed (for example, 10.2 overs = 62).
          Test and multi-day matches are not simulated.
        </p>

        {/* Player search */}
        <form onSubmit={findPlayers} className="mt-4 flex gap-2">
          <input
            className={`${field} mt-0 max-w-md`}
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search CPI players to add to lineups"
          />
          <button className="rounded border border-slate-700 px-3 text-sm" type="submit">
            Find players
          </button>
        </form>

        {players.length > 0 && (
          <div className="mt-2 max-h-36 overflow-auto rounded border border-slate-800">
            {players.map(p => (
              <div key={p.id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm even:bg-slate-950">
                <span>
                  {p.name}
                  <small className="ml-2 text-slate-500">{p.primary_role || 'Role unknown'}</small>
                </span>
                <span className="flex gap-2">
                  <button type="button" className="text-indigo-300" onClick={() => addPlayer(p, 'bat')}>
                    + batting XI
                  </button>
                  <button type="button" className="text-emerald-300" onClick={() => addPlayer(p, 'bowl')}>
                    + bowler
                  </button>
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Batting order and bowling options panels */}
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <div>
            <h3 className="text-sm font-semibold">
              Batting order{' '}
              <span className="text-xs font-normal text-slate-500">(Use ↑ ↓ to reorder)</span>
            </h3>
            <div className="mt-2 space-y-1">
              {selectedBatters.map((p, i) => (
                <div
                  key={p.id}
                  className="flex items-center justify-between rounded bg-slate-950 px-3 py-2 text-sm"
                >
                  <span>{i + 1}. {p.name}</span>
                  <span>
                    <button
                      className="px-2 text-slate-300"
                      onClick={() => setSelectedBatters(xs => {
                        const a = [...xs];
                        if (i > 0) [a[i - 1], a[i]] = [a[i], a[i - 1]];
                        return a;
                      })}
                    >↑</button>
                    <button
                      className="px-2 text-slate-300"
                      onClick={() => setSelectedBatters(xs => {
                        const a = [...xs];
                        if (i < a.length - 1) [a[i + 1], a[i]] = [a[i], a[i + 1]];
                        return a;
                      })}
                    >↓</button>
                    <button
                      className="px-2 text-red-300"
                      onClick={() => setSelectedBatters(xs => xs.filter(x => x.id !== p.id))}
                    >×</button>
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div>
            <h3 className="text-sm font-semibold">
              Bowling options{' '}
              <span className="text-xs font-normal text-slate-500">(remove an option to exclude it)</span>
            </h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {selectedBowlers.map(p => (
                <label
                  key={p.id}
                  className="flex items-center gap-2 rounded-full border border-slate-700 px-3 py-1 text-xs"
                >
                  <span>{p.name}</span>
                  <span className="text-slate-500">overs</span>
                  <input
                    aria-label={`${p.name} overs already bowled`}
                    className="w-9 bg-transparent text-center"
                    type="number"
                    min="0"
                    max={state.format.startsWith('T20') ? 4 : 10}
                    value={state.overs_bowled?.[p.id] || 0}
                    onChange={e => patch('overs_bowled', { ...state.overs_bowled, [p.id]: Number(e.target.value) })}
                  />
                  <button
                    onClick={() => setSelectedBowlers(xs => xs.filter(x => x.id !== p.id))}
                    className="text-red-300"
                  >×</button>
                </label>
              ))}
            </div>
          </div>
        </div>

        {/* Current batter / bowler selectors (shown when batters are available) */}
        {selectedBatters.length >= 2 && (
          <div className="mt-3 grid gap-3 md:grid-cols-3">
            {[['batter_id', 'Striker'], ['non_striker_id', 'Non-striker']].map(([key, label]) => (
              <label key={key} className="text-xs text-slate-400">
                {label}
                <select
                  className={field}
                  value={state[key] || ''}
                  onChange={e => setFromPlayer(key, e.target.value)}
                >
                  <option value="">Select batter</option>
                  {selectedBatters.map(p => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </label>
            ))}

            {selectedBowlers.length > 0 && (
              <label className="text-xs text-slate-400">
                Current bowler
                <select
                  className={field}
                  value={state.bowler_id || ''}
                  onChange={e => setFromPlayer('bowler_id', e.target.value)}
                >
                  <option value="">Select bowler</option>
                  {selectedBowlers.map(p => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </label>
            )}
          </div>
        )}

        {/* Live match panel */}
        {mode === 'live' && (
          <div className="mt-5 rounded-xl border border-indigo-900/60 bg-indigo-950/20 p-4">
            <h3 className="font-semibold">Analyse Live Match</h3>
            <p className="mt-1 text-xs text-slate-400">
              Upload a scorecard screenshot, review the extracted values and correct them before running a recommendation.
              Repeated screenshots update only fields that were confidently read.
            </p>

            <div className="mt-3 flex flex-wrap items-center gap-3">
              <input
                type="file"
                accept="image/png,image/jpeg"
                onChange={e => setScreenshot(e.target.files?.[0] || null)}
                className="text-xs text-slate-400"
              />
              <button onClick={uploadScreenshot} disabled={!screenshot || busy} className={button}>
                Extract screenshot
              </button>
            </div>

            {/* Team candidates */}
            {liveNames.teams.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-400">
                Team candidates:{' '}
                {liveNames.teams.map(x => (
                  <span key={x.id} className="inline-flex gap-1 rounded border border-slate-700 px-2 py-1">
                    {x.name}
                    <button onClick={() => patch('team1_name', x.name)} className="text-indigo-300">
                      set batting
                    </button>
                    <button onClick={() => patch('team2_name', x.name)} className="text-indigo-300">
                      set opposition
                    </button>
                  </span>
                ))}
              </div>
            )}

            {/* Player candidates */}
            {liveNames.players.length > 0 && (
              <>
                {/* Confirm dropdowns for striker / non-striker / bowler */}
                <div className="mt-3 grid gap-3 md:grid-cols-3">
                  {[
                    ['batter_id', 'Striker'],
                    ['non_striker_id', 'Non-striker'],
                    ['bowler_id', 'Current bowler'],
                  ].map(([key, label]) => (
                    <label className="text-xs text-slate-400" key={key}>
                      {label}
                      <select
                        className={field}
                        value={state[key] || ''}
                        onChange={e => updatePlayerPool(e.target.value, key, e.target.value)}
                      >
                        <option value="">Confirm player</option>
                        {liveNames.players.map(p => (
                          <option key={p.id} value={p.id}>
                            {p.name} ({p.confidence})
                          </option>
                        ))}
                      </select>
                    </label>
                  ))}
                </div>

                {/* Quick-add buttons — batting XI and bowlers */}
                <div className="mt-3 flex flex-wrap gap-2">
                  {liveNames.players.map(p => (
                    <button
                      key={`bat-${p.id}`}
                      onClick={() => setSelectedBatters(xs =>
                        xs.some(x => x.id === p.id) ? xs : [...xs, { id: p.id, name: p.name }]
                      )}
                      className="rounded border border-indigo-900 px-2 py-1 text-xs text-indigo-300"
                    >
                      Add {p.name} to batting XI
                    </button>
                  ))}
                  {liveNames.players.map(p => (
                    <button
                      key={`bowl-${p.id}`}
                      onClick={() => setSelectedBowlers(xs =>
                        xs.some(x => x.id === p.id) ? xs : [...xs, { id: p.id, name: p.name }]
                      )}
                      className="rounded border border-emerald-900 px-2 py-1 text-xs text-emerald-300"
                    >
                      Add {p.name} to available bowlers
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        {/* Action bar */}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          {mode === 'batting' && selectedBatters.length > 2 && (
            <label className="text-xs text-slate-400">
              Promote batter
              <select
                className={`${field} mt-1`}
                value={selectedForOrder}
                onChange={e => setSelectedForOrder(e.target.value)}
              >
                <option value="">Choose player</option>
                {selectedBatters.slice(2).map(p => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </label>
          )}

          <button disabled={busy} onClick={runMode} className={button}>
            {busy
              ? 'Running scenarios…'
              : mode === 'bowling'
                ? 'Compare available bowlers'
                : mode === 'batting'
                  ? 'Compare batting orders'
                  : mode === 'live'
                    ? 'Run tactical analysis'
                    : 'Simulate innings'}
          </button>

          <label className="text-xs text-slate-400">
            Random seed
            <input
              className={`${field} mt-1 w-24`}
              type="number"
              value={state.seed}
              onChange={e => patch('seed', Number(e.target.value))}
            />
          </label>
        </div>

        {error && (
          <p role="alert" className="mt-3 rounded bg-red-950/60 p-3 text-sm text-red-300">
            {error}
          </p>
        )}
      </section>

      {/* Results section */}
      {result && (
        <section className={`${box} space-y-4`}>
          {result.expected_final_score != null ? (
            <>
              {/* Innings simulation result */}
              <div className="flex flex-wrap gap-6">
                <div>
                  <p className="text-xs text-slate-500">Expected final score</p>
                  <p className="text-3xl font-bold text-white">{result.expected_final_score}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Median</p>
                  <p className="text-3xl font-bold text-indigo-300">{result.median_projected_score}</p>
                </div>
                {result.target_reach_probability != null && (
                  <div>
                    <p className="text-xs text-slate-500">Target reached</p>
                    <p className="text-3xl font-bold text-emerald-300">
                      {(result.target_reach_probability * 100).toFixed(1)}%
                    </p>
                  </div>
                )}
              </div>

              {/* ML Win Probability block */}
              {winProb && winProb.available && (
                <div className="rounded-lg border border-indigo-800/50 bg-indigo-950/30 p-3">
                  <p className="text-xs font-semibold uppercase text-indigo-400">
                    ML Win Probability · {winProb.model_version}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-6">
                    <div>
                      <p className="text-xs text-slate-500">{state.team1_name || 'Batting team'} wins</p>
                      <p className="text-2xl font-bold text-indigo-300">
                        {(winProb.team1_win * 100).toFixed(1)}%
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-slate-500">{state.team2_name || 'Opposition'} wins</p>
                      <p className="text-2xl font-bold text-amber-300">
                        {(winProb.team2_win * 100).toFixed(1)}%
                      </p>
                    </div>
                    {winProb.draw_or_tie > 0.005 && (
                      <div>
                        <p className="text-xs text-slate-500">Draw / tie</p>
                        <p className="text-2xl font-bold text-slate-300">
                          {(winProb.draw_or_tie * 100).toFixed(1)}%
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              )}

              <div className="grid gap-6 md:grid-cols-2">
                <div>
                  <h3 className="mb-2 text-sm font-semibold">
                    Projected score distribution · count by 10-run band
                  </h3>
                  <Histogram rows={result.score_histogram || []} />
                </div>
                <div>
                  <h3 className="mb-2 text-sm font-semibold">Expected runs by innings phase</h3>
                  {Object.entries(result.phase_projection || {}).map(([name, x]) => (
                    <div key={name} className="mb-3">
                      <div className="flex justify-between text-sm">
                        <span className="capitalize">{name}</span>
                        <span>{x.expected_runs}</span>
                      </div>
                      <div className="mt-1 h-2 rounded bg-slate-800">
                        <div
                          className="h-2 rounded bg-emerald-400"
                          style={{ width: `${Math.min(100, x.expected_runs / Math.max(1, result.expected_final_score) * 100)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                  <h4 className="mt-4 text-xs font-semibold uppercase text-slate-500">
                    Wicket count probabilities
                  </h4>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {Object.entries(result.wicket_distribution || {}).map(([w, p]) => (
                      <span key={w} className="rounded bg-slate-950 px-2 py-1 text-xs">
                        {w} wickets · {(p * 100).toFixed(1)}%
                      </span>
                    ))}
                  </div>
                </div>
              </div>

              <p className="text-xs text-slate-500">
                {result.simulations.toLocaleString()} simulations · {result.model_version} ·{' '}
                {result.model_trained ? 'trained on CPI delivery history' : 'fallback model'}
              </p>
            </>
          ) : result.options ? (
            <>
              {/* Bowling options result */}
              <h3 className="font-semibold">
                Bowling alternatives · {result.ranking_explanation}
              </h3>
              {result.options.map(x => (
                <div key={x.bowler_id} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="flex flex-wrap justify-between gap-2 text-sm">
                    <strong>
                      {selectedBowlers.find(p => p.id === x.bowler_id)?.name || x.bowler_id}
                    </strong>
                    <span>
                      Expected runs {x.expected_runs_conceded} · wicket chance{' '}
                      {(x.wicket_probability * 100).toFixed(1)}% · impact index {x.estimated_impact_score}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    {x.historical_matchup_evidence
                      ? `Historical matchup: ${x.historical_matchup_evidence.matches} matches · ${x.historical_matchup_evidence.legal_balls} legal balls · economy ${x.historical_matchup_evidence.economy}`
                      : 'No direct CPI matchup sample; prediction uses role, format and phase history.'}
                  </p>
                </div>
              ))}
            </>
          ) : (
            <>
              {/* Batting order comparison result */}
              <h3 className="font-semibold">Batting order comparison</h3>
              <p className="text-sm text-slate-400">
                Original order projected {result.original_order?.expected_final_score}; compare changes with the baseline.
              </p>
              {(result.comparisons || []).map((x, i) => (
                <div key={i} className="rounded border border-slate-800 bg-slate-950 p-3 text-sm">
                  Order {i + 2}: expected {x.expected_final_score} · Δ{' '}
                  {x.difference_from_original > 0 ? '+' : ''}{x.difference_from_original} runs · target{' '}
                  {x.target_reach_probability != null
                    ? `${(x.target_reach_probability * 100).toFixed(1)}%`
                    : '—'}
                </div>
              ))}
            </>
          )}
        </section>
      )}

      {/* OCR raw text review */}
      {result?.raw_text && (
        <section className={box}>
          <h3 className="font-semibold">OCR text and review</h3>
          <p className="mt-2 whitespace-pre-wrap text-sm text-slate-400">{result.raw_text}</p>
          <p className="mt-2 text-xs text-amber-300">
            Uncertain: {(result.uncertain_fields || []).join(', ') || 'Review every extracted field before analysis.'}
          </p>
        </section>
      )}
    </div>
  );
}

export default function MatchSimulator() {
  const sim = useSimSession();
  const [view, setView] = useState('match');
  return (
    <div className="space-y-5">
      <PageHeader
        title="Match Simulator"
        subtitle="Ball-by-ball simulation calibrated on CPI delivery history: upload both Playing XIs, set conditions, validate, then simulate one match or thousands."
      />
      <div className="flex flex-wrap gap-2" role="tablist">
        {[['match', 'Full match'], ['tools', 'Innings & live tools']].map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={view === key} onClick={() => setView(key)}
            className={`rounded-lg border px-4 py-2 text-sm font-semibold ${view === key ? 'border-indigo-500 bg-indigo-600 text-white' : 'border-slate-700 bg-slate-950 text-slate-300 hover:text-white'}`}>
            {label}
          </button>
        ))}
      </div>
      {view === 'match' ? <FullMatchSimulator sim={sim} /> : <InningsTools sim={sim} />}
    </div>
  );
}
