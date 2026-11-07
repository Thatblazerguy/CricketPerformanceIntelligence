/**
 * Batter vs Bowler Matchup Analysis
 *
 * Full cricket head-to-head analytics:
 * - Player selection with full database search
 * - Comprehensive filters (year range, format, competition, teams, venue, innings, phase, over range)
 * - Summary stats with cricket-correct calculations
 * - Dismissal breakdown (bowler-credited vs non-credited)
 * - Phase-wise analysis (Powerplay / Middle / Death)
 * - Over-by-over analysis
 * - Performance trends (year-wise, innings-wise)
 * - Match-by-match breakdown with pagination
 * - CSV export
 *
 * All statistics are derived from actual delivery-level records in PostgreSQL.
 * Wides are never counted as balls faced. No-balls are not legal deliveries.
 * Super overs are excluded from analysis by default.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  getPlayers, getMatchupFilterMetadata,
  getMatchupSummary, getMatchupDismissals,
  getMatchupByMatch, getMatchupByOver, getMatchupTrends,
} from '../../services/api';
import { useApi } from '../../hooks/useApi';
import {
  LoadingSpinner, ErrorState, EmptyState, StatCard,
  PageHeader, Badge, Table
} from '../../components/ui';

// ─────────────────────────── Alphabet constant ───────────────────────────────
const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');

// ─────────────────────────── Famous matchup presets ──────────────────────────
const FAMOUS_MATCHUPS = [
  { batter: 'V Kohli', bowler: 'JJ Bumrah', label: 'Kohli vs Bumrah' },
  { batter: 'RG Sharma', bowler: 'TA Boult', label: 'Rohit vs Boult' },
  { batter: 'MS Dhoni', bowler: 'SP Narine', label: 'Dhoni vs Narine' },
  { batter: 'DA Warner', bowler: 'R Ashwin', label: 'Warner vs Ashwin' },
  { batter: 'KL Rahul', bowler: 'Rashid Khan', label: 'Rahul vs Rashid' },
  { batter: 'AB de Villiers', bowler: 'SL Malinga', label: 'ABD vs Malinga' },
  { batter: 'SK Raina', bowler: 'DJ Bravo', label: 'Raina vs Bravo' },
];

// ─────────────────────────── Utilities ───────────────────────────────────────
function fmt(val, suffix = '') {
  if (val === null || val === undefined) return '—';
  return `${val}${suffix}`;
}
function fmtPct(val) {
  if (val === null || val === undefined) return '—';
  return `${val}%`;
}

// ─────────────────────────── Player selector ─────────────────────────────────
function PlayerSelector({ label, selectedPlayer, onSelect }) {
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [selectedLetter, setSelectedLetter] = useState('');
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    const h = setTimeout(() => { setDebouncedQuery(query); }, 200);
    return () => clearTimeout(h);
  }, [query]);

  const activeSearch = useMemo(() => selectedLetter || debouncedQuery, [selectedLetter, debouncedQuery]);

  const { data, loading } = useApi(
    () => activeSearch
      ? getPlayers({ name: activeSearch, page_size: 40 })
      : Promise.resolve({ players: [], total: 0 }),
    [activeSearch]
  );

  if (selectedPlayer) {
    return (
      <div className="bg-indigo-950/60 border border-indigo-700/80 rounded-xl p-3 flex justify-between items-center">
        <div>
          <p className="font-bold text-indigo-200">{selectedPlayer.name}</p>
          <p className="text-[11px] text-indigo-400 font-mono mt-0.5">
            {selectedPlayer.source_player_id || selectedPlayer.id.slice(0, 8)}
          </p>
        </div>
        <button
          onClick={() => { onSelect(null); setQuery(''); setSelectedLetter(''); setIsOpen(true); }}
          className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-2.5 py-1 rounded transition-colors"
        >
          Change
        </button>
      </div>
    );
  }

  return (
    <div>
      <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">{label}</label>
      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={e => { setQuery(e.target.value); setSelectedLetter(''); setIsOpen(true); }}
          onFocus={() => setIsOpen(true)}
          placeholder={`Search player name...`}
          className="w-full bg-slate-800/90 border border-slate-700 rounded-lg px-3.5 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-indigo-500 placeholder-slate-500"
        />
        {loading && (
          <div className="absolute right-3.5 top-3 w-4 h-4 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
        )}
      </div>

      {isOpen && (
        <div className="mt-2 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl p-3 z-30 max-h-[380px] flex flex-col">
          {/* Alphabet A-Z drawer */}
          <div className="flex flex-wrap gap-1 mb-2 pb-2 border-b border-slate-800">
            <button
              onClick={() => { setSelectedLetter(''); setQuery(''); }}
              className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                !selectedLetter && !query ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:bg-slate-800'
              }`}
            >All</button>
            {ALPHABET.map(c => (
              <button key={c}
                onClick={() => { setSelectedLetter(c); setQuery(c); }}
                className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${
                  selectedLetter === c ? 'bg-indigo-600 text-white font-bold' : 'text-slate-400 hover:bg-slate-800'
                }`}
              >{c}</button>
            ))}
            <button
              onClick={() => setIsOpen(false)}
              className="ml-auto text-[10px] px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300"
            >Close ✕</button>
          </div>
          <div className="overflow-y-auto flex-1 divide-y divide-slate-800 pr-1">
            {data?.players?.length > 0 ? (
              data.players.map(p => (
                <button key={p.id}
                  onClick={() => { onSelect(p); setQuery(''); setIsOpen(false); }}
                  className="w-full text-left px-3 py-2 text-sm text-slate-200 hover:bg-indigo-900/40 rounded flex justify-between items-center"
                >
                  <span className="font-medium">{p.name}</span>
                  <span className="text-xs text-slate-500 font-mono">{p.source_player_id || ''}</span>
                </button>
              ))
            ) : (
              <p className="text-xs text-slate-500 p-3 italic text-center">
                {activeSearch ? 'No players found.' : 'Start typing or choose a letter.'}
              </p>
            )}
          </div>
          {data?.total > 0 && (
            <p className="text-[10px] text-slate-500 text-center pt-2 border-t border-slate-800 mt-2">
              {data.total.toLocaleString()} players in database
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────── Filter Panel ────────────────────────────────────
function FilterPanel({ filters, onChange, metadata, onReset }) {
  const years = metadata?.years || [];
  const formats = metadata?.formats || [];
  const competitions = metadata?.competitions || [];
  const venues = metadata?.venues || [];

  const set = (key, val) => onChange({ ...filters, [key]: val });

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-5">
      <div className="flex justify-between items-center">
        <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Analysis Filters</h3>
        <button
          onClick={onReset}
          className="text-xs text-indigo-400 hover:text-indigo-300 border border-slate-700 hover:border-indigo-500 px-2.5 py-1 rounded transition-colors"
        >
          Reset Filters
        </button>
      </div>

      {/* Year range */}
      <div>
        <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Year Range</label>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[11px] text-slate-500 mb-0.5 block">From</label>
            <select
              value={filters.start_year || ''}
              onChange={e => set('start_year', e.target.value || null)}
              className="w-full bg-slate-800 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="">Earliest</option>
              {years.map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[11px] text-slate-500 mb-0.5 block">To</label>
            <select
              value={filters.end_year || ''}
              onChange={e => set('end_year', e.target.value || null)}
              className="w-full bg-slate-800 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="">Latest</option>
              {[...years].reverse().map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
        </div>
        {filters.start_year && filters.end_year && parseInt(filters.start_year) > parseInt(filters.end_year) && (
          <p className="text-[11px] text-red-400 mt-1">⚠ Start year must be ≤ end year.</p>
        )}
      </div>

      {/* Format */}
      <div>
        <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Format</label>
        <select
          value={filters.format || ''}
          onChange={e => set('format', e.target.value || null)}
          className="w-full bg-slate-800 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
        >
          <option value="">All Formats</option>
          {formats.map(f => <option key={f} value={f}>{f}</option>)}
        </select>
      </div>

      {/* Competition */}
      <div>
        <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Competition</label>
        <select
          value={filters.competition || ''}
          onChange={e => set('competition', e.target.value || null)}
          className="w-full bg-slate-800 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
        >
          <option value="">All Competitions</option>
          {competitions.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      {/* Innings number */}
      <div>
        <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Innings</label>
        <select
          value={filters.innings_number || ''}
          onChange={e => set('innings_number', e.target.value ? parseInt(e.target.value) : null)}
          className="w-full bg-slate-800 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
        >
          <option value="">All Innings</option>
          <option value="1">1st Innings</option>
          <option value="2">2nd Innings</option>
          <option value="3">3rd Innings (Test)</option>
          <option value="4">4th Innings (Test)</option>
        </select>
      </div>

      {/* Phase filter */}
      <div>
        <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Phase</label>
        <div className="flex gap-1 flex-wrap">
          {[{ val: null, label: 'All' }, { val: 'powerplay', label: 'Powerplay' }, { val: 'middle', label: 'Middle' }, { val: 'death', label: 'Death' }].map(opt => (
            <button
              key={opt.label}
              onClick={() => set('phase', opt.val)}
              className={`text-xs px-2.5 py-1 rounded border transition-colors ${
                filters.phase === opt.val
                  ? 'bg-indigo-600 border-indigo-500 text-white'
                  : 'bg-slate-800 border-slate-700 text-slate-300 hover:border-slate-600'
              }`}
            >{opt.label}</button>
          ))}
        </div>
        <p className="text-[10px] text-slate-500 mt-1">T20: PP=Ov 1–6, Mid=7–15, Death=16–20</p>
      </div>

      {/* Custom over range */}
      <div>
        <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Over Range</label>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[11px] text-slate-500 mb-0.5 block">From over</label>
            <input
              type="number"
              min="1" max="80"
              value={filters.over_start || ''}
              onChange={e => set('over_start', e.target.value ? parseInt(e.target.value) : null)}
              placeholder="1"
              className="w-full bg-slate-800 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
            />
          </div>
          <div>
            <label className="text-[11px] text-slate-500 mb-0.5 block">To over</label>
            <input
              type="number"
              min="1" max="80"
              value={filters.over_end || ''}
              onChange={e => set('over_end', e.target.value ? parseInt(e.target.value) : null)}
              placeholder="20"
              className="w-full bg-slate-800 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
            />
          </div>
        </div>
        <p className="text-[10px] text-slate-500 mt-1">1-indexed. Overrides phase filter if set.</p>
      </div>

      {/* Venue */}
      <div>
        <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Venue</label>
        <select
          value={filters.venue_id || ''}
          onChange={e => set('venue_id', e.target.value || null)}
          className="w-full bg-slate-800 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
        >
          <option value="">All Venues</option>
          {venues.map(v => (
            <option key={v.id} value={v.id}>
              {v.name}{v.city ? `, ${v.city}` : ''}
            </option>
          ))}
        </select>
      </div>

      {/* Season */}
      <div>
        <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Season (exact)</label>
        <input
          type="text"
          value={filters.season || ''}
          onChange={e => set('season', e.target.value || null)}
          placeholder="e.g. 2024, 2024/25"
          className="w-full bg-slate-800 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 placeholder-slate-600"
        />
      </div>

      {/* Min balls */}
      <div>
        <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Min Balls (sample gate)</label>
        <input
          type="number"
          min="1"
          value={filters.min_balls || ''}
          onChange={e => set('min_balls', e.target.value ? parseInt(e.target.value) : null)}
          placeholder="e.g. 6"
          className="w-full bg-slate-800 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 placeholder-slate-600"
        />
      </div>

      {/* Unavailable filter notes */}
      <div className="bg-slate-800/40 border border-slate-800 rounded-lg p-3">
        <p className="text-[10px] text-slate-500 leading-relaxed">
          <span className="text-slate-400 font-medium block mb-1">ℹ Notes on filters:</span>
          Pace/spin filter unavailable — bowling style is not reliably recorded in Cricsheet data.
          Team filters (batter&apos;s team, bowler&apos;s team) are supported via competition/season.
          Home/away/neutral venue classification not available in source data.
        </p>
      </div>
    </div>
  );
}

// ─────────────────────────── Active filter summary ───────────────────────────
function ActiveFilters({ filters }) {
  const active = [];
  if (filters.start_year || filters.end_year) {
    const from = filters.start_year || 'earliest';
    const to = filters.end_year || 'latest';
    active.push(`Years: ${from} – ${to}`);
  }
  if (filters.format) active.push(`Format: ${filters.format}`);
  if (filters.competition) active.push(`Competition: ${filters.competition}`);
  if (filters.innings_number) active.push(`Innings: ${filters.innings_number}`);
  if (filters.phase) active.push(`Phase: ${filters.phase}`);
  if (filters.over_start || filters.over_end) active.push(`Overs: ${filters.over_start || 1}–${filters.over_end || '∞'}`);
  if (filters.venue_id) active.push('Specific venue');
  if (filters.season) active.push(`Season: ${filters.season}`);
  if (!active.length) return null;

  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {active.map((f, i) => (
        <span key={i} className="text-[11px] bg-indigo-900/40 text-indigo-300 border border-indigo-800/50 px-2 py-0.5 rounded-full">
          {f}
        </span>
      ))}
    </div>
  );
}

// ─────────────────────────── Summary Stats ───────────────────────────────────
function SummaryPanel({ summary, loading, error }) {
  if (loading) return <LoadingSpinner message="Calculating matchup statistics..." />;
  if (error) return <ErrorState message={error} />;
  if (!summary) return null;

  const noBalls = summary.balls_faced === 0;

  return (
    <div className="space-y-4">
      {summary.sample_warning && (
        <div className="bg-amber-900/20 border border-amber-700 rounded-lg px-4 py-2.5 text-xs text-amber-300 flex items-center gap-2">
          <span>⚠</span> {summary.sample_warning}
        </div>
      )}

      <div className="text-xs text-slate-500 flex flex-wrap gap-4 pb-3 border-b border-slate-800">
        <span><strong className="text-slate-300">{summary.matches_count}</strong> matches</span>
        <span><strong className="text-slate-300">{summary.innings_count}</strong> innings</span>
        <span><strong className="text-slate-300">{summary.total_deliveries}</strong> total deliveries analysed</span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        <StatCard label="Runs" value={summary.batter_runs} highlight />
        <StatCard label="Balls Faced" value={summary.balls_faced} />
        <StatCard label="Strike Rate" value={noBalls ? '—' : fmt(summary.strike_rate)} highlight />
        <StatCard label="Dismissals" value={summary.dismissals} />
        <StatCard label="Batting Avg" value={noBalls ? '—' : fmt(summary.batting_average)} highlight />
        <StatCard label="Fours" value={summary.fours} />
        <StatCard label="Sixes" value={summary.sixes} />
        <StatCard label="Boundaries" value={summary.boundaries} />
        <StatCard label="Dot Balls" value={summary.dot_balls} />
        <StatCard label="Dot Ball %" value={fmtPct(summary.dot_ball_pct)} />
        <StatCard label="Boundary %" value={fmtPct(summary.boundary_pct)} />
        <StatCard label="Legal Balls" value={summary.legal_balls} />
      </div>

      {/* Visual representation */}
      {!noBalls && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 mt-2">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Ball Outcome Distribution</p>
          <div className="flex h-4 w-full rounded-full overflow-hidden gap-0.5">
            {/* Sixes */}
            <div
              style={{ width: `${(summary.sixes / summary.balls_faced) * 100}%` }}
              className="bg-indigo-500 h-full"
              title={`Sixes: ${summary.sixes}`}
            />
            {/* Fours */}
            <div
              style={{ width: `${(summary.fours / summary.balls_faced) * 100}%` }}
              className="bg-blue-400 h-full"
              title={`Fours: ${summary.fours}`}
            />
            {/* Other scoring */}
            <div
              style={{ width: `${((summary.batter_runs - summary.fours * 4 - summary.sixes * 6) / summary.balls_faced) * 100}%` }}
              className="bg-slate-500 h-full"
              title="Singles & twos"
            />
            {/* Dot balls */}
            <div
              style={{ width: `${(summary.dot_balls / summary.balls_faced) * 100}%` }}
              className="bg-rose-800 h-full"
              title={`Dot balls: ${summary.dot_balls}`}
            />
          </div>
          <div className="flex flex-wrap gap-4 mt-2 text-[10px] text-slate-400">
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-indigo-500" /> Sixes ({summary.sixes})</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-blue-400" /> Fours ({summary.fours})</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-slate-500" /> Other scoring</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-rose-800" /> Dots ({summary.dot_balls})</span>
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────── Dismissal Panel ─────────────────────────────────
function DismissalPanel({ data, loading, error }) {
  if (loading) return <LoadingSpinner message="Loading dismissal breakdown..." />;
  if (error) return <ErrorState message={error} />;
  if (!data) return null;

  const types = data.by_type || {};
  const typesArr = Object.entries(types).sort((a, b) => b[1] - a[1]);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <StatCard label="Total Dismissals" value={data.total_dismissals} />
        <StatCard label="Bowler Wickets" value={data.bowler_wickets} highlight />
        <StatCard label="Non-Bowler" value={data.not_bowler_credited} />
      </div>

      {typesArr.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-800/60 text-xs text-slate-400 uppercase tracking-wider">
              <tr>
                <th className="px-4 py-2 text-left">Dismissal Type</th>
                <th className="px-4 py-2 text-right">Count</th>
                <th className="px-4 py-2 text-center">Bowler Credit?</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {typesArr.map(([type, count]) => {
                const isBowlerWkt = !['run out', 'obstructing the field', 'retired hurt', 'retired out'].includes(type);
                return (
                  <tr key={type} className="hover:bg-slate-800/40">
                    <td className="px-4 py-2.5 text-slate-200 capitalize">{type}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-slate-300">{count}</td>
                    <td className="px-4 py-2.5 text-center">
                      {isBowlerWkt
                        ? <Badge variant="green">Yes</Badge>
                        : <Badge variant="amber">No</Badge>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {data.total_dismissals === 0 && (
        <EmptyState message="No dismissals recorded in the selected filters." />
      )}
    </div>
  );
}

// ─────────────────────────── Phase Panel ─────────────────────────────────────
function PhasePanel({ summary }) {
  const phases = summary?.phases || [];
  if (!phases.length) return <EmptyState message="Choose one limited-overs format (T20, T20I, ODI or ODM) to compare phase performance. Test and multi-day matches do not use powerplay phases." />;

  const isFiftyOver = ['ODI', 'ODM'].includes(summary?.filters_applied?.format);
  const labels = isFiftyOver
    ? { powerplay: 'Powerplay (Ov 1–10)', middle: 'Middle (Ov 11–40)', death: 'Death (Ov 41–50)' }
    : { powerplay: 'Powerplay (Ov 1–6)', middle: 'Middle (Ov 7–15)', death: 'Death (Ov 16–20)' };

  const phaseMeta = {
    powerplay: { label: labels.powerplay, color: 'bg-emerald-500', text: 'text-emerald-400' },
    middle:    { label: labels.middle, color: 'bg-indigo-500', text: 'text-indigo-400' },
    death:     { label: labels.death, color: 'bg-amber-500', text: 'text-amber-400' },
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {phases.map(ph => {
        const meta = phaseMeta[ph.phase] || { label: ph.phase, color: 'bg-slate-500', text: 'text-slate-300' };
        const sr = ph.balls > 0 ? Math.round((ph.runs / ph.balls) * 100 * 10) / 10 : null;
        const dot_pct = ph.balls > 0 ? Math.round((ph.dot_balls / ph.balls) * 100 * 10) / 10 : null;
        return (
          <div key={ph.phase} className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
            <div className="flex items-center gap-2">
              <span className={`w-2.5 h-2.5 rounded-full ${meta.color}`} />
              <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">{meta.label}</span>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="bg-slate-800/60 p-2 rounded">
                <span className="text-slate-500 block">Runs</span>
                <span className={`font-bold text-lg ${meta.text}`}>{ph.runs}</span>
              </div>
              <div className="bg-slate-800/60 p-2 rounded">
                <span className="text-slate-500 block">Balls Faced</span>
                <span className="font-semibold text-slate-200">{ph.balls}</span>
              </div>
              <div className="bg-slate-800/60 p-2 rounded">
                <span className="text-slate-500 block">Strike Rate</span>
                <span className="font-semibold text-slate-200">{sr ?? '—'}</span>
              </div>
              <div className="bg-slate-800/60 p-2 rounded">
                <span className="text-slate-500 block">Dismissals</span>
                <span className="font-semibold text-slate-200">{ph.dismissals}</span>
              </div>
              <div className="bg-slate-800/60 p-2 rounded">
                <span className="text-slate-500 block">Boundaries</span>
                <span className="font-semibold text-slate-200">{ph.fours + ph.sixes} ({ph.fours}×4, {ph.sixes}×6)</span>
              </div>
              <div className="bg-slate-800/60 p-2 rounded">
                <span className="text-slate-500 block">Dot %</span>
                <span className="font-semibold text-slate-200">{dot_pct !== null ? `${dot_pct}%` : '—'}</span>
              </div>
            </div>
            {/* SR meter */}
            {sr !== null && (
              <div>
                <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                  <div
                    style={{ width: `${Math.min((sr / 220) * 100, 100)}%` }}
                    className={`h-full ${meta.color}`}
                  />
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─────────────────────────── Over-by-over Panel ──────────────────────────────
function OverByOverPanel({ data, loading, error }) {
  if (loading) return <LoadingSpinner message="Loading over analysis..." />;
  if (error) return <ErrorState message={error} />;
  if (!data?.overs?.length) return <EmptyState message="No over-by-over data for selected filters." />;

  const overs = data.overs;
  const maxRuns = Math.max(...overs.map(o => o.runs), 1);

  return (
    <div className="space-y-4">
      {/* Bar chart */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
        <p className="text-xs text-slate-400 mb-3 font-semibold uppercase tracking-wider">Runs per Over</p>
        <div className="flex items-end gap-1 h-32">
          {overs.map(o => (
            <div key={o.over_number} className="flex flex-col items-center flex-1 min-w-0">
              <div className="w-full flex flex-col-reverse" style={{ height: '100px' }}>
                <div
                  style={{ height: `${(o.runs / maxRuns) * 100}%` }}
                  className={`w-full rounded-t transition-all ${
                    o.dismissals > 0 ? 'bg-rose-500' : o.runs >= 10 ? 'bg-indigo-500' : 'bg-slate-600'
                  }`}
                  title={`Over ${o.over_number + 1}: ${o.runs} runs, ${o.dismissals} wkt(s)`}
                />
              </div>
              <span className="text-[9px] text-slate-500 mt-1">{o.over_number + 1}</span>
            </div>
          ))}
        </div>
        <div className="flex gap-3 mt-2 text-[10px] text-slate-400">
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-rose-500" /> Wicket over</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-indigo-500" /> 10+ runs</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-slate-600" /> Normal</span>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border border-slate-800">
        <table className="w-full text-left text-xs text-slate-300">
          <thead className="bg-slate-900 text-[11px] text-slate-400 uppercase tracking-wider border-b border-slate-800">
            <tr>
              <th className="px-3 py-2">Over</th>
              <th className="px-3 py-2 text-right">Balls</th>
              <th className="px-3 py-2 text-right">Runs</th>
              <th className="px-3 py-2 text-right">SR</th>
              <th className="px-3 py-2 text-right">4s</th>
              <th className="px-3 py-2 text-right">6s</th>
              <th className="px-3 py-2 text-right">Dots</th>
              <th className="px-3 py-2 text-right">Wkts</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800 bg-slate-900/50">
            {overs.map(o => (
              <tr key={o.over_number} className={`hover:bg-slate-800/40 ${o.dismissals > 0 ? 'bg-rose-900/10' : ''}`}>
                <td className="px-3 py-2 font-medium">{o.over_number + 1}</td>
                <td className="px-3 py-2 text-right font-mono">{o.balls}</td>
                <td className="px-3 py-2 text-right font-mono font-semibold text-white">{o.runs}</td>
                <td className="px-3 py-2 text-right font-mono text-indigo-300">{fmt(o.strike_rate)}</td>
                <td className="px-3 py-2 text-right font-mono">{o.fours}</td>
                <td className="px-3 py-2 text-right font-mono">{o.sixes}</td>
                <td className="px-3 py-2 text-right font-mono text-slate-400">{o.dot_balls}</td>
                <td className="px-3 py-2 text-right">
                  {o.dismissals > 0 ? <span className="text-rose-400 font-bold">{o.dismissals}</span> : <span className="text-slate-600">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─────────────────────────── Trends Panel ────────────────────────────────────
function TrendsPanel({ data, loading, error }) {
  if (loading) return <LoadingSpinner message="Loading trend data..." />;
  if (error) return <ErrorState message={error} />;
  if (!data?.by_year?.length) return <EmptyState message="No trend data for selected filters." />;

  const byYear = data.by_year;
  const maxRuns = Math.max(...byYear.map(y => y.runs), 1);

  return (
    <div className="space-y-6">
      {/* Year-wise bar chart */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
        <p className="text-xs text-slate-400 mb-3 font-semibold uppercase tracking-wider">Runs per Year</p>
        <div className="flex items-end gap-2 h-32">
          {byYear.map(y => (
            <div key={y.year} className="flex flex-col items-center flex-1 min-w-0">
              <div className="w-full flex flex-col-reverse" style={{ height: '100px' }}>
                <div
                  style={{ height: `${(y.runs / maxRuns) * 100}%` }}
                  className="w-full rounded-t bg-indigo-600 hover:bg-indigo-500 transition-colors"
                  title={`${y.year}: ${y.runs} runs (SR ${y.strike_rate}), ${y.dismissals} dismissals`}
                />
              </div>
              <span className="text-[9px] text-slate-500 mt-1 rotate-45 origin-left">{y.year}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Year-wise table */}
      <div className="overflow-x-auto rounded-lg border border-slate-800">
        <table className="w-full text-left text-xs text-slate-300">
          <thead className="bg-slate-900 text-[11px] text-slate-400 uppercase tracking-wider border-b border-slate-800">
            <tr>
              <th className="px-3 py-2">Year</th>
              <th className="px-3 py-2 text-right">Matches</th>
              <th className="px-3 py-2 text-right">Balls</th>
              <th className="px-3 py-2 text-right">Runs</th>
              <th className="px-3 py-2 text-right">SR</th>
              <th className="px-3 py-2 text-right">Dismissals</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800 bg-slate-900/50">
            {byYear.map(y => (
              <tr key={y.year} className="hover:bg-slate-800/40">
                <td className="px-3 py-2 font-semibold text-white">{y.year}</td>
                <td className="px-3 py-2 text-right font-mono">{y.matches}</td>
                <td className="px-3 py-2 text-right font-mono">{y.balls_faced}</td>
                <td className="px-3 py-2 text-right font-mono font-semibold text-indigo-300">{y.runs}</td>
                <td className="px-3 py-2 text-right font-mono">{fmt(y.strike_rate)}</td>
                <td className="px-3 py-2 text-right font-mono text-rose-400">{y.dismissals || 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Innings breakdown */}
      {data.by_innings?.length > 0 && (
        <div>
          <p className="text-xs text-slate-400 mb-2 font-semibold uppercase tracking-wider">By Innings</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {data.by_innings.map(inn => (
              <div key={inn.innings_number} className="bg-slate-900 border border-slate-800 rounded-lg p-3 text-xs">
                <p className="text-slate-400 mb-1 font-medium">Innings {inn.innings_number}</p>
                <p className="text-white font-semibold">{inn.runs} runs</p>
                <p className="text-slate-400">{inn.balls} balls · SR {fmt(inn.strike_rate)}</p>
                <p className="text-rose-400">{inn.dismissals} dismissals</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────── Match-by-match Panel ────────────────────────────
function MatchByMatchPanel({ batterId, bowlerId, filters }) {
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState('date');
  const [sortDir, setSortDir] = useState('desc');

  // Reset page when filters change
  useEffect(() => { setPage(1); }, [filters, batterId, bowlerId]);

  const params = {
    ...buildFilterParams(filters),
    page,
    page_size: 15,
    sort_by: sortBy,
    sort_dir: sortDir,
  };

  const { data, loading, error } = useApi(
    () => batterId && bowlerId ? getMatchupByMatch(batterId, bowlerId, params) : Promise.resolve(null),
    [batterId, bowlerId, JSON.stringify(params)]
  );

  const toggleSort = (col) => {
    if (sortBy === col) setSortDir(d => d === 'desc' ? 'asc' : 'desc');
    else { setSortBy(col); setSortDir('desc'); }
  };

  const SortHeader = ({ col, label }) => (
    <th
      onClick={() => toggleSort(col)}
      className="px-3 py-2 text-right cursor-pointer hover:text-indigo-300 select-none whitespace-nowrap"
    >
      {label} {sortBy === col ? (sortDir === 'desc' ? '↓' : '↑') : ''}
    </th>
  );

  const exportCSV = () => {
    if (!data?.matches?.length) return;
    const rows = [
      ['Date', 'Competition', 'Season', 'Venue', 'Teams', 'Innings', 'Balls', 'Runs', '4s', '6s', 'Dots', 'SR', 'Dismissed', 'Dismissal Type', 'Overs'],
      ...data.matches.map(m => [
        m.date, `"${m.competition || ''}"`, m.season,
        `"${m.venue || ''}"`, `"${m.team1} vs ${m.team2}"`,
        m.innings_number, m.balls_faced, m.runs, m.fours, m.sixes, m.dot_balls,
        m.strike_rate ?? '',
        m.dismissed ? 'Yes' : 'No',
        m.dismissal_type || '',
        `"${m.over_numbers || ''}"`,
      ])
    ];
    const csv = 'data:text/csv;charset=utf-8,' + rows.map(r => r.join(',')).join('\n');
    const a = document.createElement('a');
    a.href = encodeURI(csv);
    a.download = `matchup_matches.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  if (loading) return <LoadingSpinner message="Loading match records..." />;
  if (error) return <ErrorState message={error} />;
  if (!data) return null;
  if (!data.matches?.length) return <EmptyState message="No matches found for the selected filters." />;

  const totalPages = Math.ceil(data.total / 15);

  return (
    <div className="space-y-3">
      <div className="flex justify-between items-center">
        <p className="text-xs text-slate-400">
          <strong className="text-slate-200">{data.total}</strong> matches · page {page}/{totalPages}
        </p>
        <button
          onClick={exportCSV}
          className="px-3 py-1.5 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded border border-slate-700 flex items-center gap-1.5"
        >
          ⬇ Export CSV
        </button>
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-800">
        <table className="w-full text-left text-xs text-slate-300 whitespace-nowrap">
          <thead className="bg-slate-900 text-[11px] text-slate-400 uppercase tracking-wider border-b border-slate-800">
            <tr>
              <th className="px-3 py-2 cursor-pointer hover:text-indigo-300" onClick={() => toggleSort('date')}>
                Date {sortBy === 'date' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
              </th>
              <th className="px-3 py-2">Competition</th>
              <th className="px-3 py-2">Venue</th>
              <th className="px-3 py-2">Teams</th>
              <th className="px-3 py-2 text-right">Inn</th>
              <SortHeader col="balls" label="Balls" />
              <SortHeader col="runs" label="Runs" />
              <th className="px-3 py-2 text-right">4s</th>
              <th className="px-3 py-2 text-right">6s</th>
              <th className="px-3 py-2 text-right">Dots</th>
              <SortHeader col="strike_rate" label="SR" />
              <th className="px-3 py-2 text-center">Out?</th>
              <th className="px-3 py-2">Kind</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800 bg-slate-900/50">
            {data.matches.map((m, i) => (
              <tr key={i} className={`hover:bg-slate-800/40 ${m.dismissed ? 'bg-rose-950/10' : ''}`}>
                <td className="px-3 py-2 font-mono text-slate-200">{m.date}</td>
                <td className="px-3 py-2 max-w-[160px] truncate text-slate-400">{m.competition || '—'}</td>
                <td className="px-3 py-2 max-w-[160px] truncate text-slate-400">{m.venue || '—'}</td>
                <td className="px-3 py-2 max-w-[180px] truncate">
                  <span className="text-white">{m.batter_team}</span>
                  <span className="text-slate-500"> vs </span>
                  <span className="text-slate-300">{m.bowler_team}</span>
                </td>
                <td className="px-3 py-2 text-right font-mono">{m.innings_number}</td>
                <td className="px-3 py-2 text-right font-mono">{m.balls_faced}</td>
                <td className="px-3 py-2 text-right font-mono font-semibold text-indigo-300">{m.runs}</td>
                <td className="px-3 py-2 text-right font-mono">{m.fours}</td>
                <td className="px-3 py-2 text-right font-mono">{m.sixes}</td>
                <td className="px-3 py-2 text-right font-mono text-slate-500">{m.dot_balls}</td>
                <td className="px-3 py-2 text-right font-mono">{fmt(m.strike_rate)}</td>
                <td className="px-3 py-2 text-center">
                  {m.dismissed
                    ? <span className="text-rose-400 font-bold">W</span>
                    : <span className="text-emerald-500">—</span>}
                </td>
                <td className="px-3 py-2 text-slate-400 capitalize">{m.dismissal_type || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex justify-center gap-1">
        <button
          onClick={() => setPage(p => Math.max(1, p - 1))}
          disabled={page <= 1}
          className="px-3 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded border border-slate-700 disabled:opacity-40"
        >← Prev</button>
        {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
          const pg = page <= 4 ? i + 1 : page - 3 + i;
          if (pg < 1 || pg > totalPages) return null;
          return (
            <button
              key={pg}
              onClick={() => setPage(pg)}
              className={`px-3 py-1 text-xs rounded border transition-colors ${
                pg === page
                  ? 'bg-indigo-600 border-indigo-500 text-white'
                  : 'bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700'
              }`}
            >{pg}</button>
          );
        })}
        <button
          onClick={() => setPage(p => Math.min(totalPages, p + 1))}
          disabled={page >= totalPages}
          className="px-3 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded border border-slate-700 disabled:opacity-40"
        >Next →</button>
      </div>
    </div>
  );
}

// ─────────────────────────── Filter params builder ───────────────────────────
function buildFilterParams(filters) {
  const p = {};
  if (filters.start_year) p.start_year = filters.start_year;
  if (filters.end_year) p.end_year = filters.end_year;
  if (filters.format) p.format = filters.format;
  if (filters.competition) p.competition = filters.competition;
  if (filters.innings_number) p.innings_number = filters.innings_number;
  if (filters.phase) p.phase = filters.phase;
  if (filters.over_start) p.over_start = filters.over_start;
  if (filters.over_end) p.over_end = filters.over_end;
  if (filters.venue_id) p.venue_id = filters.venue_id;
  if (filters.season) p.season = filters.season;
  return p;
}

const DEFAULT_FILTERS = {
  start_year: null, end_year: null, format: null,
  competition: null, season: null, innings_number: null,
  phase: null, over_start: null, over_end: null, venue_id: null,
};

// ─────────────────────────── Main Page ───────────────────────────────────────
export default function Matchups() {
  const [batter, setBatter] = useState(null);
  const [bowler, setBowler] = useState(null);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [activeTab, setActiveTab] = useState('summary');
  const [analysisReady, setAnalysisReady] = useState(false);

  // Metadata for filter dropdowns
  const { data: metadata, loading: metaLoading } = useApi(getMatchupFilterMetadata, []);

  // Build filter params
  const filterParams = useMemo(() => buildFilterParams(filters), [filters]);
  const filterKey = JSON.stringify(filterParams);

  // Trigger analysis
  const analyse = () => {
    if (batter && bowler) setAnalysisReady(true);
  };

  // Reset
  const resetFilters = () => setFilters(DEFAULT_FILTERS);

  // Load a famous preset
  const loadPreset = async (m) => {
    try {
      const r1 = await getPlayers({ name: m.batter, page_size: 1 });
      const r2 = await getPlayers({ name: m.bowler, page_size: 1 });
      if (r1.players.length && r2.players.length) {
        setBatter(r1.players[0]);
        setBowler(r2.players[0]);
        setAnalysisReady(true);
      }
    } catch (e) {
      console.error('Preset load failed', e);
    }
  };

  // Summary fetch
  const { data: summary, loading: summaryLoading, error: summaryError } = useApi(
    () => analysisReady && batter && bowler
      ? getMatchupSummary(batter.id, bowler.id, filterParams)
      : Promise.resolve(null),
    [batter?.id, bowler?.id, analysisReady, filterKey]
  );

  // Dismissal fetch (lazy - only load when tab is active)
  const { data: dismissals, loading: dismLoading, error: dismError } = useApi(
    () => analysisReady && batter && bowler && activeTab === 'dismissals'
      ? getMatchupDismissals(batter.id, bowler.id, filterParams)
      : Promise.resolve(null),
    [batter?.id, bowler?.id, analysisReady, filterKey, activeTab]
  );

  // Over-by-over (lazy)
  const { data: overData, loading: overLoading, error: overError } = useApi(
    () => analysisReady && batter && bowler && activeTab === 'overs'
      ? getMatchupByOver(batter.id, bowler.id, filterParams)
      : Promise.resolve(null),
    [batter?.id, bowler?.id, analysisReady, filterKey, activeTab]
  );

  // Trends (lazy)
  const { data: trendsData, loading: trendsLoading, error: trendsError } = useApi(
    () => analysisReady && batter && bowler && activeTab === 'trends'
      ? getMatchupTrends(batter.id, bowler.id, filterParams)
      : Promise.resolve(null),
    [batter?.id, bowler?.id, analysisReady, filterKey, activeTab]
  );

  const TABS = [
    { id: 'summary', label: 'Summary' },
    { id: 'phases', label: 'Phase Breakdown' },
    { id: 'dismissals', label: 'Dismissals' },
    { id: 'overs', label: 'Over-by-Over' },
    { id: 'trends', label: 'Trends' },
    { id: 'matches', label: 'Match-by-Match' },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Matchup Analysis"
        subtitle="Head-to-head batter vs bowler analytics derived from actual delivery records. All statistics are cricket-rule correct."
      />

      {/* Player Selection + Filters Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left: Player selectors + analyse button */}
        <div className="lg:col-span-8 space-y-4">
          {/* Player Selectors */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mb-4">
              <PlayerSelector label="Batter" selectedPlayer={batter} onSelect={p => { setBatter(p); setAnalysisReady(false); }} />
              <PlayerSelector label="Bowler" selectedPlayer={bowler} onSelect={p => { setBowler(p); setAnalysisReady(false); }} />
            </div>

            {/* Analyse button */}
            <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center justify-between pt-4 border-t border-slate-800">
              <div>
                <ActiveFilters filters={filters} />
                {(!batter || !bowler) && (
                  <p className="text-xs text-slate-500 italic mt-1">Select both a batter and bowler to begin analysis.</p>
                )}
              </div>
              <button
                onClick={analyse}
                disabled={!batter || !bowler}
                className="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700 disabled:text-slate-500 text-white rounded-lg text-sm font-semibold transition-colors shrink-0"
              >
                Analyse Matchup
              </button>
            </div>
          </div>

          {/* Famous Presets */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <p className="text-xs text-slate-400 mb-2 font-medium uppercase tracking-wider">Famous Rivalries</p>
            <div className="flex flex-wrap gap-2">
              {FAMOUS_MATCHUPS.map(m => (
                <button
                  key={m.label}
                  onClick={() => loadPreset(m)}
                  className="text-xs bg-slate-800 hover:bg-indigo-900/40 hover:text-indigo-300 text-slate-300 px-3 py-1.5 rounded-lg border border-slate-700/60 transition-colors"
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Right: Filter Panel */}
        <div className="lg:col-span-4">
          {metaLoading ? (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
              <LoadingSpinner message="Loading filter options..." />
            </div>
          ) : (
            <FilterPanel
              filters={filters}
              onChange={f => { setFilters(f); setAnalysisReady(false); }}
              metadata={metadata || {}}
              onReset={() => { resetFilters(); setAnalysisReady(false); }}
            />
          )}
        </div>
      </div>

      {/* Analysis Results */}
      {analysisReady && batter && bowler && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
          {/* Matchup header */}
          <div className="px-5 py-4 border-b border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div>
              <h2 className="text-lg font-bold text-white">
                <span className="text-indigo-300">{batter.name}</span>
                <span className="text-slate-500 mx-2 font-normal text-sm">vs</span>
                <span className="text-amber-300">{bowler.name}</span>
              </h2>
              <div className="flex items-center gap-2 mt-0.5">
                <ActiveFilters filters={filters} />
                {!Object.values(filters).some(Boolean) && (
                  <span className="text-xs text-slate-500 italic">All-time, all formats</span>
                )}
              </div>
            </div>
            {summary && (
              <div className="text-xs text-slate-400 text-right">
                <p><strong className="text-slate-200">{summary.matches_count}</strong> matches</p>
                <p><strong className="text-slate-200">{summary.balls_faced}</strong> balls analysed</p>
              </div>
            )}
          </div>

          {/* Tabs */}
          <div className="flex border-b border-slate-800 overflow-x-auto">
            {TABS.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-4 py-3 text-xs font-semibold whitespace-nowrap transition-colors border-b-2 ${
                  activeTab === tab.id
                    ? 'text-indigo-300 border-indigo-500'
                    : 'text-slate-400 hover:text-slate-200 border-transparent'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="p-5">
            {activeTab === 'summary' && (
              <SummaryPanel summary={summary} loading={summaryLoading} error={summaryError} />
            )}

            {activeTab === 'phases' && (
              summary
                ? <PhasePanel summary={summary} />
                : summaryLoading
                  ? <LoadingSpinner message="Loading phase data..." />
                  : <EmptyState message="Run analysis to see phase breakdown." />
            )}

            {activeTab === 'dismissals' && (
              <DismissalPanel data={dismissals} loading={dismLoading} error={dismError} />
            )}

            {activeTab === 'overs' && (
              <OverByOverPanel data={overData} loading={overLoading} error={overError} />
            )}

            {activeTab === 'trends' && (
              <TrendsPanel data={trendsData} loading={trendsLoading} error={trendsError} />
            )}

            {activeTab === 'matches' && (
              <MatchByMatchPanel
                batterId={batter.id}
                bowlerId={bowler.id}
                filters={filters}
              />
            )}
          </div>
        </div>
      )}

      {!analysisReady && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-16 text-center">
          <div className="text-5xl mb-4">⚡</div>
          <h3 className="text-lg font-semibold text-slate-300 mb-2">Head-to-Head Intelligence</h3>
          <p className="text-slate-500 text-sm max-w-md mx-auto">
            Select a batter and bowler above, apply any filters you need, then click <strong className="text-slate-300">Analyse Matchup</strong> to see
            complete delivery-level statistics derived from real match records.
          </p>
          <p className="text-xs text-slate-600 mt-3">
            Stats include: summary, phase breakdown, dismissal types, over-by-over analysis, year trends, and match-by-match records.
          </p>
        </div>
      )}
    </div>
  );
}
