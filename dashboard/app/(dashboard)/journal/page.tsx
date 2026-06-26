'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import type { SessionJournal } from '@/lib/types'
import { Badge } from '@/components/Badge'

function pnlColor(pnl: string) {
  const n = parseFloat(pnl)
  if (n > 0) return 'var(--success)'
  if (n < 0) return 'var(--destructive)'
  return 'inherit'
}

export default function JournalPage() {
  const [journal, setJournal] = useState<SessionJournal | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.getJournal()
      .then(setJournal)
      .catch((err: unknown) => setError(String(err)))
  }, [])

  if (error) {
    return (
      <div className="view">
        <div className="topbar">
          <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 600 }}>Journal</h1>
        </div>
        <div className="card">
          <p className="small muted">Could not load journal: {error}</p>
        </div>
      </div>
    )
  }

  if (!journal) {
    return (
      <div className="view">
        <div className="topbar">
          <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 600 }}>Journal</h1>
        </div>
        <div className="card">
          <p className="small muted">Loading...</p>
        </div>
      </div>
    )
  }

  const totalPnl = parseFloat(journal.total_pnl)

  return (
    <div className="view">
      <div className="topbar">
        <div>
          <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 600, letterSpacing: '-0.012em' }}>
            Session Journal
          </h1>
          <p className="small muted" style={{ marginTop: '4px' }}>
            {journal.date} — post-session trade report
          </p>
        </div>
      </div>

      {/* Session summary */}
      <div className="metrics-grid">
        <div className="metric-card">
          <span className="eyebrow">Total P&L</span>
          <span
            className="metric-value"
            style={{ color: pnlColor(journal.total_pnl) }}
          >
            ${journal.total_pnl}
          </span>
        </div>
        <div className="metric-card" style={{ borderLeft: '1px solid var(--color-border)' }}>
          <span className="eyebrow">Win Rate</span>
          <span className="metric-value">
            {journal.win_rate}
          </span>
          <span className="kpi-delta">{journal.num_wins}W / {journal.num_losses}L</span>
        </div>
        <div className="metric-card" style={{ borderLeft: '1px solid var(--color-border)' }}>
          <span className="eyebrow">Max Drawdown</span>
          <span className="metric-value negative">{journal.max_drawdown}</span>
        </div>
        <div className="metric-card" style={{ borderLeft: '1px solid var(--color-border)' }}>
          <span className="eyebrow">Trades</span>
          <span className="metric-value">{journal.trades.length}</span>
        </div>
      </div>

      {/* Trade table */}
      <div className="card">
        <div className="panel-title">
          <div>
            <h3>Trade Log</h3>
            <p className="support">All fills for the session</p>
          </div>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Side</th>
              <th>Shares</th>
              <th>Entry</th>
              <th>Exit</th>
              <th>Realised P&L</th>
              <th>Spec Refs</th>
            </tr>
          </thead>
          <tbody>
            {journal.trades.map((t, i) => (
              <tr key={i}>
                <td><strong>{t.symbol}</strong></td>
                <td>
                  <Badge variant={t.side === 'long' ? 'success' : 'warn'}>{t.side}</Badge>
                </td>
                <td className="mono">{t.shares.toLocaleString()}</td>
                <td className="mono">${t.entry_price}</td>
                <td className="mono">{t.exit_price ? `$${t.exit_price}` : '—'}</td>
                <td>
                  <span
                    className="mono"
                    style={{ color: pnlColor(t.realised_pnl) }}
                  >
                    ${t.realised_pnl}
                  </span>
                </td>
                <td className="small muted">{t.spec_refs.join(', ') || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <p className="footnote">
          Generated {new Date(journal.generated_at).toLocaleString('en-US', { timeZone: 'America/New_York' })} ET
        </p>
      </div>
    </div>
  )
}
