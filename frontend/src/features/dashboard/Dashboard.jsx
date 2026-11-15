/**
 * Dashboard — the state of CPI's cricket data at a glance.
 *
 * Every figure is read from the API (no hardcoded statistics):
 *  - /dataset/coverage      totals, format mix, matches per year
 *  - /matches               most recent results
 *  - /tournaments           competition activity
 *  - /tournaments/detail    standings, leaders and scoring trends for a spotlight competition
 */
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getCoverage, getMatches, getTournamentDetail, getTournaments } from '../../services/api';
import { useApi } from '../../hooks/useApi';
import { Badge, Button, DashboardSkeleton, EmptyState, ErrorState, MatchLink, PageHeader, Panel, PlayerLink, Select, Skeleton, StatCard } from '../../components/ui';
import { BarChart, ColumnChart, MultiSeriesLine, PALETTE } from '../../components/charts';
import MatchCentreLink from '../../components/MatchCentreLink';
import Icon from '../../components/icons';
import { NAV_GROUPS } from '../../components/navigation';
import { fmtDec, fmtInt, FORMATS } from '../../lib/format';

const FORMAT_NAME = Object.fromEntries(FORMATS.map(f => [f.id, f.label]));
const FORMAT_COLOR = { T20: PALETTE[0], T20I: PALETTE[3], ODI: PALETTE[1], ODM: PALETTE[6], Test: PALETTE[2], MDM: PALETTE[4] };
const daysBetween = (a, b) => Math.round((new Date(a) - new Date(b)) / 86400000);
const compKey = t => `${t.name}|${t.format}|${t.gender}`;
const tournamentUrl = (t, season) => `/tournaments?gender=${t.gender}&tournament=${encodeURIComponent(compKey(t))}${season ? `&season=${encodeURIComponent(season)}` : ''}`;

function resultLine(m) {
  if (m.winner) return { text: `${m.winner} won${m.result_margin_runs ? ` by ${m.result_margin_runs} runs` : m.result_margin_wickets ? ` by ${m.result_margin_wickets} wkts` : ''}`, decided: true };
  return { text: m.result_type ? m.result_type[0].toUpperCase() + m.result_type.slice(1) : 'No result recorded', decided: false };
}

/* ---------------------------------------------------------------- pieces */

/** Area sparkline of matches per year (real coverage data). */
function Sparkline({ values }) {
  const w = 320, h = 72;
  if (values.length < 2) return null;
  const max = Math.max(...values, 1);
  const pts = values.map((v, i) => [(i / (values.length - 1)) * w, h - 4 - (v / max) * (h - 10)]);
  const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="h-[72px] w-full" aria-hidden="true">
      <defs><linearGradient id="hero-spark" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="var(--c1)" stopOpacity="0.28" /><stop offset="100%" stopColor="var(--c1)" stopOpacity="0" /></linearGradient></defs>
      <path d={`${line} L${w},${h} L0,${h} Z`} fill="url(#hero-spark)" />
      <path d={line} fill="none" stroke="var(--c1)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="3.5" fill="var(--c1)" stroke="var(--chart-bg)" strokeWidth="2" />
    </svg>
  );
}

function Hero({ c, years, lastYear, prevYear, yoy, formats, activeCount }) {
  const spark = years.slice(-20);
  return (
    <section className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
      <div className="panel-hero flex flex-col justify-between p-6 sm:p-7">
        <div>
          <div className="flex items-center gap-2 text-[13px] font-medium text-slate-400"><Icon name="ball" size={15} className="text-accent" />Matches in the database</div>
          <div className="display-num mt-3 text-[52px] leading-none sm:text-[64px]">{fmtInt(c.total_matches)}</div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            {yoy !== null && <Badge variant={yoy >= 0 ? 'green' : 'red'}><span aria-hidden="true">{yoy >= 0 ? '▲' : '▼'}</span>{Math.abs(yoy).toFixed(0)}% vs {prevYear.year}{lastYear.year === new Date().getFullYear() ? ' (year to date)' : ''}</Badge>}
            {lastYear && <Badge>{fmtInt(lastYear.matches)} in {lastYear.year}</Badge>}
            <Badge variant="indigo">{formats.length} formats</Badge>
          </div>
        </div>
        {spark.length >= 2 && (
          <div className="mt-6">
            <Sparkline values={spark.map(y => y.matches)} />
            <div className="num mt-1 flex justify-between text-2xs text-slate-500"><span>{spark[0].year}</span><span>Matches per year</span><span>{spark[spark.length - 1].year}</span></div>
          </div>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-2">
        <StatCard label="Players indexed" value={fmtInt(c.total_players)} sub="Unique identities" />
        <StatCard label="Teams" value={fmtInt(c.total_teams)} sub="International and franchise" />
        <StatCard label="Competitions" value={fmtInt(c.total_tournaments)} sub={activeCount ? `${activeCount}+ active in last 90 days` : 'Stored tournaments'} />
        <StatCard label="Venues" value={fmtInt(c.total_venues)} sub="Grounds with matches" />
        <StatCard label="Seasons" value={fmtInt(c.seasons?.length)} sub={c.seasons?.length ? `${c.seasons[0]} – ${c.seasons[c.seasons.length - 1]}` : null} />
        <StatCard label="Latest import" value={c.last_ingestion ? new Date(c.last_ingestion).toLocaleDateString('en', { day: 'numeric', month: 'short' }) : null} sub={c.last_ingestion ? new Date(c.last_ingestion).toLocaleTimeString('en', { hour: '2-digit', minute: '2-digit' }) : 'Not recorded'} />
      </div>
    </section>
  );
}

const EXPLORE = ['/players', '/matches', '/simulator', '/tournaments', '/scouting', '/auction'];

/** Quick routes into the major sections (labels and hints from the nav model). */
function Explore() {
  const items = NAV_GROUPS.flatMap(g => g.items).filter(i => EXPLORE.includes(i.to)).sort((a, b) => EXPLORE.indexOf(a.to) - EXPLORE.indexOf(b.to));
  return (
    <nav aria-label="Explore CPI" className="scrollbar-none -mx-4 flex gap-3 overflow-x-auto px-4 pb-1 sm:mx-0 sm:grid sm:grid-cols-3 sm:overflow-visible sm:px-0 xl:grid-cols-6">
      {items.map(i => (
        <Link key={i.to} to={i.to} className="panel card-link group flex w-[11.5rem] shrink-0 flex-col gap-3 p-4 sm:w-auto">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-white/[0.06] text-slate-300"><Icon name={i.icon} size={18} /></span>
          <span>
            <span className="flex items-center justify-between text-[14px] font-semibold tracking-[-0.01em] text-white">{i.label}<Icon name="arrowRight" size={14} className="text-slate-600 transition-[transform,color] duration-200 group-hover:translate-x-0.5 group-hover:text-accent" /></span>
            <span className="mt-0.5 block text-xs text-slate-500">{i.hint}</span>
          </span>
        </Link>
      ))}
    </nav>
  );
}

function RecentMatches({ matches, loading }) {
  return (
    <Panel title="Latest results" subtitle="Most recent matches in the database, newest first." bodyClassName="p-0"
      actions={<Link to="/matches" className="btn btn-ghost btn-xs">All matches <Icon name="arrowRight" size={13} /></Link>}>
      {loading ? <div className="space-y-3 p-4">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-9" />)}</div>
        : !matches?.length ? <EmptyState message="No matches imported yet." hint="Run a Cricsheet sync from Settings." />
        : (
          <ul className="divide-y divide-line-soft">
            {matches.map(m => {
              const r = resultLine(m);
              return (
                <li key={m.id}>
                  <MatchCentreLink matchId={m.id} className="!no-underline">
                    <div className="row-link grid grid-cols-[auto_1fr_auto] items-center gap-x-4 px-5 py-3">
                      <div className="grid h-11 w-11 place-items-center rounded-xl bg-white/[0.05] text-center">
                        <div className="num text-[15px] font-semibold leading-none text-white">{m.start_date?.slice(8, 10)}</div>
                        <div className="-mt-1 text-3xs font-medium text-slate-500">{m.start_date ? new Date(m.start_date).toLocaleString('en', { month: 'short' }) : ''}</div>
                      </div>
                      <div className="min-w-0">
                        <div className="truncate text-[13px] text-slate-100">
                          <span className={m.winner === m.team1 ? 'font-semibold text-white' : 'text-slate-300'}>{m.team1 || 'Team 1'}</span>
                          <span className="mx-1.5 text-slate-600">v</span>
                          <span className={m.winner === m.team2 ? 'font-semibold text-white' : 'text-slate-300'}>{m.team2 || 'Team 2'}</span>
                        </div>
                        <div className="mt-0.5 truncate text-2xs text-slate-500">{m.competition || 'Unlisted competition'}{m.venue ? ` · ${m.venue.split(',')[0]}` : ''}</div>
                      </div>
                      <div className="flex flex-col items-end gap-1">
                        <span className={`hidden text-2xs sm:block ${r.decided ? 'text-pos-soft' : 'text-slate-500'}`}>{r.text}</span>
                        <Badge>{m.match_format}</Badge>
                      </div>
                    </div>
                  </MatchCentreLink>
                </li>
              );
            })}
          </ul>
        )}
    </Panel>
  );
}

function Leaderboard({ title, rows, valueKey, unit, detail, color }) {
  const max = Math.max(1, ...rows.map(r => Number(r[valueKey]) || 0));
  return (
    <div className="min-w-0">
      <div className="mb-2 flex items-baseline justify-between">
        <h4 className="text-[13px] font-semibold text-slate-100">{title}</h4>
        <span className="eyebrow">{unit}</span>
      </div>
      {!rows.length ? <p className="py-6 text-center text-xs text-slate-500">No leaders recorded for this season.</p> : (
        <ol className="space-y-1">
          {rows.map((r, i) => (
            <li key={r.player_id || r.player} className="group rounded-xl px-2 py-1.5 transition-colors hover:bg-white/[0.04]">
              <div className="flex items-center gap-2.5">
                <span className={`num grid h-5 w-5 shrink-0 place-items-center rounded-full text-2xs ${i === 0 ? 'bg-gold/15 font-semibold text-gold-soft' : 'text-slate-500'}`}>{i + 1}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <PlayerLink id={r.player_id} name={r.player} className="truncate text-[13px]" />
                    <span className="num text-[13px] font-semibold text-white">{fmtInt(r[valueKey])}</span>
                  </div>
                  <div className="mt-1 flex items-center gap-2">
                    <div className="h-1 flex-1 overflow-hidden rounded-full bg-[var(--chart-track)]"><div className="chart-hbar h-full rounded-full" style={{ width: `${(Number(r[valueKey]) / max) * 100}%`, backgroundColor: color, animationDelay: `${i * 40}ms` }} /></div>
                    <span className="num shrink-0 text-3xs text-slate-500">{detail(r)}</span>
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function Spotlight({ options }) {
  const [sel, setSel] = useState('');
  const [season, setSeason] = useState('');
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const choice = options.find(o => compKey(o) === sel) || options[0];
  useEffect(() => { setSeason(''); }, [sel]);
  useEffect(() => {
    if (!choice) return undefined;
    let alive = true;
    setState(s => ({ ...s, loading: true, error: null }));
    getTournamentDetail({ name: choice.name, format: choice.format, gender: choice.gender, season })
      .then(d => alive && setState({ loading: false, data: d, error: null }))
      .catch(e => alive && setState({ loading: false, data: null, error: e.message }));
    return () => { alive = false; };
  }, [choice?.name, choice?.format, choice?.gender, season]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!choice) return null;
  const d = state.data;
  const limited = ['T20', 'T20I', 'ODI', 'ODM'].includes(choice.format);
  const trends = d?.season_trends || [];
  const decided = d?.matches?.filter(m => m.winner).length ?? 0;

  return (
    <section className="panel min-w-0 overflow-hidden">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-line-soft bg-[radial-gradient(80%_160%_at_0%_0%,rgb(var(--accent)/0.08),transparent_60%)] px-5 py-4 sm:px-6">
        <div className="min-w-0">
          <div className="mb-1 text-xs font-semibold text-accent">Competition spotlight</div>
          <h3 className="truncate text-[19px] font-semibold tracking-[-0.022em] text-white">{choice.name} <span className="font-normal text-slate-500">· {d?.season || '…'}</span></h3>
          <p className="mt-0.5 text-2xs text-slate-500">{FORMAT_NAME[choice.format] || choice.format} · {choice.gender === 'female' ? 'Women' : 'Men'} · {fmtInt(choice.matches)} matches stored across {choice.seasons?.length || 0} seasons</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select aria-label="Spotlight competition" value={compKey(choice)} onChange={setSel} className="h-8 w-64 max-w-full text-xs"
            options={options.map(o => ({ id: compKey(o), label: `${o.name} · ${o.format}${o.gender === 'female' ? ' (W)' : ''}` }))} />
          {d?.seasons?.length > 1 && <Select aria-label="Season" value={season || d.season} onChange={setSeason} className="h-8 w-28 text-xs" options={d.seasons} />}
          <Link to={tournamentUrl(choice, season)} className="btn btn-secondary btn-sm">Open <Icon name="arrowRight" size={13} /></Link>
        </div>
      </div>
      {state.error ? <div className="p-4"><ErrorState message={state.error} /></div>
        : state.loading && !d ? <div className="grid gap-4 p-5 lg:grid-cols-3">{Array.from({ length: 3 }, (_, i) => <div key={i} className="space-y-2.5">{Array.from({ length: 6 }, (_, k) => <Skeleton key={k} className="h-7" />)}</div>)}</div>
        : (
          <div className={`grid gap-x-6 gap-y-6 p-4 transition-opacity sm:p-5 lg:grid-cols-[1.45fr_1fr_1fr] ${state.loading ? 'opacity-50' : ''}`}>
            <div className="min-w-0">
              <div className="mb-2 flex items-baseline justify-between">
                <h4 className="text-[13px] font-semibold text-slate-100">Standings</h4>
                <span className="eyebrow">{decided}/{d.matches?.length || 0} decided</span>
              </div>
              {!d.standings?.length ? <p className="py-6 text-center text-xs text-slate-500">No standings for this season.</p> : (
                <table className="w-full text-[13px]">
                  <thead><tr className="text-2xs text-slate-500">
                    <th className="pb-1.5 text-left font-semibold">Team</th><th className="pb-1.5 text-right font-semibold">P</th><th className="pb-1.5 text-right font-semibold">W</th><th className="pb-1.5 text-right font-semibold">NRR</th><th className="pb-1.5 text-right font-semibold">Pts</th>
                  </tr></thead>
                  <tbody>
                    {d.standings.slice(0, 8).map(t => (
                      <tr key={t.team_id || t.team} className="border-t border-line-soft">
                        <td className="max-w-0 py-1.5 pr-2"><div className="flex items-center gap-2"><span className="num w-3 text-2xs text-slate-500">{t.position}</span><span className="truncate text-slate-200">{t.team}</span></div></td>
                        <td className="num py-1.5 text-right text-slate-400">{t.played}</td>
                        <td className="num py-1.5 text-right text-slate-300">{t.won}</td>
                        <td className={`num py-1.5 text-right ${t.net_run_rate > 0 ? 'text-pos' : t.net_run_rate < 0 ? 'text-neg' : 'text-slate-400'}`}>{t.net_run_rate == null ? '—' : `${t.net_run_rate > 0 ? '+' : ''}${fmtDec(t.net_run_rate, 3)}`}</td>
                        <td className="num py-1.5 text-right font-semibold text-white">{t.points}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <Leaderboard title="Leading run scorers" unit="Runs" rows={(d.leading_batters || []).slice(0, 6)} valueKey="runs" color={PALETTE[0]}
              detail={r => `${r.innings} inns · avg ${fmtDec(r.average, 1)} · SR ${fmtDec(r.strike_rate, 1)}`} />
            <Leaderboard title="Leading wicket takers" unit="Wickets" rows={(d.leading_bowlers || []).slice(0, 6)} valueKey="wickets" color={PALETTE[1]}
              detail={r => <>{r.overs} ov · econ {fmtDec(r.economy, 2)} · best {r.best ? <MatchLink id={r.best_match_id}>{r.best}</MatchLink> : '—'}</>} />
          </div>
        )}
      {trends.length >= 2 && (
        <div className="border-t border-line">
          <MultiSeriesLine className="!rounded-none !border-0 !shadow-none" categorical height={220}
            title={limited ? 'Scoring by season' : 'Run rate by season'}
            subtitle={limited ? 'Average first- and second-innings totals per season in this competition.' : 'Runs per over across each season of this competition.'}
            yLabel={limited ? 'Average total' : 'Runs per over'} yFormatter={v => (limited ? Math.round(v) : fmtDec(v, 2))}
            series={limited ? [
              { name: '1st innings', color: PALETTE[0], points: trends.map(t => ({ x: t.season, y: t.average_first_innings, label: `${t.season} · ${t.matches} matches` })) },
              { name: '2nd innings', color: PALETTE[3], points: trends.map(t => ({ x: t.season, y: t.average_second_innings, label: `${t.season} · ${t.matches} matches` })) },
            ] : [{ name: 'Run rate', color: PALETTE[0], points: trends.map(t => ({ x: t.season, y: t.run_rate, label: `${t.season} · ${t.matches} matches` })) }]}
            yMin={limited ? Math.floor(Math.min(...trends.flatMap(t => [t.average_first_innings, t.average_second_innings]).filter(v => v != null)) * 0.85 / 10) * 10 : 0} />
        </div>
      )}
    </section>
  );
}

function ActiveCompetitions({ rows, through }) {
  const navigate = useNavigate();
  return (
    <Panel title="Most active competitions" subtitle={`Competitions with a match in the 90 days to ${through || 'the latest match'}, by matches stored.`} bodyClassName="p-0">
      {!rows.length ? <EmptyState message="No recent competition activity." /> : (
        <ul className="divide-y divide-line-soft">
          {rows.map(t => (
            <li key={compKey(t)} className="relative">
              {t.last_match_id && <MatchLink id={t.last_match_id} title={`Open the latest ${t.name} match`} className="absolute bottom-3 right-5 z-[1] text-3xs text-slate-500">latest {t.last_match}</MatchLink>}
              <button onClick={() => navigate(tournamentUrl(t))} className="row-link flex w-full items-center gap-3 px-5 py-3 text-left">
                <span className="dot" style={{ backgroundColor: FORMAT_COLOR[t.format] || PALETTE[6] }} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] text-slate-200">{t.name}</span>
                  <span className="block truncate text-2xs text-slate-500">{t.format}{t.gender === 'female' ? ' · Women' : ''} · {t.seasons?.[0]}</span>
                </span>
                <span className="num text-[13px] font-medium text-slate-300">{fmtInt(t.matches)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

/* ----------------------------------------------------------------- page */

export default function Dashboard() {
  const { data: c, loading, error, refetch } = useApi(getCoverage);
  const { data: recent, loading: recentLoading } = useApi(() => getMatches({ page: 1, page_size: 9 }));
  const { data: tourn } = useApi(getTournaments);

  const latest = recent?.matches?.[0]?.start_date;
  const { spotlight, active, through } = useMemo(() => {
    const list = tourn?.tournaments || [];
    const ref = list.reduce((m, t) => (t.last_match > m ? t.last_match : m), '');
    const recentList = list.filter(t => ref && daysBetween(ref, t.last_match) <= 90).sort((a, b) => b.matches - a.matches);
    const spot = list.filter(t => t.matches >= 40 && ref && daysBetween(ref, t.last_match) <= 180).sort((a, b) => b.last_match.localeCompare(a.last_match) || b.matches - a.matches).slice(0, 14);
    return { spotlight: spot, active: recentList.slice(0, 8), through: ref };
  }, [tourn]);

  if (loading) return <><PageHeader eyebrow="Overview" title="Ball-by-ball cricket archive" subtitle="Loading dataset state…" /><DashboardSkeleton /></>;
  if (error) return <ErrorState message={error} onRetry={refetch} />;

  const years = c.year_counts || [];
  const lastYear = years[years.length - 1];
  const prevYear = years[years.length - 2];
  const yoy = lastYear && prevYear && prevYear.matches ? ((lastYear.matches - prevYear.matches) / prevYear.matches) * 100 : null;
  const formats = Object.entries(c.formats || {}).sort((a, b) => b[1] - a[1]);
  const formatTotal = formats.reduce((a, [, n]) => a + n, 0);

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Overview" title="Ball-by-ball cricket archive"
        subtitle={`Every delivery across ${formats.length} formats and ${fmtInt(c.total_tournaments)} competitions${latest ? `, with matches through ${latest}` : ''}.`}
        actions={<>
          <Button as={Link} to="/players" variant="secondary" size="sm" icon="players">Explore players</Button>
          <Button as={Link} to="/simulator" variant="primary" size="sm" icon="simulator">Simulate a match</Button>
        </>} />

      <Hero c={c} years={years} lastYear={lastYear} prevYear={prevYear} yoy={yoy} formats={formats} activeCount={active.length} />

      <Explore />

      <div className="grid gap-5 xl:grid-cols-3">
        <ColumnChart className="xl:col-span-2" height={250}
          title="Match volume by year"
          subtitle={`Matches with a recorded start date per calendar year${yoy !== null ? `. ${lastYear.year} is ${yoy >= 0 ? 'up' : 'down'} ${Math.abs(yoy).toFixed(0)}% on ${prevYear.year}${lastYear.year === new Date().getFullYear() ? ' so far' : ''}` : ''}.`}
          data={years.slice(-20).map(y => ({ label: `'${String(y.year).slice(-2)}`, value: y.matches, tip: null, color: y === lastYear ? PALETTE[3] : PALETTE[0] }))
            .map((d, i, arr) => ({ ...d, tip: <div><div className="mb-1 border-b border-line pb-1 font-semibold text-white">{years.slice(-20)[i].year}</div><div className="num">{fmtInt(d.value)} matches</div>{i > 0 && arr[i - 1].value ? <div className="num text-slate-400">{((d.value - arr[i - 1].value) / arr[i - 1].value * 100).toFixed(1)}% vs prior year</div> : null}</div> }))}
          formatter={v => fmtInt(v)} barLabel="Matches" />
        <BarChart title="Format mix" subtitle="Share of all stored matches by format."
          data={formats.map(([f, n]) => ({ label: FORMAT_NAME[f] || f, value: n, color: FORMAT_COLOR[f], detail: `${((n / formatTotal) * 100).toFixed(1)}% of matches` }))}
          formatter={v => `${fmtInt(v)} · ${((v / formatTotal) * 100).toFixed(0)}%`} unit="Matches" />
      </div>

      {spotlight.length > 0 ? <Spotlight options={spotlight} /> : tourn && <Panel title="Competition spotlight"><EmptyState message="No competition with enough recent matches to spotlight." /></Panel>}

      <div className="grid gap-5 xl:grid-cols-3">
        <div className="xl:col-span-2"><RecentMatches matches={recent?.matches} loading={recentLoading} /></div>
        {tourn ? <ActiveCompetitions rows={active} through={through} />
          : <Panel title="Most active competitions"><div className="space-y-3">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-8" />)}</div></Panel>}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-2xs text-slate-500">
        {c.last_ingestion && <span>Last ingestion {new Date(c.last_ingestion).toLocaleString()}</span>}
        <span className="flex flex-wrap gap-1">{formats.map(([f]) => <Badge key={f}>{f}</Badge>)}</span>
      </div>
    </div>
  );
}
