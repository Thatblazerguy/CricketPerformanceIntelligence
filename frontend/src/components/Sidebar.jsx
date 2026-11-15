/**
 * Primary navigation.
 *  - Large screens: floating liquid-glass rail with expanded (labels) and
 *    compact (icons) states.
 *  - Smaller screens: the same list as a slide-in sheet, opened from the
 *    floating tab bar's "More" button (see MobileTabBar).
 */
import { NavLink, useLocation } from 'react-router-dom';
import { useEffect } from 'react';
import { carryFilters } from '../hooks/useFilters';
import { NAV_GROUPS } from './navigation';
import Icon from './icons';
import ThemeSwitcher from './ThemeSwitcher';

/** CPI mark: three stumps and bails inside a softly lit tile. */
export function BrandMark({ size = 32 }) {
  return (
    <span className="relative grid shrink-0 place-items-center overflow-hidden rounded-[10px] bg-gradient-to-br from-[#3aa0ff] via-[#2f7cf6] to-[#5b55e8] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.35),0_4px_12px_-4px_rgba(41,120,255,0.55)]" style={{ width: size, height: size }}>
      <svg width={size * 0.56} height={size * 0.56} viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.3" strokeLinecap="round" aria-hidden="true">
        <path d="M7.5 8v12M12 8v12M16.5 8v12M6.5 5h4.6M12.9 5h4.6" />
      </svg>
    </span>
  );
}

function Brand({ compact }) {
  return (
    <div className="flex min-w-0 items-center gap-2.5">
      <BrandMark />
      {!compact && (
        <div className="min-w-0 leading-tight">
          <div className="text-[15px] font-semibold tracking-[-0.02em] text-white">CPI</div>
          <div className="truncate text-[10.5px] font-medium text-slate-500">Cricket Performance Intelligence</div>
        </div>
      )}
    </div>
  );
}

export default function Sidebar({ open, onClose, collapsed, onToggleCollapsed }) {
  const location = useLocation();
  useEffect(() => { onClose?.(); }, [location.pathname]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!open) return undefined;
    const onKey = e => e.key === 'Escape' && onClose?.();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  // The sheet always shows labels; only the desktop rail compacts.
  const compactCls = collapsed ? 'lg:w-[4.5rem]' : 'lg:w-[15.75rem]';

  return (
    <>
      <div className={`fixed inset-0 z-drawer bg-black/40 backdrop-blur-[3px] transition-opacity duration-250 lg:hidden ${open ? 'opacity-100' : 'pointer-events-none opacity-0'}`} onClick={onClose} aria-hidden="true" />
      <div className={`fixed inset-y-0 left-0 z-drawer flex shrink-0 p-2.5 transition-[transform,width] duration-350 ease-out lg:static lg:z-nav lg:translate-x-0 lg:p-3 lg:pr-0 ${open ? 'translate-x-0' : '-translate-x-[105%]'}`}>
        <aside aria-label="Primary"
          className={`glass flex w-[17rem] flex-col overflow-hidden rounded-[24px] transition-[width] duration-350 ease-out ${compactCls}`}>
          <div className={`flex h-16 shrink-0 items-center justify-between gap-2 overflow-hidden ${collapsed ? 'px-4 lg:justify-center lg:px-0' : 'px-4'}`}>
            <NavLink to="/" aria-label="CPI dashboard" className="min-w-0 rounded-xl"><span className="lg:hidden"><Brand /></span><span className="hidden lg:block"><Brand compact={collapsed} /></span></NavLink>
            <button onClick={onClose} className="btn btn-ghost btn-icon h-8 w-8 lg:hidden" aria-label="Close navigation"><Icon name="close" size={16} /></button>
          </div>

          <nav className="scrollbar-none flex-1 overflow-y-auto px-2.5 pb-3">
            {NAV_GROUPS.map((group, gi) => (
              <div key={group.label} className={gi ? 'mt-4' : 'mt-1'}>
                <div className={`mb-1 px-3 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-slate-500 ${collapsed ? 'lg:hidden' : ''}`}>{group.label}</div>
                {collapsed && gi > 0 && <div className="mx-4 mb-2 hidden border-t border-line lg:block" aria-hidden="true" />}
                <ul className="space-y-0.5">
                  {group.items.map(({ to, label, icon }) => (
                    <li key={to}>
                      <NavLink to={to === '/' ? to : `${to}${carryFilters()}`} end={to === '/'} title={collapsed ? label : undefined}
                        className={({ isActive }) => `group relative flex h-9 items-center gap-3 rounded-xl px-3 text-[13px] transition-[background-color,color,box-shadow] duration-180 ease-out ${collapsed ? 'lg:mx-auto lg:w-11 lg:justify-center lg:px-0' : ''} ${isActive ? 'bg-white/[0.09] font-medium text-white shadow-[inset_0_0_0_0.5px_rgb(var(--line-strong))]' : 'text-slate-400 hover:bg-white/[0.05] hover:text-slate-100'}`}>
                        {({ isActive }) => (
                          <>
                            <Icon name={icon} size={17} className={`transition-colors duration-180 ${isActive ? 'text-accent' : 'text-slate-500 group-hover:text-slate-300'}`} />
                            <span className={`truncate ${collapsed ? 'lg:hidden' : ''}`}>{label}</span>
                          </>
                        )}
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>

          <div className={`shrink-0 space-y-2 border-t border-line-soft p-2.5 ${collapsed ? 'lg:px-0' : ''}`}>
            <div className="flex justify-center lg:hidden"><ThemeSwitcher size="md" /></div>
            <button onClick={onToggleCollapsed} className={`btn btn-ghost btn-sm hidden w-full rounded-xl lg:flex ${collapsed ? 'mx-auto !w-11 px-0' : 'justify-start px-3'}`}
              aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
              <Icon name="sidebar" size={16} />
              {!collapsed && <span>Collapse</span>}
            </button>
            <p className={`px-3 text-[10.5px] text-slate-500 ${collapsed ? 'lg:hidden' : ''}`}>Ball-by-ball data · Cricsheet</p>
          </div>
        </aside>
      </div>
    </>
  );
}
