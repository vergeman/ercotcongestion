import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import ScoreboardPage from './pages/ScoreboardPage.tsx'
import AnalysisPage from './pages/AnalysisPage.tsx'
import { ExplorerLayout } from './hooks/useSharedExplorer'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        {/* ExplorerLayout mounts one shared live session (ExplorerProvider) and
            stays mounted while you navigate among its child routes — so the
            window/cursor/data survive the Map ↔ Matrix ↔ Analysis hop instead of
            refetching. App still hosts both Map and Matrix and switches by
            pathname, keeping the Map mounted across /map ↔ /matrix; `*` keeps the
            root and unknown paths on the Map. Scoreboard is a sibling, outside
            the shared session. */}
        <Route element={<ExplorerLayout />}>
          <Route path="/map" element={<App />} />
          <Route path="/matrix" element={<App />} />
          <Route path="/analysis" element={<AnalysisPage />} />
          <Route path="*" element={<App />} />
        </Route>
        <Route path="/scoreboard" element={<ScoreboardPage />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
