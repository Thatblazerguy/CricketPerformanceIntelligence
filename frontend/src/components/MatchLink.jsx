/**
 * Canonical match navigation for the whole app.
 *
 * Every reference to an individual match goes to the Match Details page at
 * `/matches/:id` (id = matches.id from the database). Use:
 *   - <MatchLink id={…}>…</MatchLink>         inline text link
 *   - <MatchCard id={…}>…</MatchCard>         whole card is one link (no nested links inside)
 *   - matchRowProps(id, navigate)              whole table row clickable + keyboard accessible,
 *                                              while links/buttons inside the row keep working
 *   - matchUrl(id, { tab, innings, playerId, focus, partnership })
 */
import { Link } from 'react-router-dom';

const CONTEXT_KEYS = ['tab', 'innings', 'playerId', 'focus', 'partnership'];

export function matchUrl(matchId, context = {}) {
  if (!matchId) return null;
  const params = new URLSearchParams();
  for (const key of CONTEXT_KEYS) {
    const v = context?.[key];
    if (v !== undefined && v !== null && v !== '') params.set(key, key === 'tab' ? String(v).toLowerCase() : String(v));
  }
  const q = params.toString();
  return `/matches/${encodeURIComponent(matchId)}${q ? `?${q}` : ''}`;
}

const INLINE = 'rounded-sm decoration-accent/50 underline-offset-2 transition-colors hover:text-accent-soft hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60';

export default function MatchLink({ id, context, tab, children, className = '', title }) {
  const to = matchUrl(id, tab ? { ...context, tab } : context);
  if (!to) return <span className={className}>{children}</span>;
  // stopPropagation: a match link inside a clickable row/card must not also trigger the parent's navigation.
  return <Link to={to} title={title || 'Open match details'} onClick={e => e.stopPropagation()} className={`${INLINE} ${className}`}>{children}</Link>;
}

/** A whole card that opens the match. Do not put other links or buttons inside. */
export function MatchCard({ id, context, children, className = '', title }) {
  const to = matchUrl(id, context);
  if (!to) return <div className={className}>{children}</div>;
  return (
    <Link to={to} title={title || 'Open match details'}
      className={`group block cursor-pointer rounded-2xl transition-colors hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 ${className}`}>
      {children}
    </Link>
  );
}

const INTERACTIVE = 'a,button,input,select,textarea,label,summary,[role="button"],[role="link"]:not(tr),[data-no-row-nav]';

/**
 * Props that make a container (usually a <tr>) open a match on click, Enter or
 * Ctrl/⌘/middle click, without hijacking clicks on nested interactive elements
 * or text selection.
 */
export function matchRowProps(url, navigate, label = 'Open match details') {
  if (!url) return {};
  const open = (e, newTab) => (newTab ? window.open(url, '_blank', 'noopener') : navigate(url));
  return {
    role: 'link',
    tabIndex: 0,
    'aria-label': label,
    'data-href': url,
    onClick: e => {
      if (e.defaultPrevented || e.target.closest(INTERACTIVE)) return;
      if (window.getSelection?.()?.toString()) return;
      open(e, e.metaKey || e.ctrlKey);
    },
    onAuxClick: e => { if (e.button === 1 && !e.target.closest(INTERACTIVE)) open(e, true); },
    onKeyDown: e => { if (e.key === 'Enter' && e.target === e.currentTarget) open(e, e.metaKey || e.ctrlKey); },
    className: 'cursor-pointer focus-visible:outline-none focus-visible:bg-accent/[0.08] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/50',
  };
}
