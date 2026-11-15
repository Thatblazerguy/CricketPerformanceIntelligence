/**
 * Floating bottom tab bar for phones and tablets (hidden on lg+). Four primary
 * destinations plus "More", which opens the full navigation sheet so every
 * section stays reachable.
 */
import { NavLink, useLocation } from 'react-router-dom';
import { carryFilters } from '../hooks/useFilters';
import { navEntryFor } from './navigation';
import Icon from './icons';

const TABS = [
  { to: '/', label: 'Home', icon: 'dashboard' },
  { to: '/players', label: 'Players', icon: 'players' },
  { to: '/matches', label: 'Matches', icon: 'matches' },
  { to: '/simulator', label: 'Simulate', icon: 'simulator' },
];

export default function MobileTabBar({ onMore, moreOpen }) {
  const { pathname } = useLocation();
  const current = navEntryFor(pathname)?.to;
  const inMore = !TABS.some(t => t.to === current);
  const item = active => `flex h-12 flex-1 flex-col items-center justify-center gap-0.5 rounded-full text-[10px] font-medium transition-[background-color,color] duration-180 ${active ? 'bg-white/[0.1] text-accent' : 'text-slate-500 active:bg-white/[0.06]'}`;
  return (
    <nav aria-label="Primary (compact)" className="pointer-events-none fixed inset-x-0 bottom-0 z-nav flex justify-center px-3 lg:hidden" style={{ paddingBottom: 'max(0.75rem, env(safe-area-inset-bottom))' }}>
      <div className="glass pointer-events-auto flex w-full max-w-md items-center gap-1 rounded-full p-1.5">
        {TABS.map(t => (
          <NavLink key={t.to} to={t.to === '/' ? t.to : `${t.to}${carryFilters()}`} end={t.to === '/'} className={() => item(current === t.to)} aria-current={current === t.to ? 'page' : undefined}>
            <Icon name={t.icon} size={19} strokeWidth={current === t.to ? 2 : 1.75} />
            <span>{t.label}</span>
          </NavLink>
        ))}
        <button type="button" onClick={onMore} aria-expanded={moreOpen} aria-label="All sections" className={item(inMore || moreOpen)}>
          <Icon name="grid" size={19} />
          <span>More</span>
        </button>
      </div>
    </nav>
  );
}
