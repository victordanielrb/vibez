import { useRef, useState } from 'react'
import { fileToBase64, urlToBase64, searchByImage, type SearchResult } from '../api'

export default function ImageSearch() {
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
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  const maxDist = Math.max(...results.map(r => r.distance), 1)

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
          {results.map((r, i) => (
            <li key={r.id} className="result-card">
              <span className="result-rank">#{i + 1}</span>
              <div className="result-info">
                <a href={r.url} target="_blank" rel="noreferrer" className="result-name">
                  {r.name}
                </a>
                <span className="result-author">{r.author}</span>
                <div className="dist-bar-wrap">
                  <div
                    className="dist-bar"
                    style={{ width: `${(1 - r.distance / maxDist) * 100}%` }}
                  />
                  <span className="dist-label">{(r.distance * 100).toFixed(1)}% distance</span>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {!loading && results.length === 0 && preview && (
        <p className="hint">No tracks found — ingest a playlist first.</p>
      )}
    </div>
  )
}
