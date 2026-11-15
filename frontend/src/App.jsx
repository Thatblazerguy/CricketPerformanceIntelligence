/**
 * React Router app setup with all page routes.
 */
import { lazy } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
const Dashboard = lazy(() => import('./features/dashboard/Dashboard'));
const Players = lazy(() => import('./features/players/Players'));
const PlayerProfile = lazy(() => import('./features/players/PlayerProfile'));
const Matches = lazy(() => import('./features/matches/Matches'));
const MatchDetail = lazy(() => import('./features/matches/MatchDetail'));
const Matchups = lazy(() => import('./features/matchups/Matchups'));
const PlayerComparison = lazy(() => import('./features/comparisons/PlayerComparison'));
const Scouting = lazy(() => import('./features/scouting/Scouting'));
const VenueAnalytics = lazy(() => import('./features/venues/VenueAnalytics'));
const VenueProfile = lazy(() => import('./features/venues/VenueProfile'));
const VenueCompare = lazy(() => import('./features/venues/VenueCompare'));
const AuctionIntelligence = lazy(() => import('./features/auction/AuctionIntelligence'));
const MatchSimulator = lazy(() => import('./features/matches/MatchSimulator'));
const Settings = lazy(() => import('./features/settings/Settings'));
const DataHealth = lazy(() => import('./features/datahealth/DataHealth'));
const Tournaments = lazy(() => import('./features/tournaments/Tournaments'));
const TeamAnalytics = lazy(() => import('./features/teams/TeamAnalytics'));
const TeamProfile = lazy(() => import('./features/teams/TeamProfile'));
const TeamCompare = lazy(() => import('./features/teams/TeamCompare'));

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="players" element={<Players />} />
          <Route path="players/:id" element={<PlayerProfile />} />
          <Route path="matches" element={<Matches />} />
          <Route path="matches/:id" element={<MatchDetail />} />
          <Route path="simulator" element={<MatchSimulator />} />
          <Route path="compare" element={<PlayerComparison />} />
          <Route path="matchups" element={<Matchups />} />
          <Route path="scouting" element={<Scouting />} />
          <Route path="venues" element={<VenueAnalytics />} />
          <Route path="venues/compare" element={<VenueCompare />} />
          <Route path="venues/:id" element={<VenueProfile />} />
          <Route path="tournaments" element={<Tournaments />} />
          <Route path="teams" element={<TeamAnalytics />} />
          <Route path="teams/compare" element={<TeamCompare />} />
          <Route path="teams/:id" element={<TeamProfile />} />
          <Route path="auction" element={<AuctionIntelligence />} />
          <Route path="data-health" element={<DataHealth />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
