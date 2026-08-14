import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import ScoreboardPage from './pages/ScoreboardPage.tsx'
import BriefPage from './pages/BriefPage.tsx'
import { ExplorerLayout } from './hooks/useSharedExplorer'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        {/* The Brief reads the shared URL coordinate directly, but intentionally
            does not mount the explorer session or its playback transport. */}
        <Route path="/" element={<BriefPage />} />
        {/* Map and Matrix keep their shared live session and scrubber. */}
        <Route element={<ExplorerLayout />}>
          <Route path="/map" element={<App />} />
          <Route path="/matrix" element={<App />} />
        </Route>
        <Route path="/scoreboard" element={<ScoreboardPage />} />
        {/* Unknown locations deliberately return to the product entry point. */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
