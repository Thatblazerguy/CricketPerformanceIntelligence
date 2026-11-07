/**
 * Individual Player Performance Intelligence Profile
 * Comprehensive individual player analytics workspace:
 * - Batting & Bowling career benchmarks
 * - Pace vs Spin splits (runs, balls, SR, boundary %, dot %)
 * - Phase-by-phase breakdown (Powerplay, Middle, Death overs)
 * - Format breakdown (Test, ODI, T20, T20I)
 * - Opponent team and Venue performance records
 * - Year-wise trajectory and recent match logs
 * - Automated strengths & weaknesses
 * - Machine Learning cosine similarity engine
 * - Dynamic profile-level filters for Format, Years, Season, Opponent, Venue, Pace/Spin, Phase
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  getPlayer,
  getPlayerAnalytics,
  getPlayerFilterMetadata,
  getPlayerSimilar,
  getPlayerSimilarBowlers,
  getPlayerSimilarAllRounders
} from '../../services/api';
import {
  LoadingSpinner, ErrorState, EmptyState, StatCard, Badge
} from '../../components/ui';
import { BarChart, LineChart } from '../../components/charts';

export default function PlayerProfile() {
  const { id } = useParams();

  // Filter State
  const [format, setFormat] = useState('T20');
  const [startYear, setStartYear] = useState('');
  const [endYear, setEndYear] = useState('');
  const [appliedStartYear, setAppliedStartYear] = useState('');
  const [appliedEndYear, setAppliedEndYear] = useState('');
  const [yearFilterError, setYearFilterError] = useState('');
  const invalidYearRange = Boolean(startYear && endYear && Number(startYear) > Number(endYear));
  const [season, setSeason] = useState('');
  const [vsTeamId, setVsTeamId] = useState('');
  const [venueId, setVenueId] = useState('');
  const [bowlingStyle, setBowlingStyle] = useState('');
  const [phase, setPhase] = useState('');
  const phaseLabels = ['ODI', 'ODM'].includes(format)
    ? { powerplay: 'Powerplay (1–10)', middle: 'Middle (11–40)', death: 'Death (41–50)' }
    : ['T20', 'T20I'].includes(format)
      ? { powerplay: 'Powerplay (1–6)', middle: 'Middle (7–15)', death: 'Death (16–20)' }
      : null;

  // Active Tab
  const [activeTab, setActiveTab] = useState('overview'); // 'overview', 'splits', 'opponents', 'trends', 'similar'

  // Metadata State (Venues, Teams, Years)
  const [metadata, setMetadata] = useState(null);
  const [metadataLoading, setMetadataLoading] = useState(true);
  const [metadataError, setMetadataError] = useState('');

  // Profile Analytics Data
  const [analytics, setAnalytics] = useState(null);
  const [playerBio, setPlayerBio] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => { let active = true; getPlayer(id).then(data => { if (active) setPlayerBio(data); }).catch(() => {}); return () => { active = false; }; }, [id]);

  // ML Similar Players
  const [similarData, setSimilarData] = useState(null);
  const [bowlerSimilarData, setBowlerSimilarData] = useState(null);
  const [allRounderSimilarData, setAllRounderSimilarData] = useState(null);
  const [similarLoading, setSimilarLoading] = useState(false);
  const [similarMode, setSimilarMode] = useState('batter');

  // Load all directory-backed filter options when the profile opens. These are
  // needed by the filters themselves, not only by the all-rounder similarity tab.
  useEffect(() => {
    let mounted = true;
    getPlayerFilterMetadata()
      .then(res => {
        if (mounted) {
          setMetadata(res);
          setMetadataError('');
        }
      })
      .catch(err => {
        if (mounted) setMetadataError(err.message || 'Could not load filter options.');
      })
      .finally(() => { if (mounted) setMetadataLoading(false); });
    return () => { mounted = false; };
  }, [id]);

  // Fetch player analytics whenever filters change
  const fetchAnalytics = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = {
        format: format || undefined,
        start_year: appliedStartYear ? Number(appliedStartYear) : undefined,
        end_year: appliedEndYear ? Number(appliedEndYear) : undefined,
        season: season || undefined,
        vs_team_id: vsTeamId || undefined,
        venue_id: venueId || undefined,
        bowling_style: bowlingStyle || undefined,
        phase: phase || undefined,
      };

      const res = await getPlayerAnalytics(id, params);
      setAnalytics(res);
    } catch (err) {
      setError(err.message || 'Failed to fetch player analytics profile.');
    } finally {
      setLoading(false);
    }
  }, [id, format, appliedStartYear, appliedEndYear, season, vsTeamId, venueId, bowlingStyle, phase]);

  useEffect(() => {
    fetchAnalytics();
  }, [fetchAnalytics]);

  // Fetch ML similar players for the current format
  useEffect(() => {
    if (activeTab !== 'similar' || similarMode !== 'batter') return;
    let mounted = true;
    setSimilarLoading(true);
    getPlayerSimilar(id, { format: format || 'T20', limit: 10 })
      .then(res => {
        if (mounted) {
          setSimilarData(res);
          setSimilarLoading(false);
        }
      })
      .catch(() => {
        if (mounted) {
          setSimilarData(null);
          setSimilarLoading(false);
        }
      });
    return () => { mounted = false; };
  }, [id, format, activeTab, similarMode]);

  useEffect(() => {
    if (activeTab !== 'similar' || similarMode !== 'all_rounder') return;
    let mounted = true;
    getPlayerSimilarAllRounders(id, { format: format || 'T20', limit: 10 })
      .then(res => { if (mounted) setAllRounderSimilarData(res); })
      .catch(() => { if (mounted) setAllRounderSimilarData(null); });
    return () => { mounted = false; };
  }, [id, format, activeTab, similarMode]);

  useEffect(() => {
    if (activeTab !== 'similar' || similarMode !== 'bowler') return;
    let mounted = true;
    getPlayerSimilarBowlers(id, { format: format || 'T20', limit: 10 })
      .then(res => { if (mounted) setBowlerSimilarData(res); })
      .catch(() => { if (mounted) setBowlerSimilarData(null); });
    return () => { mounted = false; };
  }, [id, format, activeTab, similarMode]);

  // Reset profile filters
  const handleResetFilters = () => {
    setFormat('T20');
    setStartYear('');
    setEndYear('');
    setAppliedStartYear('');
    setAppliedEndYear('');
    setYearFilterError('');
    setSeason('');
    setVsTeamId('');
    setVenueId('');
    setBowlingStyle('');
    setPhase('');
  };

  const applyYearFilters = () => {
    if (startYear && endYear && Number(startYear) > Number(endYear)) {
      setYearFilterError('From Year must be earlier than or equal to To Year.');
      return;
    }
    setYearFilterError('');
    setAppliedStartYear(startYear);
    setAppliedEndYear(endYear);
  };

  const activeFiltersCount = useMemo(() => {
    let count = 0;
    if (format) count++;
    if (appliedStartYear || appliedEndYear) count++;
    if (season) count++;
    if (vsTeamId) count++;
    if (venueId) count++;
    if (bowlingStyle) count++;
    if (phase) count++;
    return count;
  }, [format, appliedStartYear, appliedEndYear, season, vsTeamId, venueId, bowlingStyle, phase]);

  // Export full profile analytics as CSV
  const handleExportCSV = () => {
    if (!analytics) return;
    const { player_name, batting, bowling, pace_spin, phases, format_breakdown, by_opponent, by_venue, year_trends } = analytics;
    const lines = [
      ['Report', 'Cricket Performance Intelligence — Comprehensive Player Profile'],
      ['Player Name', player_name],
      ['Format Filter', format || 'All Formats'],
      ['Date Range', `${appliedStartYear || 'Any'} - ${appliedEndYear || 'Any'}`],
      [],
      ['=== OVERALL BATTING BENCHMARKS ==='],
      ['Matches', batting.matches],
      ['Innings', batting.innings],
      ['Runs', batting.runs],
      ['Balls Faced', batting.balls_faced],
      ['Batting Average', batting.average ?? '—'],
      ['Strike Rate', batting.strike_rate ?? '—'],
      ['Highest Score', batting.highest_score],
      ['Fours', batting.fours],
      ['Sixes', batting.sixes],
      ['Boundary %', `${batting.boundary_percentage ?? '—'}%`],
      ['Dot Ball %', `${batting.dot_ball_percentage ?? '—'}%`],
      [],
      ['=== OVERALL BOWLING BENCHMARKS ==='],
      ['Innings Bowled', bowling.innings_bowled],
      ['Overs', bowling.overs_display],
      ['Wickets', bowling.wickets],
      ['Runs Conceded', bowling.runs_conceded],
      ['Economy Rate', bowling.economy_rate ?? '—'],
      ['Bowling Average', bowling.bowling_average ?? '—'],
      ['Bowling Strike Rate', bowling.bowling_strike_rate ?? '—'],
      ['Dot Ball %', `${bowling.dot_ball_percentage ?? '—'}%`],
      [],
      ['=== PACE VS SPIN PERFORMANCE ==='],
      ['Style', 'Runs', 'Balls', 'Strike Rate', 'Average', 'Fours', 'Sixes', 'Dot %', 'Boundary %'],
      ...pace_spin.map(p => [p.style.toUpperCase(), p.runs, p.balls, p.strike_rate ?? '', p.average ?? '', p.fours, p.sixes, `${p.dot_ball_percentage ?? ''}%`, `${p.boundary_percentage ?? ''}%`]),
      [],
      ['=== PHASE PERFORMANCE ==='],
      ['Phase', 'Role', 'Runs', 'Balls', 'Strike Rate', 'Average', 'Fours', 'Sixes', 'Dot %'],
      ...phases.map(p => [p.phase.toUpperCase(), p.role, p.runs, p.balls, p.strike_rate ?? '', p.average ?? '', p.fours, p.sixes, `${p.dot_ball_percentage ?? ''}%`]),
      [],
      ['=== FORMAT COMPARISON ==='],
      ['Format', 'Matches', 'Innings', 'Runs', 'Balls', 'Bat Avg', 'Bat SR', 'Wkts', 'Economy'],
      ...format_breakdown.map(f => [f.format, f.matches, f.innings_batted, f.runs, f.balls_faced, f.batting_average ?? '', f.batting_strike_rate ?? '', f.wickets, f.economy_rate ?? '']),
      [],
      ['=== TOP OPPONENT TEAMS ==='],
      ['Opponent', 'Matches', 'Runs', 'Balls', 'Strike Rate'],
      ...by_opponent.map(o => [o.opponent_name, o.matches, o.runs, o.balls_faced, o.batting_strike_rate ?? '']),
      [],
      ['=== TOP GROUNDS / VENUES ==='],
      ['Venue', 'Matches', 'Runs', 'Balls', 'Strike Rate'],
      ...by_venue.map(v => [v.venue_name, v.matches, v.runs, v.balls_faced, v.batting_strike_rate ?? '']),
    ];

    const csvContent = 'data:text/csv;charset=utf-8,' + lines.map(r => r.join(',')).join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `cpi-player-profile-${player_name.toLowerCase().replace(/\s+/g, '-')}-${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const formatsList = [
    { id: '', label: 'All Formats' },
    { id: 'T20I', label: 'T20I (International)' },
    { id: 'T20', label: 'T20 (Franchise)' },
    { id: 'ODI', label: 'ODI' },
    { id: 'Test', label: 'Test' },
    { id: 'MDM', label: 'Multi-day domestic' },
    { id: 'ODM', label: 'One-day domestic' },
  ];

  const activeSimilarityData = similarMode === 'bowler'
    ? bowlerSimilarData
    : similarMode === 'all_rounder' ? allRounderSimilarData : similarData;

  return (
    <div className="space-y-6">
      {playerBio?.analytics_notice && <section className="rounded-lg border border-amber-800 bg-amber-950/30 p-4 text-sm text-amber-200">
        <p>{playerBio.analytics_notice}</p>
        <p className="mt-1 text-xs text-amber-300/80">Source: {playerBio.data_source} · Availability: {playerBio.data_availability}</p>
        {playerBio.external_basic_stats && <pre className="mt-3 whitespace-pre-wrap text-xs text-slate-300">{JSON.stringify(playerBio.external_basic_stats, null, 2)}</pre>}
      </section>}
      {/* Breadcrumb Navigation */}
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <Link to="/players" className="hover:text-indigo-400 transition-colors">Players</Link>
        <span>/</span>
        <span className="text-slate-200 font-medium">{analytics?.player_name || 'Player Profile'}</span>
      </div>

      {/* Profile Header Card */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-start gap-4">
          <div className="w-14 h-14 rounded-xl bg-indigo-950/80 border border-indigo-700/60 flex items-center justify-center text-indigo-300 font-bold text-xl shadow-inner">
            {analytics?.player_name ? analytics.player_name.split(' ').map(n => n[0]).join('').slice(0, 2) : 'CR'}
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-2xl font-bold text-white tracking-tight">{analytics?.player_name}</h1>
              {analytics?.primary_role && (
                <span className="bg-indigo-900/50 text-indigo-300 border border-indigo-700/70 text-xs px-2.5 py-0.5 rounded-full font-semibold">
                  {analytics.primary_role}
                </span>
              )}
            </div>
            {analytics?.source_player_id && (
              <span className="text-[11px] font-mono text-slate-500 mt-1 inline-block">
                Source ID: {analytics.source_player_id}
              </span>
            )}
            <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[11px] text-slate-400">
              {analytics?.age != null && <span>Age {analytics.age}</span>}
              {analytics?.nationality && <span>{analytics.nationality}</span>}
              {analytics?.official_role && <span>Board role: {analytics.official_role}</span>}
              {analytics?.batting_style && <span>{analytics.batting_style}</span>}
              {analytics?.bowling_style && <span>{analytics.bowling_style}</span>}
            </div>
            {analytics?.role_source && (
              <span className="text-[10px] text-slate-500 mt-1 inline-block">
                Classification: {analytics.role_source} · {analytics.role_confidence} confidence
              </span>
            )}
            {playerBio?.data_source && <span className="text-[10px] text-slate-500 mt-1 block">Data: {playerBio.data_source} · {playerBio.data_availability} availability</span>}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-3">
          <button
            onClick={handleExportCSV}
            disabled={!analytics}
            className="flex items-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 px-3.5 py-2 rounded-lg text-xs font-medium transition-colors shadow-sm disabled:opacity-40"
          >
            <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Export Profile CSV
          </button>
          <Link
            to={`/matchups?batter=${id}`}
            className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-lg text-xs font-semibold transition-colors shadow-lg shadow-indigo-900/30"
          >
            Head-to-Head Matchup →
          </Link>
        </div>
      </div>

      {/* Comprehensive Profile Filter Bar */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4 shadow-lg space-y-3">
        <div className="flex items-center justify-between border-b border-slate-800/80 pb-2">
          <div className="flex items-center gap-2">
            <span className="text-xs uppercase font-bold tracking-wider text-indigo-400">Profile Analytics Filters</span>
            {activeFiltersCount > 0 && (
              <span className="bg-indigo-900/60 text-indigo-300 text-[10px] px-2 py-0.5 rounded-full font-semibold border border-indigo-700/60">
                {activeFiltersCount} active
              </span>
            )}
          </div>
          {(activeFiltersCount > 0 || startYear || endYear) && (
            <button
              onClick={handleResetFilters}
              className="text-[11px] text-slate-400 hover:text-rose-400 transition-colors"
            >
              Reset Filters
            </button>
          )}
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-3 text-xs">
          {/* Format */}
          <div>
            <label className="block text-[11px] font-medium text-slate-400 mb-1">Format</label>
            <select
              value={format}
              onChange={e => { setFormat(e.target.value); setPhase(''); }}
              className="w-full bg-slate-800 border border-slate-700 rounded-md px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-medium"
            >
              {formatsList.map(f => (
                <option key={f.id} value={f.id}>{f.label}</option>
              ))}
            </select>
          </div>

          {/* From Year */}
          <div>
            <label className="block text-[11px] font-medium text-slate-400 mb-1">From Year</label>
            <select
              value={startYear}
              onChange={e => setStartYear(e.target.value)}
              disabled={metadataLoading}
              className="w-full bg-slate-800 border border-slate-700 rounded-md px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="">{metadataLoading ? 'Loading years…' : `Any (${metadata?.min_year || '—'})`}</option>
              {metadata?.years?.map(y => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
          </div>

          {/* To Year */}
          <div>
            <label className="block text-[11px] font-medium text-slate-400 mb-1">To Year</label>
            <select
              value={endYear}
              onChange={e => setEndYear(e.target.value)}
              disabled={metadataLoading}
              className="w-full bg-slate-800 border border-slate-700 rounded-md px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="">{metadataLoading ? 'Loading years…' : `Any (${metadata?.max_year || '—'})`}</option>
              {metadata?.years?.map(y => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
          </div>

          {/* Opponent */}
          <div>
            <label className="block text-[11px] font-medium text-slate-400 mb-1">Opponent</label>
            <select
              value={vsTeamId}
              onChange={e => setVsTeamId(e.target.value)}
              disabled={metadataLoading}
              className="w-full bg-slate-800 border border-slate-700 rounded-md px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="">All Opponents</option>
              {metadata?.teams?.map(t => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </div>

          {/* Venue */}
          <div>
            <label className="block text-[11px] font-medium text-slate-400 mb-1">Venue</label>
            <select
              value={venueId}
              onChange={e => setVenueId(e.target.value)}
              disabled={metadataLoading}
              className="w-full bg-slate-800 border border-slate-700 rounded-md px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="">All Venues</option>
              {metadata?.venues?.map(v => (
                <option key={v.id} value={v.id}>{v.name}</option>
              ))}
            </select>
          </div>

          {/* Bowling Style (Pace vs Spin) */}
          <div>
            <label className="block text-[11px] font-medium text-slate-400 mb-1">Bowler Style</label>
            <select
              value={bowlingStyle}
              onChange={e => setBowlingStyle(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-md px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="">All Styles</option>
              <option value="pace">vs Pace Bowlers</option>
              <option value="spin">vs Spin Bowlers</option>
            </select>
          </div>

          {/* Phase */}
          <div>
            <label className="block text-[11px] font-medium text-slate-400 mb-1">Match Phase</label>
            <select
              value={phase}
              onChange={e => setPhase(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-md px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="">All Overs</option>
              {phaseLabels ? <>
                <option value="powerplay">{phaseLabels.powerplay}</option>
                <option value="middle">{phaseLabels.middle}</option>
                <option value="death">{phaseLabels.death}</option>
              </> : <option value="" disabled>Select a limited-overs format</option>}
            </select>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
          <div className="text-[11px] text-slate-500">
            {appliedStartYear || appliedEndYear ? `Showing ${appliedStartYear || 'all available years'}–${appliedEndYear || 'all available years'} · ${format || 'all formats'}` : `Showing all available years · ${format || 'all formats'}`}
            {(yearFilterError || (invalidYearRange && 'From Year must be earlier than or equal to To Year.') || metadataError) && <span className="block text-rose-400 mt-1">{yearFilterError || (invalidYearRange ? 'From Year must be earlier than or equal to To Year.' : metadataError)}</span>}
          </div>
          <button onClick={applyYearFilters} disabled={invalidYearRange}
            className="px-3 py-1.5 rounded-md bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white text-xs font-semibold">Apply Year Filters</button>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="flex items-center gap-2 border-b border-slate-800 pb-2 overflow-x-auto text-xs font-medium">
        {[
          { id: 'overview', label: 'Career Overview & Benchmarks' },
          { id: 'splits', label: 'Pace vs Spin & Phase Analytics' },
          { id: 'opponents', label: 'Opponents & Venue Splits' },
          { id: 'trends', label: 'Career Trajectory & Form' },
          { id: 'similar', label: 'ML Similar Profiles' },
        ].map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-3.5 py-2 rounded-lg transition-colors whitespace-nowrap ${
              activeTab === tab.id
                ? 'bg-indigo-600 text-white font-semibold shadow-md'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Loading & Error States */}
      {loading && <LoadingSpinner message="Computing deep delivery-level performance analytics..." />}
      {error && <ErrorState message={error} />}

      {!loading && !error && analytics && (
        <div className="space-y-8">
          {/* TAB 1: OVERVIEW & BENCHMARKS */}
          {activeTab === 'overview' && (
            <div className="space-y-6">
              {/* Tactical Strengths & Weaknesses Cards */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-emerald-950/20 border border-emerald-800/40 rounded-xl p-4">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-emerald-400 mb-2 flex items-center gap-1.5">
                    <span>✓</span> Key Strengths & Tactical Edges
                  </h3>
                  {analytics.primary_role.includes('All-Rounder') ? <div className="grid sm:grid-cols-2 gap-3 text-xs text-slate-300">
                    {[['Batting', analytics.strengths_weaknesses.batting_strengths], ['Bowling', analytics.strengths_weaknesses.bowling_strengths]].map(([label, items]) => <div key={label}>
                      <p className="text-[10px] uppercase tracking-wide text-emerald-300 mb-1">{label}</p>
                      {items.map((s, i) => <p key={i} className="mb-1">• {s}</p>)}
                    </div>)}
                  </div> : <ul className="space-y-1.5 text-xs text-slate-300">
                    {analytics.strengths_weaknesses.strengths.map((s, i) => <li key={i} className="flex items-start gap-2"><span className="text-emerald-400 font-bold">•</span><span>{s}</span></li>)}
                  </ul>}
                </div>

                <div className="bg-rose-950/20 border border-rose-800/40 rounded-xl p-4">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-rose-400 mb-2 flex items-center gap-1.5">
                    <span>⚠</span> Caveats & Matchup Vulnerabilities
                  </h3>
                  {analytics.primary_role.includes('All-Rounder') ? <div className="grid sm:grid-cols-2 gap-3 text-xs text-slate-300">
                    {[['Batting', analytics.strengths_weaknesses.batting_weaknesses], ['Bowling', analytics.strengths_weaknesses.bowling_weaknesses]].map(([label, items]) => <div key={label}>
                      <p className="text-[10px] uppercase tracking-wide text-rose-300 mb-1">{label}</p>
                      {items.map((w, i) => <p key={i} className="mb-1">• {w}</p>)}
                    </div>)}
                  </div> : <ul className="space-y-1.5 text-xs text-slate-300">
                    {analytics.strengths_weaknesses.weaknesses.map((w, i) => <li key={i} className="flex items-start gap-2"><span className="text-rose-400 font-bold">•</span><span>{w}</span></li>)}
                  </ul>}
                </div>
              </div>

              {/* Complete Batting Benchmarks */}
              <section className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Complete Batting Benchmarks</h3>
                  <span className="text-[11px] text-slate-500 font-mono">
                    {analytics.batting.sample_note}
                  </span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
                  <StatCard label="Runs" value={analytics.batting.runs.toLocaleString()} highlight />
                  <StatCard label="Batting Avg" value={analytics.batting.average != null ? analytics.batting.average.toFixed(2) : '—'} highlight />
                  <StatCard label="Strike Rate" value={analytics.batting.strike_rate != null ? analytics.batting.strike_rate.toFixed(1) : '—'} highlight />
                  <StatCard label="Highest Score" value={analytics.batting.highest_score} />
                  <StatCard label="Innings / NO" value={`${analytics.batting.innings} / ${analytics.batting.not_outs}`} />
                  <StatCard label="Balls Faced" value={analytics.batting.balls_faced.toLocaleString()} />
                  <StatCard label="Boundaries (4s/6s)" value={`${analytics.batting.fours} / ${analytics.batting.sixes}`} />
                  <StatCard label="Boundary %" value={analytics.batting.boundary_percentage != null ? `${analytics.batting.boundary_percentage.toFixed(1)}%` : '—'} />
                  <StatCard label="Dot Ball %" value={analytics.batting.dot_ball_percentage != null ? `${analytics.batting.dot_ball_percentage.toFixed(1)}%` : '—'} />
                  <StatCard label="Dismissals" value={analytics.batting.dismissals} />
                </div>
              </section>

              {/* Complete Bowling Benchmarks (if bowled) */}
              {analytics.bowling.legal_balls > 0 && (
                <section className="space-y-3 pt-4 border-t border-slate-800">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Complete Bowling Benchmarks</h3>
                    <span className="text-[11px] text-slate-500 font-mono">
                      {analytics.bowling.sample_note}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
                    <StatCard label="Wickets" value={analytics.bowling.wickets} highlight />
                    <StatCard label="Economy Rate" value={analytics.bowling.economy_rate != null ? analytics.bowling.economy_rate.toFixed(2) : '—'} highlight />
                    <StatCard label="Bowling Avg" value={analytics.bowling.bowling_average != null ? analytics.bowling.bowling_average.toFixed(2) : '—'} />
                    <StatCard label="Bowling SR" value={analytics.bowling.bowling_strike_rate != null ? analytics.bowling.bowling_strike_rate.toFixed(1) : '—'} />
                    <StatCard label="Overs Bowled" value={analytics.bowling.overs_display} />
                    <StatCard label="Runs Conceded" value={analytics.bowling.runs_conceded.toLocaleString()} />
                    <StatCard label="Dot Ball %" value={analytics.bowling.dot_ball_percentage != null ? `${analytics.bowling.dot_ball_percentage.toFixed(1)}%` : '—'} />
                    <StatCard label="Innings Bowled" value={analytics.bowling.innings_bowled} />
                  </div>
                </section>
              )}

              {/* Format-by-Format Breakdown Table */}
              <section className="space-y-3 pt-4 border-t border-slate-800">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Multi-Format Comparison (Test, ODI, T20, T20I)</h3>
                <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/60 shadow">
                  <table className="w-full text-left text-xs text-slate-300">
                    <thead className="bg-slate-800 text-[11px] uppercase tracking-wider text-slate-400">
                      <tr>
                        <th className="py-2.5 px-4 font-semibold">Format</th>
                        <th className="py-2.5 px-3 text-right">Matches</th>
                        <th className="py-2.5 px-3 text-right">Innings</th>
                        <th className="py-2.5 px-3 text-right">Runs</th>
                        <th className="py-2.5 px-3 text-right">Bat Avg</th>
                        <th className="py-2.5 px-3 text-right">Strike Rate</th>
                        <th className="py-2.5 px-3 text-right">Overs</th>
                        <th className="py-2.5 px-3 text-right">Wickets</th>
                        <th className="py-2.5 px-3 text-right">Economy</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800 font-mono text-[12px]">
                      {analytics.format_breakdown.map(f => (
                        <tr key={f.format} className="hover:bg-slate-800/40">
                          <td className="py-2 px-4 font-sans font-semibold text-white">
                            <span className={`inline-block px-2 py-0.5 rounded text-[11px] font-semibold ${
                              f.format === 'T20I' ? 'bg-indigo-950 text-indigo-300 border border-indigo-800' :
                              f.format === 'T20' ? 'bg-cyan-950 text-cyan-300 border border-cyan-800' :
                              f.format === 'ODI' ? 'bg-blue-950 text-blue-300 border border-blue-800' :
                              'bg-amber-950 text-amber-300 border border-amber-800'
                            }`}>
                              {f.format}
                            </span>
                          </td>
                          <td className="py-2 px-3 text-right text-slate-400">{f.matches}</td>
                          <td className="py-2 px-3 text-right text-slate-400">{f.innings_batted}</td>
                          <td className="py-2 px-3 text-right font-bold text-white">{f.runs > 0 ? f.runs.toLocaleString() : '—'}</td>
                          <td className="py-2 px-3 text-right font-medium text-indigo-300">{f.batting_average != null ? f.batting_average.toFixed(2) : '—'}</td>
                          <td className="py-2 px-3 text-right font-medium text-emerald-400">{f.batting_strike_rate != null ? f.batting_strike_rate.toFixed(1) : '—'}</td>
                          <td className="py-2 px-3 text-right text-slate-400">{f.overs_bowled !== '0.0' ? f.overs_bowled : '—'}</td>
                          <td className="py-2 px-3 text-right font-bold text-amber-300">{f.wickets > 0 ? f.wickets : '—'}</td>
                          <td className="py-2 px-3 text-right text-slate-300">{f.economy_rate != null ? f.economy_rate.toFixed(2) : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                  <BarChart title="Runs by format" subtitle="Actual runs in each separately stored format; T20 and T20I remain distinct." data={analytics.format_breakdown.filter(f => Number(f.runs) > 0).map(f => ({ label: `${f.format} · ${f.matches} matches`, value: f.runs }))} formatter={value => Math.round(value).toLocaleString()} color="#818cf8" />
                  <BarChart title="Bowler-credit wickets by format" subtitle="Only formats with recorded bowler-credit wickets are shown." data={analytics.format_breakdown.filter(f => Number(f.wickets) > 0).map(f => ({ label: `${f.format} · ${f.innings_bowled} inns`, value: f.wickets }))} formatter={value => `${Math.round(value)} wickets`} color="#fbbf24" />
                  <BarChart title="Batting strike rate by format" subtitle="Format-specific strike rate; formats without faced-ball data are omitted." data={analytics.format_breakdown.filter(f => f.batting_strike_rate != null).map(f => ({ label: `${f.format} · ${f.matches} matches`, value: f.batting_strike_rate }))} formatter={value => Number(value).toFixed(1)} color="#34d399" />
                  <BarChart title="Bowling economy by format" subtitle="Runs conceded per six legal deliveries, calculated separately for each format." data={analytics.format_breakdown.filter(f => f.economy_rate != null).map(f => ({ label: `${f.format} · ${f.overs_bowled} overs`, value: f.economy_rate }))} formatter={value => Number(value).toFixed(2)} color="#22d3ee" />
                </div>
              </section>
            </div>
          )}

          {/* TAB 2: PACE VS SPIN & PHASES */}
          {activeTab === 'splits' && (
            <div className="space-y-6">
              {/* Pace vs Spin Section */}
              <section className="space-y-3">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Batting Splits: Pace versus Spin</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {analytics.pace_spin.map(ps => (
                    <div
                      key={ps.style}
                      className={`p-4 rounded-xl border ${
                        ps.style === 'pace'
                          ? 'bg-cyan-950/20 border-cyan-800/40'
                          : 'bg-indigo-950/20 border-indigo-800/40'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-3">
                        <span className="font-bold text-sm uppercase tracking-wide text-white">
                          vs {ps.style} Bowling
                        </span>
                        <span className={`text-xs px-2 py-0.5 rounded font-semibold ${
                          ps.style === 'pace' ? 'bg-cyan-900/40 text-cyan-300' : 'bg-indigo-900/40 text-indigo-300'
                        }`}>
                          {ps.balls} balls faced
                        </span>
                      </div>

                      <div className="grid grid-cols-3 gap-2 mb-3">
                        <div className="bg-slate-900/80 p-2.5 rounded-lg border border-slate-800 text-center">
                          <span className="block text-[10px] text-slate-500 uppercase">Runs</span>
                          <span className="font-bold text-base text-white">{ps.runs.toLocaleString()}</span>
                        </div>
                        <div className="bg-slate-900/80 p-2.5 rounded-lg border border-slate-800 text-center">
                          <span className="block text-[10px] text-slate-500 uppercase">Strike Rate</span>
                          <span className="font-bold text-base text-emerald-400">
                            {ps.strike_rate != null ? ps.strike_rate.toFixed(1) : '—'}
                          </span>
                        </div>
                        <div className="bg-slate-900/80 p-2.5 rounded-lg border border-slate-800 text-center">
                          <span className="block text-[10px] text-slate-500 uppercase">Average</span>
                          <span className="font-bold text-base text-indigo-300">
                            {ps.average != null ? ps.average.toFixed(2) : '—'}
                          </span>
                        </div>
                      </div>

                      <div className="grid grid-cols-3 gap-2 text-[11px] text-slate-400 pt-2 border-t border-slate-800/60">
                        <div>4s / 6s: <strong className="text-white">{ps.fours} / {ps.sixes}</strong></div>
                        <div>Bound %: <strong className="text-white">{ps.boundary_percentage != null ? `${ps.boundary_percentage.toFixed(1)}%` : '—'}</strong></div>
                        <div>Dot %: <strong className="text-white">{ps.dot_ball_percentage != null ? `${ps.dot_ball_percentage.toFixed(1)}%` : '—'}</strong></div>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                  <BarChart title="Batting strike rate by bowling style" subtitle="Delivery-classified pace and spin only; missing style data stays unavailable." data={analytics.pace_spin.filter(row=>row.strike_rate!=null).map(row=>({label:`${row.style} · n=${row.balls} balls`,value:row.strike_rate}))} formatter={value=>Number(value).toFixed(1)} color="#22d3ee" />
                  <BarChart title="Batting average by bowling style" subtitle="Dismissal-based average against pace and spin; not-outs are not treated as dismissals." data={analytics.pace_spin.filter(row=>row.average!=null).map(row=>({label:`${row.style} · ${row.dismissals} dismissals`,value:row.average}))} formatter={value=>Number(value).toFixed(2)} color="#818cf8" />
                  <BarChart title="Boundary scoring by bowling style" subtitle="Share of faced balls resulting in fours or sixes." data={analytics.pace_spin.filter(row=>row.boundary_percentage!=null).map(row=>({label:`${row.style} · ${row.balls} balls`,value:row.boundary_percentage}))} formatter={value=>`${Number(value).toFixed(1)}%`} color="#34d399" />
                  <BarChart title="Dot-ball pressure by bowling style" subtitle="Share of faced balls with no batter runs." data={analytics.pace_spin.filter(row=>row.dot_ball_percentage!=null).map(row=>({label:`${row.style} · ${row.balls} balls`,value:row.dot_ball_percentage}))} formatter={value=>`${Number(value).toFixed(1)}%`} color="#fb7185" />
                  {analytics.bowling_pace_spin?.length > 0 && <BarChart title="Bowler-credit wickets by bowling style" subtitle="Style labels are based on CPI's available bowling classification." data={analytics.bowling_pace_spin.map(row=>({label:`${row.style} · ${row.overs} overs`,value:row.wickets}))} formatter={value=>`${Math.round(value)} wickets`} color="#fbbf24" />}
                  {analytics.bowling_pace_spin?.length > 0 && <BarChart title="Bowling economy by style" subtitle="Bowling runs conceded per six legal deliveries; style samples shown in overs." data={analytics.bowling_pace_spin.filter(row=>row.economy!=null).map(row=>({label:`${row.style} · ${row.overs} overs`,value:row.economy}))} formatter={value=>Number(value).toFixed(2)} color="#c084fc" />}
                  {analytics.bowling_pace_spin?.length > 0 && <BarChart title="Bowling strike rate by style" subtitle="Legal deliveries per bowler-credit wicket." data={analytics.bowling_pace_spin.filter(row=>row.bowling_strike_rate!=null).map(row=>({label:`${row.style} · ${row.wickets} wickets`,value:row.bowling_strike_rate}))} formatter={value=>Number(value).toFixed(1)} color="#fbbf24" />}
                </div>
              </section>

              {/* Phase-wise Breakdown */}
              <section className="space-y-3 pt-4 border-t border-slate-800">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Phase-by-Phase Batting Breakdown</h3>
                {phaseLabels && <BarChart title="Runs by innings phase" subtitle="Format-specific phase rules; delivery totals come from the filtered player analytics." data={analytics.phases.map(p => ({ label: phaseLabels[p.phase] || p.phase, value: p.runs }))} formatter={value => `${Math.round(value).toLocaleString()} runs`} color="#34d399" />}
                {phaseLabels && <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                  <BarChart title="Phase batting strike rate" subtitle="Runs per 100 faced balls; unavailable phases are omitted." data={analytics.phases.filter(p=>p.strike_rate!=null).map(p=>({label:phaseLabels[p.phase]||p.phase,value:p.strike_rate}))} formatter={value=>Number(value).toFixed(1)} color="#22d3ee" />
                  <BarChart title="Phase dots and boundaries" subtitle="Dots and boundary balls as shares of balls faced; separate charts preserve the underlying rates." data={analytics.phases.filter(p=>p.dot_ball_percentage!=null).map(p=>({label:`${phaseLabels[p.phase]||p.phase} · dots`,value:p.dot_ball_percentage,color:'#fb7185'})).concat(analytics.phases.filter(p=>p.boundary_percentage!=null).map(p=>({label:`${phaseLabels[p.phase]||p.phase} · boundaries`,value:p.boundary_percentage,color:'#34d399'})))} formatter={value=>`${Number(value).toFixed(1)}%`} color="#818cf8" />
                </div>}
                {!phaseLabels ? <p className="text-xs text-slate-500">Select T20, T20I, ODI or ODM to view comparable phase breakdowns. Test and multi-day cricket use innings progression instead of powerplay phases.</p> : <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/60 shadow">
                  <table className="w-full text-left text-xs text-slate-300">
                    <thead className="bg-slate-800 text-[11px] uppercase tracking-wider text-slate-400">
                      <tr>
                        <th className="py-2.5 px-4 font-semibold">Match Phase</th>
                        <th className="py-2.5 px-3 text-right">Runs</th>
                        <th className="py-2.5 px-3 text-right">Balls</th>
                        <th className="py-2.5 px-3 text-right">Strike Rate</th>
                        <th className="py-2.5 px-3 text-right">Average</th>
                        <th className="py-2.5 px-3 text-right">4s / 6s</th>
                        <th className="py-2.5 px-3 text-right">Dot Ball %</th>
                        <th className="py-2.5 px-3 text-right">Boundary %</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800 font-mono text-[12px]">
                      {analytics.phases.map(p => (
                        <tr key={p.phase} className="hover:bg-slate-800/40">
                          <td className="py-2.5 px-4 font-sans font-semibold text-white capitalize">
                            {phaseLabels?.[p.phase] || p.phase.replace('_', ' ')}
                          </td>
                          <td className="py-2.5 px-3 text-right font-bold text-white">{p.runs.toLocaleString()}</td>
                          <td className="py-2.5 px-3 text-right text-slate-400">{p.balls.toLocaleString()}</td>
                          <td className="py-2.5 px-3 text-right font-bold text-emerald-400">
                            {p.strike_rate != null ? p.strike_rate.toFixed(1) : '—'}
                          </td>
                          <td className="py-2.5 px-3 text-right font-medium text-indigo-300">
                            {p.average != null ? p.average.toFixed(2) : '—'}
                          </td>
                          <td className="py-2.5 px-3 text-right text-slate-400">{p.fours} / {p.sixes}</td>
                          <td className="py-2.5 px-3 text-right text-slate-300">
                            {p.dot_ball_percentage != null ? `${p.dot_ball_percentage.toFixed(1)}%` : '—'}
                          </td>
                          <td className="py-2.5 px-3 text-right text-slate-300">
                            {p.boundary_percentage != null ? `${p.boundary_percentage.toFixed(1)}%` : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>}
              </section>
              <section className="space-y-3 pt-4 border-t border-slate-800">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Bowling Phases & Economy</h3>
                {!analytics.bowling_phases?.length ? <p className="text-xs text-slate-500">No phase or innings-progression bowling sample is available for this format and range.</p> : <>
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                    <BarChart title="Bowler-credit wickets by phase" subtitle="Super overs and non-bowler dismissals are excluded by the analytics API." data={analytics.bowling_phases.map(p => ({ label: p.phase.replaceAll('_', ' '), value: p.wickets }))} formatter={value => `${Math.round(value)} wickets`} color="#fbbf24" />
                    <BarChart title="Phase economy comparison" subtitle="Economy per six legal deliveries; phase labels follow the selected format." data={analytics.bowling_phases.filter(p => p.economy != null).map(p => ({ label: p.phase.replaceAll('_', ' '), value: p.economy }))} formatter={value => Number(value).toFixed(2)} color="#818cf8" />
                    <BarChart title="Phase bowling strike rate" subtitle="Legal deliveries per bowler-credit wicket." data={analytics.bowling_phases.filter(p => p.bowling_strike_rate != null).map(p => ({ label: p.phase.replaceAll('_', ' '), value: p.bowling_strike_rate }))} formatter={value => Number(value).toFixed(1)} color="#22d3ee" />
                    <BarChart title="Bowling dots and boundaries conceded" subtitle="Delivery percentages by phase, using only phase samples with valid denominators." data={analytics.bowling_phases.filter(p=>p.dot_ball_percentage!=null).map(p=>({label:`${p.phase.replaceAll('_',' ')} · dots`,value:p.dot_ball_percentage,color:'#34d399'})).concat(analytics.bowling_phases.filter(p=>p.boundary_percentage!=null).map(p=>({label:`${p.phase.replaceAll('_',' ')} · boundaries`,value:p.boundary_percentage,color:'#fb7185'})))} formatter={value=>`${Number(value).toFixed(1)}%`} color="#818cf8" />
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    {analytics.bowling_phases.map(p => {
                      const maxEconomy = Math.max(1, ...analytics.bowling_phases.map(x => x.economy || 0));
                      return <div key={p.phase} className="bg-slate-900/70 border border-slate-800 rounded-lg p-3 space-y-2">
                        <div className="flex justify-between text-xs"><strong className="text-white capitalize">{p.phase.replaceAll('_', ' ')}</strong><span className="text-slate-400">{p.overs} ov</span></div>
                        <div className="h-1.5 bg-slate-800 rounded"><div className="h-1.5 bg-indigo-500 rounded" style={{ width: `${Math.min(100, (p.economy || 0) / maxEconomy * 100)}%` }} /></div>
                        <div className="grid grid-cols-2 gap-y-1 text-[11px] text-slate-400">
                          <span>Wickets <b className="text-white">{p.wickets}</b></span><span>Runs <b className="text-white">{p.runs_conceded}</b></span>
                          <span>Economy <b className="text-indigo-300">{p.economy == null ? '—' : p.economy.toFixed(2)}</b></span><span>Average <b className="text-white">{p.bowling_average == null ? '—' : p.bowling_average.toFixed(1)}</b></span>
                          <span>Strike rate <b className="text-white">{p.bowling_strike_rate == null ? '—' : p.bowling_strike_rate.toFixed(1)}</b></span><span>Dots <b className="text-white">{p.dot_ball_percentage == null ? '—' : `${p.dot_ball_percentage.toFixed(1)}%`}</b></span>
                          <span>Boundaries conceded <b className="text-white">{p.boundary_percentage == null ? '—' : `${p.boundary_percentage.toFixed(1)}%`}</b></span>
                        </div>
                      </div>;
                    })}
                  </div>
                  {['Test', 'MDM'].includes(format) && <p className="text-[10px] text-slate-500">Test/MDM periods are thirds of each innings by recorded over progression, not powerplay phases.</p>}
                </>}
                {analytics.bowling_pace_spin?.length > 0 && <div className="rounded-lg border border-slate-800 overflow-x-auto">
                  <div className="px-3 py-2 text-[10px] font-bold uppercase tracking-wide text-slate-400">Bowling effectiveness by style</div>
                  <table className="w-full text-xs text-slate-300"><thead className="bg-slate-800 text-[10px] uppercase text-slate-400"><tr><th className="p-2 text-left">Style</th><th className="p-2 text-right">Overs</th><th className="p-2 text-right">Wkts</th><th className="p-2 text-right">Economy</th><th className="p-2 text-right">Average</th><th className="p-2 text-right">SR</th><th className="p-2 text-right">Dots</th><th className="p-2 text-right">Boundaries</th></tr></thead>
                    <tbody>{analytics.bowling_pace_spin.map(s => <tr key={s.style} className="border-t border-slate-800"><td className="p-2 capitalize">{s.style}</td><td className="p-2 text-right">{s.overs}</td><td className="p-2 text-right">{s.wickets}</td><td className="p-2 text-right">{s.economy?.toFixed(2) ?? '—'}</td><td className="p-2 text-right">{s.bowling_average?.toFixed(1) ?? '—'}</td><td className="p-2 text-right">{s.bowling_strike_rate?.toFixed(1) ?? '—'}</td><td className="p-2 text-right">{s.dot_ball_percentage?.toFixed(1) ?? '—'}%</td><td className="p-2 text-right">{s.boundary_percentage?.toFixed(1) ?? '—'}%</td></tr>)}</tbody>
                  </table>
                </div>}
              </section>
            </div>
          )}

          {/* TAB 3: OPPONENTS & VENUES */}
          {activeTab === 'opponents' && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Opponent Teams */}
              <div className="space-y-3">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Performance by Opponent Team</h3>
                <div className="grid grid-cols-1 gap-3">
                  <BarChart title="Runs by opponent" subtitle="Top opponent samples in this filtered format and date range." data={[...analytics.by_opponent].filter(o=>Number(o.runs)>0).sort((a,b)=>b.runs-a.runs).slice(0,8).map(o=>({label:`${o.opponent_name} · ${o.matches} matches`,value:o.runs}))} formatter={value=>Math.round(value).toLocaleString()} color="#818cf8" />
                  <BarChart title="Strike rate by opponent" subtitle="Only opponent splits with recorded faced-ball denominators." data={[...analytics.by_opponent].filter(o=>o.batting_strike_rate!=null).sort((a,b)=>b.batting_strike_rate-a.batting_strike_rate).slice(0,8).map(o=>({label:`${o.opponent_name} · ${o.matches} matches`,value:o.batting_strike_rate}))} formatter={value=>Number(value).toFixed(1)} color="#34d399" />
                </div>
                <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/60 shadow">
                  <table className="w-full text-left text-xs text-slate-300">
                    <thead className="bg-slate-800 text-[11px] uppercase tracking-wider text-slate-400">
                      <tr>
                        <th className="py-2.5 px-3 font-semibold">Opponent</th>
                        <th className="py-2.5 px-2 text-right">Mat</th>
                        <th className="py-2.5 px-2 text-right">Runs</th>
                        <th className="py-2.5 px-2 text-right">Balls</th>
                        <th className="py-2.5 px-2 text-right">SR</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800 font-mono text-[11px]">
                      {analytics.by_opponent.map(o => (
                        <tr key={o.opponent_id} className="hover:bg-slate-800/40">
                          <td className="py-2 px-3 font-sans font-medium text-slate-200">{o.opponent_name}</td>
                          <td className="py-2 px-2 text-right text-slate-400">{o.matches}</td>
                          <td className="py-2 px-2 text-right font-bold text-white">{o.runs.toLocaleString()}</td>
                          <td className="py-2 px-2 text-right text-slate-400">{o.balls_faced}</td>
                          <td className="py-2 px-2 text-right font-medium text-emerald-400">
                            {o.batting_strike_rate != null ? o.batting_strike_rate.toFixed(1) : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Top Venues */}
              <div className="space-y-3">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Performance by Venue</h3>
                <div className="grid grid-cols-1 gap-3">
                  <BarChart title="Runs by venue" subtitle="Top venue totals in the selected format and date range." data={[...analytics.by_venue].filter(v=>Number(v.runs)>0).sort((a,b)=>b.runs-a.runs).slice(0,8).map(v=>({label:`${v.venue_name} · ${v.matches} matches`,value:v.runs}))} formatter={value=>Math.round(value).toLocaleString()} color="#c084fc" />
                  <BarChart title="Strike rate by venue" subtitle="Venue splits with observed balls faced only." data={[...analytics.by_venue].filter(v=>v.batting_strike_rate!=null).sort((a,b)=>b.batting_strike_rate-a.batting_strike_rate).slice(0,8).map(v=>({label:`${v.venue_name} · ${v.matches} matches`,value:v.batting_strike_rate}))} formatter={value=>Number(value).toFixed(1)} color="#22d3ee" />
                </div>
                <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/60 shadow">
                  <table className="w-full text-left text-xs text-slate-300">
                    <thead className="bg-slate-800 text-[11px] uppercase tracking-wider text-slate-400">
                      <tr>
                        <th className="py-2.5 px-3 font-semibold">Venue</th>
                        <th className="py-2.5 px-2 text-right">Mat</th>
                        <th className="py-2.5 px-2 text-right">Runs</th>
                        <th className="py-2.5 px-2 text-right">Balls</th>
                        <th className="py-2.5 px-2 text-right">SR</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800 font-mono text-[11px]">
                      {analytics.by_venue.map(v => (
                        <tr key={v.venue_id} className="hover:bg-slate-800/40">
                          <td className="py-2 px-3 font-sans font-medium text-slate-200">
                            {v.venue_name} {v.city ? <span className="text-slate-500 text-[10px]">({v.city})</span> : ''}
                          </td>
                          <td className="py-2 px-2 text-right text-slate-400">{v.matches}</td>
                          <td className="py-2 px-2 text-right font-bold text-white">{v.runs.toLocaleString()}</td>
                          <td className="py-2 px-2 text-right text-slate-400">{v.balls_faced}</td>
                          <td className="py-2 px-2 text-right font-medium text-emerald-400">
                            {v.batting_strike_rate != null ? v.batting_strike_rate.toFixed(1) : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* TAB 4: CAREER TRENDS & FORM */}
          {activeTab === 'trends' && (
            <div className="space-y-6">
              {/* Year Trends */}
              <section className="space-y-3">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Year-by-Year Performance Trajectory</h3>
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                  <LineChart title="Runs by year" subtitle="Runs from the selected format and applied date filters." data={analytics.year_trends.map(y => ({ label: y.year, value: y.runs }))} formatter={value => Math.round(value).toLocaleString()} color="#818cf8" />
                  <LineChart title="Batting strike rate by year" subtitle="Years without faced-ball data are omitted rather than treated as zero." data={analytics.year_trends.filter(y => y.batting_strike_rate != null).map(y => ({ label: y.year, value: y.batting_strike_rate }))} formatter={value => Number(value).toFixed(1)} color="#34d399" />
                  <LineChart title="Matches played by year" subtitle="Filtered player match appearances by year; an appearance is counted once per match." data={analytics.year_trends.filter(y=>Number(y.matches)>0).map(y=>({label:y.year,value:y.matches}))} formatter={value=>Math.round(value).toLocaleString()} color="#22d3ee" />
                </div>
                <LineChart title="Runs in recent matches" subtitle="Latest ten batting appearances, shown oldest to newest; these are match-level totals from the filtered analytics API." data={[...(analytics.recent_matches || [])].reverse().map(m=>({label:(m.match_date || '').slice(0,10),value:m.runs}))} formatter={value=>Math.round(value).toLocaleString()} color="#c084fc" />
                <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/60 shadow">
                  <table className="w-full text-left text-xs text-slate-300">
                    <thead className="bg-slate-800 text-[11px] uppercase tracking-wider text-slate-400">
                      <tr>
                        <th className="py-2.5 px-4 font-semibold">Year</th>
                        <th className="py-2.5 px-3 text-right">Matches</th>
                        <th className="py-2.5 px-3 text-right">Runs</th>
                        <th className="py-2.5 px-3 text-right">Balls Faced</th>
                        <th className="py-2.5 px-3 text-right">Strike Rate</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800 font-mono text-[12px]">
                      {analytics.year_trends.map(y => (
                        <tr key={y.year} className="hover:bg-slate-800/40">
                          <td className="py-2 px-4 font-sans font-bold text-indigo-300">{y.year}</td>
                          <td className="py-2 px-3 text-right text-slate-400">{y.matches}</td>
                          <td className="py-2 px-3 text-right font-bold text-white">{y.runs.toLocaleString()}</td>
                          <td className="py-2 px-3 text-right text-slate-400">{y.balls_faced}</td>
                          <td className="py-2 px-3 text-right font-medium text-emerald-400">
                            {y.batting_strike_rate != null ? y.batting_strike_rate.toFixed(1) : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              {/* Recent Matches */}
              <section className="space-y-3 pt-4 border-t border-slate-800">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Recent Match Logs (Last 10 Matches)</h3>
                <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/60 shadow">
                  <table className="w-full text-left text-xs text-slate-300">
                    <thead className="bg-slate-800 text-[11px] uppercase tracking-wider text-slate-400">
                      <tr>
                        <th className="py-2.5 px-4 font-semibold">Date</th>
                        <th className="py-2.5 px-2">Format</th>
                        <th className="py-2.5 px-3">Opponent</th>
                        <th className="py-2.5 px-3">Venue</th>
                        <th className="py-2.5 px-3 text-right">Runs (Balls)</th>
                        <th className="py-2.5 px-3 text-right">Strike Rate</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800 font-mono text-[11px]">
                      {analytics.recent_matches.map(m => (
                        <tr key={m.match_id} className="hover:bg-slate-800/40">
                          <td className="py-2 px-4 text-slate-400">{m.match_date || '—'}</td>
                          <td className="py-2 px-2 font-sans font-medium text-indigo-300">{m.format}</td>
                          <td className="py-2 px-3 font-sans font-medium text-slate-200">{m.opponent_name}</td>
                          <td className="py-2 px-3 font-sans text-slate-400 truncate max-w-xs">{m.venue_name}</td>
                          <td className="py-2 px-3 text-right font-bold text-white">
                            {m.runs} <span className="font-normal text-slate-500">({m.balls_faced})</span>
                          </td>
                          <td className="py-2 px-3 text-right font-medium text-emerald-400">
                            {m.strike_rate != null ? m.strike_rate.toFixed(1) : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </div>
          )}

          {/* TAB 5: ML SIMILAR PLAYERS */}
          {activeTab === 'similar' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-indigo-400">Role-aware player similarity</h3>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {similarMode === 'bowler' ? 'Bowling-only profiles, compared within the selected format.' : similarMode === 'all_rounder' ? 'Batting and bowling are scored separately and weighted equally.' : 'Batting profiles, compared within the selected format.'}
                  </p>
                </div>
                {activeSimilarityData?.model_version && (
                  <span className="text-[10px] text-slate-500 font-mono">
                    Model: {activeSimilarityData.model_version}
                  </span>
                )}
              </div>

              <div className="flex gap-2">
                {[['batter', 'Similar batters'], ['bowler', 'Similar bowlers'], ['all_rounder', 'Similar all-rounders']].map(([mode, label]) => (
                  <button key={mode} onClick={() => setSimilarMode(mode)}
                    className={`rounded-lg px-3 py-1.5 text-xs font-semibold border ${similarMode === mode ? 'bg-indigo-600/20 text-indigo-300 border-indigo-500/50' : 'text-slate-400 border-slate-700 hover:text-white'}`}>
                    {label}
                  </button>
                ))}
              </div>

              {similarLoading ? (
                <LoadingSpinner message="Calculating nearest neighbor similarity vectors..." />
              ) : activeSimilarityData?.similar_players?.length ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {activeSimilarityData.similar_players.map(sp => (
                    <div key={sp.player_id} className="bg-slate-900 border border-slate-800 p-4 rounded-xl shadow space-y-3">
                      <div className="flex items-center justify-between">
                        <Link
                          to={`/players/${sp.player_id}`}
                          className="font-bold text-white hover:text-indigo-400 transition-colors text-sm"
                        >
                          {sp.player_name}
                        </Link>
                        <span className="bg-emerald-950 text-emerald-300 border border-emerald-800/80 px-2 py-0.5 rounded text-[11px] font-bold">
                          {Math.round(sp.similarity_score)}% match
                        </span>
                      </div>

                      <div className="grid grid-cols-2 gap-2 text-xs font-mono bg-slate-800/50 p-2.5 rounded-lg border border-slate-700/50">
                        {similarMode === 'all_rounder' ? <>
                          <div>Batting match: <strong className="text-white">{sp.batting_similarity}%</strong></div>
                          <div>Bowling match: <strong className="text-emerald-400">{sp.bowling_similarity}%</strong></div>
                          <div>Batting sample: <strong className="text-slate-300">{sp.batting_innings} innings</strong></div>
                          <div>Bowling sample: <strong className="text-slate-300">{sp.bowling_innings} innings</strong></div>
                        </> : similarMode === 'bowler' ? <>
                          <div>Wickets: <strong className="text-white">{sp.wickets}</strong></div>
                          <div>Economy: <strong className="text-emerald-400">{sp.economy == null ? '—' : Number(sp.economy).toFixed(2)}</strong></div>
                          <div>Bowling avg: <strong className="text-slate-300">{sp.bowling_average == null ? '—' : Number(sp.bowling_average).toFixed(1)}</strong></div>
                          <div>Dot %: <strong className="text-slate-300">{sp.dot_ball_pct == null ? '—' : `${Number(sp.dot_ball_pct).toFixed(1)}%`}</strong></div>
                          <div className="col-span-2 text-slate-400">Sample: {sp.matches} matches / {sp.innings} innings</div>
                        </> : <>
                          <div>Avg: <strong className="text-white">{sp.batting_average == null ? '—' : Number(sp.batting_average).toFixed(1)}</strong></div>
                          <div>SR: <strong className="text-emerald-400">{sp.strike_rate == null ? '—' : Number(sp.strike_rate).toFixed(1)}</strong></div>
                          <div>Innings: <strong className="text-slate-300">{sp.innings}</strong></div>
                          <div>Bound %: <strong className="text-slate-300">{sp.boundary_pct == null ? '—' : `${Number(sp.boundary_pct).toFixed(1)}%`}</strong></div>
                        </>}
                      </div>

                      {similarMode === 'all_rounder' ? <div className="grid grid-cols-2 gap-3 text-[11px] text-slate-400">
                        <div><p className="text-indigo-300 font-semibold mb-1">Batting</p>{(sp.batting_explanations || []).slice(0, 3).map((e, i) => <p key={i}>• {e}</p>)}</div>
                        <div><p className="text-indigo-300 font-semibold mb-1">Bowling</p>{(sp.bowling_explanations || []).slice(0, 3).map((e, i) => <p key={i}>• {e}</p>)}</div>
                      </div> : (sp.explanations?.length > 0 || sp.differences?.length > 0) && (
                        <div className="text-[11px] text-slate-400 space-y-1 pt-1">
                          {[...(sp.explanations || []).slice(0, 2), ...(sp.differences || []).slice(0, 1)].map((exp, idx) => (
                            <p key={idx} className="flex items-start gap-1.5">
                              <span className="text-indigo-400 font-bold">•</span>
                              <span>{exp}</span>
                            </p>
                          ))}
                        </div>
                      )}

                      <Link
                        to={`/players/${sp.player_id}`}
                        className="block text-center text-xs text-indigo-400 hover:text-indigo-300 font-semibold pt-1 border-t border-slate-800"
                      >
                        Inspect Profile →
                      </Link>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState message="No similar player models found with sufficient sample size." />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
