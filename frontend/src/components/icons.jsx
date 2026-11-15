/**
 * CPI icon set: 24px grid, 1.75 stroke, round caps. Kept local (no dependency)
 * so navigation and controls share one consistent line weight.
 */
const paths = {
  dashboard: <><rect x="3.5" y="3.5" width="7" height="8" rx="1.5" /><rect x="13.5" y="3.5" width="7" height="5" rx="1.5" /><rect x="13.5" y="11.5" width="7" height="9" rx="1.5" /><rect x="3.5" y="14.5" width="7" height="6" rx="1.5" /></>,
  players: <><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c.6-3.4 3.3-5.5 6.5-5.5s5.9 2.1 6.5 5.5" /><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.8c2 .7 3.2 2.5 3.5 5.2" /></>,
  compare: <><rect x="3.5" y="4" width="7" height="16" rx="1.5" /><rect x="13.5" y="4" width="7" height="16" rx="1.5" /><path d="M6 9h2M6 13h2M16 9h2M16 13h2" /></>,
  matchups: <><path d="M4 7h13l-3-3M20 17H7l3 3" /></>,
  scouting: <><circle cx="11" cy="11" r="6.5" /><path d="m20.5 20.5-4.8-4.8M11 8v6M8 11h6" /></>,
  matches: <><circle cx="12" cy="12" r="8.5" /><path d="M8.5 5.3c1.6 2 1.6 11.4 0 13.4M15.5 5.3c-1.6 2-1.6 11.4 0 13.4" /></>,
  simulator: <><path d="M4 19.5V5M4 19.5h16" /><path d="m7.5 15 3.5-4 3 2.5 5-6.5" /><circle cx="19" cy="7" r="1.3" fill="currentColor" /></>,
  tournaments: <><path d="M8 4h8v5a4 4 0 0 1-8 0V4ZM12 13v4M8.5 20.5h7M9.5 17h5" /><path d="M8 6H5a2.5 2.5 0 0 0 3 3.6M16 6h3a2.5 2.5 0 0 1-3 3.6" /></>,
  teams: <><path d="M12 3.5 19.5 6v5.5c0 4.4-3.1 7.6-7.5 9-4.4-1.4-7.5-4.6-7.5-9V6L12 3.5Z" /><path d="m9 12 2 2 4-4" /></>,
  venues: <><path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0C18.5 15.4 12 21 12 21Z" /><circle cx="12" cy="10" r="2.3" /></>,
  auction: <><path d="m14 4 6 6M11.5 6.5l6 6M13 5l-7.5 7.5 6 6L19 11M3.5 20.5l5-5" /></>,
  settings: <><circle cx="12" cy="12" r="2.8" /><path d="M19.4 14.5a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5v.2a2 2 0 1 1-4 0V20a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3.9a2 2 0 1 1 0-4H4a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H10a1.6 1.6 0 0 0 1-1.5V3.9a2 2 0 1 1 4 0V4a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V10a1.6 1.6 0 0 0 1.5 1h.2a2 2 0 1 1 0 4H20a1.6 1.6 0 0 0-1.5 1Z" /></>,
  search: <><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.2-4.2" /></>,
  menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
  close: <><path d="M6 6l12 12M18 6 6 18" /></>,
  chevronLeft: <path d="m14.5 6-6 6 6 6" />,
  chevronRight: <path d="m9.5 6 6 6-6 6" />,
  chevronDown: <path d="m6 9.5 6 6 6-6" />,
  arrowRight: <path d="M5 12h14m-5-5 5 5-5 5" />,
  arrowUpRight: <path d="M7 17 17 7M8 7h9v9" />,
  download: <><path d="M12 4v11m0 0-4.5-4.5M12 15l4.5-4.5M4.5 19.5h15" /></>,
  sidebar: <><rect x="3.5" y="4.5" width="17" height="15" rx="2" /><path d="M9.5 4.5v15" /></>,
  bat: <><path d="M5 19 15.5 8.5M14 4.5l5.5 5.5-3.5 3.5L10.5 8 14 4.5ZM4 20l2-2" /></>,
  ball: <><circle cx="12" cy="12" r="8" /><path d="M7 6.5c2.2 3.4 2.2 7.6 0 11M17 6.5c-2.2 3.4-2.2 7.6 0 11" /></>,
  info: <><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5M12 8v.01" /></>,
  calendar: <><rect x="3.5" y="5" width="17" height="15" rx="2" /><path d="M3.5 9.5h17M8 3v4M16 3v4" /></>,
  pulse: <path d="M3 12h4l2.5-6 4 12 2.5-6H21" />,
  play: <path d="M7 5.5v13l11-6.5-11-6.5Z" />,
  pause: <><path d="M8 5.5v13M16 5.5v13" /></>,
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  alert: <><path d="M12 4 21 19.5H3L12 4Z" /><path d="M12 10v4M12 17v.01" /></>,
  filter: <path d="M4 5.5h16l-6.2 7.3V19l-3.6-1.8v-4.4L4 5.5Z" />,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4" /></>,
  moon: <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z" />,
  monitor: <><rect x="3" y="4.5" width="18" height="12" rx="2" /><path d="M9 20h6M12 16.5V20" /></>,
  more: <><circle cx="5.5" cy="12" r="1.4" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" /><circle cx="18.5" cy="12" r="1.4" fill="currentColor" stroke="none" /></>,
  grid: <><rect x="4" y="4" width="6.5" height="6.5" rx="1.6" /><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.6" /><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.6" /><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.6" /></>,
  stumps: <><path d="M8 7v13M12 7v13M16 7v13M7 5h4.6M12.4 5H17" /></>,
  database: <><ellipse cx="12" cy="6" rx="7.5" ry="2.8" /><path d="M4.5 6v12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8V6M4.5 12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8" /></>,
  sparkle: <path d="M12 3.5c.6 4.3 2.2 6.1 6.5 6.5-4.3.6-5.9 2.2-6.5 6.5-.6-4.3-2.2-5.9-6.5-6.5 4.3-.4 5.9-2.2 6.5-6.5ZM18.5 15.5c.3 1.9 1 2.6 2.9 2.9-1.9.3-2.6 1-2.9 2.9-.3-1.9-1-2.6-2.9-2.9 1.9-.3 2.6-1 2.9-2.9Z" />,
  refresh: <><path d="M19.5 12a7.5 7.5 0 0 1-13 5.1M4.5 12a7.5 7.5 0 0 1 13-5.1" /><path d="M17.5 3.5v3.6h-3.6M6.5 20.5v-3.6h3.6" /></>,
  external: <><path d="M14 4.5h5.5V10M19.5 4.5 11 13M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10" /></>,
};

export default function Icon({ name, size = 18, className = '', strokeWidth = 1.75, title }) {
  const body = paths[name];
  if (!body) return null;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth}
      strokeLinecap="round" strokeLinejoin="round" className={`shrink-0 ${className}`} aria-hidden={title ? undefined : true} role={title ? 'img' : undefined}>
      {title && <title>{title}</title>}
      {body}
    </svg>
  );
}
