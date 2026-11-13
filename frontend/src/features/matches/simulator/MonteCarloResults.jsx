/** Monte Carlo summary: every figure is aggregated from the simulated matches. */
import { Histogram, Panel, TEAM_COLORS } from './charts';
import { PlayerLink, TeamLink } from './MatchResult';

const th = 'px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-500';
const td = 'px-2 py-1.5';
const fmt = (v, d = 1) => (v === null || v === undefined ? '—' : Number(v).toFixed(d));

function Stat({ label, value, sub }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</p>
      <p className="mt-1 font-mono text-xl font-bold text-white">{value}</p>
      {sub && <p className="mt-0.5 text-[11px] text-slate-400">{sub}</p>}
    </div>
  );
}

export default function MonteCarloResults({ mc, names }) {
  const tie = mc.tie_pct || 0;
  const draw = mc.draw_pct || 0;
  const undecided = Math.max(0, 100 - mc.win_pct.A - mc.win_pct.B);
  const d = mc.distributions || {};
  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-indigo-900/50 bg-slate-900 p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-bold text-white">{mc.simulations.toLocaleString()} simulated matches</h2>
          <p className="text-[11px] text-slate-500">seed {mc.seed} · {mc.elapsed_seconds}s{mc.requested > mc.simulations ? ` · capped at ${mc.capped_at}` : ''}</p>
        </div>
        <div className="mt-4 flex h-9 overflow-hidden rounded-lg text-xs font-semibold" role="img" aria-label={`${names.A} ${mc.win_pct.A}%, ${names.B} ${mc.win_pct.B}%`}>
          <div className="flex items-center justify-start px-3 text-slate-950" style={{ width: `${mc.win_pct.A}%`, background: TEAM_COLORS.A }}>{mc.win_pct.A >= 12 && `${names.A} ${fmt(mc.win_pct.A)}%`}</div>
          {undecided > 0 && <div className="flex items-center justify-center bg-slate-600 text-[10px] text-white" style={{ width: `${undecided}%` }}>{undecided >= 6 && (draw ? `Draw ${fmt(draw)}%` : `Tie ${fmt(undecided)}%`)}</div>}
          <div className="flex items-center justify-end px-3 text-slate-950" style={{ width: `${mc.win_pct.B}%`, background: TEAM_COLORS.B }}>{mc.win_pct.B >= 12 && `${names.B} ${fmt(mc.win_pct.B)}%`}</div>
        </div>
        <p className="mt-2 text-[11px] text-slate-400">
          Tied after regulation in {fmt(tie)}% of matches{mc.super_over_pct ? ` (super over in ${fmt(mc.super_over_pct)}%)` : ''}{draw ? `; drawn ${fmt(draw)}%` : ''}.
          {' '}Toss winner won {fmt(mc.toss_winner_win_pct)}% of decided matches; the side batting first won {fmt(mc.bat_first_win_pct)}%.
        </p>
      </section>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Avg first-innings score" value={fmt(mc.avg_first_innings)} sub={mc.first_innings_p10_p90?.[0] != null ? `80% between ${mc.first_innings_p10_p90[0]} and ${mc.first_innings_p10_p90[1]}` : null} />
        <Stat label="Avg successful chase" value={fmt(mc.avg_successful_chase)} sub={mc.chase_success_pct != null ? `${fmt(mc.chase_success_pct)}% of chases succeed (${mc.successful_chases})` : 'Not applicable'} />
        <Stat label={`Avg wickets lost · ${names.A}`} value={fmt(mc.avg_wickets_lost?.A, 2)} sub={`avg innings ${fmt(mc.avg_innings_total?.A)}`} />
        <Stat label={`Avg wickets lost · ${names.B}`} value={fmt(mc.avg_wickets_lost?.B, 2)} sub={`avg innings ${fmt(mc.avg_innings_total?.B)}`} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="First-innings score distribution" subtitle={`By team batting first: ${names.A} ${fmt(mc.avg_first_innings_by_team?.A)}, ${names.B} ${fmt(mc.avg_first_innings_by_team?.B)}`}>
          <Histogram bins={d.first_innings} label={b => `${b.start}-${b.end}`} />
        </Panel>
        <Panel title="Winning margins" subtitle="Runs (defending side) and wickets (chasing side)">
          <div className="grid grid-cols-2 gap-4 pb-4">
            <div><p className="mb-1 text-[11px] text-slate-400">By runs</p><Histogram bins={d.margin_runs} color="#fbbf24" label={b => `${b.start}-${b.end} runs`} height={120} /></div>
            <div><p className="mb-1 text-[11px] text-slate-400">By wickets</p><Histogram bins={(d.margin_wickets || []).map(b => ({ ...b, start: b.wickets }))} color="#22d3ee" label={b => `${b.wickets} wickets`} height={120} /></div>
          </div>
        </Panel>
        {['A', 'B'].map(k => (
          <Panel key={k} title={`${names[k]}: innings totals`} subtitle={`All innings batted by ${names[k]}`}>
            <div className="pb-4"><Histogram bins={d.team_totals?.[k]} color={TEAM_COLORS[k]} label={b => `${b.start}-${b.end}`} /></div>
          </Panel>
        ))}
      </div>

      <Panel title="Most influential players" subtitle="Influence = average match impact × correlation between that impact and the team winning, across all simulations">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-xs">
            <thead><tr className="border-b border-slate-800"><th className={th}>Player</th><th className={th}>Team</th>{['Influence', 'Avg impact', 'Win corr', 'Win% above avg', 'POTM %', 'Avg runs', 'SR', '50+ %', 'Avg wkts', 'Econ'].map(h => <th key={h} className={`${th} text-right`}>{h}</th>)}</tr></thead>
            <tbody className="divide-y divide-slate-800/70 text-slate-300">
              {(mc.influential_players || []).map(p => (
                <tr key={p.player_id}>
                  <td className={td}><PlayerLink id={p.player_id} name={p.name} className="font-medium" /></td>
                  <td className={td}><TeamLink name={names[p.team]} style={{ color: TEAM_COLORS[p.team] }} /></td>
                  <td className={`${td} text-right font-mono font-semibold text-white`}>{fmt(p.influence)}</td>
                  <td className={`${td} text-right font-mono`}>{fmt(p.avg_impact)}</td>
                  <td className={`${td} text-right font-mono`}>{fmt(p.win_correlation, 2)}</td>
                  <td className={`${td} text-right font-mono`}>{p.win_rate_when_above_avg != null ? `${fmt(100 * p.win_rate_when_above_avg, 0)}% vs ${fmt(100 * p.win_rate_when_below_avg, 0)}%` : '—'}</td>
                  <td className={`${td} text-right font-mono`}>{fmt(p.potm_pct)}</td>
                  <td className={`${td} text-right font-mono`}>{fmt(p.avg_runs)}</td>
                  <td className={`${td} text-right font-mono`}>{fmt(p.strike_rate)}</td>
                  <td className={`${td} text-right font-mono`}>{fmt(p.fifty_plus_pct)}</td>
                  <td className={`${td} text-right font-mono`}>{fmt(p.avg_wickets, 2)}</td>
                  <td className={`${td} text-right font-mono`}>{fmt(p.economy, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
