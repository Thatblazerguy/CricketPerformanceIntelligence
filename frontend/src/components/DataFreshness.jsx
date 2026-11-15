/**
 * Compact data-freshness indicator: latest match date in the database and the
 * last successful Cricsheet check, from /data-sync/status. Links to Settings.
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getDataSyncStatus } from '../services/api';
import { daysSince, formatDateTime, formatMatchDate, relativeTime } from '../features/settings/syncFormat';

export default function DataFreshness({ className = '', compact = false }) {
  const [status, setStatus] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () => getDataSyncStatus()
      .then(s => { if (alive) { setStatus(s); setFailed(false); } })
      .catch(() => alive && setFailed(true));
    load();
    const id = setInterval(load, 60000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  if (failed && !status) {
    return (
      <Link to="/settings" className={`inline-flex h-9 items-center gap-2 rounded-full border border-line px-3.5 text-2xs text-slate-500 ${className}`}>
        Data freshness unavailable
      </Link>
    );
  }
  if (!status) return null;

  const syncing = status.sync_running || status.current_sync;
  const stale = daysSince(status.data_updated_through) > 14;
  const problem = status.latest_sync && ['failed', 'partial', 'interrupted'].includes(status.latest_sync.status);
  const dot = syncing ? 'bg-electric animate-pulse' : problem ? 'bg-warn' : stale ? 'bg-slate-500' : 'bg-pos';

  if (compact) {
    return (
      <Link to="/settings" title={`Data through ${formatMatchDate(status.data_updated_through)} · last Cricsheet check ${formatDateTime(status.last_checked_at)}`}
        className={`h-9 shrink-0 items-center gap-2 rounded-full border border-line bg-white/[0.03] px-3.5 text-xs text-slate-400 transition-colors hover:border-line-strong hover:text-slate-200 ${className}`}>
        <span className={`relative h-1.5 w-1.5 rounded-full ${dot}`} />
        <span className="whitespace-nowrap">{syncing ? 'Syncing…' : <>Data to <span className="num font-medium text-slate-200">{formatMatchDate(status.data_updated_through)}</span></>}</span>
        {problem && !syncing && <span className="text-warn">· errors</span>}
      </Link>
    );
  }

  return (
    <Link
      to="/settings"
      title={`Last Cricsheet check: ${formatDateTime(status.last_checked_at)}`}
      className={`inline-flex flex-wrap items-center gap-x-3 gap-y-1 rounded-full border border-line bg-surface px-3.5 py-1.5 text-xs text-slate-400 transition-colors hover:border-line-strong ${className}`}
    >
      <span className="inline-flex items-center gap-1.5">
        <span className={`h-2 w-2 rounded-full ${dot}`} />
        Data through <span className="font-medium text-slate-200">{formatMatchDate(status.data_updated_through)}</span>
      </span>
      <span className="text-slate-600">·</span>
      <span>
        {syncing ? 'Syncing now…' : status.last_checked_at ? <>Checked {relativeTime(status.last_checked_at)}</> : 'Not checked yet'}
      </span>
      {problem && !syncing && <span className="text-warn">Last sync had errors</span>}
    </Link>
  );
}
