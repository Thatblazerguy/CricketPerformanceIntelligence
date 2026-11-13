/**
 * Settings -> Data Management: Cricsheet synchronisation status and controls.
 * Every value shown comes from /api/v1/data-sync/*; nothing is computed or assumed here.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getDataSyncHistory,
  getDataSyncStatus,
  triggerDataSync,
  updateDataSyncSettings,
} from '../../services/api';
import { ErrorState, LoadingSpinner, StatCard } from '../../components/ui';
import {
  PHASES,
  PHASE_LABEL,
  STATUS_LABEL,
  STATUS_STYLE,
  formatBytes,
  formatDateTime,
  formatDuration,
  formatInterval,
  formatMatchDate,
  relativeTime,
} from './syncFormat';

const INTERVAL_OPTIONS = [1, 3, 6, 12, 24, 48, 168];
const ACTIVE_POLL_MS = 2000;
const IDLE_POLL_MS = 30000;

function StatusPill({ status }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[status] || STATUS_STYLE.no_changes}`}>
      {status === 'running' && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-sky-300" />}
      {STATUS_LABEL[status] || status}
    </span>
  );
}

function Panel({ title, subtitle, action, children }) {
  return (
    <section className="mb-6 rounded-lg border border-slate-800 bg-slate-900/60">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-800 px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold text-slate-200">{title}</h2>
          {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
        </div>
        {action}
      </header>
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}

function TimeValue({ ts, empty = 'Never' }) {
  if (!ts) return <span className="text-slate-500">{empty}</span>;
  return <span title={formatDateTime(ts)}>{relativeTime(ts)}</span>;
}

function Toggle({ checked, onChange, disabled, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${checked ? 'bg-indigo-500' : 'bg-slate-700'}`}
    >
      <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${checked ? 'translate-x-6' : 'translate-x-1'}`} />
    </button>
  );
}

function PhaseTracker({ run }) {
  const source = run.sources.find(s => s.status === 'running') || run.sources[run.sources.length - 1];
  const failed = source.phase === 'failed';
  const currentIdx = PHASES.findIndex(p => p.key === source.phase);
  const pct = source.progress_total > 0 ? Math.min(100, Math.round((source.progress_current / source.progress_total) * 100)) : null;
  const progressText = source.phase === 'downloading'
    ? `${formatBytes(source.progress_current)}${source.progress_total ? ` of ${formatBytes(source.progress_total)}` : ''}`
    : source.progress_total ? `${source.progress_current.toLocaleString()} of ${source.progress_total.toLocaleString()}` : null;

  return (
    <div>
      <p className="mb-3 text-xs text-slate-400">
        Source <span className="font-mono text-slate-300">{source.source_key}</span>
        {run.sources.length > 1 && ` · ${run.sources.filter(s => s.status !== 'running').length} of ${run.sources.length} sources finished`}
      </p>
      <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
        {PHASES.map((p, idx) => {
          const done = !failed && currentIdx > idx;
          const active = !failed && currentIdx === idx;
          return (
            <li key={p.key} className={`rounded-md border px-2.5 py-2 text-xs ${
              active ? 'border-sky-700 bg-sky-950/50 text-sky-200'
                : done ? 'border-emerald-900 bg-emerald-950/30 text-emerald-300'
                  : 'border-slate-800 text-slate-500'}`}>
              <span className="mr-1">{done ? '✓' : active ? '●' : '○'}</span>{p.label}
            </li>
          );
        })}
      </ol>
      {failed && <p className="mt-3 text-sm text-red-300">Failed: {source.error_detail}</p>}
      {!failed && pct !== null && (
        <div className="mt-4">
          <div className="h-1.5 overflow-hidden rounded bg-slate-800">
            <div className="h-full bg-sky-500 transition-all" style={{ width: `${pct}%` }} />
          </div>
          <p className="mt-1.5 text-xs text-slate-500">{PHASE_LABEL[source.phase]} · {progressText}</p>
        </div>
      )}
    </div>
  );
}

function HistoryTable({ items }) {
  const [open, setOpen] = useState(null);
  if (!items.length) {
    return <p className="text-sm text-slate-500">No synchronisation has run yet.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-800 text-left text-xs uppercase tracking-wider text-slate-500">
            <th className="py-2 pr-4 font-medium">Started</th>
            <th className="py-2 pr-4 font-medium">Source</th>
            <th className="py-2 pr-4 font-medium">Trigger</th>
            <th className="py-2 pr-4 font-medium">Result</th>
            <th className="py-2 pr-4 text-right font-medium">New</th>
            <th className="py-2 pr-4 text-right font-medium">Updated</th>
            <th className="py-2 pr-4 text-right font-medium">Unchanged</th>
            <th className="py-2 pr-4 text-right font-medium">Failed</th>
            <th className="py-2 text-right font-medium">Duration</th>
          </tr>
        </thead>
        <tbody>
          {items.map(h => {
            const hasDetail = h.error_detail || (h.failed_files && h.failed_files.length) || h.stats_refresh;
            return [
              <tr
                key={h.id}
                onClick={() => hasDetail && setOpen(open === h.id ? null : h.id)}
                className={`border-b border-slate-800/60 ${hasDetail ? 'cursor-pointer hover:bg-slate-800/40' : ''}`}
              >
                <td className="py-2 pr-4 whitespace-nowrap text-slate-300" title={formatDateTime(h.started_at)}>{formatDateTime(h.started_at)}</td>
                <td className="py-2 pr-4 font-mono text-xs text-slate-400">{h.source_key}</td>
                <td className="py-2 pr-4 text-slate-400 capitalize">{h.triggered_by}</td>
                <td className="py-2 pr-4"><StatusPill status={h.status} /></td>
                <td className="py-2 pr-4 text-right tabular-nums text-slate-200">{h.new_matches}</td>
                <td className="py-2 pr-4 text-right tabular-nums text-slate-200">{h.updated_matches}</td>
                <td className="py-2 pr-4 text-right tabular-nums text-slate-400">{h.unchanged_matches.toLocaleString()}</td>
                <td className={`py-2 pr-4 text-right tabular-nums ${h.failed_records ? 'text-amber-300' : 'text-slate-400'}`}>{h.failed_records}</td>
                <td className="py-2 text-right tabular-nums text-slate-400">{formatDuration(h.duration_seconds)}</td>
              </tr>,
              open === h.id && (
                <tr key={`${h.id}-detail`} className="border-b border-slate-800/60 bg-slate-950/40">
                  <td colSpan={9} className="px-3 py-3 text-xs text-slate-400">
                    {h.error_detail && <p className="mb-2 text-red-300">{h.error_detail}</p>}
                    {h.failed_files?.length > 0 && (
                      <ul className="mb-2 space-y-1">
                        {h.failed_files.slice(0, 20).map(f => (
                          <li key={f.file}><span className="font-mono text-slate-300">{f.file}</span> ({f.stage}): {f.error}</li>
                        ))}
                      </ul>
                    )}
                    {h.stats_refresh && !h.stats_refresh.error && (
                      <p>
                        Statistics refreshed for {h.stats_refresh.affected_matches} match(es):
                        {' '}{h.stats_refresh.win_probability_matches} win-probability curve(s),
                        {' '}{h.stats_refresh.player_impact_rows} player impact row(s) across {h.stats_refresh.players_affected} player(s).
                      </p>
                    )}
                    {h.stats_refresh?.error && <p className="text-amber-300">Statistics refresh error: {h.stats_refresh.error}</p>}
                  </td>
                </tr>
              ),
            ];
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function DataManagement() {
  const [status, setStatus] = useState(null);
  const [history, setHistory] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [saving, setSaving] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [page, setPage] = useState(1);
  const timer = useRef(null);

  const active = Boolean(status && (status.sync_running || status.current_sync || status.manual_sync_requested_at));

  const load = useCallback(async () => {
    try {
      const [s, h] = await Promise.all([getDataSyncStatus(), getDataSyncHistory(page, 15)]);
      setStatus(s);
      setHistory(h);
      setError(null);
    } catch (err) {
      setError(err.message || 'Could not load synchronisation status');
    }
  }, [page]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(load, active ? ACTIVE_POLL_MS : IDLE_POLL_MS);
    return () => clearTimeout(timer.current);
  }, [status, active, load]);

  // An informational "sync requested" notice is only relevant while that sync is pending or running.
  const wasActive = useRef(false);
  useEffect(() => {
    if (wasActive.current && !active) setNotice(n => (n && n.kind === 'info' ? null : n));
    wasActive.current = active;
  }, [active]);

  const saveSettings = async (patch) => {
    setSaving(true);
    setNotice(null);
    try {
      await updateDataSyncSettings(patch);
      await load();
    } catch (err) {
      setNotice({ kind: 'error', text: err.message });
    } finally {
      setSaving(false);
    }
  };

  const syncNow = async () => {
    setTriggering(true);
    setNotice(null);
    try {
      const res = await triggerDataSync();
      setNotice({ kind: 'info', text: res.message });
    } catch (err) {
      setNotice({ kind: 'error', text: err.message });
    } finally {
      setTriggering(false);
      load();
    }
  };

  if (!status && error) return <ErrorState message={error} />;
  if (!status) return <LoadingSpinner message="Loading synchronisation status..." />;

  const latest = status.latest_sync;
  const worker = status.worker;
  const settings = status.settings;
  const queued = !status.current_sync && status.manual_sync_requested_at;

  return (
    <div>
      {error && <p className="mb-4 rounded border border-red-900 bg-red-950/40 px-3 py-2 text-sm text-red-300">Live refresh failed: {error}</p>}

      <Panel
        title="Cricsheet synchronisation"
        subtitle="Checks Cricsheet for new and corrected matches and imports only what changed."
        action={(
          <div className="flex items-center gap-3">
            <span className={`inline-flex items-center gap-1.5 text-xs ${worker.healthy ? 'text-emerald-300' : 'text-amber-300'}`}>
              <span className={`h-2 w-2 rounded-full ${worker.healthy ? 'bg-emerald-400' : 'bg-amber-400'}`} />
              Worker {worker.healthy ? (worker.state === 'syncing' ? 'syncing' : 'running') : worker.state === 'stopped' ? 'stopped' : 'not responding'}
            </span>
            <button
              type="button"
              onClick={syncNow}
              disabled={triggering || active}
              className="rounded-md bg-indigo-600 px-3.5 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
            >
              {active ? 'Sync in progress…' : triggering ? 'Starting…' : 'Sync Now'}
            </button>
          </div>
        )}
      >
        {notice && (
          <p className={`mb-4 rounded border px-3 py-2 text-sm ${notice.kind === 'error' ? 'border-red-900 bg-red-950/40 text-red-300' : 'border-sky-900 bg-sky-950/40 text-sky-200'}`}>{notice.text}</p>
        )}
        {!worker.healthy && (
          <p className="mb-4 rounded border border-amber-900 bg-amber-950/30 px-3 py-2 text-xs text-amber-200">
            The background worker is {worker.state === 'stopped' ? 'stopped' : 'not responding'}
            {worker.heartbeat_at && <> (last heartbeat <TimeValue ts={worker.heartbeat_at} />)</>}.
            Automatic checks pause until it runs again; start it with <code className="font-mono">./start.sh</code> or <code className="font-mono">backend/scripts/sync_worker.sh start</code>. Sync Now still works.
          </p>
        )}

        {status.current_sync ? (
          <PhaseTracker run={status.current_sync} />
        ) : queued ? (
          <p className="text-sm text-sky-200">Sync requested <TimeValue ts={status.manual_sync_requested_at} /> — waiting for the worker to start it…</p>
        ) : (
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-slate-400">
            <span>Latest result: {latest ? <StatusPill status={latest.status} /> : <span className="text-slate-500">No sync yet</span>}</span>
            {latest && <span>Finished <TimeValue ts={latest.completed_at} /></span>}
            {latest?.failed_records > 0 && <span className="text-amber-300">{latest.failed_records} file(s) failed — see history</span>}
          </div>
        )}
      </Panel>

      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Data updated through" value={formatMatchDate(status.data_updated_through)} sub="Latest match date in the database" highlight />
        <StatCard label="Last source check" value={status.last_checked_at ? relativeTime(status.last_checked_at) : 'Never'} sub={status.last_checked_at ? formatDateTime(status.last_checked_at) : 'Cricsheet not checked yet'} />
        <StatCard label="Last successful import" value={status.last_imported_at ? relativeTime(status.last_imported_at) : 'Never'} sub={status.last_imported_at ? formatDateTime(status.last_imported_at) : 'No clean import recorded'} />
        <StatCard
          label="Next scheduled check"
          value={status.next_check_at ? relativeTime(status.next_check_at) : '—'}
          sub={!settings.auto_sync_enabled ? 'Automatic sync is off' : !worker.healthy ? 'Worker not running' : formatDateTime(status.next_check_at)}
        />
      </div>

      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-5">
        <StatCard label="Matches" value={status.total_matches.toLocaleString()} />
        <StatCard label="Innings" value={status.total_innings.toLocaleString()} />
        <StatCard label="Deliveries" value={status.total_deliveries.toLocaleString()} />
        <StatCard label="New in latest sync" value={status.new_matches_latest_sync.toLocaleString()} />
        <StatCard label="Corrected in latest sync" value={status.corrected_matches_latest_sync.toLocaleString()} />
      </div>

      <Panel title="Schedule" subtitle="Stored in PostgreSQL; the worker applies changes within a few seconds.">
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-sm text-slate-200">Automatic synchronisation</p>
              <p className="text-xs text-slate-500">Check Cricsheet in the background, even when CPI isn't open in a browser.</p>
            </div>
            <Toggle label="Automatic synchronisation" checked={settings.auto_sync_enabled} disabled={saving}
              onChange={v => saveSettings({ auto_sync_enabled: v })} />
          </div>
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-sm text-slate-200">Check frequency</p>
              <p className="text-xs text-slate-500">How often to ask Cricsheet whether its archives changed.</p>
            </div>
            <select
              value={settings.interval_hours}
              disabled={saving || !settings.auto_sync_enabled}
              onChange={e => saveSettings({ interval_hours: Number(e.target.value) })}
              className="rounded-md border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-slate-200 disabled:opacity-50"
            >
              {[...new Set([...INTERVAL_OPTIONS, settings.interval_hours])].sort((a, b) => a - b).map(h => (
                <option key={h} value={h}>Every {formatInterval(h)}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-sm text-slate-200">Check when the worker starts</p>
              <p className="text-xs text-slate-500">Skipped if a check succeeded in the last 15 minutes.</p>
            </div>
            <Toggle label="Check when the worker starts" checked={settings.check_on_start} disabled={saving}
              onChange={v => saveSettings({ check_on_start: v })} />
          </div>
        </div>
      </Panel>

      <Panel title="Sources" subtitle="Cricsheet archives monitored by CPI. Matches are de-duplicated across archives.">
        <ul className="divide-y divide-slate-800">
          {status.sources.map(s => (
            <li key={s.source_key} className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
              <div className="min-w-0">
                <p className="text-sm text-slate-200">{s.label}</p>
                <p className="truncate font-mono text-xs text-slate-500">{s.archive_url}</p>
                <p className="mt-1 text-xs text-slate-500">
                  Checked <TimeValue ts={s.last_checked_at} /> · Imported <TimeValue ts={s.last_imported_at} />
                  {s.last_modified && <> · Cricsheet updated {s.last_modified}</>}
                </p>
                {s.last_error && <p className="mt-1 text-xs text-amber-300">{s.last_error}</p>}
              </div>
              <Toggle label={`Monitor ${s.label}`} checked={s.enabled} disabled={saving}
                onChange={v => saveSettings({ sources: { [s.source_key]: v } })} />
            </li>
          ))}
        </ul>
      </Panel>

      <Panel
        title="Synchronisation history"
        subtitle="One row per archive per run. Click a row for errors and refreshed statistics."
        action={history && history.pages > 1 && (
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <button type="button" disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="rounded border border-slate-700 px-2 py-1 disabled:opacity-40">Prev</button>
            <span>{page} / {history.pages}</span>
            <button type="button" disabled={page >= history.pages} onClick={() => setPage(p => p + 1)} className="rounded border border-slate-700 px-2 py-1 disabled:opacity-40">Next</button>
          </div>
        )}
      >
        {history ? <HistoryTable items={history.items} /> : <LoadingSpinner message="Loading history..." />}
      </Panel>
    </div>
  );
}
