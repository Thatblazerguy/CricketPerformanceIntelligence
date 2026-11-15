/**
 * CPI chart library — dependency-free SVG charts.
 *
 * Conventions:
 *  - Every chart sits in a ChartPanel with title, subtitle, optional sample size,
 *    legend and footnote.
 *  - Missing values (null/undefined/NaN) are dropped, never drawn as zero.
 *  - Charts render at their measured pixel width so axis text stays legible on
 *    small screens; hover/focus shows an exact-value tooltip.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { SampleBadge } from './ui';

// Colours are CSS variables (src/index.css) so every chart re-themes with the app.
// c1 blue is the primary highlight; c2 green / c6 red carry win-loss semantics.
export const PALETTE = ['var(--c1)', 'var(--c2)', 'var(--c3)', 'var(--c4)', 'var(--c5)', 'var(--c6)', 'var(--c7)', 'var(--c8)'];
export const POS = 'var(--c2)';
export const NEG = 'var(--c6)';
export const WARN = 'var(--c3)';
const GRID = 'var(--chart-grid)';
const BASE = 'var(--chart-base)';
const AXIS = 'var(--chart-axis)';
const LABEL = 'var(--chart-label)';
const REF = 'var(--chart-ref)';
const BG = 'var(--chart-bg)';
const STRONG = 'var(--chart-strong)';
const AXIS_FONT = { fontSize: 10.5, fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", Inter, system-ui, sans-serif', style: { fontVariantNumeric: 'tabular-nums' } };
const isNum = v => v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v));

/* ---------------------------------------------------------------- helpers */

function useWidth(fallback = 640) {
  const ref = useRef(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    if (!ref.current) return undefined;
    const el = ref.current;
    const update = () => setWidth(Math.max(260, Math.floor(el.getBoundingClientRect().width)));
    update();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

export function niceTicks(min, max, count = 5) {
  if (!isNum(min) || !isNum(max)) return [];
  if (min === max) { max = min + 1; }
  const span = max - min;
  const step0 = span / Math.max(1, count);
  const mag = 10 ** Math.floor(Math.log10(step0));
  const norm = step0 / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const start = Math.floor(min / step) * step;
  const ticks = [];
  for (let v = start; v <= max + step * 0.5; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks;
}

function useTooltip() {
  const [tip, setTip] = useState(null);
  const wrap = useRef(null);
  const show = useCallback((evt, content) => {
    const box = wrap.current?.getBoundingClientRect();
    if (!box) return;
    const p = evt.touches?.[0] || evt;
    const x = (p.clientX ?? box.left + box.width / 2) - box.left;
    const y = (p.clientY ?? box.top + 20) - box.top;
    setTip({ x, y, content, w: box.width });
  }, []);
  const hide = useCallback(() => setTip(null), []);
  const node = tip ? (
    <div role="tooltip" className="chart-tip glass-pop pointer-events-none absolute z-20 min-w-[9.5rem] max-w-[17rem] rounded-2xl px-3.5 py-2.5 text-xs leading-relaxed text-slate-200"
      style={{ left: tip.x + 14 + 200 > tip.w ? Math.max(4, tip.x - 14 - 200) : tip.x + 14, top: tip.y < 150 ? tip.y + 14 : tip.y - 12, transform: tip.y < 150 ? 'none' : 'translateY(-100%)', '--tip-ty': tip.y < 150 ? '0px' : '-100%' }}>
      {tip.content}
    </div>
  ) : null;
  return { wrap, show, hide, node };
}

/** Accessible hover target that also responds to keyboard focus. */
function hoverProps(tt, content) {
  return {
    onMouseMove: e => tt.show(e, content),
    onMouseLeave: tt.hide,
    onFocus: e => { const r = e.currentTarget.getBoundingClientRect(); tt.show({ clientX: r.left + r.width / 2, clientY: r.top }, content); },
    onBlur: tt.hide,
    onTouchStart: e => tt.show(e, content),
    tabIndex: 0,
    // No `style` here: spreading it would overwrite each mark's own inline style (position, colour, width).
  };
}

function TipRows({ title, rows }) {
  return (
    <div>
      {title && <div className="mb-1.5 border-b border-line pb-1.5 text-[12.5px] font-semibold tracking-[-0.01em] text-white">{title}</div>}
      {rows.filter(Boolean).map(([k, v, color]) => (
        <div key={k} className="flex items-center justify-between gap-4 py-px">
          <span className="flex items-center gap-1.5 text-slate-400">{color && <i className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: color }} />}{k}</span>
          <span className="num font-semibold text-white">{v}</span>
        </div>
      ))}
    </div>
  );
}

export function Legend({ items }) {
  if (!items?.length) return null;
  return (
    <div className="mb-3.5 flex flex-wrap gap-1.5 text-2xs text-slate-300">
      {items.map(it => (
        <span key={it.label} className="inline-flex items-center gap-1.5 rounded-full bg-white/[0.05] px-2.5 py-1">
          <i className={`inline-block ${it.line ? 'h-[2.5px] w-3.5 rounded-full' : 'h-2 w-2 rounded-full'}`} style={{ backgroundColor: it.color, ...(it.dashed ? { background: `repeating-linear-gradient(90deg, ${it.color} 0 3px, transparent 3px 5px)` } : {}) }} />
          {it.label}
        </span>
      ))}
    </div>
  );
}

export function ChartPanel({ title, subtitle, sample, sampleUnit, actions, legend, footnote, children, className = '' }) {
  return (
    <section className={`panel min-w-0 p-5 ${className}`}>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 max-w-2xl">
          <h3 className="text-[15px] font-semibold tracking-[-0.015em] text-white">{title}</h3>
          {subtitle && <p className="mt-1 text-xs leading-relaxed text-slate-500">{subtitle}</p>}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {isNum(sample) && <SampleBadge n={sample} unit={sampleUnit || 'obs'} />}
          {actions}
        </div>
      </div>
      <Legend items={legend} />
      {children}
      {footnote && <p className="mt-4 border-t border-line-soft pt-3 text-2xs leading-relaxed text-slate-500">{footnote}</p>}
    </section>
  );
}

const Empty = ({ text = 'No data available for this view.' }) => <div className="flex min-h-[8rem] flex-col items-center justify-center gap-2 rounded-2xl bg-white/[0.025] px-4 py-8 text-center text-xs text-slate-500"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true"><path d="M4 19.5h16M7 16V11M12 16V7M17 16v-3" /></svg>{text}</div>;

function YAxis({ ticks, y, left, right, width, fmt, label, height, top, bottom }) {
  return (
    <g>
      {ticks.map((t, i) => (
        <g key={t}>
          <line x1={left} x2={width - right} y1={y(t)} y2={y(t)} stroke={i === 0 ? BASE : GRID} strokeDasharray={i === 0 ? undefined : '2 3'} />
          <text x={left - 8} y={y(t) + 3.5} textAnchor="end" fill={AXIS} {...AXIS_FONT}>{fmt(t)}</text>
        </g>
      ))}
      {label && <text transform={`translate(11 ${(top + height - bottom) / 2}) rotate(-90)`} textAnchor="middle" fill={LABEL} fontSize="10.5" letterSpacing="0.02em">{label}</text>}
    </g>
  );
}

/* ------------------------------------------------------- horizontal bars */

export function BarChart({ title, subtitle, data = [], valueKey = 'value', labelKey = 'label', color = PALETTE[0], formatter = v => v, className = '', sample, sampleUnit, footnote, limit, unit, tooltip, actions }) {
  const tt = useTooltip();
  const rows = useMemo(() => {
    const r = data.filter(row => isNum(row[valueKey]));
    return limit ? r.slice(0, limit) : r;
  }, [data, valueKey, limit]);
  const max = Math.max(...rows.map(row => Math.abs(Number(row[valueKey]))), 0) || 1;
  return (
    <ChartPanel title={title} subtitle={subtitle} sample={sample} sampleUnit={sampleUnit} footnote={footnote} className={className} actions={actions}>
      {!rows.length ? <Empty /> : (
        <div ref={tt.wrap} className="relative space-y-2.5" role="list" aria-label={title}>
          {rows.map((row, i) => {
            const v = Number(row[valueKey]);
            const width = Math.max(v > 0 ? 1.5 : 0, Math.abs(v) / max * 100);
            const c = row.color || color;
            return (
              <div key={`${row[labelKey]}-${i}`} role="listitem" aria-label={`${row[labelKey]}: ${formatter(v)}`} {...hoverProps(tt, tooltip ? tooltip(row) : <TipRows title={String(row[labelKey])} rows={[[unit || 'Value', formatter(v), c], ...(row.detail ? [['', row.detail]] : [])]} />)}>
                <div className="mb-1 flex items-center justify-between gap-2 text-xs">
                  <span className="truncate text-slate-300">{row[labelKey]}</span>
                  <span className="num shrink-0 font-medium text-slate-100">{formatter(v)}</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-[var(--chart-track)]"><div className="chart-hbar h-full rounded-full transition-[width] duration-500 ease-out" style={{ width: `${width}%`, backgroundColor: c, animationDelay: `${Math.min(i, 12) * 25}ms` }} /></div>
              </div>
            );
          })}
          {tt.node}
        </div>
      )}
    </ChartPanel>
  );
}

/* ----------------------------------------------------- vertical columns */

/**
 * Vertical bars with optional overlay line (secondary axis) and point markers.
 * data: [{ label, value, color?, line?, markers?: n, tip?: ReactNode }]
 */
export function ColumnChart({ title, subtitle, data = [], formatter = v => v, lineFormatter = v => v, color = PALETTE[0], lineColor = PALETTE[2], lineLabel, barLabel, xLabel, yLabel, y2Label, markerLabel = 'Wickets', className = '', sample, sampleUnit, footnote, height = 240, actions, legend, referenceY, referenceLabel }) {
  const [ref, width] = useWidth();
  const tt = useTooltip();
  const rows = data.filter(d => isNum(d.value) || isNum(d.line));
  const hasLine = rows.some(d => isNum(d.line));
  const left = 44, right = hasLine ? (y2Label ? 58 : 44) : 12, top = 14, bottom = xLabel ? 38 : 26;
  const vals = rows.map(d => Number(d.value)).filter(isNum);
  const yTicks = niceTicks(0, Math.max(1, ...vals, isNum(referenceY) ? referenceY : 0), 4);
  const yMax = yTicks[yTicks.length - 1] || 1;
  const lineVals = rows.map(d => Number(d.line)).filter(isNum);
  const y2Ticks = hasLine ? niceTicks(Math.min(0, ...lineVals), Math.max(1, ...lineVals), 4) : [];
  const y2Min = y2Ticks[0] ?? 0, y2Max = y2Ticks[y2Ticks.length - 1] ?? 1;
  const plotW = width - left - right, plotH = height - top - bottom;
  const band = plotW / Math.max(1, rows.length);
  const x = i => left + band * i + band / 2;
  const y = v => top + plotH - (v / yMax) * plotH;
  const y2 = v => top + plotH - ((v - y2Min) / (y2Max - y2Min || 1)) * plotH;
  const every = Math.ceil(rows.length / Math.max(4, Math.floor(plotW / 34)));
  const legendItems = legend || [barLabel && { label: barLabel, color }, hasLine && lineLabel && { label: lineLabel, color: lineColor, line: true }, rows.some(r => r.markers) && { label: markerLabel, color: NEG }].filter(Boolean);
  return (
    <ChartPanel title={title} subtitle={subtitle} sample={sample} sampleUnit={sampleUnit} footnote={footnote} className={className} actions={actions} legend={legendItems}>
      <div ref={ref} className="relative w-full">
        <div ref={tt.wrap} className="relative">
          {!rows.length ? <Empty /> : (
            <svg width={width} height={height} role="img" aria-label={title}>
              <YAxis ticks={yTicks} y={y} left={left} right={right} width={width} fmt={formatter} label={yLabel} height={height} top={top} bottom={bottom} />
              {hasLine && y2Ticks.map(t => <text key={t} x={width - right + 6} y={y2(t) + 3.5} fill={AXIS} {...AXIS_FONT}>{lineFormatter(t)}</text>)}
              {hasLine && y2Label && <text transform={`translate(${width - 6} ${(top + height - bottom) / 2}) rotate(90)`} textAnchor="middle" fill={LABEL} fontSize="10.5">{y2Label}</text>}
              {isNum(referenceY) && <g><line x1={left} x2={width - right} y1={y(referenceY)} y2={y(referenceY)} stroke={REF} strokeOpacity="0.7" strokeDasharray="4 4" /><text x={width - right - 4} y={y(referenceY) - 4} textAnchor="end" fill={LABEL} fontSize="10">{referenceLabel}</text></g>}
              {rows.map((d, i) => {
                const v = Number(d.value);
                const bw = Math.max(2, Math.min(28, band * 0.7));
                return (
                  <g key={`${d.label}-${i}`} className="group/col" {...hoverProps(tt, d.tip || <TipRows title={String(d.label)} rows={[[barLabel || 'Value', formatter(v), d.color || color], hasLine && isNum(d.line) && [lineLabel || 'Line', lineFormatter(Number(d.line)), lineColor], d.markers ? [markerLabel, d.markers, NEG] : null]} />)}>
                    <rect x={x(i) - band / 2} y={top} width={band} height={plotH} fill="transparent" />
                    <rect x={x(i) - band / 2 + 1} y={top} width={Math.max(0, band - 2)} height={plotH} rx="2" fill={STRONG} className="opacity-0 transition-opacity group-hover/col:opacity-[0.05]" />
                    {isNum(d.value) && <rect className="chart-bar" style={{ animationDelay: `${Math.min(i, 40) * 8}ms` }} x={x(i) - bw / 2} y={y(Math.max(0, v))} width={bw} height={Math.max(0, y(0) - y(Math.max(0, v)))} rx={Math.min(4, bw / 3)} fill={d.color || color} fillOpacity="0.92" />}
                    {d.markers > 0 && (band < 9
                      // Dense charts: one marker per bar (exact count in the tooltip) so dots never tower over the bars.
                      ? <circle cx={x(i)} cy={y(Math.max(0, v)) - 4} r={Math.min(3, Math.max(1.6, band / 3))} fill={NEG} />
                      : Array.from({ length: d.markers }, (_, k) => <circle key={k} cx={x(i)} cy={y(Math.max(0, v)) - 6 - k * 9} r="3.5" fill={NEG} stroke={BG} strokeWidth="1.25" />))}
                    {(i % every === 0 || i === rows.length - 1) && <text x={x(i)} y={height - bottom + 15} textAnchor="middle" fill={AXIS} {...AXIS_FONT}>{d.label}</text>}
                  </g>
                );
              })}
              {hasLine && <polyline className="chart-line" pathLength="1" pointerEvents="none" fill="none" stroke={lineColor} strokeWidth="1.75" strokeLinejoin="round" strokeLinecap="round" points={rows.map((d, i) => isNum(d.line) ? `${x(i)},${y2(Number(d.line))}` : null).filter(Boolean).join(' ')} />}
              {xLabel && <text x={left + plotW / 2} y={height - 4} textAnchor="middle" fill={LABEL} fontSize="10.5">{xLabel}</text>}
            </svg>
          )}
          {tt.node}
        </div>
      </div>
    </ChartPanel>
  );
}

/* ------------------------------------------------------------- lines */

/**
 * Multi-series line chart on a numeric or categorical x axis.
 * series: [{ name, color?, dashed?, points: [{ x, y, label?, marker?, tip? }] }]
 */
export function MultiSeriesLine({ title, subtitle, series = [], xLabel, yLabel, xFormatter = v => v, yFormatter = v => v, className = '', sample, sampleUnit, footnote, height = 260, categorical = false, actions, references = [], yMin, minPoints = 2, emptyText, area }) {
  const [ref, width] = useWidth();
  const tt = useTooltip();
  const [hoverX, setHoverX] = useState(null);
  const gid = useMemo(() => `g${Math.random().toString(36).slice(2, 8)}`, []);
  const usable = series.map((s, i) => ({ ...s, color: s.color || PALETTE[i % PALETTE.length], points: (s.points || []).filter(p => isNum(p.y) && (categorical || isNum(p.x))) })).filter(s => s.points.length >= minPoints || (s.points.length && s.allowSingle));
  const cats = categorical ? [...new Set(usable.flatMap(s => s.points.map(p => p.x)))] : [];
  const xs = categorical ? cats.map((_, i) => i) : usable.flatMap(s => s.points.map(p => Number(p.x)));
  const ys = usable.flatMap(s => s.points.map(p => Number(p.y))).concat(references.filter(r => r.axis !== 'x').map(r => r.value));
  const left = 48, right = 16, top = 14, bottom = xLabel ? 42 : 28;
  const plotW = width - left - right, plotH = height - top - bottom;
  const yTicks = niceTicks(isNum(yMin) ? yMin : Math.min(0, ...ys), Math.max(1, ...ys), 4);
  const lo = yTicks[0] ?? 0, hi = yTicks[yTicks.length - 1] ?? 1;
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  const sx = v => left + (categorical ? (cats.length > 1 ? cats.indexOf(v) / (cats.length - 1) : 0.5) : (Number(v) - xMin) / ((xMax - xMin) || 1)) * plotW;
  const sy = v => top + plotH - ((Number(v) - lo) / ((hi - lo) || 1)) * plotH;
  const xTicks = categorical ? cats.filter((_, i) => i % Math.ceil(cats.length / Math.max(3, Math.floor(plotW / 60))) === 0 || i === cats.length - 1) : niceTicks(xMin, xMax, Math.max(3, Math.floor(plotW / 70))).filter(t => t >= xMin && t <= xMax);
  // Single-series trends get a soft area fill unless explicitly disabled.
  const showArea = area ?? usable.length === 1;
  const key = p => (categorical ? String(p.x) : Number(p.x));
  const allX = useMemo(() => [...new Set(usable.flatMap(s => s.points.map(key)))], [usable]); // eslint-disable-line react-hooks/exhaustive-deps

  const onMove = evt => {
    const box = evt.currentTarget.ownerSVGElement?.getBoundingClientRect() || evt.currentTarget.getBoundingClientRect();
    const px = (evt.touches?.[0] || evt).clientX - box.left;
    let best = null, bestD = Infinity;
    allX.forEach(xv => { const d = Math.abs(sx(xv) - px); if (d < bestD) { bestD = d; best = xv; } });
    if (best === null) return;
    setHoverX(best);
    const hits = usable.map(s => ({ s, p: s.points.find(p => key(p) === best) })).filter(h => h.p);
    const content = hits.length === 1 && hits[0].p.tip ? hits[0].p.tip
      : hits.some(h => h.p.tip) ? <div className="space-y-2">{hits.map(h => <div key={h.s.name}><div className="mb-0.5 flex items-center gap-1.5 text-3xs uppercase tracking-wide text-slate-500"><i className="h-[2px] w-3 rounded-full" style={{ backgroundColor: h.s.color }} />{h.s.name}</div>{h.p.tip || yFormatter(Number(h.p.y))}</div>)}</div>
      : <TipRows title={hits[0]?.p.label || `${xLabel || ''} ${xFormatter(best)}`.trim()} rows={hits.map(h => [h.s.name, yFormatter(Number(h.p.y)), h.s.color])} />;
    tt.show(evt, content);
  };
  const onLeave = () => { setHoverX(null); tt.hide(); };

  return (
    <ChartPanel title={title} subtitle={subtitle} sample={sample} sampleUnit={sampleUnit} footnote={footnote} className={className} actions={actions}
      legend={usable.length > 1 || references.length ? [...usable.map(s => ({ label: s.name, color: s.color, line: true, dashed: s.dashed })), ...references.map(r => ({ label: r.label, color: r.color || REF, line: true, dashed: true }))] : null}>
      <div ref={ref} className="relative w-full">
        <div ref={tt.wrap} className="relative">
          {!usable.length ? <Empty text={emptyText || 'At least two observations are needed to draw a trend.'} /> : (
            <svg width={width} height={height} role="img" aria-label={title}>
              <defs>
                {usable.map((s, i) => (
                  <linearGradient key={i} id={`${gid}-${i}`} x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor={s.color} stopOpacity="0.24" />
                    <stop offset="100%" stopColor={s.color} stopOpacity="0" />
                  </linearGradient>
                ))}
              </defs>
              <YAxis ticks={yTicks} y={sy} left={left} right={right} width={width} fmt={yFormatter} label={yLabel} height={height} top={top} bottom={bottom} />
              {xTicks.map(t => <text key={String(t)} x={sx(t)} y={height - bottom + 15} textAnchor="middle" fill={AXIS} {...AXIS_FONT}>{xFormatter(t)}</text>)}
              {references.map(r => r.axis === 'x'
                ? <g key={r.label}><line x1={sx(r.value)} x2={sx(r.value)} y1={top} y2={top + plotH} stroke={r.color || REF} strokeOpacity="0.7" strokeDasharray="4 4" /><text x={sx(r.value) + 4} y={top + 10} fill={LABEL} fontSize="10">{r.label}</text></g>
                : <g key={r.label}><line x1={left} x2={width - right} y1={sy(r.value)} y2={sy(r.value)} stroke={r.color || REF} strokeOpacity="0.7" strokeDasharray="4 4" /><text x={width - right - 4} y={sy(r.value) - 5} textAnchor="end" fill={LABEL} fontSize="10">{r.label}</text></g>)}
              {usable.map((s, si) => {
                const pts = s.points.map(p => `${sx(p.x)},${sy(p.y)}`);
                const base = sy(Math.max(lo, Math.min(hi, 0)));
                return (
                  <g key={s.name}>
                    {showArea && !s.dashed && <polygon points={`${sx(s.points[0].x)},${base} ${pts.join(' ')} ${sx(s.points[s.points.length - 1].x)},${base}`} fill={`url(#${gid}-${si})`} className="animate-fade-in" />}
                    <polyline className={s.dashed ? '' : 'chart-line'} pathLength={s.dashed ? undefined : 1} fill="none" stroke={s.color} strokeWidth={s.width || 2} strokeDasharray={s.dashed ? '5 4' : undefined} strokeLinejoin="round" strokeLinecap="round" points={pts.join(' ')} />
                    {s.points.map((p, i) => {
                      const hot = hoverX !== null && key(p) === hoverX;
                      const dense = s.points.length > 40;
                      return (
                        <g key={i} {...hoverProps(tt, p.tip || <TipRows title={p.label || `${xLabel || 'x'} ${xFormatter(p.x)}`} rows={[[s.name, yFormatter(Number(p.y)), s.color]]} />)}>
                          <circle cx={sx(p.x)} cy={sy(p.y)} r={p.marker ? 4 : hot ? 4.5 : dense ? 0 : 2.75} fill={p.marker ? NEG : hot ? BG : s.color} stroke={p.marker ? BG : hot ? s.color : 'none'} strokeWidth={hot ? 2 : 1.25} />
                        </g>
                      );
                    })}
                  </g>
                );
              })}
              {hoverX !== null && <line x1={sx(hoverX)} x2={sx(hoverX)} y1={top} y2={top + plotH} stroke={LABEL} strokeOpacity="0.5" strokeDasharray="3 3" pointerEvents="none" />}
              <rect x={left} y={top} width={Math.max(0, plotW)} height={Math.max(0, plotH)} fill="transparent" onMouseMove={onMove} onMouseLeave={onLeave} onTouchStart={onMove} onTouchMove={onMove} onTouchEnd={onLeave} style={{ cursor: 'crosshair' }} />
              {xLabel && <text x={left + plotW / 2} y={height - 4} textAnchor="middle" fill={LABEL} fontSize="10.5">{xLabel}</text>}
            </svg>
          )}
          {tt.node}
        </div>
      </div>
    </ChartPanel>
  );
}

/** Backwards-compatible single-series line over categorical labels. */
export function LineChart({ title, subtitle, data = [], xKey = 'label', yKey = 'value', color = PALETTE[0], formatter = v => v, className = '', xLabel, yLabel, sample, sampleUnit, footnote }) {
  return <MultiSeriesLine title={title} subtitle={subtitle} className={className} categorical xLabel={xLabel} yLabel={yLabel} yFormatter={formatter} sample={sample} sampleUnit={sampleUnit} footnote={footnote}
    series={[{ name: yLabel || title, color, points: data.map(d => ({ x: d[xKey], y: d[yKey], label: String(d[xKey]), tip: d.tip })) }]} />;
}

/** Recent-form comparison (kept for existing callers): values aligned by appearance index. */
export function MultiLineChart({ title, subtitle, series = [], className = '' }) {
  return <MultiSeriesLine title={title} subtitle={subtitle} className={className} xLabel="Recent appearances (oldest → latest)" yLabel="Runs" xFormatter={v => `#${v}`}
    emptyText="Select a player with at least two recent match observations."
    series={series.map(s => ({ name: s.name, points: (s.values || []).filter(p => isNum(p.value)).map((p, i) => ({ x: i + 1, y: Number(p.value), label: p.date || `Appearance ${i + 1}` })) }))} />;
}

/* ---------------------------------------------------- histogram / grouped */

/**
 * Grouped vertical bars over shared categories.
 * categories: [label]; series: [{ name, color?, values: [number|null] }]
 */
export function GroupedBarChart({ title, subtitle, categories = [], series = [], formatter = v => v, yLabel, xLabel, className = '', sample, sampleUnit, footnote, height = 240, actions, stacked = false }) {
  const [ref, width] = useWidth();
  const tt = useTooltip();
  const ser = series.map((s, i) => ({ ...s, color: s.color || PALETTE[i % PALETTE.length] }));
  const hasData = ser.some(s => s.values?.some(isNum));
  const left = 46, right = 12, top = 14, bottom = xLabel ? 40 : 28;
  const plotW = width - left - right, plotH = height - top - bottom;
  const totals = categories.map((_, ci) => stacked ? ser.reduce((a, s) => a + (isNum(s.values?.[ci]) ? Number(s.values[ci]) : 0), 0) : Math.max(0, ...ser.map(s => (isNum(s.values?.[ci]) ? Number(s.values[ci]) : 0))));
  const yTicks = niceTicks(0, Math.max(1, ...totals), 4);
  const yMax = yTicks[yTicks.length - 1] || 1;
  const band = plotW / Math.max(1, categories.length);
  const y = v => top + plotH - (v / yMax) * plotH;
  const inner = Math.min(band * 0.8, stacked ? 30 : 18 * ser.length);
  const bw = stacked ? inner : inner / Math.max(1, ser.length);
  const maxLabel = Math.max(1, ...categories.map(c => String(c).length));
  const every = Math.max(1, Math.ceil(categories.length / Math.max(2, Math.floor(plotW / (maxLabel * 6.2 + 10)))));
  // Only force the final label when it will not collide with the previous tick label.
  const showLast = (categories.length - 1) % every >= every / 2 || every === 1;
  return (
    <ChartPanel title={title} subtitle={subtitle} sample={sample} sampleUnit={sampleUnit} footnote={footnote} className={className} actions={actions}
      legend={ser.length > 1 ? ser.map(s => ({ label: s.name, color: s.color })) : null}>
      <div ref={ref} className="relative w-full">
        <div ref={tt.wrap} className="relative">
          {!hasData ? <Empty /> : (
            <svg width={width} height={height} role="img" aria-label={title}>
              <YAxis ticks={yTicks} y={y} left={left} right={right} width={width} fmt={formatter} label={yLabel} height={height} top={top} bottom={bottom} />
              {categories.map((cat, ci) => {
                const cx = left + band * ci + band / 2;
                let acc = 0;
                const tip = <TipRows title={String(cat)} rows={ser.map(s => [s.name, isNum(s.values?.[ci]) ? formatter(Number(s.values[ci])) : '—', s.color])} />;
                return (
                  <g key={`${cat}-${ci}`} className="group/col" {...hoverProps(tt, tip)}>
                    <rect x={cx - band / 2 + 1} y={top} width={Math.max(0, band - 2)} height={plotH} rx="4" fill={STRONG} fillOpacity="0" className="transition-[fill-opacity] group-hover/col:[fill-opacity:0.05]" />
                    {ser.map((s, si) => {
                      const v = s.values?.[ci];
                      if (!isNum(v)) return null;
                      const val = Number(v);
                      if (stacked) { const y0 = y(acc), y1 = y(acc + val); acc += val; return <rect key={si} x={cx - bw / 2} y={y1} width={bw} height={Math.max(0, y0 - y1)} fill={s.color} stroke={BG} strokeWidth="0.75" />; }
                      return <rect key={si} className="chart-bar" style={{ animationDelay: `${Math.min(ci, 30) * 12}ms` }} x={cx - inner / 2 + si * bw + 1} y={y(Math.max(0, val))} width={Math.max(1, bw - 2)} height={Math.max(0, y(0) - y(Math.max(0, val)))} rx={Math.min(4, bw / 3)} fill={s.color} />;
                    })}
                    {(ci % every === 0 || (ci === categories.length - 1 && showLast)) && <text x={ci === categories.length - 1 && categories.length > 4 ? Math.min(cx, width - right - 2) : cx} y={height - bottom + 14} textAnchor={ci === categories.length - 1 && categories.length > 4 && cx + 18 > width - right ? 'end' : 'middle'} fill={AXIS} {...AXIS_FONT}>{cat}</text>}
                  </g>
                );
              })}
              {xLabel && <text x={left + plotW / 2} y={height - 4} textAnchor="middle" fill={LABEL} fontSize="10.5">{xLabel}</text>}
            </svg>
          )}
          {tt.node}
        </div>
      </div>
    </ChartPanel>
  );
}

/** Histogram over API-provided bins: bins [{ label, count }] or multiple series. */
export function Histogram({ title, subtitle, bins = [], series, xLabel, yLabel = 'Count', className = '', sample, sampleUnit, footnote, color = PALETTE[0], height = 230, actions }) {
  const ser = series || [{ name: yLabel, color, values: bins.map(b => b.count) }];
  return <GroupedBarChart title={title} subtitle={subtitle} categories={bins.map(b => b.label)} series={ser} formatter={v => Math.round(v).toLocaleString()} xLabel={xLabel} yLabel={yLabel} className={className} sample={sample} sampleUnit={sampleUnit} footnote={footnote} height={height} actions={actions} />;
}

/* ------------------------------------------------------------ stacked */

/**
 * Horizontal 100% / absolute stacked bars.
 * rows: [{ label, segments: [{ name, value, color? }], sub? }]
 */
export function StackedBar({ title, subtitle, rows = [], formatter = v => Math.round(v).toLocaleString(), percent = false, className = '', sample, sampleUnit, footnote, legend }) {
  const tt = useTooltip();
  const usable = rows.filter(r => r.segments?.some(s => isNum(s.value) && Number(s.value) > 0));
  const max = Math.max(1, ...usable.map(r => r.segments.reduce((a, s) => a + (isNum(s.value) ? Number(s.value) : 0), 0)));
  const names = legend || [...new Map(usable.flatMap(r => r.segments).map((s, i) => [s.name, { label: s.name, color: s.color || PALETTE[i % PALETTE.length] }])).values()];
  return (
    <ChartPanel title={title} subtitle={subtitle} sample={sample} sampleUnit={sampleUnit} footnote={footnote} className={className} legend={names}>
      {!usable.length ? <Empty /> : (
        <div ref={tt.wrap} className="relative space-y-3">
          {usable.map((r, ri) => {
            const total = r.segments.reduce((a, s) => a + (isNum(s.value) ? Number(s.value) : 0), 0);
            return (
              <div key={`${r.label}-${ri}`}>
                <div className="mb-1 flex justify-between gap-2 text-xs"><span className="truncate text-slate-300">{r.label}</span><span className="num shrink-0 text-slate-400">{r.sub ?? formatter(total)}</span></div>
                <div className="chart-hbar flex h-3.5 overflow-hidden rounded-full bg-[var(--chart-track)]" style={{ width: percent ? '100%' : `${Math.max(4, total / max * 100)}%`, animationDelay: `${Math.min(ri, 12) * 30}ms` }}>
                  {r.segments.filter(s => isNum(s.value) && Number(s.value) > 0).map((s, si) => {
                    const share = Number(s.value) / total * 100;
                    const c = s.color || names.find(n => n.label === s.name)?.color || PALETTE[si % PALETTE.length];
                    return (
                      <div key={s.name} className="h-full border-r-2 border-surface transition-opacity last:border-0 hover:opacity-80" style={{ width: `${share}%`, backgroundColor: c }}
                        {...hoverProps(tt, <TipRows title={r.label} rows={[[s.name, `${formatter(Number(s.value))} (${share.toFixed(1)}%)`, c], ...(s.detail ? [['', s.detail]] : [])]} />)} />
                    );
                  })}
                </div>
              </div>
            );
          })}
          {tt.node}
        </div>
      )}
    </ChartPanel>
  );
}

/* ---------------------------------------------------------- donut */

export function DonutChart({ title, subtitle, data = [], valueKey = 'value', labelKey = 'label', className = '', sample, sampleUnit, footnote, centerLabel = 'TOTAL' }) {
  const tt = useTooltip();
  const rows = data.filter(row => isNum(row[valueKey]) && Number(row[valueKey]) > 0);
  const total = rows.reduce((sum, row) => sum + Number(row[valueKey]), 0);
  let offset = 0;
  const segments = rows.map((row, index) => { const share = Number(row[valueKey]) / total; const r = { ...row, share, offset, color: row.color || PALETTE[index % PALETTE.length] }; offset += share; return r; });
  return (
    <ChartPanel title={title} subtitle={subtitle} sample={sample} sampleUnit={sampleUnit} footnote={footnote} className={className}>
      {!total ? <Empty /> : (
        <div ref={tt.wrap} className="relative flex flex-wrap items-center justify-center gap-6">
          <svg viewBox="0 0 120 120" className="h-36 w-36 shrink-0" role="img" aria-label={title}>
            <circle cx="60" cy="60" r="43" fill="none" stroke="var(--chart-track)" strokeWidth="14" />
            {segments.map((row, i) => <circle key={`${row[labelKey]}-${i}`} cx="60" cy="60" r="43" fill="none" stroke={row.color} strokeWidth="14" pathLength="100" className="transition-[stroke-width] duration-150 hover:[stroke-width:17]" strokeDasharray={`${row.share * 100} ${100 - row.share * 100}`} strokeDashoffset={-row.offset * 100} transform="rotate(-90 60 60)"
              {...hoverProps(tt, <TipRows title={String(row[labelKey])} rows={[['Count', Number(row[valueKey]).toLocaleString(), row.color], ['Share', `${(row.share * 100).toFixed(1)}%`]]} />)} />)}
            <text x="60" y="59" textAnchor="middle" fill={STRONG} fontSize="15" fontWeight="600" style={{ fontVariantNumeric: 'tabular-nums', letterSpacing: '-0.02em' }}>{total.toLocaleString()}</text>
            <text x="60" y="72" textAnchor="middle" fill={AXIS} fontSize="6.5" letterSpacing="1.2" fontWeight="600">{centerLabel}</text>
          </svg>
          <div className="space-y-1.5 text-xs">{segments.map((row, i) => <div key={`${row[labelKey]}-${i}`} className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: row.color }} /><span className="text-slate-400">{row[labelKey]}</span><strong className="num font-medium text-slate-200">{Number(row[valueKey]).toLocaleString()}</strong><span className="num text-slate-500">{(row.share * 100).toFixed(1)}%</span></div>)}</div>
          {tt.node}
        </div>
      )}
    </ChartPanel>
  );
}

/* ---------------------------------------------------------- radar */

/**
 * Radar over 0–100 scores. When `values` are raw metrics, scores are min–max
 * normalised within the selected players (legacy behaviour); pass `scaled`
 * when values are already percentiles.
 */
export function RadarChart({ title, subtitle, series = [], metrics = [], className = '', scaled = false, footnote }) {
  const tt = useTooltip();
  const axes = metrics.filter(m => series.length > 0 && series.every(p => isNum(p.values?.[m.key])) && (scaled || series.length > 1));
  const cx = 170, cy = 150, radius = 105, count = axes.length;
  const score = (player, m) => {
    const v = Number(player.values[m.key]);
    if (scaled) return Math.max(0, Math.min(1, v / 100));
    const vals = series.map(c => Number(c.values[m.key]));
    const min = Math.min(...vals), max = Math.max(...vals);
    let s = max === min ? 1 : (v - min) / (max - min);
    if (m.lowerIsBetter) s = 1 - s;
    return s;
  };
  const pt = (i, s) => { const a = -Math.PI / 2 + i * Math.PI * 2 / count; return { x: cx + Math.cos(a) * radius * s, y: cy + Math.sin(a) * radius * s }; };
  return (
    <ChartPanel title={title} subtitle={subtitle} className={className} legend={series.map((p, i) => ({ label: p.name, color: p.color || PALETTE[i % PALETTE.length] }))}
      footnote={footnote ?? (scaled ? 'Axes show cohort percentiles (100 = best in cohort; lower-is-better metrics inverted).' : 'Axes are normalised within the selected players. Economy and bowling average score lower values as better.')}>
      {count < 3 ? <Empty text="At least three metrics with values for every selected player are needed." /> : (
        <div ref={tt.wrap} className="relative">
          <svg viewBox="-44 -6 428 312" className="mx-auto w-full max-w-lg" role="img" aria-label={title}>
            {[0.25, 0.5, 0.75, 1].map(s => <polygon key={s} points={axes.map((_, i) => { const p = pt(i, s); return `${p.x},${p.y}`; }).join(' ')} fill="none" stroke={GRID} />)}
            {axes.map((m, i) => { const p = pt(i, 1.16), e = pt(i, 1); return <g key={m.key}><line x1={cx} y1={cy} x2={e.x} y2={e.y} stroke={GRID} /><text x={p.x} y={p.y} textAnchor={p.x < cx - 8 ? 'end' : p.x > cx + 8 ? 'start' : 'middle'} dominantBaseline="middle" fill={LABEL} fontSize="9.5">{m.label}</text></g>; })}
            {series.map((p, si) => {
              const color = p.color || PALETTE[si % PALETTE.length];
              const pts = axes.map((m, i) => pt(i, score(p, m)));
              return (
                <g key={p.name}>
                  <polygon points={pts.map(q => `${q.x},${q.y}`).join(' ')} fill={color} fillOpacity=".12" stroke={color} strokeWidth="1.75" strokeLinejoin="round" className="animate-fade-in" />
                  {pts.map((q, i) => <circle key={i} cx={q.x} cy={q.y} r="3" fill={color} {...hoverProps(tt, <TipRows title={p.name} rows={[[axes[i].label, p.display?.[axes[i].key] ?? Number(p.values[axes[i].key]).toFixed(1), color]]} />)} />)}
                </g>
              );
            })}
          </svg>
          {tt.node}
        </div>
      )}
    </ChartPanel>
  );
}

/* ---------------------------------------------------------- scatter */

export function ScatterChart({ title, subtitle, data = [], xKey, yKey, xLabel, yLabel, formatX = v => v, formatY = v => v, className = '', footnote, references = [], height = 280, highlightKey = 'highlight', onPointClick }) {
  const [ref, width] = useWidth();
  const tt = useTooltip();
  const rows = data.filter(r => isNum(r[xKey]) && isNum(r[yKey]));
  const groups = [...new Map(rows.filter(r => r.group).map(r => [r.group, { label: r.group, color: r.color || PALETTE[0] }])).values()];
  const left = 50, right = 14, top = 14, bottom = 40;
  const plotW = width - left - right, plotH = height - top - bottom;
  const xs = rows.map(r => Number(r[xKey])), ys = rows.map(r => Number(r[yKey]));
  const xt = niceTicks(Math.min(...xs), Math.max(...xs), Math.max(3, Math.floor(plotW / 80))), yt = niceTicks(Math.min(...ys), Math.max(...ys), 4);
  const x0 = xt[0], x1 = xt[xt.length - 1], y0 = yt[0], y1 = yt[yt.length - 1];
  const sx = v => left + (v - x0) / ((x1 - x0) || 1) * plotW;
  const sy = v => top + plotH - (v - y0) / ((y1 - y0) || 1) * plotH;
  const ordered = [...rows].sort((a, b) => Number(Boolean(a[highlightKey])) - Number(Boolean(b[highlightKey])));
  return (
    <ChartPanel title={title} subtitle={subtitle} className={className} footnote={footnote} sample={rows.length} sampleUnit="points" legend={groups.length ? groups : null}>
      <div ref={ref} className="relative w-full">
        <div ref={tt.wrap} className="relative">
          {!rows.length ? <Empty text="No paired observations available." /> : (
            <svg width={width} height={height} role="img" aria-label={title}>
              <YAxis ticks={yt} y={sy} left={left} right={right} width={width} fmt={formatY} label={yLabel} height={height} top={top} bottom={bottom} />
              {xt.map(t => <g key={t}><line x1={sx(t)} x2={sx(t)} y1={top} y2={top + plotH} stroke={GRID} strokeDasharray="2 3" /><text x={sx(t)} y={height - bottom + 15} textAnchor="middle" fill={AXIS} {...AXIS_FONT}>{formatX(t)}</text></g>)}
              {references.map(r => r.axis === 'x'
                ? <line key={r.label} x1={sx(r.value)} x2={sx(r.value)} y1={top} y2={top + plotH} stroke={REF} strokeOpacity="0.6" strokeDasharray="4 4"><title>{r.label}</title></line>
                : <line key={r.label} x1={left} x2={width - right} y1={sy(r.value)} y2={sy(r.value)} stroke={REF} strokeOpacity="0.6" strokeDasharray="4 4"><title>{r.label}</title></line>)}
              {ordered.map((r, i) => {
                const hl = r[highlightKey];
                return (
                  <g key={`${r.name || r.label || i}-${i}`} onClick={onPointClick ? () => onPointClick(r) : undefined} {...hoverProps(tt, <TipRows title={r.name || r.label || 'Observation'} rows={[[xLabel, formatX(Number(r[xKey]))], [yLabel, formatY(Number(r[yKey]))], r.detail ? ['', r.detail] : null]} />)}>
                    {hl && <circle cx={sx(Number(r[xKey]))} cy={sy(Number(r[yKey]))} r="9" fill="none" stroke={r.color || STRONG} strokeWidth="2" />}
                    <circle cx={sx(Number(r[xKey]))} cy={sy(Number(r[yKey]))} r={hl ? 5.5 : r.size ? Math.max(2.5, Math.min(8, Number(r.size))) : 3.5} fill={r.color || PALETTE[0]} fillOpacity={hl ? 1 : r.muted ? 0.25 : 0.72} stroke={hl ? BG : 'none'} className="transition-[r] duration-150" />
                    {hl && r.name && <text x={sx(Number(r[xKey])) + 11} y={sy(Number(r[yKey])) + 4} fill={STRONG} fontSize="10.5" fontWeight="500">{r.name}</text>}
                  </g>
                );
              })}
              <text x={left + plotW / 2} y={height - 4} textAnchor="middle" fill={LABEL} fontSize="10.5">{xLabel}</text>
            </svg>
          )}
          {tt.node}
        </div>
      </div>
    </ChartPanel>
  );
}

export function PlayerScatterPlot({ title, subtitle, data = [], xKey = 'batting_average', yKey = 'strike_rate', xLabel = 'Batting average', yLabel = 'Strike rate', referenceX, referenceY, highlightedIds = [], onPointClick, className = '' }) {
  const roleColor = role => /all-rounder/i.test(role || '') ? PALETTE[2] : /wicketkeeper/i.test(role || '') ? PALETTE[3] : /bowler/i.test(role || '') ? PALETTE[5] : PALETTE[0];
  const hl = new Set(highlightedIds);
  const rows = data.map(r => ({ ...r, name: r.player_name, group: r.role || 'Unclassified', color: roleColor(r.role), highlight: hl.has(r.player_id),
    detail: `${r.role || 'Unclassified'} · ${r.matches} matches · ${r.innings} inns · ${r.runs ?? '—'} runs` }));
  const refs = [isNum(referenceX) && { axis: 'x', value: Number(referenceX), label: `Cohort mean average ${Number(referenceX).toFixed(2)}` }, isNum(referenceY) && { axis: 'y', value: Number(referenceY), label: `Cohort mean SR ${Number(referenceY).toFixed(1)}` }].filter(Boolean);
  return <ScatterChart title={title} subtitle={subtitle} data={rows} xKey={xKey} yKey={yKey} xLabel={xLabel} yLabel={yLabel} formatX={v => Number(v).toFixed(0)} formatY={v => Number(v).toFixed(0)} references={refs} height={400} className={className} onPointClick={onPointClick}
    footnote="Dashed lines mark the eligible cohort's mean batting average and strike rate. Hover a point for its sample; click to open the profile; select players in the table to highlight them." />;
}

/* ------------------------------------------------------- ranges / pct */

export function RangeChart({ title, subtitle, data = [], labelKey = 'label', lowKey = 'low', valueKey = 'value', highKey = 'high', formatter = v => v, className = '' }) {
  const rows = data.filter(r => [r[lowKey], r[valueKey], r[highKey]].every(isNum));
  const min = Math.min(0, ...rows.map(r => Number(r[lowKey]))), max = Math.max(1, ...rows.map(r => Number(r[highKey]))), span = max - min || 1;
  return (
    <ChartPanel title={title} subtitle={subtitle} className={className}>
      {!rows.length ? <Empty text="No confidence ranges available." /> : (
        <div className="space-y-3">{rows.map((r, i) => {
          const l = (Number(r[lowKey]) - min) / span * 100, w = Math.max(1, (Number(r[highKey]) - Number(r[lowKey])) / span * 100), p = (Number(r[valueKey]) - min) / span * 100;
          return <div key={`${r[labelKey]}-${i}`} title={`${r[labelKey]}: ${formatter(r[lowKey])}–${formatter(r[highKey])} · estimate ${formatter(r[valueKey])}`}>
            <div className="mb-1 flex justify-between gap-2 text-xs"><span className="truncate text-slate-400">{r[labelKey]}</span><span className="num shrink-0 text-slate-200">{formatter(r[valueKey])}</span></div>
            <div className="relative h-2 rounded-full bg-[var(--chart-track)]"><div className="absolute h-full rounded-full bg-accent/40" style={{ left: `${l}%`, width: `${w}%` }} /><div className="absolute -top-1 h-4 w-[3px] -translate-x-1/2 rounded-full bg-white shadow" style={{ left: `${p}%` }} /></div>
            <div className="num mt-1 flex justify-between text-2xs text-slate-600"><span>{formatter(r[lowKey])}</span><span>{formatter(r[highKey])}</span></div>
          </div>;
        })}</div>
      )}
    </ChartPanel>
  );
}

/**
 * Percentile bars for several players across metrics.
 * metrics: [{ key, label, display? }]; players: [{ name, color, percentiles: {key: 0-100}, raw?: {key: string} }]
 */
export function PercentileBars({ title, subtitle, metrics = [], players = [], className = '', footnote, sample, sampleUnit }) {
  const tt = useTooltip();
  return (
    <ChartPanel title={title} subtitle={subtitle} className={className} footnote={footnote} sample={sample} sampleUnit={sampleUnit} legend={players.map((p, i) => ({ label: p.name, color: p.color || PALETTE[i % PALETTE.length] }))}>
      <div ref={tt.wrap} className="relative space-y-3">
        {metrics.map(m => (
          <div key={m.key}>
            <div className="mb-1 text-xs text-slate-400">{m.label}</div>
            <div className="relative h-5 rounded-full bg-[var(--chart-track)]">
              {[25, 50, 75].map(t => <div key={t} className={`absolute top-0 h-full w-px ${t === 50 ? 'bg-slate-500/50' : 'bg-slate-500/20'}`} style={{ left: `${t}%` }} />)}
              {players.map((p, i) => {
                const v = p.percentiles?.[m.key];
                if (!isNum(v)) return null;
                const c = p.color || PALETTE[i % PALETTE.length];
                return <div key={p.name} className="absolute top-0.5 h-4 w-1.5 -translate-x-1/2 rounded-full ring-2 ring-surface" style={{ left: `${v}%`, backgroundColor: c }}
                  {...hoverProps(tt, <TipRows title={p.name} rows={[[m.label, p.raw?.[m.key] ?? '—', c], ['Percentile', `${Number(v).toFixed(0)}th`]]} />)} />;
              })}
            </div>
          </div>
        ))}
        <div className="num flex justify-between text-2xs text-slate-600"><span>0</span><span>25</span><span>50</span><span>75</span><span>100</span></div>
        {tt.node}
      </div>
    </ChartPanel>
  );
}

/** Small switcher hook for charts that offer alternative views. */
export function useChartMode(initial) {
  const [mode, setMode] = useState(initial);
  useEffect(() => setMode(initial), [initial]);
  return [mode, setMode];
}
