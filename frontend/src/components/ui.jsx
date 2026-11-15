/**
 * CPI shared UI primitives. Every page composes these so spacing, type scale,
 * surfaces and states stay consistent across the product.
 */
import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import CanonicalMatchLink, { matchRowProps } from './MatchLink';
import { DASH, sampleLevel } from '../lib/format';
import Icon from './icons';

/* ---------------------------------------------------------------- states */

export function LoadingSpinner({ message = 'Loading…', compact = false }) {
  return (
    <div className={`flex flex-col items-center justify-center text-slate-500 animate-fade-in ${compact ? 'py-6' : 'py-20'}`} role="status" aria-live="polite">
      <div className="relative mb-3 h-5 w-5">
        <div className="absolute inset-0 rounded-full border-[2.5px] border-white/[0.08]" />
        <div className="absolute inset-0 animate-spin rounded-full border-[2.5px] border-transparent border-t-accent" />
      </div>
      <span className="text-xs">{message}</span>
    </div>
  );
}

export function Skeleton({ className = 'h-4 w-full' }) {
  return <div className={`skeleton ${className}`} aria-hidden="true" />;
}

export function PanelSkeleton({ rows = 4, className = '' }) {
  return (
    <div className={`panel p-5 ${className}`} aria-busy="true" aria-label="Loading">
      <Skeleton className="mb-2.5 h-4 w-1/3" />
      <Skeleton className="mb-6 h-2.5 w-1/2" />
      <div className="space-y-3">{Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-3" />)}</div>
    </div>
  );
}

/** Route-level placeholder shaped like a typical analytics page. */
export function PageSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Loading view">
      <div className="space-y-3"><Skeleton className="h-3 w-24" /><Skeleton className="h-9 w-72 max-w-full rounded-xl" /><Skeleton className="h-3.5 w-[28rem] max-w-full" /></div>
      <Skeleton className="h-[84px] rounded-[20px]" />
      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]"><PanelSkeleton rows={6} /><PanelSkeleton rows={6} /></div>
    </div>
  );
}

export function DashboardSkeleton({ panels = 4 }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[84px] rounded-[18px]" />)}</div>
      <div className="grid gap-4 lg:grid-cols-2">{Array.from({ length: panels }, (_, i) => <PanelSkeleton key={i} rows={5} />)}</div>
    </div>
  );
}

export function ErrorState({ message, onRetry }) {
  return (
    <div className="panel flex flex-col items-center justify-center px-6 py-14 text-center" role="alert">
      <span className="mb-4 grid h-11 w-11 place-items-center rounded-2xl bg-neg/10 text-neg"><Icon name="alert" size={19} /></span>
      <span className="mb-1 text-[15px] font-semibold text-white">Couldn’t load this view</span>
      <p className="max-w-md text-[13px] leading-relaxed text-slate-400">{message}</p>
      {onRetry && <button onClick={onRetry} className="btn btn-secondary btn-sm mt-5"><Icon name="refresh" size={14} />Try again</button>}
    </div>
  );
}

export function EmptyState({ message = 'No data available for this selection.', hint, icon = 'filter', action }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <span className="mb-4 grid h-11 w-11 place-items-center rounded-2xl bg-white/[0.06] text-slate-400"><Icon name={icon} size={18} /></span>
      <p className="text-[14px] font-medium text-slate-200">{message}</p>
      {hint && <p className="mt-1.5 max-w-sm text-[13px] leading-relaxed text-slate-500">{hint}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/* ------------------------------------------------------------- structure */

export function PageHeader({ title, subtitle, eyebrow, actions, children, meta }) {
  return (
    <header className="mb-7 flex flex-wrap items-end justify-between gap-x-6 gap-y-4 pt-1">
      <div className="min-w-0 max-w-3xl">
        {eyebrow && <div className="mb-2 text-[13px] font-semibold tracking-[-0.005em] text-accent">{eyebrow}</div>}
        <h1 className="title-xl">{title}</h1>
        {subtitle && <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-slate-400 text-balance">{subtitle}</p>}
        {meta && <div className="mt-3 flex flex-wrap items-center gap-2">{meta}</div>}
        {children}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Panel({ title, subtitle, actions, footer, children, className = '', bodyClassName = 'p-5', id, eyebrow }) {
  return (
    <section id={id} className={`panel min-w-0 ${className}`}>
      {(title || actions) && (
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line-soft px-5 py-3.5">
          <div className="min-w-0">
            {eyebrow && <div className="eyebrow mb-0.5">{eyebrow}</div>}
            {title && <h3 className="text-[15px] font-semibold tracking-[-0.015em] text-white">{title}</h3>}
            {subtitle && <p className="mt-0.5 text-xs leading-relaxed text-slate-500">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
      {footer && <div className="border-t border-line-soft px-5 py-3 text-xs text-slate-500">{footer}</div>}
    </section>
  );
}

export function SectionHeader({ title, subtitle, actions, eyebrow }) {
  return (
    <div className="mb-3.5 mt-3 flex flex-wrap items-end justify-between gap-2">
      <div>
        {eyebrow && <div className="eyebrow mb-1">{eyebrow}</div>}
        <h2 className="text-[19px] font-semibold tracking-[-0.022em] text-white">{title}</h2>
        {subtitle && <p className="mt-0.5 text-[13px] text-slate-500">{subtitle}</p>}
      </div>
      {actions}
    </div>
  );
}

/** Expandable analytical section (native <details> so it stays accessible). */
export function Collapsible({ title, subtitle, children, defaultOpen = false, className = '', badge }) {
  return (
    <details open={defaultOpen} className={`panel group min-w-0 ${className}`}>
      <summary className="flex items-center justify-between gap-3 rounded-[20px] px-5 py-4 transition-colors hover:bg-white/[0.025]">
        <div className="min-w-0">
          <div className="flex items-center gap-2"><h3 className="text-[15px] font-semibold tracking-[-0.015em] text-white">{title}</h3>{badge}</div>
          {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
        </div>
        <span className="grid h-7 w-7 place-items-center rounded-full bg-white/[0.06] text-slate-400 transition-transform duration-250 ease-out group-open:rotate-180"><Icon name="chevronDown" size={14} /></span>
      </summary>
      <div className="border-t border-line-soft p-5 animate-fade-in">{children}</div>
    </details>
  );
}

export function StatCard({ label, value, sub, highlight = false, tone, title, icon }) {
  const toneClass = tone === 'pos' ? 'text-pos' : tone === 'neg' ? 'text-neg' : tone === 'warn' ? 'text-warn' : highlight ? 'text-white' : 'text-slate-50';
  return (
    <div title={title} className={`relative min-w-0 overflow-hidden rounded-[18px] border px-4 py-3.5 shadow-card ${highlight ? 'border-accent/25 bg-surface bg-[radial-gradient(120%_140%_at_0%_0%,rgb(var(--accent)/0.12),transparent_60%)]' : 'border-line bg-surface'}`}>
      <div className="mb-2 flex items-center gap-1.5">
        {icon && <Icon name={icon} size={13} className="text-slate-500" />}
        <p className="truncate text-xs font-medium text-slate-500">{label}</p>
      </div>
      <p className={`display-num text-[1.625rem] leading-none ${toneClass}`}>{value ?? <span className="text-base text-slate-600">{DASH}</span>}</p>
      {sub && <p className="mt-2 truncate text-2xs text-slate-500">{sub}</p>}
    </div>
  );
}

export function KpiGrid({ items, cols = 'grid-cols-2 sm:grid-cols-3 lg:grid-cols-6' }) {
  return <div className={`grid gap-3 ${cols}`}>{items.filter(Boolean).map(item => <StatCard key={item.label} {...item} />)}</div>;
}

/** Compact inline metric used inside headers and dense strips. */
export function Metric({ label, value, sub, tone, align = 'left', size = 'md' }) {
  const toneClass = tone === 'pos' ? 'text-pos' : tone === 'neg' ? 'text-neg' : tone === 'warn' ? 'text-warn' : tone === 'accent' ? 'text-accent-soft' : 'text-white';
  const sz = size === 'lg' ? 'text-[28px]' : size === 'sm' ? 'text-[15px]' : 'text-[22px]';
  return (
    <div className={`min-w-0 ${align === 'right' ? 'text-right' : ''}`}>
      <div className="mb-1.5 truncate text-xs font-medium text-slate-500">{label}</div>
      <div className={`display-num leading-none ${sz} ${toneClass}`}>{value ?? <span className="text-slate-600">{DASH}</span>}</div>
      {sub && <div className="mt-1 truncate text-2xs text-slate-500">{sub}</div>}
    </div>
  );
}

/** Horizontal strip of metrics separated by hairlines (denser than cards). */
export function MetricStrip({ items, className = '' }) {
  const list = items.filter(Boolean);
  return (
    <div className={`panel grid grid-cols-2 divide-line-soft overflow-hidden sm:grid-cols-3 sm:divide-x lg:flex lg:divide-x ${className}`}>
      {list.map((m, i) => <div key={m.label || i} className="min-w-0 border-line-soft px-5 py-4 max-sm:border-b max-sm:odd:border-r lg:flex-1"><Metric {...m} /></div>)}
    </div>
  );
}

/** Thin proportional meter (0–max). */
export function Meter({ value, max = 100, color = 'bg-accent', className = '' }) {
  const pct = Number.isFinite(Number(value)) ? Math.max(0, Math.min(100, (Number(value) / (max || 1)) * 100)) : 0;
  return <div className={`h-1.5 overflow-hidden rounded-full bg-white/[0.07] ${className}`}><div className={`chart-hbar h-full rounded-full ${color}`} style={{ width: `${pct}%` }} /></div>;
}

export function SampleNote({ note }) {
  if (!note) return null;
  return <p className="mt-3 text-2xs leading-relaxed text-slate-500">{note}</p>;
}

export function SampleWarning({ warning }) {
  if (!warning) return null;
  return <div className="mt-3 flex items-start gap-2 rounded-2xl bg-warn/10 px-3.5 py-2.5 text-xs text-warn-soft"><Icon name="alert" size={14} className="mt-px" />{warning}</div>;
}

export function Callout({ tone = 'info', children }) {
  const cls = tone === 'warn' ? 'border-warn/20 bg-warn/10 text-warn-soft' : 'border-line-soft bg-white/[0.035] text-slate-300';
  return <div className={`flex items-start gap-2.5 rounded-2xl border px-3.5 py-2.5 text-xs leading-relaxed ${cls}`}><Icon name={tone === 'warn' ? 'alert' : 'info'} size={14} className="mt-px opacity-80" /><div className="min-w-0">{children}</div></div>;
}

/** Inline sample-size chip; amber below `low`, muted otherwise. */
export function SampleBadge({ n, unit = 'matches', low = 10, ok = 30 }) {
  const level = sampleLevel(n, { low, ok });
  if (!level) return null;
  const cls = level === 'low' ? 'border-warn/30 bg-warn/10 text-warn-soft' : level === 'limited' ? 'border-line-strong text-slate-300' : 'border-line text-slate-500';
  return <span title={level === 'low' ? 'Small sample — interpret with caution' : undefined} className={`num inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-3xs font-medium ${cls}`}>{level === 'low' && <span className="dot bg-warn" />}n={Number(n).toLocaleString()} {unit}</span>;
}

export function Badge({ children, variant = 'default', className = '' }) {
  const styles = {
    default: 'bg-white/[0.06] text-slate-300',
    indigo: 'bg-accent/[0.12] text-accent-soft',
    blue: 'bg-electric/[0.12] text-electric-soft',
    green: 'bg-pos/[0.12] text-pos-soft',
    red: 'bg-neg/[0.12] text-neg-soft',
    amber: 'bg-warn/[0.12] text-warn-soft',
    gold: 'bg-gold/[0.14] text-gold-soft',
  };
  return <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-2xs font-medium ${styles[variant] || styles.default} ${className}`}>{children}</span>;
}

export function Avatar({ name, size = 'md', className = '' }) {
  const initials = (name || '?').split(/\s+/).filter(Boolean).map(s => s[0]).join('').slice(0, 2).toUpperCase();
  const sz = size === 'lg' ? 'h-[72px] w-[72px] text-[22px]' : size === 'sm' ? 'h-7 w-7 text-2xs' : 'h-10 w-10 text-sm';
  return <span className={`grid shrink-0 place-items-center rounded-full bg-gradient-to-br from-slate-600 to-slate-800 font-semibold tracking-tight text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.15)] ${sz} ${className}`} aria-hidden="true">{initials}</span>;
}

/* -------------------------------------------------------------- controls */

export function Button({ variant = 'secondary', size, icon, iconRight, children, className = '', as: As = 'button', ...rest }) {
  const sz = size === 'sm' ? 'btn-sm' : size === 'xs' ? 'btn-xs' : size === 'lg' ? 'btn-lg' : '';
  // Literal class names so Tailwind keeps every variant in the build.
  const v = { primary: 'btn-primary', secondary: 'btn-secondary', tertiary: 'btn-tertiary', ghost: 'btn-ghost', danger: 'btn-danger', float: 'btn-float', icon: 'btn-ghost btn-icon' }[variant] || 'btn-secondary';
  return (
    <As className={`btn ${v} ${sz} ${className}`} {...rest}>
      {icon && <Icon name={icon} size={size === 'xs' ? 13 : 15} />}
      {children}
      {iconRight && <Icon name={iconRight} size={size === 'xs' ? 13 : 15} />}
    </As>
  );
}

/** Measures the selected child so a thumb can slide beneath it. */
function useThumb(deps, selector) {
  const ref = useRef(null);
  const [thumb, setThumb] = useState(null);
  useLayoutEffect(() => {
    const list = ref.current;
    if (!list) return undefined;
    const update = () => {
      const el = list.querySelector(selector);
      setThumb(el ? { left: el.offsetLeft, width: el.offsetWidth } : null);
    };
    update();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(update);
    ro.observe(list);
    return () => ro.disconnect();
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
  return [ref, thumb];
}

const Thumb = ({ thumb }) => thumb ? <span aria-hidden="true" className="segment-thumb" style={{ left: 0, width: thumb.width, transform: `translateX(${thumb.left}px)` }} /> : null;

/**
 * Section tabs as an iOS-style segmented capsule with a spring-animated thumb.
 * Scrolls horizontally when there are more tabs than room.
 */
export function Tabs({ tabs, value, onChange, className = '' }) {
  const [ref, thumb] = useThumb([value, tabs], '[aria-selected="true"]');
  useEffect(() => { ref.current?.querySelector('[aria-selected="true"]')?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' }); }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className={`scrollbar-none max-w-full overflow-x-auto ${className}`}>
      <div ref={ref} role="tablist" className="segmented">
        <Thumb thumb={thumb} />
        {tabs.map(t => {
          const id = typeof t === 'string' ? t : t.id;
          const label = typeof t === 'string' ? t : t.label;
          const active = value === id;
          return (
            <button key={id} role="tab" aria-selected={active} onClick={() => onChange(id)} className="segment h-8 shrink-0 px-4 text-[13px]">
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Compact segmented control for chart/metric switching. */
export function Segmented({ options, value, onChange, size = 'sm', label }) {
  const [ref, thumb] = useThumb([value, options], '[aria-checked="true"]');
  return (
    <div className="scrollbar-none inline-flex max-w-full overflow-x-auto">
      <div ref={ref} role="radiogroup" aria-label={label} className="segmented">
        <Thumb thumb={thumb} />
        {options.map(o => {
          const id = typeof o === 'string' ? o : o.id;
          const text = typeof o === 'string' ? o : o.label;
          const active = value === id;
          return (
            <button key={id} type="button" role="radio" aria-checked={active} onClick={() => onChange(id)}
              className={`segment shrink-0 ${size === 'xs' ? 'h-6 px-2.5 text-2xs' : 'h-7 px-3 text-xs'}`}>
              {text}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function FilterField({ label, children, className = '' }) {
  return (
    <label className={`flex min-w-[8.5rem] flex-col gap-1.5 ${className}`}>
      <span className="pl-1 text-2xs font-medium text-slate-500">{label}</span>
      {children}
    </label>
  );
}

export function Select({ value, onChange, options, placeholder, className = '', ...rest }) {
  return (
    <select value={value ?? ''} onChange={e => onChange(e.target.value)} className={`h-9 text-[13px] ${className}`} {...rest}>
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map(o => {
        const id = typeof o === 'object' ? o.id ?? o.value : o;
        const label = typeof o === 'object' ? o.label ?? o.name : o;
        return <option key={id} value={id}>{label}</option>;
      })}
    </select>
  );
}

export function FilterBar({ children, onReset, active = 0, note }) {
  return (
    <div className="glass mb-6 rounded-[24px] px-4 py-3.5 sm:px-5">
      <div className="flex flex-wrap items-end gap-3">
        {children}
        {onReset && (
          <button onClick={onReset} disabled={!active} className="btn btn-ghost btn-sm ml-auto h-9">
            <Icon name="refresh" size={13} />Reset{active ? <span className="num grid h-[18px] min-w-[18px] place-items-center rounded-full bg-accent px-1 text-3xs font-semibold text-on-accent">{active}</span> : ''}
          </button>
        )}
      </div>
      {note && <p className="mt-2.5 pl-1 text-2xs leading-relaxed text-slate-500">{note}</p>}
    </div>
  );
}

/* --------------------------------------------------------------- links */

export function PlayerLink({ id, name, className = '' }) {
  if (!id) return <span className={className}>{name || DASH}</span>;
  return <Link to={`/players/${id}`} className={`text-slate-100 decoration-accent/50 underline-offset-2 transition-colors hover:text-accent-soft hover:underline ${className}`}>{name || 'Unknown player'}</Link>;
}

/** Inline link to a match's details page (delegates to the canonical components/MatchLink). */
export function MatchLink({ id, children, tab, context, className = '', title }) {
  return <CanonicalMatchLink id={id} tab={tab} context={context} className={className} title={title}>{children}</CanonicalMatchLink>;
}

/* --------------------------------------------------------------- tables */

const TH = 'whitespace-nowrap border-b border-line text-2xs font-semibold tracking-[-0.003em]';

/** Legacy simple table kept for existing callers. */
export function Table({ headers, rows, emptyMessage = 'No data.', alignRight = [] }) {
  if (!rows || rows.length === 0) return <div className="panel"><EmptyState message={emptyMessage} /></div>;
  return (
    <div className="overflow-x-auto rounded-[20px] border border-line bg-surface shadow-card">
      <table className="w-full text-[13px]">
        <thead className="bg-surface-raised/60"><tr>{headers.map((h, i) => <th key={i} className={`${TH} px-4 py-2.5 text-slate-500 ${alignRight.includes(i) ? 'text-right' : 'text-left'}`}>{h}</th>)}</tr></thead>
        <tbody>{rows.map((row, i) => <tr key={i} className="row-link border-b border-line-soft last:border-0">{row.map((cell, j) => <td key={j} className={`px-4 py-2.5 text-slate-300 ${alignRight.includes(j) ? 'num text-right' : ''}`}>{cell}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

const sortVal = (col, row) => {
  const v = col.sortValue ? col.sortValue(row) : row[col.key];
  if (v === null || v === undefined || v === '' || (typeof v === 'number' && !Number.isFinite(v))) return null;
  return v;
};

function SortIcon({ dir }) {
  return (
    <svg width="8" height="10" viewBox="0 0 8 10" aria-hidden="true" className="shrink-0">
      <path d="M4 0.5 7 4H1z" fill={dir === 'asc' ? 'rgb(var(--accent))' : 'var(--chart-dim)'} />
      <path d="M4 9.5 1 6h6z" fill={dir === 'desc' ? 'rgb(var(--accent))' : 'var(--chart-dim)'} />
    </svg>
  );
}

/**
 * Data table with sorting, search, pagination, sticky header, numeric alignment
 * and optional expandable rows. Missing values always sort last.
 *
 * columns: [{ key, label, align, render(row), sortValue(row), title, sortable=true, className }]
 */
export function DataTable({
  columns, rows = [], rowKey = (r, i) => r.id ?? i, searchKeys, searchPlaceholder = 'Search…',
  pageSize = 25, initialSort, stickyHeader = true, maxHeight, renderExpanded, emptyMessage = 'No rows for this selection.',
  dense = false, caption, toolbar, rowClassName, onRowClick, stickyFirst = false, rowHref, rowLabel,
}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState(initialSort || null);
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState(() => new Set());
  useEffect(() => setPage(0), [query, rows]);

  const filtered = useMemo(() => {
    if (!query || !searchKeys?.length) return rows;
    const q = query.toLowerCase();
    return rows.filter(r => searchKeys.some(k => String(typeof k === 'function' ? k(r) : r[k] ?? '').toLowerCase().includes(q)));
  }, [rows, query, searchKeys]);

  const sorted = useMemo(() => {
    if (!sort) return filtered;
    const col = columns.find(c => c.key === sort.key);
    if (!col) return filtered;
    const dir = sort.dir === 'asc' ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const va = sortVal(col, a), vb = sortVal(col, b);
      if (va === null && vb === null) return 0;
      if (va === null) return 1;
      if (vb === null) return -1;
      if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir;
      return String(va).localeCompare(String(vb), undefined, { numeric: true }) * dir;
    });
  }, [filtered, sort, columns]);

  const pages = pageSize ? Math.max(1, Math.ceil(sorted.length / pageSize)) : 1;
  const visible = pageSize ? sorted.slice(page * pageSize, page * pageSize + pageSize) : sorted;
  const pad = dense ? 'px-3 py-1.5' : 'px-3.5 py-2.5';
  const toggleSort = col => {
    if (col.sortable === false) return;
    setSort(s => (s?.key === col.key ? { key: col.key, dir: s.dir === 'desc' ? 'asc' : 'desc' } : { key: col.key, dir: col.align === 'right' ? 'desc' : 'asc' }));
  };
  const stickyCls = i => (stickyFirst && i === 0 ? 'sticky left-0 z-[1] bg-inherit' : '');

  return (
    <div className="min-w-0">
      {(searchKeys?.length || toolbar || caption) && (
        <div className="flex flex-wrap items-center justify-between gap-2 px-0.5 pb-2.5">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            {searchKeys?.length > 0 && (
              <div className="relative">
                <Icon name="search" size={13} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                <input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder={searchPlaceholder} aria-label={searchPlaceholder} className="h-8 w-60 max-w-full pl-8 pr-3 text-xs" />
              </div>
            )}
            {toolbar}
          </div>
          <span className="num text-2xs text-slate-500">{caption ? `${caption} · ` : ''}{sorted.length.toLocaleString()} row{sorted.length === 1 ? '' : 's'}</span>
        </div>
      )}
      <div className="overflow-auto rounded-2xl border border-line bg-surface" style={maxHeight ? { maxHeight } : undefined}>
        <table className="w-full text-[13px]">
          <thead className={`bg-surface-raised ${stickyHeader ? 'sticky top-0 z-[2] shadow-[0_1px_0_rgb(var(--line))]' : ''}`}>
            <tr>
              {renderExpanded && <th className={`${TH} w-8`} />}
              {columns.map((col, ci) => {
                const active = sort?.key === col.key;
                return (
                  <th key={col.key} scope="col" title={col.title}
                    aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined}
                    className={`${TH} ${pad} ${col.align === 'right' ? 'text-right' : 'text-left'} ${active ? 'text-accent-soft' : 'text-slate-500'} ${stickyCls(ci)} ${col.headerClassName || ''}`}>
                    {col.sortable === false ? col.label : (
                      <button onClick={() => toggleSort(col)} className={`inline-flex items-center gap-1.5 rounded-md transition-colors hover:text-slate-100 ${col.align === 'right' ? 'flex-row-reverse' : ''}`}>
                        {col.label}<SortIcon dir={active ? sort.dir : null} />
                      </button>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 && <tr><td colSpan={columns.length + (renderExpanded ? 1 : 0)} className="px-3 py-10 text-center text-xs text-slate-500">{emptyMessage}</td></tr>}
            {visible.map((row, i) => {
              const key = rowKey(row, i);
              const isOpen = open.has(key);
              const href = rowHref ? rowHref(row) : null;
              const nav = href ? matchRowProps(href, navigate, rowLabel ? rowLabel(row) : undefined) : {};
              return (
                <Fragment key={key}>
                  <tr {...nav} onClick={nav.onClick || (onRowClick ? () => onRowClick(row) : undefined)}
                    className={`group border-b border-line-soft ${stickyFirst ? 'bg-surface' : ''} transition-colors duration-150 last:border-0 hover:bg-surface-hover ${onRowClick ? 'cursor-pointer' : ''} ${nav.className || ''} ${isOpen ? 'bg-accent/[0.06]' : ''} ${rowClassName ? rowClassName(row) : ''}`}>
                    {renderExpanded && (
                      <td className={`${pad} text-slate-500`}>
                        <button aria-label={isOpen ? 'Collapse row' : 'Expand row'} aria-expanded={isOpen} onClick={e => { e.stopPropagation(); setOpen(s => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n; }); }}
                          className="grid h-6 w-6 place-items-center rounded-full transition-colors hover:bg-white/[0.08] hover:text-slate-200">
                          <Icon name="chevronRight" size={13} className={`transition-transform duration-150 ${isOpen ? 'rotate-90' : ''}`} />
                        </button>
                      </td>
                    )}
                    {columns.map((col, ci) => (
                      <td key={col.key} className={`${pad} ${col.align === 'right' ? 'num text-right' : 'text-left'} whitespace-nowrap ${sort?.key === col.key ? 'font-medium text-white' : 'text-slate-300'} ${stickyCls(ci)} ${col.className ? (typeof col.className === 'function' ? col.className(row) : col.className) : ''}`}>
                        {col.render ? col.render(row) : (row[col.key] ?? <span className="text-slate-600">{DASH}</span>)}
                      </td>
                    ))}
                  </tr>
                  {renderExpanded && isOpen && <tr className="border-b border-line-soft bg-surface-sunken"><td /><td colSpan={columns.length} className="px-3 py-3 animate-fade-in">{renderExpanded(row)}</td></tr>}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {pageSize > 0 && pages > 1 && (
        <div className="flex flex-wrap items-center justify-between gap-2 px-0.5 pt-2.5 text-2xs text-slate-500">
          <span className="num">{(page * pageSize + 1).toLocaleString()}–{Math.min(sorted.length, (page + 1) * pageSize).toLocaleString()} of {sorted.length.toLocaleString()}</span>
          <div className="flex items-center gap-1">
            <button disabled={page === 0} onClick={() => setPage(0)} className="btn btn-ghost btn-xs" aria-label="First page">First</button>
            <button disabled={page === 0} onClick={() => setPage(p => p - 1)} className="btn btn-secondary btn-xs w-7 px-0" aria-label="Previous page"><Icon name="chevronLeft" size={13} /></button>
            <span className="num px-2 text-slate-400">{page + 1} / {pages}</span>
            <button disabled={page >= pages - 1} onClick={() => setPage(p => p + 1)} className="btn btn-secondary btn-xs w-7 px-0" aria-label="Next page"><Icon name="chevronRight" size={13} /></button>
            <button disabled={page >= pages - 1} onClick={() => setPage(pages - 1)} className="btn btn-ghost btn-xs" aria-label="Last page">Last</button>
          </div>
        </div>
      )}
    </div>
  );
}
