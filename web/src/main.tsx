import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import TimelineProvider from './components/TimelineProvider'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <TimelineProvider>
      <App />
    </TimelineProvider>
  </StrictMode>,
)
