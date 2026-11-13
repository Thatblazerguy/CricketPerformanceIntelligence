/** Small SVG charts for simulator results (dark slate / indigo palette). */
export const TEAM_COLORS = { A: '#818cf8', B: '#34d399' };

export function Panel({ title, subtitle, children, className = '', right }) {
  return (
    <section className={`min-w-0 rounded-xl border border-slate-800 bg-slate-900/70 p-4 ${className}`}>
      {(title || right) && (
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div>
            {title && <h3 className="text-sm font-semibold text-slate-200">{title}</h3>}
            {subtitle && <p className="mt-0.5 text-[11px] text-slate-500">{subtitle}</p>}
          </div>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function WinProbabilityChart({ points = [], names }) {
  if (points.length < 2) return <p className="py-6 text-center text-xs text-slate-500">Not enough points to chart.</p>;
  const width = 900, height = 220, left = 36, right = 12, top = 12, bottom = 28;
  const x = i => left + (i / (points.length - 1)) * (width - left - right);
  const y = p => top + (1 - p) * (height - top - bottom);
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.team_a).toFixed(1)}`).join(' ');
  const hasCi = points.some(p => p.ci_low != null);
  const band = hasCi ? `${points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.ci_high ?? p.team_a).toFixed(1)}`).join(' ')} ${points.map((p, i) => [i, p]).reverse().map(([i, p]) => `L${x(i).toFixed(1)},${y(p.ci_low ?? p.team_a).toFixed(1)}`).join(' ')} Z` : null;
  const area = `${path} L${x(points.length - 1)},${y(0)} L${x(0)},${y(0)} Z`;
  const breaks = points.map((p, i) => (i > 0 && p.innings !== points[i - 1].innings ? i : null)).filter(i => i !== null);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label={`Win probability for ${names.A} through the match`}>
      {[0, 0.25, 0.5, 0.75, 1].map(v => (
        <g key={v}>
          <line x1={left} x2={width - right} y1={y(v)} y2={y(v)} stroke={v === 0.5 ? '#475569' : '#1e293b'} strokeDasharray={v === 0.5 ? '4 4' : '0'} />
          <text x={left - 6} y={y(v) + 3} textAnchor="end" fontSize="10" fill="#64748b">{Math.round(v * 100)}%</text>
        </g>
      ))}
      {breaks.map(i => (
        <g key={i}>
          <line x1={x(i)} x2={x(i)} y1={top} y2={height - bottom} stroke="#334155" strokeDasharray="2 4" />
          <text x={x(i) + 4} y={top + 10} fontSize="10" fill="#94a3b8">Innings {points[i].innings}</text>
        </g>
      ))}
      <path d={area} fill={TEAM_COLORS.A} opacity="0.08" />
      {band && <path d={band} fill={TEAM_COLORS.A} opacity="0.3" />}
      <path d={path} fill="none" stroke={TEAM_COLORS.A} strokeWidth="2.5" strokeLinejoin="round" />
      {points.map((p, i) => (
        <circle key={i} cx={x(i)} cy={y(p.team_a)} r="5" fill="transparent">
          <title>{`Innings ${p.innings}, after ${p.over} overs: ${p.score}/${p.wickets} — ${names.A} ${(p.team_a * 100).toFixed(1)}%${p.exact ? ' (decided)' : p.ci_low != null ? ` (95% ${(p.ci_low * 100).toFixed(1)}–${(p.ci_high * 100).toFixed(1)}%)` : ''}, ${names.B} ${(p.team_b * 100).toFixed(1)}%`}</title>
        </circle>
      ))}
      <text x={left} y={height - 8} fontSize="10" fill={TEAM_COLORS.A}>▲ {names.A} more likely</text>
      <text x={width - right} y={height - 8} fontSize="10" textAnchor="end" fill={TEAM_COLORS.B}>{names.B} more likely ▼</text>
    </svg>
  );
}

export function WormChart({ innings = [] }) {
  const series = innings.filter(i => !i.super_over).map(i => ({ key: `${i.number}`, team: i.batting, label: `${i.batting_team} (inn ${i.number})`,
    values: [0, ...(i.scorecard.overs_progression || []).map(o => o.score)], wickets: i.scorecard.overs_progression || [] }));
  if (!series.length) return null;
  const maxOvers = Math.max(...series.map(s => s.values.length - 1), 1);
  const maxRuns = Math.max(...series.flatMap(s => s.values), 10);
  const width = 900, height = 240, left = 40, right = 12, top = 12, bottom = 28;
  const x = o => left + (o / maxOvers) * (width - left - right);
  const y = r => top + (1 - r / maxRuns) * (height - top - bottom);
  const dash = { 1: '0', 2: '0', 3: '6 4', 4: '6 4' };
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-400">
        {series.map(s => <span key={s.key} className="inline-flex items-center gap-1"><i className="h-2 w-2 rounded-full" style={{ background: TEAM_COLORS[s.team] }} />{s.label}</span>)}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label="Cumulative runs by over (worm)">
        {[0, 0.25, 0.5, 0.75, 1].map(v => (
          <g key={v}><line x1={left} x2={width - right} y1={y(maxRuns * v)} y2={y(maxRuns * v)} stroke="#1e293b" />
            <text x={left - 6} y={y(maxRuns * v) + 3} textAnchor="end" fontSize="10" fill="#64748b">{Math.round(maxRuns * v)}</text></g>
        ))}
        {series.map(s => (
          <g key={s.key}>
            <polyline points={s.values.map((v, i) => `${x(i)},${y(v)}`).join(' ')} fill="none" stroke={TEAM_COLORS[s.team]} strokeWidth="2.5" strokeDasharray={dash[s.key] || '0'} />
            {s.wickets.map((o, i) => o.wickets > 0 && (
              <circle key={i} cx={x(i + 1)} cy={y(o.score)} r={3 + o.wickets} fill="#0f172a" stroke={TEAM_COLORS[s.team]} strokeWidth="2">
                <title>{`${s.label}: ${o.wickets} wicket${o.wickets > 1 ? 's' : ''} in over ${o.over} (${o.score})`}</title>
              </circle>
            ))}
          </g>
        ))}
        {Array.from({ length: Math.min(maxOvers, 10) + 1 }, (_, k) => Math.round((k * maxOvers) / Math.min(maxOvers, 10))).map(o => (
          <text key={o} x={x(o)} y={height - 10} textAnchor="middle" fontSize="10" fill="#64748b">{o}</text>
        ))}
      </svg>
    </div>
  );
}

export function OverBars({ overs = [], color = TEAM_COLORS.A }) {
  if (!overs.length) return null;
  const max = Math.max(...overs.map(o => o.runs), 6);
  const width = 900, height = 160, left = 28, bottom = 22, top = 8;
  const bw = (width - left) / overs.length;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label="Runs per over">
      {[0.5, 1].map(v => <g key={v}><line x1={left} x2={width} y1={top + (1 - v) * (height - top - bottom)} y2={top + (1 - v) * (height - top - bottom)} stroke="#1e293b" />
        <text x={left - 4} y={top + (1 - v) * (height - top - bottom) + 3} fontSize="9" textAnchor="end" fill="#64748b">{Math.round(max * v)}</text></g>)}
      {overs.map((o, i) => {
        const h = (o.runs / max) * (height - top - bottom);
        return (
          <g key={o.over}>
            <rect x={left + i * bw + bw * 0.12} y={height - bottom - h} width={bw * 0.76} height={Math.max(h, 1)} rx="2" fill={color} opacity="0.8">
              <title>{`Over ${o.over}: ${o.runs} runs${o.wickets ? `, ${o.wickets} wkt` : ''} (${o.score})`}</title>
            </rect>
            {Array.from({ length: o.wickets }, (_, k) => <circle key={k} cx={left + i * bw + bw / 2} cy={height - bottom - h - 6 - k * 9} r="3.5" fill="#f87171" />)}
            {(overs.length <= 20 || o.over % 5 === 0) && <text x={left + i * bw + bw / 2} y={height - 7} fontSize="9" textAnchor="middle" fill="#64748b">{o.over}</text>}
          </g>
        );
      })}
    </svg>
  );
}

export function Histogram({ bins = [], color = '#818cf8', label = v => v, height = 150 }) {
  if (!bins.length) return <p className="py-4 text-center text-xs text-slate-500">No outcomes in this category.</p>;
  const max = Math.max(...bins.map(b => b.count), 1);
  const total = bins.reduce((a, b) => a + b.count, 0) || 1;
  return (
    <div className="flex items-end gap-0.5 border-b border-l border-slate-700 px-1 pt-2" style={{ height }} role="img" aria-label="Distribution">
      {bins.map((b, i) => (
        <div key={i} className="group relative flex h-full flex-1 flex-col justify-end" title={`${label(b)}: ${b.count} (${((100 * b.count) / total).toFixed(1)}%)`}>
          <div className="w-full rounded-t" style={{ height: `${Math.max(1.5, (b.count / max) * 100)}%`, background: color, opacity: 0.85 }} />
          {(bins.length <= 14 || i % Math.ceil(bins.length / 10) === 0) && <span className="absolute -bottom-4 left-1/2 -translate-x-1/2 whitespace-nowrap text-[9px] text-slate-500">{b.start ?? b.wickets}</span>}
        </div>
      ))}
    </div>
  );
}
