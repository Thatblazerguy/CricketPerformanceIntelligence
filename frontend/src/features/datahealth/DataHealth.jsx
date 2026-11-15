/**
 * Data Health: what CPI holds, what is missing, and the controls to fix it.
 * All figures come from /api/v1/data-health/*; nothing is computed here.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { dataHealth } from '../../services/api';
import {
  Badge, Button, Callout, DataTable, ErrorState, FilterBar, FilterField, KpiGrid, PageHeader, Panel,
  PanelSkeleton, PlayerLink, Select, Tabs,
} from '../../components/ui';
import { COVERAGE_META, CoverageBar, CoverageLegend } from '../../components/coverage';

const FORMAT_OPTIONS = [
  { id: 'TEST', label: 'Test' }, { id: 'ODI', label: 'ODI' }, { id: 'T20I', label: 'T20I' },
  { id: 'FIRST_CLASS', label: 'First-class' }, { id: 'LIST_A', label: 'List A' },
  { id: 'MULTI_DAY', label: 'Other multi-day (MDM)' }, { id: 'ONE_DAY', label: 'Other one-day (ODM)' },
  { id: 'T20_DOMESTIC', label: 'Domestic / franchise T20' },
];
const EMPTY = { format_class: '', gender: '', season: '', competition: '', team: '', player_id: '' };
const fmt = d => (d ? new Date(d).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '—');
const day = d => (d ? new Date(d).toLocaleDateString(undefined, { dateStyle: 'medium' }) : '—');
const n = v => (v ?? 0).toLocaleString();
const clean = f => Object.fromEntries(Object.entries(f).filter(([, v]) => v));

function useLoad(fn, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const load = useCallback(() => {
    setState(s => ({ ...s, loading: true, error: null }));
    return fn().then(data => setState({ data, error: null, loading: false }))
      .catch(e => setState({ data: null, error: e.message, loading: false }));
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);
  return { ...state, reload: load };
}

function CoverageRows({ rows, labelKey = 'key' }) {
  return (
    <div className="space-y-2.5">
      {rows.map(r => (
        <div key={r.key} className="grid grid-cols-[minmax(0,12rem)_1fr_4.5rem_7rem] items-center gap-3 text-xs max-sm:grid-cols-[minmax(0,8rem)_1fr_3.5rem]">
          <span className="truncate text-slate-300" title={String(r[labelKey] ?? r.key)}>{r[labelKey] ?? r.key}</span>
          <CoverageBar counts={r.counts} />
          <span className="num text-right text-slate-400">{n(r.total)}</span>
          <span className="num text-right text-2xs text-slate-500 max-sm:hidden">{r.first ? `${new Date(r.first).getFullYear()}–${new Date(r.last).getFullYear()}` : ''}</span>
        </div>
      ))}
    </div>
  );
}

function OverviewTab({ filters }) {
  const ov = useLoad(() => dataHealth.overview(clean(filters)), [JSON.stringify(filters)]);
  const comp = useLoad(() => dataHealth.competitions(clean(filters)), [JSON.stringify(filters)]);
  if (ov.error) return <ErrorState message={ov.error} onRetry={ov.reload} />;
  const o = ov.data;
  return (
    <div className="space-y-6">
      {!o ? <PanelSkeleton rows={3} /> : (
        <>
          <KpiGrid cols="grid-cols-2 sm:grid-cols-3 lg:grid-cols-5" items={[
            { label: 'Total matches', value: n(o.total_matches), sub: `${n(o.deliveries_imported)} deliveries` },
            { label: 'Full ball-by-ball', value: n(o.by_status.FULL_BALL_BY_BALL), sub: COVERAGE_META.FULL_BALL_BY_BALL.label, tone: 'pos' },
            { label: 'Scorecard only', value: n(o.by_status.SCORECARD_ONLY), sub: COVERAGE_META.SCORECARD_ONLY.label },
            { label: 'Partial', value: n(o.by_status.PARTIAL_BALL_BY_BALL), sub: COVERAGE_META.PARTIAL_BALL_BY_BALL.label, tone: o.by_status.PARTIAL_BALL_BY_BALL ? 'warn' : undefined },
            { label: 'Metadata only', value: n(o.by_status.METADATA_ONLY + o.by_status.UNKNOWN), sub: 'Coverage unverified' },
            { label: 'Missing downloadable', value: n(o.missing_downloadable), sub: 'Listed by Cricsheet, not in CPI', tone: o.missing_downloadable ? 'warn' : undefined },
            { label: 'Failed imports', value: n(o.failed_imports), tone: o.failed_imports ? 'neg' : undefined },
            { label: 'Withheld by source', value: o.withheld_by_source ?? '—', sub: 'Cricsheet policy; not obtainable there' },
            { label: 'Duplicate candidates', value: n(o.duplicate_candidates), tone: o.duplicate_candidates ? 'warn' : undefined },
            { label: 'Last sync', value: o.last_sync ? day(o.last_sync) : 'Never', sub: `Checked ${fmt(o.last_sync_check)}` },
          ]} />
          {o.open_reconciliation_flags > 0 && <Callout tone="warn">{o.open_reconciliation_flags} source disagreements await reconciliation (Players tab).</Callout>}
        </>
      )}
      {comp.error && <ErrorState message={comp.error} onRetry={comp.reload} />}
      {!comp.data && !comp.error && <PanelSkeleton rows={6} />}
      {comp.data && (
        <>
          <div className="grid gap-6 lg:grid-cols-2">
            <Panel title="International vs domestic" actions={<CoverageLegend />}><CoverageRows rows={comp.data.by_category} /></Panel>
            <Panel title="By format" subtitle="Each match belongs to exactly one format, so totals never double-count">
              <CoverageRows rows={comp.data.by_format} labelKey="label" />
            </Panel>
          </div>
          <Panel title="Where source coverage begins" subtitle="Nothing earlier than these dates exists in any integrated source. Careers that started before them are incomplete.">
            <div className="flex flex-wrap gap-2">
              {comp.data.source_coverage_starts.map(s => <Badge key={`${s.format_class}-${s.gender}`}>{s.label} ({s.gender}) from {day(s.first)}</Badge>)}
            </div>
          </Panel>
          <Panel title="By year" actions={<CoverageLegend />}>
            <div className="flex h-36 items-end gap-1 overflow-x-auto pb-1">
              {comp.data.by_year.map(y => {
                const max = Math.max(...comp.data.by_year.map(r => r.total));
                return (
                  <div key={y.key} className="flex min-w-[20px] flex-1 flex-col items-center gap-1" title={`${y.key}: ${n(y.total)} matches`}>
                    <div className="flex w-full flex-col-reverse overflow-hidden rounded-sm" style={{ height: `${(110 * y.total) / max}px` }}>
                      {['FULL_BALL_BY_BALL', 'PARTIAL_BALL_BY_BALL', 'SCORECARD_ONLY'].map(k => y.counts[k] ? <div key={k} className={COVERAGE_META[k].bar} style={{ height: `${(100 * y.counts[k]) / y.total}%` }} /> : null)}
                    </div>
                    <span className="num text-3xs text-slate-500">{String(y.key).slice(2)}</span>
                  </div>
                );
              })}
            </div>
          </Panel>
          <div className="grid gap-6 lg:grid-cols-2">
            <Panel title="By competition" subtitle="Top 60 by matches"><CoverageRows rows={comp.data.by_competition} /></Panel>
            <Panel title="By country" subtitle="Venue country where known"><CoverageRows rows={comp.data.by_country} /></Panel>
          </div>
        </>
      )}
    </div>
  );
}

function PlayersTab({ gender }) {
  const p = useLoad(() => dataHealth.players({ limit: 200, ...(gender ? { gender } : {}) }), [gender]);
  const flags = useLoad(() => dataHealth.reconciliation(), []);
  if (p.error) return <ErrorState message={p.error} onRetry={p.reload} />;
  if (!p.data) return <PanelSkeleton rows={8} />;
  const d = p.data;
  return (
    <div className="space-y-6">
      <Panel title="Careers that predate available records"
        subtitle="International players whose first recorded match falls when source coverage of their team begins. Their CPI career totals are incomplete; this is a coverage gap, not a data error.">
        <DataTable dense pageSize={15} rows={d.career_predates_records} rowKey={(r, i) => `${r.player_id}-${r.format_class}-${i}`}
          searchKeys={['name', 'team']} searchPlaceholder="Search players or teams"
          columns={[
            { key: 'name', label: 'Player', render: r => <PlayerLink id={r.player_id} name={r.name} /> },
            { key: 'format_class', label: 'Format' },
            { key: 'team', label: 'Team' },
            { key: 'first_record', label: 'First record', render: r => day(r.first_record) },
            { key: 'team_records_begin', label: 'Team records begin', render: r => day(r.team_records_begin) },
            { key: 'matches_recorded', label: 'Matches recorded', align: 'right' },
          ]} />
      </Panel>
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Incomplete ball-by-ball coverage" subtitle="Players with partial or scorecard-only matches">
          <DataTable dense pageSize={10} rows={d.incomplete_ball_by_ball} rowKey={r => r.player_id} emptyMessage="Every recorded match has full delivery data."
            columns={[
              { key: 'name', label: 'Player', render: r => <PlayerLink id={r.player_id} name={r.name} /> },
              { key: 'matches', label: 'Matches', align: 'right' }, { key: 'partial', label: 'Partial', align: 'right' },
              { key: 'scorecard_only', label: 'Scorecard', align: 'right' },
            ]} />
        </Panel>
        <Panel title="Unresolved scorecard identities" subtitle="Scorecard names not linked to a CPI player (no ID and no unique name + team match)">
          <DataTable dense pageSize={10} rows={d.unresolved_scorecard_identities} rowKey={r => r.name} emptyMessage="No unresolved names."
            columns={[{ key: 'name', label: 'Name in source' }, { key: 'rows', label: 'Rows', align: 'right' }]} />
        </Panel>
      </div>
      <Panel title="Source disagreements" subtitle="Both values are kept. The value used follows the documented precedence until someone resolves the flag with evidence.">
        {flags.data && <DataTable dense pageSize={15} rows={flags.data.flags} rowKey={r => r.id} emptyMessage="No open disagreements."
          columns={[
            { key: 'player', label: 'Player' }, { key: 'match', label: 'Match' },
            { key: 'start_date', label: 'Date', render: r => day(r.start_date) },
            { key: 'innings_number', label: 'Inns', align: 'right' }, { key: 'metric', label: 'Metric' },
            { key: 'values', label: 'Values by source', render: r => Object.entries(r.values).map(([k, v]) => `${k}: ${v}`).join(' · ') },
            { key: 'resolution', label: 'Current handling' },
            { key: 'id', label: '', sortable: false, render: r => <Button size="xs" variant="ghost" onClick={async () => {
              const note = window.prompt('Resolution, citing the evidence used:');
              if (note) { await dataHealth.resolveFlag(r.id, note); flags.reload(); }
            }}>Resolve</Button> },
          ]} />}
      </Panel>
    </div>
  );
}

const ACTIONS = [
  { id: 'refresh-inventory', label: 'Refresh source inventories', hint: 'Re-read the Cricsheet match list and compare it with CPI', params: { check_upstream: true } },
  { id: 'import-missing', label: 'Import missing matches', hint: 'Import listed matches CPI lacks from the local archive (queues a sync for any not downloaded)' },
  { id: 'retry-failed', label: 'Retry failed imports', hint: 'Re-attempt matches that previously failed to import' },
  { id: 'reconcile', label: 'Reconcile conflicting records', hint: 'Re-check every match held by more than one source' },
  { id: 'refresh-coverage', label: 'Recompute coverage', hint: 'Re-classify every match (takes a few minutes on the full dataset)' },
];

function IngestionTab() {
  const [busy, setBusy] = useState(null);
  const [result, setResult] = useState(null);
  const inv = useLoad(() => dataHealth.inventory({ limit: 500 }), []);
  const log = useLoad(() => dataHealth.log({ limit: 100 }), []);
  const dup = useLoad(() => dataHealth.duplicates(), []);
  const [bundleError, setBundleError] = useState(null);

  const run = async a => {
    setBusy(a.id); setResult(null);
    try { setResult({ action: a.label, data: await dataHealth.action(a.id, a.params) }); inv.reload(); log.reload(); }
    catch (e) { setResult({ action: a.label, error: e.message }); }
    finally { setBusy(null); }
  };
  const upload = async file => {
    setBundleError(null); setBusy('upload');
    try { setResult({ action: 'Scorecard import', data: await dataHealth.importScorecards(JSON.parse(await file.text())) }); log.reload(); }
    catch (e) { setBundleError(e.message); }
    finally { setBusy(null); }
  };

  return (
    <div className="space-y-6">
      <Panel title="Ingestion management">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {ACTIONS.map(a => (
            <div key={a.id} className="flex flex-col justify-between gap-3 rounded-2xl border border-line-soft p-4">
              <div><p className="text-sm font-medium text-slate-200">{a.label}</p><p className="mt-1 text-2xs text-slate-500">{a.hint}</p></div>
              <Button size="sm" variant={a.id === 'import-missing' ? 'primary' : 'secondary'} disabled={!!busy} onClick={() => run(a)}>
                {busy === a.id ? 'Running…' : 'Run'}
              </Button>
            </div>
          ))}
          <div className="flex flex-col justify-between gap-3 rounded-2xl border border-line-soft p-4">
            <div>
              <p className="text-sm font-medium text-slate-200">Import verified scorecards</p>
              <p className="mt-1 text-2xs text-slate-500">JSON bundle from a licensed source; must name the source and licence (docs/SCORECARD_IMPORT_FORMAT.md).</p>
            </div>
            <label className={`btn btn-secondary btn-sm ${busy ? 'pointer-events-none opacity-50' : ''}`}>
              {busy === 'upload' ? 'Importing…' : 'Choose file'}
              <input type="file" accept="application/json,.json" className="hidden" onChange={e => e.target.files[0] && upload(e.target.files[0])} />
            </label>
            {bundleError && <p className="text-2xs text-neg-soft">{bundleError}</p>}
          </div>
        </div>
        {result && (
          <div className="mt-4">
            {result.error ? <ErrorState message={`${result.action}: ${result.error}`} />
              : <Callout><span className="font-medium">{result.action} finished.</span> <code className="break-all text-2xs">{JSON.stringify(result.data)}</code></Callout>}
          </div>
        )}
      </Panel>

      <Panel title="Missing and failed matches" subtitle="Listed by a source but not imported into CPI">
        {inv.data && <DataTable dense pageSize={15} rows={inv.data.items} rowKey={r => `${r.source_key}-${r.source_match_id}`}
          emptyMessage="Every match listed by Cricsheet is in CPI." searchKeys={['teams', 'source_match_id']}
          columns={[
            { key: 'source_match_id', label: 'Source ID' }, { key: 'start_date', label: 'Date', render: r => day(r.start_date) },
            { key: 'match_type', label: 'Type' }, { key: 'teams', label: 'Teams' },
            { key: 'status', label: 'Status', render: r => <Badge variant={r.status === 'failed' ? 'red' : 'amber'}>{r.status}</Badge> },
            { key: 'attempts', label: 'Attempts', align: 'right' }, { key: 'last_error', label: 'Last error' },
          ]} />}
      </Panel>

      <Panel title="Duplicate detection" subtitle="Records the identity rules consider the same match. Same-day fixtures between the same teams are only merged when totals and results agree.">
        {dup.data && (
          <>
            <p className="mb-3 text-xs text-slate-400">{n(dup.data.same_day_fixtures_kept_apart)} same-date, same-teams fixture pairs exist; {n(dup.data.candidates.length)} look like true duplicates.</p>
            <DataTable dense pageSize={10} rows={dup.data.candidates} rowKey={r => `${r.a}-${r.b}`} emptyMessage="No duplicate matches detected."
              columns={[{ key: 'date', label: 'Date', render: r => day(r.date) }, { key: 'teams', label: 'Teams' },
                { key: 'evidence', label: 'Evidence', render: r => <code className="text-2xs">{JSON.stringify(r.evidence)}</code> }]} />
          </>
        )}
      </Panel>

      <Panel title="Ingestion log" subtitle="Hybrid engine events and Cricsheet sync runs">
        {log.data && <DataTable dense pageSize={20} rows={log.data.events} rowKey={r => `${r.kind}-${r.id}`}
          columns={[
            { key: 'created_at', label: 'When', render: r => fmt(r.created_at) }, { key: 'source_key', label: 'Source' },
            { key: 'action', label: 'Action' },
            { key: 'status', label: 'Status', render: r => <Badge variant={['ok', 'completed', 'no_changes'].includes(r.status) ? 'green' : r.status === 'failed' ? 'red' : 'amber'}>{r.status}</Badge> },
            { key: 'counts', label: 'Counts', render: r => <code className="text-2xs">{JSON.stringify(r.counts)}</code> },
          ]} />}
      </Panel>
    </div>
  );
}

function SourcesTab() {
  const s = useLoad(() => dataHealth.sources(), []);
  if (s.error) return <ErrorState message={s.error} onRetry={s.reload} />;
  if (!s.data) return <PanelSkeleton rows={6} />;
  const access = { open: 'green', user_supplied: 'blue', licence_required: 'amber', restricted: 'red', unavailable: 'default' };
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {s.data.sources.map(src => (
        <Panel key={src.key} title={src.name} actions={<div className="flex gap-1.5">
          <Badge variant={access[src.access] || 'default'}>{src.access.replace('_', ' ')}</Badge>
          <Badge variant={src.integrated ? 'green' : 'default'}>{src.integrated ? 'integrated' : 'not integrated'}</Badge>
        </div>}>
          <dl className="space-y-2 text-xs">
            <div><dt className="text-slate-500">Data level</dt><dd className="text-slate-200">{src.data_level.replace(/_/g, ' ')}</dd></div>
            <div><dt className="text-slate-500">Coverage</dt><dd className="text-slate-300">{src.coverage}</dd></div>
            <div><dt className="text-slate-500">Licence / access</dt><dd className="text-slate-300">{src.licence}</dd></div>
          </dl>
          {src.notes?.length > 0 && <ul className="mt-3 list-disc space-y-1 pl-4 text-2xs text-slate-400">{src.notes.map(t => <li key={t}>{t}</li>)}</ul>}
        </Panel>
      ))}
    </div>
  );
}

export default function DataHealth() {
  const [tab, setTab] = useState('overview');
  const [filters, setFilters] = useState(EMPTY);
  const active = useMemo(() => Object.values(filters).filter(Boolean).length, [filters]);
  const set = k => v => setFilters(f => ({ ...f, [k]: v }));
  return (
    <div>
      <PageHeader eyebrow="System" title="Data Health"
        subtitle="Coverage of every match CPI knows about, what is missing, and the tools to recover it. Ball-by-ball and scorecard data are tracked separately and never confused." />
      {tab === 'overview' && (
        <FilterBar onReset={() => setFilters(EMPTY)} active={active}
          note="Filters apply to the overview. Player filter takes a CPI player id (from a profile URL).">
          <FilterField label="Format"><Select value={filters.format_class} onChange={set('format_class')} options={FORMAT_OPTIONS} placeholder="All formats" /></FilterField>
          <FilterField label="Gender"><Select value={filters.gender} onChange={set('gender')} options={[{ id: 'male', label: 'Men' }, { id: 'female', label: 'Women' }]} placeholder="All" /></FilterField>
          <FilterField label="Season / year"><input className="h-9 w-28 text-[13px]" value={filters.season} onChange={e => set('season')(e.target.value)} placeholder="e.g. 2011" /></FilterField>
          <FilterField label="Competition"><input className="h-9 w-44 text-[13px]" value={filters.competition} onChange={e => set('competition')(e.target.value)} placeholder="e.g. Ranji" /></FilterField>
          <FilterField label="Team"><input className="h-9 w-36 text-[13px]" value={filters.team} onChange={e => set('team')(e.target.value)} placeholder="e.g. India" /></FilterField>
          <FilterField label="Player id"><input className="h-9 w-40 text-[13px]" value={filters.player_id} onChange={e => set('player_id')(e.target.value.trim())} placeholder="uuid" /></FilterField>
        </FilterBar>
      )}
      <Tabs className="mb-6" value={tab} onChange={setTab} tabs={[
        { id: 'overview', label: 'Coverage' }, { id: 'players', label: 'Players' },
        { id: 'ingestion', label: 'Ingestion' }, { id: 'sources', label: 'Sources' },
      ]} />
      {tab === 'overview' && <OverviewTab filters={filters} />}
      {tab === 'players' && <PlayersTab gender={filters.gender} />}
      {tab === 'ingestion' && <IngestionTab />}
      {tab === 'sources' && <SourcesTab />}
    </div>
  );
}
