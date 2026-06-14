import { useEffect, useState } from 'react'
import { fetchMetricsOps, GeminiLimits, MetricsOps } from '../api'

const OP_LABELS: Record<string, string> = {
  describe_image: 'Describe Image',
  extract_genres: 'Extract Genres',
  rerank_tracks: 'Rerank Tracks',
  embed_image: 'Embed Image',
  embed_text: 'Embed Text',
  image_search: 'Image Search (marker)',
  track_ingest: 'Track Ingest (marker)',
}

const OP_COLORS: Record<string, string> = {
  describe_image: '#a78bfa',
  extract_genres: '#60a5fa',
  rerank_tracks: '#34d399',
  embed_image: '#f472b6',
  embed_text: '#fb923c',
  image_search: '#94a3b8',
  track_ingest: '#64748b',
}

function fmt(n: number) {
  return new Intl.NumberFormat('pt-BR', { notation: 'compact' }).format(n)
}

function GeminiModelLimits({ g }: { g: GeminiLimits }) {
  const rows: Array<{ key: keyof typeof g.used; label: string; unit: string }> = [
    { key: 'rpm', label: 'RPM', unit: 'req/min' },
    { key: 'tpm', label: 'TPM', unit: 'tok/min' },
    { key: 'rpd', label: 'RPD', unit: 'req/day' },
  ]
  return (
    <div className="gemini-limits">
      <div className="gemini-model-tag">{g.model}</div>
      {rows.map(({ key, label, unit }) => {
        const used = g.used[key]
        const limit = g.limits[key]
        const pct = Math.min((used / limit) * 100, 100)
        const color = pct >= 80 ? '#ef4444' : pct >= 50 ? '#f59e0b' : '#a78bfa'
        return (
          <div key={key} className="gemini-limit-row">
            <div className="gemini-limit-meta">
              <span className="gemini-limit-label">{label}</span>
              <span className="gemini-limit-unit">{unit}</span>
              <span className="gemini-limit-val" style={{ color }}>
                {fmt(used)} / {fmt(limit)}
              </span>
            </div>
            <div className="gemini-bar-wrap">
              <div className="gemini-bar" style={{ width: `${Math.max(pct, 0.5)}%`, background: color }} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="stat-card">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

function OpsChart({ data }: { data: MetricsOps['ops_breakdown'] }) {
  const realOps = data.filter(d => d.model !== '')
  if (!realOps.length) return <p className="dash-empty">No Gemini calls today yet.</p>

  const maxTokens = Math.max(...realOps.map(d => d.tokens_in + d.tokens_out), 1)

  return (
    <div className="ops-chart">
      {realOps.map(d => {
        const total = d.tokens_in + d.tokens_out
        const pct = Math.max((total / maxTokens) * 100, 2)
        const color = OP_COLORS[d.operation] ?? '#94a3b8'
        const label = OP_LABELS[d.operation] ?? d.operation
        return (
          <div key={d.operation} className="ops-row">
            <div className="ops-label">{label}</div>
            <div className="ops-bar-wrap">
              <div className="ops-bar" style={{ width: `${pct}%`, background: color }} />
            </div>
            <div className="ops-meta">
              <span>{fmt(total)} tok</span>
              <span className="ops-calls">{d.calls}×</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function HourlyChart({ data }: { data: MetricsOps['hourly'] }) {
  if (!data.length) return <p className="dash-empty">No activity in the last 24 hours.</p>

  const maxTokens = Math.max(...data.map(d => d.tokens), 1)

  return (
    <div className="hourly-chart">
      {data.map(d => {
        const h = d.hour.slice(11, 13) + 'h'
        const pct = Math.max((d.tokens / maxTokens) * 100, 2)
        return (
          <div key={d.hour} className="hourly-col" title={`${d.hour}\n${fmt(d.tokens)} tokens · ${d.calls} calls`}>
            <div className="hourly-bar-wrap">
              <div className="hourly-bar" style={{ height: `${pct}%` }} />
            </div>
            <div className="hourly-label">{h}</div>
          </div>
        )
      })}
    </div>
  )
}

export default function MetricsDashboard() {
  const [data, setData] = useState<MetricsOps | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = () => {
    setLoading(true)
    fetchMetricsOps()
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  if (loading) return <p className="dash-loading">Loading metrics…</p>
  if (error) return <p className="dash-error">{error}</p>
  if (!data) return null

  const g = data.global_today
  const totalTokens = g.tokens_used
  const markerOps = data.ops_breakdown.filter(d => d.model === '')
  const tracksIngested = markerOps.find(d => d.operation === 'track_ingest')?.calls ?? g.tracks_ingested

  return (
    <div className="dash-wrap">
      <div className="dash-header">
        <h2>Metrics Dashboard</h2>
        <button className="dash-refresh" onClick={load} title="Refresh">↻</button>
      </div>

      <section className="dash-section">
        <h3>Today — Global</h3>
        <div className="stat-grid">
          <StatCard label="Tokens Used" value={fmt(totalTokens)} sub="gemini calls" />
          <StatCard label="Image Searches" value={g.image_searches} />
          <StatCard label="Tracks Ingested" value={tracksIngested} />
          <StatCard label="Unique IPs" value={g.unique_ips} />
          <StatCard label="RPM (live)" value={g.rpm} sub="last 60s" />
        </div>
      </section>

      <section className="dash-section">
        <h3>Gemini API — Model Limits</h3>
        <GeminiModelLimits g={data.gemini} />
      </section>

      <section className="dash-section">
        <h3>Tokens by Operation (today)</h3>
        <OpsChart data={data.ops_breakdown} />
      </section>

      <section className="dash-section">
        <h3>Activity — Last 24 h</h3>
        <HourlyChart data={data.hourly} />
      </section>

      <section className="dash-section dash-otel-note">
        <h3>OTel / Prometheus</h3>
        <p>
          ADK emits <code>gen_ai.agent.invocation.duration</code>, <code>gen_ai.agent.request.size</code>,
          and <code>gen_ai.agent.workflow.steps</code> via OpenTelemetry.
          Raw Prometheus scrape endpoint:
          <a href="/api/otel-metrics" target="_blank" rel="noreferrer"> /api/otel-metrics</a>
        </p>
      </section>
    </div>
  )
}
