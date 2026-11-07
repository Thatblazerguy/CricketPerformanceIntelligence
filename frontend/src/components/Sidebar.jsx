/**
 * Sidebar navigation component.
 */
import { NavLink } from 'react-router-dom';

const navItems = [
  { to: '/', label: 'Dashboard', icon: '▦' },
  { to: '/players', label: 'Players', icon: '◎' },
  { to: '/compare', label: 'Comparison', icon: '⧉' },
  { to: '/matches', label: 'Matches', icon: '◉' },
  { to: '/matchups', label: 'Matchups', icon: '⇌' },
  { to: '/scouting', label: 'Scouting', icon: '⌖' },
  { to: '/auction', label: 'Auction Intelligence', icon: '₹' },
  { to: '/venues', label: 'Teams & Venues', icon: '◈' },
];

export default function Sidebar() {
  return (
    <aside className="w-56 shrink-0 bg-slate-900 border-r border-slate-800 flex flex-col">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-slate-800">
        <span className="text-indigo-400 font-bold text-sm tracking-widest uppercase">CPI</span>
        <p className="text-slate-500 text-xs mt-0.5">Cricket Intelligence</p>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {navItems.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors ${
                isActive
                  ? 'bg-indigo-900/50 text-indigo-300 font-medium'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
              }`
            }
          >
            <span className="text-base w-5 text-center">{icon}</span>
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-slate-800">
        <p className="text-xs text-slate-600">Powered by Cricsheet</p>
      </div>
    </aside>
  );
}
