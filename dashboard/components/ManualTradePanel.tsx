'use client'

import { useState } from 'react'
import { api } from '@/lib/api'
import { useDashboard } from '@/hooks/useDashboardState'
import { useChartSymbol } from '@/hooks/useChartSymbol'

/**
 * Manual test-trade desk for the Command Center.
 *
 * Lets the operator place a paper order with Ross's OWN execution rules (limit-only, U7)
 * and watch it flow through the SAME risk gate the autonomous bot uses (U4 daily-loss,
 * U5 3-strikes, sizing/cushion §5/§6). The gate can VETO or RESIZE — exactly like a real
 * bot entry. This is how you confirm the strategy + Alpaca wiring work end-to-end:
 * the fill, the position, and the P&L all appear in the panels around it.
 *
 * BUY routes through the hard gate; SELL is an exit. "Use last price" pulls the most
 * recent 1-min close from GET /api/bars so the limit is realistic.
 */
export function ManualTradePanel() {
  const { refetch } = useDashboard()
  const { setSymbol: setChartSymbol } = useChartSymbol()

  const [symbol, setSymbol] = useState('')
  const [side, setSide] = useState<'BUY' | 'SELL'>('BUY')
  const [qty, setQty] = useState('')
  const [limit, setLimit] = useState('')
  const [busy, setBusy] = useState(false)
  const [priceBusy, setPriceBusy] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null)

  const sym = symbol.toUpperCase().trim()

  async function useLastPrice() {
    if (!sym) return
    setPriceBusy(true)
    setResult(null)
    try {
      const { bars } = await api.getBars(sym, 1)
      const last = bars[bars.length - 1]
      if (last) {
        setLimit(last.close)
        setChartSymbol(sym)
      } else {
        setResult({ ok: false, text: `No recent bars for ${sym}.` })
      }
    } catch (e) {
      setResult({ ok: false, text: String(e) })
    } finally {
      setPriceBusy(false)
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setResult(null)
    try {
      const r = await api.manualOrder({
        symbol: sym,
        side,
        qty: Number(qty),
        limit_price: Number(limit),
      })
      if (r.approved === false) {
        setResult({ ok: false, text: `🛑 Risk manager VETOED: ${r.veto}` })
      } else if (r.ok) {
        const sized = r.qty ?? qty
        setResult({
          ok: true,
          text: `✅ ${side} ${sized} ${sym} @ $${r.limit_price ?? limit} — status ${r.status}. Watch the Positions / P&L panels.`,
        })
        setChartSymbol(sym)
        await refetch()
      } else {
        setResult({ ok: false, text: `Order not accepted: ${JSON.stringify(r)}` })
      }
    } catch (e2) {
      setResult({ ok: false, text: String(e2) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card manual-trade-panel" onSubmit={submit}>
      <header className="card-head">
        <h3>Place a Test Trade</h3>
      </header>
      <p className="muted small">
        Trade the strategy by hand on the live Alpaca paper account. Same rules as the bot:
        limit-only (U7), routed through the risk gate (it can veto or resize). The fill,
        position, and P&L show up in the panels on this page.
      </p>

      <div className="control-group">
        <span className="control-eyebrow">Side</span>
        <div className="toggle-pair">
          <button
            type="button"
            className={`btn btn-sm ${side === 'BUY' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setSide('BUY')}
          >
            BUY (entry)
          </button>
          <button
            type="button"
            className={`btn btn-sm ${side === 'SELL' ? 'btn-warn' : 'btn-ghost'}`}
            onClick={() => setSide('SELL')}
          >
            SELL (exit)
          </button>
        </div>
      </div>

      <div className="manual-trade-grid">
        <label className="model-field">
          <span className="control-eyebrow">Symbol</span>
          <input
            className="input input-sm"
            placeholder="e.g. MLGO"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
          />
        </label>
        <label className="model-field">
          <span className="control-eyebrow">Shares</span>
          <input
            className="input input-sm"
            placeholder="100"
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            inputMode="numeric"
          />
        </label>
        <label className="model-field">
          <span className="control-eyebrow">Limit price ($)</span>
          <div className="toggle-pair">
            <input
              className="input input-sm"
              placeholder="4.30"
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
              inputMode="decimal"
            />
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              onClick={useLastPrice}
              disabled={!sym || priceBusy}
              title="Prefill with the most recent 1-min close"
            >
              {priceBusy ? '…' : 'Last'}
            </button>
          </div>
        </label>
      </div>

      <button
        className="btn btn-primary btn-block"
        type="submit"
        disabled={busy || !sym || !qty || !limit}
      >
        {busy ? 'Submitting…' : `Submit ${side} (Paper)`}
      </button>

      {result && (
        <p className={result.ok ? 'ok-text small' : 'error-text small'}>{result.text}</p>
      )}
    </form>
  )
}
