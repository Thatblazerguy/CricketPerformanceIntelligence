/**
 * Players Directory Page
 * Search every indexed player with fuzzy name matching (initials, full names, typos), team names,
 * nationality, roles and bowling styles. Filters, role-aware sorting and the stats on each card are
 * computed server-side from delivery-level data for the selected scope (format, gender, competition, team).
 * Detailed analytics live inside the individual Player Profile.
 *
 * All search state lives in the URL so returning from a profile restores the exact search.
 */
import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { getPlayerSearchOptions, searchPlayers, suggestPlayers } from '../../services/api';
import { Avatar, Badge, EmptyState, ErrorState, FilterField, PageHeader, Segmented, Skeleton } from '../../components/ui';
import Icon from '../../components/icons';

const FORMATS = [
  { id: '', label: 'All formats' },
  { id: 'T20I', label: 'T20I' },
  { id: 'T20', label: 'T20 (franchise/domestic)' },
  { id: 'ODI', label: 'ODI' },
  { id: 'Test', label: 'Test' },
  { id: 'MDM', label: 'Multi-day domestic' },
  { id: 'ODM', label: 'One-day domestic' },
];
const GENDERS = [{ id: '', label: 'All' }, { id: 'male', label: 'Men' }, { id: 'female', label: 'Women' }];
const ROLES = [{ id: '', label: 'All roles' }, { id: 'batter', label: 'Batters' }, { id: 'bowler', label: 'Bowlers' }, { id: 'all_rounder', label: 'All-rounders' }];

// label, short label for card highlight, and which disciplines it belongs to
const SORTS = {
  relevance: { label: 'Best match' },
  matches: { label: 'Matches', group: 'general' },
  runs: { label: 'Runs', group: 'bat' },
  batting_average: { label: 'Batting average', group: 'bat' },
  batting_strike_rate: { label: 'Strike rate', group: 'bat' },
  highest_score: { label: 'Highest score', group: 'bat' },
  hundreds: { label: 'Hundreds', group: 'bat' },
  fifties: { label: 'Fifties', group: 'bat' },
  sixes: { label: 'Sixes', group: 'bat' },
  wickets: { label: 'Wickets', group: 'bowl' },
  bowling_average: { label: 'Bowling average', group: 'bowl' },
  economy: { label: 'Economy', group: 'bowl' },
  bowling_strike_rate: { label: 'Bowling strike rate', group: 'bowl' },
  five_wickets: { label: 'Five-wicket hauls', group: 'bowl' },
  last_played: { label: 'Most recent match', group: 'general' },
  name: { label: 'Name', group: 'general' },
};
const LOWER_IS_BETTER = new Set(['bowling_average', 'economy', 'bowling_strike_rate']);
const ADVANCED_KEYS = ['competition', 'team', 'nationality', 'batting_style', 'bowling_type', 'bowling_style', 'bowling_arm', 'status', 'min_matches'];
const FILTER_LABELS = {
  format: 'Format', gender: 'Gender', role: 'Role', competition: 'Competition', team: 'Team', nationality: 'Nationality',
  batting_style: 'Batting', bowling_type: 'Bowling type', bowling_style: 'Bowling style', bowling_arm: 'Arm',
  status: 'Status', min_matches: 'Min matches',
};
const PAGE_SIZE = 24;

const RECENT_PLAYERS_KEY = 'cpi.players.recentPlayers';
const RECENT_QUERIES_KEY = 'cpi.players.recentQueries';
const VIEW_KEY = 'cpi.players.view';
const readList = key => { try { const v = JSON.parse(localStorage.getItem(key) || '[]'); return Array.isArray(v) ? v : []; } catch { return []; } };
const writeList = (key, list) => { try { localStorage.setItem(key, JSON.stringify(list)); } catch { /* storage unavailable */ } };
const pushRecent = (key, item, same, max = 6) => { const next = [item, ...readList(key).filter(x => !same(x))].slice(0, max); writeList(key, next); return next; };

const fmtNum = (v, digits = 0) => (v === null || v === undefined ? '—' : Number(v).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits }));
const roleVariant = r => (r?.includes('Batter') ? 'blue' : r?.includes('Bowler') ? 'amber' : r?.includes('All-Rounder') ? 'green' : 'default');
const isBowlingRole = r => r === 'Specialist Bowler';
const isAllRounder = r => r?.includes('All-Rounder');

/** Profile defaults to T20; send the player to a format they actually played (the active one if set). */
function profileHref(player, format) {
  const fmts = player.formats || [];
  const target = format || (fmts.includes('T20') ? '' : ['T20I', 'ODI', 'Test', 'ODM', 'MDM'].find(f => fmts.includes(f)) || '');
  return `/players/${player.id}${target ? `?format=${target}` : ''}`;
}

function useDebounced(value, delay) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => { const t = setTimeout(() => setDebounced(value), delay); return () => clearTimeout(t); }, [value, delay]);
  return debounced;
}

export default function Players() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const get = k => params.get(k) || '';
  const q = get('q');
  const format = get('format');
  const gender = get('gender');
  const role = get('role');
  const sort = get('sort') || (q ? 'relevance' : role === 'bowler' ? 'wickets' : 'runs');
  const dir = get('dir') || 'desc';
  const page = Math.max(1, Number(get('page')) || 1);

  const update = useCallback((patch, { keepPage = false } = {}) => {
    setParams(prev => {
      const next = new URLSearchParams(prev);
      Object.entries(patch).forEach(([k, v]) => (v === '' || v === null || v === undefined ? next.delete(k) : next.set(k, String(v))));
      if (!keepPage) next.delete('page');
      return next;
    }, { replace: true });
  }, [setParams]);

  const [view, setView] = useState(() => { try { return localStorage.getItem(VIEW_KEY) || 'cards'; } catch { return 'cards'; } });
  useEffect(() => { try { localStorage.setItem(VIEW_KEY, view); } catch { /* storage unavailable */ } }, [view]);
  const advancedActive = ADVANCED_KEYS.filter(k => get(k)).length;
  const [showFilters, setShowFilters] = useState(advancedActive > 0);

  // ----- filter options (counts are players in the current format/gender scope)
  const [options, setOptions] = useState(null);
  const optionsCache = useRef({});
  useEffect(() => {
    const key = `${format}|${gender}`;
    if (optionsCache.current[key]) { setOptions(optionsCache.current[key]); return; }
    let live = true;
    getPlayerSearchOptions({ format, gender }).then(o => { optionsCache.current[key] = o; if (live) setOptions(o); }).catch(() => {});
    return () => { live = false; };
  }, [format, gender]);

  // ----- results
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [reload, setReload] = useState(0);
  const queryKey = params.toString();
  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    searchPlayers({
      q, format, gender, role, competition: get('competition'), team_id: get('team'), nationality: get('nationality'),
      batting_style: get('batting_style'), bowling_type: get('bowling_type'), bowling_style: get('bowling_style'),
      bowling_arm: get('bowling_arm'), status: get('status'), min_matches: get('min_matches'),
      sort, dir, page, page_size: PAGE_SIZE,
    }, ctrl.signal)
      .then(res => { setData(res); setLoading(false); })
      .catch(err => { if (err.name !== 'AbortError') { setError(err.message || 'Failed to search players.'); setLoading(false); } });
    return () => ctrl.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey, reload]);

  // ----- recent activity
  const [recentPlayers, setRecentPlayers] = useState(() => readList(RECENT_PLAYERS_KEY));
  const [recentQueries, setRecentQueries] = useState(() => readList(RECENT_QUERIES_KEY));
  const rememberPlayer = p => setRecentPlayers(pushRecent(RECENT_PLAYERS_KEY, { id: p.id, name: p.name, role: p.role, nationality: p.nationality, formats: p.formats || [] }, x => x.id === p.id));
  const rememberQuery = text => { const t = text.trim(); if (t.length >= 2) setRecentQueries(pushRecent(RECENT_QUERIES_KEY, t, x => x.toLowerCase() === t.toLowerCase(), 8)); };
  const clearRecent = () => { writeList(RECENT_PLAYERS_KEY, []); writeList(RECENT_QUERIES_KEY, []); setRecentPlayers([]); setRecentQueries([]); };

  const openPlayer = p => { rememberPlayer(p); if (q) rememberQuery(q); navigate(profileHref(p, format)); };

  // ----- role switch keeps sort meaningful for the discipline
  const handleRole = r => {
    const patch = { role: r };
    const group = SORTS[sort]?.group;
    if (r === 'bowler' && group === 'bat') patch.sort = 'wickets';
    if (r === 'batter' && group === 'bowl') patch.sort = 'runs';
    update(patch);
  };

  const sortOptions = useMemo(() => {
    const groups = role === 'bowler' ? ['bowl', 'bat'] : ['bat', 'bowl'];
    const pick = g => Object.entries(SORTS).filter(([, s]) => s.group === g);
    return [
      ...(q ? [['relevance', SORTS.relevance]] : []),
      ...pick('general').filter(([k]) => k === 'matches'),
      ...groups.flatMap(pick),
      ...pick('general').filter(([k]) => k !== 'matches'),
    ];
  }, [q, role]);

  const scopeChips = [
    ...['gender', 'role', ...ADVANCED_KEYS].filter(k => get(k)).map(k => {
      let value = get(k);
      if (k === 'gender') value = value === 'male' ? 'Men' : 'Women';
      if (k === 'role') value = ROLES.find(r => r.id === value)?.label || value;
      if (k === 'team') value = options?.teams?.find(t => t.value === value)?.label || 'Selected team';
      if (k === 'status') value = value === 'active' ? 'Active' : 'Inactive';
      if (k === 'min_matches') value = `${value}+`;
      return { key: k, label: FILTER_LABELS[k], value };
    }),
  ];
  const anyFilter = Boolean(format || scopeChips.length);
  const clearFilters = () => update(Object.fromEntries(['format', 'gender', 'role', ...ADVANCED_KEYS].map(k => [k, ''])));

  const totalPages = data?.total_pages || 1;
  const sortLabel = SORTS[data?.sort || sort]?.label;
  const scopeLabel = [FORMATS.find(f => f.id === format)?.label, get('competition'), gender ? (gender === 'male' ? 'Men' : 'Women') : null].filter(Boolean).join(' · ');

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Players" title="Player directory"
        subtitle="Search by name, initials, nickname spelling, team, nationality, role or bowling style. Stats reflect the selected format and filters." />

      <div className="panel relative z-20 divide-y divide-line">
        <div className="flex flex-col gap-3 p-3 lg:flex-row lg:items-center lg:justify-between">
          <SearchBox value={q} onCommit={text => { update({ q: text, sort: get('sort') === 'relevance' && !text ? '' : get('sort') }); if (text) rememberQuery(text); }}
            onPickPlayer={openPlayer} onPickTeam={t => { update({ team: t.id, q: '' }); setShowFilters(true); }}
            recentPlayers={recentPlayers} recentQueries={recentQueries} onClearRecent={clearRecent} format={format} />
          <div className="flex flex-wrap items-center gap-2">
            <Segmented label="Gender" value={gender} onChange={g => update({ gender: g, team: '' })} options={GENDERS} />
            <Segmented label="Role" value={role} onChange={handleRole} options={ROLES} />
          </div>
        </div>
        <div className="flex items-center gap-2 overflow-x-auto px-3 py-2.5 scrollbar-none">
          <span className="eyebrow shrink-0 pr-1">Format</span>
          {FORMATS.map(f => (
            <button key={f.id} onClick={() => update({ format: f.id, competition: '' })} aria-pressed={format === f.id}
              className={`shrink-0 whitespace-nowrap rounded-full border px-3 py-1 text-xs transition-colors ${format === f.id ? 'border-accent/50 bg-accent-muted text-white' : 'border-line text-slate-400 hover:border-line-strong hover:text-slate-200'}`}>
              {f.label}
            </button>
          ))}
          <button type="button" onClick={() => setShowFilters(s => !s)} aria-expanded={showFilters}
            className="btn btn-ghost btn-sm ml-auto shrink-0">
            <Icon name="filter" size={14} />More filters{advancedActive > 0 && <span className="num rounded-full bg-accent/20 px-1.5 text-2xs text-accent-soft">{advancedActive}</span>}
            <Icon name="chevronDown" size={13} className={`transition-transform duration-200 ${showFilters ? 'rotate-180' : ''}`} />
          </button>
        </div>
        {showFilters && (
          <AdvancedFilters options={options} get={get} update={update} format={format} gender={gender} />
        )}
      </div>

      {/* Toolbar: result count, active filters, sorting, view */}
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="text-xs text-slate-400" aria-live="polite">
            {data ? <><strong className="num font-semibold text-white">{data.total.toLocaleString()}</strong> {data.total === 1 ? 'player' : 'players'}{q && <> matching “<span className="text-slate-200">{q}</span>”</>}{scopeLabel && <> in {scopeLabel}</>}</> : 'Searching…'}
          </span>
          {scopeChips.map(c => (
            <button key={c.key} type="button" onClick={() => update({ [c.key]: '' })} className="chip group hover:border-line-strong" title={`Remove ${c.label} filter`}>
              <span className="text-slate-500">{c.label}:</span>{c.value}<Icon name="close" size={11} className="text-slate-500 group-hover:text-slate-200" />
            </button>
          ))}
          {anyFilter && <button type="button" onClick={clearFilters} className="text-2xs font-medium text-accent-soft hover:text-white">Clear filters</button>}
          <div className="ml-auto flex items-center gap-2">
            <label className="flex items-center gap-2 text-xs text-slate-500">
              <span className="hidden sm:inline">Sort by</span>
              <select value={data?.sort || sort} onChange={e => update({ sort: e.target.value, dir: '' })} className="h-8 px-3 text-xs" aria-label="Sort by">
                {sortOptions.map(([k, s]) => <option key={k} value={k}>{s.label}</option>)}
              </select>
            </label>
            {sort !== 'relevance' && (
              <button type="button" className="btn btn-secondary btn-xs h-8" onClick={() => update({ dir: dir === 'desc' ? 'asc' : 'desc' })}
                title="Reverse order">
                {sort === 'name' ? (dir === 'desc' ? 'Z → A' : 'A → Z') : sort === 'last_played' ? (dir === 'desc' ? 'Newest' : 'Oldest') : dir === 'desc' ? (LOWER_IS_BETTER.has(sort) ? 'Lowest first' : 'Highest first') : (LOWER_IS_BETTER.has(sort) ? 'Highest first' : 'Lowest first')}
              </button>
            )}
            <Segmented size="xs" label="View" value={view} onChange={setView} options={[{ id: 'cards', label: 'Cards' }, { id: 'table', label: 'Table' }]} />
          </div>
        </div>
        {data?.qualifier && (
          <p className="text-2xs text-slate-500">
            <Icon name="info" size={12} className="mr-1 inline -translate-y-px" />
            Ranked on {sortLabel?.toLowerCase()} only for players with at least {data.qualifier.minimum} {data.qualifier.stat === 'balls_faced' ? 'balls faced' : 'legal balls bowled'} in this scope
            {data.qualifier.excluded > 0 && <> ({data.qualifier.excluded.toLocaleString()} with smaller samples hidden)</>}.
          </p>
        )}
      </div>

      {error && <ErrorState message={error} onRetry={() => setReload(r => r + 1)} />}
      {!error && !data && loading && <ResultsSkeleton view={view} />}
      {!error && data && (
        <div className={`transition-opacity duration-200 ${loading ? 'pointer-events-none opacity-50' : ''}`} aria-busy={loading}>
          {data.players.length === 0 ? (
            <div className="panel">
              <EmptyState icon="search"
                message={q ? `No players match “${q}”${anyFilter ? ' with these filters' : ''}.` : 'No players match these filters.'}
                hint={anyFilter ? 'Filters narrow the search to players who appeared in that scope. Try removing one.' : 'Check the spelling, or try a surname, initials (e.g. “MS Dhoni”), a team or a country.'}
                action={<div className="flex gap-2">{anyFilter && <button className="btn btn-secondary btn-sm" onClick={clearFilters}>Clear filters</button>}{q && <button className="btn btn-ghost btn-sm" onClick={() => update({ q: '' })}>Clear search</button>}</div>} />
            </div>
          ) : view === 'cards' ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {data.players.map((p, i) => <PlayerCard key={p.id} p={p} index={i} sort={data.sort} format={format} showGender={!gender} onOpen={() => openPlayer(p)} />)}
            </div>
          ) : (
            <ResultsTable players={data.players} sort={data.sort} format={format} onOpen={openPlayer}
              onSort={k => update(k === (data.sort || sort) ? { dir: dir === 'desc' ? 'asc' : 'desc' } : { sort: k, dir: '' })} />
          )}

          {data.total > PAGE_SIZE && (
            <div className="mt-4 flex flex-col items-center justify-between gap-3 text-2xs text-slate-500 sm:flex-row">
              <span className="num">Showing {((page - 1) * PAGE_SIZE + 1).toLocaleString()}–{Math.min(page * PAGE_SIZE, data.total).toLocaleString()} of {data.total.toLocaleString()}</span>
              <div className="flex items-center gap-1">
                <button onClick={() => update({ page: '' }, { keepPage: true })} disabled={page <= 1} className="btn btn-ghost btn-xs">First</button>
                <button onClick={() => update({ page: page - 1 }, { keepPage: true })} disabled={page <= 1} className="btn btn-secondary btn-xs px-1.5" aria-label="Previous page"><Icon name="chevronLeft" size={13} /></button>
                <span className="num px-2 text-slate-400">{page} / {totalPages}</span>
                <button onClick={() => update({ page: page + 1 }, { keepPage: true })} disabled={page >= totalPages} className="btn btn-secondary btn-xs px-1.5" aria-label="Next page"><Icon name="chevronRight" size={13} /></button>
                <button onClick={() => update({ page: totalPages }, { keepPage: true })} disabled={page >= totalPages} className="btn btn-ghost btn-xs">Last</button>
              </div>
            </div>
          )}
        </div>
      )}
      {!q && !anyFilter && data && page === 1 && (
        <p className="text-center text-2xs text-slate-600">Showing every player with ball-by-ball records. Press ⌘K anywhere to jump straight to a profile.</p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ search box with typeahead */

function SearchBox({ value, onCommit, onPickPlayer, onPickTeam, recentPlayers, recentQueries, onClearRecent, format }) {
  const [text, setText] = useState(value);
  const [open, setOpen] = useState(false);
  const [suggestions, setSuggestions] = useState([]);
  const [suggesting, setSuggesting] = useState(false);
  const [active, setActive] = useState(-1);
  const wrapRef = useRef(null);
  const inputRef = useRef(null);
  const debouncedText = useDebounced(text, 160);
  const debouncedCommit = useDebounced(text, 450);

  useEffect(() => { setText(value); }, [value]);
  // Live search: commit after the user pauses typing (results are cached server-side).
  useEffect(() => { if (debouncedCommit.trim() !== value) onCommit(debouncedCommit.trim()); // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedCommit]);

  useEffect(() => {
    const t = debouncedText.trim();
    if (t.length < 2) { setSuggestions([]); setSuggesting(false); return; }
    const ctrl = new AbortController();
    setSuggesting(true);
    suggestPlayers(t, ctrl.signal)
      .then(r => { setSuggestions(r.suggestions || []); setActive(-1); setSuggesting(false); })
      .catch(err => { if (err.name !== 'AbortError') { setSuggestions([]); setSuggesting(false); } });
    return () => ctrl.abort();
  }, [debouncedText]);

  useEffect(() => {
    const onDoc = e => { if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const showRecent = text.trim().length < 2;
  const items = showRecent
    ? [...recentPlayers.map(p => ({ ...p, type: 'player', recent: true })), ...recentQueries.map(qq => ({ type: 'query', name: qq }))]
    : suggestions;

  const choose = item => {
    setOpen(false);
    if (item.type === 'player') onPickPlayer(item);
    else if (item.type === 'team') { setText(''); onPickTeam(item); }
    else { setText(item.name); onCommit(item.name); }
  };

  const onKeyDown = e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setActive(a => Math.min(items.length - 1, a + 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(a => Math.max(-1, a - 1)); }
    else if (e.key === 'Escape') { setOpen(false); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      if (open && active >= 0 && items[active]) choose(items[active]);
      else { setOpen(false); onCommit(text.trim()); }
    }
  };

  return (
    <div ref={wrapRef} className="relative w-full lg:max-w-md">
      <div className="relative">
        <Icon name="search" size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
        <input ref={inputRef} type="text" inputMode="search" enterKeyHint="search" value={text} placeholder="Search players, teams, countries, styles…" aria-label="Search players"
          role="combobox" aria-expanded={open && items.length > 0} aria-controls="player-suggest" aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? `player-suggest-${active}` : undefined}
          onChange={e => { setText(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} onKeyDown={onKeyDown}
          className="h-9 w-full pl-9 pr-9 text-[13px]" autoComplete="off" spellCheck={false} />
        {suggesting && <span className="absolute right-9 top-1/2 h-3.5 w-3.5 -translate-y-1/2 animate-spin rounded-full border-2 border-transparent border-t-accent" aria-hidden="true" />}
        {text && (
          <button type="button" onClick={() => { setText(''); onCommit(''); inputRef.current?.focus(); }} aria-label="Clear search"
            className="absolute right-2 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-full text-slate-500 hover:bg-white/[0.06] hover:text-slate-200">
            <Icon name="close" size={13} />
          </button>
        )}
      </div>
      {open && (items.length > 0 || (!showRecent && !suggesting && debouncedText.trim().length >= 2)) && (
        <div id="player-suggest" role="listbox" className="panel-raised absolute left-0 right-0 top-full z-30 mt-1.5 max-h-[22rem] overflow-y-auto p-1.5 animate-[fade-in_120ms_ease-out]">
          {showRecent && (
            <div className="flex items-center justify-between px-2.5 pb-1 pt-1.5">
              <span className="eyebrow">Recent</span>
              <button type="button" onClick={onClearRecent} className="text-2xs text-slate-500 hover:text-slate-200">Clear</button>
            </div>
          )}
          {items.length === 0 && <p className="px-3 py-3 text-xs text-slate-500">No quick matches. Press Enter to run a full search.</p>}
          {items.map((item, i) => (
            <button key={`${item.type}-${item.id || item.name}`} id={`player-suggest-${i}`} type="button" role="option" aria-selected={i === active}
              onMouseEnter={() => setActive(i)} onMouseDown={e => e.preventDefault()} onClick={() => choose(item)}
              className={`flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-[13px] transition-colors ${i === active ? 'bg-surface-hover text-white' : 'text-slate-300'}`}>
              {item.type === 'player' && <Avatar name={item.name} size="sm" />}
              {item.type === 'team' && <span className="grid h-7 w-7 place-items-center rounded-full bg-white/[0.06] text-slate-400"><Icon name="teams" size={14} /></span>}
              {item.type === 'query' && <span className="grid h-7 w-7 place-items-center rounded-full text-slate-500"><Icon name="search" size={14} /></span>}
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{item.name}{item.full_name && <span className="ml-1.5 font-normal text-slate-500">{item.full_name}</span>}</span>
                {item.type === 'player' && (
                  <span className="block truncate text-2xs text-slate-500">
                    {[item.role && item.role !== 'Unclassified' ? item.role : null, item.nationality, item.gender === 'female' ? 'Women' : null, item.matches ? `${item.matches} matches` : null].filter(Boolean).join(' · ') || 'No ball-by-ball record'}
                  </span>
                )}
                {item.type === 'team' && <span className="block text-2xs text-slate-500">Filter players by team</span>}
              </span>
              {item.type === 'player' && <Icon name="arrowRight" size={13} className="text-slate-600" />}
            </button>
          ))}
          {!showRecent && text.trim() && (
            <button type="button" onMouseDown={e => e.preventDefault()} onClick={() => { setOpen(false); onCommit(text.trim()); }}
              className="mt-1 flex w-full items-center gap-2 rounded-xl border-t border-line-soft px-2.5 py-2 text-left text-xs text-slate-400 hover:text-white">
              <Icon name="search" size={13} />See all results for “{text.trim()}”{format && <span className="text-slate-600">in {format}</span>}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ advanced filters */

function AdvancedFilters({ options, get, update, format, gender }) {
  const opt = (list, render = o => `${o.value} (${o.count})`) => (list || []).map(o => <option key={o.value} value={o.value}>{render(o)}</option>);
  const sel = (key, label, children, extra = {}) => (
    <FilterField label={label} className="min-w-0">
      <select className="h-9 w-full px-3 text-[13px]" value={get(key)} onChange={e => update({ [key]: e.target.value })} disabled={!options} {...extra}>
        <option value="">Any</option>{children}
      </select>
    </FilterField>
  );
  const coverage = options && (
    <p className="col-span-full text-2xs leading-relaxed text-slate-500">
      Counts are players with records in {format || 'any format'}{gender ? ` (${gender === 'male' ? 'men' : 'women'})` : ''}. Batting and bowling styles are only listed where the data source records them
      ({(options.batting_styles || []).reduce((n, o) => n + o.count, 0)} with batting style, {(options.bowling_styles || []).reduce((n, o) => n + o.count, 0)} with bowling style), so style filters return a subset.
      “Active” means a match within {Math.round((options.active_window_days || 365) / 30.4)} months of the latest recorded match.
    </p>
  );
  return (
    <div className="grid grid-cols-2 gap-3 p-3 md:grid-cols-3 xl:grid-cols-5 animate-[fade-in_160ms_ease-out]">
      {sel('competition', 'Competition', opt(options?.competitions, o => `${o.value} (${o.count} matches)`))}
      {sel('team', 'Team', opt(options?.teams, o => `${o.label} (${o.count})`))}
      {sel('nationality', 'Nationality', opt(options?.nationalities))}
      {sel('status', 'Playing status', <>
        <option value="active">Active ({options?.status_counts?.find(s => s.value === 'active')?.count ?? 0})</option>
        <option value="inactive">Inactive ({options?.status_counts?.find(s => s.value === 'inactive')?.count ?? 0})</option>
      </>)}
      <FilterField label="Minimum matches" className="min-w-0">
        <select className="h-9 w-full px-3 text-[13px]" value={get('min_matches')} onChange={e => update({ min_matches: e.target.value })}>
          <option value="">Any</option>{[5, 10, 25, 50, 100].map(n => <option key={n} value={n}>{n}+</option>)}
        </select>
      </FilterField>
      {sel('batting_style', 'Batting style', opt(options?.batting_styles))}
      {sel('bowling_type', 'Bowling type', opt(options?.bowling_types))}
      {sel('bowling_style', 'Bowling style', opt(options?.bowling_styles))}
      {sel('bowling_arm', 'Bowling arm', opt(options?.bowling_arms, o => `${o.value.replace(/^./, c => c.toUpperCase())} (${o.count})`))}
      <div className="flex items-end">
        <button type="button" className="btn btn-ghost btn-sm w-full" onClick={() => update(Object.fromEntries(ADVANCED_KEYS.map(k => [k, ''])))}
          disabled={!ADVANCED_KEYS.some(k => get(k))}>Reset these filters</button>
      </div>
      {coverage}
    </div>
  );
}

/* ------------------------------------------------------------------ result views */

function statLine(p) {
  const s = p.stats;
  if (!s) return [];
  const bat = [['Runs', fmtNum(s.runs), 'runs'], ['Avg', fmtNum(s.batting_average, 2), 'batting_average'], ['SR', fmtNum(s.batting_strike_rate, 1), 'batting_strike_rate'], ['HS', s.highest_score ?? '—', 'highest_score'], ['100s/50s', `${s.hundreds}/${s.fifties}`, s.hundreds ? 'hundreds' : 'fifties']];
  const bowl = [['Wkts', fmtNum(s.wickets), 'wickets'], ['Avg', fmtNum(s.bowling_average, 2), 'bowling_average'], ['Econ', fmtNum(s.economy, 2), 'economy'], ['SR', fmtNum(s.bowling_strike_rate, 1), 'bowling_strike_rate'], ['Best', s.best_bowling ?? '—', 'five_wickets']];
  const m = ['Mat', fmtNum(s.matches), 'matches'];
  if (isBowlingRole(p.role)) return [m, ...bowl];
  if (isAllRounder(p.role)) return [m, bat[0], ['Bat avg', bat[1][1], bat[1][2]], ['Bat SR', bat[2][1], bat[2][2]], bowl[0], bowl[2]];
  if (s.legal_balls > s.balls_faced) return [m, ...bowl];
  return [m, ...bat];
}

function PlayerCard({ p, index, sort, format, showGender, onOpen }) {
  const stats = statLine(p);
  const styles = [p.batting_style && `${p.batting_style} bat`, p.bowling_style || (p.bowling_type && `${p.bowling_type} bowler`)].filter(Boolean);
  return (
    <Link to={profileHref(p, format)} onClick={e => { if (!e.metaKey && !e.ctrlKey && !e.shiftKey) { e.preventDefault(); onOpen(); } }}
      className="panel group flex flex-col gap-3.5 p-4 transition-[border-color,transform,box-shadow] duration-200 hover:-translate-y-0.5 hover:border-line-strong focus-visible:-translate-y-0.5 motion-safe:animate-[fade-up_260ms_ease-out_both]"
      style={{ animationDelay: `${Math.min(index, 11) * 22}ms` }}>
      <div className="flex items-start gap-3">
        {p.player_image
          ? <img src={p.player_image} alt="" className="h-11 w-11 shrink-0 rounded-full object-cover" loading="lazy" />
          : <Avatar name={p.name} className="!h-11 !w-11" />}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-[15px] font-semibold text-slate-100 group-hover:text-white">{p.name}</span>
            {p.status === 'active' && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-pos" title="Active: played within the last 12 months of recorded matches" />}
          </div>
          <p className="truncate text-xs text-slate-500">
            {[p.full_name, p.nationality, showGender && p.gender ? (p.gender === 'male' ? 'Men' : 'Women') : null].filter(Boolean).join(' · ') || 'Nationality not recorded'}
          </p>
        </div>
        <Badge variant={roleVariant(p.role)} className="shrink-0">{p.role}</Badge>
      </div>

      {(styles.length > 0 || p.teams.length > 0) && (
        <div className="space-y-1 text-2xs text-slate-500">
          {styles.length > 0 && <p className="truncate"><span className="text-slate-600">Style</span> <span className="text-slate-400">{styles.join(' · ')}</span></p>}
          {p.teams.length > 0 && (
            <p className="truncate" title={p.teams.join(', ')}><span className="text-slate-600">Teams</span> <span className="text-slate-400">{p.teams.slice(0, 2).join(', ')}{p.teams.length > 2 && ` +${p.teams.length - 2}`}</span></p>
          )}
        </div>
      )}

      {stats.length ? (
        <dl className="mt-auto grid grid-cols-3 gap-px overflow-hidden rounded-xl border border-line-soft bg-line-soft">
          {stats.map(([label, value, key]) => (
            <div key={label} className={`bg-surface px-2 py-2 ${key === sort ? 'bg-accent/[0.08]' : ''}`}>
              <dt className={`text-[10px] font-medium ${key === sort ? 'text-accent-soft' : 'text-slate-500'}`}>{label}</dt>
              <dd className="num truncate text-[13px] font-semibold text-slate-100">{value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="mt-auto rounded-xl border border-dashed border-line-soft px-3 py-2.5 text-2xs text-slate-500">No ball-by-ball record in this scope.</p>
      )}
      <div className="flex items-center justify-between text-2xs text-slate-600">
        <span className="truncate">{p.formats.length ? p.formats.join(' · ') : ''}{p.last_played && <> · last {p.last_played.slice(0, 4)}</>}</span>
        <span className="inline-flex items-center gap-1 text-slate-500 transition-colors group-hover:text-accent-soft">Profile<Icon name="arrowRight" size={12} /></span>
      </div>
    </Link>
  );
}

const TABLE_COLS = [
  ['matches', 'Mat'], ['runs', 'Runs'], ['batting_average', 'Bat avg'], ['batting_strike_rate', 'SR'], ['highest_score', 'HS'],
  ['wickets', 'Wkts'], ['bowling_average', 'Bowl avg'], ['economy', 'Econ'], ['bowling_strike_rate', 'Bowl SR'],
];

function ResultsTable({ players, sort, format, onOpen, onSort }) {
  const cell = (p, k) => {
    const s = p.stats;
    if (!s) return '—';
    const digits = { batting_average: 2, batting_strike_rate: 1, bowling_average: 2, economy: 2, bowling_strike_rate: 1 }[k] ?? 0;
    return k === 'highest_score' ? (s.highest_score ?? '—') : fmtNum(s[k], digits);
  };
  return (
    <div className="panel overflow-x-auto">
      <table className="w-full min-w-[960px] text-left text-[13px] text-slate-300">
        <thead className="sticky top-0 bg-surface-raised text-3xs font-semibold text-slate-500">
          <tr className="border-b border-line">
            <th className="px-4 py-2.5">Player</th>
            <th className="px-3 py-2.5">Role</th>
            <th className="px-3 py-2.5">Country</th>
            {TABLE_COLS.map(([k, label]) => (
              <th key={k} className="px-3 py-2.5 text-right" aria-sort={sort === k ? 'descending' : undefined}>
                <button type="button" onClick={() => onSort(k)} className={`hover:text-slate-200 ${sort === k ? 'text-accent-soft' : ''}`}>{label}</button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {players.map(p => (
            <tr key={p.id} className="group border-b border-line-soft transition-colors last:border-0 hover:bg-surface-hover/60">
              <td className="px-4 py-2.5">
                <Link to={profileHref(p, format)} onClick={e => { if (!e.metaKey && !e.ctrlKey) { e.preventDefault(); onOpen(p); } }} className="flex items-center gap-2.5">
                  <Avatar name={p.name} size="sm" />
                  <span className="min-w-0">
                    <span className="block font-medium text-slate-100 group-hover:text-white">{p.name}</span>
                    {p.bowling_style && <span className="block text-2xs text-slate-500">{p.bowling_style}</span>}
                  </span>
                </Link>
              </td>
              <td className="px-3 py-2.5"><Badge variant={roleVariant(p.role)}>{p.role}</Badge></td>
              <td className="px-3 py-2.5">{p.nationality ?? <span className="text-slate-600">—</span>}</td>
              {TABLE_COLS.map(([k]) => <td key={k} className={`num px-3 py-2.5 text-right ${sort === k ? 'font-semibold text-white' : ''}`}>{cell(p, k)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResultsSkeleton({ view }) {
  if (view === 'table') return <div className="panel space-y-3 p-4" aria-busy="true">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-7" />)}</div>;
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true" aria-label="Loading players">
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className="panel space-y-4 p-4">
          <div className="flex items-center gap-3"><Skeleton className="h-11 w-11 rounded-full" /><div className="flex-1 space-y-2"><Skeleton className="h-3.5 w-2/3" /><Skeleton className="h-2.5 w-1/2" /></div></div>
          <Skeleton className="h-2.5 w-3/4" />
          <Skeleton className="h-12 rounded-xl" />
        </div>
      ))}
    </div>
  );
}
