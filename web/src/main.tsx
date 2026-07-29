import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import ScoreboardPage from './pages/ScoreboardPage.tsx'
import AnalysisPage from './pages/AnalysisPage.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        {/* The live-data shell (App) hosts both the Map and Matrix workspaces and
            switches between them by pathname, keeping the Map mounted across the
            /map ↔ /matrix hop — so both land on the same element rather than
            separate route components. `*` keeps the root and any unknown path on
            the Map, preserving the map-first landing. */}
        <Route path="/map" element={<App />} />
        <Route path="/matrix" element={<App />} />
        <Route path="/scoreboard" element={<ScoreboardPage />} />
        <Route path="/analysis" element={<AnalysisPage />} />
        <Route path="*" element={<App />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
