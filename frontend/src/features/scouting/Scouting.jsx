/**
 * Scouting workspace: define requirements → filter → ranked shortlist →
 * analytics → comparison → scouting report. All analytics come from the
 * /scouting/v2 backend engine.
 */
import { useEffect, useMemo, useState } from 'react';
import { getScoutOptions, scoutRank } from '../../services/api';
import { Callout, Collapsible, EmptyState, ErrorState, LoadingSpinner, PageHeader, Tabs } from '../../components/ui';
import RequirementsPanel from './RequirementsPanel';
import RankingTable, { ExclusionSummary, MethodologyPanel } from './RankingTable';
import CompareView from './CompareView';
import PlayerReport from './PlayerReport';
import CohortExplorer from './CohortExplorer';
import { fmtInt, storage } from './scoutUi';

const INITIAL = {
  role: 'middle_order', format: 'T20', gender: 'male', competitions: [], seasons: [], start_year: '', end_year: '',
  nationality: '', positions: [], bowling_type: '', bowling_arm: '', bowling_styles: [], min_matches: 0, min_innings: 10,
  min_dual_matches: 5, min_age: '', max_age: '', requirements: [], weights: null, allrounder_batting_weight: 0.5, min_tier: 'Promising',
};
const SHORTLIST_KEY = 'cpi.scouting.shortlist.v2';
const STEPS = ['Define requirements', 'Apply filters', 'Generate shortlist', 'Examine analytics', 'Compare candidates', 'Scouting report'];

const num = v => (v === '' || v === null || v === undefined ? null : Number(v));

export default function Scouting() {
  const [options, setOptions] = useState(null);
  const [optionsError, setOptionsError] = useState('');
  const [form, setForm] = useState(INITIAL);
  const [result, setResult] = useState(null);
  const [submittedScope, setSubmittedScope] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('ranking');
  const [shortlist, setShortlist] = useState(() => storage.get(SHORTLIST_KEY, {}));
  const [reportPlayer, setReportPlayer] = useState(null);
  const [reportRole, setReportRole] = useState(null);

  useEffect(() => {
    getScoutOptions().then(setOptions).catch(e => setOptionsError(e.message));
  }, []);
  useEffect(() => storage.set(SHORTLIST_KEY, shortlist), [shortlist]);

  const scope = useMemo(() => ({
    format: form.format, gender: form.gender, competitions: form.competitions, seasons: form.seasons,
    start_year: num(form.start_year), end_year: num(form.end_year),
  }), [form.format, form.gender, form.competitions, form.seasons, form.start_year, form.end_year]);

  async function run() {
    setLoading(true); setError('');
    try {
      const payload = {
        ...scope, role: form.role, nationality: form.nationality || null,
        positions: form.positions, bowling_type: form.bowling_type || null, bowling_arm: form.bowling_arm || null,
        bowling_styles: form.bowling_styles, min_matches: Number(form.min_matches) || 0, min_innings: Number(form.min_innings) || 0,
        min_dual_matches: form.role === 'all_rounder' ? Number(form.min_dual_matches) || 0 : 0,
        min_age: num(form.min_age), max_age: num(form.max_age), requirements: form.requirements,
        weights: form.weights, allrounder_batting_weight: form.allrounder_batting_weight, min_tier: form.min_tier || null, limit: 150,
      };
      const data = await scoutRank(payload);
      setResult(data);
      setSubmittedScope(scope);
      setTab('ranking');
    } catch (e) {
      setError(e.message || 'Scouting failed.');
    } finally {
      setLoading(false);
    }
  }

  function toggleShortlist(c) {
    const id = c.identity.player_id;
    setShortlist(old => {
      const next = { ...old };
      if (next[id]) delete next[id];
      else next[id] = { player_id: id, player_name: c.identity.player_name, nationality: c.identity.nationality };
      return next;
    });
  }
  function openReport(c) {
    setReportPlayer(c.identity.player_id);
    setReportRole(result?.role?.key || form.role);
    setTab('report');
  }

  const activeStep = tab === 'report' ? 5 : tab === 'compare' ? 4 : result ? 3 : 0;
  const shortlistCount = Object.keys(shortlist).length;
  const effectiveScope = submittedScope || scope;

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Recruitment intelligence" title="Scouting"
        subtitle="Role-specific, sample-aware player evaluation from ball-by-ball records. Every score is a weighted mean of percentiles you can audit metric by metric." />

      <ol className="flex flex-wrap gap-1.5 text-2xs" aria-label="Scouting workflow">
        {STEPS.map((s, i) => (
          <li key={s} className={`flex items-center gap-1.5 rounded-md border px-2 py-1 ${i <= activeStep ? 'border-accent/40 bg-accent-muted/40 text-slate-200' : 'border-line text-slate-500'}`}>
            <span className="num text-3xs text-accent-soft">{i + 1}</span>{s}
          </li>
        ))}
      </ol>

      {optionsError && <ErrorState message={optionsError} />}
      {!options && !optionsError && <LoadingSpinner message="Loading scouting model…" />}
      {options && (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-[320px_minmax(0,1fr)]">
          <aside className="h-fit space-y-3 xl:sticky xl:top-4">
            <RequirementsPanel options={options} form={form} setForm={setForm} onSubmit={run} loading={loading} />
            <Collapsible title="Data coverage & limits" subtitle="What the dataset can and cannot support">
              <ul className="list-disc space-y-1.5 pl-4 text-2xs leading-relaxed text-slate-400">
                {options.coverage.notes.map((n, i) => <li key={i}>{n}</li>)}
              </ul>
            </Collapsible>
          </aside>

          <section className="min-w-0 space-y-4">
            <Tabs value={tab} onChange={setTab} tabs={[
              { id: 'ranking', label: `Ranked candidates${result ? ` · ${fmtInt(result.total_candidates)}` : ''}` },
              { id: 'compare', label: `Shortlist & compare · ${shortlistCount}` },
              { id: 'report', label: 'Scouting report' },
              { id: 'explorer', label: 'Cohort explorer' },
            ]} />

            {tab === 'ranking' && (
              <>
                {loading && <LoadingSpinner message="Aggregating innings, estimating priors and ranking…" />}
                {error && <ErrorState message={error} />}
                {!result && !loading && !error && (
                  <EmptyState icon="scouting" message="Describe the player you want to recruit, then generate a shortlist."
                    hint="Example: Middle-order batter · T20 · nationality India · min 30 innings · requirement 'Strike rate vs spin ≥ 120' · raise the weights for middle-overs SR and spin." />
                )}
                {result && !loading && (
                  <>
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <p className="text-xs text-slate-400"><b className="text-white">{fmtInt(result.total_candidates)}</b> candidates · {result.role.label} · {result.scope}
                        {result.role.positions && <> · positions {result.role.positions.join(', ')}</>}</p>
                      <ExclusionSummary result={result} />
                    </div>
                    {Object.values(result.comparison_group).some(g => g.note) && <Callout tone="warn">{Object.values(result.comparison_group).map(g => g.note).filter(Boolean).join(' ')}</Callout>}
                    <RankingTable result={result} shortlist={shortlist} toggleShortlist={toggleShortlist} onReport={openReport} />
                    {result.total_candidates > result.candidates.length && <p className="text-2xs text-slate-500">Showing the top {result.candidates.length} of {fmtInt(result.total_candidates)}. Tighten the requirements to narrow the list.</p>}
                    <Collapsible title="Ranking methodology" subtitle="Weights, comparison groups and prior strengths used for this shortlist" defaultOpen={false}>
                      <MethodologyPanel result={result} />
                    </Collapsible>
                  </>
                )}
              </>
            )}

            {tab === 'compare' && options && (
              <CompareView shortlist={shortlist} scope={effectiveScope} roles={options.roles.filter(r => !(r.limited_overs_only && !['T20', 'T20I', 'ODI', 'ODM'].includes(effectiveScope.format)))}
                defaultRole={result?.role?.key || form.role}
                onRemove={id => setShortlist(old => { const n = { ...old }; delete n[id]; return n; })}
                onClear={() => setShortlist({})} onReport={openReport} />
            )}

            {tab === 'report' && (
              <PlayerReport playerId={reportPlayer} scope={effectiveScope} roleKey={reportRole}
                roles={options.roles.filter(r => !(r.limited_overs_only && !['T20', 'T20I', 'ODI', 'ODM'].includes(effectiveScope.format)))}
                onRoleChange={setReportRole} onShortlist={toggleShortlist} shortlisted={Boolean(shortlist[reportPlayer])} />
            )}

            {tab === 'explorer' && <CohortExplorer embedded />}
          </section>
        </div>
      )}
    </div>
  );
}
