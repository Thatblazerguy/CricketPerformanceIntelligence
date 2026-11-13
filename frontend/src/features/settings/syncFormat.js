/**
 * Formatting helpers for Cricsheet sync status. Backend timestamps are UTC ISO strings ("...Z").
 */

export const PHASES = [
  { key: 'checking_source', label: 'Checking source' },
  { key: 'downloading', label: 'Downloading archive' },
  { key: 'extracting', label: 'Extracting files' },
  { key: 'validating', label: 'Validating matches' },
  { key: 'importing', label: 'Importing matches' },
  { key: 'refreshing_statistics', label: 'Refreshing statistics' },
  { key: 'completed', label: 'Completed' },
];

export const PHASE_LABEL = Object.fromEntries(PHASES.map(p => [p.key, p.label]).concat([['failed', 'Failed']]));

export const STATUS_LABEL = {
  running: 'Running',
  completed: 'Completed',
  no_changes: 'No changes',
  partial: 'Completed with errors',
  failed: 'Failed',
  interrupted: 'Interrupted',
};

export const STATUS_STYLE = {
  running: 'bg-sky-900/50 text-sky-300 border-sky-800',
  completed: 'bg-emerald-900/40 text-emerald-300 border-emerald-800',
  no_changes: 'bg-slate-800 text-slate-300 border-slate-700',
  partial: 'bg-amber-900/40 text-amber-300 border-amber-800',
  failed: 'bg-red-900/40 text-red-300 border-red-800',
  interrupted: 'bg-amber-900/40 text-amber-300 border-amber-800',
};

export function parseTs(ts) {
  return ts ? new Date(ts) : null;
}

export function formatDateTime(ts) {
  const d = parseTs(ts);
  return d ? d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '—';
}

/** A match date (YYYY-MM-DD) is a calendar date, not an instant: never shift it by timezone. */
export function formatMatchDate(isoDate) {
  if (!isoDate) return '—';
  const [y, m, d] = isoDate.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

export function relativeTime(ts, now = Date.now()) {
  const d = parseTs(ts);
  if (!d) return null;
  const diff = Math.round((d.getTime() - now) / 1000);
  const abs = Math.abs(diff);
  const units = [[86400, 'day'], [3600, 'hour'], [60, 'minute'], [1, 'second']];
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
  for (const [secs, unit] of units) {
    if (abs >= secs || unit === 'second') return rtf.format(Math.round(diff / secs), unit);
  }
  return null;
}

export function daysSince(isoDate, now = new Date()) {
  if (!isoDate) return null;
  const [y, m, d] = isoDate.split('-').map(Number);
  const then = new Date(y, m - 1, d);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((today - then) / 86400000);
}

export function formatDuration(seconds) {
  if (seconds == null) return '—';
  if (seconds < 1) return '<1s';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function formatBytes(n) {
  if (!n) return '0 MB';
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatInterval(hours) {
  if (hours < 1) return `${Math.round(hours * 60)} minutes`;
  if (hours === 1) return '1 hour';
  if (hours % 24 === 0) return hours === 24 ? '1 day' : `${hours / 24} days`;
  return `${hours} hours`;
}
