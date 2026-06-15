import { useRef, useState } from 'react'
import { fileToBase64, urlToBase64, searchByImage, type SearchResult, type FitLevel } from '../api'

const FIT_COLOR: Record<FitLevel, string> = {
  alto:  'var(--ok)',
  médio: 'var(--accent)',
  baixo: 'var(--err)',
}

function fmtOffset(s: number): string {
  const m = Math.floor(s / 60)
  const sec = s % 60
  return `${m}:${sec.toString().padStart(2, '0')}`
}

function ResultCard({ r }: { r: SearchResult }) {
  const [open, setOpen] = useState(false)
  const href = r.offset != null ? `${r.url}&t=${r.offset}` : r.url
  return (
    <li className="result-card">
      <span className="result-rank">#{r.rank}</span>
      <div className="result-info">
        <a href={href} target="_blank" rel="noreferrer" className="result-name">
          {r.name}
        </a>
        {r.offset != null && (
          <span className="result-timestamp">@ {fmtOffset(r.offset)}</span>
        )}
        <span className="result-author">{r.author}</span>
        {(r.genre_fit || r.mood_fit || r.pace_fit) && (
          <div className="fit-badges">
            {r.genre_fit && <span className="fit-badge" style={{ color: FIT_COLOR[r.genre_fit] }}>gênero {r.genre_fit}</span>}
            {r.mood_fit  && <span className="fit-badge" style={{ color: FIT_COLOR[r.mood_fit]  }}>mood {r.mood_fit}</span>}
            {r.pace_fit  && <span className="fit-badge" style={{ color: FIT_COLOR[r.pace_fit]  }}>ritmo {r.pace_fit}</span>}
          </div>
        )}
        {r.reason && <span className="result-reason">{r.reason}</span>}
        {r.description && (
          <>
            <button
              className="result-details-toggle"
              onClick={() => setOpen(v => !v)}
            >
              {open ? '▲ hide details' : '▼ audio details'}
            </button>
            {open && <p className="result-description">{r.description}</p>}
          </>
        )}
      </div>
    </li>
  )
}

type Props = { onComplete?: () => void }

export default function ImageSearch({ onComplete }: Props) {
  const [mode, setMode] = useState<'upload' | 'link'>('upload')
  const [imageUrl, setImageUrl] = useState('')
  const [preview, setPreview] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [description, setDescription] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  async function handleFile(file: File) {
    const b64 = await fileToBase64(file)
    setPreview(b64)
  }

  async function handleSearch() {
    setError('')
    setResults([])
    setDescription('')
    setLoading(true)
    try {
      let base64 = preview
      if (mode === 'link') {
        base64 = await urlToBase64(imageUrl.trim())
        setPreview(base64)
      }
      if (!base64) throw new Error('No image selected')
      const data = await searchByImage(base64)
      setDescription(data.description ?? '')
      setResults(data.searchResults ?? [])
      onComplete?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="section">
      <h2>Find Matching Track</h2>

      <div className="mode-tabs">
        <button className={mode === 'upload' ? 'active' : ''} onClick={() => setMode('upload')}>
          Upload
        </button>
        <button className={mode === 'link' ? 'active' : ''} onClick={() => setMode('link')}>
          Link
        </button>
      </div>

      {mode === 'upload' ? (
        <div
          className="drop-zone"
          onClick={() => fileRef.current?.click()}
          onDragOver={e => e.preventDefault()}
          onDrop={e => {
            e.preventDefault()
            const file = e.dataTransfer.files[0]
            if (file) handleFile(file)
          }}
        >
          {preview ? (
            <img src={preview} alt="preview" className="preview-img" />
          ) : (
            <span>Click or drag an image here</span>
          )}
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            hidden
            onChange={e => e.target.files?.[0] && handleFile(e.target.files[0])}
          />
        </div>
      ) : (
        <div className="row">
          <input
            type="text"
            placeholder="https://example.com/image.jpg"
            value={imageUrl}
            onChange={e => setImageUrl(e.target.value)}
            className="input-url"
          />
        </div>
      )}

      {mode === 'link' && preview && (
        <img src={preview} alt="preview" className="preview-img preview-link" />
      )}

      <button
        onClick={handleSearch}
        disabled={loading || (mode === 'upload' ? !preview : !imageUrl.trim())}
        className="btn-primary"
      >
        {loading ? 'Searching…' : 'Search'}
      </button>

      {error && <p className="error">{error}</p>}

      {description && (
        <p className="image-description">{description}</p>
      )}

      {results.length > 0 && (
        <ul className="results-list">
          {results.map(r => <ResultCard key={r.id} r={r} />)}
        </ul>
      )}

      {!loading && results.length === 0 && preview && (
        <p className="hint">No tracks found — ingest a playlist first.</p>
      )}
    </div>
  )
}
