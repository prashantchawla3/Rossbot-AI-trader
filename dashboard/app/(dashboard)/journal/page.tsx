'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { MetricCard } from '@/components/MetricCard'
import type { JournalTrade, SessionSummary } from '@/lib/types'

const RULES: { q: string; a: string }[] = [
  {
    q: 'What is Tier A vs Tier B?',
    a: 'Tier A is the wide net — stocks moving enough to watch. Tier B has passed all 5 of Ross’s Five Pillars and is the only kind the bot will trade.',
  },
  {
    q: 'Why did the bot not trade that symbol?',
    a: 'Every entry is an AND-gate of E1–E7. If any one fails — most commonly E4 (MACD not positive) or a missing catalyst (P5) — the trade is skipped. The Signals feed shows exactly which gate failed.',
  },
  {
    q: 'What is RVOL?',
    a: 'Relative Volume — today’s volume vs the 50-day average. 5x means five times normal activity. Ross requires ≥5x (Pillar P3).',
  },
  {
    q: 'What is the 3-strikes rule?',
    a: 'Three consecutive losing trades ends trading for the day. It stops a bad streak from compounding (spec U5).',
  },
  {
    q: 'What is a mental stop?',
    a: 'The bot tracks the stop price internally and exits if it breaks — it never places a resting stop order with the broker, because market makers hunt visible stops (spec U13).',
  },
  {
    q: 'What is the cushion / icebreaker size?',
    a: 'While the day’s P&L is negative, position size is cut to about a quarter of normal. The bot only sizes up once it’s green for the day (spec §5).',
  },
  {
    q: 'What is the daily loss limit / give-back?',
    a: 'If the day P&L drops below the limit, or gives back 50% of the peak profit, the bot halts for the day (spec U4).',
  },
]

export default function JournalPage() {
  const [trades, setTrades] = useState<JournalTrade[]>([])
  const [summary, setSummary] = useState<SessionSummary | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [openRule, setOpenRule] = useState<number | null>(null)

  useEffect(() => {
    Promise.all([api.journalToday(), api.sessionSummary()])
      .then(([j, s]) => {
        setTrades(j.trades)
        setSummary(s)
      })
      .catch((e) => setErr(String(e)))
  }, [])

  const today = new Date().toLocaleDateString('en-US', { dateStyle: 'long' })

  return (
    <div className="view">
      <div className="page-head">
        <div>
          <h1>Journal &amp; History</h1>
          <p className="muted">{today} — today’s completed trades and the session summary.</p>
        </div>
        <div className="head-actions">
          <a className="btn btn-primary btn-sm" href={api.journalExportUrl()}>
            📥 Export CSV
          </a>
        </div>
      </div>

      {err && <p className="error-text">{err}</p>}

      {summary && (
        <div className="metrics-grid">
          <MetricCard
            label="Win Rate"
            value={summary.win_rate !== null ? `${Math.round(summary.win_rate * 100)}%` : '—'}
            hint="≥60% over 10 sim days is the gate for live trading (U6)."
          />
          <MetricCard
            label="Profit Factor"
            value={summary.profit_factor !== null ? summary.profit_factor.toFixed(2) : '—'}
            hint="Gross wins ÷ gross losses. Above 1.0 is profitable."
          />
          <MetricCard label="Avg Winner" value={`$${summary.avg_winner}`} sentiment="positive" />
          <MetricCard label="Avg Loser" value={`$${summary.avg_loser}`} sentiment="negative" />
        </div>
      )}

      {summary && (
        <div className="card session-summary">
          <div className="ss-grid">
            <span>Trades <b>{summary.trades}</b></span>
            <span>Wins <b className="pos">{summary.wins}</b></span>
            <span>Losses <b className="neg">{summary.losses}</b></span>
            <span>Best <b className="pos">${summary.best_trade}</b></span>
            <span>Worst <b className="neg">${summary.worst_trade}</b></span>
            <span>Realized P&L <b className={Number(summary.realized_pnl) >= 0 ? 'pos' : 'neg'}>${summary.realized_pnl}</b></span>
            <span>Rules Violated <b>{summary.rules_violated}</b></span>
          </div>
        </div>
      )}

      <div className="card">
        <header className="card-head">
          <h3>Today’s Trade Journal</h3>
          <span className="muted small">{trades.length} trades</span>
        </header>
        <table className="table compact">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Side</th>
              <th>Entry</th>
              <th>Exit</th>
              <th>Shares</th>
              <th>P&L</th>
              <th>R</th>
              <th>Exit Reason</th>
            </tr>
          </thead>
          <tbody>
            {trades.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  No completed trades yet today.
                </td>
              </tr>
            )}
            {trades.map((t, i) => {
              const pnl = Number(t.pnl)
              return (
                <tr key={i} className={pnl >= 0 ? 'row-win' : 'row-loss'}>
                  <td className="mono strong">{t.symbol}</td>
                  <td>{t.side}</td>
                  <td className="mono">${t.entry_price}</td>
                  <td className="mono">${t.exit_price}</td>
                  <td className="mono">{t.shares}</td>
                  <td className={`mono ${pnl >= 0 ? 'pos' : 'neg'}`}>
                    {pnl >= 0 ? '+' : '-'}${Math.abs(pnl).toFixed(2)}
                  </td>
                  <td className="mono">{t.r_multiple !== null ? `${t.r_multiple}R` : '—'}</td>
                  <td className="small">{t.exit_reason}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="card">
        <header className="card-head">
          <h3>Bot Rules Reference</h3>
          <span className="muted small">plain-English</span>
        </header>
        <div className="accordion">
          {RULES.map((r, i) => (
            <div key={i} className={`acc-item ${openRule === i ? 'open' : ''}`}>
              <button className="acc-head" onClick={() => setOpenRule(openRule === i ? null : i)}>
                <span>{r.q}</span>
                <span>{openRule === i ? '▾' : '▸'}</span>
              </button>
              {openRule === i && <p className="acc-body">{r.a}</p>}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
