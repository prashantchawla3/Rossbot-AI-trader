'use client'

import { useState } from 'react'
import { useDashboard } from '@/hooks/useDashboardState'
import { useChartSymbol } from '@/hooks/useChartSymbol'
import { PositionControls } from '@/components/PositionControls'
import { Term } from '@/components/Term'
import type { OpenPosition, SignalEvent } from '@/lib/types'

// Rough "closest exit rule" hint from entry vs current — Ross's exit ladder (P1–P8).
function closestExit(p: OpenPosition): string {
  const entry = Number(p.avg_price)
  const cur = Number(p.current_price)
  const movePct = entry > 0 ? ((cur - entry) / entry) * 100 : 0
  if (cur < entry) return 'P1 — Mental Stop (price below entry)'
  if (movePct >= 4) return 'P5 — Scale target near (+5% rule)'
  return 'P2 — Time / bailout watch'
}

export default function SignalsPage() {
  const { state } = useDashboard()
  const { setSymbol } = useChartSymbol()
  const positions = state.data?.positions ?? []
  const signals = state.data?.recent_signals ?? []

  return (
    <div className="view">
      <div className="page-head">
        <div>
          <h1>Positions &amp; Signals</h1>
          <p className="muted">Manage open trades and watch every decision the bot makes, live.</p>
        </div>
      </div>

      <div className="card">
        <header className="card-head">
          <h3>Active Positions</h3>
          <span className="muted small">{positions.length} open</span>
        </header>
        <table className="table compact">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Shares</th>
              <th>Entry</th>
              <th>Current</th>
              <th>P&L $</th>
              <th>P&L %</th>
              <th>Closest Exit</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {positions.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  No open positions.
                </td>
              </tr>
            )}
            {positions.map((p) => {
              const entry = Number(p.avg_price)
              const cur = Number(p.current_price)
              const pnl = Number(p.unrealised_pnl)
              const pnlPct = entry > 0 ? ((cur - entry) / entry) * 100 : 0
              return (
                <tr key={p.symbol}>
                  <td className="mono strong link" onClick={() => setSymbol(p.symbol)}>
                    {p.symbol}
                  </td>
                  <td className="mono">{p.shares}</td>
                  <td className="mono">${p.avg_price}</td>
                  <td className="mono">${p.current_price}</td>
                  <td className={`mono ${pnl >= 0 ? 'pos' : 'neg'}`}>
                    {pnl >= 0 ? '+' : '-'}${Math.abs(pnl).toFixed(2)}
                  </td>
                  <td className={`mono ${pnlPct >= 0 ? 'pos' : 'neg'}`}>{pnlPct.toFixed(2)}%</td>
                  <td className="small">
                    <Term term="Mental Stop">{closestExit(p)}</Term>
                  </td>
                  <td>
                    <PositionControls position={p} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="card">
        <header className="card-head">
          <h3>Signals Feed</h3>
          <span className="muted small">last {Math.min(signals.length, 20)} of {signals.length}</span>
        </header>
        <div className="signal-cards">
          {signals.length === 0 && <p className="muted">No signals yet.</p>}
          {signals.slice(0, 20).map((s) => (
            <SignalCard key={s.id} signal={s} onView={() => setSymbol(s.symbol)} />
          ))}
        </div>
      </div>
    </div>
  )
}

function SignalCard({ signal, onView }: { signal: SignalEvent; onView: () => void }) {
  const [open, setOpen] = useState(false)
  const fired = signal.action === 'entry'
  const veto = signal.action === 'veto'
  const detail = signal.detail ?? {}
  const gates = (detail.gates as Record<string, unknown>) ?? {}
  const ts = new Date(signal.ts).toLocaleTimeString('en-US', { hour12: false })

  return (
    <div className={`signal-card ${fired ? 'fired' : veto ? 'blocked' : 'info'}`}>
      <button className="signal-head" onClick={() => setOpen((o) => !o)}>
        <span className="signal-dot">{fired ? '🟢' : veto ? '🔴' : '⚪'}</span>
        <span className="signal-title">
          {fired ? 'SIGNAL FIRED' : veto ? 'SIGNAL BLOCKED' : signal.event_type.toUpperCase()} —{' '}
          <strong className="mono">{signal.symbol}</strong>
        </span>
        <span className="signal-time mono">{ts}</span>
        <span className="signal-caret">{open ? '▾' : '▸'}</span>
      </button>
      <div className="signal-gates mono small">
        {Object.entries(gates).map(([k, v]) => (
          <span key={k} className={v ? 'pos' : 'neg'}>
            {k} {v ? '✓' : '✗'}
          </span>
        ))}
      </div>
      {open && (
        <div className="signal-detail">
          <dl>
            {Object.entries(detail)
              .filter(([k]) => k !== 'gates')
              .map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd className="mono">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd>
                </div>
              ))}
          </dl>
          <button className="btn btn-sm btn-ghost" onClick={onView}>
            View chart
          </button>
        </div>
      )}
    </div>
  )
}
