/**
 * Shared presentation for hybrid data coverage: quality labels, stacked coverage
 * bars and metric values that carry their verification status. Labels and
 * statuses come from the backend; nothing is computed here beyond display.
 */
import { Badge } from './ui';

export const COVERAGE_ORDER = ['FULL_BALL_BY_BALL', 'PARTIAL_BALL_BY_BALL', 'SCORECARD_ONLY', 'METADATA_ONLY', 'UNKNOWN'];

export const COVERAGE_META = {
  FULL_BALL_BY_BALL: { label: 'FULL MATCH DATA', short: 'Ball-by-ball', variant: 'green', bar: 'bg-pos' },
  PARTIAL_BALL_BY_BALL: { label: 'PARTIAL MATCH DATA', short: 'Partial', variant: 'amber', bar: 'bg-warn' },
  SCORECARD_ONLY: { label: 'SCORECARD DATA', short: 'Scorecard only', variant: 'blue', bar: 'bg-electric' },
  METADATA_ONLY: { label: 'COVERAGE UNVERIFIED', short: 'Metadata only', variant: 'default', bar: 'bg-slate-500' },
  UNKNOWN: { label: 'COVERAGE UNVERIFIED', short: 'Unknown', variant: 'default', bar: 'bg-slate-600' },
};

export function CoverageBadge({ status, className = '' }) {
  const meta = COVERAGE_META[status] || COVERAGE_META.UNKNOWN;
  return <Badge variant={meta.variant} className={`tracking-wide ${className}`}>{meta.label}</Badge>;
}

/** Proportional stacked bar of coverage statuses; `counts` = {STATUS: n}. */
export function CoverageBar({ counts = {}, className = 'h-2' }) {
  const total = COVERAGE_ORDER.reduce((s, k) => s + (counts[k] || 0), 0);
  if (!total) return <div className={`rounded-full bg-white/[0.06] ${className}`} />;
  return (
    <div className={`flex overflow-hidden rounded-full bg-white/[0.06] ${className}`} role="img"
      aria-label={COVERAGE_ORDER.filter(k => counts[k]).map(k => `${COVERAGE_META[k].short}: ${counts[k]}`).join(', ')}>
      {COVERAGE_ORDER.filter(k => counts[k]).map(k => (
        <div key={k} className={`${COVERAGE_META[k].bar} h-full`} style={{ width: `${(100 * counts[k]) / total}%` }}
          title={`${COVERAGE_META[k].short}: ${counts[k].toLocaleString()}`} />
      ))}
    </div>
  );
}

export function CoverageLegend({ statuses = COVERAGE_ORDER.slice(0, 3) }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-slate-500">
      {statuses.map(k => <span key={k} className="inline-flex items-center gap-1.5"><span className={`h-2 w-2 rounded-full ${COVERAGE_META[k].bar}`} />{COVERAGE_META[k].short}</span>)}
    </div>
  );
}

const STATUS_TEXT = {
  verified: 'Verified from source records',
  derived: 'Derived from verified inputs',
  incomplete: 'Incomplete: some innings lack the fields this metric needs',
  unavailable: 'Unavailable: no record carries the fields this metric needs',
};

/** A metric value plus its status; incomplete values show their basis (n of m innings). */
export function StatusValue({ metric, digits }) {
  if (!metric) return <span className="text-slate-600">—</span>;
  const { value, status, basis } = metric;
  const shown = value === null || value === undefined ? '—'
    : typeof value === 'number' && digits !== undefined ? value.toFixed(digits)
    : typeof value === 'number' ? value.toLocaleString() : value;
  const tip = `${STATUS_TEXT[status] || status}${basis ? ` (${basis.innings} of ${basis.of} innings)` : ''}`;
  return (
    <span title={tip} className="inline-flex items-baseline gap-1">
      <span className={status === 'unavailable' ? 'text-slate-600' : status === 'incomplete' ? 'text-warn-soft' : ''}>{shown}</span>
      {status === 'incomplete' && basis && <span className="text-3xs text-slate-500">({basis.innings}/{basis.of})</span>}
    </span>
  );
}
