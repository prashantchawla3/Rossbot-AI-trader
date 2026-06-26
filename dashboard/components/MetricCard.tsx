import type { ReactNode } from 'react'

interface MetricCardProps {
  label: string
  value: string
  delta?: string
  icon?: ReactNode
  sentiment?: 'positive' | 'negative' | 'neutral'
}

export function MetricCard({ label, value, delta, icon, sentiment = 'neutral' }: MetricCardProps) {
  const valueClass = `metric-value${sentiment !== 'neutral' ? ` ${sentiment}` : ''}`
  return (
    <div className="metric-card">
      <div className="metric-head">
        <span className="eyebrow">{label}</span>
        {icon && <span className="muted">{icon}</span>}
      </div>
      <span className={valueClass}>{value}</span>
      {delta && <span className="kpi-delta">{delta}</span>}
    </div>
  )
}
