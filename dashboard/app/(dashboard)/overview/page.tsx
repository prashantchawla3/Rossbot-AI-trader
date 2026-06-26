'use client'

import { useDashboard } from '@/hooks/useDashboardState'
import { MetricCard } from '@/components/MetricCard'
import { KillSwitch } from '@/components/KillSwitch'
import { PnLChart } from '@/components/PnLChart'
import { PositionsCard } from '@/components/PositionsCard'
import { SignalFeed } from '@/components/SignalFeed'
import { Badge } from '@/components/Badge'
import {
  DollarSign,
  TrendingUp,
  AlertCircle,
  Target,
} from 'lucide-react'
import type { LineData } from 'lightweight-charts'

function buildChartData(dayPnl: string): LineData[] {
  const now = Math.floor(Date.now() / 1000)
  const val = parseFloat(dayPnl)
  return [
    { time: (now - 3600) as LineData['time'], value: 0 },
    { time: now as LineData['time'], value: val },
  ]
}

function pnlSentiment(pnl: string) {
  const n = parseFloat(pnl)
  if (n > 0) return 'positive' as const
  if (n < 0) return 'negative' as const
  return 'neutral' as const
}

export default function OverviewPage() {
  const { state } = useDashboard()
  const risk = state.data?.risk
  const positions = state.data?.positions ?? []
  const signals = state.data?.recent_signals ?? []

  const dayPnl = risk?.day_pnl ?? '0.00'
  const maxLoss = risk?.max_daily_loss ?? '0.00'
  const consLosses = risk?.consecutive_losses ?? 0
  const winRate =
    risk && risk.trades_today > 0
      ? `${((risk.wins_today / risk.trades_today) * 100).toFixed(0)}%`
      : '—'

  const statusVariant = risk?.is_halted
    ? 'warn'
    : risk?.is_paused
      ? 'default'
      : 'live'
  const statusLabel = risk?.is_halted
    ? `Halted${risk.halt_reason ? `: ${risk.halt_reason}` : ''}`
    : risk?.is_paused
      ? 'Paused'
      : 'Live'

  return (
    <div className="view">
      <div className="topbar">
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '16px',
          }}
        >
          <div>
            <h1
              style={{
                margin: 0,
                fontSize: '1.5rem',
                fontWeight: 600,
                letterSpacing: '-0.012em',
              }}
            >
              Overview
            </h1>
            <p className="small muted" style={{ marginTop: '4px' }}>
              Session P&amp;L, positions, live signals
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Badge variant={statusVariant}>{statusLabel}</Badge>
            <KillSwitch />
          </div>
        </div>
      </div>

      {/* Metrics */}
      <div className="metrics-grid">
        <MetricCard
          label="Day P&L"
          value={`$${dayPnl}`}
          delta={`Max loss: $${maxLoss}`}
          icon={<DollarSign size={14} />}
          sentiment={pnlSentiment(dayPnl)}
        />
        <MetricCard
          label="Win Rate"
          value={winRate}
          delta={`${risk?.wins_today ?? 0}W / ${risk?.losses_today ?? 0}L`}
          icon={<Target size={14} />}
        />
        <MetricCard
          label="Consec. Losses"
          value={String(consLosses)}
          delta="Halt at 3"
          icon={<AlertCircle size={14} />}
          sentiment={consLosses >= 2 ? 'negative' : 'neutral'}
        />
        <MetricCard
          label="Open Positions"
          value={String(positions.length)}
          icon={<TrendingUp size={14} />}
        />
      </div>

      {/* P&L Chart */}
      <div className="card">
        <div className="panel-title">
          <div>
            <h3>Session P&amp;L</h3>
            <p className="support">Intraday cumulative — flat-to-zero baseline</p>
          </div>
          <span
            className="mono small muted"
            style={{ whiteSpace: 'nowrap' }}
          >
            {state.lastUpdated
              ? state.lastUpdated.toLocaleTimeString('en-US', { hour12: false })
              : '—'}
          </span>
        </div>
        <PnLChart data={buildChartData(dayPnl)} height={140} />
      </div>

      {/* Positions + Signals */}
      <div className="content-grid">
        <div className="card">
          <div className="panel-title">
            <div>
              <h3>Open Positions</h3>
              <p className="support">{positions.length} active</p>
            </div>
          </div>
          <PositionsCard positions={positions} />
        </div>

        <div className="card">
          <div className="panel-title">
            <div>
              <h3>Signal Feed</h3>
              <p className="support">Latest 20 events</p>
            </div>
          </div>
          <SignalFeed signals={signals} limit={20} />
        </div>
      </div>
    </div>
  )
}
