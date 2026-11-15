/**
 * Root application layout.
 *  - Floating glass navigation rail (lg+) / floating tab bar + sheet (< lg).
 *  - Sticky glass header inside the scroll area: breadcrumbs, quick search,
 *    data freshness and the appearance switcher.
 * (Playing XIs are managed inside the Match Simulator.)
 */
import { Suspense, useEffect, useRef, useState } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import Sidebar, { BrandMark } from './Sidebar';
import MobileTabBar from './MobileTabBar';
import QuickSearch from './QuickSearch';
import DataFreshness from './DataFreshness';
import ThemeSwitcher from './ThemeSwitcher';
import Icon from './icons';
import { PageSkeleton } from './ui';
import { breadcrumbsFor } from './navigation';

const COLLAPSE_KEY = 'cpi.sidebar.collapsed';
const readCollapsed = () => { try { return localStorage.getItem(COLLAPSE_KEY) === '1'; } catch { return false; } };

export default function Layout() {
  const [navOpen, setNavOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [scrolled, setScrolled] = useState(false);
  const location = useLocation();
  const mainRef = useRef(null);
  const crumbs = breadcrumbsFor(location.pathname);

  useEffect(() => { try { localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0'); } catch { /* storage unavailable */ } }, [collapsed]);
  // New page: start at the top (query-string changes keep scroll position).
  useEffect(() => { mainRef.current?.scrollTo({ top: 0 }); }, [location.pathname]);

  return (
    <div className="relative flex h-[100dvh] overflow-hidden text-slate-100">
      <Sidebar open={navOpen} onClose={() => setNavOpen(false)} collapsed={collapsed} onToggleCollapsed={() => setCollapsed(c => !c)} />
      <main ref={mainRef} onScroll={e => setScrolled(e.currentTarget.scrollTop > 4)} className="relative z-[1] min-w-0 flex-1 overflow-y-auto overflow-x-hidden">
        <header className="sticky top-0 z-header px-3 pt-2.5 sm:px-5 lg:px-6 lg:pt-3">
          <div className={`mx-auto flex h-12 max-w-[1480px] items-center gap-3 rounded-full px-2 transition-[background-color,box-shadow,border-color] duration-250 sm:px-3 ${scrolled ? 'glass' : 'border border-transparent'}`}>
            <Link to="/" className="shrink-0 rounded-[10px] lg:hidden" aria-label="CPI dashboard"><BrandMark size={28} /></Link>
            <nav aria-label="Breadcrumb" className="hidden min-w-0 items-center gap-1.5 pl-1 text-[13px] sm:flex">
              {crumbs.map((c, i) => (
                <span key={`${c.label}-${i}`} className="flex min-w-0 items-center gap-1.5">
                  {i > 0 && <Icon name="chevronRight" size={12} className="text-slate-600" />}
                  {c.to && i < crumbs.length - 1
                    ? <Link to={c.to} className="truncate text-slate-500 transition-colors hover:text-slate-100">{c.label}</Link>
                    : <span className={`truncate ${i === crumbs.length - 1 ? 'font-semibold text-white' : 'text-slate-500'}`}>{c.label}</span>}
                </span>
              ))}
            </nav>
            <span className="truncate text-[15px] font-semibold tracking-tight text-white sm:hidden">{crumbs[crumbs.length - 1]?.label || 'CPI'}</span>
            <div className="ml-auto flex min-w-0 flex-1 items-center justify-end gap-2">
              <div className="flex min-w-0 flex-1 justify-end"><QuickSearch /></div>
              <DataFreshness compact className="hidden xl:inline-flex" />
              <ThemeSwitcher compact className="hidden sm:inline-flex" />
            </div>
          </div>
        </header>
        <div key={location.pathname} className="page-enter mx-auto max-w-[1480px] px-4 pb-32 pt-5 sm:px-6 lg:px-8 lg:pb-16">
          <Suspense fallback={<PageSkeleton />}><Outlet /></Suspense>
        </div>
      </main>
      <MobileTabBar onMore={() => setNavOpen(o => !o)} moreOpen={navOpen} />
    </div>
  );
}
