import { useState } from 'react'
import { ingestPlaylist, type SseEvent, type TrackResult } from '../api'

type TrackRow = {
  videoId: string
  status: 'ok' | 'error'
  result?: TrackResult
  error?: string
}

export default function PlaylistIngester() {
  const [url, setUrl] = useState('')
  const [tracks, setTracks] = useState<TrackRow[]>([])
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState('')

  async function handleIngest() {
    if (!url.trim()) return
    setTracks([])
    setDone(false)
    setError('')
    setLoading(true)

    try {
      await ingestPlaylist(url.trim(), (e: SseEvent) => {
        if (e.type === 'progress') {
          setTracks(prev => [...prev, { videoId: e.videoId, status: 'ok', result: e.result }])
        } else if (e.type === 'error') {
          setTracks(prev => [...prev, { videoId: 'unknown', status: 'error', error: e.error }])
        } else if (e.type === 'done') {
          setDone(true)
        }
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="section">
      <h2>Ingest Playlist</h2>
      <div className="row">
        <input
          type="text"
          placeholder="https://www.youtube.com/playlist?list=..."
          value={url}
          onChange={e => setUrl(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleIngest()}
          disabled={loading}
          className="input-url"
        />
        <button onClick={handleIngest} disabled={loading || !url.trim()} className="btn-primary">
          {loading ? 'Ingesting…' : 'Ingest'}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {tracks.length > 0 && (
        <ul className="track-list">
          {tracks.map((t, i) => (
            <li key={i} className={`track-row ${t.status}`}>
              {t.status === 'ok' ? (
                <>
                  <span className="chip ok">✓</span>
                  <span className="track-title">{t.result?.title ?? t.videoId}</span>
                  {t.result?.author && <span className="track-author">{t.result.author}</span>}
                </>
              ) : (
                <>
                  <span className="chip error">✗</span>
                  <span className="track-error">{t.error}</span>
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      {done && (
        <p className="done-msg">
          Done — {tracks.filter(t => t.status === 'ok').length} tracks ingested
          {tracks.filter(t => t.status === 'error').length > 0 &&
            `, ${tracks.filter(t => t.status === 'error').length} failed`}
        </p>
      )}
    </div>
  )
}
