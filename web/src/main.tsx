import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './index.css'
import App, { ExplorerApp } from './App.tsx'
import ScoreboardPage from './pages/ScoreboardPage.tsx'
import BriefPage from './pages/BriefPage.tsx'
import AboutPage from './pages/AboutPage.tsx'
import { ExplorerLayout } from './hooks/useSharedExplorer'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        {/* Brief, Map, and Matrix share this client-side route shell. The Brief
            remains outside ExplorerLayout so it does not mount the playback
            session or transport, while App itself stays mounted across hops. */}
        <Route element={<App />}>
          <Route path="/" element={<BriefPage />} />
          <Route path="/about" element={<AboutPage />} />
          {/* Map and Matrix keep their shared live session and scrubber. */}
          <Route element={<ExplorerLayout />}>
            <Route path="/map" element={<ExplorerApp />} />
            <Route path="/matrix" element={<ExplorerApp />} />
          </Route>
        </Route>
        <Route path="/scoreboard" element={<ScoreboardPage />} />
        {/* Unknown locations deliberately return to the product entry point. */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
