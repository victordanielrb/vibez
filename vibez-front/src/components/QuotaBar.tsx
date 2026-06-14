import { useEffect, useState, useCallback } from 'react'
import { fetchQuota, type QuotaInfo } from '../api'

const fmt = (n: number) =>
  new Intl.NumberFormat('pt-BR', { notation: 'compact', maximumFractionDigits: 1 }).format(n)

function barColor(pct: number): string {
  if (pct >= 80) return '#ef4444'
  if (pct >= 50) return '#f59e0b'
  return '#a855f7'
}

type Props = { refreshKey?: number }

export default function QuotaBar({ refreshKey }: Props) {
  const [quota, setQuota] = useState<QuotaInfo | null>(null)

  const load = useCallback(() => {
    fetchQuota().then(setQuota).catch(() => {})
  }, [])

  useEffect(() => { load() }, [load, refreshKey])

  if (!quota) return null

  const pct = quota.pct_tokens
  const { tokens_used, tokens_per_day } = { tokens_used: quota.today.tokens_used, tokens_per_day: quota.limits.tokens_per_day }
  const color = barColor(pct)
  const limitReached = pct >= 100
  const rpmColor = barColor(quota.pct_rpm)

  return (
    <div className="quota-wrap">
      <div className="quota-label">
        <span style={{ color }}>
          {fmt(tokens_used)} / {fmt(tokens_per_day)} tokens hoje
        </span>
        <span className="quota-sep">·</span>
        <span style={{ color: rpmColor }}>
          {quota.rpm_used} / {quota.limits.rpm} RPM
        </span>
        {limitReached && <span className="quota-limit-msg">Limite diário atingido</span>}
      </div>
      <div className="quota-track">
        <div
          className="quota-fill"
          style={{ width: `${Math.min(pct, 100)}%`, background: color }}
        />
      </div>
    </div>
  )
}
