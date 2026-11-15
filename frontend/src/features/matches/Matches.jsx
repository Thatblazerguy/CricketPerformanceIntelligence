/**
 * Match Centre index: searchable match summaries (GET /matches). Innings and
 * delivery detail load only when a match is opened. With no filters applied the
 * most recent matches are listed.
 */
import { useEffect, useState } from 'react';
import { getMatches } from '../../services/api';
import { Badge, EmptyState, ErrorState, FilterField, PageHeader, Skeleton } from '../../components/ui';
import MatchCentreLink from '../../components/MatchCentreLink';
import Icon from '../../components/icons';

const EMPTY = { format: '', search: '', competition: '', season: '', year_from: '', year_to: '', team: '', opponent: '', venue: '', country: '', result: '', start_date: '', end_date: '' };
const ADVANCED = ['team', 'opponent', 'venue', 'country', 'result', 'year_from', 'year_to', 'start_date', 'end_date'];
const FORMATS = ['Test', 'ODI', 'ODM', 'T20', 'T20I', 'MDM'];

function margin(m) {
  if (!m.winner) return m.result_type ? m.result_type[0].toUpperCase() + m.result_type.slice(1) : 'No result';
  return `${m.winner} won${m.result_margin_runs ? ` by ${m.result_margin_runs} runs` : m.result_margin_wickets ? ` by ${m.result_margin_wickets} wkts` : ''}`;
}

export default function Matches() {
  const [filters, setFilters] = useState(EMPTY);
  const [submitted, setSubmitted] = useState(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const update = (key, value) => setFilters(prev => ({ ...prev, [key]: value }));

  async function search(e, nextPage = 1, size = pageSize) {
    e?.preventDefault();
    const applied = submitted || filters;
    if (e) setSubmitted({ ...filters });
    const query = e ? filters : applied;
    setLoading(true); setError(null); setPage(nextPage);
    try {
      const payload = Object.fromEntries(Object.entries({ ...query, page: nextPage, page_size: size }).filter(([, v]) => v !== '' && v != null));
      setData(await getMatches(payload));
    } catch (err) { setError(err.message || 'Could not load matches.'); } finally { setLoading(false); }
  }
  // Default view: latest matches, newest first.
  useEffect(() => { search(null, 1); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const reset = () => { setFilters(EMPTY); setSubmitted(null); setError(null); setTimeout(() => search(null, 1), 0); };
  const activeCount = Object.values(submitted || {}).filter(Boolean).length;
  const advancedActive = ADVANCED.filter(k => filters[k]).length;
  const maxPage = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;
  const field = (key, label, props = {}) => (
    <FilterField key={key} label={label} className="min-w-0">
      <input className="h-9 w-full px-3 text-[13px]" value={filters[key]} onChange={e => update(key, e.target.value)} {...props} />
    </FilterField>
  );

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Matches" title="Match Centre" subtitle="Every imported match with scorecards, ball-by-ball commentary, partnerships and over-by-over analysis. Detail loads when a match is opened." />

      <form onSubmit={search} className="panel">
        <div className="grid grid-cols-2 gap-3 p-4 md:grid-cols-[2fr_1fr_1.5fr_1fr]">
          <FilterField label="Search" className="col-span-2 min-w-0 md:col-span-1">
            <div className="relative">
              <Icon name="search" size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
              <input className="h-9 w-full pl-8 pr-2.5 text-[13px]" placeholder="Team, tournament, venue or match ID" value={filters.search} onChange={e => update('search', e.target.value)} />
            </div>
          </FilterField>
          <FilterField label="Format" className="min-w-0">
            <select className="h-9 w-full px-3 text-[13px]" value={filters.format} onChange={e => update('format', e.target.value)}><option value="">All formats</option>{FORMATS.map(x => <option key={x}>{x}</option>)}</select>
          </FilterField>
          {field('competition', 'Competition (exact)', { placeholder: 'e.g. Indian Premier League' })}
          {field('season', 'Season', { placeholder: 'e.g. 2026' })}
        </div>
        {showAdvanced && (
          <div className="grid grid-cols-2 gap-3 border-t border-line p-4 animate-fade-in md:grid-cols-4 xl:grid-cols-5">
            {field('team', 'Team')}
            {field('opponent', 'Opponent')}
            {field('venue', 'Venue')}
            {field('country', 'Country')}
            {field('result', 'Result type', { placeholder: 'win / tie / no result' })}
            {field('year_from', 'Year from', { type: 'number' })}
            {field('year_to', 'Year to', { type: 'number' })}
            {field('start_date', 'Start date', { type: 'date' })}
            {field('end_date', 'End date', { type: 'date' })}
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-2.5">
          <button type="button" onClick={() => setShowAdvanced(v => !v)} className="btn btn-ghost btn-sm -ml-2">
            <Icon name="filter" size={14} />{showAdvanced ? 'Fewer filters' : 'More filters'}{advancedActive ? <span className="num rounded bg-accent-muted px-1.5 text-3xs text-accent-soft">{advancedActive}</span> : null}
            <Icon name="chevronDown" size={13} className={`transition-transform ${showAdvanced ? 'rotate-180' : ''}`} />
          </button>
          <div className="flex items-center gap-2">
            <button type="button" className="btn btn-ghost btn-sm" onClick={reset}>Reset</button>
            <button className="btn btn-primary btn-sm">Search matches</button>
          </div>
        </div>
      </form>

      {error && <ErrorState message={error} onRetry={() => search(null, page)} />}

      {!error && (
        <section className="panel overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5 text-2xs text-slate-500">
            <span>{data ? <><span className="num font-semibold text-slate-200">{data.total.toLocaleString()}</span> {activeCount ? 'matches for these filters' : 'matches · latest first'}</> : 'Loading…'}</span>
            <label className="flex items-center gap-2">Rows
              <select className="h-7 px-3 text-2xs" value={pageSize} onChange={e => { const n = +e.target.value; setPageSize(n); search(null, 1, n); }}><option>25</option><option>50</option><option>100</option></select>
            </label>
          </div>
          {loading && !data ? <div className="space-y-2 p-4">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-11" />)}</div>
            : data?.matches.length === 0 ? <EmptyState message="No matches found for these filters." hint="Competition matching is exact; try the free-text search instead." />
            : data && (
              <ul className={`divide-y divide-line-soft transition-opacity ${loading ? 'opacity-50' : ''}`}>
                {data.matches.map(m => (
                  <li key={m.id}>
                    <MatchCentreLink matchId={m.id} className="!no-underline">
                      <div className="row-link group grid grid-cols-[4.5rem_1fr_auto] items-center gap-x-4 px-4 py-3 md:grid-cols-[5.5rem_1.6fr_1.2fr_auto]">
                        <div className="num text-xs text-slate-400">{m.start_date}</div>
                        <div className="min-w-0">
                          <div className="truncate text-[13px]">
                            <span className={m.winner === m.team1 ? 'font-semibold text-white' : 'text-slate-300'}>{m.team1 || 'Team 1'}</span>
                            <span className="mx-1.5 text-slate-600">v</span>
                            <span className={m.winner === m.team2 ? 'font-semibold text-white' : 'text-slate-300'}>{m.team2 || 'Team 2'}</span>
                          </div>
                          <div className="mt-0.5 truncate text-2xs text-slate-500">{m.competition || 'Unlisted competition'}{m.season ? ` · ${m.season}` : ''}<span className="md:hidden">{m.venue ? ` · ${m.venue.split(',')[0]}` : ''}</span></div>
                        </div>
                        <div className="hidden min-w-0 md:block">
                          <div className={`truncate text-xs ${m.winner ? 'text-pos-soft' : 'text-slate-500'}`}>{margin(m)}</div>
                          <div className="mt-0.5 truncate text-2xs text-slate-500">{m.venue || 'Venue unavailable'}</div>
                        </div>
                        <div className="flex items-center gap-3">
                          <Badge>{m.match_format}</Badge>
                          <Icon name="chevronRight" size={14} className="text-slate-600 transition-colors group-hover:text-slate-300" />
                        </div>
                      </div>
                    </MatchCentreLink>
                  </li>
                ))}
              </ul>
            )}
          {data && maxPage > 1 && (
            <div className="flex items-center justify-between border-t border-line px-4 py-2.5 text-2xs text-slate-500">
              <span className="num">Page {page} of {maxPage.toLocaleString()}</span>
              <div className="flex items-center gap-1">
                <button disabled={page <= 1 || loading} onClick={() => search(null, page - 1)} className="btn btn-secondary btn-xs"><Icon name="chevronLeft" size={13} />Previous</button>
                <button disabled={page >= maxPage || loading} onClick={() => search(null, page + 1)} className="btn btn-secondary btn-xs">Next<Icon name="chevronRight" size={13} /></button>
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
