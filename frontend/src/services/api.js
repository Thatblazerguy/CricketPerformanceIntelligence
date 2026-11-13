/**
 * CPI API Client
 * Central service for all backend API calls.
 * All cricket statistics come from the backend — never calculated in React.
 */

// In Vite development, use its same-origin proxy to avoid localhost/IPv6 and CORS
// differences between the browser and the backend listener. Production can set VITE_API_URL.
const BASE_URL = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? '' : 'http://127.0.0.1:8000') + '/api/v1';

async function request(path, options = {}) {
  const url = `${BASE_URL}${path}`;
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  const response = await fetch(url, {
    headers: { ...(isFormData ? {} : { 'Content-Type': 'application/json' }), ...options.headers },
    ...options,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    const detail = error.detail;
    const message = typeof detail === 'string' ? detail
      : Array.isArray(detail?.errors) ? detail.errors.join('; ')
      : Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join('; ')
      : detail ? JSON.stringify(detail) : '';
    throw new Error(message || `API error ${response.status}`);
  }

  return response.json();
}

// --- Health ---
export const getHealth = () => request('/health');
export const getCoverage = () => request('/dataset/coverage');

// --- Players ---
export const getPlayers = (params = {}) => {
  const q = new URLSearchParams(params).toString();
  return request(`/players${q ? `?${q}` : ''}`);
};
export const getPlayerFilterMetadata = () => request('/players/filter-metadata');
export const getPlayerPerformance = (params = {}) => {
  // Clean empty or null params
  const cleanParams = {};
  for (const [key, val] of Object.entries(params)) {
    if (val !== undefined && val !== null && val !== '') {
      cleanParams[key] = val;
    }
  }
  const q = new URLSearchParams(cleanParams).toString();
  return request(`/players/performance${q ? `?${q}` : ''}`);
};
export const getPlayer = (id) => request(`/players/${id}`);
export const getPlayerAnalytics = (id, params = {}) => {
  const cleanParams = {};
  for (const [key, val] of Object.entries(params)) {
    if (val !== undefined && val !== null && val !== '') {
      cleanParams[key] = val;
    }
  }
  const q = new URLSearchParams(cleanParams).toString();
  return request(`/players/${id}/analytics${q ? `?${q}` : ''}`);
};
export const getPlayerBatting = (id, params = {}) => {
  const q = new URLSearchParams(params).toString();
  return request(`/players/${id}/batting${q ? `?${q}` : ''}`);
};
export const getPlayerBowling = (id, params = {}) => {
  const q = new URLSearchParams(params).toString();
  return request(`/players/${id}/bowling${q ? `?${q}` : ''}`);
};
export const getPlayerPhases = (id, params = {}) => {
  const q = new URLSearchParams(params).toString();
  return request(`/players/${id}/phases${q ? `?${q}` : ''}`);
};
export const getPlayerSimilar = (id, params = {}) => {
  const q = new URLSearchParams(params).toString();
  return request(`/players/${id}/similar${q ? `?${q}` : ''}`);
};
export const getPlayerSimilarBowlers = (id, params = {}) => {
  const q = new URLSearchParams(params).toString();
  return request(`/players/${id}/similar-bowlers${q ? `?${q}` : ''}`);
};
export const getPlayerSimilarAllRounders = (id, params = {}) => {
  const q = new URLSearchParams(params).toString();
  return request(`/players/${id}/similar-all-rounders${q ? `?${q}` : ''}`);
};

// --- Matches ---
export const getMatches = (params = {}) => {
  const q = new URLSearchParams(params).toString();
  return request(`/matches${q ? `?${q}` : ''}`);
};
export const getMatch = (id) => request(`/matches/${id}`);
export const getMatchDetails = (id) => request(`/matches/${id}/details`);
export const getMatchWinProbability = (id) => request(`/matches/${id}/win-probability`);
export const getPlayerWinProbabilityImpact = (id) => request(`/players/${id}/impact`);
export const getWinProbabilityCoverage = () => request('/win-probability/coverage');
export const simulateInnings = (state) => request('/simulator/simulate', { method: 'POST', body: JSON.stringify({ state }) });
export const compareBattingOrders = (state, batting_orders) => request('/simulator/batting-order', { method: 'POST', body: JSON.stringify({ state, batting_orders }) });
export const compareBowlingOptions = (state, options, overs_bowled = {}) => request('/simulator/bowling-options', { method: 'POST', body: JSON.stringify({ state, options, overs_bowled }) });
export const analyseLiveMatchScreenshot = (file) => { const form = new FormData(); form.append('file', file); return request('/simulator/analyse-live-match', { method: 'POST', body: form, headers: {} }); };
export const getSimulatorOptions = () => request('/simulator/options');
export const getSimulatorWinProbability = (state) => request('/simulator/win-probability', { method: 'POST', body: JSON.stringify({ state }) });
// Full-match simulation: validate the two XIs, then run one match or a Monte Carlo batch as a background job.
export const getMatchSimOptions = (format = 'T20') => request(`/simulator/match/options?format=${encodeURIComponent(format)}`);
export const validateMatchSim = (body) => request('/simulator/match/validate', { method: 'POST', body: JSON.stringify(body) });
export const startMatchSim = (body) => request('/simulator/match/run', { method: 'POST', body: JSON.stringify(body) });
export const startMonteCarloSim = (body) => request('/simulator/match/monte-carlo', { method: 'POST', body: JSON.stringify(body) });
export const getSimJob = (id) => request(`/simulator/jobs/${encodeURIComponent(id)}`);

// --- Matchups ---
export const getMatchup = (batterId, bowlerId, params = {}) => {
  const q = new URLSearchParams(params).toString();
  return request(`/matchups/${batterId}/${bowlerId}${q ? `?${q}` : ''}`);
};

// Enhanced matchup endpoints
export const getMatchupFilterMetadata = () => request('/matchups/filter-metadata');
export const getMatchupSummary = (batterId, bowlerId, params = {}) => {
  const q = new URLSearchParams(params).toString();
  return request(`/matchups/${batterId}/${bowlerId}/summary${q ? `?${q}` : ''}`);
};
export const getMatchupDismissals = (batterId, bowlerId, params = {}) => {
  const q = new URLSearchParams(params).toString();
  return request(`/matchups/${batterId}/${bowlerId}/dismissals${q ? `?${q}` : ''}`);
};
export const getMatchupByMatch = (batterId, bowlerId, params = {}) => {
  const q = new URLSearchParams(params).toString();
  return request(`/matchups/${batterId}/${bowlerId}/by-match${q ? `?${q}` : ''}`);
};
export const getMatchupByOver = (batterId, bowlerId, params = {}) => {
  const q = new URLSearchParams(params).toString();
  return request(`/matchups/${batterId}/${bowlerId}/by-over${q ? `?${q}` : ''}`);
};
export const getMatchupTrends = (batterId, bowlerId, params = {}) => {
  const q = new URLSearchParams(params).toString();
  return request(`/matchups/${batterId}/${bowlerId}/trends${q ? `?${q}` : ''}`);
};

// --- Venues ---
export const getVenues = (format = 'T20') => request(`/venues?format=${encodeURIComponent(format)}`);
export const getGroundAnalytics = (venueId, format = 'T20', params = {}) => {
  const q = new URLSearchParams({ format, ...params }).toString();
  return request(`/venues/${encodeURIComponent(venueId)}/ground-analytics?${q}`);
};

// --- Teams ---
export const getTeams = () => request('/teams');
export const getTeamStats = (id, params = {}) => {
  const q = new URLSearchParams(params).toString();
  return request(`/teams/${id}${q ? `?${q}` : ''}`);
};

// --- Scouting ---
export const scoutingSearch = (payload) =>
  request('/scouting/search', { method: 'POST', body: JSON.stringify(payload) });
export const getScoutingOptions = () => request('/scouting/options');

// --- Auction Intelligence ---
export const getAuctionScenarios = () => request('/auction/scenarios');
export const createAuctionScenario = (payload) => request('/auction/scenarios', {
  method: 'POST', body: JSON.stringify(payload),
});
export const getAuctionScenario = (id) => request(`/auction/scenarios/${id}`);
export const addAuctionTeam = (id, payload) => request(`/auction/scenarios/${id}/teams`, {
  method: 'POST', body: JSON.stringify(payload),
});
export const getAuctionTeams = (id) => request(`/auction/scenarios/${id}/teams`);
export const runAuctionScenario = (id) => request(`/auction/scenarios/${id}/run`, { method: 'POST' });
export const previewAuctionPool = (id, payload) => request(`/auction/scenarios/${id}/player-pool/preview`, {
  method: 'POST', body: JSON.stringify(payload),
});
export const importAuctionPool = (id, payload) => request(`/auction/scenarios/${id}/player-pool/import`, {
  method: 'POST', body: JSON.stringify(payload),
});
export const previewAuctionPoolCsv = (id, file) => {
  const body = new FormData(); body.append('file', file);
  return request(`/auction/scenarios/${id}/player-pool/preview-csv`, { method: 'POST', body });
};
export const importAuctionPoolCsv = (id, file) => {
  const body = new FormData(); body.append('file', file);
  return request(`/auction/scenarios/${id}/player-pool/import-csv`, { method: 'POST', body });
};
export const previewAuctionRetentionsCsv = (id, file) => {
  const body = new FormData(); body.append('file', file);
  return request(`/auction/scenarios/${id}/retentions/preview-csv`, { method: 'POST', body });
};
export const importAuctionRetentionsCsv = (id, file) => {
  const body = new FormData(); body.append('file', file);
  return request(`/auction/scenarios/${id}/retentions/import-csv`, { method: 'POST', body });
};
export const previewAuctionHistoryCsv = (file, sourceName) => {
  const body = new FormData(); body.append('file', file); body.append('source_name', sourceName);
  return request('/auction/history/preview-csv', { method: 'POST', body });
};
export const importAuctionHistoryCsv = (file, sourceName, sourceUrl = '') => {
  const body = new FormData(); body.append('file', file); body.append('source_name', sourceName);
  if (sourceUrl) body.append('source_url', sourceUrl);
  return request('/auction/history/import-csv', { method: 'POST', body });
};
export const importBundledAuctionSources = () => request('/auction/history/import-bundled-sources', { method: 'POST' });
export const getAuctionHistorySummary = () => request('/auction/history/summary');
export const trainAuctionPriceModel = () => request('/auction/models/train-price', { method: 'POST' });
export const parseAuctionRules = (id, file) => { const body = new FormData(); body.append('file', file); return request(`/auction/scenarios/${id}/rules/parse`, { method: 'POST', body }); };
export const confirmAuctionRules = (id, rules) => request(`/auction/scenarios/${id}/rules`, { method: 'PUT', body: JSON.stringify({ rules }) });
export const generateAuctionXI = (id, team_id, style) => request(`/auction/scenarios/${id}/predicted-xi`, { method: 'POST', body: JSON.stringify({ team_id, style }) });

// --- Ingestion ---
export const triggerIngestion = (limit) =>
  request('/ingestion/run-sync', { method: 'POST', ...(limit ? { body: JSON.stringify({ limit }) } : {}) });

// --- Playing XI ---
export const resolveXi = (data) => request('/xi/resolve', { method: 'POST', body: JSON.stringify(data) });
export const uploadXiFile = (file) => {
  const body = new FormData();
  body.append('file', file);
  return request('/xi/upload-file', { method: 'POST', body, headers: {} });
};
export const getXiPresets = () => request('/xi/presets');
export const searchPlayerForXi = (q) => request(`/xi/search-player?q=${encodeURIComponent(q)}`);

// --- Data Sync / Settings (Cricsheet automatic synchronisation) ---
export const getDataSyncStatus = () => request('/data-sync/status');
export const getDataSyncHistory = (page = 1, pageSize = 20) =>
  request(`/data-sync/history?page=${page}&page_size=${pageSize}`);
export const triggerDataSync = () => request('/data-sync/trigger', { method: 'POST' });
export const getDataSyncHealth = () => request('/data-sync/health');
export const updateDataSyncSettings = (settings) =>
  request('/data-sync/settings', { method: 'POST', body: JSON.stringify(settings) });
