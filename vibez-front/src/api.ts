const BASE = '/api'

export type TrackResult = {
  videoId: string
  index: number
  total: number
  title?: string
  author?: string
  input_url?: string
  description?: string
  error?: string
  [key: string]: unknown
}

export type SearchResult = {
  id: number
  rank: number
  reason: string
  name: string
  author: string
  url: string
  description: string | null
  distance: number
}

export type QuotaInfo = {
  client_ip: string
  today: { image_searches: number; tracks_ingested: number; tokens_used: number; rpm: number }
  limits: { image_searches_per_day: number; tracks_per_day: number; tokens_per_day: number; rpm: number }
  pct_tokens: number
  rpm_used: number
  pct_rpm: number
}

export class RateLimitError extends Error {
  constructor(message = 'Daily limit reached. Try again tomorrow.') {
    super(message)
    this.name = 'RateLimitError'
  }
}

async function _check(res: Response) {
  if (res.status === 429) {
    const body = await res.json().catch(() => ({}))
    throw new RateLimitError(body?.detail?.message ?? 'Daily limit reached. Try again tomorrow.')
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res
}

export async function ingestPlaylist(playlistUrl: string): Promise<TrackResult[]> {
  const res = await fetch(`${BASE}/extract`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ playlistUrl }),
  })
  await _check(res)
  const data = await res.json()
  return data.results ?? []
}

export async function searchByImage(
  imageBase64: string,
  topN = 5
): Promise<{ description: string; searchResults: SearchResult[] }> {
  const res = await fetch(`${BASE}/image-embedding`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ imageBase64, topN }),
  })
  await _check(res)
  return res.json()
}

export async function fetchQuota(): Promise<QuotaInfo> {
  const res = await fetch(`${BASE}/quota`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export type OpsEntry = { operation: string; model: string; calls: number; tokens_in: number; tokens_out: number }
export type HourlyEntry = { hour: string; tokens: number; calls: number }
export type GlobalToday = { image_searches: number; tracks_ingested: number; tokens_used: number; unique_ips: number; rpm: number }
export type GeminiLimits = {
  model: string
  limits: { rpm: number; tpm: number; rpd: number }
  used: { rpm: number; tpm: number; rpd: number }
}

export type MetricsOps = {
  ops_breakdown: OpsEntry[]
  hourly: HourlyEntry[]
  global_today: GlobalToday
  gemini: GeminiLimits
}

export async function fetchMetricsOps(): Promise<MetricsOps> {
  const res = await fetch(`${BASE}/metrics/ops`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

export async function urlToBase64(imageUrl: string): Promise<string> {
  const res = await fetch(imageUrl)
  if (!res.ok) throw new Error(`Could not fetch image: HTTP ${res.status}`)
  const blob = await res.blob()
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(blob)
  })
}
