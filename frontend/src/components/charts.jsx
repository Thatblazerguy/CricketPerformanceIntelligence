import { useMemo } from 'react';

const COLORS = ['#818cf8', '#34d399', '#22d3ee', '#fbbf24', '#c084fc', '#fb7185'];

function Panel({ title, subtitle, children, className = '' }) {
  return <section className={`rounded-xl border border-slate-800 bg-slate-900/70 p-4 min-w-0 ${className}`}>
    <div className="mb-3"><h3 className="text-sm font-semibold text-slate-200">{title}</h3>{subtitle && <p className="mt-1 text-[11px] text-slate-500">{subtitle}</p>}</div>
    {children}
  </section>;
}

export function BarChart({ title, subtitle, data = [], valueKey = 'value', labelKey = 'label', color = COLORS[0], formatter = value => value, className = '' }) {
  const rows = useMemo(() => data.filter(row => row[valueKey] !== null && row[valueKey] !== undefined && row[valueKey] !== '' && Number.isFinite(Number(row[valueKey]))), [data, valueKey]);
  const max = Math.max(1, ...rows.map(row => Number(row[valueKey])));
  if (!rows.length) return <Panel title={title} subtitle={subtitle} className={className}><p className="py-6 text-center text-xs text-slate-500">No data available for this view.</p></Panel>;
  return <Panel title={title} subtitle={subtitle} className={className}><div className="space-y-3" role="img" aria-label={title}>
    {rows.map((row, index) => { const value = Number(row[valueKey]); const width = Math.max(value > 0 ? 2 : 0, value / max * 100); return <div key={`${row[labelKey]}-${index}`} title={`${row[labelKey]}: ${formatter(value)}`}>
      <div className="mb-1 flex items-center justify-between gap-2 text-xs"><span className="truncate text-slate-400">{row[labelKey]}</span><span className="shrink-0 font-mono text-slate-200">{formatter(value)}</span></div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-800"><div className="h-full rounded-full transition-[width] duration-500" style={{ width: `${width}%`, backgroundColor: row.color || color }} /></div>
    </div>; })}
  </div></Panel>;
}

export function LineChart({ title, subtitle, data = [], xKey = 'label', yKey = 'value', color = COLORS[0], formatter = value => value, className = '' }) {
  const rows = data.filter(row => row[yKey] !== null && row[yKey] !== undefined && row[yKey] !== '' && Number.isFinite(Number(row[yKey])));
  if (rows.length < 2) return <Panel title={title} subtitle={subtitle} className={className}><p className="py-6 text-center text-xs text-slate-500">At least two observations are needed to show a trend.</p></Panel>;
  const width = 640, height = 220, left = 38, right = 12, top = 12, bottom = 34;
  const vals = rows.map(row => Number(row[yKey]));
  const low = Math.min(0, ...vals), high = Math.max(1, ...vals), span = high - low || 1;
  const x = index => left + index * (width - left - right) / (rows.length - 1);
  const y = value => top + (high - value) * (height - top - bottom) / span;
  const points = rows.map((row, i) => `${x(i)},${y(Number(row[yKey]))}`).join(' ');
  const gridValues = [low + span * .25, low + span * .5, low + span * .75];
  return <Panel title={title} subtitle={subtitle} className={className}><svg viewBox={`0 0 ${width} ${height}`} className="w-full overflow-visible" role="img" aria-label={title}>
    {gridValues.map((value, i) => <g key={i}><line x1={left} x2={width-right} y1={y(value)} y2={y(value)} stroke="#334155" strokeDasharray="3 5"/><text x={left-7} y={y(value)+4} textAnchor="end" fill="#64748b" fontSize="10">{formatter(value)}</text></g>)}
    <polyline points={points} fill="none" stroke={color} strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" />
    {rows.map((row, i) => <g key={`${row[xKey]}-${i}`}><circle cx={x(i)} cy={y(Number(row[yKey]))} r="4" fill={color}><title>{`${row[xKey]}: ${formatter(Number(row[yKey]))}`}</title></circle>{(rows.length <= 12 || i === 0 || i === rows.length-1 || i % Math.ceil(rows.length / 8) === 0) && <text x={x(i)} y={height-10} textAnchor="middle" fill="#94a3b8" fontSize="10">{row[xKey]}</text>}</g>)}
  </svg></Panel>;
}

export function DonutChart({ title, subtitle, data = [], valueKey = 'value', labelKey = 'label', className = '' }) {
  const rows = data.filter(row => Number.isFinite(Number(row[valueKey])) && Number(row[valueKey]) > 0);
  const total = rows.reduce((sum, row) => sum + Number(row[valueKey]), 0);
  if (!total) return <Panel title={title} subtitle={subtitle} className={className}><p className="py-6 text-center text-xs text-slate-500">No data available for this view.</p></Panel>;
  let offset = 0;
  const segments = rows.map((row, index) => { const share = Number(row[valueKey]) / total; const result = { ...row, share, offset, color: COLORS[index % COLORS.length] }; offset += share; return result; });
  return <Panel title={title} subtitle={subtitle} className={className}><div className="flex flex-wrap items-center justify-center gap-6">
    <svg viewBox="0 0 120 120" className="w-36 h-36 shrink-0" role="img" aria-label={title}><circle cx="60" cy="60" r="43" fill="none" stroke="#1e293b" strokeWidth="18" />{segments.map((row, index) => <circle key={`${row[labelKey]}-${index}`} cx="60" cy="60" r="43" fill="none" stroke={row.color} strokeWidth="18" pathLength="100" strokeDasharray={`${row.share*100} ${100-row.share*100}`} strokeDashoffset={-row.offset*100} transform="rotate(-90 60 60)"><title>{`${row[labelKey]}: ${Number(row[valueKey]).toLocaleString()} (${Math.round(row.share*100)}%)`}</title></circle>)}<text x="60" y="57" textAnchor="middle" fill="#f8fafc" fontSize="15" fontWeight="700">{total.toLocaleString()}</text><text x="60" y="73" textAnchor="middle" fill="#94a3b8" fontSize="8">TOTAL</text></svg>
    <div className="space-y-2 text-xs">{segments.map((row,index)=><div key={`${row[labelKey]}-${index}`} className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-sm" style={{backgroundColor:row.color}}/><span className="text-slate-400">{row[labelKey]}</span><strong className="font-mono text-slate-200">{Number(row[valueKey]).toLocaleString()}</strong><span className="text-slate-500">{Math.round(row.share*100)}%</span></div>)}</div>
  </div></Panel>;
}

export function RadarChart({ title, subtitle, series = [], metrics = [], className = '' }) {
  const axes = metrics.filter(metric => series.length > 1 && series.every(player => Number.isFinite(Number(player.values?.[metric.key]))));
  if (!axes.length) return <Panel title={title} subtitle={subtitle} className={className}><p className="py-6 text-center text-xs text-slate-500">Comparable values are not available for enough players.</p></Panel>;
  const cx = 160, cy = 145, radius = 100, count = axes.length;
  const pointsFor = player => axes.map((metric, index) => {
    const values = series.map(candidate => Number(candidate.values[metric.key]));
    const min = Math.min(...values), max = Math.max(...values), value = Number(player.values[metric.key]);
    let score = max === min ? 1 : (value - min) / (max - min);
    if (metric.lowerIsBetter) score = 1 - score;
    const angle = -Math.PI / 2 + index * Math.PI * 2 / count;
    return { x: cx + Math.cos(angle) * radius * score, y: cy + Math.sin(angle) * radius * score };
  });
  const axisPoint = (index, scale) => { const angle = -Math.PI/2 + index*Math.PI*2/count; return {x:cx+Math.cos(angle)*radius*scale,y:cy+Math.sin(angle)*radius*scale}; };
  const colors = ['#818cf8','#34d399','#fbbf24'];
  return <Panel title={title} subtitle={subtitle} className={className}><div className="flex flex-wrap justify-center gap-x-4 gap-y-2 mb-2 text-[11px]">{series.map((player,index)=><span key={player.name} className="flex items-center gap-1.5 text-slate-400"><i className="h-2 w-2 rounded-full" style={{backgroundColor:colors[index%colors.length]}} />{player.name}</span>)}</div><svg viewBox="0 0 320 290" className="mx-auto w-full max-w-lg" role="img" aria-label={title}>
    {[.25,.5,.75,1].map(scale=><polygon key={scale} points={axes.map((_,index)=>{const p=axisPoint(index,scale);return `${p.x},${p.y}`}).join(' ')} fill="none" stroke="#334155" strokeDasharray={scale===1?'':'2 4'} />)}
    {axes.map((metric,index)=>{const p=axisPoint(index,1.13);const edge=axisPoint(index,1);return <g key={metric.key}><line x1={cx} y1={cy} x2={edge.x} y2={edge.y} stroke="#334155"/><text x={p.x} y={p.y} textAnchor={p.x<cx-8?'end':p.x>cx+8?'start':'middle'} dominantBaseline="middle" fill="#94a3b8" fontSize="9">{metric.label}</text></g>})}
    {series.map((player,index)=>{const points=pointsFor(player);return <polygon key={player.name} points={points.map(p=>`${p.x},${p.y}`).join(' ')} fill={colors[index%colors.length]} fillOpacity=".12" stroke={colors[index%colors.length]} strokeWidth="2"> <title>{player.name}</title></polygon>})}
  </svg><p className="text-center text-[10px] text-slate-600">Axes are normalized within the selected players. Economy and bowling average are scored with lower values as better.</p></Panel>;
}

export function ScatterChart({ title, subtitle, data = [], xKey, yKey, xLabel, yLabel, formatX = value => value, formatY = value => value, className = '' }) {
  const rows = data.filter(row => row[xKey] != null && row[yKey] != null && Number.isFinite(Number(row[xKey])) && Number.isFinite(Number(row[yKey])));
  const groups = [...new Map(rows.filter(row => row.group).map(row => [row.group, { label: row.group, color: row.color || '#818cf8' }])).values()];
  if (!rows.length) return <Panel title={title} subtitle={subtitle} className={className}><p className="py-6 text-center text-xs text-slate-500">No paired observations available.</p></Panel>;
  const w=640,h=250,l=54,r=16,t=16,b=42;
  const xs=rows.map(row=>Number(row[xKey])),ys=rows.map(row=>Number(row[yKey]));
  const xmin=Math.min(0,...xs),xmax=Math.max(1,...xs),ymin=Math.min(0,...ys),ymax=Math.max(1,...ys);
  const sx=v=>l+(v-xmin)/(xmax-xmin||1)*(w-l-r), sy=v=>t+(ymax-v)/(ymax-ymin||1)*(h-t-b);
  return <Panel title={title} subtitle={subtitle} className={className}><svg viewBox={`0 0 ${w} ${h}`} className="w-full" role="img" aria-label={title}>
    {[0,.25,.5,.75,1].map((p,i)=><g key={i}><line x1={l} x2={w-r} y1={t+p*(h-t-b)} y2={t+p*(h-t-b)} stroke="#334155" strokeDasharray="3 5"/><text x={l-8} y={t+p*(h-t-b)+4} textAnchor="end" fill="#64748b" fontSize="10">{formatY(ymax-p*(ymax-ymin))}</text><line y1={t} y2={h-b} x1={l+p*(w-l-r)} x2={l+p*(w-l-r)} stroke="#263449" strokeDasharray="3 5"/><text x={l+p*(w-l-r)} y={h-21} textAnchor="middle" fill="#64748b" fontSize="10">{formatX(xmin+p*(xmax-xmin))}</text></g>)}
    {rows.map((row,index)=><circle key={`${row.name || row.label || index}-${index}`} cx={sx(Number(row[xKey]))} cy={sy(Number(row[yKey]))} r={row.size?Math.max(4,Math.min(9,Number(row.size))):5} fill={row.color || '#818cf8'} fillOpacity=".75" stroke="#0f172a" strokeWidth="1.5"><title>{`${row.name || row.label || 'Observation'} · ${xLabel}: ${formatX(Number(row[xKey]))} · ${yLabel}: ${formatY(Number(row[yKey]))}${row.detail ? ` · ${row.detail}` : ''}`}</title></circle>)}
    <text x={(l+w-r)/2} y={h-3} textAnchor="middle" fill="#94a3b8" fontSize="10">{xLabel}</text><text transform={`translate(13 ${(t+h-b)/2}) rotate(-90)`} textAnchor="middle" fill="#94a3b8" fontSize="10">{yLabel}</text>
  </svg><div className="mt-2 flex flex-wrap gap-3 text-[10px] text-slate-500"><span>{rows.length} paired records</span>{groups.map(group=><span key={group.label} className="inline-flex items-center gap-1"><i className="h-2 w-2 rounded-full" style={{backgroundColor:group.color}} />{group.label}</span>)}</div></Panel>;
}

export function PlayerScatterPlot({ title, subtitle, data = [], xKey='batting_average', yKey='strike_rate', xLabel='Batting average', yLabel='Strike rate', referenceX, referenceY, highlightedIds = [], onPointClick, className = '' }) {
  const rows = data.filter(row => row[xKey] != null && row[yKey] != null && Number.isFinite(Number(row[xKey])) && Number.isFinite(Number(row[yKey])));
  if (rows.length < 2) return <Panel title={title} subtitle={subtitle} className={className}><p className="py-10 text-center text-sm text-slate-500">At least two eligible players with both batting average and strike rate are needed for this comparison.</p></Panel>;
  const width=920,height=510,left=76,right=26,top=28,bottom=62;
  const xs=rows.map(row=>Number(row[xKey])),ys=rows.map(row=>Number(row[yKey]));
  const xmin=Math.min(0,...xs),xmax=Math.max(...xs),ymin=Math.min(0,...ys),ymax=Math.max(...ys);
  const xspan=xmax-xmin||1,yspan=ymax-ymin||1;
  const sx=value=>left+(Number(value)-xmin)/xspan*(width-left-right);
  const sy=value=>top+(ymax-Number(value))/yspan*(height-top-bottom);
  const roleColor=role=>/all-rounder/i.test(role||'')?'#fbbf24':/wicketkeeper/i.test(role||'')?'#22d3ee':/bowler/i.test(role||'')?'#fb7185':'#818cf8';
  const colors=[...new Map(rows.map(row=>[row.role||'Unclassified',roleColor(row.role)])).entries()];
  const xRef=Number.isFinite(Number(referenceX))?sx(referenceX):null;
  const yRef=Number.isFinite(Number(referenceY))?sy(referenceY):null;
  const highlighted=new Set(highlightedIds);
  return <Panel title={title} subtitle={subtitle} className={className}>
    <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-400">{colors.map(([role,color])=><span key={role} className="inline-flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-full" style={{backgroundColor:color}}/>{role}</span>)}<span>{rows.length.toLocaleString()} plotted · {highlighted.size} highlighted</span></div>
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full min-h-[360px]" role="img" aria-label={title}>
      {[0,.25,.5,.75,1].map((p,index)=><g key={index}><line x1={left} x2={width-right} y1={top+p*(height-top-bottom)} y2={top+p*(height-top-bottom)} stroke="#334155" strokeDasharray="3 5"/><text x={left-10} y={top+p*(height-top-bottom)+4} textAnchor="end" fill="#64748b" fontSize="11">{(ymax-p*yspan).toFixed(0)}</text><line y1={top} y2={height-bottom} x1={left+p*(width-left-right)} x2={left+p*(width-left-right)} stroke="#263449" strokeDasharray="3 5"/><text x={left+p*(width-left-right)} y={height-bottom+21} textAnchor="middle" fill="#64748b" fontSize="11">{(xmin+p*xspan).toFixed(0)}</text></g>)}
      {xRef!==null&&<line x1={xRef} x2={xRef} y1={top} y2={height-bottom} stroke="#a5b4fc" strokeWidth="2" strokeDasharray="7 5"><title>{`Cohort mean batting average ${Number(referenceX).toFixed(2)}`}</title></line>}
      {yRef!==null&&<line x1={left} x2={width-right} y1={yRef} y2={yRef} stroke="#6ee7b7" strokeWidth="2" strokeDasharray="7 5"><title>{`Cohort mean strike rate ${Number(referenceY).toFixed(1)}`}</title></line>}
      {xRef!==null&&yRef!==null&&<g fill="#64748b" fontSize="12"><text x={left+10} y={top+18}>Aggressive · lower average</text><text x={xRef+10} y={top+18}>Elite batting</text><text x={left+10} y={height-bottom-12}>Further evaluation</text><text x={xRef+10} y={height-bottom-12}>Accumulation · high average</text></g>}
      {rows.map(row=>{const selected=highlighted.has(row.player_id);const color=roleColor(row.role);return <g key={row.player_id} onClick={()=>onPointClick?.(row)} onKeyDown={event=>{if(event.key==='Enter'||event.key===' ')onPointClick?.(row)}} role="button" tabIndex="0" aria-label={`${row.player_name}: batting average ${Number(row[xKey]).toFixed(2)}, strike rate ${Number(row[yKey]).toFixed(1)}. Open player profile.`} className="cursor-pointer">
        {selected&&<circle cx={sx(row[xKey])} cy={sy(row[yKey])} r="11" fill="none" stroke="#f8fafc" strokeWidth="2.5"/>}
        <circle cx={sx(row[xKey])} cy={sy(row[yKey])} r={selected?7:5} fill={color} fillOpacity={selected?1:.78} stroke="#020617" strokeWidth="1.5"><title>{`${row.player_name} · ${row.role} · ${row.nationality || 'Unknown'} · Avg ${Number(row[xKey]).toFixed(2)} · SR ${Number(row[yKey]).toFixed(1)} · ${row.matches} matches · ${row.innings} innings · ${row.runs ?? '—'} runs · recent 5-match avg ${row.recent_form == null ? 'unavailable' : Number(row.recent_form).toFixed(1)}`}</title></circle>
      </g>})}
      <text x={(left+width-right)/2} y={height-12} textAnchor="middle" fill="#cbd5e1" fontSize="13">{xLabel}</text><text transform={`translate(18 ${(top+height-bottom)/2}) rotate(-90)`} textAnchor="middle" fill="#cbd5e1" fontSize="13">{yLabel}</text>
    </svg>
    <p className="mt-2 text-[10px] text-slate-500">Dashed lines mark the eligible cohort’s player-average benchmarks. Hover for the sample and recent form; select players in the results table to highlight them, or click a point to open the profile.</p>
  </Panel>;
}

export function MultiLineChart({ title, subtitle, series = [], className = '' }) {
  const colors=['#818cf8','#34d399','#fbbf24','#22d3ee','#fb7185'];
  const usable=series.filter(item=>item.values?.filter(point=>point.value!=null&&Number.isFinite(Number(point.value))).length>=2);
  if(!usable.length)return <Panel title={title} subtitle={subtitle} className={className}><p className="py-6 text-center text-xs text-slate-500">Select a player with at least two recent match observations.</p></Panel>;
  const width=640,height=260,left=42,right=12,top=16,bottom=34;
  const values=usable.flatMap(item=>item.values.filter(point=>point.value!=null).map(point=>Number(point.value)));
  const min=Math.min(0,...values),max=Math.max(1,...values),span=max-min||1;
  const sx=index=>left+index*(width-left-right)/4;
  const sy=value=>top+(max-value)*(height-top-bottom)/span;
  return <Panel title={title} subtitle={subtitle} className={className}>
    <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-400">{usable.map((item,index)=><span key={item.name} className="inline-flex items-center gap-1"><i className="h-2 w-2 rounded-full" style={{backgroundColor:colors[index%colors.length]}}/>{item.name}</span>)}</div>
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label={title}>
      {[0,.25,.5,.75,1].map((p,index)=><g key={index}><line x1={left} x2={width-right} y1={top+p*(height-top-bottom)} y2={top+p*(height-top-bottom)} stroke="#334155" strokeDasharray="3 5"/><text x={left-7} y={top+p*(height-top-bottom)+4} textAnchor="end" fill="#64748b" fontSize="10">{Math.round(max-p*span)}</text></g>)}
      {[0,1,2,3,4].map(index=><text key={index} x={sx(index)} y={height-9} textAnchor="middle" fill="#64748b" fontSize="10">{index===4?'Latest':`−${4-index}`}</text>)}
      {usable.map((item,index)=>{const points=item.values.filter(point=>point.value!=null&&Number.isFinite(Number(point.value))).map((point,i)=>({point,x:sx(i),y:sy(Number(point.value))}));return <g key={item.name}><polyline points={points.map(p=>`${p.x},${p.y}`).join(' ')} fill="none" stroke={colors[index%colors.length]} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round"/>{points.map((p,i)=><circle key={i} cx={p.x} cy={p.y} r="4" fill={colors[index%colors.length]}><title>{`${item.name} · ${p.point.date||'Recent appearance'}: ${Number(p.point.value).toFixed(0)} runs`}</title></circle>)}</g>})}
      <text x={(left+width-right)/2} y={height-1} textAnchor="middle" fill="#94a3b8" fontSize="10">Recent appearances · oldest to latest</text>
    </svg>
  </Panel>;
}

export function RangeChart({ title, subtitle, data = [], labelKey='label', lowKey='low', valueKey='value', highKey='high', formatter=value=>value, className='' }) {
  const rows=data.filter(row=>[row[lowKey],row[valueKey],row[highKey]].every(value=>value!==null&&value!==undefined&&Number.isFinite(Number(value))));
  if(!rows.length)return <Panel title={title} subtitle={subtitle} className={className}><p className="py-6 text-center text-xs text-slate-500">No confidence ranges available.</p></Panel>;
  const min=Math.min(0,...rows.map(row=>Number(row[lowKey]))),max=Math.max(1,...rows.map(row=>Number(row[highKey]))),span=max-min||1;
  return <Panel title={title} subtitle={subtitle} className={className}><div className="space-y-3">{rows.map((row,index)=>{const left=(Number(row[lowKey])-min)/span*100;const width=Math.max(1,(Number(row[highKey])-Number(row[lowKey]))/span*100);const point=(Number(row[valueKey])-min)/span*100;return <div key={`${row[labelKey]}-${index}`} title={`${row[labelKey]}: ${formatter(row[lowKey])}–${formatter(row[highKey])} · estimate ${formatter(row[valueKey])}`}><div className="mb-1 flex justify-between gap-2 text-xs"><span className="truncate text-slate-400">{row[labelKey]}</span><span className="shrink-0 text-slate-200">{formatter(row[valueKey])}</span></div><div className="relative h-2 rounded-full bg-slate-800"><div className="absolute h-full rounded-full bg-indigo-500/70" style={{left:`${left}%`,width:`${width}%`}}/><div className="absolute -top-0.5 h-3 w-1 rounded bg-emerald-300" style={{left:`${point}%`}}/></div><div className="mt-1 flex justify-between text-[10px] text-slate-600"><span>{formatter(row[lowKey])}</span><span>{formatter(row[highKey])}</span></div></div>})}</div></Panel>;
}
