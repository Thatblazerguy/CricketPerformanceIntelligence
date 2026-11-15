/**
 * Global player quick-search (⌘K / Ctrl+K or "/"). Queries GET /players?name=
 * and jumps straight to the profile; arrow keys move through results.
 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getPlayers } from '../services/api';
import Icon from './icons';

export default function QuickSearch() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    const onKey = e => {
      const typing = /input|textarea|select/i.test(document.activeElement?.tagName || '');
      if ((e.key === 'k' && (e.metaKey || e.ctrlKey)) || (e.key === '/' && !typing)) { e.preventDefault(); setOpen(true); }
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => { if (open) { setTimeout(() => inputRef.current?.focus(), 10); } else { setQ(''); setResults([]); } }, [open]);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) { setResults([]); setLoading(false); return undefined; }
    let alive = true;
    setLoading(true);
    const t = setTimeout(() => {
      getPlayers({ name: term, page_size: 8 })
        .then(r => { if (alive) { setResults(r.players || []); setActive(0); } })
        .catch(() => alive && setResults([]))
        .finally(() => alive && setLoading(false));
    }, 180);
    return () => { alive = false; clearTimeout(t); };
  }, [q]);

  const go = p => { setOpen(false); navigate(`/players/${p.id}`); };
  const onKeyDown = e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive(a => Math.min(results.length - 1, a + 1)); }
    if (e.key === 'ArrowUp') { e.preventDefault(); setActive(a => Math.max(0, a - 1)); }
    if (e.key === 'Enter' && results[active]) go(results[active]);
  };

  return (
    <>
      <button onClick={() => setOpen(true)} className="group hidden h-9 w-full max-w-[19rem] items-center gap-2 rounded-full border border-line bg-white/[0.04] px-3.5 text-[13px] text-slate-500 transition-[background-color,border-color,color] duration-150 hover:border-line-strong hover:bg-white/[0.07] hover:text-slate-300 md:flex" aria-label="Search players">
        <Icon name="search" size={14} />
        <span className="flex-1 truncate text-left">Search players…</span>
        <kbd className="kbd">⌘K</kbd>
      </button>
      <button onClick={() => setOpen(true)} className="btn btn-ghost btn-icon md:hidden" aria-label="Search players"><Icon name="search" size={17} /></button>
      {open && (
        <div className="fixed inset-0 z-modal flex items-start justify-center bg-black/40 px-4 pt-[12vh] backdrop-blur-[8px] animate-fade-in" onMouseDown={() => setOpen(false)}>
          <div role="dialog" aria-modal="true" aria-label="Search players" className="glass-pop w-full max-w-xl overflow-hidden rounded-[22px] animate-pop-in" onMouseDown={e => e.stopPropagation()}>
            <div className="flex items-center gap-3 border-b border-line px-5">
              <Icon name="search" size={16} className="text-slate-500" />
              <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)} onKeyDown={onKeyDown} placeholder="Search by player name…" aria-label="Player name"
                className="h-14 flex-1 !rounded-none !border-0 !bg-transparent px-0 text-[15px] !shadow-none" />
              {loading && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-accent border-t-transparent" aria-hidden="true" />}
              <kbd className="kbd">esc</kbd>
            </div>
            <ul className="max-h-[50vh] overflow-y-auto p-2" role="listbox">
              {q.trim().length < 2 && <li className="px-3 py-6 text-center text-xs text-slate-500">Type at least two characters.</li>}
              {q.trim().length >= 2 && !loading && results.length === 0 && <li className="px-3 py-6 text-center text-xs text-slate-500">No players match “{q.trim()}”.</li>}
              {results.map((p, i) => (
                <li key={p.id} role="option" aria-selected={i === active}>
                  <button onMouseEnter={() => setActive(i)} onClick={() => go(p)} className={`flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition-colors duration-100 ${i === active ? 'bg-accent/10' : ''}`}>
                    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-gradient-to-br from-slate-700 to-slate-800 text-2xs font-semibold text-slate-200">{(p.name || '?').split(' ').map(s => s[0]).join('').slice(0, 2)}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-slate-100">{p.full_name && p.full_name !== p.name ? p.full_name : p.name}</span>
                      <span className="block truncate text-2xs text-slate-500">{[p.primary_role, p.nationality && p.nationality !== 'Unknown' ? p.nationality : null, p.bowling_style].filter(Boolean).join(' · ') || 'Profile'}</span>
                    </span>
                    <Icon name="arrowRight" size={14} className={i === active ? 'text-accent' : 'text-transparent'} />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </>
  );
}
