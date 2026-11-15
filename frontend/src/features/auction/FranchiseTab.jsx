import { useEffect, useState } from 'react';
import { auctionAnalytics } from '../../services/api';
import { BarChart, PALETTE } from '../../components/charts';
import { Badge, Callout, ErrorState, KpiGrid, Panel, PanelSkeleton } from '../../components/ui';
import { DASH, KV, PriorityBadge, Prov, fmtL, fmtNum, fmtPct, roleLabel, useAsync } from './auctionUi';

export default function FranchiseTab({ context, onPlayer }) {
  const list = useAsync(() => auctionAnalytics.franchises(context), [context]);
  const [code, setCode] = useState('');
  useEffect(() => { if (list.data && !list.data.franchises.some(f => f.code === code)) setCode(list.data.franchises[0]?.code || ''); }, [list.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const detail = useAsync(() => (code ? auctionAnalytics.franchise(context, code) : Promise.resolve(null)), [context, code]);

  if (list.error) return <ErrorState message={list.error} />;
  if (!list.data) return <PanelSkeleton rows={6} />;
  const d = detail.data;
  return (
    <div className="space-y-5">
      <Panel title="Franchise overview" subtitle="Purse, squad slots and the most pressing needs — calculated from each franchise's actual squad in this context."
        actions={<Prov kind="calculated" />} bodyClassName="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead className="bg-surface-raised text-left text-2xs uppercase tracking-wide text-slate-500"><tr>
              <th className="px-4 py-2.5">Franchise</th><th className="px-3 text-right">Purse</th><th className="px-3">Basis</th><th className="px-3 text-right">Squad</th>
              <th className="px-3 text-right">Slots</th><th className="px-3 text-right">Overseas slots</th><th className="px-3 text-right">Max bid</th><th className="px-3 text-right">XI score</th><th className="px-3">Biggest gaps</th></tr></thead>
            <tbody>{list.data.franchises.map(f => (
              <tr key={f.code} onClick={() => setCode(f.code)} className={`cursor-pointer border-b border-line-soft hover:bg-surface-hover ${code === f.code ? 'bg-accent/[0.07]' : ''}`}>
                <td className="px-4 py-2.5 font-medium text-white">{f.code} <span className="text-2xs font-normal text-slate-500">{f.name}</span></td>
                <td className="num px-3 text-right">{fmtL(f.purse.purse_lakh)}</td>
                <td className="px-3"><Prov kind={f.purse_basis === 'sourced' ? 'actual' : f.purse_basis === 'unknown' ? 'conflict' : 'derived'}>{f.purse_basis.replace(/_/g, ' ')}</Prov></td>
                <td className="num px-3 text-right">{f.squad_size}</td><td className="num px-3 text-right">{f.purse.slots_left ?? DASH}</td>
                <td className="num px-3 text-right">{f.purse.overseas_slots_left ?? DASH}</td><td className="num px-3 text-right">{fmtL(f.purse.max_theoretical_bid_lakh)}</td>
                <td className="num px-3 text-right">{fmtNum(f.xi_score, 0)}</td>
                <td className="px-3"><div className="flex flex-wrap gap-1">{f.needs.filter(n => n.priority === 'Critical' || n.priority === 'High').slice(0, 3).map(n => <Badge key={n.key} variant={n.priority === 'Critical' ? 'red' : 'amber'}>{n.label}</Badge>)}</div></td>
              </tr>))}</tbody>
          </table>
        </div>
      </Panel>

      {detail.loading && <PanelSkeleton rows={6} />}
      {detail.error && <ErrorState message={detail.error} />}
      {d && (
        <div className="space-y-5">
          <KpiGrid items={[
            { label: `${d.code} purse`, value: fmtL(d.purse.purse_lakh), sub: d.purse_basis.replace(/_/g, ' '), highlight: true },
            { label: 'Slots left', value: d.purse.slots_left ?? DASH, sub: `${d.purse.min_slots_to_fill ?? DASH} needed for minimum squad` },
            { label: 'Avg per slot', value: fmtL(d.purse.avg_per_slot_lakh) },
            { label: 'Minimum reserve', value: fmtL(d.purse.minimum_reserve_lakh), sub: 'To complete the minimum squad' },
            { label: 'Max theoretical bid', value: fmtL(d.purse.max_theoretical_bid_lakh), sub: 'Legal maximum' },
            { label: 'Reserve for critical needs', value: fmtL(d.critical_reserve.total_lakh), sub: 'Cheapest adequate options', tone: d.critical_reserve.total_lakh > (d.purse.purse_lakh || 0) ? 'neg' : undefined },
          ]} />
          {d.purse.purse_lakh !== undefined && d.critical_reserve.total_lakh > (d.purse.purse_lakh || 0) && (
            <Callout tone="warn">Filling every Critical/High need with the cheapest adequate player still costs more than the remaining purse — {d.code} must accept weaker options in some roles.</Callout>)}
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
            <Panel title="Squad requirements" subtitle="Priority list calculated from the actual squad and how many players IPL teams really use per role." actions={<Prov kind="calculated" />} bodyClassName="p-0">
              <table className="w-full text-[13px]"><thead className="text-left text-2xs uppercase tracking-wide text-slate-500"><tr><th className="px-5 py-2">Requirement</th><th>Priority</th><th className="text-right">Have / target</th><th className="px-5">Reason</th></tr></thead>
                <tbody>{d.needs.map(n => <tr key={n.key} className="border-t border-line-soft"><td className="px-5 py-2 text-slate-200">{n.label}</td><td><PriorityBadge priority={n.priority} /></td>
                  <td className="num text-right">{n.have} / {n.target}</td><td className="px-5 text-xs text-slate-400" title={n.target_basis}>{n.reason}</td></tr>)}</tbody></table>
            </Panel>
            <Panel title="Current squad" subtitle={`Best XI score ${fmtNum(d.xi.score, 0)} (batting ${fmtNum(d.xi.batting, 0)} · bowling ${fmtNum(d.xi.bowling, 0)})`} actions={<Prov kind="calculated" />} bodyClassName="p-0">
              <ul className="max-h-[26rem] divide-y divide-line-soft overflow-y-auto">{d.squad.map(m => (
                <li key={m.player_id || m.name} className="flex items-center justify-between gap-2 px-5 py-2 text-xs">
                  <span className="min-w-0"><span className="block truncate text-slate-200">{m.name}{d.xi.xi?.includes(m.player_id || m.name) && <Badge variant="indigo" className="ml-1.5">XI</Badge>}{m.overseas && <Badge variant="blue" className="ml-1">OS</Badge>}</span>
                    <span className="block truncate text-2xs text-slate-500">{(m.tags || []).map(t => t.replace(/_/g, ' ')).join(' · ') || roleLabel(m.role)}{m.assumed ? ' · no evidence (assumed)' : ''}</span></span>
                  <span className="num shrink-0 text-right text-slate-400">bat {fmtNum(m.bat, 0)} · bowl {fmtNum(m.bowl, 0)}<br /><span className="text-slate-500">{fmtL(m.price_lakh)}</span></span>
                </li>))}</ul>
            </Panel>
          </div>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <TargetList title="Priority targets" subtitle="Largest squad improvement (best-XI change + depth for open needs)" rows={d.priority_targets} onPlayer={onPlayer} metric={r => `+${fmtNum(r.marginal.total, 0)}`} />
            <TargetList title="Best value targets" subtitle="Squad improvement per crore of predicted price" rows={d.value_targets} onPlayer={onPlayer} metric={r => `${fmtNum(r.value_per_crore, 0)}/cr`} />
          </div>
          {d.behaviour && <Behaviour b={d.behaviour} />}
          <p className="text-2xs text-slate-500">{d.labels.needs}. Requirement targets: {Object.entries(d.requirement_targets).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v.median_used}`).join(' · ')} (median players used per IPL team-season, last 3 seasons before this auction).</p>
        </div>
      )}
    </div>
  );
}

function TargetList({ title, subtitle, rows, onPlayer, metric }) {
  return (
    <Panel title={title} subtitle={subtitle} actions={<Prov kind="model" />} bodyClassName="p-0">
      {!rows.length ? <p className="px-5 py-6 text-xs text-slate-500">No eligible targets.</p> : (
        <ul className="divide-y divide-line-soft">{rows.map(r => (
          <li key={r.key}><button onClick={() => onPlayer(r.key)} className="flex w-full items-center justify-between gap-3 px-5 py-2.5 text-left hover:bg-surface-hover">
            <span className="min-w-0"><span className="block truncate text-[13px] text-white">{r.name}</span>
              <span className="block truncate text-2xs text-slate-500">{r.marginal.fills.map(f => `${f.need} (${f.priority})`).join(', ') || roleLabel(r.role)} · {r.marginal.would_start ? 'would start' : 'depth'}</span></span>
            <span className="num shrink-0 text-right text-xs"><span className="block text-slate-100">{metric(r)}</span><span className="block text-slate-500">{fmtL(r.predicted.p50)}</span></span>
          </button></li>))}</ul>
      )}
    </Panel>
  );
}

function Behaviour({ b }) {
  return (
    <Panel title={`${b.name}: historical auction behaviour`} subtitle={`${b.purchases} recorded auction purchases across ${b.seasons} seasons — ${b.evidence}.`} actions={<Prov kind="actual">Observed history</Prov>}>
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <div className="space-y-1 text-xs">
          <KV k="Avg price (share of purse)" v={fmtPct(b.avg_price_share_of_purse, 2)} />
          <KV k="Avg price since 2022" v={fmtL(b.avg_price_lakh_recent)} />
          <KV k="Overseas purchase rate" v={fmtPct(b.overseas_purchase_rate)} />
          <KV k="Bidding-war buys (≥3× base)" v={`${fmtPct(b.bidding_war_rate)} of ${b.bidding_war_sample}`} />
          <div className="pt-3">
            <p className="mb-1.5 text-2xs font-medium text-slate-400">Statistically supported tendencies</p>
            {b.tendencies.length ? b.tendencies.map(t => <p key={t.tendency} className="text-xs text-slate-300">• {t.tendency} <span className="text-slate-500">(z = {t.z})</span></p>)
              : <p className="text-xs text-slate-500">None — differences from the league average are within normal variation.</p>}
          </div>
        </div>
        <BarChart title="Spend share by role" data={Object.entries(b.spend_share_by_role).map(([k, v], i) => ({ label: roleLabel(k), value: v * 100, color: PALETTE[i] }))} formatter={v => `${v.toFixed(0)}%`} className="!p-0 !shadow-none !border-0 !bg-transparent" />
        <div><p className="mb-2 text-xs font-medium text-white">Biggest purchases</p>
          {b.biggest_purchases.map(p => <div key={`${p.season}-${p.player}`} className="flex justify-between border-b border-line-soft py-1 text-xs"><span className="text-slate-300">{p.season} · {p.player}</span><span className="num text-slate-200">{fmtL(p.price_lakh)}</span></div>)}</div>
      </div>
    </Panel>
  );
}
