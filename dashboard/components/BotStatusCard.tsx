'use client'

import type { HealthOut, RiskState } from '@/lib/types'

// HealthOut is extended by the engine with runtime-only fields
type HealthRich = HealthOut & {
  session?: string
  market_active?: boolean
  et_time?: string
}

function clientEtTime(): string {
  return new Date().toLocaleTimeString('en-US', {
    timeZone: 'America/New_York',
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function clientSession(): string {
  const et = new Date(
    new Date().toLocaleString('en-US', { timeZone: 'America/New_York' })
  )
  const day = et.getDay()
  if (day === 0 || day === 6) return 'CLOSED'
  const m = et.getHours() * 60 + et.getMinutes()
  if (m < 240) return 'CLOSED'
  if (m < 570) return 'PREMARKET'
  if (m < 960) return 'RTH'
  if (m < 1200) return 'AFTERHOURS'
  return 'CLOSED'
}

function inEntryWindow(): boolean {
  const et = new Date(
    new Date().toLocaleString('en-US', { timeZone: 'America/New_York' })
  )
  const day = et.getDay()
  if (day === 0 || day === 6) return false
  const m = et.getHours() * 60 + et.getMinutes()
  return m >= 420 && m <= 660 // 07:00–11:00
}

interface Props {
  risk: RiskState | undefined
  health: HealthRich | undefined
}

export function BotStatusCard({ risk, health }: Props) {
  const pnl = Number(risk?.day_pnl ?? 0)
  const pnlStr = pnl >= 0 ? `+$${pnl.toFixed(2)}` : `-$${Math.abs(pnl).toFixed(2)}`
  const pnlClass = pnl > 0 ? 'pos' : pnl < 0 ? 'neg' : ''

  const session = health?.session ?? clientSession()
  const etTime = health?.et_time ?? clientEtTime()
  const windowOpen = inEntryWindow()
  const brokerOk = health?.all_healthy ?? false
  const isHalted = risk?.is_halted ?? false
  const isPaused = risk?.is_paused ?? false
  const losses = risk?.consecutive_losses ?? 0

  const botState = isHalted
    ? { label: 'HALTED', cls: 'neg', sub: risk?.halt_reason ?? 'day halted' }
    : isPaused
      ? { label: 'PAUSED', cls: 'warn-text', sub: 'no new entries' }
      : { label: 'ACTIVE', cls: 'pos', sub: 'scanning & trading' }

  return (
    <div className="card bs-card">
      <div className="bs-row">

        {/* Bot state */}
        <div className="bs-cell">
          <span className="bs-label">Bot</span>
          <span className={`bs-value ${botState.cls}`}>{botState.label}</span>
          <span className="bs-sub">{botState.sub}</span>
        </div>

        {/* Market session */}
        <div className="bs-cell">
          <span className="bs-label">Session</span>
          <span className="bs-value mono">{session}</span>
          <span className="bs-sub mono">{etTime} ET</span>
        </div>

        {/* Entry window */}
        <div className="bs-cell">
          <span className="bs-label">Entry Window</span>
          <span className={`bs-value ${windowOpen ? 'pos' : 'muted'}`}>
            {windowOpen ? 'OPEN' : 'OUTSIDE'}
          </span>
          <span className="bs-sub">07:00–11:00 ET</span>
        </div>

        {/* Broker */}
        <div className="bs-cell">
          <span className="bs-label">Broker</span>
          <span className={`bs-value ${brokerOk ? 'pos' : 'neg'}`}>
            {brokerOk ? 'Connected' : 'Offline'}
          </span>
          <span className="bs-sub">Alpaca paper</span>
        </div>

        {/* P&L */}
        <div className="bs-cell">
          <span className="bs-label">Day P&amp;L</span>
          <span className={`bs-value mono ${pnlClass}`}>{pnlStr}</span>
          <span className="bs-sub">
            {risk?.trades_today ?? 0} trades · {risk?.wins_today ?? 0}W {risk?.losses_today ?? 0}L
          </span>
        </div>

        {/* 3-strikes */}
        <div className="bs-cell">
          <span className="bs-label">Streak</span>
          <span className={`bs-value ${losses >= 2 ? 'neg' : ''}`}>{losses} / 3</span>
          <span className="bs-sub">consecutive losses</span>
        </div>

      </div>
    </div>
  )
}
