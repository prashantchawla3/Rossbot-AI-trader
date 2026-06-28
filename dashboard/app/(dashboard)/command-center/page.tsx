'use client'

import { useDashboard } from '@/hooks/useDashboardState'
import { BotControls } from '@/components/BotControls'
import { RiskGauge } from '@/components/RiskGauge'
import { MetricCard } from '@/components/MetricCard'

export default function CommandCenterPage() {
  const { state } = useDashboard()
  const risk = state.data?.risk
  const positions = state.data?.positions ?? []
  const day = Number(risk?.day_pnl ?? 0)
  const winRate =
    risk && risk.trades_today > 0
      ? `${Math.round((risk.wins_today / (risk.wins_today + risk.losses_today || 1)) * 100)}%`
      : '—'

  return (
    <div className="view">
      <div className="page-head">
        <div>
          <h1>Command Center</h1>
          <p className="muted">Full visibility and control of the autonomous bot.</p>
        </div>
      </div>

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
    </div>
  )
}
