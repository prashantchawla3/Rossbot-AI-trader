import { Badge } from './Badge'
import { Tooltip } from './Tooltip'
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

const ACTION_HINT: Record<SignalEvent['action'], string> = {
  entry: 'The bot bought into this stock — a trade was opened.',
  exit: 'The bot sold — a trade was closed out.',
  veto: 'The bot blocked this trade because a safety rule said no.',
  info: 'Informational note — no trade was placed.',
}

export function SignalFeed({ signals, limit = 20 }: SignalFeedProps) {
  const visible = signals.slice(0, limit)

  if (visible.length === 0) {
    return <p className="empty-state">No signals yet — the bot hasn’t acted this session.</p>
  }

  return (
    <div className="list">
      {visible.map((s) => (
        <div key={s.id} className="activity-row">
          <div>
            <strong>{s.symbol}</strong>{' '}
            <span className="small muted">{s.event_type.replace(/_/g, ' ')}</span>
            {s.detail && Object.keys(s.detail).length > 0 && (
              <p className="small muted" style={{ marginTop: '2px' }}>
                {Object.entries(s.detail)
                  .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${String(v)}`)
                  .join(' · ')}
              </p>
            )}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '4px', flexShrink: 0 }}>
            <Tooltip label={ACTION_HINT[s.action]}>
              <Badge variant={actionVariant(s.action)}>{s.action}</Badge>
            </Tooltip>
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
