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
        <Route path="/scoreboard" element={<ScoreboardPage />} />
        <Route path="/analysis" element={<AnalysisPage />} />
        <Route path="*" element={<App />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
