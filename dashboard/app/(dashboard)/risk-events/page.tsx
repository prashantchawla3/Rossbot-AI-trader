'use client'

import { useDashboard } from '@/hooks/useDashboardState'
import { RiskEventLog } from '@/components/RiskEventLog'

export default function RiskEventsPage() {
  const { state } = useDashboard()
  const events = state.data?.recent_risk_events ?? []

  const criticalCount = events.filter((e) => e.severity === 'CRITICAL').length
  const warnCount = events.filter((e) => e.severity === 'WARN').length

  return (
    <div className="view">
      <div className="topbar">
        <div>
          <h1
            style={{
              margin: 0,
              fontSize: '1.5rem',
              fontWeight: 600,
              letterSpacing: '-0.012em',
            }}
          >
            Risk Events
          </h1>
          <p className="small muted" style={{ marginTop: '4px' }}>
            Vetoes, halts, guardrail triggers — last 500
          </p>
        </div>
      </div>

      {/* Summary row */}
      <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
        <div className="metric-card">
          <span className="eyebrow">Total Events</span>
          <span className="metric-value">{events.length}</span>
        </div>
        <div className="metric-card" style={{ borderLeft: '1px solid var(--color-border)' }}>
          <span className="eyebrow">Critical</span>
          <span className={`metric-value${criticalCount > 0 ? ' negative' : ''}`}>
            {criticalCount}
          </span>
        </div>
        <div className="metric-card" style={{ borderLeft: '1px solid var(--color-border)' }}>
          <span className="eyebrow">Warnings</span>
          <span className="metric-value">{warnCount}</span>
        </div>
      </div>

      <div className="card">
        <div className="panel-title">
          <div>
            <h3>Event Log</h3>
            <p className="support">Newest first</p>
          </div>
        </div>
        <RiskEventLog events={events} limit={500} />
      </div>
    </div>
  )
}
