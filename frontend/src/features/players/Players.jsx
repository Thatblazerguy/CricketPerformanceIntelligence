/**
 * Players Directory Page
 * Clean, fast player directory with format filters, role filters, search, sorting and pagination.
 * Displays only essential metrics (Matches, Runs, Bat Avg, Strike Rate, Wickets, Role).
 * Detailed player analytics live inside the individual Player Profile.
 */
import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { getPlayers } from '../../services/api';
import { LoadingSpinner, ErrorState, EmptyState, PageHeader } from '../../components/ui';

export default function Players() {
  const [format, setFormat] = useState('');
  const [role, setRole] = useState('all');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [sortBy, setSortBy] = useState('runs');
  const [sortDir, setSortDir] = useState('desc');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const [playersData, setPlayersData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchPlayers = useCallback(async () => {
    if (!search.trim()) { setPlayersData(null); setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const queryParams = {
        page,
        page_size: pageSize,
        role: role === 'all' ? undefined : role,
        ...(format ? { format } : {}),
        ...(search ? { name: search } : {}),
      };

      const res = await getPlayers(queryParams);
      setPlayersData(res);
    } catch (err) {
      setError(err.message || 'Failed to fetch players.');
    } finally {
      setLoading(false);
    }
  }, [format, role, search, page, pageSize]);

  useEffect(() => {
    if (search) fetchPlayers();
  }, [fetchPlayers]);

  const handleSearch = (e) => {
    e.preventDefault();
    if (!searchInput.trim()) return;
    setSearch(searchInput.trim());
    setPage(1);
  };

  const handleClearSearch = () => {
    setSearchInput('');
    setSearch('');
    setPage(1);
  };

  const handleFormatChange = (fmt) => {
    setFormat(fmt);
    setPage(1);
  };

  const handleRoleChange = (r) => {
    setRole(r);
    if (r === 'bowler' && sortBy === 'runs') {
      setSortBy('wickets');
    } else if (r === 'batter' && sortBy === 'wickets') {
      setSortBy('runs');
    }
    setPage(1);
  };

  const handleSort = (col) => {
    if (sortBy === col) {
      setSortDir(prev => prev === 'desc' ? 'asc' : 'desc');
    } else {
      setSortBy(col);
      setSortDir('desc');
    }
    setPage(1);
  };

  const getPlayerRole = (p) => {
    if (p.primary_role) return p.primary_role;
    const bats = p.balls_faced >= 120 && p.innings_batted >= 8;
    const bowls = p.legal_balls_bowled >= 120 && p.innings_bowled >= 8;
    if (bats && bowls) return p.balls_faced >= p.legal_balls_bowled ? 'Batting All-Rounder' : 'Bowling All-Rounder';
    if (bowls) return 'Specialist Bowler';
    if (bats) return 'Specialist Batter';
    return 'Unclassified';
  };

  const formatsList = [
    { id: '', label: 'All Formats' },
    { id: 'T20I', label: 'T20I (International)' },
    { id: 'T20', label: 'T20 (Franchise/Domestic)' },
    { id: 'ODI', label: 'ODI' },
    { id: 'Test', label: 'Test' },
    { id: 'MDM', label: 'Multi-day domestic' },
    { id: 'ODM', label: 'One-day domestic' },
  ];

  const sortIndicator = (col) => {
    if (sortBy !== col) return <span className="text-slate-600 ml-1 text-xs">↕</span>;
    return <span className="text-indigo-400 ml-1 text-xs">{sortDir === 'asc' ? '▲' : '▼'}</span>;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <PageHeader
        title="Players"
        subtitle="Player directory across Test, ODI, T20 and T20I formats. Select any player to inspect their complete analytics profile."
      />

      {/* Format & Role Controls */}
      <div className="bg-slate-900/90 border border-slate-800 p-2.5 rounded-xl flex flex-wrap items-center justify-between gap-3 shadow-md">
        {/* Format Selector */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-xs uppercase tracking-wider text-slate-500 font-semibold px-2">Format:</span>
          {formatsList.map(fmt => (
            <button
              key={fmt.id}
              onClick={() => handleFormatChange(fmt.id)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                format === fmt.id
                  ? 'bg-indigo-600 text-white shadow-sm font-semibold'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
              }`}
            >
              {fmt.label}
            </button>
          ))}
        </div>

        {/* Role Selector */}
        <div className="flex items-center gap-1 bg-slate-800/80 p-1 rounded-lg border border-slate-700/60">
          {[
            { id: 'all', label: 'All Roles' },
            { id: 'batter', label: 'Batters' },
            { id: 'bowler', label: 'Bowlers' },
            { id: 'all_rounder', label: 'All-Rounders' },
          ].map(r => (
            <button
              key={r.id}
              onClick={() => handleRoleChange(r.id)}
              className={`px-3 py-1 rounded text-xs transition-colors ${
                role === r.id
                  ? 'bg-indigo-600 text-white font-medium shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* Search Bar & Results Summary */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
        <form onSubmit={handleSearch} className="flex gap-2 w-full sm:w-80">
          <div className="relative flex-1">
            <input
              type="text"
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
              placeholder="Search player name..."
              className="w-full bg-slate-800/90 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            />
            <svg className="w-4 h-4 text-slate-500 absolute left-3 top-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </div>
          <button
            type="submit"
            className="bg-indigo-600 hover:bg-indigo-500 text-white text-xs px-3.5 py-2 rounded-lg font-medium transition-colors"
          >
            Search
          </button>
          {search && (
            <button
              type="button"
              onClick={handleClearSearch}
              className="text-slate-400 hover:text-slate-200 text-xs px-2"
            >
              Clear
            </button>
          )}
        </form>

        <div className="flex items-center gap-3 text-xs text-slate-400 self-end sm:self-auto">
          {playersData && (
            <span>
              <strong className="text-white font-semibold">{playersData.total.toLocaleString()}</strong> players found
              {search && ` for "${search}"`}
            </span>
          )}
          <div className="flex items-center gap-1.5 ml-2">
            <span>Per page:</span>
            <select
              value={pageSize}
              onChange={e => { setPageSize(Number(e.target.value)); setPage(1); }}
              className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none"
            >
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
          </div>
        </div>
      </div>

      {/* Loading / Error States */}
      {loading && <LoadingSpinner message="Loading player directory..." />}
      {error && <><ErrorState message={error} /><button onClick={fetchPlayers} className="text-sm text-indigo-300">Retry search</button></>}

      {/* Essential Directory Table */}
      {!loading && !error && playersData && (
        <>
          {playersData.players.length === 0 ? (
            <EmptyState message="No players found matching your criteria." />
          ) : (
            <div className="overflow-x-auto rounded-xl border border-slate-800 shadow-xl bg-slate-900/40">
              <table className="w-full text-left text-xs text-slate-300">
                <thead className="bg-slate-800/90 border-b border-slate-700 text-[11px] uppercase tracking-wider text-slate-400 font-semibold select-none">
                  <tr>
                    <th className="py-3 px-4">Player</th>
                    <th className="py-3 px-3 text-center">Role</th>
                    <th className="py-3 px-3 text-center">Age</th>
                    <th className="py-3 px-3 text-center">Nationality</th>
                    <th className="py-3 px-3 text-center">Batting style</th>
                    <th className="py-3 px-3 text-center">Bowling style</th>
                    <th className="py-3 px-4 text-center">Profile</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800 font-mono text-[12px]">
                  {playersData.players.map(p => {
                    const pRole = getPlayerRole(p);
                    const roleColor = pRole.includes('Batter')
                      ? 'bg-blue-950/60 text-blue-300 border-blue-800/50'
                      : pRole.includes('Bowler')
                      ? 'bg-amber-950/60 text-amber-300 border-amber-800/50'
                      : pRole.includes('All-Rounder')
                      ? 'bg-emerald-950/60 text-emerald-300 border-emerald-800/50'
                      : 'bg-slate-900 text-slate-400 border-slate-700';

                    return (
                      <tr key={p.id} className="hover:bg-slate-800/40 transition-colors">
                        <td className="py-2.5 px-4 font-sans font-medium text-slate-200">
                          <Link
                            to={`/players/${p.id}`}
                            className="hover:text-indigo-400 transition-colors font-semibold"
                          >
                            {p.name}
                          </Link>
                        </td>
                        <td className="py-2.5 px-3 text-center font-sans">
                          <span className={`inline-block px-2 py-0.5 rounded text-[11px] font-medium border ${roleColor}`}>
                            {pRole}
                          </span>
                        </td>
                        <td className="py-2.5 px-3 text-center">{p.age ?? '—'}</td>
                        <td className="py-2.5 px-3 text-center">{p.nationality ?? '—'}</td>
                        <td className="py-2.5 px-3 text-center">{p.batting_style ?? '—'}</td>
                        <td className="py-2.5 px-3 text-center">{p.bowling_style ?? '—'}</td>
                        <td className="py-2.5 px-4 text-center font-sans">
                          <Link
                            to={`/players/${p.id}`}
                            className="text-xs text-indigo-400 hover:text-indigo-300 font-semibold transition-colors"
                          >
                            View Profile →
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Pagination */}
          {playersData.total > 0 && (
            <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-4 border-t border-slate-800 text-xs">
              <div className="text-slate-400">
                Page <strong className="text-white">{page}</strong> of{' '}
                <strong className="text-white">{Math.max(1, Math.ceil(playersData.total / pageSize))}</strong> ({playersData.total.toLocaleString()} players)
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage(1)}
                  disabled={page <= 1}
                  className="px-2.5 py-1.5 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-30 text-slate-300 transition-colors"
                >
                  « First
                </button>
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-30 text-slate-300 transition-colors"
                >
                  ← Prev
                </button>
                  <span className="px-3 py-1 text-slate-400 font-mono">
                  {page} / {Math.max(1, Math.ceil(playersData.total / pageSize))}
                </span>
                <button
                  onClick={() => setPage(p => Math.min(Math.ceil(playersData.total / pageSize), p + 1))}
                  disabled={page >= Math.ceil(playersData.total / pageSize)}
                  className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-30 text-slate-300 transition-colors"
                >
                  Next →
                </button>
                <button
                  onClick={() => setPage(playersData.total_pages)}
                  disabled={page >= playersData.total_pages}
                  className="px-2.5 py-1.5 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-30 text-slate-300 transition-colors"
                >
                  Last »
                </button>
              </div>
            </div>
          )}
        </>
      )}
      {!loading && !error && !playersData && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-10 text-center text-sm text-slate-400">
          Search for a player to explore their statistics. Results are loaded one page at a time; profile analytics load when you open a player.
        </div>
      )}
    </div>
  );
}
