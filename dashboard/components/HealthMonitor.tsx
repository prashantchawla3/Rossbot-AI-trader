import { Badge } from './Badge'
import type { HealthOut } from '@/lib/types'

interface HealthMonitorProps {
  health: HealthOut
}

export function HealthMonitor({ health }: HealthMonitorProps) {
  return (
    <div className="list">
      {health.feeds.map((feed) => (
        <div key={feed.feed_name} className="data-row">
          <div>
            <strong>{feed.feed_name}</strong>
            <p className="small muted" style={{ marginTop: '2px', fontFamily: 'var(--font-mono)' }}>
              {feed.last_tick_ts
                ? new Date(feed.last_tick_ts).toLocaleTimeString('en-US', { hour12: false })
                : 'No tick yet'}
              {feed.stale_seconds != null && ` (${feed.stale_seconds.toFixed(0)}s ago)`}
            </p>
          </div>
          <Badge variant={feed.is_stale ? 'warn' : 'success'}>
            {feed.is_stale ? 'Stale' : 'Live'}
          </Badge>
        </div>
      ))}

      <div className="data-row">
        <div>
          <strong>Clock Drift</strong>
        </div>
        <span className="mono small">
          {health.clock_drift_ms != null
            ? `${health.clock_drift_ms.toFixed(1)} ms`
            : '—'}
        </span>
      </div>

      <div className="data-row">
        <div>
          <strong>Avg Order Ack</strong>
        </div>
        <span className="mono small">
          {health.avg_order_ack_ms != null
            ? `${health.avg_order_ack_ms.toFixed(1)} ms`
            : '—'}
        </span>
      </div>

      <div className="data-row">
        <div>
          <strong>WS Clients</strong>
        </div>
        <span className="mono small">{health.ws_client_count}</span>
      </div>

      <div className="data-row">
        <div>
          <strong>Overall</strong>
        </div>
        <Badge variant={health.all_healthy ? 'success' : 'warn'}>
          {health.all_healthy ? 'Healthy' : 'Degraded'}
        </Badge>
      </div>
    </div>
  )
}
