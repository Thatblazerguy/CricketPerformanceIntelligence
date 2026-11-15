/**
 * Small presentational helpers shared by the scouting workspace.
 * All numbers come from the backend scouting engine; nothing is computed here
 * beyond formatting.
 */
import { Badge } from '../../components/ui';

export const DASH = '—';
export const isNum = v => v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v));
export const fmt = (v, d = 1) => (isNum(v) ? Number(v).toFixed(d) : DASH);
export const fmtInt = v => (isNum(v) ? Math.round(Number(v)).toLocaleString() : DASH);
export const ordinal = v => {
  if (!isNum(v)) return DASH;
  const n = Math.min(99, Math.round(Number(v)));
  const s = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
  return `${n}${s}`;
};

export const METRIC_DECIMALS = { economy: 2, pp_economy: 2, mid_economy: 2, death_economy: 2 };
export const metricValue = (key, v) => {
  if (!isNum(v)) return DASH;
  const d = METRIC_DECIMALS[key] ?? 1;
  return `${Number(v).toFixed(d)}${key.endsWith('_pct') ? '%' : ''}`;
};

export function TierBadge({ tier, reliability }) {
  if (!tier) return null;
  const variant = tier === 'Established' ? 'green' : tier.startsWith('Promising') ? 'amber' : 'default';
  const short = tier === 'Established' ? 'Established' : tier.startsWith('Promising') ? 'Limited evidence' : 'Insufficient';
  return (
    <span title={`${tier}. Reliability ${fmt(reliability, 2)} = share of the estimate that comes from the player's own data.`}>
      <Badge variant={variant} className="num">{short}{isNum(reliability) ? ` · ${Number(reliability).toFixed(2)}` : ''}</Badge>
    </span>
  );
}

/** Horizontal 0–100 percentile bar with the median tick. */
export function PctBar({ value, className = '' }) {
  if (!isNum(value)) return <span className="text-2xs text-slate-600">no evidence</span>;
  const v = Math.max(0, Math.min(100, Number(value)));
  const color = v >= 75 ? 'bg-pos' : v <= 25 ? 'bg-neg' : 'bg-accent';
  return (
    <div className={`flex items-center gap-2 ${className}`} title={`${ordinal(v)} percentile`}>
      <div className="relative h-1.5 w-16 shrink-0 rounded-full bg-surface-hover">
        <div className="absolute inset-y-0 left-1/2 w-px bg-slate-600" />
        <div className={`absolute inset-y-0 left-0 rounded-full ${color}`} style={{ width: `${v}%` }} />
      </div>
      <span className="num w-7 text-right text-2xs text-slate-400">{Math.round(v)}</span>
    </div>
  );
}

export function ScoreCell({ score }) {
  if (!isNum(score)) return <span className="text-slate-600">{DASH}</span>;
  return (
    <div className="flex items-center gap-2">
      <span className="num w-9 text-right text-[13px] font-semibold text-white">{Number(score).toFixed(1)}</span>
      <div className="h-1.5 w-14 rounded-full bg-surface-hover"><div className="h-full rounded-full bg-accent" style={{ width: `${Math.max(0, Math.min(100, score))}%` }} /></div>
    </div>
  );
}

/** Compact two-column key/value table used inside report sections. */
export function KV({ rows }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
      {rows.filter(Boolean).map(([k, v]) => [
        <dt key={`${k}-k`} className="text-slate-500">{k}</dt>,
        <dd key={`${k}-v`} className="num text-right text-slate-200">{v}</dd>,
      ])}
    </dl>
  );
}

/** Simple dense table: columns [{key,label,align,render}] */
export function MiniTable({ columns, rows, empty = 'No data in this scope.', dense = true }) {
  if (!rows?.length) return <p className="py-3 text-xs text-slate-500">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-xs">
        <thead>
          <tr className="border-b border-line text-left text-2xs uppercase tracking-wide text-slate-500">
            {columns.map(c => <th key={c.key} className={`${dense ? 'px-2 py-1.5' : 'px-3 py-2'} font-medium ${c.align === 'right' ? 'text-right' : ''}`}>{c.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.key ?? i} className="border-b border-line-soft last:border-0 hover:bg-surface-hover/30">
              {columns.map(c => (
                <td key={c.key} className={`${dense ? 'px-2 py-1.5' : 'px-3 py-2'} ${c.align === 'right' ? 'num text-right' : ''} text-slate-300`}>
                  {c.render ? c.render(r) : (r[c.key] ?? DASH)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function downloadCsv(filename, rows) {
  const csv = rows.map(row => row.map(v => `"${String(v ?? '').replaceAll('"', '""')}"`).join(',')).join('\n');
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

export const storage = {
  get(key, fallback) {
    try { const v = window.localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch { return fallback; }
  },
  set(key, value) {
    try { window.localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
  },
};
