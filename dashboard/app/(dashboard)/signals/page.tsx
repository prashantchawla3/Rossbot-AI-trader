'use client'

import { useDashboard } from '@/hooks/useDashboardState'
import { SignalFeed } from '@/components/SignalFeed'

export default function SignalsPage() {
  const { state } = useDashboard()
  const signals = state.data?.recent_signals ?? []

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
            Signals
          </h1>
          <p className="small muted" style={{ marginTop: '4px' }}>
            Entry, exit, veto events — last 200
          </p>
        </div>
      </div>

      <div className="card">
        <div className="panel-title">
          <div>
            <h3>Signal Feed</h3>
            <p className="support">{signals.length} events in buffer</p>
          </div>
        </div>
        <SignalFeed signals={signals} limit={200} />
      </div>
    </div>
  )
}
