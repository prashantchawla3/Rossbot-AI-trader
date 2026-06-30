'use client'

import type { HealthOut } from '@/lib/types'
import { useDashboard } from '@/hooks/useDashboardState'
import { BotStatusCard } from '@/components/BotStatusCard'
import { ActivityTimeline } from '@/components/ActivityTimeline'
import { PillarDots } from '@/components/PillarDots'

type HealthRich = HealthOut & {
  session?: string
  market_active?: boolean
  et_time?: string
}

export default function LivePage() {
  const { state } = useDashboard()
  const data = state.data

  const tierA = data?.watchlist_tier_a ?? []
  const tierB = data?.watchlist_tier_b ?? []
  const topScan = [...tierA, ...tierB].slice(0, 12)

  const signals = data?.recent_signals ?? []
  const riskEvents = data?.recent_risk_events ?? []
  const positions = data?.positions ?? []

  return (
    <div className="view">

      <div className="page-head">
        <div>
          <h1>Live Activity</h1>
          <p className="muted">
            Every scan, signal, order, and exit as it happens. Entry window: 07:00–11:00 ET weekdays.
          </p>
        </div>
      </div>

      {/* Status strip */}
      <BotStatusCard
        risk={data?.risk}
        health={data?.health as HealthRich | undefined}
      />

      {/* Two-column: scan + positions */}
      <div className="cc-grid" style={{ marginTop: 20 }}>

        {/* Latest scan */}
        <div className="card">
          <header className="card-head">
            <h3>Latest Scan</h3>
            <span className="muted small">{tierA.length} Tier-A · {tierB.length} Tier-B</span>
          </header>
          {topScan.length === 0 ? (
            <p className="muted small">No movers yet — bot scans every 60 s.</p>
          ) : (
            <div className="scan-card-grid">
              {topScan.map(e => (
                <div key={e.symbol} className="scan-row">
                  <span className={`scan-tier ${e.tier === 'A' ? 'tier-a' : ''}`}>{e.tier}</span>
                  <span className="scan-sym">{e.symbol}</span>
                  <div className="scan-meta">
                    {e.price && <span>${e.price}</span>}
                    {e.change_pct && (
                      <span className={parseFloat(e.change_pct) >= 0 ? 'pos' : 'neg'}>
                        {parseFloat(e.change_pct) >= 0 ? '+' : ''}{e.change_pct}%
                      </span>
                    )}
                    {e.rvol && <span>rvol {e.rvol}x</span>}
                    {e.catalyst && <span>{e.catalyst.slice(0, 28)}</span>}
                  </div>
                  {e.pillar_flags && Object.keys(e.pillar_flags).length > 0 && (
                    <PillarDots flags={e.pillar_flags} />
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Open positions mini-card */}
        <div className="card">
          <header className="card-head">
            <h3>Open Positions</h3>
            <span className="muted small">{positions.length} active</span>
          </header>
          {positions.length === 0 ? (
            <p className="muted small">No open positions.</p>
          ) : (
            <div className="list">
              {positions.map(p => {
                const pnl = parseFloat(p.unrealised_pnl)
                const cls = pnl > 0 ? 'pos' : pnl < 0 ? 'neg' : ''
                return (
                  <div key={p.symbol} className="activity-row" style={{ gap: 12 }}>
                    <span style={{ fontWeight: 700, minWidth: 60 }}>{p.symbol}</span>
                    <span className="muted small">
                      {p.shares} shs @ ${p.avg_price}
                    </span>
                    <span style={{ marginLeft: 'auto', fontWeight: 600 }} className={cls}>
                      {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </div>

      </div>

      {/* Timeline */}
      <div className="card" style={{ marginTop: 20 }}>
        <header className="card-head">
          <h3>Activity Timeline</h3>
          <span className="muted small">
            {signals.length} signals · {riskEvents.length} events · newest first
          </span>
        </header>
        <ActivityTimeline signals={signals} riskEvents={riskEvents} />
      </div>

    </div>
  )
}
