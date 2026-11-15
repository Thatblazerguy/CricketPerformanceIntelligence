/**
 * Auction Intelligence. The original scenario workbench (retention list and
 * player-pool upload, rules, run-scenario analysis, predicted XI) remains the
 * default view; the analytical sections below it share its scenarios.
 *
 * Every section works on one *auction context*: a completed auction replayed
 * with only pre-auction information (models retrained on earlier seasons), or
 * a user scenario uploaded in "Data & scenarios". All analytics are computed
 * server-side by the /auction API.
 */
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { auctionAnalytics } from '../../services/api';
import { Badge, ErrorState, LoadingSpinner, PageHeader, PanelSkeleton, Select, Tabs } from '../../components/ui';
import { PlayerDrawer } from './auctionUi';

const MarketTab = lazy(() => import('./MarketTab'));
const ValuationTab = lazy(() => import('./ValuationTab'));
const FranchiseTab = lazy(() => import('./FranchiseTab'));
const SimulatorTab = lazy(() => import('./SimulatorTab'));
const OptimizerTab = lazy(() => import('./OptimizerTab'));
const HistoryTab = lazy(() => import('./HistoryTab'));
const BacktestTab = lazy(() => import('./BacktestTab'));
const DataTab = lazy(() => import('./DataTab'));
const ScenarioWorkbench = lazy(() => import('./ScenarioWorkbench'));

const SECTIONS = [
  { id: 'scenarios', label: 'Scenario workbench' },
  { id: 'market', label: 'Market intelligence' },
  { id: 'valuation', label: 'Player valuation' },
  { id: 'franchise', label: 'Franchise strategy' },
  { id: 'simulator', label: 'Auction simulator' },
  { id: 'optimizer', label: 'Purse optimizer' },
  { id: 'history', label: 'Historical auctions' },
  { id: 'backtest', label: 'Backtesting & models' },
  { id: 'data', label: 'Data coverage' },
];
const CONTEXT_FREE = new Set(['scenarios', 'history', 'backtest', 'data']);

export default function AuctionIntelligence() {
  const [params, setParams] = useSearchParams();
  const tab = SECTIONS.some(s => s.id === params.get('tab')) ? params.get('tab') : 'scenarios';
  const [contexts, setContexts] = useState(null);
  const [strategies, setStrategies] = useState([]);
  const [error, setError] = useState('');
  const [drawer, setDrawer] = useState(null);
  const context = params.get('ctx') || '';

  const loadContexts = useCallback(() => auctionAnalytics.contexts().then(d => {
    setContexts(d.contexts); setStrategies(d.strategies);
    if (!params.get('ctx') && d.contexts.length) {
      const first = d.contexts.find(c => c.simulatable && c.key.startsWith('season:')) || d.contexts[0];
      setParams(p => { const n = new URLSearchParams(p); n.set('ctx', first.key); return n; }, { replace: true });
    }
  }).catch(e => setError(e.message)), []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { loadContexts(); }, [loadContexts]);

  const setTab = id => setParams(p => { const n = new URLSearchParams(p); n.set('tab', id); return n; });
  const setContext = key => setParams(p => { const n = new URLSearchParams(p); n.set('ctx', key); return n; });
  const current = useMemo(() => contexts?.find(c => c.key === context), [contexts, context]);
  const openPlayer = useCallback(key => setDrawer(key), []);

  const meta = current && !CONTEXT_FREE.has(tab) && (
    <>
      <Badge variant="indigo">{current.key.startsWith('season:') ? 'Historical replay' : 'Scenario'}</Badge>
      {current.auction_date && <Badge>Auction {current.auction_date}</Badge>}
      {current.pool_complete === false && <Badge variant="amber">Sold-only pool</Badge>}
      {current.pool_complete && <Badge variant="green">Full pool incl. unsold</Badge>}
      <Badge>{current.pool_recorded} players · {current.franchises} franchises</Badge>
    </>
  );

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Recruitment" title="Auction Intelligence"
        subtitle={tab === 'scenarios'
          ? 'Upload the complete retention list and auction player pool. Franchise records are created from the retention file.'
          : "What players are worth, who will compete for them, what each purchase costs in future options, and whether CPI's own predictions held up in past auctions."}
        meta={meta}
        actions={!CONTEXT_FREE.has(tab) && contexts && (
          <label className="flex flex-col gap-1.5">
            <span className="pl-1 text-2xs font-medium text-slate-500">Auction context</span>
            <Select value={context} onChange={setContext} className="min-w-[17rem]"
              options={contexts.map(c => ({ id: c.key, label: c.label + (c.key.startsWith('season:') && !c.simulatable ? ' · purse unknown' : '') }))} />
          </label>
        )} />
      <Tabs value={tab} onChange={setTab} tabs={SECTIONS} />
      {error && <ErrorState message={error} onRetry={loadContexts} />}
      {!contexts && !error && <LoadingSpinner message="Loading auction contexts…" />}
      {contexts && (
        <Suspense fallback={<PanelSkeleton rows={6} />}>
          {tab === 'scenarios' && <ScenarioWorkbench onChanged={loadContexts} />}
          {tab === 'market' && context && <MarketTab context={context} onPlayer={openPlayer} />}
          {tab === 'valuation' && context && <ValuationTab context={context} onPlayer={openPlayer} />}
          {tab === 'franchise' && context && <FranchiseTab context={context} onPlayer={openPlayer} />}
          {tab === 'simulator' && context && <SimulatorTab context={context} contextInfo={current} strategies={strategies} onPlayer={openPlayer} />}
          {tab === 'optimizer' && context && <OptimizerTab context={context} onPlayer={openPlayer} />}
          {tab === 'history' && <HistoryTab />}
          {tab === 'backtest' && <BacktestTab />}
          {tab === 'data' && <DataTab onChanged={loadContexts} />}
        </Suspense>
      )}
      <PlayerDrawer context={context} playerKey={drawer} onClose={() => setDrawer(null)} />
    </div>
  );
}
