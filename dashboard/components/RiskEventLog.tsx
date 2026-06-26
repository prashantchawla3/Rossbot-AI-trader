import { Badge } from './Badge'
import type { RiskEvent } from '@/lib/types'

interface RiskEventLogProps {
  events: RiskEvent[]
  limit?: number
}

function severityVariant(severity: RiskEvent['severity']): 'default' | 'warn' | 'live' {
  switch (severity) {
    case 'CRITICAL': return 'live'
    case 'WARN': return 'warn'
    default: return 'default'
  }
}

export function RiskEventLog({ events, limit = 30 }: RiskEventLogProps) {
  const visible = events.slice(0, limit)

  if (visible.length === 0) {
    return (
      <p className="small muted" style={{ textAlign: 'center', padding: '24px 0' }}>
        No risk events
      </p>
    )
  }

  return (
    <div className="list">
      {visible.map((e) => (
        <div key={e.id} className="activity-row">
          <div>
            <strong>{e.event_type}</strong>
            <p className="small muted" style={{ marginTop: '2px' }}>{e.message}</p>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '4px', flexShrink: 0 }}>
            <Badge variant={severityVariant(e.severity)}>{e.severity}</Badge>
            <span className="small muted"
              style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem' }}>
              {new Date(e.ts).toLocaleTimeString('en-US', { hour12: false })}
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}
