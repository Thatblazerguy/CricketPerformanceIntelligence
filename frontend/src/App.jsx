/**
 * React Router app setup with all page routes.
 */
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './features/dashboard/Dashboard';
import Players from './features/players/Players';
import PlayerProfile from './features/players/PlayerProfile';
import Matches from './features/matches/Matches';
import MatchDetail from './features/matches/MatchDetail';
import Matchups from './features/matchups/Matchups';
import PlayerComparison from './features/comparisons/PlayerComparison';
import Scouting from './features/scouting/Scouting';
import Venues from './features/venues/Venues';
import AuctionIntelligence from './features/auction/AuctionIntelligence';

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
          <Route path="compare" element={<PlayerComparison />} />
          <Route path="matchups" element={<Matchups />} />
          <Route path="scouting" element={<Scouting />} />
          <Route path="venues" element={<Venues />} />
          <Route path="auction" element={<AuctionIntelligence />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
