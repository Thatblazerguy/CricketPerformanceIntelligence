/**
 * Theme store: 'light' | 'dark' | 'system'.
 *
 * The inline script in index.html applies the stored preference before first
 * paint; this module keeps it in sync at runtime (persisting the choice,
 * following OS changes while on "system", and cross-fading colours briefly
 * while switching).
 */
import { useSyncExternalStore } from 'react';
import { flushSync } from 'react-dom';

const KEY = 'cpi.theme';
const MODES = ['light', 'dark', 'system'];
const media = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
const listeners = new Set();

function readPref() {
  try { const v = localStorage.getItem(KEY); return MODES.includes(v) ? v : 'system'; } catch { return 'system'; }
}

let pref = readPref();
const resolve = p => (p === 'system' ? (media?.matches ? 'dark' : 'light') : p);
let snapshot = { preference: pref, resolved: resolve(pref) };

function commit() {
  const root = document.documentElement;
  const resolved = resolve(pref);
  root.setAttribute('data-theme', resolved);
  root.setAttribute('data-theme-pref', pref);
  snapshot = { preference: pref, resolved };
  // Render subscribers synchronously so the new frame is complete when the
  // view transition captures it.
  flushSync(() => listeners.forEach(l => l()));
}

function apply(animate) {
  const root = document.documentElement;
  const changesColours = resolve(pref) !== root.getAttribute('data-theme');
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  if (!animate || !changesColours || reduced) { commit(); return; }

  // Preferred: one composited cross-fade of the whole page. Every surface,
  // gradient, chart and blur changes together instead of element by element.
  if (document.startViewTransition) {
    apply.vt?.skipTransition?.();
    root.classList.add('theme-vt');
    apply.vt = document.startViewTransition(commit);
    apply.vt.finished.finally(() => root.classList.remove('theme-vt'));
    return;
  }

  // Fallback: transition colour properties on every element briefly.
  root.classList.add('theme-switching');
  window.clearTimeout(apply.t);
  apply.t = window.setTimeout(() => root.classList.remove('theme-switching'), 420);
  commit();
}

media?.addEventListener?.('change', () => { if (pref === 'system') apply(true); });
// Keep several open tabs in step.
if (typeof window !== 'undefined') window.addEventListener('storage', e => { if (e.key === KEY) { pref = readPref(); apply(true); } });

export function setTheme(next) {
  if (!MODES.includes(next)) return;
  pref = next;
  try { localStorage.setItem(KEY, next); } catch { /* storage unavailable */ }
  apply(true);
}

const subscribe = l => { listeners.add(l); return () => listeners.delete(l); };
const getSnapshot = () => snapshot;

/** React hook: { preference, resolved, setTheme }. */
export function useTheme() {
  const s = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  return { ...s, setTheme };
}

export const THEME_MODES = [
  { id: 'light', label: 'Light', icon: 'sun' },
  { id: 'dark', label: 'Dark', icon: 'moon' },
  { id: 'system', label: 'System', icon: 'monitor' },
];
