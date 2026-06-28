'use client'

import { useEffect, useRef, useState } from 'react'
import dynamic from 'next/dynamic'
import { useDashboard } from '@/hooks/useDashboardState'
import { useChartSymbol } from '@/hooks/useChartSymbol'
import { api } from '@/lib/api'
import { PillarDots } from '@/components/PillarDots'
import { Term } from '@/components/Term'
import type { WatchlistEntry } from '@/lib/types'

// TradingView injects DOM directly — load client-only to avoid hydration mismatch.
const TradingViewChart = dynamic(
  () => import('@/components/TradingViewChart').then((m) => m.TradingViewChart),
  { ssr: false, loading: () => <div className="tv-loading">Loading chart…</div> },
)

function floatLabel(f: number | null): string {
  if (f === null || f === undefined) return 'UNKNOWN'
  if (f < 1_000_000) return '< 1M'
  if (f < 5_000_000) return '< 5M'
  if (f < 10_000_000) return '< 10M'
  if (f < 20_000_000) return '< 20M'
  return `${(f / 1_000_000).toFixed(0)}M`
}

export default function WatchlistPage() {
  const { state } = useDashboard()
  const { symbol, setSymbol } = useChartSymbol()
  const tierB = state.data?.watchlist_tier_b ?? []
  const tierA = state.data?.watchlist_tier_a ?? []
  const signals = state.data?.recent_signals ?? []
  const rows = [...tierB, ...tierA]

  const [scanMsg, setScanMsg] = useState<string | null>(null)
  const [addInput, setAddInput] = useState('')
  const lastSignalId = useRef<string | null>(null)

  // Auto-update the chart when a new entry signal fires (Tier B trigger).
  useEffect(() => {
    const latest = signals[0]
    if (latest && latest.action === 'entry' && latest.id !== lastSignalId.current) {
      lastSignalId.current = latest.id
      setSymbol(latest.symbol)
    }
  }, [signals, setSymbol])

  async function scanNow() {
    setScanMsg('Scanning…')
    try {
      const r = await api.scanNow()
      setScanMsg(r.ok ? `Scan done — Tier A ${r.tier_a}, Tier B ${r.tier_b}` : r.message ?? 'Scan unavailable')
    } catch (e) {
      setScanMsg(String(e))
    }
  }

  const viewedSignal = signals.find((s) => s.symbol === symbol)

  return (
    <div className="view">
      <div className="page-head">
        <div>
          <h1>Watchlist &amp; Chart</h1>
          <p className="muted">
            <Term term="Tier B">Tier B</Term> rows are tradeable; <Term term="Tier A">Tier A</Term> is the wider
            pool.
          </p>
        </div>
        <div className="head-actions">
          <button className="btn btn-primary btn-sm" onClick={scanNow}>
            🔍 Scan Now
          </button>
          <form
            className="add-symbol"
            onSubmit={(e) => {
              e.preventDefault()
              if (addInput.trim()) setSymbol(addInput)
              setAddInput('')
            }}
          >
            <input
              className="input input-sm"
              placeholder="+ Add symbol"
              value={addInput}
              onChange={(e) => setAddInput(e.target.value)}
            />
            <button className="btn btn-ghost btn-sm" type="submit">
              View
            </button>
          </form>
        </div>
      </div>
      {scanMsg && <p className="ok-text small">{scanMsg}</p>}

      <div className="wl-grid">
        <div className="card wl-table-card">
          <table className="table compact">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Price</th>
                <th>Chg %</th>
                <th>
                  <Term term="RVOL">RVOL</Term>
                </th>
                <th>
                  <Term term="Float">Float</Term>
                </th>
                <th>Tier</th>
                <th>Pillars</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td colSpan={8} className="muted">
                    No symbols on the watchlist yet — the scanner runs on a cadence, or press “Scan Now”.
                  </td>
                </tr>
              )}
              {rows.map((e: WatchlistEntry) => (
                <tr
                  key={`${e.tier}-${e.symbol}`}
                  className={`wl-row tier-${e.tier.toLowerCase()} ${e.symbol === symbol ? 'active' : ''}`}
                  onClick={() => setSymbol(e.symbol)}
                >
                  <td className="mono strong">{e.symbol}</td>
                  <td className="mono">${e.price}</td>
                  <td className={`mono ${Number(e.change_pct) >= 0 ? 'pos' : 'neg'}`}>
                    {e.change_pct ? `${e.change_pct}%` : '—'}
                  </td>
                  <td className="mono">{e.rvol}</td>
                  <td>{floatLabel(e.float_shares)}</td>
                  <td>
                    <span className={`badge tier-badge tier-${e.tier.toLowerCase()}`}>{e.tier}</span>
                  </td>
                  <td>
                    <PillarDots flags={e.pillar_flags} />
                  </td>
                  <td>
                    <button
                      className="btn btn-sm btn-ghost"
                      onClick={(ev) => {
                        ev.stopPropagation()
                        setSymbol(e.symbol)
                      }}
                    >
                      View Chart
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="wl-chart-card">
          <div className="card">
            <header className="card-head">
              <h3>
                {symbol} <span className="muted small">· 1-min · MACD / 9 EMA / VWAP</span>
              </h3>
            </header>
            <TradingViewChart symbol={symbol} height={460} />
          </div>
          <div className="card mini-signal">
            <h4>Last signal for {symbol}</h4>
            {viewedSignal ? (
              <p className="mono small">
                {Object.entries((viewedSignal.detail?.gates as Record<string, unknown>) ?? {})
                  .map(([k, v]) => `${k}${v ? '✓' : '✗'}`)
                  .join('  ')}{' '}
                — <strong className={viewedSignal.action === 'veto' ? 'neg' : 'pos'}>{viewedSignal.event_type}</strong>
              </p>
            ) : (
              <p className="muted small">No recent signal for {symbol}. Click a watchlist row to inspect.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
