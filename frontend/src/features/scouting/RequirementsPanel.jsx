/**
 * Step 1–2 of the scouting workflow: describe the player to recruit and apply filters.
 */
import { useMemo, useState } from 'react';
import { Collapsible } from '../../components/ui';
import { isNum } from './scoutUi';

const LIMITED = new Set(['T20', 'T20I', 'ODI', 'ODM']);
const FORMAT_LABEL = { T20: 'T20 (franchise/domestic)', T20I: 'T20 International', ODI: 'ODI', ODM: 'One-day domestic', Test: 'Test', MDM: 'Multi-day domestic' };

const field = 'h-8 w-full rounded-md border border-line-strong bg-surface-sunken px-2 text-xs text-slate-200';
const Label = ({ children, hint }) => (
  <span className="mb-1 flex items-baseline justify-between text-2xs font-medium text-slate-500">{children}{hint && <span className="text-3xs font-normal text-slate-600">{hint}</span>}</span>
);

function Chips({ values, onRemove }) {
  if (!values.length) return null;
  return (
    <div className="mt-1.5 flex flex-wrap gap-1">
      {values.map(v => (
        <button key={v} type="button" onClick={() => onRemove(v)} className="chip hover:border-neg/50 hover:text-neg-soft" title="Remove">{v} ×</button>
      ))}
    </div>
  );
}

function MultiPick({ label, hint, options, values, onChange, placeholder }) {
  return (
    <label className="block">
      <Label hint={hint}>{label}</Label>
      <select className={field} value="" onChange={e => e.target.value && onChange([...new Set([...values, e.target.value])])}>
        <option value="">{placeholder}</option>
        {options.filter(o => !values.includes(o.value ?? o)).map(o => <option key={o.value ?? o} value={o.value ?? o}>{o.label ?? o}</option>)}
      </select>
      <Chips values={values} onRemove={v => onChange(values.filter(x => x !== v))} />
    </label>
  );
}

export default function RequirementsPanel({ options, form, setForm, onSubmit, loading }) {
  const [boundMetric, setBoundMetric] = useState('');
  const [boundOp, setBoundOp] = useState('min');
  const [boundValue, setBoundValue] = useState('');
  const role = options.roles.find(r => r.key === form.role);
  const limited = LIMITED.has(form.format);
  const metricMap = useMemo(() => Object.fromEntries(options.metrics.map(m => [m.key, m])), [options.metrics]);
  const disc = role?.discipline;
  const usableMetrics = options.metrics.filter(m =>
    (limited || !m.limited_overs_only) && (disc === 'allround' || m.discipline === disc));

  const groups = role ? (limited || !role.multi_day_groups?.length ? role.groups : role.multi_day_groups) : [];
  const allGroups = disc === 'allround' ? [...groups, ...(role.bowl_groups || [])] : groups;
  const defaultWeights = useMemo(() => {
    const out = {};
    const usable = gs => gs.map(g => ({ ...g, metrics: g.metrics.filter(k => limited || !metricMap[k]?.limited_overs_only) })).filter(g => g.metrics.length);
    const assign = gs => { const u = usable(gs); u.forEach(g => g.metrics.forEach(k => { out[k] = (out[k] || 0) + 1 / u.length / g.metrics.length; })); };
    assign(groups);
    if (disc === 'allround') assign(role.bowl_groups || []);
    return out;
  }, [role, limited, metricMap]); // eslint-disable-line react-hooks/exhaustive-deps

  const weights = form.weights || defaultWeights;
  const set = (key, value) => setForm(f => ({ ...f, [key]: value }));
  const competitions = useMemo(() => {
    const rows = options.competitions.filter(c => c.match_format === form.format && (form.gender === 'all' || c.gender === form.gender));
    return rows.map(c => ({ value: c.name, label: `${c.name} (${c.matches})` }));
  }, [options.competitions, form.format, form.gender]);
  const seasons = useMemo(() => [...new Set(options.seasons.filter(s => s.match_format === form.format && (form.gender === 'all' || s.gender === form.gender)).map(s => s.season))], [options.seasons, form.format, form.gender]);

  function changeRole(key) {
    const next = options.roles.find(r => r.key === key);
    setForm(f => ({ ...f, role: key, weights: null, positions: [], requirements: f.requirements.filter(b => next.discipline === 'allround' || metricMap[b.metric]?.discipline === next.discipline) }));
  }
  function changeFormat(format) {
    const lim = LIMITED.has(format);
    setForm(f => {
      const r = options.roles.find(x => x.key === f.role);
      return {
        ...f, format, competitions: [], seasons: [], weights: null,
        role: !lim && r?.limited_overs_only ? 'batter' : f.role,
        requirements: f.requirements.filter(b => lim || !metricMap[b.metric]?.limited_overs_only),
      };
    });
  }
  function addBound() {
    if (!boundMetric || !isNum(boundValue)) return;
    set('requirements', [...form.requirements.filter(b => !(b.metric === boundMetric && b.op === boundOp)), { metric: boundMetric, op: boundOp, value: Number(boundValue) }]);
    setBoundValue('');
  }
  function setWeight(key, value) {
    set('weights', { ...weights, [key]: Number(value) });
  }
  const totalWeight = Object.values(weights).reduce((a, b) => a + Number(b || 0), 0);
  const posDefault = role?.positions || [];
  const positions = form.positions.length ? form.positions : posDefault;

  return (
    <form onSubmit={e => { e.preventDefault(); onSubmit(); }} className="panel space-y-4 p-4">
      <div>
        <div className="eyebrow mb-2">1 · Role model</div>
        <div className="grid grid-cols-2 gap-1 xl:grid-cols-1">
          {options.roles.map(r => {
            const disabled = r.limited_overs_only && !limited;
            return (
              <button key={r.key} type="button" disabled={disabled} onClick={() => changeRole(r.key)}
                className={`rounded-md border px-2.5 py-1.5 text-left text-xs transition-colors disabled:opacity-35 ${form.role === r.key ? 'border-accent/60 bg-accent-muted/50 text-white' : 'border-line bg-surface-sunken text-slate-300 hover:border-line-strong'}`}>
                {r.label}{disabled && <span className="ml-1 text-3xs text-slate-500">(limited overs only)</span>}
              </button>
            );
          })}
        </div>
        {role && <p className="mt-2 text-2xs leading-relaxed text-slate-500">{role.rationale}</p>}
      </div>

      <div className="space-y-2.5 border-t border-line pt-3">
        <div className="eyebrow">2 · Scope</div>
        <div className="grid grid-cols-2 gap-2">
          <label><Label>Format</Label>
            <select className={field} value={form.format} onChange={e => changeFormat(e.target.value)}>
              {options.formats.map(f => <option key={f} value={f}>{FORMAT_LABEL[f] || f}</option>)}
            </select></label>
          <label><Label>Gender</Label>
            <select className={field} value={form.gender} onChange={e => setForm(f => ({ ...f, gender: e.target.value, competitions: [], seasons: [] }))}>
              <option value="male">Men</option><option value="female">Women</option><option value="all">All</option>
            </select></label>
        </div>
        <MultiPick label="Tournaments" hint="any if empty" options={competitions} values={form.competitions} onChange={v => set('competitions', v)} placeholder="Add tournament…" />
        <MultiPick label="Seasons" hint="any if empty" options={seasons} values={form.seasons} onChange={v => set('seasons', v)} placeholder="Add season…" />
        <div className="grid grid-cols-2 gap-2">
          <label><Label>From year</Label><input className={field} type="number" placeholder="Any" value={form.start_year} onChange={e => set('start_year', e.target.value)} /></label>
          <label><Label>To year</Label><input className={field} type="number" placeholder="Any" value={form.end_year} onChange={e => set('end_year', e.target.value)} /></label>
        </div>
      </div>

      <div className="space-y-2.5 border-t border-line pt-3">
        <div className="eyebrow">3 · Player filters</div>
        <label className="block"><Label>Nationality</Label>
          <select className={field} value={form.nationality} onChange={e => set('nationality', e.target.value)}>
            <option value="">Any</option>{options.nationalities.map(n => <option key={n}>{n}</option>)}
          </select></label>
        {disc !== 'bowl' && (
          <div>
            <Label hint={posDefault.length ? `role default ${posDefault.join(', ')}` : 'any'}>Batting positions (≥{Math.round(options.position_share * 100)}% of innings)</Label>
            <div className="flex flex-wrap gap-1">
              {[1, 2, 3, 4, 5, 6, 7, 8].map(p => {
                const on = positions.includes(p);
                return <button key={p} type="button" onClick={() => set('positions', on ? positions.filter(x => x !== p) : [...positions, p].sort((a, b) => a - b))}
                  className={`num h-7 w-7 rounded-full border text-2xs ${on ? 'border-accent/60 bg-accent-muted/60 text-white' : 'border-line bg-surface-sunken text-slate-400'}`}>{p === 8 ? '8+' : p}</button>;
              })}
            </div>
          </div>
        )}
        {disc !== 'bat' && (
          <>
            <div className="grid grid-cols-2 gap-2">
              <label><Label>Pace / spin</Label>
                <select className={field} value={form.bowling_type} onChange={e => set('bowling_type', e.target.value)} disabled={Boolean(role?.bowling_type)}>
                  <option value="">{role?.bowling_type ? `${role.bowling_type} (role)` : 'Any'}</option><option value="pace">Pace</option><option value="spin">Spin</option>
                </select></label>
              <label><Label>Bowling arm</Label>
                <select className={field} value={form.bowling_arm} onChange={e => set('bowling_arm', e.target.value)}>
                  <option value="">Any</option>{options.bowling_arms.map(a => <option key={a} value={a}>{a}</option>)}
                </select></label>
            </div>
            <MultiPick label="Detailed bowling style" hint={`${options.coverage.bowling_style} bowlers sourced`} options={options.bowling_styles} values={form.bowling_styles} onChange={v => set('bowling_styles', v)} placeholder="Add style…" />
          </>
        )}
        <div className="grid grid-cols-3 gap-2">
          <label><Label>Min matches</Label><input className={field} type="number" min="0" value={form.min_matches} onChange={e => set('min_matches', e.target.value)} /></label>
          <label><Label>Min innings</Label><input className={field} type="number" min="0" value={form.min_innings} onChange={e => set('min_innings', e.target.value)} /></label>
          {disc === 'allround'
            ? <label><Label>Dual matches</Label><input className={field} type="number" min="0" value={form.min_dual_matches} onChange={e => set('min_dual_matches', e.target.value)} title="Matches with meaningful batting and bowling" /></label>
            : <label><Label>Evidence</Label>
              <select className={field} value={form.min_tier} onChange={e => set('min_tier', e.target.value)}>
                <option value="">All tiers</option><option value="Promising">Limited+</option><option value="Established">Established</option>
              </select></label>}
        </div>
        {disc === 'allround' && (
          <label className="block"><Label>Evidence tier</Label>
            <select className={field} value={form.min_tier} onChange={e => set('min_tier', e.target.value)}>
              <option value="">All tiers</option><option value="Promising">Limited evidence or better</option><option value="Established">Established only</option>
            </select></label>
        )}
        <div className="grid grid-cols-2 gap-2">
          <label><Label hint={`${options.coverage.date_of_birth} DOBs`}>Min age</Label><input className={field} type="number" value={form.min_age} onChange={e => set('min_age', e.target.value)} placeholder="Verified DOB only" /></label>
          <label><Label>Max age</Label><input className={field} type="number" value={form.max_age} onChange={e => set('max_age', e.target.value)} placeholder="Verified DOB only" /></label>
        </div>
      </div>

      <div className="space-y-2 border-t border-line pt-3">
        <div className="eyebrow">4 · Statistical requirements</div>
        <div className="grid grid-cols-[1fr_56px_64px_auto] gap-1.5">
          <select className={field} value={boundMetric} onChange={e => setBoundMetric(e.target.value)}>
            <option value="">Metric…</option>
            {usableMetrics.filter(m => m.kind !== 'derived' || m.key.endsWith('index')).map(m => <option key={m.key} value={m.key}>{m.label}</option>)}
          </select>
          <select className={field} value={boundOp} onChange={e => setBoundOp(e.target.value)}><option value="min">≥</option><option value="max">≤</option></select>
          <input className={field} type="number" step="any" value={boundValue} onChange={e => setBoundValue(e.target.value)} placeholder="value" />
          <button type="button" onClick={addBound} className="btn btn-secondary btn-xs h-8">Add</button>
        </div>
        {boundMetric && metricMap[boundMetric] && <p className="text-3xs text-slate-600">{metricMap[boundMetric].description || ''} {metricMap[boundMetric].higher_is_better ? '' : 'Lower is better.'}</p>}
        {form.requirements.length > 0 && (
          <ul className="space-y-1">
            {form.requirements.map(b => (
              <li key={`${b.metric}-${b.op}`} className="flex items-center justify-between rounded-md border border-line bg-surface-sunken px-2 py-1 text-2xs text-slate-300">
                <span>{metricMap[b.metric]?.label} <b className="num text-white">{b.op === 'min' ? '≥' : '≤'} {b.value}</b></span>
                <button type="button" className="text-slate-500 hover:text-neg-soft" onClick={() => set('requirements', form.requirements.filter(x => x !== b))}>remove</button>
              </li>
            ))}
          </ul>
        )}
        <p className="text-3xs leading-relaxed text-slate-600">Requirements apply to observed values. Players without any sample for a required metric are excluded and counted as "no evidence", never treated as zero.</p>
      </div>

      <Collapsible title="Metric weights" subtitle={form.weights ? 'Custom weights' : 'Default: equal per group, split within group'} className="!rounded-lg">
        <div className="space-y-2.5">
          {disc === 'allround' && (
            <label className="block text-2xs text-slate-400">Batting vs bowling · {Math.round(form.allrounder_batting_weight * 100)}% / {Math.round((1 - form.allrounder_batting_weight) * 100)}%
              <input type="range" min="0" max="1" step="0.05" value={form.allrounder_batting_weight} onChange={e => set('allrounder_batting_weight', Number(e.target.value))} className="block w-full accent-indigo-500" />
            </label>
          )}
          {allGroups.map(g => (
            <div key={g.name}>
              <div className="mb-1 text-3xs font-semibold uppercase tracking-wide text-slate-500">{g.name}</div>
              {g.metrics.filter(k => limited || !metricMap[k]?.limited_overs_only).map(k => (
                <label key={k} className="block text-2xs text-slate-400">
                  <span className="flex justify-between"><span>{metricMap[k]?.label}</span><span className="num text-slate-300">{totalWeight ? Math.round(100 * (weights[k] || 0) / totalWeight) : 0}%</span></span>
                  <input type="range" min="0" max="1" step="0.01" value={weights[k] || 0} onChange={e => setWeight(k, e.target.value)} className="block w-full accent-indigo-500" />
                </label>
              ))}
            </div>
          ))}
          {form.weights && <button type="button" className="btn btn-ghost btn-xs" onClick={() => set('weights', null)}>Reset to role defaults</button>}
          <p className="text-3xs leading-relaxed text-slate-600">CPI has no outcome-validated basis to favour one dimension of a role over another, so defaults weight each group equally. Correlated metrics share their group's weight instead of double-counting.</p>
        </div>
      </Collapsible>

      <button disabled={loading} className="btn btn-primary w-full">{loading ? 'Evaluating candidates…' : 'Generate shortlist'}</button>
    </form>
  );
}
