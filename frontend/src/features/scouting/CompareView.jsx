/**
 * Step 5: side-by-side comparison of shortlisted candidates under one role model.
 * Radar axes are percentiles; every axis is accompanied by the actual values.
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { scoutCompare } from '../../services/api';
import { EmptyState, ErrorState, LoadingSpinner, Panel } from '../../components/ui';
import { PALETTE, RadarChart } from '../../components/charts';
import { DASH, PctBar, TierBadge, downloadCsv, fmt, fmtInt, metricValue } from './scoutUi';

const PHASE = { pp: 'Powerplay', mid: 'Middle', death: 'Death' };

function Row({ label, values, hint }) {
  return (
    <tr className="border-b border-line-soft last:border-0">
      <td className="whitespace-nowrap px-2 py-1.5 text-slate-400">{label}{hint && <div className="text-3xs text-slate-600">{hint}</div>}</td>
      {values.map((v, i) => <td key={i} className="num px-2 py-1.5 text-right text-slate-200">{v ?? DASH}</td>)}
    </tr>
  );
}

function Section({ title, children, players }) {
  return (
    <>
      <tr className="bg-surface-raised/60"><td colSpan={players.length + 1} className="px-2 py-1 text-3xs font-semibold text-slate-500">{title}</td></tr>
      {children}
    </>
  );
}

export default function CompareView({ shortlist, scope, roles, defaultRole, onRemove, onReport, onClear }) {
  const ids = Object.keys(shortlist);
  const [role, setRole] = useState(defaultRole);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => setRole(defaultRole), [defaultRole]);

  useEffect(() => {
    if (!ids.length) { setData(null); return; }
    let live = true;
    setLoading(true); setError('');
    scoutCompare({ ...scope, role, player_ids: ids.slice(0, 8) })
      .then(d => live && setData(d)).catch(e => live && setError(e.message)).finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [ids.join(','), role, JSON.stringify(scope)]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!ids.length) return <EmptyState icon="compare" message="Your shortlist is empty." hint="Star candidates in the ranking to compare them side by side. The shortlist is kept in this browser." />;

  const players = (data?.players || []).filter(p => p.available);
  const missing = (data?.players || []).filter(p => !p.available);
  const metrics = players[0]?.metrics || [];
  const hasBat = players.some(p => p.batting);
  const hasBowl = players.some(p => p.bowling);

  function exportCsv() {
    const header = ['Metric', ...players.map(p => p.identity.player_name)];
    const rows = [header,
      ['Scope', ...players.map(() => data.scope)], ['Role model', ...players.map(() => data.role.label)],
      ['Suitability score', ...players.map(p => p.score)], ['Reliability', ...players.map(p => p.reliability)], ['Evidence tier', ...players.map(p => p.tier)],
      ...metrics.flatMap(m => [
        [`${m.label} (value)`, ...players.map(p => p.metrics.find(x => x.metric === m.metric)?.value)],
        [`${m.label} (percentile)`, ...players.map(p => p.metrics.find(x => x.metric === m.metric)?.percentile)],
        [`${m.label} (sample)`, ...players.map(p => p.metrics.find(x => x.metric === m.metric)?.n)],
      ]),
    ];
    if (hasBat) rows.push(
      ['Batting innings', ...players.map(p => p.batting?.career.innings)], ['Batting runs', ...players.map(p => p.batting?.career.runs)],
      ['Batting average', ...players.map(p => p.batting?.career.average)], ['Strike rate', ...players.map(p => p.batting?.career.strike_rate)],
      ['Last 10 inns SR', ...players.map(p => p.batting?.recent.strike_rate)], ['Median runs', ...players.map(p => p.batting?.consistency.median)],
    );
    if (hasBowl) rows.push(
      ['Bowling innings', ...players.map(p => p.bowling?.career.innings)], ['Wickets', ...players.map(p => p.bowling?.career.wickets)],
      ['Economy', ...players.map(p => p.bowling?.career.economy)], ['Last 10 inns economy', ...players.map(p => p.bowling?.recent.economy)],
    );
    downloadCsv(`cpi-shortlist-${data.role.key}-${scope.format}.csv`, rows);
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {Object.values(shortlist).map((p, i) => (
          <span key={p.player_id} className="chip"><span className="dot" style={{ background: PALETTE[i % PALETTE.length] }} />{p.player_name}
            <button type="button" className="ml-1 text-slate-500 hover:text-neg-soft" onClick={() => onRemove(p.player_id)} aria-label={`Remove ${p.player_name}`}>×</button></span>
        ))}
        <select className="ml-auto h-8 border border-line-strong bg-surface-sunken px-3 text-xs text-slate-200" value={role} onChange={e => setRole(e.target.value)} aria-label="Comparison role model">
          {roles.map(r => <option key={r.key} value={r.key}>Compare as: {r.label}</option>)}
        </select>
        <button type="button" className="btn btn-secondary btn-sm" disabled={!players.length} onClick={exportCsv}>Export CSV</button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onClear}>Clear</button>
      </div>
      {ids.length > 8 && <p className="text-2xs text-warn-soft">Only the first 8 shortlisted players are compared.</p>}
      {loading && <LoadingSpinner message="Comparing candidates…" compact />}
      {error && <ErrorState message={error} />}
      {missing.length > 0 && <p className="text-2xs text-slate-500">No innings in this scope for: {missing.map(p => p.identity.player_name).join(', ')}.</p>}
      {data && players.length > 0 && (
        <>
          <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_380px]">
            <Panel title="Side-by-side" subtitle={`${data.scope} · ${data.role.label} model · percentiles vs ${Object.entries(data.comparison_group).map(([d, n]) => `${n} ${d === 'bat' ? 'batters' : 'bowlers'}`).join(' / ')}`} bodyClassName="p-0">
              <div className="overflow-x-auto">
                <table className="min-w-full text-xs">
                  <thead>
                    <tr className="border-b border-line text-2xs text-slate-500">
                      <th className="px-2 py-2 text-left font-medium">Metric</th>
                      {players.map((p, i) => (
                        <th key={p.player_id} className="px-2 py-2 text-right font-medium">
                          <Link to={`/players/${p.player_id}`} className="text-slate-100 hover:text-accent-soft" style={{ borderBottom: `2px solid ${PALETTE[i % PALETTE.length]}` }}>{p.identity.player_name}</Link>
                          <div className="mt-1 flex justify-end"><TierBadge tier={p.tier} reliability={p.reliability} /></div>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    <Row label="Suitability score" values={players.map(p => <b className="text-white">{fmt(p.score)}</b>)} />
                    {players[0].allrounder_type && <Row label="All-rounder type" values={players.map(p => <span className="text-2xs">{p.allrounder_type}</span>)} />}
                    <Section title="Role metrics · value · percentile · sample" players={players}>
                      {metrics.map(m => (
                        <tr key={m.metric} className="border-b border-line-soft">
                          <td className="whitespace-nowrap px-2 py-1.5 text-slate-400">{m.label}<div className="text-3xs text-slate-600">{m.group} · {Math.round(m.weight * 100)}%</div></td>
                          {players.map(p => {
                            const x = p.metrics.find(y => y.metric === m.metric);
                            return <td key={p.player_id} className="px-2 py-1.5 text-right"><div className="num text-slate-100">{metricValue(m.metric, x?.value)} <span className="text-3xs text-slate-600">n={fmtInt(x?.n)}</span></div><div className="flex justify-end"><PctBar value={x?.percentile} /></div></td>;
                          })}
                        </tr>
                      ))}
                    </Section>
                    {hasBat && (
                      <Section title="Batting · career vs last 10 innings" players={players}>
                        <Row label="Innings · runs" values={players.map(p => p.batting ? `${p.batting.career.innings} · ${fmtInt(p.batting.career.runs)}` : null)} />
                        <Row label="Average (career / last 10)" values={players.map(p => p.batting ? `${fmt(p.batting.career.average)} / ${fmt(p.batting.recent.average)}` : null)} />
                        <Row label="Strike rate (career / last 10)" values={players.map(p => p.batting ? `${fmt(p.batting.career.strike_rate)} / ${fmt(p.batting.recent.strike_rate)}` : null)} />
                        <Row label="Boundary % · dot %" values={players.map(p => p.batting ? `${fmt(p.batting.career.boundary_pct)} · ${fmt(p.batting.career.dot_pct)}` : null)} />
                        <Row label="Primary position" values={players.map(p => p.batting?.primary_position)} />
                        {players.some(p => p.batting?.phases) && Object.keys(PHASE).map(ph => (
                          <Row key={ph} label={`${PHASE[ph]} SR`} hint="balls in phase" values={players.map(p => p.batting?.phases ? `${fmt(p.batting.phases[ph].strike_rate)} (${fmtInt(p.batting.phases[ph].balls)})` : null)} />
                        ))}
                        <Row label="vs pace SR · avg" hint="classified bowlers only" values={players.map(p => p.batting ? `${fmt(p.batting.pace.strike_rate)} · ${fmt(p.batting.pace.average)} (${fmtInt(p.batting.pace.balls)}b)` : null)} />
                        <Row label="vs spin SR · avg" values={players.map(p => p.batting ? `${fmt(p.batting.spin.strike_rate)} · ${fmt(p.batting.spin.average)} (${fmtInt(p.batting.spin.balls)}b)` : null)} />
                        <Row label="Median · SD runs per innings" values={players.map(p => p.batting ? `${fmt(p.batting.consistency.median)} · ${fmt(p.batting.consistency.sd)}` : null)} />
                        <Row label="Significant / failure innings %" values={players.map(p => p.batting ? `${fmt(p.batting.consistency.significant_pct)} / ${fmt(p.batting.consistency.poor_pct)}` : null)} />
                      </Section>
                    )}
                    {hasBowl && (
                      <Section title="Bowling · career vs last 10 innings" players={players}>
                        <Row label="Innings · wickets" values={players.map(p => p.bowling ? `${p.bowling.career.innings} · ${p.bowling.career.wickets}` : null)} />
                        <Row label="Economy (career / last 10)" values={players.map(p => p.bowling ? `${fmt(p.bowling.career.economy, 2)} / ${fmt(p.bowling.recent.economy, 2)}` : null)} />
                        <Row label="Average · strike rate" values={players.map(p => p.bowling ? `${fmt(p.bowling.career.average)} · ${fmt(p.bowling.career.strike_rate)}` : null)} />
                        <Row label="Dot %" values={players.map(p => p.bowling ? fmt(p.bowling.career.dot_pct) : null)} />
                        {players.some(p => p.bowling?.phases) && Object.keys(PHASE).map(ph => (
                          <Row key={ph} label={`${PHASE[ph]} economy`} hint="balls in phase" values={players.map(p => p.bowling?.phases ? `${fmt(p.bowling.phases[ph].economy, 2)} (${fmtInt(p.bowling.phases[ph].balls)})` : null)} />
                        ))}
                        <Row label="Spell economy median · SD" values={players.map(p => p.bowling ? `${fmt(p.bowling.consistency.economy_median, 2)} · ${fmt(p.bowling.consistency.economy_sd, 2)}` : null)} />
                        <Row label="Economical / wicketless spells %" values={players.map(p => p.bowling ? `${fmt(p.bowling.consistency.good_spell_pct)} / ${fmt(p.bowling.consistency.wicketless_pct)}` : null)} />
                      </Section>
                    )}
                    <tr><td className="px-2 py-2" />{players.map(p => <td key={p.player_id} className="px-2 py-2 text-right"><button type="button" className="btn btn-secondary btn-xs" onClick={() => onReport({ identity: p.identity })}>Report</button></td>)}</tr>
                  </tbody>
                </table>
              </div>
            </Panel>
            <RadarChart scaled title="Role-metric percentiles"
              subtitle="Shrunk-value percentiles within the role comparison group; hover for actual values."
              metrics={metrics.map(m => ({ key: m.metric, label: m.label.replace(' (context-adjusted)', ' adj.').replace('Strike rate', 'SR') }))}
              series={players.map((p, i) => ({
                name: p.identity.player_name, color: PALETTE[i % PALETTE.length],
                values: Object.fromEntries(p.metrics.map(m => [m.metric, m.percentile])),
                display: Object.fromEntries(p.metrics.map(m => [m.metric, `${metricValue(m.metric, m.value)} · ${m.percentile != null ? `${Math.round(m.percentile)}th pct` : 'no evidence'} · n=${m.n}`])),
              }))}
              footnote="Axes need a value for every selected player; metrics without evidence for someone are omitted from the radar but remain in the table." />
          </div>
        </>
      )}
    </div>
  );
}
