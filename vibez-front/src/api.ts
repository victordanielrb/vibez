const BASE = '/api'

export type SseEvent =
  | { type: 'progress'; index: number; total: number; videoId: string; result: TrackResult }
  | { type: 'error'; error: string }
  | { type: 'done' }

export type TrackResult = {
  title: string
  author: string
  input_url: string
  description: string
  [key: string]: unknown
}

export type SearchResult = {
  id: number
  name: string
  author: string
  url: string
  distance: number
}

export async function ingestPlaylist(
  playlistUrl: string,
  onEvent: (e: SseEvent) => void
): Promise<void> {
  const res = await fetch(`${BASE}/extract-stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ playlistUrl }),
  })

  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const event = JSON.parse(line.slice(6)) as SseEvent
          onEvent(event)
        } catch {
          // skip malformed
        }
      }
    }
  }
}

export async function searchByImage(
  imageBase64: string
): Promise<{ embedding: number[]; description: string; searchResults: SearchResult[] }> {
  const res = await fetch(`${BASE}/image-embedding`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ imageBase64 }),
  })
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
