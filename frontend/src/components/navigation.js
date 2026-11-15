/**
 * Single source of truth for CPI navigation: sidebar groups, breadcrumbs and
 * page context in the top bar all derive from this list. Every existing route
 * is represented; nothing is removed.
 */
export const NAV_GROUPS = [
  { label: 'Overview', items: [{ to: '/', label: 'Dashboard', icon: 'dashboard', hint: 'Dataset state and leaders' }] },
  { label: 'Players', items: [
    { to: '/players', label: 'Players', icon: 'players', hint: 'Search and rank players' },
    { to: '/compare', label: 'Comparison', icon: 'compare', hint: 'Side-by-side profiles' },
    { to: '/matchups', label: 'Matchups', icon: 'matchups', hint: 'Batter vs bowler' },
    { to: '/scouting', label: 'Scouting', icon: 'scouting', hint: 'Find players by profile' },
  ] },
  { label: 'Matches', items: [
    { to: '/matches', label: 'Match Centre', icon: 'matches', hint: 'Scorecards and ball-by-ball' },
    { to: '/simulator', label: 'Match Simulator', icon: 'simulator', hint: 'Simulate and Monte Carlo' },
  ] },
  { label: 'Competitions', items: [
    { to: '/tournaments', label: 'Tournaments', icon: 'tournaments', hint: 'Standings and leaders' },
    { to: '/teams', label: 'Team Analytics', icon: 'teams', hint: 'Team performance, home/away, chasing' },
    { to: '/venues', label: 'Venue Analytics', icon: 'venues', hint: 'Grounds, toss impact and conditions' },
  ] },
  { label: 'Markets', items: [{ to: '/auction', label: 'Auction Intelligence', icon: 'auction', hint: 'Valuation and auction rooms' }] },
  { label: 'System', items: [
    { to: '/data-health', label: 'Data Health', icon: 'database', hint: 'Coverage, gaps and ingestion' },
    { to: '/settings', label: 'Settings', icon: 'settings', hint: 'Data sync and management' },
  ] },
];

const FLAT = NAV_GROUPS.flatMap(g => g.items.map(i => ({ ...i, group: g.label })));

/** Resolve the nav entry for a pathname (deepest matching prefix wins). */
export function navEntryFor(pathname) {
  if (pathname === '/') return FLAT[0];
  return FLAT.filter(i => i.to !== '/' && (pathname === i.to || pathname.startsWith(`${i.to}/`)))
    .sort((a, b) => b.to.length - a.to.length)[0] || null;
}

const DETAIL_LABELS = { '/players': 'Player profile', '/matches': 'Match', '/teams': 'Team profile', '/venues': 'Venue profile' };

/** Breadcrumb trail: group › section › detail. */
export function breadcrumbsFor(pathname) {
  const entry = navEntryFor(pathname);
  if (!entry) return [];
  const crumbs = [{ label: entry.group }, { label: entry.label, to: entry.to }];
  if (pathname === `${entry.to}/compare`) crumbs.push({ label: 'Comparison' });
  else if (pathname !== entry.to && DETAIL_LABELS[entry.to]) crumbs.push({ label: DETAIL_LABELS[entry.to] });
  return crumbs;
}
