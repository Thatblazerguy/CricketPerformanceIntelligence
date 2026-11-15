/**
 * Player profile: data coverage and reconciled career totals (hybrid engine).
 *
 * - AnalyticsBasisNote: one line, shown on every tab, stating how many
 *   ball-by-ball matches the delivery-level analytics are built on.
 * - DataCoverageTab: career totals per format from both data layers, with
 *   each metric's verification status, plus coverage by format, competition
 *   and year, and any detected gaps.
 */
import { useEffect, useState } from 'react';
import { getPlayerCareer, getPlayerCoverage } from '../../services/api';
import { Callout, ErrorState, KpiGrid, Panel, PanelSkeleton } from '../../components/ui';
import { COVERAGE_META, CoverageBadge, CoverageBar, CoverageLegend, StatusValue } from '../../components/coverage';

const fmtDate = d => (d ? new Date(d).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—');

export function usePlayerCoverage(id) {
  const [state, setState] = useState({ coverage: null, error: null });
  useEffect(() => {
    let live = true;
    setState({ coverage: null, error: null });
    getPlayerCoverage(id).then(c => live && setState({ coverage: c, error: null }))
      .catch(e => live && setState({ coverage: null, error: e.message }));
    return () => { live = false; };
  }, [id]);
  return state;
}

export function AnalyticsBasisNote({ coverage, onOpen }) {
  if (!coverage) return null;
  const partial = coverage.total_matches - (coverage.by_status?.FULL_BALL_BY_BALL || 0);
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-line-soft bg-white/[0.025] px-4 py-2.5 text-xs text-slate-400">
      <span>{coverage.analytics_basis?.statement}</span>
      <span className="flex items-center gap-2">
        {coverage.career_predates_records?.length > 0 && <span className="text-warn-soft">Career predates available records</span>}
        {partial > 0 && !coverage.career_predates_records?.length && <span>{partial} match{partial === 1 ? '' : 'es'} without full delivery data</span>}
        <button type="button" onClick={onOpen} className="btn btn-ghost btn-xs">Data coverage</button>
      </span>
    </div>
  );
}

const BAT_COLS = [['runs', 'Runs'], ['innings', 'Inns'], ['not_outs', 'NO'], ['highest_score', 'HS'],
  ['batting_average', 'Ave', 2], ['strike_rate', 'SR', 2], ['hundreds', '100s'], ['fifties', '50s']];
const BOWL_COLS = [['wickets', 'Wkts'], ['innings', 'Inns'], ['balls_bowled', 'Balls'], ['runs_conceded', 'Runs'],
  ['bowling_average', 'Ave', 2], ['economy', 'Econ', 2], ['best_innings', 'Best'], ['five_wicket_hauls', '5w']];

function CareerTable({ career, kind }) {
  const cols = kind === 'batting' ? BAT_COLS : BOWL_COLS;
  const rows = Object.entries(career.formats).filter(([, f]) => f[kind].innings.value > 0);
  if (!rows.length) return <p className="text-xs text-slate-500">No {kind} innings recorded.</p>;
  const intl = career.international_combined;
  const showIntl = rows.filter(([fc]) => ['TEST', 'ODI', 'T20I'].includes(fc)).length > 1;
  return (
    <div className="overflow-x-auto rounded-2xl border border-line bg-surface">
      <table className="w-full text-[13px]">
        <thead className="bg-surface-raised"><tr>
          <th className="px-3.5 py-2.5 text-left text-2xs font-medium text-slate-500">Format</th>
          <th className="px-3.5 py-2.5 text-right text-2xs font-medium text-slate-500">Mat</th>
          {cols.map(([k, label]) => <th key={k} className="px-3.5 py-2.5 text-right text-2xs font-medium text-slate-500">{label}</th>)}
          <th className="px-3.5 py-2.5 text-left text-2xs font-medium text-slate-500">Sources</th>
        </tr></thead>
        <tbody>
          {rows.map(([fc, f]) => (
            <tr key={fc} className="border-t border-line-soft">
              <td className="px-3.5 py-2.5 text-slate-200">{f.label}</td>
              <td className="num px-3.5 py-2.5 text-right text-slate-300">{f.matches.value}</td>
              {cols.map(([k, , d]) => <td key={k} className="num px-3.5 py-2.5 text-right text-slate-200"><StatusValue metric={f[kind][k]} digits={d} /></td>)}
              <td className="px-3.5 py-2.5 text-2xs text-slate-500">{provenanceText(f.provenance[kind])}</td>
            </tr>
          ))}
          {showIntl && (
            <tr className="border-t border-line bg-white/[0.02]">
              <td className="px-3.5 py-2.5 font-medium text-slate-200">International (Test + ODI + T20I)</td>
              <td className="num px-3.5 py-2.5 text-right text-slate-300">{intl.matches}</td>
              {cols.map(([k, , d]) => <td key={k} className="num px-3.5 py-2.5 text-right font-medium text-white"><StatusValue metric={intl[kind][k]} digits={d} /></td>)}
              <td />
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

const PROV_LABEL = { ball_by_ball: 'ball-by-ball', scorecard: 'scorecard', both_agree: 'both agree', reconciled: 'reconciled' };
function provenanceText(p = {}) {
  return Object.entries(p).map(([k, n]) => `${n} ${PROV_LABEL[k] || k}`).join(' · ') || '—';
}

function BreakdownTable({ rows, keyLabel, keyField }) {
  return (
    <div className="space-y-2.5">
      {rows.map(r => (
        <div key={r[keyField]} className="grid grid-cols-[minmax(0,10rem)_1fr_3.5rem] items-center gap-3 text-xs">
          <span className="truncate text-slate-300" title={r[keyField]}>{r.label || r[keyField]}</span>
          <CoverageBar counts={r.counts} />
          <span className="num text-right text-slate-400">{r.total}</span>
        </div>
      ))}
      {!rows.length && <p className="text-xs text-slate-500">No {keyLabel} recorded.</p>}
    </div>
  );
}

export function DataCoverageTab({ playerId, coverage }) {
  const [career, setCareer] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let live = true;
    setCareer(null); setError(null);
    getPlayerCareer(playerId).then(c => live && setCareer(c)).catch(e => live && setError(e.message));
    return () => { live = false; };
  }, [playerId]);

  if (!coverage) return <PanelSkeleton rows={6} />;
  const s = coverage.by_status || {};
  return (
    <div className="space-y-6">
      <KpiGrid cols="grid-cols-2 sm:grid-cols-3 lg:grid-cols-6" items={[
        { label: 'Verified matches', value: coverage.verified_matches.toLocaleString(), sub: `${coverage.total_matches} recorded` },
        { label: 'Ball-by-ball', value: (s.FULL_BALL_BY_BALL || 0).toLocaleString(), sub: COVERAGE_META.FULL_BALL_BY_BALL.label, tone: 'pos' },
        { label: 'Scorecard only', value: (s.SCORECARD_ONLY || 0).toLocaleString(), sub: COVERAGE_META.SCORECARD_ONLY.label },
        { label: 'Partial', value: (s.PARTIAL_BALL_BY_BALL || 0).toLocaleString(), sub: COVERAGE_META.PARTIAL_BALL_BY_BALL.label, tone: s.PARTIAL_BALL_BY_BALL ? 'warn' : undefined },
        { label: 'Records span', value: coverage.earliest_record ? `${new Date(coverage.earliest_record).getFullYear()}–${new Date(coverage.latest_record).getFullYear()}` : '—', sub: `${fmtDate(coverage.earliest_record)} → ${fmtDate(coverage.latest_record)}` },
        { label: 'Last data sync', value: coverage.last_ball_by_ball_sync ? fmtDate(coverage.last_ball_by_ball_sync) : 'Never', sub: coverage.last_scorecard_import ? `Scorecards ${fmtDate(coverage.last_scorecard_import)}` : 'No scorecard imports yet' },
      ]} />

      {coverage.career_predates_records?.length > 0 && (
        <Callout tone="warn">
          <p className="font-medium">This player's career likely starts before the available records.</p>
          <ul className="mt-1.5 list-disc space-y-1 pl-4">
            {coverage.career_predates_records.map(g => <li key={`${g.format_class}-${g.team}`}>{g.message}</li>)}
          </ul>
          <p className="mt-1.5">Totals below are what CPI can verify, not the complete career. No figure has been estimated to fill the gap.</p>
        </Callout>
      )}

      <Panel title="Career statistics from verified records" subtitle="Ball-by-ball and verified scorecard data combined; each innings counted once. Amber values are incomplete (n/m innings carry the inputs). Hover a value for its status.">
        {error && <ErrorState message={error} />}
        {!career && !error && <PanelSkeleton rows={4} />}
        {career && (
          <div className="space-y-5">
            <div><h4 className="mb-2 text-xs font-semibold text-slate-300">Batting</h4><CareerTable career={career} kind="batting" /></div>
            <div><h4 className="mb-2 text-xs font-semibold text-slate-300">Bowling</h4><CareerTable career={career} kind="bowling" /></div>
            {career.conflicts?.length > 0 && (
              <Callout tone="warn">{career.conflicts.length} value{career.conflicts.length === 1 ? '' : 's'} differ between sources; both are kept and flagged for reconciliation in Data Health.</Callout>
            )}
            {career.excluded_inconsistent_scorecard_innings > 0 && (
              <p className="text-2xs text-slate-500">{career.excluded_inconsistent_scorecard_innings} scorecard innings failed consistency checks and are excluded.</p>
            )}
          </div>
        )}
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Coverage by format" actions={<CoverageLegend />}>
          <BreakdownTable rows={coverage.by_format} keyField="format_class" keyLabel="formats" />
        </Panel>
        <Panel title="Coverage by competition" subtitle="Top 25 by matches">
          <BreakdownTable rows={coverage.by_competition} keyField="competition" keyLabel="competitions" />
        </Panel>
      </div>
      <Panel title="Coverage by year" actions={<CoverageLegend />}>
        <div className="flex h-28 items-end gap-1 overflow-x-auto">
          {coverage.by_year.map(y => {
            const max = Math.max(...coverage.by_year.map(r => r.total));
            return (
              <div key={y.year} className="flex min-w-[18px] flex-1 flex-col items-center gap-1" title={`${y.year}: ${y.total} matches`}>
                <div className="flex w-full flex-col-reverse overflow-hidden rounded-sm" style={{ height: `${(80 * y.total) / max}px` }}>
                  {['FULL_BALL_BY_BALL', 'PARTIAL_BALL_BY_BALL', 'SCORECARD_ONLY'].map(k => y.counts[k] ? <div key={k} className={COVERAGE_META[k].bar} style={{ height: `${(100 * y.counts[k]) / y.total}%` }} /> : null)}
                </div>
                <span className="num text-3xs text-slate-500">{String(y.year).slice(2)}</span>
              </div>
            );
          })}
        </div>
      </Panel>
      <p className="text-2xs text-slate-500">Data labels: <CoverageBadge status="FULL_BALL_BY_BALL" /> <CoverageBadge status="SCORECARD_ONLY" /> <CoverageBadge status="PARTIAL_BALL_BY_BALL" /> <CoverageBadge status="UNKNOWN" /></p>
    </div>
  );
}
