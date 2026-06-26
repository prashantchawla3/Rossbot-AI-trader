'use client'

import { useDashboard } from '@/hooks/useDashboardState'
import { HealthMonitor } from '@/components/HealthMonitor'
import { Badge } from '@/components/Badge'

export default function HealthPage() {
  const { state } = useDashboard()
  const health = state.data?.health

  if (!health) {
    return (
      <div className="view">
        <div className="topbar">
          <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 600 }}>Health</h1>
        </div>
        <div className="card">
          <p className="small muted">Connecting...</p>
        </div>
      </div>
    )
  }

  const staleFeeds = health.feeds.filter((f) => f.is_stale).length

  return (
    <div className="view">
      <div className="topbar">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h1
              style={{
                margin: 0,
                fontSize: '1.5rem',
                fontWeight: 600,
                letterSpacing: '-0.012em',
              }}
            >
              Health
            </h1>
            <p className="small muted" style={{ marginTop: '4px' }}>
              Feed liveness, clock drift, order latency
            </p>
          </div>
          <Badge variant={health.all_healthy ? 'success' : 'warn'}>
            {health.all_healthy ? 'All Systems Go' : `${staleFeeds} Feed(s) Stale`}
          </Badge>
        </div>
      </div>

      {/* Summary metrics */}
      <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
        <div className="metric-card">
          <span className="eyebrow">WS Clients</span>
          <span className="metric-value">{health.ws_client_count}</span>
        </div>
        <div className="metric-card" style={{ borderLeft: '1px solid var(--color-border)' }}>
          <span className="eyebrow">Clock Drift</span>
          <span className="metric-value">
            {health.clock_drift_ms != null
              ? `${health.clock_drift_ms.toFixed(1)}ms`
              : '—'}
          </span>
        </div>
        <div className="metric-card" style={{ borderLeft: '1px solid var(--color-border)' }}>
          <span className="eyebrow">Order Ack</span>
          <span className="metric-value">
            {health.avg_order_ack_ms != null
              ? `${health.avg_order_ack_ms.toFixed(1)}ms`
              : '—'}
          </span>
        </div>
      </div>

      <div className="card">
        <div className="panel-title">
          <div>
            <h3>Feed Status</h3>
            <p className="support">
              Checked at{' '}
              {new Date(health.checked_at).toLocaleTimeString('en-US', { hour12: false })}
            </p>
          </div>
        </div>
        <HealthMonitor health={health} />
      </div>
    </div>
  )
}
