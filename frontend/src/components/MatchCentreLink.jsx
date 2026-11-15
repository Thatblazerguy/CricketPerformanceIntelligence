/**
 * Back-compat wrapper: match links with Match Centre context (tab, innings, player…).
 * All URL building lives in ./MatchLink (the canonical match navigation).
 */
import MatchLink, { matchUrl } from './MatchLink';

export function matchCentreUrl(matchId, context = {}) {
  return matchUrl(matchId, { tab: 'scorecard', ...context });
}

export default function MatchCentreLink({ matchId, context, children, className = '' }) {
  return <MatchLink id={matchId} context={{ tab: 'scorecard', ...context }} className={`link ${className}`}>{children}</MatchLink>;
}
