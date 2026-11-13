/**
 * Playing XI editor for one side of a simulated match (the only XI upload UI in CPI).
 *
 * Upload by pasted names, team-sheet image (OCR) or CSV, load a verified preset or
 * a saved XI, then fix the lineup: batting order, captain / wicketkeeper tags,
 * swap unmatched or wrong players via CPI player search, add or remove players.
 * Every name is resolved with the backend's CPI player identification (/xi/resolve).
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { resolveXi, uploadXiFile, searchPlayerForXi, getXiPresets } from '../../../services/api';
import { deleteSavedXi, loadSavedXis, saveXiToLibrary } from './session';

const input = 'w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:border-indigo-500 focus:outline-none';
const FLAG_TEXT = { unmatched: 'Not in CPI database', duplicate: 'Duplicate', both: 'Also in the other XI' };

let presetCache = null;

function fromResolved(res) {
  return (res.players || []).map(p => ({
    id: p.id || null, name: p.name || p.input_name, input_name: p.input_name, matched: !!p.id, confidence: p.confidence,
    primary_role: p.primary_role, batting_style: p.batting_style, bowling_type: p.bowling_type, bowling_style: p.bowling_style,
    is_captain: !!p.is_captain, is_wicketkeeper: !!p.is_wicketkeeper, alternatives: p.alternatives || [],
  }));
}

function PlayerSearch({ initial = '', onPick, onCancel, label }) {
  const [q, setQ] = useState(initial);
  const [results, setResults] = useState([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (q.trim().length < 2) { setResults([]); return undefined; }
    let live = true;
    const t = setTimeout(() => {
      setBusy(true);
      searchPlayerForXi(q.trim()).then(r => live && setResults(r.results || [])).catch(() => live && setResults([])).finally(() => live && setBusy(false));
    }, 250);
    return () => { live = false; clearTimeout(t); };
  }, [q]);
  return (
    <div className="mt-2 w-full rounded-lg border border-indigo-700/60 bg-slate-900 p-3">
      <div className="flex items-center justify-between text-xs">
        <span className="font-semibold text-indigo-300">{label}</span>
        <button type="button" onClick={onCancel} className="text-slate-400 hover:text-white">Cancel</button>
      </div>
      <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="Search the CPI player database…" className={`${input} mt-2 text-xs`} />
      {busy && <p className="mt-1 text-[10px] text-slate-500">Searching…</p>}
      {results.length > 0 && (
        <div className="mt-2 max-h-40 divide-y divide-slate-800 overflow-y-auto rounded border border-slate-800 bg-slate-950">
          {results.map(r => (
            <button type="button" key={r.id} onClick={() => onPick(r)} className="flex w-full items-center justify-between p-2 text-left text-xs hover:bg-indigo-950/40">
              <span><span className="font-semibold text-white">{r.name}</span><span className="ml-2 text-[10px] text-slate-400">{r.primary_role}{r.bowling_type ? ` · ${r.bowling_type}` : ''}</span></span>
              <span className="rounded bg-indigo-600 px-2 py-0.5 text-[10px] text-white">Select</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function XiEditor({ teamKey, team, onChange, flags = {}, format, onDone }) {
  const [tab, setTab] = useState(team.players.length ? 'lineup' : 'paste');
  const [pasteText, setPasteText] = useState('');
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [presets, setPresets] = useState(presetCache || []);
  const [saved, setSaved] = useState(loadSavedXis);
  const [swapping, setSwapping] = useState(null); // index | 'add'

  useEffect(() => {
    if (presetCache) return;
    getXiPresets().then(r => { presetCache = r.presets || []; setPresets(presetCache); }).catch(() => {});
  }, []);

  const players = team.players || [];
  const setPlayers = list => onChange({ ...team, players: list.map((p, i) => ({ ...p, order: i + 1 })) });

  async function resolveText() {
    if (!pasteText.trim()) { setError('Paste at least one player name.'); return; }
    setBusy(true); setError(''); setMessage('');
    try {
      const res = await resolveXi({ team_name: team.name, text: pasteText, format });
      const list = fromResolved(res);
      onChange({ ...team, players: list });
      setMessage(`Resolved ${res.matched_count} of ${res.total_players} names against the CPI database.`);
      setTab('lineup');
    } catch (e) { setError(e.message || 'Could not resolve the names.'); } finally { setBusy(false); }
  }

  async function uploadFile() {
    if (!file) { setError('Choose a team-sheet image or CSV/TXT file.'); return; }
    setBusy(true); setError(''); setMessage('');
    try {
      const res = await uploadXiFile(file);
      onChange({ ...team, players: fromResolved(res) });
      setMessage(`Extracted and resolved ${res.matched_count} of ${res.total_players} players.`);
      setTab('lineup');
    } catch (e) {
      const msg = e.message || '';
      setError(/503|vision|swift|extract text/i.test(msg) ? 'Could not read this image (OCR needs macOS Vision on the server). Paste the names instead.' : msg || 'Upload failed.');
    } finally { setBusy(false); }
  }

  function loadXi(xi, label) {
    const name = (xi.team_name || xi.name || team.name || '').split('—')[0].trim() || team.name;
    onChange({ ...team, name, team_id: xi.team_id || team.team_id || null, players: (xi.players || []).map(p => ({ ...p, matched: !!p.id })) });
    setMessage(`Loaded ${label}.`);
    setTab('lineup');
  }

  const move = (i, d) => {
    const j = i + d;
    if (j < 0 || j >= players.length) return;
    const list = [...players];
    [list[i], list[j]] = [list[j], list[i]];
    setPlayers(list);
  };
  const toggle = (i, key) => {
    setPlayers(players.map((p, idx) => {
      if (key === 'is_captain' || key === 'is_wicketkeeper') {
        // One captain and one keeper per side.
        if (idx === i) return { ...p, [key]: !p[key] };
        return players[i][key] ? p : { ...p, [key]: false };
      }
      return p;
    }));
  };
  const pick = (r, target = swapping) => {
    const chosen = { id: r.id, name: r.name, input_name: r.name, matched: true, confidence: 'user_selected', primary_role: r.primary_role,
      batting_style: r.batting_style, bowling_type: r.bowling_type, bowling_style: r.bowling_style, is_captain: false, is_wicketkeeper: false };
    if (target === 'add') setPlayers([...players, chosen]);
    else setPlayers(players.map((p, i) => (i === target ? { ...chosen, is_captain: p.is_captain, is_wicketkeeper: p.is_wicketkeeper } : p)));
    setSwapping(null);
  };

  const tabs = [['lineup', `Lineup (${players.length}/11)`], ['paste', 'Paste names'], ['file', 'Image / CSV'], ['presets', 'Presets'], ['saved', `Saved (${saved.length})`]];

  return (
    <section className="rounded-xl border border-indigo-900/50 bg-slate-900 p-4" aria-label={`Edit ${team.name || `Team ${teamKey}`} XI`}>
      <div className="flex flex-wrap items-end gap-3">
        <label className="min-w-[220px] flex-1 text-xs text-slate-400">
          Team {teamKey} name
          <input className={`${input} mt-1`} value={team.name} maxLength={80} onChange={e => onChange({ ...team, name: e.target.value, team_id: null })} placeholder="e.g. India" />
        </label>
        <div className="flex gap-2">
          <button type="button" disabled={!players.length} onClick={() => { setSaved(saveXiToLibrary({ ...team, id: team.savedId })); setMessage('Saved to your XI library.'); }}
            className="rounded-lg border border-indigo-700 bg-indigo-950/60 px-3 py-2 text-xs font-semibold text-indigo-300 hover:bg-indigo-900/80 disabled:opacity-40">Save XI</button>
          <button type="button" disabled={!players.length} onClick={() => onChange({ ...team, players: [] })}
            className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-400 hover:bg-slate-800 disabled:opacity-40">Clear</button>
          {onDone && <button type="button" onClick={onDone} className="rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-500">Done</button>}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap border-b border-slate-800" role="tablist">
        {tabs.map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => { setTab(key); setError(''); }}
            className={`border-b-2 px-3 py-2 text-xs font-semibold ${tab === key ? 'border-indigo-500 text-indigo-300' : 'border-transparent text-slate-400 hover:text-slate-200'}`}>{label}</button>
        ))}
      </div>

      {error && <div role="alert" className="mt-3 rounded-lg border border-red-800/60 bg-red-950/40 p-2.5 text-xs text-red-300">{error}</div>}
      {message && !error && <div role="status" className="mt-3 rounded-lg border border-emerald-800/60 bg-emerald-950/40 p-2.5 text-xs text-emerald-300">{message}</div>}

      {tab === 'paste' && (
        <div className="mt-3 space-y-3">
          <label className="block text-xs text-slate-400">
            One name per line or comma-separated, in batting order. Tags like (c), (wk), (c/wk), * and † are detected.
            <textarea rows={8} value={pasteText} onChange={e => setPasteText(e.target.value)} className={`${input} mt-1 font-mono text-xs`}
              placeholder={'1. Rohit Sharma (c)\n2. Virat Kohli\n3. Rishabh Pant (wk)\n…'} />
          </label>
          <button type="button" disabled={busy || !pasteText.trim()} onClick={resolveText} className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50">
            {busy ? 'Resolving against CPI…' : 'Resolve names'}
          </button>
        </div>
      )}

      {tab === 'file' && (
        <div className="mt-3 space-y-3">
          <label className="block cursor-pointer rounded-xl border-2 border-dashed border-slate-700 bg-slate-950/40 p-5 text-center hover:border-indigo-600">
            <input type="file" className="sr-only" accept="image/png,image/jpeg,image/webp,.csv,.txt" onChange={e => setFile(e.target.files?.[0] || null)} />
            <span className="text-sm font-medium text-indigo-300">{file ? file.name : 'Choose a team-sheet image or CSV/TXT roster'}</span>
            <span className="mt-1 block text-xs text-slate-500">PNG, JPG, WEBP (OCR) or CSV/TXT with one name per row · up to 10 MB</span>
          </label>
          <button type="button" disabled={busy || !file} onClick={uploadFile} className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50">
            {busy ? 'Extracting and resolving…' : 'Upload and resolve'}
          </button>
        </div>
      )}

      {tab === 'presets' && (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {!presets.length && <p className="text-xs text-slate-500">Loading verified presets…</p>}
          {presets.map(pr => (
            <button type="button" key={pr.id} onClick={() => loadXi(pr, pr.name)} className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-left hover:border-indigo-500/60">
              <span className="flex items-center justify-between gap-2"><span className="text-sm font-semibold text-white">{pr.name}</span><span className="rounded bg-indigo-900/60 px-1.5 py-0.5 text-[10px] text-indigo-300">{pr.format}</span></span>
              <span className="mt-1 block text-[11px] text-slate-400">{pr.description}</span>
              <span className="mt-1 block text-[10px] text-slate-500">{pr.matched_count}/{pr.total_players} matched</span>
            </button>
          ))}
        </div>
      )}

      {tab === 'saved' && (
        <div className="mt-3 space-y-2">
          {!saved.length && <p className="text-xs text-slate-500">No saved XIs yet. Build a lineup and press “Save XI”.</p>}
          {saved.map(s => (
            <div key={s.id} className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/60 p-2.5">
              <button type="button" className="text-left" onClick={() => loadXi({ ...s, players: s.players }, s.team_name || s.name)}>
                <span className="block text-sm font-semibold text-white hover:text-indigo-300">{s.team_name || s.name}</span>
                <span className="text-[11px] text-slate-500">{s.players?.length || 0} players · saved {s.updatedAt ? new Date(s.updatedAt).toLocaleDateString() : ''}</span>
              </button>
              <button type="button" aria-label={`Delete ${s.team_name || s.name}`} onClick={() => setSaved(deleteSavedXi(s.id))} className="rounded px-2 py-1 text-xs text-red-400 hover:bg-red-950/40">✕</button>
            </div>
          ))}
        </div>
      )}

      {tab === 'lineup' && (
        <div className="mt-3">
          {!players.length && <p className="text-xs text-slate-500">No players yet. Paste names, upload a team sheet, or load a preset.</p>}
          {players.length > 0 && (
            <ol className="divide-y divide-slate-800 overflow-hidden rounded-xl border border-slate-800 bg-slate-950/70">
              {players.map((p, i) => {
                const flag = flags[i];
                return (
                  <li key={`${p.id || p.input_name}-${i}`} className={`flex flex-wrap items-center gap-2 px-3 py-2 text-xs ${flag ? 'bg-red-950/20' : ''}`}>
                    <span className="w-5 text-center font-mono font-semibold text-slate-500">{i + 1}</span>
                    <div className="min-w-[180px] flex-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        {p.id ? <Link to={`/players/${p.id}`} className="font-semibold text-white hover:text-indigo-300">{p.name}</Link>
                          : <span className="font-semibold text-amber-300">{p.input_name || p.name}</span>}
                        {p.is_captain && <span className="rounded bg-amber-500/20 px-1 text-[10px] font-bold text-amber-300">C</span>}
                        {p.is_wicketkeeper && <span className="rounded bg-cyan-500/20 px-1 text-[10px] font-bold text-cyan-300">WK</span>}
                        {flag && <span className="rounded bg-red-900/50 px-1.5 text-[10px] font-semibold text-red-300">{FLAG_TEXT[flag]}</span>}
                        {p.confidence && !['exact', 'alias', 'user_selected', 'unmatched'].includes(p.confidence) && p.id && <span className="rounded bg-slate-800 px-1.5 text-[10px] text-slate-400" title={p.input_name ? `Typed: ${p.input_name}` : ''}>{p.confidence.replace('_', ' ')} match — check</span>}
                      </div>
                      <div className="text-[10px] text-slate-500">{[p.primary_role, p.batting_style, p.bowling_type && `${p.bowling_type}${p.bowling_style ? ` (${p.bowling_style})` : ''}`].filter(Boolean).join(' · ') || (p.id ? 'Role from CPI history' : 'Swap to a CPI player')}</div>
                    </div>
                    <div className="ml-auto flex items-center gap-1">
                      <button type="button" title="Captain" aria-pressed={!!p.is_captain} onClick={() => toggle(i, 'is_captain')} className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${p.is_captain ? 'bg-amber-500 text-slate-950' : 'bg-slate-800 text-slate-400 hover:text-white'}`}>C</button>
                      <button type="button" title="Wicketkeeper" aria-pressed={!!p.is_wicketkeeper} onClick={() => toggle(i, 'is_wicketkeeper')} className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${p.is_wicketkeeper ? 'bg-cyan-500 text-slate-950' : 'bg-slate-800 text-slate-400 hover:text-white'}`}>WK</button>
                      <button type="button" onClick={() => setSwapping(swapping === i ? null : i)} className="rounded border border-slate-700 bg-slate-800 px-2 py-0.5 text-[10px] text-indigo-300 hover:bg-slate-700">Swap</button>
                      <button type="button" aria-label="Move up" disabled={i === 0} onClick={() => move(i, -1)} className="rounded px-1.5 text-slate-400 hover:bg-slate-800 disabled:opacity-20">↑</button>
                      <button type="button" aria-label="Move down" disabled={i === players.length - 1} onClick={() => move(i, 1)} className="rounded px-1.5 text-slate-400 hover:bg-slate-800 disabled:opacity-20">↓</button>
                      <button type="button" aria-label="Remove player" onClick={() => setPlayers(players.filter((_, j) => j !== i))} className="rounded px-1.5 text-red-400 hover:bg-slate-800">✕</button>
                    </div>
                    {!p.id && p.alternatives?.length > 0 && swapping !== i && (
                      <div className="w-full pl-7 text-[10px] text-slate-400">Did you mean: {p.alternatives.map(a => (
                        <button type="button" key={a.id} onClick={() => pick({ id: a.id, name: a.name }, i)} className="ml-1 rounded bg-slate-800 px-1.5 py-0.5 text-indigo-300 hover:bg-slate-700">{a.name}</button>
                      ))}</div>
                    )}
                    {swapping === i && <PlayerSearch initial={p.input_name || p.name || ''} label={`Replace ${p.name || p.input_name}`} onPick={r => pick(r, i)} onCancel={() => setSwapping(null)} />}
                  </li>
                );
              })}
            </ol>
          )}
          {players.length < 11 && (swapping === 'add'
            ? <PlayerSearch label="Add a player" onPick={r => pick(r, 'add')} onCancel={() => setSwapping(null)} />
            : <button type="button" onClick={() => setSwapping('add')} className="mt-2 rounded-lg border border-dashed border-slate-700 px-3 py-2 text-xs text-slate-400 hover:border-indigo-500 hover:text-indigo-300">+ Add player ({11 - players.length} more needed)</button>)}
        </div>
      )}
    </section>
  );
}
