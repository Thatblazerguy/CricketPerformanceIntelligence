/**
 * Matchups — head-to-head intelligence for player battles and team rivalries.
 *
 *   Players: batter vs bowler from ball-by-ball records (GET /matchups/player-analysis)
 *   Teams:   team vs team from matches + innings totals (GET /matchups/team-analysis)
 *
 * Every statistic is computed server-side from stored Cricsheet data; insights carry
 * their sample size and statistical basis, and every match shown links to its
 * Match Details page.
 */
import { useSearchParams } from 'react-router-dom';
import { PageHeader, Segmented } from '../../components/ui';
import PlayerMatchup from './PlayerMatchup';
import TeamMatchup from './TeamMatchup';

export default function Matchups() {
  const [params, setParams] = useSearchParams();
  const mode = params.get('mode') === 'teams' ? 'teams' : 'players';
  const switchMode = m => { if (m !== mode) setParams(m === 'teams' ? { mode: 'teams' } : {}, { replace: false }); };
  return (
    <div>
      <PageHeader eyebrow="Matchups" title={mode === 'teams' ? 'Team vs team' : 'Batter vs bowler'}
        subtitle={mode === 'teams'
          ? 'The full rivalry: results, records, toss and innings effects, phase-by-phase batting and bowling, venue intelligence and every encounter.'
          : 'Every ball between two players: scoring, dismissals, phases, venues, form and how it compares with their usual numbers.'}
        actions={<Segmented label="Matchup type" value={mode} onChange={switchMode} options={[{ id: 'players', label: 'Player vs player' }, { id: 'teams', label: 'Team vs team' }]} />} />
      {mode === 'teams' ? <TeamMatchup /> : <PlayerMatchup />}
    </div>
  );
}
