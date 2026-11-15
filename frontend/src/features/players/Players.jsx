/**
 * Players Directory Page
 * Clean, fast player directory with format filters, role filters, search, sorting and pagination.
 * Displays only essential metrics (Matches, Runs, Bat Avg, Strike Rate, Wickets, Role).
 * Detailed player analytics live inside the individual Player Profile.
 */
import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { getPlayerFilterMetadata, getPlayers } from '../../services/api';
import { Avatar, Badge, EmptyState, ErrorState, FilterField, LoadingSpinner, PageHeader, Segmented } from '../../components/ui';
import Icon from '../../components/icons';

export default function Players() {
  const [format, setFormat] = useState('');
  const [role, setRole] = useState('all');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [sortBy, setSortBy] = useState('runs');
  const [sortDir, setSortDir] = useState('desc');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [bowlingType, setBowlingType] = useState('');
  const [bowlingStyle, setBowlingStyle] = useState('');
  const [bowlingArm, setBowlingArm] = useState('');
  const [bowlingSpeed, setBowlingSpeed] = useState('');
  const [filterMetadata, setFilterMetadata] = useState(null);

  const [playersData, setPlayersData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => { getPlayerFilterMetadata().then(setFilterMetadata).catch(() => {}); }, []);

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
        ...(bowlingType ? { bowling_type: bowlingType } : {}),
        ...(bowlingStyle ? { bowling_style: bowlingStyle } : {}),
        ...(bowlingArm ? { bowling_arm: bowlingArm } : {}),
        ...(bowlingSpeed ? { bowling_speed_category: bowlingSpeed } : {}),
      };

      const res = await getPlayers(queryParams);
      setPlayersData(res);
    } catch (err) {
      setError(err.message || 'Failed to fetch players.');
    } finally {
      setLoading(false);
    }
  }, [format, role, search, page, pageSize, bowlingType, bowlingStyle, bowlingArm, bowlingSpeed]);

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

  const totalPages = playersData ? Math.max(1, Math.ceil(playersData.total / pageSize)) : 1;
  const roleVariant = r => (r.includes('Batter') ? 'blue' : r.includes('Bowler') ? 'amber' : r.includes('All-Rounder') ? 'green' : 'default');
  const ROLES = [{ id: 'all', label: 'All roles' }, { id: 'batter', label: 'Batters' }, { id: 'bowler', label: 'Bowlers' }, { id: 'all_rounder', label: 'All-rounders' }];

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Players" title="Player directory"
        subtitle="Search every indexed player across Test, ODI, T20 and T20I. Open a profile for delivery-level analytics." />

      <div className="panel divide-y divide-line">
        <div className="flex flex-col gap-3 p-3 lg:flex-row lg:items-center lg:justify-between">
          <form onSubmit={handleSearch} className="flex w-full gap-2 lg:max-w-md">
            <div className="relative flex-1">
              <Icon name="search" size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input type="text" value={searchInput} onChange={e => setSearchInput(e.target.value)} placeholder="Search player name…" aria-label="Player name" className="h-9 w-full pl-9 pr-3 text-[13px]" />
            </div>
            <button type="submit" className="btn btn-primary">Search</button>
            {search && <button type="button" onClick={handleClearSearch} className="btn btn-ghost">Clear</button>}
          </form>
          <Segmented label="Role" value={role} onChange={handleRoleChange} options={ROLES} />
        </div>
        <div className="flex items-center gap-2 overflow-x-auto px-3 py-2.5 scrollbar-none">
          <span className="eyebrow shrink-0 pr-1">Format</span>
          {formatsList.map(fmt => (
            <button key={fmt.id} onClick={() => handleFormatChange(fmt.id)}
              className={`shrink-0 whitespace-nowrap rounded-full border px-3 py-1 text-xs transition-colors ${format === fmt.id ? 'border-accent/50 bg-accent-muted text-white' : 'border-line text-slate-400 hover:border-line-strong hover:text-slate-200'}`}>
              {fmt.label}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-3 p-3 md:grid-cols-4">
          {[
            ['Bowling category', bowlingType, setBowlingType, filterMetadata?.bowling_types || []],
            ['Specific bowling style', bowlingStyle, setBowlingStyle, filterMetadata?.bowling_styles || []],
            ['Bowling arm', bowlingArm, setBowlingArm, filterMetadata?.bowling_arms || []],
            ['Bowling speed', bowlingSpeed, setBowlingSpeed, filterMetadata?.bowling_speed_categories || []],
          ].map(([title, value, setter, options]) => (
            <FilterField key={title} label={title} className="min-w-0">
              <select className="h-9 w-full px-3 text-[13px]" value={value} onChange={event => { setter(event.target.value); setPage(1); }}>
                <option value="">Any</option>{options.map(option => <option key={option} value={option}>{option}</option>)}
              </select>
            </FilterField>
          ))}
        </div>
      </div>

      {(playersData || search) && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-slate-400">
          <span>{playersData ? <><strong className="num font-semibold text-white">{playersData.total.toLocaleString()}</strong> players{search && <> matching “<span className="text-slate-200">{search}</span>”</>}</> : 'Searching…'}</span>
          <label className="flex items-center gap-2">Per page
            <select value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); setPage(1); }} className="h-8 px-3 text-xs">
              <option value={25}>25</option><option value={50}>50</option><option value={100}>100</option>
            </select>
          </label>
        </div>
      )}

      {loading && <LoadingSpinner message="Loading player directory…" />}
      {error && <ErrorState message={error} onRetry={fetchPlayers} />}

      {!loading && !error && playersData && (
        <>
          {playersData.players.length === 0 ? (
            <div className="panel"><EmptyState message="No players match these filters." hint="Try a shorter name or clear the bowling filters." /></div>
          ) : (
            <div className="panel overflow-x-auto">
              <table className="w-full min-w-[820px] text-left text-[13px] text-slate-300">
                <thead className="sticky top-0 bg-surface-raised text-3xs font-semibold uppercase tracking-[0.08em] text-slate-500">
                  <tr className="border-b border-line">
                    <th className="px-4 py-2.5">Player</th>
                    <th className="px-3 py-2.5">Role</th>
                    <th className="px-3 py-2.5 text-right">Age</th>
                    <th className="px-3 py-2.5">Country</th>
                    <th className="px-3 py-2.5">Batting</th>
                    <th className="px-3 py-2.5">Bowling</th>
                    <th className="px-4 py-2.5" aria-label="Open profile" />
                  </tr>
                </thead>
                <tbody>
                  {playersData.players.map(p => {
                    const pRole = getPlayerRole(p);
                    return (
                      <tr key={p.id} className="group border-b border-line-soft transition-colors last:border-0 hover:bg-surface-hover/60">
                        <td className="px-4 py-2.5">
                          <Link to={`/players/${p.id}`} className="flex items-center gap-2.5">
                            <Avatar name={p.name} size="sm" />
                            <span className="font-medium text-slate-100 transition-colors group-hover:text-white">{p.full_name && p.full_name !== p.name ? p.full_name : p.name}</span>
                          </Link>
                        </td>
                        <td className="px-3 py-2.5"><Badge variant={roleVariant(pRole)}>{pRole}</Badge></td>
                        <td className="num px-3 py-2.5 text-right">{p.age ?? <span className="text-slate-600">—</span>}</td>
                        <td className="px-3 py-2.5">{p.nationality && p.nationality !== 'Unknown' ? p.nationality : <span className="text-slate-600">—</span>}</td>
                        <td className="px-3 py-2.5 text-slate-400">{p.batting_style ?? <span className="text-slate-600">—</span>}</td>
                        <td className="px-3 py-2.5"><span className={p.bowling_style ? 'text-slate-300' : 'text-slate-600'}>{p.bowling_style ?? 'Not available'}</span>{p.bowling_type && <Badge variant="indigo" className="ml-1.5">{p.bowling_type}</Badge>}</td>
                        <td className="px-4 py-2.5 text-right">
                          <Link to={`/players/${p.id}`} className="inline-flex items-center gap-1 text-xs text-slate-500 transition-colors group-hover:text-accent-soft">Profile<Icon name="arrowRight" size={13} /></Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {playersData.total > 0 && (
            <div className="flex flex-col items-center justify-between gap-3 text-2xs text-slate-500 sm:flex-row">
              <span className="num">Page <strong className="text-slate-200">{page}</strong> of <strong className="text-slate-200">{totalPages}</strong> · {playersData.total.toLocaleString()} players</span>
              <div className="flex items-center gap-1">
                <button onClick={() => setPage(1)} disabled={page <= 1} className="btn btn-ghost btn-xs">First</button>
                <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1} className="btn btn-secondary btn-xs px-1.5" aria-label="Previous page"><Icon name="chevronLeft" size={13} /></button>
                <span className="num px-2 text-slate-400">{page} / {totalPages}</span>
                <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages} className="btn btn-secondary btn-xs px-1.5" aria-label="Next page"><Icon name="chevronRight" size={13} /></button>
                <button onClick={() => setPage(playersData.total_pages)} disabled={page >= playersData.total_pages} className="btn btn-ghost btn-xs">Last</button>
              </div>
            </div>
          )}
        </>
      )}
      {!loading && !error && !playersData && (
        <div className="panel">
          <EmptyState icon="search" message="Search for a player to explore their statistics."
            hint="Results load one page at a time; profile analytics load when you open a player. Tip: press ⌘K anywhere to jump straight to a profile." />
        </div>
      )}
    </div>
  );
}
