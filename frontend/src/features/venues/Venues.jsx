/**
 * Teams & Venues Intelligence Hub
 * Comprehensive ground-level scoring averages, toss tendencies, and team win-rate analytics.
 * Fully backed by Cricsheet PostgreSQL delivery & match tables.
 */
import { useState, useMemo, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getVenues, getGroundAnalytics, getTeams, getTeamStats } from '../../services/api';
import { useApi } from '../../hooks/useApi';
import { LoadingSpinner, ErrorState, EmptyState, PageHeader, Badge, StatCard } from '../../components/ui';
import { BarChart, LineChart } from '../../components/charts';
import MatchCentreLink from '../../components/MatchCentreLink';

export default function Venues() {
  const [activeTab, setActiveTab] = useState('venues'); // 'venues' | 'teams'
  const [groundFormat, setGroundFormat] = useState('T20');
  const [selectedVenue, setSelectedVenue] = useState(null);
  const [groundPeriod, setGroundPeriod] = useState('all');
  const [groundFrom, setGroundFrom] = useState('');
  const [groundTo, setGroundTo] = useState('');
  const [recentMatches, setRecentMatches] = useState('10');

  // Venues data
  const { data: venuesData, loading: venuesLoading, error: venuesError } = useApi(
    () => getVenues(groundFormat), [groundFormat]
  );
  const { data: groundAnalytics, loading: groundLoading, error: groundError, refetch: refetchGround } = useApi(
    () => selectedVenue ? getGroundAnalytics(selectedVenue.venue_id, groundFormat, {
      period: groundPeriod,
      ...(groundPeriod === 'custom' && groundFrom ? { start_date: `${groundFrom}-01-01` } : {}),
      ...(groundPeriod === 'custom' && groundTo ? { end_date: `${groundTo}-12-31` } : {}), recent_matches: recentMatches,
    }) : Promise.resolve(null),
    [selectedVenue?.venue_id, groundFormat, groundPeriod, groundFrom, groundTo, recentMatches]
  );
  const [venueSearch, setVenueSearch] = useState('');

  // Teams data
  const { data: teamsData, loading: teamsLoading, error: teamsError } = useApi(getTeams);
  const [teamSearch, setTeamSearch] = useState('');
  const [selectedTeam, setSelectedTeam] = useState(null);
  // Deep link: /venues?team=<CPI team id or name> opens that team's records (used by the Match Simulator).
  const [searchParams] = useSearchParams();
  useEffect(() => {
    const wanted = (searchParams.get('team') || '').trim().toLowerCase();
    if (!wanted || !teamsData) return;
    const match = teamsData.find(t => t.id === wanted || (t.canonical_name || '').toLowerCase() === wanted || (t.name || '').toLowerCase() === wanted);
    if (match) { setActiveTab('teams'); setSelectedTeam(match); }
  }, [teamsData, searchParams]);
  const [teamFormat, setTeamFormat] = useState('T20');
  const [teamPeriod, setTeamPeriod] = useState('all');
  const [teamFrom, setTeamFrom] = useState('');
  const [teamTo, setTeamTo] = useState('');
  const [teamCountry, setTeamCountry] = useState('');
  const [teamOpponent, setTeamOpponent] = useState('');
  const [teamGender, setTeamGender] = useState('male');

  // Selected team stats
  const {
    data: selectedTeamStats,
    loading: teamStatsLoading,
    error: teamStatsError,
  } = useApi(
    () => (selectedTeam ? getTeamStats(selectedTeam.id, {
      format: teamFormat, period: teamFrom || teamTo ? 'all' : teamPeriod,
      ...(teamFrom ? { start_date: `${teamFrom}-01-01` } : {}),
      ...(teamTo ? { end_date: `${teamTo}-12-31` } : {}),
      ...(teamCountry ? { country: teamCountry } : {}), ...(teamOpponent ? { opposition: teamOpponent } : {}), gender: teamGender,
    }) : Promise.resolve(null)),
    [selectedTeam?.id, teamFormat, teamPeriod, teamFrom, teamTo, teamCountry, teamOpponent, teamGender]
  );

  function fmt(v, suffix = '') {
    if (v === null || v === undefined) return '—';
    return `${v}${suffix}`;
  }

  // Filtered venues
  const filteredVenues = useMemo(() => {
    if (!venuesData) return [];
    return venuesData
      .filter(v => v.total_matches > 0)
      .filter(v => {
        if (!venueSearch) return true;
        const q = venueSearch.toLowerCase();
        return (
          (v.venue_name && v.venue_name.toLowerCase().includes(q)) ||
          (v.city && v.city.toLowerCase().includes(q)) ||
          (v.country && v.country.toLowerCase().includes(q))
        );
      })
      .sort((a, b) => b.total_matches - a.total_matches);
  }, [venuesData, venueSearch]);

  // Filtered teams
  const filteredTeams = useMemo(() => {
    if (!teamsData) return [];
    return teamsData
      .filter(t => t.matches_played > 0)
      .filter(t => {
        if (!teamSearch) return true;
        return (
          t.name.toLowerCase().includes(teamSearch.toLowerCase()) ||
          t.canonical_name.toLowerCase().includes(teamSearch.toLowerCase())
        );
      })
      .sort((a, b) => b.matches_played - a.matches_played);
  }, [teamsData, teamSearch]);

  // Export Venues to CSV
  const exportVenuesCSV = () => {
    if (!filteredVenues.length) return;
    const rows = [
      ['Venue Name', 'City', 'Country', 'Format Group', 'Matches Played'],
      ...filteredVenues.map(v => [
        `"${v.venue_name || ''}"`,
        `"${v.city || ''}"`,
        `"${v.country || ''}"`,
        groundFormat,
        v.total_matches,
      ]),
    ];
    const csvContent = 'data:text/csv;charset=utf-8,' + rows.map(e => e.join(',')).join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', 'cpi_venue_statistics.csv');
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // Export Selected Team Stats to CSV
  const exportTeamCSV = () => {
    if (!selectedTeamStats) return;
    const rows = [
      ['Metric', 'Value'],
      ['Team', selectedTeamStats.team_name],
      ['Format', teamFormat],
      ['Total Matches', selectedTeamStats.total_matches],
      ['Wins', selectedTeamStats.wins],
      ['Losses', selectedTeamStats.losses],
      ['Ties', selectedTeamStats.ties],
      ['No Results', selectedTeamStats.no_results],
      ['Win Percentage', `${selectedTeamStats.win_percentage ?? '—'}%`],
      ['Batting First Matches', selectedTeamStats.batting_first_matches],
      ['Batting First Wins', selectedTeamStats.batting_first_wins],
      ['Batting First Win %', `${selectedTeamStats.batting_first_win_pct ?? '—'}%`],
      ['Chasing Matches', selectedTeamStats.chasing_matches],
      ['Chasing Wins', selectedTeamStats.chasing_wins],
      ['Chasing Win %', `${selectedTeamStats.chasing_win_pct ?? '—'}%`],
    ];
    const csvContent = 'data:text/csv;charset=utf-8,' + rows.map(e => e.join(',')).join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `team_${selectedTeamStats.team_name.replace(/\s+/g, '_')}_${teamFormat}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div>
      <PageHeader
        title="Teams & Venues"
        subtitle="Match records, batting-first vs chasing splits, and venue scoring intelligence."
      />

      {/* Primary Tabs */}
      <div className="flex border-b border-slate-800 mb-6 gap-6">
        <button
          onClick={() => setActiveTab('venues')}
          className={`pb-3 text-sm font-semibold transition-colors relative ${
            activeTab === 'venues'
              ? 'text-indigo-400 border-b-2 border-indigo-500'
              : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          Grounds & Venues ({venuesData ? venuesData.filter(v => v.total_matches > 0).length : '—'})
        </button>
        <button
          onClick={() => setActiveTab('teams')}
          className={`pb-3 text-sm font-semibold transition-colors relative ${
            activeTab === 'teams'
              ? 'text-indigo-400 border-b-2 border-indigo-500'
              : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          Team Records & Splits ({teamsData ? teamsData.filter(t => t.matches_played > 0).length : '—'})
        </button>
      </div>

      {/* ================= TAB 1: VENUES ================= */}
      {activeTab === 'venues' && (
        <div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-4 mb-5">
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
              <div>
                <h2 className="font-semibold text-slate-100">Ground filters</h2>
                <p className="text-xs text-slate-500 mt-1">Details load only after you select a ground.</p>
              </div>
              <div className="flex gap-2 flex-wrap" role="group" aria-label="Ground match format">
                {[['ODI','ODI + ODM'],['T20','T20 + T20I'],['Test','Test + MDM']].map(([value,label]) => (
                  <button key={value} onClick={() => setGroundFormat(value)}
                    className={`px-3 py-2 rounded-lg border text-sm ${groundFormat === value ? 'bg-indigo-600 border-indigo-500 text-white' : 'bg-slate-950 border-slate-700 text-slate-300 hover:border-slate-500'}`}>
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-2">
              <select aria-label="Ground period" value={groundPeriod} onChange={e => { const v=e.target.value; setGroundPeriod(v); if(v!=='custom'){const n=Number(v),y=new Date().getFullYear();setGroundFrom(v==='all'?'':String(y-n+1));setGroundTo(v==='all'?'':String(y));} }} className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200">
                <option value="all">All time</option><option value="1">Last 1 year</option><option value="3">Last 3 years</option><option value="5">Last 5 years</option><option value="10">Last 10 years</option><option value="custom">Custom years</option>
              </select>
              {groundPeriod==='custom' && <><input aria-label="Ground from year" type="number" placeholder="From year" value={groundFrom} onChange={e=>setGroundFrom(e.target.value)} className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200"/><input aria-label="Ground to year" type="number" placeholder="To year" value={groundTo} onChange={e=>setGroundTo(e.target.value)} className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200"/></>}
              <select aria-label="Recent match sample" value={recentMatches} onChange={e=>setRecentMatches(e.target.value)} className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200"><option value="10">Recent 10 matches</option><option value="20">Recent 20 matches</option></select>
            </div>
          </div>
          {venuesLoading && <LoadingSpinner message="Loading grounds for selected format..." />}
          {venuesError && <ErrorState message={venuesError} />}
          {venuesData && <div className="grid grid-cols-1 xl:grid-cols-12 gap-5">
            <section className="xl:col-span-4 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
              <div className="flex items-center justify-between gap-2 mb-3">
                <h3 className="text-sm font-semibold text-slate-100">Grounds</h3>
                <span className="text-xs text-slate-500">{filteredVenues.length} available</span>
              </div>
              <div className="flex gap-2 mb-3">
                <input type="text" placeholder="Search ground, city or country..." value={venueSearch}
                  onChange={e => setVenueSearch(e.target.value)}
                  className="min-w-0 flex-1 bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500 placeholder-slate-600" />
                <button onClick={exportVenuesCSV} className="px-3 rounded-lg border border-slate-700 text-xs text-slate-300 hover:bg-slate-800">Export</button>
              </div>
              <div className="max-h-[720px] overflow-y-auto space-y-1.5">
                {filteredVenues.map(v => <button key={v.venue_id} onClick={() => setSelectedVenue(v)}
                  className={`w-full text-left p-3 rounded-lg border transition-colors ${selectedVenue?.venue_id === v.venue_id ? 'bg-indigo-950/60 border-indigo-700' : 'bg-slate-950/50 border-slate-800 hover:border-slate-600'}`}>
                  <span className="flex justify-between gap-3"><span className="font-medium text-slate-100 truncate">{v.venue_name}</span><span className="text-xs text-slate-400 shrink-0">{v.total_matches} matches</span></span>
                  <span className="block text-xs text-slate-500 mt-1">{[v.city, v.country].filter(Boolean).join(', ') || 'Location unavailable'}</span>
                </button>)}
                {filteredVenues.length === 0 && <EmptyState message="No grounds found for this format and search." />}
              </div>
            </section>
            <section className="xl:col-span-8 min-w-0">
              {!selectedVenue && <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-12 text-center text-slate-400">Select a ground to load its historical analytics.</div>}
              {selectedVenue && <>
                {groundLoading && <LoadingSpinner message={`Loading ${selectedVenue.venue_name} analytics...`} />}
                {groundError && <div className="rounded-xl border border-red-900/70 bg-red-950/30 p-5 text-sm text-red-200"><p>{groundError}</p><button onClick={refetchGround} className="mt-3 px-3 py-1.5 rounded bg-red-900/60 hover:bg-red-900">Retry</button></div>}
                {groundAnalytics?.venue?.id === selectedVenue.venue_id && groundAnalytics?.format === groundFormat && <GroundAnalyticsView data={groundAnalytics} />}
              </>}
            </section>
          </div>}
        </div>
      )}

      {/* ================= TAB 2: TEAMS ================= */}
      {activeTab === 'teams' && (
        <div>
          {teamsLoading && <LoadingSpinner message="Loading team directory..." />}
          {teamsError && <ErrorState message={teamsError} />}

          {teamsData && (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              {/* Left Column: Team Directory */}
              <div className="lg:col-span-5 bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col h-[650px]">
                <div className="flex justify-between items-center mb-3">
                  <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    Select a Team
                  </h3>
                  <span className="text-xs text-slate-500 font-mono">
                    {filteredTeams.length} available
                  </span>
                </div>
                <input
                  type="text"
                  placeholder="Search team name (e.g. India, Mumbai, England)..."
                  value={teamSearch}
                  onChange={e => setTeamSearch(e.target.value)}
                  className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 mb-3 focus:outline-none focus:border-indigo-500 placeholder-slate-600"
                />

                <div className="flex-1 overflow-y-auto space-y-1.5 pr-1">
                  {filteredTeams.map(t => {
                    const isSelected = selectedTeam?.id === t.id;
                    return (
                      <button
                        key={t.id}
                        onClick={() => setSelectedTeam(t)}
                        className={`w-full text-left px-3 py-2.5 rounded-lg text-sm flex items-center justify-between transition-colors ${
                          isSelected
                            ? 'bg-indigo-900/60 text-white border border-indigo-700'
                            : 'bg-slate-800/40 hover:bg-slate-800 text-slate-300 border border-transparent'
                        }`}
                      >
                        <span className="font-medium truncate">{t.canonical_name}</span>
                        <span className="text-xs font-mono text-slate-400 shrink-0 ml-2">
                          {t.matches_played} matches
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Right Column: In-Depth Team Record & Splits */}
              <div className="lg:col-span-7">
                {!selectedTeam ? (
                  <div className="bg-slate-900 border border-slate-800 rounded-xl p-12 text-center">
                    <p className="text-slate-400 mb-2">Select a team from the left to view comprehensive performance analytics.</p>
                    <p className="text-xs text-slate-600">Includes win rates, batting-first vs chasing splits, and tactical indicators.</p>
                  </div>
                ) : (
                  <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-6">
                    {/* Header with format switcher & export */}
                    <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 pb-4 border-b border-slate-800">
                      <div>
                        <h2 className="text-xl font-bold text-white">{selectedTeam.canonical_name}</h2>
                        <span className="text-xs text-slate-500 font-mono">ID: {selectedTeam.id}</span>
                        <p className="text-xs text-slate-400 mt-1">{teamGender==='all' ? "Men's and women's records combined" : `${teamGender==='male' ? "Men's" : "Women's"} match records`}{selectedTeamStats?.team_country ? ` · Country: ${selectedTeamStats.team_country}` : ''}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <select
                          value={teamFormat}
                          onChange={e => setTeamFormat(e.target.value)}
                          className="bg-slate-800 border border-slate-700 rounded px-2.5 py-1 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                        >
                          <option value="T20">T20 + T20I</option>
                          <option value="ODI">ODI + ODM</option>
                          <option value="Test">Test + MDM</option>
                        </select>
                        <button
                          onClick={exportTeamCSV}
                          disabled={!selectedTeamStats}
                          className="px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded border border-slate-700 transition-colors flex items-center gap-1 disabled:opacity-50"
                        >
                          <span>⬇</span> CSV
                        </button>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 md:grid-cols-6 gap-2 border-b border-slate-800 pb-4">
                      <select aria-label="Team gender" value={teamGender} onChange={e=>setTeamGender(e.target.value)} className="bg-slate-800 border border-slate-700 rounded px-2 py-2 text-xs text-slate-200"><option value="male">Men's</option><option value="female">Women's</option><option value="all">Men + Women</option></select>
                      <select aria-label="Team period" value={teamPeriod} onChange={e=>{setTeamPeriod(e.target.value);setTeamFrom('');setTeamTo('');}} className="bg-slate-800 border border-slate-700 rounded px-2 py-2 text-xs text-slate-200"><option value="all">All time</option><option value="1">Last 1 year</option><option value="3">Last 3 years</option><option value="5">Last 5 years</option><option value="10">Last 10 years</option></select>
                      <input aria-label="Team country filter" placeholder="Country" value={teamCountry} onChange={e=>setTeamCountry(e.target.value)} className="bg-slate-800 border border-slate-700 rounded px-2 py-2 text-xs text-slate-200" />
                      <select aria-label="Team opposition filter" value={teamOpponent} onChange={e=>setTeamOpponent(e.target.value)} className="bg-slate-800 border border-slate-700 rounded px-2 py-2 text-xs text-slate-200"><option value="">All oppositions</option>{teamsData?.filter(t=>t.id!==selectedTeam.id).map(t=><option key={t.id} value={t.id}>{t.canonical_name}</option>)}</select>
                      <input aria-label="Team from year" type="number" placeholder="From year" value={teamFrom} onChange={e=>setTeamFrom(e.target.value)} className="bg-slate-800 border border-slate-700 rounded px-2 py-2 text-xs text-slate-200" />
                      <input aria-label="Team to year" type="number" placeholder="To year" value={teamTo} onChange={e=>setTeamTo(e.target.value)} className="bg-slate-800 border border-slate-700 rounded px-2 py-2 text-xs text-slate-200" />
                    </div>

                    {teamStatsLoading && <LoadingSpinner message="Calculating team splits..." />}
                    {teamStatsError && <ErrorState message={teamStatsError} />}

                    {selectedTeamStats && (
                      <div className="space-y-6">
                        {/* Overall Record Stat Cards */}
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                          <StatCard label="Matches" value={selectedTeamStats.total_matches} />
                          <StatCard label="Wins" value={selectedTeamStats.wins} highlight />
                          <StatCard label="Losses" value={selectedTeamStats.losses} />
                          <StatCard label="Loss %" value={fmt(selectedTeamStats.loss_percentage, '%')} />
                          <StatCard
                            label="Win %"
                            value={fmt(selectedTeamStats.win_percentage, '%')}
                            highlight
                          />
                        </div>

                        {/* Visual Overall Win/Loss Bar */}
                        {selectedTeamStats.total_matches > 0 && (
                          <div>
                            <div className="flex justify-between text-xs text-slate-400 mb-1">
                              <span>Wins: {selectedTeamStats.wins}</span>
                              <span>Ties: {selectedTeamStats.ties} · NR: {selectedTeamStats.no_results}</span>
                              <span>Losses: {selectedTeamStats.losses}</span>
                            </div>
                            <div className="h-3 w-full bg-slate-800 rounded-full overflow-hidden flex">
                              <div
                                style={{ width: `${(selectedTeamStats.wins / selectedTeamStats.total_matches) * 100}%` }}
                                className="bg-emerald-500 h-full"
                                title={`Wins: ${selectedTeamStats.wins}`}
                              />
                              <div
                                style={{ width: `${((selectedTeamStats.ties + selectedTeamStats.no_results) / selectedTeamStats.total_matches) * 100}%` }}
                                className="bg-slate-600 h-full"
                                title={`Ties/NR: ${selectedTeamStats.ties + selectedTeamStats.no_results}`}
                              />
                              <div
                                style={{ width: `${(selectedTeamStats.losses / selectedTeamStats.total_matches) * 100}%` }}
                                className="bg-rose-500 h-full"
                                title={`Losses: ${selectedTeamStats.losses}`}
                              />
                            </div>
                          </div>
                        )}

                        {/* Batting First vs Chasing Splits */}
                        <div className="bg-slate-800/40 border border-slate-800 rounded-lg p-4 space-y-4">
                          <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
                            Batting First vs Chasing Disparity
                          </h4>

                          {/* Batting First */}
                          <div>
                            <div className="flex justify-between items-center text-xs mb-1">
                              <span className="text-slate-300 font-medium">Batting First</span>
                              <span className="text-slate-400 font-mono">
                                {selectedTeamStats.batting_first_wins} / {selectedTeamStats.batting_first_matches} matches (
                                <strong className="text-indigo-400">
                                  {fmt(selectedTeamStats.batting_first_win_pct, '%')}
                                </strong>)
                              </span>
                            </div>
                            <div className="h-2 w-full bg-slate-800 rounded-full overflow-hidden">
                              <div
                                style={{ width: `${selectedTeamStats.batting_first_win_pct || 0}%` }}
                                className="h-full bg-indigo-500 rounded-full"
                              />
                            </div>
                          </div>

                          {/* Chasing */}
                          <div>
                            <div className="flex justify-between items-center text-xs mb-1">
                              <span className="text-slate-300 font-medium">Chasing (Batting Second)</span>
                              <span className="text-slate-400 font-mono">
                                {selectedTeamStats.chasing_wins} / {selectedTeamStats.chasing_matches} matches (
                                <strong className="text-emerald-400">
                                  {fmt(selectedTeamStats.chasing_win_pct, '%')}
                                </strong>)
                              </span>
                            </div>
                            <div className="h-2 w-full bg-slate-800 rounded-full overflow-hidden">
                              <div
                                style={{ width: `${selectedTeamStats.chasing_win_pct || 0}%` }}
                                className="h-full bg-emerald-500 rounded-full"
                              />
                            </div>
                          </div>

                          {/* Tactical Insight Pill */}
                          {selectedTeamStats.batting_first_win_pct !== null && selectedTeamStats.chasing_win_pct !== null && (
                            <div className="pt-2 text-xs text-slate-400 flex items-center gap-2">
                              <span className="text-indigo-400">ℹ</span>
                              <span>
                                {Math.abs(selectedTeamStats.batting_first_win_pct - selectedTeamStats.chasing_win_pct) < 3 ? (
                                  'Demonstrates balanced performance regardless of toss outcome.'
                                ) : selectedTeamStats.chasing_win_pct > selectedTeamStats.batting_first_win_pct ? (
                                  <>Superior record when <strong>chasing</strong> (+{(selectedTeamStats.chasing_win_pct - selectedTeamStats.batting_first_win_pct).toFixed(1)}% higher win rate).</>
                                ) : (
                                  <>Superior record when <strong>defending targets</strong> (+{(selectedTeamStats.batting_first_win_pct - selectedTeamStats.chasing_win_pct).toFixed(1)}% higher win rate).</>
                                )}
                              </span>
                            </div>
                          )}
                        </div>
                        <TeamBreakdowns stats={selectedTeamStats} />
                        <section className="overflow-hidden rounded-xl border border-slate-800">
                          <h3 className="bg-slate-900 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-300">Recent matches · selected filters</h3>
                          <div className="overflow-x-auto"><table className="w-full min-w-[560px] text-left text-xs"><thead className="text-slate-500"><tr>{['Date','Format','Match','Venue','Result'].map(label=><th key={label} className="px-3 py-2">{label}</th>)}</tr></thead><tbody>{(selectedTeamStats.recent_matches || []).map(match=><tr key={match.match_id} className="border-t border-slate-800/80 text-slate-300"><td className="px-3 py-2"><MatchCentreLink matchId={match.match_id}>{match.date || 'Open scorecard'}</MatchCentreLink></td><td className="px-3 py-2">{match.format}</td><td className="px-3 py-2"><MatchCentreLink matchId={match.match_id}>{match.team1 || 'Team 1'} vs {match.team2 || 'Team 2'}</MatchCentreLink></td><td className="px-3 py-2 text-slate-400">{match.venue || 'N/A'}</td><td className="px-3 py-2">{match.winner ? `${match.winner} won` : match.result_type || 'Result unavailable'}</td></tr>)}</tbody></table>{!selectedTeamStats.recent_matches?.length && <p className="px-3 py-4 text-xs text-slate-500">No match records for the selected filters.</p>}</div>
                        </section>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function displayMetric(value, suffix = '') {
  return value === null || value === undefined ? '—' : `${value}${suffix}`;
}

function MiniBarChart({ title, items, label, value, color = 'bg-indigo-500', suffix = '' }) {
  const available = items.filter(item => value(item) !== null && value(item) !== undefined && Number.isFinite(Number(value(item))));
  const values = available.map(item => Number(value(item)));
  const max = Math.max(...values, 1);
  return <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
    <h3 className="text-sm font-semibold text-slate-200 mb-4">{title}</h3>
    {!available.length ? <p className="text-xs text-slate-500">Insufficient data for this comparison.</p> :
      <div className="space-y-3">{available.map((item, index) => {
        const amount = Number(value(item));
        return <div key={`${label(item)}-${index}`}>
          <div className="flex justify-between text-xs gap-3 mb-1"><span className="text-slate-400 truncate">{label(item)}</span><span className="font-mono text-slate-200 shrink-0">{amount}{suffix}</span></div>
          <div className="h-2 rounded bg-slate-800 overflow-hidden"><div className={`h-full rounded ${color}`} style={{ width: `${Math.max(0, Math.min(100, amount / max * 100))}%` }} /></div>
        </div>;
      })}</div>}
  </div>;
}

function GroundAnalyticsView({ data }) {
  const { venue, batting, bowling, match_conditions: conditions } = data;
  const outcomes = conditions.outcomes;
  const paceSpin = bowling.pace_spin || [];
  const phaseScoring = batting.phase_scoring || [];
  const phaseBowling = bowling.by_phase || [];
  const recent = conditions.recent || {};
  const isTest = data.format === 'Test';
  return <div className="space-y-5 min-w-0">
    <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-5">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
        <div><p className="text-[11px] uppercase tracking-wider text-indigo-300">Ground analysis · {data.format}</p>
          <h2 className="text-2xl font-bold text-white mt-1">{venue.name}</h2>
          <p className="text-sm text-slate-400 mt-1">{[venue.city,venue.country].filter(Boolean).join(', ') || 'Location unavailable'}</p></div>
        <div className="flex gap-2 flex-wrap">{data.format_match_counts.map(item => <Badge key={item.format}>{item.format} · {item.matches} matches</Badge>)}</div>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-5">
        <StatCard label="Matches" value={data.matches} sub="Selected format group" />
        <StatCard label="Avg 1st innings" value={displayMetric(batting.average_first_innings_score)} sub={`${batting.first_innings_sample} innings with deliveries`} highlight />
        <StatCard label="Avg 2nd innings" value={displayMetric(batting.average_second_innings_score)} sub={`${batting.second_innings_sample} innings with deliveries`} />
        <StatCard label="Decided matches" value={outcomes.decided_with_first_innings} sub={`${outcomes.no_result} no-result / abandoned`} />
      </div>
    </div>

    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <MiniBarChart title="First vs second innings scoring" items={[
        {name:'1st innings',score:batting.average_first_innings_score,sample:batting.first_innings_sample},
        {name:'2nd innings',score:batting.average_second_innings_score,sample:batting.second_innings_sample},
      ].filter(x=>x.score!==null)} label={x=>`${x.name} · n=${x.sample}`} value={x=>x.score} suffix=" runs" />
      <MiniBarChart title={isTest ? 'Innings-one side vs opposition win rate' : 'Batting first vs chasing win rate'} items={[
        {name:isTest ? 'Innings-one side' : 'Batting first',rate:outcomes.batting_first_win_percentage,n:outcomes.decided_with_first_innings},
        {name:isTest ? 'Opposition' : 'Chasing',rate:outcomes.chasing_win_percentage,n:outcomes.decided_with_first_innings},
      ].filter(x=>x.rate!==null)} label={x=>`${x.name} · n=${x.n}`} value={x=>x.rate} color="bg-emerald-500" suffix="%" />
      <MiniBarChart title={isTest ? 'Innings progression scoring (20-over bands)' : 'Average scoring by match phase'}
        items={phaseScoring.map(p=>({...p,name:`${p.format} · ${p.phase} · n=${p.sample_innings}`}))}
        label={x=>x.name} value={x=>x.average_runs} color="bg-cyan-500" suffix=" runs" />
      <MiniBarChart title="Pace vs spin bowler-credit wickets" items={paceSpin.filter(x=>x.wickets>0)}
        label={x=>`${x.style} · ${x.wickets} wickets`} value={x=>x.wickets} color="bg-amber-500" suffix=" wkts" />
      <MiniBarChart title="Pace vs spin economy" items={paceSpin.filter(x=>x.economy!==null)}
        label={x=>`${x.style} · ${x.legal_balls ? (x.legal_balls/6).toFixed(1) : 0} overs`} value={x=>x.economy} color="bg-cyan-500" suffix=" runs/6 balls" />
      <MiniBarChart title="Wickets lost by innings" items={(batting.average_wickets_lost||[]).filter(x=>x.average_wickets_lost!==null)}
        label={x=>`${x.innings} innings · n=${x.sample_innings}`} value={x=>x.average_wickets_lost} color="bg-rose-500" suffix=" wickets" />
    </div>

    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold text-slate-200">Recent ground form</h3><span className="text-xs text-slate-500">Latest {recent.sample_matches || 0} of {recent.requested_matches || 10} requested matches</span></div>
      <MiniBarChart title="Recent vs selected-period first-innings average" items={[
        {name:`Recent · n=${recent.first_innings_sample || 0}`,value:recent.average_first_innings_score},
        {name:`Selected period · n=${batting.first_innings_sample}`,value:batting.average_first_innings_score},
      ].filter(x=>x.value!==null)} label={x=>x.name} value={x=>x.value} color="bg-cyan-500" suffix=" runs" />
      <MiniBarChart title="Recent vs selected-period second-innings average" items={[
        {name:`Recent · n=${recent.second_innings_sample || 0}`,value:recent.average_second_innings_score},
        {name:`Selected period · n=${batting.second_innings_sample}`,value:batting.average_second_innings_score},
      ].filter(x=>x.value!==null)} label={x=>x.name} value={x=>x.value} color="bg-violet-500" suffix=" runs" />
      <div className="overflow-x-auto"><table className="w-full text-xs text-left"><thead className="text-slate-500 border-b border-slate-800"><tr>{['Date','Format','Match','Result'].map(x=><th key={x} className="p-2">{x}</th>)}</tr></thead><tbody>{(recent.results || []).map(m=><tr key={m.match_id} className="border-b border-slate-800/70 text-slate-300"><td className="p-2"><MatchCentreLink matchId={m.match_id}>{m.date}</MatchCentreLink></td><td className="p-2">{m.format}</td><td className="p-2"><MatchCentreLink matchId={m.match_id}>{m.team1 || 'Unknown'} vs {m.team2 || 'Unknown'}</MatchCentreLink></td><td className="p-2">{m.winner ? `${m.winner} won` : (m.result_type || 'Result unavailable')}</td></tr>)}</tbody></table></div>
    </div>

    {data.format_comparison?.length > 1 && <MiniBarChart title="Stored-format comparison · average first-innings score"
      items={data.format_comparison.filter(x=>x.average_first_innings_score!==null).map(x=>({...x,name:`${x.format} · n=${x.first_innings_sample}`}))}
      label={x=>x.name} value={x=>x.average_first_innings_score} color="bg-fuchsia-500" suffix=" runs" />}

    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <MiniBarChart title="Phase wickets by bowling style" items={phaseBowling.filter(x=>x.wickets>0).map(x=>({...x,name:`${x.style} · ${x.phase} · n=${x.sample_innings}`}))} label={x=>x.name} value={x=>x.wickets} color="bg-amber-500" suffix=" wkts" />
      <MiniBarChart title="Phase economy by bowling style" items={phaseBowling.filter(x=>x.economy!==null).map(x=>({...x,name:`${x.style} · ${x.phase} · ${(x.legal_balls/6).toFixed(1)} overs`}))} label={x=>x.name} value={x=>x.economy} color="bg-indigo-500" suffix=" runs/6 balls" />
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 overflow-x-auto">
        <h3 className="text-sm font-semibold text-slate-200 mb-3">Pace vs spin effectiveness</h3>
        <table className="w-full text-xs text-left min-w-[580px]"><thead className="text-slate-500 border-b border-slate-800"><tr>{['Style','Wkts / innings','Economy','Bowling avg','Strike rate','Dot %','Boundary %','Wicket share'].map(h=><th key={h} className="p-2">{h}</th>)}</tr></thead>
          <tbody>{paceSpin.map(row=><tr key={row.style} className="border-b border-slate-800/70 text-slate-300"><td className="p-2 capitalize font-medium">{row.style}</td><td className="p-2">{displayMetric(row.wickets_per_innings)}</td><td className="p-2">{displayMetric(row.economy)}</td><td className="p-2">{displayMetric(row.bowling_average)}</td><td className="p-2">{displayMetric(row.bowling_strike_rate)}</td><td className="p-2">{displayMetric(row.dot_ball_percentage,'%')}</td><td className="p-2">{displayMetric(row.boundary_percentage_conceded,'%')}</td><td className="p-2">{displayMetric(row.wicket_share_percentage,'%')}</td></tr>)}</tbody>
        </table>
        <p className="text-[11px] text-slate-500 mt-2">Unknown style: {bowling.unknown_style.deliveries.toLocaleString()} deliveries, {bowling.unknown_style.wickets} bowler-credit wickets; excluded from pace/spin rates.</p>
      </div>
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 overflow-x-auto">
        <h3 className="text-sm font-semibold text-slate-200 mb-3">{isTest ? 'Bowling by innings progression band' : 'Bowling by match phase'}</h3>
        <table className="w-full text-xs text-left min-w-[680px]"><thead className="text-slate-500 border-b border-slate-800"><tr>{['Format','Style','Phase','Overs','Wkts','Runs','Eco','Avg','SR','Dot %','Boundary %'].map(h=><th key={h} className="p-2">{h}</th>)}</tr></thead>
          <tbody>{phaseBowling.map((r,i)=><tr key={`${r.format}-${r.style}-${r.phase}-${i}`} className="border-b border-slate-800/70 text-slate-300"><td className="p-2">{r.format}</td><td className="p-2 capitalize">{r.style}</td><td className="p-2">{r.phase}</td><td className="p-2">{(r.legal_balls/6).toFixed(1)}</td><td className="p-2">{r.wickets}</td><td className="p-2">{r.runs_conceded}</td><td className="p-2">{displayMetric(r.economy)}</td><td className="p-2">{displayMetric(r.bowling_average)}</td><td className="p-2">{displayMetric(r.bowling_strike_rate)}</td><td className="p-2">{displayMetric(r.dot_ball_percentage,'%')}</td><td className="p-2">{displayMetric(r.boundary_percentage_conceded,'%')}</td></tr>)}</tbody>
        </table>
      </div>
    </div>

    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 overflow-x-auto">
        <h3 className="text-sm font-semibold text-slate-200 mb-3">Scores and wickets by innings</h3>
        <table className="w-full text-sm text-left"><thead className="text-slate-500 border-b border-slate-800"><tr><th className="p-2">Innings</th><th className="p-2">Avg score</th><th className="p-2">Avg wickets lost</th><th className="p-2">Samples</th></tr></thead>
          <tbody>{data.innings.map(row=>{const wickets=batting.average_wickets_lost.find(x=>x.innings===row.innings);return <tr key={row.innings} className="border-b border-slate-800/70 text-slate-300"><td className="p-2">{row.innings}</td><td className="p-2">{displayMetric(row.average_score)}</td><td className="p-2">{displayMetric(wickets?.average_wickets_lost)}</td><td className="p-2">{row.sample_innings}</td></tr>;})}</tbody>
        </table>
        <p className="text-xs text-slate-500 mt-3">Team totals span {batting.team_total_innings_sample} observed non-super-over innings. Highest: {displayMetric(batting.highest_team_total)} · Lowest: {displayMetric(batting.lowest_team_total)}.</p>
      </div>
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 overflow-x-auto">
        <h3 className="text-sm font-semibold text-slate-200 mb-3">Toss decision and outcomes</h3>
        <MiniBarChart title="Toss winner match-win rate" items={outcomes.toss_decision.filter(row=>row.toss_winner_win_percentage!==null).map(row=>({...row,name:`${row.decision} · n=${row.matches}`}))} label={x=>x.name} value={x=>x.toss_winner_win_percentage} color="bg-emerald-500" suffix="%" />
        <table className="w-full text-sm text-left"><thead className="text-slate-500 border-b border-slate-800"><tr><th className="p-2">Toss choice</th><th className="p-2">Matches decided</th><th className="p-2">Toss winner won</th><th className="p-2">Win %</th></tr></thead>
          <tbody>{outcomes.toss_decision.map(row=><tr key={row.decision} className="border-b border-slate-800/70 text-slate-300"><td className="p-2 capitalize">{row.decision}</td><td className="p-2">{row.matches}</td><td className="p-2">{row.toss_winner_wins}</td><td className="p-2">{displayMetric(row.toss_winner_win_percentage,'%')}</td></tr>)}</tbody>
        </table>
        <p className="text-xs text-slate-500 mt-3">Result rates use matches with a recorded winner and first innings team; ties and no-results are excluded.</p>
      </div>
    </div>

    {!!conditions.year_trends.length && <LineChart title="Historical first-innings scoring trend by year" subtitle="Yearly average of observed first-innings scores; sample sizes are shown in each point's accessible label when inspected in the table above." data={conditions.year_trends.filter(x=>x.average_first_innings_score!==null).map(x=>({label:x.year,value:x.average_first_innings_score}))} formatter={value=>Number(value).toFixed(1)} color="#c084fc" />}

    <div className="rounded-xl border border-indigo-900/60 bg-indigo-950/20 p-4">
      <h3 className="text-sm font-semibold text-indigo-200 mb-2">Ground insights</h3>
      <ul className="list-disc pl-5 space-y-1 text-sm text-slate-300">{data.insights.map((text,i)=><li key={i}>{text}</li>)}</ul>
      <p className="text-[11px] text-slate-500 mt-3">{data.limitations.phase_rules} {data.limitations.shortened_matches} {data.limitations.super_overs} Conclusions are shown only when their match or wicket sample threshold is met.</p>
    </div>
  </div>;
}

function TeamBreakdowns({ stats }) {
  const rows = [
    ['Wins by country', stats.by_country], ['Wins by ground', stats.by_ground],
    ['Opponent record', stats.by_opponent], ['Toss decision and outcome', stats.toss_decisions],
  ];
  return <div className="space-y-4">
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <BarChart title="Match outcomes" subtitle={`Filtered ${stats.filters?.format || 'all-format'} record · n=${stats.total_matches}`} data={[
        {label:'Wins',value:stats.wins,color:'#34d399'},
        {label:'Losses',value:stats.losses,color:'#fb7185'},
        {label:'Ties',value:stats.ties,color:'#fbbf24'},
        {label:'No result',value:stats.no_results,color:'#64748b'},
      ]} formatter={value => Math.round(value).toLocaleString()} />
      <BarChart title="Win rate by match context" subtitle="Rates use the selected format, date range, country, opposition and gender filters." data={[
        {label:`Batting first · n=${stats.batting_first_matches}`,value:stats.batting_first_win_pct},
        {label:`Chasing · n=${stats.chasing_matches}`,value:stats.chasing_win_pct},
        ...Object.entries(stats.home_away || {}).filter(([kind,row])=>kind!=='unknown' && row.matches>0).map(([kind,row])=>({label:`${kind} · n=${row.matches}`,value:row.matches ? row.wins*100/row.matches : null})),
      ].filter(row=>row.value!=null)} formatter={value => `${Number(value).toFixed(1)}%`} color="#22d3ee" />
    </div>
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <BarChart title="Win rate by country" subtitle="Ground country, not team nationality; labels include match sample size." data={[...(stats.by_country||[])].filter(row=>row.win_percentage!=null&&row.matches>0).sort((a,b)=>b.win_percentage-a.win_percentage).slice(0,8).map(row=>({label:`${row.name} · n=${row.matches}`,value:row.win_percentage}))} formatter={value=>`${Number(value).toFixed(1)}%`} color="#34d399" />
      <BarChart title="Win rate by ground" subtitle="Highest win-rate grounds with actual recorded match outcomes." data={[...(stats.by_ground||[])].filter(row=>row.win_percentage!=null&&row.matches>0).sort((a,b)=>b.win_percentage-a.win_percentage).slice(0,8).map(row=>({label:`${row.name} · n=${row.matches}`,value:row.win_percentage}))} formatter={value=>`${Number(value).toFixed(1)}%`} color="#818cf8" />
      <BarChart title="Win rate by opponent" subtitle="Head-to-head win rate in the active format, gender and date filters." data={[...(stats.by_opponent||[])].filter(row=>row.win_percentage!=null&&row.matches>0).sort((a,b)=>b.win_percentage-a.win_percentage).slice(0,8).map(row=>({label:`${row.name} · n=${row.matches}`,value:row.win_percentage}))} formatter={value=>`${Number(value).toFixed(1)}%`} color="#fbbf24" />
    </div>
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
      <StatCard label="Ties" value={stats.ties} /><StatCard label="No results" value={stats.no_results} /><StatCard label="Unresolved results" value={stats.unresolved} />
    </div>
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">{rows.map(([title, values])=><div key={title} className="rounded-lg border border-slate-800 bg-slate-800/30 p-4 overflow-auto max-h-96"><h3 className="text-xs uppercase tracking-wide text-slate-300 mb-3">{title}</h3><table className="w-full text-xs text-left"><thead className="text-slate-500"><tr><th className="py-1">Name / choice</th><th>W-L-T-NR</th><th>Win %</th><th>n</th></tr></thead><tbody>{values.map(row=><tr key={row.name} className="border-t border-slate-800 text-slate-300"><td className="py-2 pr-2">{row.name}</td><td>{row.wins}-{row.losses}-{row.ties}-{row.no_results}</td><td>{displayMetric(row.win_percentage,'%')}</td><td>{row.matches}</td></tr>)}{!values.length&&<tr><td colSpan="4" className="py-3 text-slate-500">No records for this filter.</td></tr>}</tbody></table></div>)}</div>
    <div className="rounded-lg border border-slate-800 bg-slate-800/30 p-4"><h3 className="text-xs uppercase tracking-wide text-slate-300 mb-2">Home / away / neutral</h3><div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs text-slate-300">{Object.entries(stats.home_away).map(([kind,row])=><div key={kind}><span className="capitalize">{kind}</span><div className="text-slate-500 mt-1">{row.wins}/{row.matches} wins</div></div>)}</div><p className="text-[11px] text-slate-500 mt-2">Classification compares venue country with both teams’ stored country mappings. CPI currently has no ground-country values for its 543 venue records; {stats.home_away_coverage.ground_country_missing} selected matches therefore remain unknown until that reference data is available. {stats.home_away_coverage.team_country_missing} matches also have at least one unmapped team.</p></div>
    <div className="rounded-lg border border-indigo-900/60 bg-indigo-950/20 p-4"><h3 className="text-xs uppercase tracking-wide text-indigo-200 mb-2">Team insights · n={stats.filters.sample_matches}</h3>{stats.insights.length?<ul className="list-disc pl-5 space-y-1 text-sm text-slate-300">{stats.insights.map((s,i)=><li key={i}>{s}</li>)}</ul>:<p className="text-xs text-slate-500">Insufficient sample size for a reliable team insight.</p>}</div>
  </div>;
}
