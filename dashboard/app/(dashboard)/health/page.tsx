'use client'

import { useDashboard } from '@/hooks/useDashboardState'
import { HealthMonitor } from '@/components/HealthMonitor'
import { Badge } from '@/components/Badge'
import { InfoHint } from '@/components/Tooltip'

export default function HealthPage() {
  const { state } = useDashboard()
  const health = state.data?.health

  if (!health) {
    return (
      <div className="view">
        <div className="page-head">
          <h1>Health</h1>
        </div>
        <div className="card">
          <p className="empty-state">Connecting…</p>
        </div>
      </div>
    )
  }

  const staleFeeds = health.feeds.filter((f) => f.is_stale).length

  return (
    <div className="view">
      <div className="page-head">
        <div>
          <h1>System Health</h1>
          <p className="lede">
            Is the bot connected and getting fresh data fast enough to trade safely? Green
            means all good.
          </p>
        </div>
        <div className="head-actions">
          <Badge variant={health.all_healthy ? 'success' : 'warn'}>
            {health.all_healthy ? 'All Systems Go' : `${staleFeeds} Feed(s) Stale`}
          </Badge>
        </div>
      </div>

      {/* Summary metrics */}
      <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}>
        <div className="metric-card">
          <span className="eyebrow">
            Connected Screens
            <InfoHint label="How many dashboards (like this one) are connected to the bot right now." />
          </span>
          <span className="metric-value">{health.ws_client_count}</span>
        </div>
        <div className="metric-card">
          <span className="eyebrow">
            Clock Drift
            <InfoHint label="How far the bot’s clock is from real time. Small numbers are good; large drift can mis-time trades." />
          </span>
          <span className="metric-value">
            {health.clock_drift_ms != null
              ? `${health.clock_drift_ms.toFixed(1)}ms`
              : '—'}
          </span>
        </div>
        <div className="metric-card">
          <span className="eyebrow">
            Order Speed
            <InfoHint label="Average time for the broker to confirm an order, in milliseconds. Lower is faster." />
          </span>
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
            <h3>
              Data Feeds
              <InfoHint label="Live = data is flowing. Stale = no recent updates, which can pause trading until it recovers." />
            </h3>
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
