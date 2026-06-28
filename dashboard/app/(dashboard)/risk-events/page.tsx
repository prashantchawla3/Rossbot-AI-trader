'use client'

import { useDashboard } from '@/hooks/useDashboardState'
import { RiskEventLog } from '@/components/RiskEventLog'
import { InfoHint } from '@/components/Tooltip'

export default function RiskEventsPage() {
  const { state } = useDashboard()
  const events = state.data?.recent_risk_events ?? []

  const criticalCount = events.filter((e) => e.severity === 'CRITICAL').length
  const warnCount = events.filter((e) => e.severity === 'WARN').length

  return (
    <div className="view">
      <div className="page-head">
        <div>
          <h1>Risk &amp; Safety</h1>
          <p className="lede">
            Every time a safety rule kicked in — a trade blocked, a limit hit, or trading
            paused to protect the account. A quiet page here is a good sign.
          </p>
        </div>
      </div>

      {/* Summary row */}
      <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}>
        <div className="metric-card">
          <span className="eyebrow">
            Total Events
            <InfoHint label="How many safety triggers have fired today, of any severity." />
          </span>
          <span className="metric-value">{events.length}</span>
        </div>
        <div className="metric-card">
          <span className="eyebrow">
            Critical
            <InfoHint label="Serious triggers that stopped trading — like hitting the daily loss limit." />
          </span>
          <span className={`metric-value${criticalCount > 0 ? ' negative' : ''}`}>
            {criticalCount}
          </span>
        </div>
        <div className="metric-card">
          <span className="eyebrow">
            Warnings
            <InfoHint label="Cautionary triggers — the bot adjusted but kept trading." />
          </span>
          <span className="metric-value">{warnCount}</span>
        </div>
      </div>

      <div className="card">
        <div className="panel-title">
          <div>
            <h3>
              Event Log
              <InfoHint label="Each row is one safety trigger, newest first, with the reason it fired." />
            </h3>
            <p className="support">Newest first</p>
          </div>
        </div>
        <RiskEventLog events={events} limit={500} />
      </div>
    </div>
  )
}
