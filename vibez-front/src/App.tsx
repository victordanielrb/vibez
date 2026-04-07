import { useState } from 'react'
import PlaylistIngester from './components/PlaylistIngester'
import ImageSearch from './components/ImageSearch'

type Tab = 'ingest' | 'search'

export default function App() {
  const [tab, setTab] = useState<Tab>('ingest')

  return (
    <div className="app">
      <header>
        <h1>vibez</h1>
        <p className="subtitle">match your vibe</p>
      </header>

      <nav className="tabs">
        <button className={tab === 'ingest' ? 'active' : ''} onClick={() => setTab('ingest')}>
          Ingest Playlist
        </button>
        <button className={tab === 'search' ? 'active' : ''} onClick={() => setTab('search')}>
          Search by Image
        </button>
      </nav>

      <main>
        {tab === 'ingest' ? <PlaylistIngester /> : <ImageSearch />}
      </main>
    </div>
  )
}
