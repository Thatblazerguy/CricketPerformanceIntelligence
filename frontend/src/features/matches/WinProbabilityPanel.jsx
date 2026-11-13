export default function WinProbabilityPanel({ data, matchData, selectedSequence, setSelectedSequence, onReplay, playing, setPlaying }) {
  if (!data || data.status === 'not_precomputed') return <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-5"><h3 className="font-semibold text-white">Win Probability & Historical Replay</h3><p className="mt-2 text-sm text-slate-400">This match has not been precomputed yet. Run the offline model build after applying its database migration.</p></section>;
  if (data.status !== 'available' || !data.points?.length) return <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-5"><h3 className="font-semibold text-white">Win Probability & Historical Replay</h3><p className="mt-2 text-sm text-slate-400">{data.exclusion_reason || 'Probability data is unavailable for this match.'}</p></section>;
  const points = data.points;
  const selectedIndex = Math.max(0, Math.min(selectedSequence ?? 0, points.length - 1));
  const selected = points[selectedIndex];
  const width = 1000, height = 250, padX = 36, padY = 18;
  const x = index => padX + (points.length <= 1 ? 0 : index / (points.length - 1)) * (width - 2 * padX);
  const y = probability => padY + (1 - probability) * (height - 2 * padY);
  const path = key => points.map((point, idx) => `${idx ? 'L' : 'M'}${x(idx)},${y(point.after[key])}`).join(' ');
  const selectAt = event => {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    const index = Math.round(ratio * (points.length - 1));
    setSelectedSequence(index);
    onReplay(points[index]);
  };
  const selectOver = direction => {
    const current = points[selectedIndex];
    for (let index = selectedIndex + direction; index >= 0 && index < points.length; index += direction) {
      const point = points[index];
      const crossedOver = point.innings_number !== current.innings_number || point.over !== current.over;
      if (crossedOver) {
        if (direction < 0) {
          while (index > 0 && points[index - 1].innings_number === point.innings_number && points[index - 1].over === point.over) index -= 1;
        }
        setSelectedSequence(index);
        return;
      }
    }
  };
  const innings = matchData.innings.find(item => item.innings_number === selected.innings_number);
  const deliveries = innings?.deliveries.slice(0, selected.delivery_index + 1) || [];
  const score = deliveries.reduce((value, delivery) => ({
    runs: value.runs + delivery.total_runs,
    wickets: value.wickets + (delivery.wickets?.filter(w => w.kind !== 'retired hurt').length || 0),
  }), { runs: 0, wickets: 0 });
  const highestDelivery = points.reduce((best, point) => Math.abs(point.wpa) > Math.abs(best.wpa) ? point : best, points[0]);
  const byOver = new Map();
  points.forEach(point => {
    const key = `${point.innings_number}:${point.over}`;
    const current = byOver.get(key) || { innings_number: point.innings_number, over: point.over, wpa: 0 };
    current.wpa += point.wpa;
    byOver.set(key, current);
  });
  const highestOver = [...byOver.values()].reduce((best, over) => Math.abs(over.wpa) > Math.abs(best.wpa) ? over : best);
  const colors = { team1_win: '#818cf8', team2_win: '#34d399', draw_or_tie: '#fbbf24' };

  return <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 sm:p-5">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div><h3 className="font-semibold text-white">Win Probability & Historical Replay</h3><p className="mt-1 text-xs text-slate-500">{data.model_version} · {data.format_family} model</p></div>
      <div className="flex flex-wrap gap-2"><button onClick={() => selectOver(-1)} className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300">Prev over</button><button onClick={() => setSelectedSequence(Math.max(0, selectedIndex - 1))} className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300">Previous ball</button><button onClick={() => setPlaying(!playing)} className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white">{playing ? 'Pause' : 'Play'}</button><button onClick={() => setSelectedSequence(Math.min(points.length - 1, selectedIndex + 1))} className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300">Next ball</button><button onClick={() => selectOver(1)} className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300">Next over</button></div>
    </div>
    <div className="mt-4 grid gap-3 sm:grid-cols-3">{[[data.team1, selected.after.team1_win, colors.team1_win], [data.team2, selected.after.team2_win, colors.team2_win], ['Draw / tie', selected.after.draw_or_tie, colors.draw_or_tie]].map(([label, value, color]) => <div key={label} className="rounded-lg bg-slate-950/70 p-3"><div className="text-xs text-slate-400">{label}</div><div className="mt-1 text-xl font-semibold tabular-nums" style={{ color }}>{(value * 100).toFixed(1)}%</div></div>)}</div>
    <div className="mt-3 grid gap-2 sm:grid-cols-2"><div className="rounded-lg border border-slate-800 p-3 text-xs text-slate-400">Largest delivery swing <span className="font-medium text-white">Innings {highestDelivery.innings_number}, {highestDelivery.over}.{highestDelivery.ball}</span> <span className="text-indigo-300">({(highestDelivery.wpa * 100).toFixed(2)} pp)</span></div><div className="rounded-lg border border-slate-800 p-3 text-xs text-slate-400">Largest over swing <span className="font-medium text-white">Innings {highestOver.innings_number}, over {highestOver.over}</span> <span className="text-indigo-300">({(highestOver.wpa * 100).toFixed(2)} pp)</span></div></div>
    <p className="mt-3 text-sm text-slate-300">Innings {selected.innings_number} · {selected.over}.{selected.ball} · {score.runs}/{score.wickets} · {selected.runs} run(s){selected.wickets ? ` · ${selected.wickets} wicket(s)` : ''}{selected.boundary ? ` · ${selected.boundary}` : ''}</p>
    <div className="mt-3 overflow-hidden rounded-lg bg-slate-950/60"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Win probability by delivery. Click to select a delivery." className="h-56 w-full cursor-crosshair" onClick={selectAt}>
      {[0, .25, .5, .75, 1].map(value => <g key={value}><line x1={padX} x2={width - padX} y1={y(value)} y2={y(value)} stroke="#334155" strokeDasharray="4 7"/><text x="4" y={y(value) + 4} fill="#94a3b8" fontSize="12">{Math.round(value * 100)}%</text></g>)}
      <path d={path('team1_win')} fill="none" stroke={colors.team1_win} strokeWidth="3"/><path d={path('team2_win')} fill="none" stroke={colors.team2_win} strokeWidth="3"/><path d={path('draw_or_tie')} fill="none" stroke={colors.draw_or_tie} strokeWidth="2" strokeDasharray="6 5"/>
      {points.map((point, idx) => (point.wickets || point.boundary) ? <circle key={idx} cx={x(idx)} cy={y(point.after.team1_win)} r={point.wickets ? 5 : 3.5} fill={point.wickets ? '#fb7185' : '#e2e8f0'} stroke="#0f172a" strokeWidth="2"><title>{point.wickets ? 'Wicket' : point.boundary} · Innings {point.innings_number}, {point.over}.{point.ball}</title></circle> : null)}
      <line x1={x(selectedIndex)} x2={x(selectedIndex)} y1={padY} y2={height - padY} stroke="#f8fafc" strokeOpacity=".55" strokeDasharray="3 4"/>
    </svg></div>
    <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-400"><div className="flex flex-wrap gap-4"><span style={{ color: colors.team1_win }}>● {data.team1}</span><span style={{ color: colors.team2_win }}>● {data.team2}</span><span style={{ color: colors.draw_or_tie }}>● Draw / tie</span><span className="text-rose-300">● Wicket</span><span>○ Boundary</span></div><button onClick={() => onReplay(selected)} className="text-indigo-300 hover:text-indigo-200">Open selected delivery in commentary →</button></div>
    <p className="mt-2 text-[11px] text-slate-500">Click the graph to inspect a delivery. Replay values come from stored ball-by-ball records and precomputed model output.</p>
  </section>;
}
