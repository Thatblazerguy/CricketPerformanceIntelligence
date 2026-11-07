import { useState } from 'react';
import { Link } from 'react-router-dom';
import { getMatches } from '../../services/api';
import { LoadingSpinner, ErrorState, EmptyState, PageHeader, Badge } from '../../components/ui';

const inputClass = 'bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200';

export default function Matches() {
  const [filters, setFilters] = useState({format:'',search:'',competition:'',season:'',year_from:'',year_to:'',team:'',opponent:'',venue:'',country:'',result:'',start_date:'',end_date:''});
  const [submitted, setSubmitted] = useState(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const update = (key, value) => setFilters(prev => ({...prev, [key]:value}));
  async function search(e, nextPage=1) {
    e?.preventDefault();
    const applied = submitted || filters;
    if (e) setSubmitted({...filters});
    const query = e ? filters : applied;
    setLoading(true); setError(null); setPage(nextPage);
    try {
      const payload = Object.fromEntries(Object.entries({...query,page:nextPage,page_size:pageSize}).filter(([,v])=>v!==''&&v!=null));
      setData(await getMatches(payload));
    } catch(err) { setError(err.message || 'Could not load matches.'); }
    finally { setLoading(false); }
  }
  const maxPage = data ? Math.max(1, Math.ceil(data.total/pageSize)) : 1;
  return <div className="space-y-6">
    <PageHeader title="Matches" subtitle="Search imported match summaries. Innings and delivery detail is requested only when opened." />
    <form onSubmit={search} className="grid grid-cols-2 md:grid-cols-4 gap-3 rounded-xl border border-slate-800 bg-slate-900 p-4">
      <select className={inputClass} value={filters.format} onChange={e=>update('format',e.target.value)}><option value="">All formats</option>{['Test','ODI','ODM','T20','T20I','MDM'].map(x=><option key={x}>{x}</option>)}</select>
      <input className={inputClass} placeholder="Team, tournament, venue or ID" value={filters.search} onChange={e=>update('search',e.target.value)} />
      <input className={inputClass} placeholder="Competition / tournament (exact)" value={filters.competition} onChange={e=>update('competition',e.target.value)} />
      <input className={inputClass} placeholder="Season" value={filters.season} onChange={e=>update('season',e.target.value)} />
      <input className={inputClass} placeholder="Team" value={filters.team} onChange={e=>update('team',e.target.value)} />
      <input className={inputClass} placeholder="Opponent" value={filters.opponent} onChange={e=>update('opponent',e.target.value)} />
      <input className={inputClass} placeholder="Venue" value={filters.venue} onChange={e=>update('venue',e.target.value)} />
      <input className={inputClass} placeholder="Country" value={filters.country} onChange={e=>update('country',e.target.value)} />
      <input className={inputClass} placeholder="Result type (win/tie/no result)" value={filters.result} onChange={e=>update('result',e.target.value)} />
      <input className={inputClass} type="number" placeholder="Year from" value={filters.year_from} onChange={e=>update('year_from',e.target.value)} />
      <input className={inputClass} type="number" placeholder="Year to" value={filters.year_to} onChange={e=>update('year_to',e.target.value)} />
      <label className="text-xs text-slate-500">Start date<input className={`${inputClass} block w-full mt-1`} type="date" value={filters.start_date} onChange={e=>update('start_date',e.target.value)} /></label>
      <label className="text-xs text-slate-500">End date<input className={`${inputClass} block w-full mt-1`} type="date" value={filters.end_date} onChange={e=>update('end_date',e.target.value)} /></label>
      <button className="bg-indigo-600 hover:bg-indigo-500 rounded px-4 py-2 text-sm text-white">Search matches</button>
      <button type="button" className="text-slate-400 text-sm" onClick={()=>{setFilters({format:'',search:'',competition:'',season:'',year_from:'',year_to:'',team:'',opponent:'',venue:'',country:'',result:'',start_date:'',end_date:''});setSubmitted(null);setData(null);setError(null);}}>Reset</button>
    </form>
    {!submitted && !loading && <EmptyState message="Apply filters or search to browse match summaries." />}
    {loading && <LoadingSpinner message="Searching match summaries…" />}
    {error && <><ErrorState message={error} /><button onClick={()=>search(null,page)} className="text-sm text-indigo-300">Retry search</button></>}
    {data && !loading && <>
      <div className="flex justify-between items-center text-xs text-slate-400"><span>{data.total.toLocaleString()} matches · page {page} of {maxPage}</span><label>Rows <select className={inputClass} value={pageSize} onChange={e=>{setPageSize(+e.target.value);setTimeout(()=>search(null,1),0);}}><option>25</option><option>50</option><option>100</option></select></label></div>
      {data.matches.length===0 ? <EmptyState message="No matches found for these filters."/> : <div className="overflow-x-auto rounded-xl border border-slate-800"><table className="w-full text-left text-sm"><thead className="bg-slate-800 text-slate-400"><tr>{['Date','Competition','Teams','Venue','Result','Format','Details'].map(h=><th className="p-3" key={h}>{h}</th>)}</tr></thead><tbody>{data.matches.map(m=><tr key={m.id} className="border-t border-slate-800 text-slate-300"><td className="p-3 whitespace-nowrap">{m.start_date}</td><td className="p-3">{m.competition||'—'}</td><td className="p-3">{m.team1} vs {m.team2}</td><td className="p-3">{m.venue||'—'}</td><td className="p-3">{m.winner?`${m.winner} won`:m.result_type||'—'}</td><td className="p-3"><Badge>{m.match_format}</Badge></td><td className="p-3"><Link to={`/matches/${m.id}`} className="text-indigo-300">Open</Link></td></tr>)}</tbody></table></div>}
      <div className="flex justify-between"><button disabled={page<=1} onClick={()=>search(null,page-1)} className="text-slate-300 disabled:opacity-30">← Previous</button><button disabled={page>=maxPage} onClick={()=>search(null,page+1)} className="text-slate-300 disabled:opacity-30">Next →</button></div>
    </>}
  </div>;
}
