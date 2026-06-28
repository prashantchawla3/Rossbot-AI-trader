'use client'

import { useEffect, useRef, useState } from 'react'

declare global {
  interface Window {
    TradingView?: { widget: new (config: Record<string, unknown>) => unknown }
  }
}

const TV_SRC = 'https://s3.tradingview.com/tv.js'
const EXCHANGE = 'NASDAQ'

let scriptPromise: Promise<void> | null = null

function loadTradingView(): Promise<void> {
  if (typeof window === 'undefined') return Promise.reject(new Error('no window'))
  if (window.TradingView) return Promise.resolve()
  if (scriptPromise) return scriptPromise
  scriptPromise = new Promise<void>((resolve, reject) => {
    const el = document.createElement('script')
    el.src = TV_SRC
    el.async = true
    el.onload = () => resolve()
    el.onerror = () => {
      scriptPromise = null
      reject(new Error('tv-load-failed'))
    }
    document.head.appendChild(el)
  })
  return scriptPromise
}

/**
 * TradingView free embed (no API key) — 1-min candles with the exact indicators Ross
 * uses: MACD (E4 gate), 9 EMA (pullback touch), VWAP (exit guard). Loads tv.js
 * dynamically (hydration-safe) and rebuilds the widget when `symbol` changes. If the
 * script is blocked (CSP/offline) it falls back to a lightweight OHLC table from
 * GET /api/bars/{symbol}.
 */
export function TradingViewChart({ symbol, height = 500 }: { symbol: string; height?: number }) {
  const containerId = useRef(`tv_${Math.random().toString(36).slice(2)}`)
  const [blocked, setBlocked] = useState(false)
  const ticker = `${EXCHANGE}:${(symbol || 'AAPL').toUpperCase().trim()}`

  useEffect(() => {
    let cancelled = false
    loadTradingView()
      .then(() => {
        if (cancelled || !window.TradingView) return
        const node = document.getElementById(containerId.current)
        if (node) node.innerHTML = ''
        new window.TradingView.widget({
          autosize: true,
          symbol: ticker,
          interval: '1', // 1-minute — Ross's primary timeframe
          timezone: 'America/New_York',
          theme: 'dark',
          style: '1', // candlesticks
          locale: 'en',
          toolbar_bg: '#0b0f1a',
          enable_publishing: false,
          hide_side_toolbar: false,
          allow_symbol_change: true,
          studies: ['MACD@tv-basicstudies', 'MAExp@tv-basicstudies', 'VWAP@tv-basicstudies'],
          container_id: containerId.current,
        })
      })
      .catch(() => {
        if (!cancelled) setBlocked(true)
      })
    return () => {
      cancelled = true
    }
  }, [ticker])

  if (blocked) return <LightweightFallback symbol={symbol} height={height} />

  return (
    <div className="tv-wrap" style={{ height }}>
      <div id={containerId.current} className="tv-container" style={{ height }} />
    </div>
  )
}

// ── Fallback: render last bars from the backend if TradingView is unreachable ──

import { api } from '@/lib/api'
import type { Bar } from '@/lib/types'

function LightweightFallback({ symbol, height }: { symbol: string; height: number }) {
  const [bars, setBars] = useState<Bar[]>([])
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    api
      .getBars(symbol, 50)
      .then((r) => {
        if (alive) setBars(r.bars)
      })
      .catch((e) => alive && setErr(String(e)))
    return () => {
      alive = false
    }
  }, [symbol])

  return (
    <div className="tv-fallback" style={{ height, overflowY: 'auto' }}>
      <p className="muted">
        TradingView could not load (offline or blocked). Showing the last bars for {symbol} from
        the bot feed.
      </p>
      {err && <p className="error-text">{err}</p>}
      {!err && bars.length === 0 && <p className="muted">No bar data available.</p>}
      {bars.length > 0 && (
        <table className="table compact">
          <thead>
            <tr>
              <th>Time</th>
              <th>O</th>
              <th>H</th>
              <th>L</th>
              <th>C</th>
              <th>Vol</th>
            </tr>
          </thead>
          <tbody>
            {bars
              .slice()
              .reverse()
              .map((b) => (
                <tr key={b.time}>
                  <td className="mono">{new Date(b.time * 1000).toLocaleTimeString('en-US')}</td>
                  <td className="mono">{b.open}</td>
                  <td className="mono">{b.high}</td>
                  <td className="mono">{b.low}</td>
                  <td className="mono">{b.close}</td>
                  <td className="mono">{b.volume.toLocaleString()}</td>
                </tr>
              ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
