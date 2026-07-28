import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { ErrorBoundary } from './components/common/ErrorBoundary'
import { JobEventsProvider } from './context/JobContext'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <JobEventsProvider>
        <App />
      </JobEventsProvider>
    </ErrorBoundary>
  </StrictMode>,
)
