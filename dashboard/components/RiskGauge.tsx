'use client'

import type { RiskState } from '@/lib/types'
import { TermHint } from './Term'

const money = (v: number) =>
  `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

/**
 * Vertical Day-P&L gauge with the four spec zones:
 *   GREEN  profitable (≥ $0)
 *   YELLOW 0 → -25% give-back (warning)
 *   ORANGE -25% → -50% give-back (reduce size)
 *   RED    -50%+ give-back OR below the daily loss limit (HALT)
 * Plus the consecutive-loss counter (3 strikes ends the day).
 */
export function RiskGauge({ risk }: { risk: RiskState }) {
  const day = Number(risk.day_pnl)
  const peak = Number(risk.peak_pnl)
  const maxLoss = Number(risk.max_daily_loss)
  const giveBack = peak > 0 ? Math.max(0, (peak - day) / peak) : 0
  const losses = risk.consecutive_losses

  let zone: 'green' | 'yellow' | 'orange' | 'red' = 'green'
  let threshold = ''
  if (day <= -maxLoss || giveBack >= 0.5) {
    zone = 'red'
    threshold = 'HALT threshold reached'
  } else if (giveBack >= 0.25) {
    zone = 'orange'
    threshold = `Reduce size — ${(50 - giveBack * 100).toFixed(0)}% give-back until halt`
  } else if (day < 0 || (peak > 0 && giveBack > 0)) {
    zone = 'yellow'
    threshold = `Give-back warning — ${(25 - giveBack * 100).toFixed(0)}% until reduce-size`
  } else {
    threshold = `Cushion intact — ${money(day + maxLoss)} until daily stop`
  }

  // Fill height maps day P&L within [-maxLoss, +maxLoss].
  const pct = Math.max(0, Math.min(100, ((day + maxLoss) / (2 * maxLoss)) * 100))

  return (
    <div className="risk-gauge card">
      <header className="card-head">
        <h3>
          Day P&L Risk <TermHint term="Give-back" />
        </h3>
        <span className={`zone-badge zone-${zone}`}>{zone.toUpperCase()}</span>
      </header>

      <div className="gauge-row">
        <div className="gauge-track">
          <div className={`gauge-fill zone-${zone}`} style={{ height: `${pct}%` }} />
          <span className="gauge-zero" />
        </div>
        <dl className="gauge-stats">
          <div>
            <dt>Current P&L</dt>
            <dd className={day >= 0 ? 'pos' : 'neg'}>{money(day)}</dd>
          </div>
          <div>
            <dt>Peak today</dt>
            <dd>{money(peak)}</dd>
          </div>
          <div>
            <dt>Give-back</dt>
            <dd>{(giveBack * 100).toFixed(0)}%</dd>
          </div>
          <div>
            <dt>Daily loss limit</dt>
            <dd>{money(-maxLoss)}</dd>
          </div>
        </dl>
      </div>

      <p className="gauge-threshold">{threshold}</p>

      <div className="strike-row">
        <span className="strike-label">
          Losses <TermHint term="3-Strikes Rule" />
        </span>
        <span className="strike-dots">
          {[0, 1, 2].map((i) => (
            <span key={i} className={`strike-dot ${i < losses ? 'on' : ''}`} />
          ))}
        </span>
        <span className="strike-count">{losses}/3 — next loss halts trading</span>
      </div>
    </div>
  )
}
