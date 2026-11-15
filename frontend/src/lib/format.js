/**
 * Cricket-aware number formatting. Missing values render as an em dash, never 0.
 */
export const DASH = '—';
const isNum = v => v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v));

export const fmtInt = v => (isNum(v) ? Math.round(Number(v)).toLocaleString() : DASH);
export const fmtDec = (v, d = 2) => (isNum(v) ? Number(v).toFixed(d) : DASH);
export const fmtPct = (v, d = 1) => (isNum(v) ? `${Number(v).toFixed(d)}%` : DASH);
/** Batting/bowling averages: two decimals. */
export const fmtAvg = v => fmtDec(v, 2);
/** Strike rates: two decimals keep small differences visible. */
export const fmtSR = v => fmtDec(v, 2);
/** Economy rates: two decimals. */
export const fmtEcon = v => fmtDec(v, 2);
/** Overs in overs.balls notation from a legal-ball count. */
export const oversFromBalls = balls => (isNum(balls) ? `${Math.floor(balls / 6)}.${balls % 6}` : DASH);
export const fmtDate = v => (v ? String(v).slice(0, 10) : DASH);
export const fmtSigned = (v, d = 2) => (isNum(v) ? `${Number(v) > 0 ? '+' : ''}${Number(v).toFixed(d)}` : DASH);
export const isValue = isNum;

export const PHASE_LABELS = {
  T20: { powerplay: 'Powerplay (1–6)', middle: 'Middle (7–15)', death: 'Death (16–20)' },
  T20I: { powerplay: 'Powerplay (1–6)', middle: 'Middle (7–15)', death: 'Death (16–20)' },
  ODI: { powerplay: 'Powerplay (1–10)', middle: 'Middle (11–40)', death: 'Death (41–50)' },
  ODM: { powerplay: 'Powerplay (1–10)', middle: 'Middle (11–40)', death: 'Death (41–50)' },
};
export const phaseLabel = (format, phase) => PHASE_LABELS[format]?.[phase] || (phase ? phase[0].toUpperCase() + phase.slice(1) : DASH);
export const hasPhases = format => Boolean(PHASE_LABELS[format]);

export const FORMATS = [
  { id: 'T20', label: 'T20 (franchise/domestic)' },
  { id: 'T20I', label: 'T20I' },
  { id: 'ODI', label: 'ODI' },
  { id: 'ODM', label: 'One-day domestic' },
  { id: 'Test', label: 'Test' },
  { id: 'MDM', label: 'Multi-day domestic' },
];

/** Sample-size confidence used across charts and tables. */
export function sampleLevel(n, { low = 10, ok = 30 } = {}) {
  if (!isNum(n)) return null;
  if (n < low) return 'low';
  if (n < ok) return 'limited';
  return 'ok';
}

export const cleanParams = params => Object.fromEntries(Object.entries(params || {}).filter(([, v]) => v !== undefined && v !== null && v !== ''));
