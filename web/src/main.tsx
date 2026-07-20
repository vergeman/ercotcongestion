import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import ScoreboardPage from './pages/ScoreboardPage.tsx'

// Minimal pathname routing (no router dependency): /scoreboard renders the full
// backtest board (the "View full scoreboard" target), everything else the map.
// The <a href> links do full navigations; vite's SPA fallback serves index.html
// for /scoreboard so this switch resolves it.
const Root = window.location.pathname.startsWith('/scoreboard') ? ScoreboardPage : App

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
