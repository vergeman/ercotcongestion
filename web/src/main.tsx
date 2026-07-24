import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import ScoreboardPage from './pages/ScoreboardPage.tsx'

// Scoreboard remains a standalone analytical application. The explorer itself
// handles /map and /matrix transitions without recreating its live session.
export function Root() {
  return window.location.pathname.startsWith('/scoreboard') ? (
    <ScoreboardPage />
  ) : (
    <App />
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
