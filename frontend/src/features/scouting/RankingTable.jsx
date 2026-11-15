/**
 * Step 3–4: ranked, explainable candidate list. Each row expands into the full
 * metric breakdown (observed value, shrunk value, interval, sample, percentile,
 * weight and contribution) so every score can be audited.
 */
import { Fragment, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Badge } from '../../components/ui';
import { DASH, PctBar, ScoreCell, TierBadge, fmt, fmtInt, isNum, metricValue, ordinal } from './scoutUi';

function MetricBreakdown({ cand }) {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
      <div className="overflow-x-auto">
        <table className="min-w-full text-2xs">
          <thead>
            <tr className="border-b border-line text-left text-slate-500">
              <th className="px-2 py-1 font-medium">Metric</th><th className="px-2 py-1 text-right font-medium">Observed</th>
              <th className="px-2 py-1 text-right font-medium" title="Shrunk towards the comparison-group mean in proportion to sample size">Shrunk</th>
              <th className="px-2 py-1 text-right font-medium">95% CI</th><th className="px-2 py-1 text-right font-medium">Sample</th>
              <th className="px-2 py-1 text-right font-medium" title="n / (n + m)">Rel.</th><th className="px-2 py-1 font-medium">Percentile</th>
              <th className="px-2 py-1 text-right font-medium">Group median</th><th className="px-2 py-1 text-right font-medium">Weight</th>
              <th className="px-2 py-1 text-right font-medium">Contrib.</th>
            </tr>
          </thead>
          <tbody>
            {cand.metrics.map(m => (
              <tr key={m.metric} className="border-b border-line-soft last:border-0">
                <td className="px-2 py-1 text-slate-300">{m.label}<div className="text-3xs text-slate-600">{m.group}{m.style ? ` · weaker: ${m.style}` : ''}</div></td>
                <td className="num px-2 py-1 text-right text-white">{metricValue(m.metric, m.value)}</td>
                <td className="num px-2 py-1 text-right text-slate-300">{metricValue(m.metric, m.adjusted)}</td>
                <td className="num px-2 py-1 text-right text-slate-500">{m.ci ? `${fmt(m.ci[0])}–${fmt(m.ci[1])}` : DASH}</td>
                <td className="num px-2 py-1 text-right text-slate-400">{fmtInt(m.n)} <span className="text-slate-600">{m.unit}</span></td>
                <td className="num px-2 py-1 text-right text-slate-400">{fmt(m.reliability, 2)}</td>
                <td className="px-2 py-1"><PctBar value={m.percentile} /></td>
                <td className="num px-2 py-1 text-right text-slate-500">{metricValue(m.metric, m.cohort_median)}</td>
                <td className="num px-2 py-1 text-right text-slate-400">{Math.round(m.weight * 100)}%</td>
                <td className="num px-2 py-1 text-right text-slate-300">{fmt(m.contribution)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="space-y-3 text-2xs leading-relaxed">
        <div>
          <div className="mb-1 font-semibold text-pos-soft">Strengths</div>
          {cand.strengths?.length ? cand.strengths.map((s, i) => <p key={i} className="text-slate-300">+ {s}</p>) : <p className="text-slate-500">No metric at or above the 75th percentile.</p>}
        </div>
        <div>
          <div className="mb-1 font-semibold text-neg-soft">Weaknesses</div>
          {cand.weaknesses?.length ? cand.weaknesses.map((s, i) => <p key={i} className="text-slate-300">− {s}</p>) : <p className="text-slate-500">No metric at or below the 25th percentile.</p>}
        </div>
        {cand.allrounder_type && <p className="text-slate-400">Classification: <b className="text-slate-200">{cand.allrounder_type}</b> · batting {fmt(cand.batting?.score)} / bowling {fmt(cand.bowling?.score)} · {cand.dual_matches} matches using both disciplines.</p>}
        <p className="text-slate-500">Score = weighted mean of available metric percentiles{isNum(cand.weight_coverage) && cand.weight_coverage < 1 ? ` (metrics with no sample omitted; ${Math.round(cand.weight_coverage * 100)}% of the weight had evidence)` : ''}.</p>
      </div>
    </div>
  );
}

export default function RankingTable({ result, shortlist, toggleShortlist, onReport }) {
  const [open, setOpen] = useState(null);
  const [sort, setSort] = useState({ key: 'rank', desc: false });
  const disc = Object.keys(result.weights)[0];
  const keyMetrics = useMemo(() => {
    const all = Object.values(result.weights).flat();
    return [...all].sort((a, b) => b.weight - a.weight).slice(0, 5);
  }, [result.weights]);

  const rows = useMemo(() => {
    const value = (c, key) => {
      if (key === 'rank') return c.rank;
      if (key === 'score') return c.score;
      if (key === 'reliability') return c.reliability;
      if (key === 'innings') return c.sample?.batting?.innings ?? c.sample?.bowling?.innings;
      const m = c.metrics.find(x => x.metric === key);
      return m?.percentile;
    };
    const list = [...result.candidates];
    list.sort((a, b) => {
      const va = value(a, sort.key), vb = value(b, sort.key);
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      return sort.desc ? vb - va : va - vb;
    });
    return list;
  }, [result.candidates, sort]);

  const th = (key, label, align = 'right', title) => (
    <th key={key} title={title} className={`cursor-pointer select-none px-2 py-2 font-medium hover:text-slate-200 ${align === 'right' ? 'text-right' : 'text-left'}`}
      onClick={() => setSort(s => ({ key, desc: s.key === key ? !s.desc : key !== 'rank' }))}>
      {label}{sort.key === key ? (sort.desc ? ' ↓' : ' ↑') : ''}
    </th>
  );

  return (
    <div className="panel overflow-hidden">
      <div className="overflow-x-auto">
        <table className="min-w-full text-xs">
          <thead className="bg-surface-raised text-2xs text-slate-500">
            <tr>
              <th className="w-8 px-2 py-2" aria-label="Shortlist" />
              {th('rank', '#', 'left')}
              <th className="px-2 py-2 text-left font-medium">Player</th>
              {th('score', 'Suitability')}
              {th('reliability', 'Evidence', 'left', 'Reliability tier (share of the estimate from the player’s own data)')}
              {th('innings', 'Inns')}
              {keyMetrics.map(m => th(m.metric, m.label.replace(' (context-adjusted)', ' (adj.)'), 'left', `${m.group} · weight ${Math.round(m.weight * 100)}% · bar = percentile`))}
              <th className="px-2 py-2" />
            </tr>
          </thead>
          <tbody>
            {rows.map(c => {
              const id = c.identity.player_id;
              const sample = c.sample?.batting || c.sample?.bowling || {};
              const isOpen = open === id;
              return (
                <Fragment key={id}>
                  <tr className={`border-t border-line align-top hover:bg-surface-hover/30 ${isOpen ? 'bg-surface-hover/20' : ''}`}>
                    <td className="px-2 py-2">
                      <button type="button" aria-label={shortlist[id] ? 'Remove from shortlist' : 'Add to shortlist'} onClick={() => toggleShortlist(c)}
                        className={`text-base leading-none ${shortlist[id] ? 'text-warn' : 'text-slate-600 hover:text-slate-300'}`}>{shortlist[id] ? '★' : '☆'}</button>
                    </td>
                    <td className="num px-2 py-2 text-accent-soft">{c.rank}</td>
                    <td className="min-w-[11rem] px-2 py-2">
                      <Link to={`/players/${id}`} className="font-medium text-white hover:text-accent-soft">{c.identity.player_name}</Link>
                      <div className="mt-0.5 text-3xs text-slate-500">
                        {[c.identity.nationality, c.identity.bowling_style || (c.identity.bowling_type && `${c.identity.bowling_type}`), c.identity.primary_position && disc !== 'bowl' ? `bats ${c.identity.primary_position}` : null].filter(Boolean).join(' · ')}
                      </div>
                    </td>
                    <td className="px-2 py-2"><ScoreCell score={c.score} />{c.allrounder_type && <div className="mt-0.5 text-3xs text-slate-500">bat {fmt(c.batting?.score, 0)} · bowl {fmt(c.bowling?.score, 0)}</div>}</td>
                    <td className="px-2 py-2"><TierBadge tier={c.tier} reliability={c.reliability} /></td>
                    <td className="num px-2 py-2 text-right text-slate-300">{sample.innings ?? DASH}<div className="text-3xs text-slate-600">{sample.balls ? `${fmtInt(sample.balls)} b` : sample.legal_balls ? `${fmtInt(sample.legal_balls)} b` : ''}</div></td>
                    {keyMetrics.map(k => {
                      const m = c.metrics.find(x => x.metric === k.metric);
                      return (
                        <td key={k.metric} className="px-2 py-2">
                          <div className="num text-slate-200">{metricValue(k.metric, m?.value)}<span className="ml-1 text-3xs text-slate-600">{m?.n ? `n=${fmtInt(m.n)}` : ''}</span></div>
                          <PctBar value={m?.percentile} />
                        </td>
                      );
                    })}
                    <td className="whitespace-nowrap px-2 py-2 text-right">
                      <button type="button" className="btn btn-ghost btn-xs" onClick={() => setOpen(isOpen ? null : id)}>{isOpen ? 'Hide' : 'Why?'}</button>
                      <button type="button" className="btn btn-secondary btn-xs ml-1" onClick={() => onReport(c)}>Report</button>
                    </td>
                  </tr>
                  {isOpen && (
                    <tr className="border-t border-line-soft bg-surface-sunken/60">
                      <td colSpan={7 + keyMetrics.length} className="px-4 py-3"><MetricBreakdown cand={c} /></td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {!rows.length && <p className="p-6 text-center text-xs text-slate-500">No candidates meet these requirements. See the exclusion summary above.</p>}
    </div>
  );
}

export function MethodologyPanel({ result }) {
  const discs = Object.keys(result.weights);
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {discs.map(d => {
        const cg = result.comparison_group[d];
        return (
          <div key={d} className="panel-flat p-3 text-2xs">
            <div className="mb-1.5 font-semibold text-slate-200">{d === 'bat' ? 'Batting' : 'Bowling'} comparison group · {fmtInt(cg.size)} players</div>
            {cg.note && <p className="mb-1.5 text-warn-soft">{cg.note}</p>}
            <table className="w-full">
              <thead><tr className="text-left text-3xs text-slate-600"><th>Metric</th><th>Group</th><th className="text-right">Weight</th><th className="text-right" title="Prior strength m in sample units, estimated from the cohort">Prior m</th></tr></thead>
              <tbody>
                {result.weights[d].map(w => {
                  const prior = cg.priors?.[w.metric] || cg.priors?.[{ sr_index: 'strike_rate', econ_index: 'economy', pp_sr_index: 'pp_sr', mid_sr_index: 'mid_sr', death_sr_index: 'death_sr' }[w.metric]];
                  return (
                    <tr key={w.metric} className="border-t border-line-soft">
                      <td className="py-0.5 text-slate-300">{w.label}</td><td className="text-slate-500">{w.group}</td>
                      <td className="num text-right text-slate-300">{Math.round(w.weight * 100)}%</td>
                      <td className="num text-right text-slate-500">{prior ? `${fmtInt(prior.strength)}${prior.fallback ? '*' : ''}` : DASH}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        );
      })}
      <div className="panel-flat p-3 text-2xs leading-relaxed text-slate-400 md:col-span-2">
        <b className="text-slate-200">How the score works.</b> Each metric is shrunk towards the comparison-group mean: shrunk = (num + m·mean)/(n + m), where m is estimated from the spread between players (method of moments), so a 3-innings cameo is pulled to the group average far more than a 40-innings record. Shrunk values are converted to percentiles within the role’s comparison group (format- and scope-specific; nationality and style filters narrow candidates but never the group). The suitability score is the weighted mean of percentiles over metrics with evidence. Reliability = n/(n+m) averaged by weight: Established ≥ 0.60, Limited evidence ≥ 0.30. Context-adjusted indices divide by the run rate of all players in the same competition-season and phase mix (100 = environment average). {result.thresholds && <>Significant score: {result.thresholds.sig}+; failure: dismissed below {result.thresholds.poor}.</>}
      </div>
    </div>
  );
}

export function ExclusionSummary({ result }) {
  if (!result.exclusions?.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-2xs text-slate-500">
      <span>Excluded from {fmtInt(result.pool_size)} role-eligible players:</span>
      {result.exclusions.map(e => <Badge key={e.reason}>{e.reason} · {fmtInt(e.players)}</Badge>)}
    </div>
  );
}

export { ordinal };
