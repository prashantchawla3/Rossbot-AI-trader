'use client'

import { useDashboard } from '@/hooks/useDashboardState'

const money = (v: number) =>
  `${v >= 0 ? '+' : '-'}$${Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

function timeLeft(etTime?: string): string {
  // Minutes until the 11:00 ET hard-stop, from the demo health.et_time (HH:MM:SS ET).
  if (!etTime) return '—'
  const [h, m] = etTime.split(':').map(Number)
  if (Number.isNaN(h)) return '—'
  const mins = 11 * 60 - (h * 60 + m)
  if (mins <= 0) return 'closed'
  return `${Math.floor(mins / 60)}h ${mins % 60}m`
}

/** Always-visible status strip: bot state, P&L, positions, trades, time-left, market. */
export function StatusBar() {
  const { state } = useDashboard()
  const data = state.data
  const risk = data?.risk
  // Demo health carries extra fields (et_time, market_active) beyond the typed HealthOut.
  const health = data?.health as unknown as Record<string, unknown> | undefined

  const day = Number(risk?.day_pnl ?? 0)
  const halted = risk?.is_halted ?? false
  const paused = risk?.is_paused ?? false
  const status = halted ? 'HALTED' : paused ? 'PAUSED' : state.status === 'live' ? 'ACTIVE' : 'CONNECTING'
  const statusClass = halted ? 'st-halted' : paused ? 'st-paused' : status === 'ACTIVE' ? 'st-active' : 'st-connecting'
  const marketActive = (health?.market_active as boolean | undefined) ?? false
  const etTime = health?.et_time as string | undefined

  return (
    <div className="status-bar">
      <span className={`status-pill ${statusClass}`}>
        <span className="status-led" /> BOT: {status}
      </span>
      <span className="status-item">
        Day P&L:{' '}
        <strong className={day >= 0 ? 'pos' : 'neg'}>{money(day)}</strong>
      </span>
      <span className="status-item">
        Positions: <strong>{data?.positions.length ?? 0}</strong>
      </span>
      <span className="status-item">
        Trades: <strong>{risk?.trades_today ?? 0}</strong>
      </span>
      <span className="status-item">
        Time Left: <strong>{timeLeft(etTime)}</strong>
      </span>
      <span className="status-item">
        Market: <strong className={marketActive ? 'pos' : 'muted'}>{marketActive ? 'OPEN' : 'CLOSED'}</strong>
      </span>
    </div>
  )
}
