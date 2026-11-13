/**
 * Dashboard page — dataset overview, top stats, recent matches.
 * All data fetched from API; no hardcoded statistics.
 */
import { getCoverage, getMatches } from '../../services/api';
import { useApi } from '../../hooks/useApi';
import { LoadingSpinner, ErrorState, StatCard, PageHeader, Table, Badge } from '../../components/ui';
import { Link } from 'react-router-dom';
import MatchCentreLink from '../../components/MatchCentreLink';
import { BarChart, DonutChart, LineChart } from '../../components/charts';
import DataFreshness from '../../components/DataFreshness';

export default function Dashboard() {
  const { data: coverage, loading: covLoading, error: covError } = useApi(getCoverage);
  const { data: recentMatches, loading: matchLoading } = useApi(() => getMatches({ page: 1, page_size: 8 }));

  if (covLoading) return <LoadingSpinner message="Loading dataset overview..." />;
  if (covError) return <ErrorState message={covError} />;

  const c = coverage;

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle="Cricket Performance Intelligence — dataset overview"
      />
      <DataFreshness className="-mt-5 mb-6" />

      {/* Coverage stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard label="Total Matches" value={c.total_matches.toLocaleString()} highlight />
        <StatCard label="Players" value={c.total_players.toLocaleString()} />
        <StatCard label="Teams" value={c.total_teams.toLocaleString()} />
        <StatCard label="Venues" value={c.total_venues.toLocaleString()} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 mb-8">
        <DonutChart title="Matches by format" subtitle="Imported match records; each stored format remains distinct." data={Object.entries(c.formats || {}).map(([label, value]) => ({ label, value }))} />
        <LineChart title="Dataset growth by match year" subtitle="Matches with a recorded start date, grouped by calendar year." data={(c.year_counts || []).slice(-18).map(row => ({ label: row.year, value: row.matches }))} formatter={value => Math.round(value).toLocaleString()} color="#34d399" />
      </div>

      {/* Format breakdown */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Format Coverage
        </h2>
        <div className="flex flex-wrap gap-3">
          {Object.entries(c.formats || {}).map(([fmt, count]) => (
            <div key={fmt} className="bg-slate-800 border border-slate-700 rounded-lg px-4 py-3">
              <p className="text-xs text-slate-400">{fmt}</p>
              <p className="text-xl font-bold text-white">{count.toLocaleString()}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mb-8">
        <BarChart title="Available years" subtitle={`${c.seasons?.length || 0} recorded competition seasons. Year bars count dated matches.`} data={(c.year_counts || []).slice(-10).map(row => ({ label: row.year, value: row.matches }))} formatter={value => Math.round(value).toLocaleString()} color="#818cf8" />
      </section>

      {/* Season list */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Seasons in Dataset
        </h2>
        <div className="flex flex-wrap gap-2">
          {(c.seasons || []).map(s => (
            <Badge key={s} variant="indigo">{s}</Badge>
          ))}
        </div>
      </section>

      {/* Recent matches */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">
            Recent Matches
          </h2>
          <Link to="/matches" className="text-xs text-indigo-400 hover:text-indigo-300">
            View all →
          </Link>
        </div>

        {matchLoading ? (
          <LoadingSpinner message="Loading matches..." />
        ) : (
          <Table
            headers={['Date', 'Competition', 'Teams', 'Result', 'Format']}
            rows={(recentMatches?.matches || []).map(m => [
              m.start_date,
              m.competition || '—',
              <MatchCentreLink key={`match-${m.id}`} matchId={m.id}>{`${m.team1 || 'Team 1'} vs ${m.team2 || 'Team 2'}`}</MatchCentreLink>,
              m.winner
                ? `${m.winner} won${m.result_margin_runs ? ` by ${m.result_margin_runs}R` : m.result_margin_wickets ? ` by ${m.result_margin_wickets}W` : ''}`
                : m.result_type || '—',
              <Badge key={m.id}>{m.match_format}</Badge>,
            ])}
            emptyMessage="No matches imported yet. Run the ingestion script."
          />
        )}
      </section>

      {/* Last ingestion */}
      {c.last_ingestion && (
        <p className="text-xs text-slate-600 mt-6">
          Last ingestion: {new Date(c.last_ingestion).toLocaleString()}
        </p>
      )}
    </div>
  );
}
