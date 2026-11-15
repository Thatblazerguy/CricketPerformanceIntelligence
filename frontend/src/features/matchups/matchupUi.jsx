/**
 * Shared building blocks for the Matchups page (player and team modes).
 * Every number is computed by /api/v1/matchups/*; this file only lays it out.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { getPlayers } from '../../services/api';
import { Badge, FilterField, SampleBadge } from '../../components/ui';
import Icon from '../../components/icons';
import { DASH, fmtPct } from '../../lib/format';

export const COLOR_A = 'var(--c1)';
export const COLOR_B = 'var(--c2)';

const TONE = { pos: 'bg-pos', neg: 'bg-neg', neutral: 'bg-slate-400' };

/**
 * Insight cards: the observation, its statistical basis and sample size.
 * `aName`/`bName` decide which side a positive/negative tone refers to.
 */
export function InsightCards({ items, limit, empty = 'No pattern clears the sample-size and effect-size thresholds for this selection.' }) {
  const list = limit ? (items || []).slice(0, limit) : items || [];
  if (!list.length) return <p className="text-sm text-slate-500">{empty}</p>;
  return (
    <ul className="grid gap-3 md:grid-cols-2">
      {list.map((it, i) => (
        <li key={`${it.kind}-${i}`} className="rounded-2xl border border-line bg-surface-raised/60 p-4 animate-fade-in" style={{ animationDelay: `${i * 40}ms` }}>
          <div className="flex items-start gap-2.5">
            <span className={`mt-[7px] h-2 w-2 shrink-0 rounded-full ${TONE[it.tone] || TONE.neutral}`} />
            <div className="min-w-0 flex-1">
              <p className="text-[13.5px] font-medium leading-relaxed text-slate-100">{it.text}</p>
              <p className="mt-1.5 text-2xs leading-relaxed text-slate-500"><span className="font-medium text-slate-400">Basis: </span>{it.basis}</p>
              <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                <SampleBadge n={it.n} unit={it.unit || 'matches'} />
                {it.significant === true && <Badge variant="green">significant</Badge>}
                {it.significant === false && <Badge>not significant</Badge>}
                <Badge variant="indigo">historical · not a prediction</Badge>
              </div>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Proportional win split between two sides with the undecided remainder. */
export function RivalryBar({ a = 0, b = 0, other = 0, aLabel, bLabel, colorA = COLOR_A, colorB = COLOR_B }) {
  const total = a + b + other;
  const w = v => `${total ? (v / total) * 100 : 0}%`;
  return (
    <div className="min-w-0">
      <div className="flex h-3 overflow-hidden rounded-full bg-[var(--chart-track)]" role="img"
        aria-label={`${aLabel} ${a} wins, ${bLabel} ${b} wins${other ? `, ${other} other results` : ''}`}>
        <span className="chart-hbar h-full" style={{ width: w(a), backgroundColor: colorA }} />
        {other > 0 && <span className="h-full bg-slate-500/40" style={{ width: w(other) }} />}
        <span className="chart-hbar h-full" style={{ width: w(b), backgroundColor: colorB }} />
      </div>
      <div className="mt-1.5 flex justify-between text-2xs text-slate-500">
        <span><span className="num font-semibold" style={{ color: colorA }}>{a}</span> {aLabel}</span>
        {other > 0 && <span className="num">{other} tied / NR / drawn</span>}
        <span>{bLabel} <span className="num font-semibold" style={{ color: colorB }}>{b}</span></span>
      </div>
    </div>
  );
}

/** Compact proportion row: label · value · sample. `p` is the backend { value, k, n } object. */
export function PropRow({ label, p, sub }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line-soft py-2 last:border-0">
      <div className="min-w-0"><div className="truncate text-[13px] text-slate-300">{label}</div>{sub && <div className="text-3xs text-slate-500">{sub}</div>}</div>
      <div className="flex shrink-0 items-baseline gap-2">
        <span className="num text-[15px] font-semibold text-slate-50">{p && p.value !== null && p.value !== undefined ? fmtPct(p.value) : DASH}</span>
        {p && <span className="num text-3xs text-slate-500">{p.k}/{p.n}</span>}
      </div>
    </div>
  );
}

/** Searchable player picker backed by GET /players. */
export function PlayerPicker({ label, value, onChange, placeholder = 'Search player…', accent = COLOR_A }) {
  const [q, setQ] = useState('');
  const [debounced, setDebounced] = useState('');
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [cursor, setCursor] = useState(0);
  const box = useRef(null);
  useEffect(() => { const h = setTimeout(() => setDebounced(q.trim()), 200); return () => clearTimeout(h); }, [q]);
  useEffect(() => {
    if (debounced.length < 2) { setResults([]); return undefined; }
    let live = true;
    setLoading(true);
    getPlayers({ name: debounced, page_size: 20 }).then(r => live && setResults(r.players || [])).catch(() => live && setResults([])).finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [debounced]);
  useEffect(() => {
    const close = e => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);
  const pick = p => { onChange({ id: p.id, name: p.name || p.canonical_name }); setQ(''); setOpen(false); };

  if (value?.id) {
    return (
      <FilterField label={label} className="min-w-[14rem] flex-1 basis-[16rem]">
        <div className="flex h-9 items-center justify-between gap-2 rounded-full border border-line bg-surface px-3">
          <span className="flex min-w-0 items-center gap-2"><span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: accent }} /><span className="truncate text-[13px] font-medium text-slate-100">{value.name || 'Selected player'}</span></span>
          <button type="button" onClick={() => { onChange(null); setOpen(true); }} className="btn btn-ghost btn-xs" aria-label={`Change ${label}`}>Change</button>
        </div>
      </FilterField>
    );
  }
  return (
    <div ref={box} className="relative min-w-[14rem] flex-1 basis-[16rem]">
      <FilterField label={label} className="w-full">
        <div className="relative">
          <Icon name="search" size={13} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input type="search" value={q} placeholder={placeholder} aria-label={label} aria-expanded={open} aria-autocomplete="list"
            onChange={e => { setQ(e.target.value); setOpen(true); setCursor(0); }} onFocus={() => setOpen(true)}
            onKeyDown={e => {
              if (e.key === 'ArrowDown') { e.preventDefault(); setCursor(c => Math.min(results.length - 1, c + 1)); }
              if (e.key === 'ArrowUp') { e.preventDefault(); setCursor(c => Math.max(0, c - 1)); }
              if (e.key === 'Enter' && results[cursor]) { e.preventDefault(); pick(results[cursor]); }
              if (e.key === 'Escape') setOpen(false);
            }}
            className="h-9 w-full pl-8 pr-3 text-[13px]" />
        </div>
      </FilterField>
      {open && q.trim().length >= 2 && (
        <div role="listbox" className="glass absolute left-0 right-0 top-full z-30 mt-1.5 max-h-72 overflow-y-auto rounded-2xl p-1.5 shadow-2xl">
          {loading && <p className="px-3 py-2 text-xs text-slate-500">Searching…</p>}
          {!loading && !results.length && <p className="px-3 py-2 text-xs text-slate-500">No players match “{q}”.</p>}
          {results.map((p, i) => (
            <button key={p.id} type="button" role="option" aria-selected={i === cursor} onMouseEnter={() => setCursor(i)} onClick={() => pick(p)}
              className={`flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left text-[13px] ${i === cursor ? 'bg-accent/[0.12] text-white' : 'text-slate-300'}`}>
              <span className="truncate">{p.name || p.canonical_name}</span>
              {p.nationality ? <span className="shrink-0 text-3xs text-slate-500">{p.nationality}</span> : null}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Pill date input (YYYY-MM-DD). */
export function DateField({ label, value, onChange }) {
  return (
    <FilterField label={label} className="min-w-[9rem]">
      <input type="date" value={value || ''} onChange={e => onChange(e.target.value)} className="h-9 px-3 text-[13px]" aria-label={label} />
    </FilterField>
  );
}

/** Small "n matches contributing" chip row under the filter bar. */
export function ContributionNote({ children }) {
  return <div className="-mt-3 mb-5 flex flex-wrap items-center gap-2 px-1 text-2xs text-slate-500">{children}</div>;
}

/** Sticky section tabs for long analytical pages. */
export function useSectionTabs(tabs, initial) {
  const [tab, setTab] = useState(initial || tabs[0].id);
  const valid = useMemo(() => tabs.some(t => t.id === tab), [tabs, tab]);
  return [valid ? tab : tabs[0].id, setTab];
}
