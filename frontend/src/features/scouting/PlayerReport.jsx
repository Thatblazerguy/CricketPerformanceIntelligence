/**
 * Step 6: evidence-backed scouting report. Sections follow the recruitment brief:
 * overview, role, career, recent form, strengths/weaknesses, phases, matchups,
 * consistency, format suitability, reliability, recruitment suitability, evidence.
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { scoutFormats, scoutReport } from '../../services/api';
import { Callout, ErrorState, LoadingSpinner, MatchLink, Panel } from '../../components/ui';
import { ColumnChart, MultiSeriesLine, PALETTE } from '../../components/charts';
import { DASH, KV, MiniTable, PctBar, TierBadge, fmt, fmtInt, isNum } from './scoutUi';

const metricCell = (m, d = 1) => (m ? (
  <span className="inline-flex flex-col items-end">
    <span className="num text-slate-100">{fmt(m.value, d)}{isNum(m.adjusted) && m.adjusted !== m.value && <span className="ml-1 text-3xs text-slate-500">({fmt(m.adjusted, d)})</span>}</span>
    {isNum(m.percentile) && <PctBar value={m.percentile} />}
  </span>
) : DASH);

const matchRef = r => (
  <span>
    <MatchLink id={r.match_id} className="text-slate-200 hover:text-accent-soft">{r.date}</MatchLink>
    <span className="text-slate-500"> v {r.opponent || 'Unknown'}{r.venue ? ` · ${r.venue}` : ''}</span>
    {r.tournament && <div className="text-3xs text-slate-600">{r.tournament}</div>}
  </span>
);

function N({ n, children }) {
  return <span className="text-3xs text-slate-500">{children || `n=${fmtInt(n)}`}</span>;
}

function BattingSections({ bat, format }) {
  const s = bat.summary;
  return (
    <>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel eyebrow="3 · Career summary" title="Batting record in scope" subtitle={`${s.first_date || ''} → ${s.last_date || ''}. Shrunk value in brackets; bar = percentile in comparison group.`}>
          <KV rows={[
            ['Matches · innings · not outs', `${s.matches} · ${s.innings} · ${s.not_outs}`],
            ['Runs · balls', `${fmtInt(s.runs)} · ${fmtInt(s.balls)}`],
            ['50s · 100s · highest', <>{s.fifties} · {s.hundreds} · <MatchLink id={s.highest_match_id}>{s.highest ?? DASH}</MatchLink></>],
            ['Average', metricCell(s.average)],
            ['Strike rate', metricCell(s.strike_rate)],
            ['SR index (100 = environment)', metricCell(s.sr_index)],
            ['Balls per dismissal', metricCell(s.balls_per_dismissal)],
          ]} />
        </Panel>
        <Panel eyebrow="4 · Recent form" title={`Last ${bat.recent_form.recent.innings} innings vs whole scope`}>
          <MiniTable columns={[
            { key: 'k', label: '' }, { key: 'avg', label: 'Avg', align: 'right' }, { key: 'sr', label: 'SR', align: 'right' },
            { key: 'bnd', label: 'Bdry %', align: 'right' }, { key: 'dot', label: 'Dot %', align: 'right' }]}
            rows={[['Recent', bat.recent_form.recent], ['Career', bat.recent_form.career]].map(([k, r]) => ({ key: k, k, avg: fmt(r.average), sr: fmt(r.strike_rate), bnd: fmt(r.boundary_pct), dot: fmt(r.dot_pct) }))} />
          <div className="mt-3 max-h-48 overflow-y-auto">
            <MiniTable columns={[{ key: 'm', label: 'Match', render: r => matchRef(r) }, { key: 'position', label: '#', align: 'right' },
              { key: 'score', label: 'Score', align: 'right', render: r => `${r.runs} (${r.balls})` }, { key: 'dismissal', label: 'How out' }]}
              rows={bat.recent_form.log} />
          </div>
        </Panel>
      </div>

      {bat.phases?.length > 0 && (
        <Panel eyebrow="6 · Phase-wise performance" title="By match phase" subtitle="Percentiles vs the same comparison group.">
          <MiniTable columns={[{ key: 'phase', label: 'Phase' }, { key: 'balls', label: 'Balls', align: 'right' },
            { key: 'share_of_balls', label: '% of balls', align: 'right' }, { key: 'runs', label: 'Runs', align: 'right' },
            { key: 'sr', label: 'Strike rate', align: 'right', render: r => metricCell(r.strike_rate) },
            { key: 'avg', label: 'Average', align: 'right', render: r => metricCell(r.average) },
            { key: 'dot_pct', label: 'Dot %', align: 'right' }, { key: 'boundary_pct', label: 'Bdry %', align: 'right' }]} rows={bat.phases} />
        </Panel>
      )}

      <div className="grid gap-4 2xl:grid-cols-2">
        <Panel eyebrow="7 · Matchups" title="Pace vs spin" subtitle={`${bat.matchups.classified_share ?? DASH}% of balls faced came from bowlers with a sourced classification (${fmtInt(bat.matchups.unclassified_balls)} unclassified balls excluded).`}>
          <MiniTable columns={[{ key: 'k', label: '' }, { key: 'balls', label: 'Balls', align: 'right' }, { key: 'runs', label: 'Runs', align: 'right' },
            { key: 'dismissals', label: 'Outs', align: 'right' }, { key: 'sr', label: 'SR', align: 'right', render: r => metricCell(r.strike_rate) },
            { key: 'avg', label: 'Avg', align: 'right', render: r => metricCell(r.average) }, { key: 'dot_pct', label: 'Dot %', align: 'right' }]}
            rows={[{ key: 'pace', k: 'Pace', ...bat.matchups.pace }, { key: 'spin', k: 'Spin', ...bat.matchups.spin }]} />
          <p className="mt-2 text-3xs text-slate-600">{bat.matchups.handedness}</p>
        </Panel>
        <Panel title="By detailed bowling style" subtitle="Sourced styles only; intervals show strike-rate uncertainty.">
          <MiniTable columns={[{ key: 'style', label: 'Style', render: r => <span>{r.style}{r.sample_warning && <span className="ml-1 text-3xs text-warn">limited</span>}</span> },
            { key: 'balls', label: 'Balls', align: 'right' }, { key: 'strike_rate', label: 'SR', align: 'right' },
            { key: 'ci', label: '95% CI', align: 'right', render: r => (r.sr_ci ? `${fmt(r.sr_ci[0], 0)}–${fmt(r.sr_ci[1], 0)}` : DASH) },
            { key: 'average', label: 'Avg', align: 'right' }, { key: 'dismissals', label: 'Outs', align: 'right' }, { key: 'dot_pct', label: 'Dot %', align: 'right' }]}
            rows={bat.matchups.by_style} empty="No deliveries from bowlers with a sourced detailed style." />
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel eyebrow="9 · Consistency" title="Innings distribution" subtitle={`Median ${fmt(bat.consistency.median)} · mean ${fmt(bat.consistency.mean)} · SD ${fmt(bat.consistency.sd)} · IQR ${fmt(bat.consistency.p25)}–${fmt(bat.consistency.p75)}`}>
          <KV rows={[
            [`Significant innings (${bat.consistency.significant_threshold}+)`, `${fmt(bat.consistency.significant_pct)}%`],
            [`Failures (out < ${bat.consistency.poor_threshold})`, `${fmt(bat.consistency.poor_pct)}%`],
            ['Early dismissal (≤10 balls)', metricCell(bat.consistency.early_out_pct)],
            ['Coefficient of variation', fmt(bat.consistency.cv, 2)],
          ]} />
          <ColumnChart className="mt-3 !border-0 !p-0 !shadow-none" height={150} data={bat.consistency.distribution.map(d => ({ label: d.bucket, value: d.innings }))} formatter={v => `${v} inns`} barLabel="Innings" />
        </Panel>
        <MultiSeriesLine title={`Rolling ${bat.consistency.rolling_window || ''}-innings form`} subtitle="Runs per innings and strike rate over a trailing window; only shown where sample permits."
          series={bat.consistency.rolling_window ? [
            { name: 'Runs / innings', color: PALETTE[0], points: bat.consistency.rolling.map(r => ({ x: r.index, y: r.runs_per_innings })) },
            { name: 'Strike rate ÷ 4', color: PALETTE[1], points: bat.consistency.rolling.map(r => ({ x: r.index, y: r.strike_rate != null ? r.strike_rate / 4 : null })) },
          ] : []} xLabel="Innings #" emptyText="Fewer than 10 innings: rolling form not shown." />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Batting position" subtitle={`Primary: ${bat.positions.primary}`}>
          <MiniTable columns={[{ key: 'positions', label: '#' }, { key: 'innings', label: 'Inns', align: 'right' }, { key: 'average', label: 'Avg', align: 'right' }, { key: 'strike_rate', label: 'SR', align: 'right' }]} rows={bat.positions.by_position} />
        </Panel>
        <Panel title="Match situation" subtitle={format === 'Test' || format === 'MDM' ? 'Chase splits apply to limited-overs formats only.' : 'Chasing outcomes from match results.'}>
          <MiniTable columns={[{ key: 'situation', label: '' }, { key: 'innings', label: 'Inns', align: 'right' }, { key: 'average', label: 'Avg', align: 'right' }, { key: 'strike_rate', label: 'SR', align: 'right' },
            { key: 'not_out_pct', label: 'NO %', align: 'right' }]} rows={bat.situations} empty="Not applicable in this format." />
        </Panel>
        <Panel title="Dismissals & scoring">
          <MiniTable columns={[{ key: 'type', label: 'Dismissal' }, { key: 'count', label: 'n', align: 'right' }, { key: 'share', label: '%', align: 'right' }]} rows={bat.dismissals} />
          <div className="mt-2"><KV rows={[['Runs from 4s · 6s · running', `${fmt(bat.scoring.from_fours_pct)}% · ${fmt(bat.scoring.from_sixes_pct)}% · ${fmt(bat.scoring.from_running_pct)}%`],
            ['Strike rotation %', metricCell(bat.scoring.rotation_pct)]]} /></div>
        </Panel>
      </div>
    </>
  );
}

function BowlingSections({ bowl }) {
  const s = bowl.summary;
  return (
    <>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel eyebrow="3 · Career summary" title="Bowling record in scope" subtitle="Shrunk value in brackets; bar = percentile in comparison group.">
          <KV rows={[
            ['Matches · innings · overs', `${s.matches} · ${s.innings} · ${s.overs}`],
            ['Wickets · runs', `${s.wickets} · ${fmtInt(s.runs)}`],
            ['Economy', metricCell(s.economy, 2)], ['Economy index (100 = environment)', metricCell(s.econ_index)],
            ['Average', metricCell(s.average)], ['Balls per wicket', metricCell(s.strike_rate)],
            ['Dot %', metricCell(s.dot_pct)], ['Boundary % conceded', metricCell(s.boundary_pct_conceded)],
            ['Wides + no-balls per over', fmt(s.wides_noballs_per_over, 2)], [`Hauls (${s.haul_threshold}+ wkts)`, s.hauls],
          ]} />
        </Panel>
        <Panel eyebrow="4 · Recent form" title="Last 10 bowling innings vs scope">
          <MiniTable columns={[{ key: 'k', label: '' }, { key: 'economy', label: 'Econ', align: 'right' }, { key: 'average', label: 'Avg', align: 'right' }, { key: 'strike_rate', label: 'SR', align: 'right' }, { key: 'dot_pct', label: 'Dot %', align: 'right' }]}
            rows={[{ key: 'r', k: 'Recent', ...bowl.recent_form.recent }, { key: 'c', k: 'Career', ...bowl.recent_form.career }]} />
          <div className="mt-3 max-h-48 overflow-y-auto">
            <MiniTable columns={[{ key: 'm', label: 'Match', render: r => matchRef(r) }, { key: 'fig', label: 'Figures', align: 'right', render: r => `${r.overs}-${r.runs}-${r.wickets}` }]} rows={bowl.recent_form.log} />
          </div>
        </Panel>
      </div>
      {bowl.phases?.length > 0 && (
        <Panel eyebrow="6 · Phase-wise performance" title="Bowling by phase">
          <MiniTable columns={[{ key: 'phase', label: 'Phase' }, { key: 'legal_balls', label: 'Balls', align: 'right' }, { key: 'share_of_balls', label: '% of balls', align: 'right' },
            { key: 'wickets', label: 'Wkts', align: 'right' }, { key: 'economy', label: 'Economy', align: 'right', render: r => metricCell(r.economy, 2) },
            { key: 'bpw', label: 'Balls/wkt', align: 'right', render: r => metricCell(r.balls_per_wicket) }, { key: 'dot_pct', label: 'Dot %', align: 'right' }, { key: 'boundary_pct', label: 'Bdry %', align: 'right' }]} rows={bowl.phases} />
        </Panel>
      )}
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel eyebrow="9 · Consistency" title="Spell consistency" subtitle={`${bowl.consistency.spells} spells of ≥${bowl.consistency.spell_min_balls} legal balls; par economy ${fmt(bowl.consistency.par_economy, 2)}`}>
          <KV rows={[['Spell economy median · SD', `${fmt(bowl.consistency.economy_median, 2)} · ${fmt(bowl.consistency.economy_sd, 2)}`],
            ['Economical spells', metricCell(bowl.consistency.good_spell_pct)], ['Wicketless spells', metricCell(bowl.consistency.wicketless_pct)],
            ['Haul innings', metricCell(bowl.consistency.haul_pct)]]} />
          <MiniTable columns={[{ key: 'wickets', label: 'Wkts in innings' }, { key: 'innings', label: 'Innings', align: 'right' }]} rows={bowl.consistency.wickets_distribution} />
        </Panel>
        <Panel title="Dismissal types & situations">
          <MiniTable columns={[{ key: 'type', label: 'Type' }, { key: 'count', label: 'n', align: 'right' }, { key: 'share', label: '%', align: 'right' }]} rows={bowl.dismissals} />
          <div className="mt-2"><MiniTable columns={[{ key: 'situation', label: '' }, { key: 'innings', label: 'Inns', align: 'right' }, { key: 'economy', label: 'Econ', align: 'right' }, { key: 'wickets', label: 'Wkts', align: 'right' }]} rows={bowl.situations} empty="Not applicable in this format." /></div>
          <p className="mt-2 text-3xs text-slate-600">{bowl.matchups.handedness}</p>
        </Panel>
        <MultiSeriesLine title={`Rolling ${bowl.consistency.rolling_window || ''}-innings economy`} series={bowl.consistency.rolling_window ? [
          { name: 'Economy', color: PALETTE[2], points: bowl.consistency.rolling.map(r => ({ x: r.index, y: r.economy })) },
        ] : []} xLabel="Innings #" emptyText="Fewer than 10 innings: rolling form not shown." />
      </div>
    </>
  );
}

function FormatSuitability({ playerId, gender }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    setData(null);
    scoutFormats(playerId, gender).then(d => live && setData(d)).catch(e => live && setError(e.message));
    return () => { live = false; };
  }, [playerId, gender]);
  return (
    <Panel eyebrow="10 · Format suitability" title="Record in each format" subtitle={data?.note || 'Each format against its own regulars.'}>
      {error ? <p className="text-xs text-neg-soft">{error}</p> : !data ? <LoadingSpinner compact message="Comparing across formats…" /> : (
        <MiniTable columns={[{ key: 'format', label: 'Format' },
          { key: 'bi', label: 'Bat inns', align: 'right', render: r => r.batting?.innings ?? DASH },
          { key: 'ba', label: 'Avg (pct)', align: 'right', render: r => r.batting ? `${fmt(r.batting.average)} (${fmt(r.batting.average_pct, 0)})` : DASH },
          { key: 'bs', label: 'SR idx (pct)', align: 'right', render: r => r.batting ? `${fmt(r.batting.sr_index)} (${fmt(r.batting.sr_index_pct, 0)})` : DASH },
          { key: 'wi', label: 'Bowl inns', align: 'right', render: r => r.bowling?.innings ?? DASH },
          { key: 'we', label: 'Econ idx (pct)', align: 'right', render: r => r.bowling ? `${fmt(r.bowling.econ_index)} (${fmt(r.bowling.econ_index_pct, 0)})` : DASH },
          { key: 'ws', label: 'Balls/wkt (pct)', align: 'right', render: r => r.bowling ? `${fmt(r.bowling.bowling_strike_rate)} (${fmt(r.bowling.strike_rate_pct, 0)})` : DASH },
          { key: 'reg', label: 'Regular?', render: r => [r.batting?.regular && 'bat', r.bowling?.regular && 'bowl'].filter(Boolean).join(' · ') || 'below baseline' }]}
          rows={data.formats.map(f => ({ key: f.format, ...f }))} />
      )}
    </Panel>
  );
}

export default function PlayerReport({ playerId, scope, roleKey, roles, onRoleChange, onShortlist, shortlisted }) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!playerId) return undefined;
    let live = true;
    setLoading(true); setError('');
    scoutReport(playerId, { ...scope, role: roleKey || undefined })
      .then(d => live && setReport(d)).catch(e => live && setError(e.message)).finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [playerId, roleKey, JSON.stringify(scope)]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!playerId) return <p className="py-10 text-center text-xs text-slate-500">Open a report from the ranking or the comparison.</p>;
  if (loading) return <LoadingSpinner message="Building scouting report…" />;
  if (error) return <ErrorState message={error} />;
  if (!report) return null;
  if (!report.available) return <Callout tone="warn">{report.player_name || 'This player'}: {report.message} ({report.scope})</Callout>;

  const o = report.overview;
  const rec = report.recruitment;
  return (
    <div className="space-y-4">
      <div className="panel flex flex-wrap items-start justify-between gap-4 p-4">
        <div className="min-w-0">
          <div className="eyebrow mb-1">1 · Player overview · {report.scope}</div>
          <h2 className="text-lg font-semibold text-white"><Link to={`/players/${o.player_id}`} className="hover:text-accent-soft">{o.player_name}</Link></h2>
          <p className="mt-1 text-xs text-slate-400">
            {[o.nationality || 'Nationality unresolved', o.bowling_style ? `bowls ${o.bowling_style}` : o.bowling_type ? `bowls ${o.bowling_type.toLowerCase()}` : 'bowling style not sourced',
              o.batting_hand ? `${o.batting_hand} bat` : 'batting hand not sourced', isNum(o.age) ? `age ${o.age}` : 'DOB not verified',
              o.keeper_evidence?.stumpings ? `${o.keeper_evidence.stumpings} stumpings (keeper)` : null].filter(Boolean).join(' · ')}
          </p>
          <p className="mt-2 text-xs text-slate-300"><span className="text-slate-500">2 · Playing role:</span> observed {report.role.observed_role} ({report.role.observed_basis}){report.role.primary_position ? ` · bats ${report.role.primary_position}` : ''}{report.role.metadata_role ? ` · metadata: ${report.role.metadata_role}` : ''}{report.role.allrounder_type ? ` · ${report.role.allrounder_type}` : ''}</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="text-right">
            <div className="text-3xs uppercase tracking-wide text-slate-500">12 · {rec.role} suitability</div>
            <div className="num text-3xl font-semibold text-white">{fmt(rec.score)}</div>
            <div className="text-2xs text-slate-500">vs {fmtInt(rec.comparison_group)} in comparison group</div>
          </div>
          <TierBadge tier={report.reliability.tier} reliability={report.reliability.overall} />
          <div className="flex gap-2">
            <select className="h-8 border border-line-strong bg-surface-sunken px-3 text-xs text-slate-200" value={report.role.role_key} onChange={e => onRoleChange(e.target.value)} aria-label="Evaluate as role">
              {roles.map(r => <option key={r.key} value={r.key}>Evaluate as: {r.label}</option>)}
            </select>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => onShortlist({ identity: o })}>{shortlisted ? '★ Shortlisted' : '☆ Shortlist'}</button>
          </div>
        </div>
      </div>
      {rec.comparison_note && <Callout tone="warn">{rec.comparison_note}</Callout>}

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel eyebrow="5 · Statistical strengths & weaknesses" title="What the numbers say" subtitle="Generated only from metrics at or beyond the 75th / 25th percentile.">
          <div className="space-y-1.5 text-xs leading-relaxed">
            {report.strengths.map((s, i) => <p key={`s${i}`} className="text-slate-200"><span className="text-pos">+ </span>{s}</p>)}
            {!report.strengths.length && <p className="text-slate-500">No role metric reaches the 75th percentile.</p>}
            {report.weaknesses.map((s, i) => <p key={`w${i}`} className="text-slate-200"><span className="text-neg">− </span>{s}</p>)}
            {!report.weaknesses.length && <p className="text-slate-500">No role metric falls to the 25th percentile.</p>}
          </div>
        </Panel>
        <Panel eyebrow="12 · Recruitment suitability" title="Fit across role models" subtitle="The same record scored under each role’s metrics and comparison group.">
          <MiniTable columns={[{ key: 'label', label: 'Role model', render: r => <span className={r.eligible ? 'text-slate-200' : 'text-slate-500'}>{r.label}{!r.eligible && <div className="text-3xs text-slate-600">{r.eligibility_note}</div>}</span> },
            { key: 'score', label: 'Score', align: 'right', render: r => fmt(r.score) }, { key: 'tier', label: 'Evidence', render: r => <TierBadge tier={r.tier} reliability={r.reliability} /> },
            { key: 'comparison_group', label: 'Group', align: 'right' }]} rows={rec.role_fit.map(r => ({ key: r.role, ...r }))} />
        </Panel>
      </div>

      {report.batting && <BattingSections bat={report.batting} format={scope.format} />}
      {report.bowling && <BowlingSections bowl={report.bowling} />}

      <FormatSuitability playerId={o.player_id} gender={scope.gender} />

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel eyebrow="11 · Sample reliability" title="Evidence behind each role metric" subtitle={report.reliability.explanation}>
          <MiniTable columns={[{ key: 'metric', label: 'Metric' }, { key: 'value', label: 'Observed', align: 'right', render: r => fmt(r.value) },
            { key: 'adjusted', label: 'Shrunk', align: 'right', render: r => fmt(r.adjusted) }, { key: 'ci', label: '95% CI', align: 'right', render: r => (r.ci ? `${fmt(r.ci[0])}–${fmt(r.ci[1])}` : DASH) },
            { key: 'n', label: 'Sample', align: 'right', render: r => `${fmtInt(r.n)} ${r.unit || ''}` }, { key: 'reliability', label: 'Rel.', align: 'right', render: r => fmt(r.reliability, 2) }]}
            rows={report.reliability.metrics.map((m, i) => ({ key: i, ...m }))} />
          {report.reliability.limited_matchups.length > 0 && (
            <div className="mt-2 space-y-0.5 text-2xs text-warn-soft">{report.reliability.limited_matchups.map((x, i) => <p key={i}>⚠ {x}</p>)}</div>
          )}
        </Panel>
        <Panel eyebrow="13 · Supporting match evidence" title={report.batting ? 'Highest innings' : 'Best bowling figures'}>
          {report.batting && <MiniTable columns={[{ key: 'm', label: 'Match', render: r => matchRef(r) }, { key: 'position', label: '#', align: 'right' },
            { key: 's', label: 'Score', align: 'right', render: r => `${r.runs}${r.not_out ? '*' : ''} (${r.balls})` }, { key: 'b', label: '4s/6s', align: 'right', render: r => `${r.fours}/${r.sixes}` },
            { key: 'res', label: 'Result', render: r => (r.won == null ? 'no result' : r.won ? 'won' : 'lost') + (r.chase ? ' · chase' : '') }]} rows={report.batting.evidence.top_innings} />}
          {report.bowling && <div className={report.batting ? 'mt-3' : ''}><MiniTable columns={[{ key: 'm', label: 'Match', render: r => matchRef(r) }, { key: 'f', label: 'Figures', align: 'right', render: r => `${r.wickets}/${r.runs} (${r.overs})` }]} rows={report.bowling.evidence.best_figures} /></div>}
        </Panel>
      </div>

      {(report.batting?.seasons?.length > 1 || report.bowling?.seasons?.length > 1) && (
        <Panel title="Season by season" subtitle="Trajectory within the selected scope.">
          {report.batting && <MiniTable columns={[{ key: 'season', label: 'Season' }, { key: 'innings', label: 'Inns', align: 'right' }, { key: 'runs', label: 'Runs', align: 'right' },
            { key: 'average', label: 'Avg', align: 'right' }, { key: 'strike_rate', label: 'SR', align: 'right' }, { key: 'boundary_pct', label: 'Bdry %', align: 'right' }]} rows={report.batting.seasons.map(s => ({ key: s.season, ...s }))} />}
          {report.bowling && <div className="mt-3"><MiniTable columns={[{ key: 'season', label: 'Season' }, { key: 'innings', label: 'Inns', align: 'right' }, { key: 'wickets', label: 'Wkts', align: 'right' },
            { key: 'economy', label: 'Econ', align: 'right' }, { key: 'average', label: 'Avg', align: 'right' }, { key: 'strike_rate', label: 'SR', align: 'right' }]} rows={report.bowling.seasons.map(s => ({ key: s.season, ...s }))} /></div>}
        </Panel>
      )}
      {((report.batting?.conditions?.length || 0) > 1 || (report.bowling?.conditions?.length || 0) > 1) && (
        <Panel title="Conditions (by venue country)" subtitle="Pitch-type data is not in the source feed; venue country is the only condition proxy available.">
          <div className="grid gap-4 lg:grid-cols-2">
            {report.batting && <MiniTable columns={[{ key: 'country', label: 'Country' }, { key: 'innings', label: 'Inns', align: 'right' }, { key: 'average', label: 'Avg', align: 'right' }, { key: 'strike_rate', label: 'SR', align: 'right' }]} rows={report.batting.conditions.map(c => ({ key: c.country, ...c }))} />}
            {report.bowling && <MiniTable columns={[{ key: 'country', label: 'Country' }, { key: 'innings', label: 'Inns', align: 'right' }, { key: 'economy', label: 'Econ', align: 'right' }, { key: 'wickets', label: 'Wkts', align: 'right' }]} rows={report.bowling.conditions.map(c => ({ key: c.country, ...c }))} />}
          </div>
        </Panel>
      )}
      <p className="text-3xs text-slate-600">Missing values are shown as {DASH} and are never treated as zero.</p>
    </div>
  );
}
