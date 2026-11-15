/**
 * Multi-franchise auction room. The user controls one franchise; every other
 * franchise bids independently from its own squad, purse and needs (server-side).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { auctionAnalytics } from '../../services/api';
import { Badge, Button, Callout, EmptyState, ErrorState, FilterField, Panel, Select } from '../../components/ui';
import { DASH, PriceRange, Prov, fmtL, fmtNum, fmtPct, roleLabel } from './auctionUi';

const SIM_KEY = 'cpi.auction.sim.v2';

export default function SimulatorTab({ context, contextInfo, strategies, onPlayer }) {
  const [sim, setSim] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [team, setTeam] = useState('');
  const [strategy, setStrategy] = useState('balanced');
  const [running, setRunning] = useState(false);
  const runRef = useRef(false);

  useEffect(() => {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(SIM_KEY) || 'null'); } catch { /* storage unavailable */ }
    if (saved?.context === context && saved.id) auctionAnalytics.roomGet(saved.id).then(setSim).catch(() => setSim(null));
    else setSim(null);
  }, [context]);

  const act = useCallback(async body => {
    if (!sim) return null;
    setBusy(true); setError('');
    try { const next = await auctionAnalytics.roomAction(sim.id, body); setSim(s => ({ ...s, ...next })); return next; }
    catch (e) { setError(e.message); return null; }
    finally { setBusy(false); }
  }, [sim]);

  async function start() {
    setBusy(true); setError('');
    try {
      const created = await auctionAnalytics.roomCreate({ context, user_franchise: team || null, strategy });
      setSim(created);
      try { localStorage.setItem(SIM_KEY, JSON.stringify({ context, id: created.id })); } catch { /* ignore */ }
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  // Auto-run lot by lot so the room stays responsive and can be paused.
  async function play() {
    runRef.current = true; setRunning(true);
    let state = sim;
    while (runRef.current && state && state.status !== 'COMPLETE') {
      if (state.current?.status === 'BIDDING') {
        state = await act({ action: 'resolve' });
        // Still open after resolving → the AI has stopped and it is the user's call.
        if (state?.current?.status === 'BIDDING') break;
      } else {
        state = await act({ action: 'call' });
      }
    }
    runRef.current = false; setRunning(false);
  }
  const pause = () => { runRef.current = false; setRunning(false); };

  if (!sim) {
    return (
      <div className="space-y-4">
        <Panel title="Set up the auction room" subtitle="Choose a franchise to control (or watch all ten AI franchises) and a bidding strategy. Strategies change your recommended limits and autopilot bids, not just labels.">
          {contextInfo && !contextInfo.simulatable && <Callout tone="warn">Pre-auction purse is not known for enough franchises in this context, so it cannot be simulated. Choose 2022 or later.</Callout>}
          <div className="flex flex-wrap items-end gap-3">
            <FilterField label="Your franchise"><Select value={team} onChange={setTeam} placeholder="None — watch only" options={['CSK', 'DC', 'GT', 'KKR', 'LSG', 'MI', 'PBKS', 'RCB', 'RR', 'SRH']} /></FilterField>
            <FilterField label="Strategy"><Select value={strategy} onChange={setStrategy} options={strategies.map(s => ({ id: s.key, label: s.label }))} /></FilterField>
            <Button variant="primary" onClick={start} disabled={busy || (contextInfo && !contextInfo.simulatable)}>{busy ? 'Preparing valuations…' : 'Start auction'}</Button>
          </div>
          <p className="mt-3 text-xs text-slate-500">{strategies.find(s => s.key === strategy)?.summary}</p>
          <p className="mt-2 text-2xs text-slate-500">All bids are simulated. Franchise interest comes from each squad's needs, purse and the predicted price; nothing reconstructs real bidding (no bid-level data exists).</p>
        </Panel>
        {error && <ErrorState message={error} />}
      </div>
    );
  }

  const cur = sim.current;
  const rec = sim.recommendation;
  const user = sim.user_franchise;
  const done = sim.status === 'COMPLETE';
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
          <Badge variant="gold">Simulation</Badge>
          <span className="num">Lot {sim.cursor} / {sim.total_lots}</span>
          {user && <Badge variant="indigo">You: {user} · {sim.strategy}</Badge>}
          {sim.excluded_franchises?.length > 0 && <Badge variant="amber">Not simulated (purse unknown): {sim.excluded_franchises.join(', ')}</Badge>}
        </div>
        <div className="flex flex-wrap gap-2">
          {!running ? <Button size="sm" icon="play" onClick={play} disabled={busy || done}>{cur?.status === 'BIDDING' && rec ? 'Resume after your decision' : 'Run auction'}</Button>
            : <Button size="sm" icon="pause" onClick={pause}>Pause</Button>}
          <Button size="sm" onClick={() => act({ action: 'step' })} disabled={busy || running || done}>Simulate next bid</Button>
          <Button size="sm" onClick={() => act(cur?.status === 'BIDDING' ? { action: 'resolve' } : { action: 'call' })} disabled={busy || running || done}>{cur?.status === 'BIDDING' ? 'Resolve lot' : 'Next player'}</Button>
          <Button size="sm" onClick={() => act({ action: 'complete' })} disabled={busy || running || done} title="Your franchise bids on autopilot with your strategy">Complete auction</Button>
          <Button size="sm" variant="ghost" onClick={() => { setSim(null); try { localStorage.removeItem(SIM_KEY); } catch { /* ignore */ } }}>New simulation</Button>
        </div>
      </div>
      {error && <ErrorState message={error} />}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <Panel title={cur ? cur.player.name : 'Auction block'} eyebrow={cur ? `${roleLabel(cur.player.role)} · ${cur.player.overseas ? 'Overseas' : 'Domestic'}${cur.player.set_code ? ` · Set ${cur.player.set_code}` : ''}` : 'Waiting'}
          actions={cur && <Button size="xs" variant="ghost" onClick={() => onPlayer(cur.player_key)}>Full valuation</Button>}>
          {!cur ? <EmptyState icon="auction" message="Call the first player to begin." action={<Button variant="primary" onClick={() => act({ action: 'call' })}>Call first player</Button>} /> : (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Stat label="Base price" value={fmtL(cur.base)} />
                <Stat label={cur.status === 'BIDDING' ? 'Current bid' : cur.status === 'SOLD' ? 'Sold for' : 'Result'} value={cur.bid ? fmtL(cur.bid) : cur.status === 'UNSOLD' ? 'Unsold' : 'No bids'} tone="accent" />
                <Stat label="Highest bidder" value={cur.leader || DASH} />
                <Stat label="Next bid" value={fmtL(cur.next_bid_lakh)} />
              </div>
              <div><div className="mb-1 flex justify-between text-2xs text-slate-500"><span>CPI predicted range</span><Prov kind="model" /></div>
                <PriceRange p10={cur.player.p10} p50={cur.player.p50} p90={cur.player.p90} base={cur.base} actual={undefined} /></div>
              <div className="grid grid-cols-2 gap-x-5 gap-y-1 text-xs sm:grid-cols-3">
                {[['Quality', fmtNum(cur.player.quality, 0)], ['Market value', fmtL(cur.player.market_value_lakh)], ['P(bidding war)', fmtPct(cur.player.bidding_war_probability)],
                  ['IPL matches', cur.player.stats?.ipl_matches_career ?? DASH], ['SR / econ (eq.)', `${fmtNum(cur.player.stats?.bat_sr_eq, 0)} / ${fmtNum(cur.player.stats?.bowl_econ_eq, 2)}`], ['Scarcity', cur.player.scarcity ? `${fmtNum(cur.player.scarcity.score, 0)} (${cur.player.scarcity.group})` : DASH]]
                  .map(([k, v]) => <div key={k} className="flex justify-between border-b border-line-soft py-1"><span className="text-slate-500">{k}</span><span className="num text-slate-200">{v}</span></div>)}
              </div>
              {user && cur.status === 'BIDDING' && (
                <div className="flex flex-wrap gap-2">
                  <Button variant="primary" onClick={() => act({ action: 'bid' })} disabled={busy || cur.leader === user}>Bid {fmtL(cur.next_bid_lakh)}</Button>
                  <BidInput onBid={amount => act({ action: 'bid', amount })} disabled={busy || cur.leader === user} min={cur.next_bid_lakh} />
                  <Button onClick={() => act({ action: 'pass' })} disabled={busy}>Pass</Button>
                </div>
              )}
              <div>
                <p className="mb-1.5 flex items-center justify-between text-2xs font-medium text-slate-400"><span>Bidding history</span><Prov kind="simulated" /></p>
                <div className="flex max-h-28 flex-wrap gap-1 overflow-y-auto">{cur.history.length ? cur.history.map((h, i) => <Badge key={i} variant={h.franchise === user ? 'indigo' : 'default'}>{h.franchise} {fmtL(h.bid_lakh, { short: true })}</Badge>) : <span className="text-xs text-slate-500">No bids yet.</span>}</div>
              </div>
            </div>
          )}
        </Panel>

        <div className="space-y-4">
          {rec && (
            <Panel title={`Recommendation: ${rec.action}`} subtitle={`${rec.strategy} strategy · your limit ${fmtL(rec.max_bid_lakh)}`} actions={<Prov kind="model" />}>
              <ul className="list-disc space-y-1 pl-4 text-xs text-slate-300">{rec.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
              {rec.alternatives?.length > 0 && <div className="mt-3"><p className="mb-1 text-2xs text-slate-500">Alternatives still to come</p>
                {rec.alternatives.slice(0, 4).map(a => <div key={a.name} className="flex justify-between text-xs"><span className="text-slate-300">{a.name}</span><span className="num text-slate-400">q {fmtNum(a.quality, 0)} · {fmtL(a.p50)}</span></div>)}</div>}
              <div className="mt-3 flex flex-wrap gap-1.5">{strategies.map(s => <button key={s.key} onClick={() => act({ action: 'strategy', strategy: s.key })} className={`rounded-full px-2.5 py-1 text-2xs ${sim.strategy === s.key ? 'bg-accent text-on-accent' : 'bg-white/[0.06] text-slate-300'}`}>{s.label}</button>)}</div>
            </Panel>
          )}
          {cur && (
            <Panel title="Competing franchises" subtitle="Estimated limits for this player (model-estimated, not real intentions)" actions={<Prov kind="model" />} bodyClassName="p-0">
              <ul className="divide-y divide-line-soft">{cur.interest.map(i => (
                <li key={i.franchise} className="flex items-center gap-3 px-5 py-1.5 text-xs" title={i.reasons.join(' · ')}>
                  <span className="w-11 font-medium text-slate-200">{i.franchise}</span>
                  <div className="h-1.5 flex-1 rounded-full bg-[var(--chart-track)]"><div className="h-full rounded-full bg-accent" style={{ width: `${Math.min(100, (i.limit / Math.max(cur.player.p90 || 1, cur.bid || 1, ...cur.interest.map(x => x.limit))) * 100)}%`, opacity: i.eligible ? 1 : 0.25 }} /></div>
                  <span className="num w-20 text-right text-slate-300">{i.eligible ? fmtL(i.limit) : 'out'}</span>
                </li>))}</ul>
            </Panel>
          )}
        </div>
      </div>

      <Panel title="Franchises" subtitle="Live purse, squad and needs — recalculated after every purchase." bodyClassName="p-0">
        <div className="overflow-x-auto"><table className="w-full text-[13px]">
          <thead className="bg-surface-raised text-left text-2xs uppercase tracking-wide text-slate-500"><tr><th className="px-4 py-2">Team</th><th className="px-3 text-right">Purse</th><th className="px-3 text-right">Spent</th><th className="px-3 text-right">Squad</th><th className="px-3 text-right">OS</th><th className="px-3 text-right">Max bid</th><th className="px-3 text-right">XI</th><th className="px-3">Open needs</th><th className="px-3">Bought</th></tr></thead>
          <tbody>{sim.teams.map(t => (
            <tr key={t.code} className={`border-b border-line-soft ${t.is_user ? 'bg-accent/[0.07]' : ''}`}>
              <td className="px-4 py-2 font-medium text-white">{t.code}{t.rtm_cards ? <Badge className="ml-1.5">RTM {t.rtm_cards}</Badge> : null}</td>
              <td className="num px-3 text-right">{fmtL(t.purse_lakh)}</td><td className="num px-3 text-right">{fmtL(t.spent_lakh)}</td>
              <td className="num px-3 text-right">{t.squad_size}</td><td className="num px-3 text-right">{t.overseas}</td><td className="num px-3 text-right">{fmtL(t.max_bid_lakh)}</td>
              <td className="num px-3 text-right">{fmtNum(t.xi_score, 0)}</td>
              <td className="px-3"><div className="flex flex-wrap gap-1">{t.top_needs.slice(0, 3).map(n => <Badge key={n.key} variant={n.priority === 'Critical' ? 'red' : 'amber'}>{n.label}</Badge>)}</div></td>
              <td className="max-w-[18rem] truncate px-3 text-xs text-slate-400">{t.bought.map(b => `${b.name} ${fmtL(b.price_lakh, { short: true })}`).join(', ') || DASH}</td>
            </tr>))}</tbody></table></div>
      </Panel>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel title="Results" subtitle="Simulated price vs CPI range — and the recorded outcome where this is a replay" bodyClassName="p-0">
          <div className="max-h-[24rem] overflow-y-auto"><table className="w-full text-xs">
            <thead className="sticky top-0 bg-surface-raised text-left text-2xs uppercase text-slate-500"><tr><th className="px-4 py-2">Player</th><th className="px-2">Simulated</th><th className="px-2 text-right">Price</th><th className="px-2">Actual</th></tr></thead>
            <tbody>{[...sim.results].reverse().map(r => (
              <tr key={r.player_key} className="border-t border-line-soft"><td className="px-4 py-1.5 text-slate-200">{r.name}{r.rtm && <Badge variant="amber" className="ml-1" title={r.rtm}>RTM</Badge>}</td>
                <td className="px-2">{r.status === 'SOLD' ? r.franchise : <span className="text-slate-500">unsold</span>}</td>
                <td className="num px-2 text-right">{fmtL(r.price_lakh)}</td>
                <td className="px-2 text-slate-500">{r.actual_status ? (r.actual_status === 'SOLD' ? `${r.actual_franchise} ${fmtL(r.actual_price_lakh, { short: true })}` : r.actual_status.toLowerCase()) : DASH}</td></tr>))}</tbody>
          </table></div>
        </Panel>
        {sim.summary && (
          <Panel title="Simulation summary" actions={<Prov kind="simulated" />}>
            <div className="grid grid-cols-2 gap-x-5 gap-y-1 text-xs">
              {[['Lots completed', sim.summary.lots], ['Sold / unsold', `${sim.summary.sold} / ${sim.summary.unsold}`], ['Total spend', fmtL(sim.summary.total_spend_lakh)],
                ['Compared with recorded', sim.summary.vs_actual.compared], ['Price MAE vs recorded', fmtL(sim.summary.vs_actual.mae_lakh)], ['Same franchise as recorded', fmtPct(sim.summary.vs_actual.same_franchise_rate)]]
                .map(([k, v]) => <div key={k} className="flex justify-between border-b border-line-soft py-1"><span className="text-slate-500">{k}</span><span className="num text-slate-200">{v ?? DASH}</span></div>)}
            </div>
            {sim.summary.below_minimum_squad?.length > 0 && <Callout tone="warn">Below minimum squad: {sim.summary.below_minimum_squad.map(s => `${s.franchise} (${s.squad_size})`).join(', ')}. {sim.summary.below_minimum_note}</Callout>}
            <p className="mt-3 text-2xs text-slate-500">{sim.labels?.actual}. A single simulated run is one plausible auction, not a forecast of the real one.</p>
          </Panel>
        )}
      </div>
      {sim.upcoming?.length > 0 && <p className="text-2xs text-slate-500">Up next: {sim.upcoming.map(p => p.name).join(' · ')}</p>}
    </div>
  );
}

function Stat({ label, value, tone }) {
  return <div className="rounded-2xl border border-line bg-surface-raised px-3 py-2.5"><div className="text-2xs text-slate-500">{label}</div><div className={`display-num mt-1 text-lg ${tone === 'accent' ? 'text-accent-soft' : 'text-white'}`}>{value}</div></div>;
}

function BidInput({ onBid, disabled, min }) {
  const [v, setV] = useState('');
  return (
    <form className="flex gap-1" onSubmit={e => { e.preventDefault(); if (v) { onBid(Number(v)); setV(''); } }}>
      <input type="number" min={min} step="5" value={v} onChange={e => setV(e.target.value)} placeholder={`≥ ${min ?? ''} L`} className="h-9 w-28 text-[13px]" aria-label="Custom bid in lakh" />
      <Button type="submit" disabled={disabled || !v}>Place bid</Button>
    </form>
  );
}
