'use client'

import { useState } from 'react'
import { useDashboard } from '@/hooks/useDashboardState'
import { api } from '@/lib/api'
import { BotControls } from '@/components/BotControls'
import { RiskGauge } from '@/components/RiskGauge'
import { MetricCard } from '@/components/MetricCard'
import { AccountPanel } from '@/components/AccountPanel'
import { ManualTradePanel } from '@/components/ManualTradePanel'
import { PositionsCard } from '@/components/PositionsCard'
import { WatchlistTable } from '@/components/WatchlistTable'

export default function CommandCenterPage() {
  const { state, refetch } = useDashboard()
  const risk = state.data?.risk
  const positions = state.data?.positions ?? []
  const tierA = state.data?.watchlist_tier_a ?? []
  const tierB = state.data?.watchlist_tier_b ?? []
  const day = Number(risk?.day_pnl ?? 0)
  const winRate =
    risk && risk.trades_today > 0
      ? `${Math.round((risk.wins_today / (risk.wins_today + risk.losses_today || 1)) * 100)}%`
      : '—'

  const [scanMsg, setScanMsg] = useState<string | null>(null)
  const [scanning, setScanning] = useState(false)

  async function scanNow() {
    setScanning(true)
    setScanMsg(null)
    try {
      const r = await api.scanNow()
      setScanMsg(
        r.ok
          ? `Scan complete — ${r.tier_a ?? 0} Tier-A, ${r.tier_b ?? 0} Tier-B candidates.`
          : r.message ?? 'Scan returned no data.',
      )
      await refetch()
    } catch (e) {
      setScanMsg(String(e))
    } finally {
      setScanning(false)
    }
  }

  return (
    <div className="view">
      <div className="page-head">
        <div>
          <h1>Command Center</h1>
          <p className="muted">
            Full visibility and control of the bot — and your desk for placing manual test
            trades. Everything here is wired to the live Alpaca paper account and runs through
            the same risk gate the autonomous bot uses.
          </p>
        </div>
      </div>

      <AccountPanel />

      <div className="metrics-grid">
        <MetricCard
          label="Day P&L"
          value={`${day >= 0 ? '+' : '-'}$${Math.abs(day).toFixed(2)}`}
          sentiment={day >= 0 ? 'positive' : 'negative'}
          hint="Realized + unrealized profit/loss today."
        />
        <MetricCard label="Win Rate" value={winRate} hint="Winning trades vs total closed trades today." />
        <MetricCard
          label="Losing Streak"
          value={`${risk?.consecutive_losses ?? 0}/3`}
          sentiment={(risk?.consecutive_losses ?? 0) >= 2 ? 'negative' : undefined}
          hint="3 consecutive losses halts trading (U5)."
        />
        <MetricCard label="Open Positions" value={String(positions.length)} hint="Positions currently held." />
      </div>

      <div className="cc-grid">
        <BotControls />
        {risk ? <RiskGauge risk={risk} /> : <div className="card muted">Waiting for risk state…</div>}
      </div>

      <div className="cc-grid">
        <ManualTradePanel />

        <div className="card">
          <header className="card-head">
            <h3>Open Positions &amp; P&L</h3>
          </header>
          <PositionsCard positions={positions} />
          <p className="muted small" style={{ marginTop: '0.75rem' }}>
            Close or scale out individual positions from the <a href="/overview">Overview</a> page,
            or use FLATTEN ALL in Bot Controls.
          </p>
        </div>
      </div>

      <div className="card">
        <header className="card-head">
          <h3>Live Scanner Signals</h3>
          <button className="btn btn-sm btn-primary" onClick={scanNow} disabled={scanning}>
            {scanning ? 'Scanning…' : '🔄 Scan now'}
          </button>
        </header>
        <p className="muted small">
          These are the symbols the strategy flagged right now (Tier A = wide net, Tier B = passes
          the Five Pillars). Pick one, then place a test trade above to see the full flow.
        </p>
        {scanMsg && <p className="ok-text small">{scanMsg}</p>}
        <h4 className="section-eyebrow">Tier B — Five Pillars</h4>
        <WatchlistTable entries={tierB} tier="B" />
        <h4 className="section-eyebrow">Tier A — momentum candidates</h4>
        <WatchlistTable entries={tierA} tier="A" />
      </div>
    </div>
  )
}
