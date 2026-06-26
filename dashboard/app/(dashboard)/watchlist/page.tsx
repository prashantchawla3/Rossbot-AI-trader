'use client'

import { useDashboard } from '@/hooks/useDashboardState'
import { WatchlistTable } from '@/components/WatchlistTable'
import { Badge } from '@/components/Badge'

export default function WatchlistPage() {
  const { state } = useDashboard()
  const tierA = state.data?.watchlist_tier_a ?? []
  const tierB = state.data?.watchlist_tier_b ?? []

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
            Watchlist
          </h1>
          <p className="small muted" style={{ marginTop: '4px' }}>
            Tier A wide-net scan, Tier B Five-Pillar qualified
          </p>
        </div>
      </div>

      <div className="card">
        <div className="panel-title">
          <div>
            <h3>Tier B — Five Pillars</h3>
            <p className="support">Price $2–20, Float ≤20M, RVOL ≥5x, ROC ≥10%, Catalyst</p>
          </div>
          <Badge variant={tierB.length > 0 ? 'live' : 'default'}>{tierB.length}</Badge>
        </div>
        <WatchlistTable entries={tierB} tier="B" />
      </div>

      <div className="card">
        <div className="panel-title">
          <div>
            <h3>Tier A — Wide Net</h3>
            <p className="support">All pre-screened candidates</p>
          </div>
          <Badge variant="default">{tierA.length}</Badge>
        </div>
        <WatchlistTable entries={tierA} tier="A" />
      </div>
    </div>
  )
}
