import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getMatchDetails } from '../../services/api';
import { ErrorState, LoadingSpinner, PageHeader } from '../../components/ui';

export default function MatchDetail() {
  const { id } = useParams();
  const [data, setData] = useState(null); const [error, setError] = useState(null); const [loading, setLoading] = useState(true);
  async function load() { setLoading(true); setError(null); try { setData(await getMatchDetails(id)); } catch(e) { setError(e.message || 'Could not load match detail.'); } finally { setLoading(false); } }
  useEffect(() => { load(); }, [id]);
  if (loading) return <LoadingSpinner message="Loading innings and deliveries…"/>;
  if (error) return <div><ErrorState message={error}/><button onClick={load} className="text-indigo-300">Retry</button></div>;
  const m=data.match;
  return <div className="space-y-5"><Link to="/matches" className="text-sm text-indigo-300">← Matches</Link><PageHeader title={`${m.team1} vs ${m.team2}`} subtitle={`${m.competition||'Match'} · ${m.start_date} · ${m.venue||'Venue unavailable'} · ${m.match_format}`}/>
    {data.innings.map(inn=><section key={inn.innings_number} className="rounded-xl border border-slate-800 overflow-hidden"><h2 className="p-3 bg-slate-900 text-white">Innings {inn.innings_number}{inn.batting_team?` · ${inn.batting_team}`:''}{inn.is_super_over?' · Super Over':''}</h2><div className="max-h-[65vh] overflow-auto"><table className="w-full text-xs"><thead className="sticky top-0 bg-slate-800 text-slate-400"><tr>{['Over','Ball','Batter','Bowler','Runs / extras','Wickets','Phase'].map(x=><th className="p-2 text-left" key={x}>{x}</th>)}</tr></thead><tbody>{inn.deliveries.map((d,i)=><tr className="border-t border-slate-800 text-slate-300" key={i}><td className="p-2">{d.over}</td><td className="p-2">{d.ball}{!d.legal?' ·':''}</td><td className="p-2">{d.batter||'—'}</td><td className="p-2">{d.bowler||'—'}</td><td className="p-2">{d.total_runs}{d.extra_types?.length?` · ${d.extra_types.map(e=>`${e.type} ${e.runs}`).join(', ')}`:''}</td><td className="p-2">{d.wickets?.map(w=>`${w.player_out} (${w.kind})`).join(', ')||'—'}</td><td className="p-2">{d.phase||'—'}</td></tr>)}</tbody></table></div></section>)}
  </div>;
}
