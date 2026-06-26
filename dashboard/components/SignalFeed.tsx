import { Badge } from './Badge'
import type { SignalEvent } from '@/lib/types'

interface SignalFeedProps {
  signals: SignalEvent[]
  limit?: number
}

function actionVariant(action: SignalEvent['action']): 'live' | 'warn' | 'success' | 'default' {
  switch (action) {
    case 'entry': return 'live'
    case 'exit': return 'success'
    case 'veto': return 'warn'
    default: return 'default'
  }
}

export function SignalFeed({ signals, limit = 20 }: SignalFeedProps) {
  const visible = signals.slice(0, limit)

  if (visible.length === 0) {
    return (
      <p className="small muted" style={{ textAlign: 'center', padding: '24px 0' }}>
        No signals yet
      </p>
    )
  }

  return (
    <div className="list">
      {visible.map((s) => (
        <div key={s.id} className="activity-row">
          <div>
            <strong>{s.symbol}</strong>{' '}
            <span className="small muted">{s.event_type}</span>
            {s.detail && Object.keys(s.detail).length > 0 && (
              <p className="small muted" style={{ marginTop: '2px' }}>
                {JSON.stringify(s.detail)}
              </p>
            )}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '4px', flexShrink: 0 }}>
            <Badge variant={actionVariant(s.action)}>{s.action}</Badge>
            <span className="small muted"
              style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem' }}>
              {new Date(s.ts).toLocaleTimeString('en-US', { hour12: false })}
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}
