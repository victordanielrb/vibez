import { useState } from 'react'
import PlaylistIngester from './components/PlaylistIngester'
import ImageSearch from './components/ImageSearch'
import QuotaBar from './components/QuotaBar'
import MetricsDashboard from './components/MetricsDashboard'

type Tab = 'ingest' | 'search' | 'dashboard'

export default function App() {
  const [tab, setTab] = useState<Tab>('ingest')
  const [quotaRefresh, setQuotaRefresh] = useState(0)

  const refreshQuota = () => setQuotaRefresh(k => k + 1)

  return (
    <div className="app">
      <header>
        <h1>vibez</h1>
        <p className="subtitle">match your vibe</p>
      </header>

      <QuotaBar refreshKey={quotaRefresh} />

      <nav className="tabs">
        <button className={tab === 'ingest' ? 'active' : ''} onClick={() => setTab('ingest')}>
          Ingest Playlist
        </button>
        <button className={tab === 'search' ? 'active' : ''} onClick={() => setTab('search')}>
          Search by Image
        </button>
        <button className={tab === 'dashboard' ? 'active' : ''} onClick={() => setTab('dashboard')}>
          Dashboard
        </button>
      </nav>

      <main>
        {tab === 'ingest' && <PlaylistIngester onComplete={refreshQuota} />}
        {tab === 'search' && <ImageSearch onComplete={refreshQuota} />}
        {tab === 'dashboard' && <MetricsDashboard />}
      </main>
    </div>
  )
}
