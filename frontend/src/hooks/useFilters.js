/**
 * URL-backed analytical filters.
 *
 * Filters live in the query string so views are shareable and the browser back
 * button works. The common keys below are also remembered for the session so
 * moving between related pages (player -> team -> tournament) keeps the same
 * format, gender, years and competition unless the user changes them.
 */
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

export const SHARED_KEYS = ['format', 'gender', 'start_year', 'end_year', 'competition'];
const STORE = 'cpi.filters';

function readStore() {
  try { return JSON.parse(sessionStorage.getItem(STORE) || '{}') || {}; } catch { return {}; }
}
function writeStore(values) {
  try {
    const next = { ...readStore() };
    SHARED_KEYS.forEach(k => { if (k in values) { if (values[k]) next[k] = values[k]; else delete next[k]; } });
    sessionStorage.setItem(STORE, JSON.stringify(next));
  } catch { /* storage unavailable: URL state still works */ }
}

/** Query string carrying the remembered shared filters, for navigation links. */
export function carryFilters(keys = SHARED_KEYS) {
  const stored = readStore();
  const p = new URLSearchParams();
  keys.forEach(k => { if (stored[k]) p.set(k, stored[k]); });
  const s = p.toString();
  return s ? `?${s}` : '';
}

/**
 * @param defaults  default values; keys define which params the page owns
 * @returns [filters, setFilter(key, value) | setFilters(obj), reset, activeCount]
 */
export function useUrlFilters(defaults) {
  const [params, setParams] = useSearchParams();
  const stored = useMemo(readStore, []);
  const filters = useMemo(() => {
    const out = {};
    Object.keys(defaults).forEach(k => {
      const fromUrl = params.get(k);
      out[k] = fromUrl !== null ? fromUrl : (SHARED_KEYS.includes(k) && stored[k] !== undefined ? stored[k] : defaults[k]);
    });
    return out;
  }, [params, defaults, stored]);

  const setFilters = useCallback(updates => {
    const next = new URLSearchParams(params);
    Object.entries(updates).forEach(([k, v]) => { if (v === '' || v === null || v === undefined) next.delete(k); else next.set(k, v); });
    writeStore(updates);
    setParams(next, { replace: true });
  }, [params, setParams]);
  const setFilter = useCallback((k, v) => setFilters({ [k]: v }), [setFilters]);
  const reset = useCallback(() => {
    const cleared = Object.fromEntries(Object.keys(defaults).map(k => [k, defaults[k]]));
    setFilters(cleared);
  }, [defaults, setFilters]);
  const active = Object.keys(defaults).filter(k => (filters[k] || '') !== (defaults[k] || '')).length;
  return [filters, setFilter, reset, active, setFilters];
}
