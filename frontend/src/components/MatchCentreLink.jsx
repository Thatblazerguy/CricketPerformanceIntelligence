import { Link } from 'react-router-dom';

export function matchCentreUrl(matchId, context = {}) {
  if (!matchId) return null;
  const params = new URLSearchParams();
  params.set('tab', String(context.tab || 'scorecard').toLowerCase());
  for (const key of ['innings', 'playerId', 'focus', 'partnership']) {
    if (context[key] !== undefined && context[key] !== null && context[key] !== '') params.set(key, String(context[key]));
  }
  return `/matches/${encodeURIComponent(matchId)}?${params.toString()}`;
}

export default function MatchCentreLink({ matchId, context, children, className = '' }) {
  const to = matchCentreUrl(matchId, context);
  if (!to) return <>{children}</>;
  return <Link to={to} className={`text-indigo-300 underline decoration-indigo-500/40 underline-offset-2 hover:text-indigo-200 hover:decoration-indigo-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400 ${className}`}>
    {children}
  </Link>;
}
