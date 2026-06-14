import { useState } from 'react'
import { ingestPlaylist, type TrackResult } from '../api'

type Props = { onComplete?: () => void }

export default function PlaylistIngester({ onComplete }: Props) {
  const [url, setUrl] = useState('')
  const [tracks, setTracks] = useState<TrackResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleIngest() {
    if (!url.trim()) return
    setTracks([])
    setError('')
    setLoading(true)
    try {
      const results = await ingestPlaylist(url.trim())
      setTracks(results)
      onComplete?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  const ok = tracks.filter(t => !t.error)
  const failed = tracks.filter(t => !!t.error)

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
        <>
          <p className="done-msg">
            {ok.length} tracks ingested{failed.length > 0 && `, ${failed.length} failed`}
          </p>
          <ul className="track-list">
            {tracks.map((t, i) => (
              <li key={i} className={`track-row ${t.error ? 'error' : 'ok'}`}>
                {t.error ? (
                  <>
                    <span className="chip error">✗</span>
                    <span className="track-error">{t.error}</span>
                  </>
                ) : (
                  <>
                    <span className="chip ok">✓</span>
                    <span className="track-title">{t.title ?? t.videoId}</span>
                    {t.author && <span className="track-author">{t.author}</span>}
                  </>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
