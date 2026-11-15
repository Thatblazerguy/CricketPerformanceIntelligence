/**
 * Shared building blocks for Team Analytics and Venue Analytics.
 * Every number comes from /api/v1/competition/*; nothing is computed here
 * beyond formatting and layout.
 */
import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { getCompetitionSeasons } from '../../services/api';
import { useUrlFilters } from '../../hooks/useFilters';
import { Badge, FilterBar, FilterField, Panel, SampleBadge, Select } from '../../components/ui';
import { PALETTE, StackedBar } from '../../components/charts';
import Icon from '../../components/icons';
import { matchUrl } from '../../components/MatchLink';
import { DASH, FORMATS, fmtDec, fmtInt, fmtPct } from '../../lib/format';

// Gender is always set: many team records (e.g. "India") hold both men's and women's matches, so mixing them is never meaningful.
export const SCOPE_DEFAULTS = { format: 'T20', gender: 'male', competition: '', season: '', start_year: '', end_year: '' };
export const SCOPE_KEYS = Object.keys(SCOPE_DEFAULTS);
const YEARS = Array.from({ length: new Date().getFullYear() - 2001 }, (_, i) => String(new Date().getFullYear() - i));
export const isNum = v => v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v));

/** URL-backed scope filters shared by both sections (format, gender, competition, season, years). */
export function useScope(extra = {}) {
  const defaults = useMemo(() => ({ ...SCOPE_DEFAULTS, ...extra }), []); // eslint-disable-line react-hooks/exhaustive-deps
  const [filters, setFilter, reset, active, setFilters] = useUrlFilters(defaults);
  const params = useMemo(() => Object.fromEntries(SCOPE_KEYS.map(k => [k, k === 'gender' ? (filters.gender === 'female' ? 'female' : 'male') : filters[k]]).filter(([, v]) => v)), [filters]);
  return { filters, setFilter, setFilters, reset, active, params, key: JSON.stringify(params) };
}

/** Query string that carries the current scope to another competition page. */
export function useScopeSearch(drop = []) {
  const { search } = useLocation();
  const p = new URLSearchParams(search);
  [...drop].forEach(k => p.delete(k));
  const s = p.toString();
  return s ? `?${s}` : '';
}

export function ScopeFilters({ scope, children, note }) {
  const { filters, setFilter, setFilters, reset, active } = scope;
  const [seasons, setSeasons] = useState([]);
  useEffect(() => {
    let live = true;
    getCompetitionSeasons({ format: filters.format, gender: filters.gender, competition: filters.competition })
      .then(r => live && setSeasons(r.seasons || [])).catch(() => live && setSeasons([]));
    return () => { live = false; };
  }, [filters.format, filters.gender, filters.competition]);
  return (
    <FilterBar onReset={reset} active={active} note={note}>
      <FilterField label="Format"><Select value={filters.format} onChange={v => setFilters({ format: v, season: '' })} options={FORMATS} /></FilterField>
      <FilterField label="Gender"><Select value={filters.gender || 'male'} onChange={v => setFilters({ gender: v, season: '' })} options={[{ id: 'male', label: 'Men' }, { id: 'female', label: 'Women' }]} /></FilterField>
      <FilterField label="Competition">
        <input key={filters.competition} type="search" defaultValue={filters.competition} placeholder="e.g. Premier League" aria-label="Competition"
          onBlur={e => e.target.value.trim() !== filters.competition && setFilters({ competition: e.target.value.trim(), season: '' })}
          onKeyDown={e => e.key === 'Enter' && setFilters({ competition: e.currentTarget.value.trim(), season: '' })} className="h-9 w-44 px-3 text-[13px]" />
      </FilterField>
      <FilterField label="Season"><Select value={filters.season} onChange={v => setFilter('season', v)} options={seasons} placeholder="All" /></FilterField>
      <FilterField label="From"><Select value={filters.start_year} onChange={v => setFilter('start_year', v)} options={YEARS} placeholder="Any" className="w-24" /></FilterField>
      <FilterField label="To"><Select value={filters.end_year} onChange={v => setFilter('end_year', v)} options={YEARS} placeholder="Any" className="w-24" /></FilterField>
      {children}
    </FilterBar>
  );
}

/** Searchable team/venue picker (native select + quick search). */
export function EntityPicker({ items, value, onChange, label, placeholder = 'Search…', allowEmpty, labelOf = x => x.name, className = 'min-w-[15rem] flex-1 basis-[18rem]' }) {
  const [q, setQ] = useState('');
  const current = items.find(t => t.id === value);
  const shown = useMemo(() => {
    const ql = q.toLowerCase();
    return items.filter(t => !ql || labelOf(t).toLowerCase().includes(ql)).slice(0, 80);
  }, [items, q, labelOf]);
  return (
    <FilterField label={label} className={className}>
      <div className="flex min-w-0 gap-1.5">
        <input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder={placeholder} aria-label={`${label} search`} className="h-9 w-24 shrink-0 px-3 text-[13px]" />
        <Select className="w-0 min-w-0 flex-1" value={value} onChange={onChange} placeholder={allowEmpty ? 'Any' : `Choose…`}
          options={[...(current && !shown.includes(current) ? [current] : []), ...shown].map(t => ({ id: t.id, label: labelOf(t) }))} />
      </div>
    </FilterField>
  );
}

/** Active-scope chips shown under profile headers. */
export function ScopeChips({ scope, extra }) {
  const s = scope || {};
  const chips = [s.format, s.gender && (s.gender === 'male' ? 'Men' : 'Women'), s.competition && `“${s.competition}”`, s.season && `Season ${s.season}`,
    (s.start_year || s.end_year) && `${s.start_year || '…'}–${s.end_year || '…'}`, extra].filter(Boolean);
  return <>{chips.map(c => <Badge key={c} variant="indigo">{c}</Badge>)}</>;
}

/* ------------------------------------------------------------- statistics UI */

/**
 * A proportion with its 95% interval on a 0–100 track, a 50% reference and the
 * sample size. `p` is the backend proportion object { value, k, n, ci95, sample }.
 */
export function CiBar({ label, p, color = 'var(--c1)', reference = 50, sub, compact }) {
  const has = p && isNum(p.value);
  return (
    <div className="min-w-0">
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="truncate text-xs text-slate-300">{label}</span>
        <span className="flex shrink-0 items-baseline gap-2">
          <span className={`num font-semibold text-slate-50 ${compact ? 'text-sm' : 'text-base'}`}>{has ? fmtPct(p.value) : DASH}</span>
          {p && <SampleBadge n={p.n} unit={p.unitLabel || 'matches'} />}
        </span>
      </div>
      <div className="relative h-2.5 rounded-full bg-slate-800/70" role="img" aria-label={has ? `${label}: ${p.value}% (95% CI ${p.ci95?.[0]}–${p.ci95?.[1]}%, n=${p.n})` : `${label}: no data`}>
        {isNum(reference) && <span className="absolute inset-y-[-3px] w-px bg-slate-400/60" style={{ left: `${reference}%` }} title={`${reference}% reference`} />}
        {has && p.ci95 && <span className="chart-hbar absolute inset-y-0 rounded-full opacity-35" style={{ left: `${p.ci95[0]}%`, width: `${Math.max(1, p.ci95[1] - p.ci95[0])}%`, backgroundColor: color }} />}
        {has && <span className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[var(--chart-bg)] transition-[left] duration-500" style={{ left: `${p.value}%`, backgroundColor: color }} />}
      </div>
      <div className="mt-1 flex justify-between text-3xs text-slate-500">
        <span>{has && p.ci95 ? `95% CI ${p.ci95[0]}–${p.ci95[1]}%` : 'No decided matches'}</span>
        <span>{sub}</span>
      </div>
    </div>
  );
}

/** Two values on mirrored bars (A left, B right); `better` = 'high' | 'low' | null. */
export function VersusRow({ label, a, b, format = v => v, better = 'high', aColor = 'var(--c1)', bColor = 'var(--c2)', sub }) {
  const va = isNum(a) ? Number(a) : null, vb = isNum(b) ? Number(b) : null;
  const max = Math.max(Math.abs(va ?? 0), Math.abs(vb ?? 0)) || 1;
  const win = va === null || vb === null || va === vb || !better ? null : (better === 'high' ? (va > vb ? 'a' : 'b') : (va < vb ? 'a' : 'b'));
  return (
    <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-x-3 py-1.5">
      <div className="flex items-center justify-end gap-2">
        <span className={`num text-[13px] ${win === 'a' ? 'font-semibold text-white' : 'text-slate-400'}`}>{va === null ? DASH : format(va)}</span>
        <div className="h-1.5 w-full max-w-[9rem] overflow-hidden rounded-full bg-slate-800/60"><div className="chart-hbar ml-auto h-full rounded-full" style={{ width: `${va === null ? 0 : Math.abs(va) / max * 100}%`, backgroundColor: aColor, opacity: win === 'b' ? 0.45 : 1 }} /></div>
      </div>
      <div className="w-32 text-center sm:w-40">
        <div className="truncate text-2xs font-medium text-slate-300">{label}</div>
        {sub && <div className="truncate text-3xs text-slate-500">{sub}</div>}
      </div>
      <div className="flex items-center gap-2">
        <div className="h-1.5 w-full max-w-[9rem] overflow-hidden rounded-full bg-slate-800/60"><div className="chart-hbar h-full rounded-full" style={{ width: `${vb === null ? 0 : Math.abs(vb) / max * 100}%`, backgroundColor: bColor, opacity: win === 'a' ? 0.45 : 1 }} /></div>
        <span className={`num text-[13px] ${win === 'b' ? 'font-semibold text-white' : 'text-slate-400'}`}>{vb === null ? DASH : format(vb)}</span>
      </div>
    </div>
  );
}

/** Value vs format baseline with a signed delta chip. lowerIsBetter flips the colour. */
export function BaselineDelta({ value, baseline, format = v => Number(v).toFixed(2), lowerIsBetter = false, neutral = false }) {
  if (!isNum(value)) return <span className="text-slate-600">{DASH}</span>;
  const d = isNum(baseline) ? Number(value) - Number(baseline) : null;
  const good = d === null || neutral ? null : (lowerIsBetter ? d < 0 : d > 0);
  return (
    <span className="inline-flex items-baseline gap-1.5">
      <span className="num text-slate-100">{format(value)}</span>
      {d !== null && Math.abs(d) >= 0.005 && <span className={`num text-3xs ${good === null ? 'text-slate-400' : good ? 'text-pos' : 'text-neg'}`}>{d > 0 ? '+' : ''}{format(d)}</span>}
    </span>
  );
}

const TONE = { pos: 'bg-pos', neg: 'bg-neg', neutral: 'bg-slate-400', bat: 'bg-pos', bowl: 'bg-electric' };

export function InsightList({ items, empty = 'No pattern clears the sample-size and effect-size thresholds for this selection.' }) {
  if (!items?.length) return <p className="text-sm text-slate-500">{empty}</p>;
  return (
    <ul className="space-y-2.5">
      {items.map((it, i) => (
        <li key={i} className="flex gap-2.5 text-[13px] leading-relaxed animate-fade-in" style={{ animationDelay: `${i * 40}ms` }}>
          <span className={`mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full ${TONE[it.tone] || TONE.neutral}`} />
          <span className="text-slate-300">{it.text}{it.significant && <Badge variant="green" className="ml-2 align-middle">significant</Badge>}</span>
        </li>
      ))}
    </ul>
  );
}

/** Explicit "not available" indicator — used instead of fabricating a value. */
export function Unavailable({ title, reason }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-dashed border-line-strong bg-surface-sunken/60 px-4 py-3">
      <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full border border-line-strong text-slate-500"><Icon name="info" size={12} /></span>
      <div className="min-w-0">
        <p className="text-[13px] font-medium text-slate-300">{title} <span className="ml-1 text-2xs font-normal text-slate-500">unavailable</span></p>
        <p className="mt-0.5 text-2xs leading-relaxed text-slate-500">{reason}</p>
      </div>
    </div>
  );
}

const RESULT_STYLE = { won: 'bg-pos/15 text-pos-soft', lost: 'bg-neg/15 text-neg-soft', tie: 'bg-warn/15 text-warn-soft', draw: 'bg-white/10 text-slate-300', no_result: 'bg-white/[0.06] text-slate-500', unknown: 'bg-white/[0.06] text-slate-500' };
const RESULT_LETTER = { won: 'W', lost: 'L', tie: 'T', draw: 'D', no_result: 'NR', unknown: '?' };

/**
 * Result chips. Pass `results` (strings) or `items` ({ result, match_id, label }) — with a
 * match_id each chip links to that match's details page.
 */
export function FormStrip({ results = [], items, size = 'md' }) {
  const sz = size === 'sm' ? 'h-4 min-w-4 text-[9px]' : 'h-5 min-w-5 text-3xs';
  const list = items || results.map(r => ({ result: r }));
  return (
    <span className="inline-flex gap-1" aria-label={`Recent results: ${list.map(r => RESULT_LETTER[r.result] || r.result).join(' ')}`}>
      {list.map((r, i) => {
        const cls = `grid place-items-center rounded px-1 font-semibold ${sz} ${RESULT_STYLE[r.result] || RESULT_STYLE.unknown}`;
        const letter = RESULT_LETTER[r.result] || '?';
        return r.match_id
          ? <Link key={i} to={matchUrl(r.match_id)} title={r.label || 'Open match details'} onClick={e => e.stopPropagation()} className={`${cls} transition-opacity hover:opacity-75 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60`}>{letter}</Link>
          : <span key={i} className={cls}>{letter}</span>;
      })}
    </span>
  );
}

export const resultLabel = r => ({ won: 'Won', lost: 'Lost', tie: 'Tied', draw: 'Drawn', no_result: 'No result' }[r] || r);

/** Record line, e.g. "120 M · 70 W · 45 L · 2 T · 3 NR". */
export function recordLine(r) {
  if (!r) return DASH;
  return [`${r.matches} M`, `${r.won} W`, `${r.lost} L`, r.tied && `${r.tied} T`, r.drawn && `${r.drawn} D`, r.no_result && `${r.no_result} NR`].filter(Boolean).join(' · ');
}

/** Hero card used at the top of profiles. */
export function ProfileHero({ eyebrow, title, subtitle, meta, aside, children }) {
  return (
    <section className="panel-hero mb-6 p-6 sm:p-7">
      <div className="relative flex flex-wrap items-start justify-between gap-5">
        <div className="min-w-0">
          {eyebrow && <div className="mb-2 text-[13px] font-semibold text-accent">{eyebrow}</div>}
          <h1 className="title-xl">{title}</h1>
          {subtitle && <p className="mt-1.5 text-[15px] text-slate-400">{subtitle}</p>}
          {meta && <div className="mt-3 flex flex-wrap items-center gap-2">{meta}</div>}
        </div>
        {aside && <div className="flex flex-wrap items-center gap-2">{aside}</div>}
      </div>
      {children && <div className="relative mt-5">{children}</div>}
    </section>
  );
}

export function BackLink({ to, children }) {
  return <Link to={to} className="mb-3 inline-flex items-center gap-1 text-xs text-slate-400 transition-colors hover:text-slate-200"><Icon name="chevronLeft" size={13} />{children}</Link>;
}

export function MethodNote({ items }) {
  if (!items?.length) return null;
  return <ul className="mt-6 list-disc space-y-1 pl-5 text-2xs leading-relaxed text-slate-500">{items.map(n => <li key={n}>{n}</li>)}</ul>;
}

/** Wrap a proportion object with a different unit label for SampleBadge. */
export const withUnit = (p, unitLabel) => (p ? { ...p, unitLabel } : p);

/** Pace vs spin bowling panel (team bowling or venue conditions). */
export function PaceSpin({ ps, title = 'Pace vs spin', subtitle }) {
  const s = Object.fromEntries(ps.styles.map(x => [x.style, x]));
  return (
    <Panel title={title} subtitle={subtitle || `Coverage: ${fmtPct(ps.coverage_percentage)} of legal balls bowled by classified bowlers. Δ = vs the same style across the format.`}>
      {!ps.total_balls ? <Unavailable title="Pace vs spin" reason="No ball-by-ball bowling records for this selection." /> : (
        <>
          <StackedBar rows={[{ label: 'Share of overs', segments: [{ name: 'Pace', value: s.pace?.balls, color: PALETTE[3] }, { name: 'Spin', value: s.spin?.balls, color: PALETTE[4] }, { name: 'Unclassified', value: ps.unclassified_balls, color: 'var(--chart-dim)' }] }]} percent formatter={v => `${fmtInt(v / 6)} ov`} className="!border-0 !p-0" />
          <table className="mt-3 w-full text-[13px]">
            <thead><tr className="text-left text-3xs text-slate-500"><th className="py-1.5 font-medium">Style</th><th className="text-right font-medium">Overs</th><th className="text-right font-medium">Wkts</th><th className="text-right font-medium">Econ (Δ)</th><th className="text-right font-medium">SR</th><th className="text-right font-medium">Avg</th><th className="text-right font-medium">Wkt share</th></tr></thead>
            <tbody>{['pace', 'spin'].map(k => s[k] && (
              <tr key={k} className="border-t border-line-soft">
                <td className="py-2 capitalize text-slate-200"><i className="mr-2 inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: k === 'pace' ? PALETTE[3] : PALETTE[4] }} />{k}</td>
                <td className="num text-right text-slate-300">{fmtInt(s[k].overs)}</td><td className="num text-right text-slate-300">{fmtInt(s[k].wickets)}</td>
                <td className="text-right"><BaselineDelta value={s[k].economy} baseline={s[k].baseline_economy} lowerIsBetter /></td>
                <td className="num text-right text-slate-300">{fmtDec(s[k].strike_rate, 1)}</td><td className="num text-right text-slate-300">{fmtDec(s[k].average)}</td>
                <td className="num text-right text-slate-300">{fmtPct(s[k].wicket_share)}</td>
              </tr>))}</tbody>
          </table>
          <p className="mt-3 text-2xs text-slate-500">{ps.note}</p>
        </>
      )}
    </Panel>
  );
}

