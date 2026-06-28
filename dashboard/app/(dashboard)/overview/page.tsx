'use client'

import { useDashboard } from '@/hooks/useDashboardState'
import { MetricCard } from '@/components/MetricCard'
import { PnLChart } from '@/components/PnLChart'
import { PositionsCard } from '@/components/PositionsCard'
import { SignalFeed } from '@/components/SignalFeed'
import { InfoHint } from '@/components/Tooltip'
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

  return (
    <div className="view">
      <div className="page-head">
        <div>
          <h1>Overview</h1>
          <p className="lede">
            Today at a glance — how much the bot has made or lost, what it’s holding,
            and what it just did. Status and the kill switch live in the top bar.
          </p>
        </div>
      </div>

      {/* Metrics */}
      <div className="metrics-grid">
        <MetricCard
          label="Day P&L"
          value={`$${dayPnl}`}
          delta={`Daily stop: $${maxLoss}`}
          icon={<DollarSign size={14} />}
          sentiment={pnlSentiment(dayPnl)}
          hint="Profit or loss for today so far. Green is up, red is down. Trading stops automatically if losses reach the daily stop."
        />
        <MetricCard
          label="Win Rate"
          value={winRate}
          delta={`${risk?.wins_today ?? 0}W / ${risk?.losses_today ?? 0}L`}
          icon={<Target size={14} />}
          hint="Share of today’s closed trades that made money. e.g. 60% means 6 of every 10 trades were winners."
        />
        <MetricCard
          label="Losing Streak"
          value={String(consLosses)}
          delta="Auto-halt at 3"
          icon={<AlertCircle size={14} />}
          sentiment={consLosses >= 2 ? 'negative' : 'neutral'}
          hint="Losses in a row. After 3 straight losses the bot stops trading for the day to avoid digging a deeper hole."
        />
        <MetricCard
          label="Open Positions"
          value={String(positions.length)}
          icon={<TrendingUp size={14} />}
          hint="How many stocks the bot currently holds. All positions are sold before the market closes — nothing is held overnight."
        />
      </div>

      {/* P&L Chart */}
      <div className="card">
        <div className="panel-title">
          <div>
            <h3>
              Session P&amp;L
              <InfoHint label="How your profit/loss has moved through the day. The line starts at zero each morning." />
            </h3>
            <p className="support">Running total since the open</p>
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
              <h3>
                Open Positions
                <InfoHint label="Stocks the bot owns right now and how each one is doing." />
              </h3>
              <p className="support">{positions.length} active</p>
            </div>
          </div>
          <PositionsCard positions={positions} />
        </div>

        <div className="card">
          <div className="panel-title">
            <div>
              <h3>
                Signal Feed
                <InfoHint label="A live stream of what the bot is doing — buys, sells, and trades it chose to skip." />
              </h3>
              <p className="support">Most recent first</p>
            </div>
          </div>
          <SignalFeed signals={signals} limit={20} />
        </div>
      </div>
    </div>
  )
}
