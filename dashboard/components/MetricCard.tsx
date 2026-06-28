import type { ReactNode } from 'react'
import { InfoHint } from './Tooltip'

interface MetricCardProps {
  label: string
  value: string
  delta?: string
  icon?: ReactNode
  sentiment?: 'positive' | 'negative' | 'neutral'
  /** Plain-language explanation shown on the ⓘ icon next to the label. */
  hint?: string
}

export function MetricCard({
  label,
  value,
  delta,
  icon,
  sentiment = 'neutral',
  hint,
}: MetricCardProps) {
  const valueClass = `metric-value${sentiment !== 'neutral' ? ` ${sentiment}` : ''}`
  return (
    <div className="metric-card">
      <div className="metric-head">
        <span className="eyebrow">
          {label}
          {hint && <InfoHint label={hint} />}
        </span>
        {icon && <span className="muted">{icon}</span>}
      </div>
      <span className={valueClass}>{value}</span>
      {delta && <span className="kpi-delta">{delta}</span>}
    </div>
  )
}
