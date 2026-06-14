import { useRef, useState } from 'react'
import { startIngest } from '../api'

type JobEvent = {
  type: 'start' | 'progress' | 'track_error' | 'done' | 'error'
  processed?: number
  total?: number
  track?: string
  error?: string
}

type LogEntry = { ok: boolean; label: string }

type Props = { onComplete?: () => void }

export default function PlaylistIngester({ onComplete }: Props) {
  const [url, setUrl] = useState('')
  const [status, setStatus] = useState<'idle' | 'running' | 'done' | 'failed'>('idle')
  const [progress, setProgress] = useState({ processed: 0, total: 0 })
  const [log, setLog] = useState<LogEntry[]>([])
  const esRef = useRef<EventSource | null>(null)

  function handleIngest() {
    if (!url.trim()) return
    setLog([])
    setStatus('running')
    setProgress({ processed: 0, total: 0 })

    startIngest(url.trim())
      .then(({ jobId }) => {
        const es = new EventSource(`/api/jobs/${jobId}/stream`)
        esRef.current = es

        es.onmessage = (e) => {
          const ev: JobEvent = JSON.parse(e.data)
          if (ev.type === 'start') {
            setProgress({ processed: 0, total: ev.total ?? 0 })
          }
          if (ev.type === 'progress') {
            setProgress({ processed: ev.processed ?? 0, total: ev.total ?? 0 })
            setLog(prev => [...prev, { ok: true, label: ev.track ?? '' }])
          }
          if (ev.type === 'track_error') {
            setProgress(p => ({ ...p, processed: ev.processed ?? p.processed }))
            setLog(prev => [...prev, { ok: false, label: ev.error ?? 'unknown error' }])
          }
          if (ev.type === 'done') {
            setStatus('done')
            es.close()
            onComplete?.()
          }
          if (ev.type === 'error') {
            setStatus('failed')
            es.close()
          }
        }

        es.onerror = () => {
          setStatus('failed')
          es.close()
        }
      })
      .catch(() => setStatus('failed'))
  }

  const pct = progress.total ? Math.round((progress.processed / progress.total) * 100) : 0
  const ok = log.filter(l => l.ok).length
  const failed = log.filter(l => !l.ok).length

  return (
    <div className="section">
      <h2>Ingest Playlist</h2>

      <div className="row">
        <input
          type="text"
          placeholder="https://www.youtube.com/playlist?list=..."
          value={url}
          onChange={e => setUrl(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && status !== 'running' && handleIngest()}
          disabled={status === 'running'}
          className="input-url"
        />
        <button
          onClick={handleIngest}
          disabled={status === 'running' || !url.trim()}
          className="btn-primary"
        >
          {status === 'running' ? 'Ingesting…' : 'Ingest'}
        </button>
      </div>

      {status === 'running' && progress.total > 0 && (
        <div className="ingest-progress">
          <div className="ingest-progress-meta">
            <span>{progress.processed} / {progress.total} tracks</span>
            <span>{pct}%</span>
          </div>
          <div className="quota-track">
            <div className="quota-fill" style={{ width: `${pct}%`, background: 'var(--accent)' }} />
          </div>
        </div>
      )}

      {status === 'done' && (
        <p className="done-msg">
          {ok} track{ok !== 1 ? 's' : ''} ingested{failed > 0 ? `, ${failed} failed` : ''}
        </p>
      )}

      {status === 'failed' && (
        <p className="error">Ingestion failed. Check the server logs.</p>
      )}

      {log.length > 0 && (
        <ul className="track-list">
          {log.map((entry, i) => (
            <li key={i} className="track-row">
              <span className={`chip ${entry.ok ? 'ok' : 'error'}`}>
                {entry.ok ? '✓' : '✗'}
              </span>
              <span className={entry.ok ? 'track-title' : 'track-error'}>
                {entry.label}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
