/**
 * Match Simulator session: the single source of truth for match-specific Playing XIs.
 *
 * Both XIs, conditions and the latest results persist in sessionStorage for the
 * browser session, so moving between CPI screens and back keeps the setup.
 * Saved XIs (a personal library) persist in localStorage under the key the old
 * global XI feature used, so previously saved lineups are not lost.
 */
import { useCallback, useEffect, useState } from 'react';

const SESSION_KEY = 'cpi_sim_session_v1';
const SAVED_KEY = 'cpi_saved_xis';

export const emptyTeam = name => ({ name, team_id: null, players: [] });

const DEFAULT_SESSION = {
  format: 'T20',
  overs: '',
  teams: { A: emptyTeam('Team A'), B: emptyTeam('Team B') },
  conditions: { venue_id: '', venue_name: '', pitch: 'balanced', weather: 'clear', toss_winner: 'random', toss_decision: 'auto', super_over: true },
  seed: '',
  simulations: 1000,
  wp_simulations: '',
  validation: null,
  match: null,
  monteCarlo: null,
};

function read(key, fallback) {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? { ...fallback, ...JSON.parse(raw) } : fallback;
  } catch {
    return fallback;
  }
}

export function useSimSession() {
  const [session, setSession] = useState(() => read(SESSION_KEY, DEFAULT_SESSION));
  useEffect(() => {
    try {
      sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
    } catch {
      // Large results may exceed the quota: keep the setup, drop the stored results.
      try { sessionStorage.setItem(SESSION_KEY, JSON.stringify({ ...session, match: null, monteCarlo: null })); } catch { /* ignore */ }
    }
  }, [session]);
  const update = useCallback(patch => setSession(s => ({ ...s, ...(typeof patch === 'function' ? patch(s) : patch) })), []);
  const setTeam = useCallback((key, team) => setSession(s => ({ ...s, teams: { ...s.teams, [key]: team }, validation: null })), []);
  const setConditions = useCallback(patch => setSession(s => ({ ...s, conditions: { ...s.conditions, ...patch }, validation: null })), []);
  const reset = useCallback(() => setSession(DEFAULT_SESSION), []);
  return { session, update, setTeam, setConditions, reset };
}

export function loadSavedXis() {
  try { return JSON.parse(localStorage.getItem(SAVED_KEY) || '[]'); } catch { return []; }
}

export function saveXiToLibrary(xi) {
  const id = xi.id || `custom-${Date.now()}`;
  const entry = { ...xi, id, team_name: xi.name, updatedAt: new Date().toISOString() };
  const list = [entry, ...loadSavedXis().filter(x => x.id !== id)].slice(0, 20);
  try { localStorage.setItem(SAVED_KEY, JSON.stringify(list)); } catch { /* ignore */ }
  return list;
}

export function deleteSavedXi(id) {
  const list = loadSavedXis().filter(x => x.id !== id);
  try { localStorage.setItem(SAVED_KEY, JSON.stringify(list)); } catch { /* ignore */ }
  return list;
}

/** Instant, client-side checks; the server repeats them and adds database checks. */
export function localIssues(teams) {
  const issues = { A: [], B: [] };
  const playerFlags = { A: {}, B: {} };
  const owner = {};
  for (const key of ['A', 'B']) {
    const players = teams[key]?.players || [];
    const label = teams[key]?.name || `Team ${key}`;
    if (players.length !== 11) issues[key].push(`${label} needs exactly 11 players (has ${players.length}).`);
    const seen = {};
    players.forEach((p, i) => {
      if (!p.id) {
        playerFlags[key][i] = 'unmatched';
        return;
      }
      if (seen[p.id] !== undefined) {
        playerFlags[key][i] = 'duplicate';
        playerFlags[key][seen[p.id]] = 'duplicate';
      } else seen[p.id] = i;
    });
    const unmatched = players.filter(p => !p.id).length;
    if (unmatched) issues[key].push(`${unmatched} player${unmatched > 1 ? 's are' : ' is'} not matched to the CPI database; swap or remove ${unmatched > 1 ? 'them' : 'it'}.`);
    if (Object.values(playerFlags[key]).includes('duplicate')) issues[key].push('The same player appears more than once.');
    const keepers = players.filter(p => p.is_wicketkeeper).length;
    if (players.length && !keepers) issues[key].push('No wicketkeeper marked (stumpings will become catches).');
    for (const p of players) if (p.id) (owner[p.id] = owner[p.id] || new Set()).add(key);
  }
  for (const key of ['A', 'B']) {
    (teams[key]?.players || []).forEach((p, i) => {
      if (p.id && owner[p.id]?.size > 1) playerFlags[key][i] = 'both';
    });
    if ((teams[key]?.players || []).some(p => p.id && owner[p.id]?.size > 1)) issues[key].push('A player is selected in both XIs.');
  }
  const blocking = ['A', 'B'].some(k => issues[k].some(m => !m.startsWith('No wicketkeeper')));
  return { issues, playerFlags, blocking };
}

export function requestBody(session, extra = {}) {
  const team = t => ({
    name: (t.name || '').trim(), team_id: t.team_id || null,
    players: (t.players || []).map(p => ({ id: p.id || null, name: p.name || null, input_name: p.input_name || null, is_captain: !!p.is_captain, is_wicketkeeper: !!p.is_wicketkeeper })),
  });
  const c = session.conditions;
  return {
    format: session.format,
    overs: session.overs && session.format !== 'Test' ? Number(session.overs) : null,
    teams: { A: team(session.teams.A), B: team(session.teams.B) },
    conditions: { venue_id: c.venue_id || null, pitch: c.pitch, weather: c.weather, toss_winner: c.toss_winner, toss_decision: c.toss_decision, super_over: !!c.super_over },
    seed: session.seed === '' || session.seed === null ? null : Number(session.seed),
    simulations: Number(session.simulations) || 500,
    wp_simulations: session.wp_simulations ? Math.min(5000, Math.max(100, Number(session.wp_simulations))) : null,
    ...extra,
  };
}
