'use client'

import { useEffect, useRef, useCallback, useState } from 'react'
import { api } from '@/lib/api'
import { PnLChart } from '@/components/PnLChart'
import type { EquityPoint } from '@/components/PnLChart'
import type {
  PerformanceSummary,
  TradeLogEntry,
  ScanStats,
  PerfWsMessage,
} from '@/lib/types'
import type { UTCTimestamp } from 'lightweight-charts'

// ── helpers ──────────────────────────────────────────────────────────────────

const WS_URL = (process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000') + '/ws/performance'

function pct(v: number | null, digits = 1) {
  if (v === null) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

function fmtPnl(s: string) {
  const n = Number(s)
  return `${n >= 0 ? '+' : ''}$${Math.abs(n).toFixed(2)}`
}

function sentimentFromPnl(s: string): 'positive' | 'negative' | 'neutral' {
  const n = Number(s)
  if (n > 0) return 'positive'
  if (n < 0) return 'negative'
  return 'neutral'
}

function tradeRowClass(trade: TradeLogEntry): string {
  const pnl = Number(trade.realized_pnl)
  if (!trade.is_disciplined) return 'row-violation'
  if (pnl > 0) return 'row-win'
  return 'row-disciplined-loss'
}

function tradeDot(trade: TradeLogEntry): string {
  const pnl = Number(trade.realized_pnl)
  if (!trade.is_disciplined) return '●'
  if (pnl > 0) return '▲'
  return '▼'
}

function tradeDotColor(trade: TradeLogEntry): string {
  const pnl = Number(trade.realized_pnl)
  if (!trade.is_disciplined) return 'var(--state-error)'
  if (pnl > 0) return 'var(--state-success)'
  return '#f59e0b'
}

function exitReasonLabel(reason: string): string {
  const map: Record<string, string> = {
    hard_stop: 'P1 Hard Stop',
    time_stop: 'P2 Time Stop',
    l2_reversal: 'P3 L2 Reversal',
    topping_tail: 'P4 Topping Tail',
    scale_strength: 'P5 Scale (HOD)',
    first_red_close: 'P6 First Red',
    vwap_guard: 'P7 VWAP Guard',
    lost_popularity: 'P8 Attention Out',
    P5_scale_half: 'P5 Scale Half',
    manual_close: 'Manual Close',
  }
  return map[reason] ?? reason
}

function patternLabel(p: string): string {
  const map: Record<string, string> = {
    micro_pullback: 'R1 Micro PB',
    abcd: 'R2 ABCD',
    bull_flag: 'R3 Bull Flag',
    flat_top: 'R3 Flat Top',
    gap_and_go: 'R5 Gap & Go',
    vwap_break: 'R6 VWAP Break',
    halt_resumption: 'R7 Halt Resume',
    red_to_green: 'R10 R2G',
    reverse_split_squeeze: 'R11 RevSplit',
    none: '—',
    manual: 'Manual',
  }
  return map[p] ?? p
}

function toEquityCurve(curve: PerformanceSummary['equity_curve']): EquityPoint[] {
  return curve.map((pt) => ({
    time: Math.floor(new Date(pt.ts).getTime() / 1000) as UTCTimestamp,
    value: Number(pt.cumulative_pnl),
  }))
}

// ── Live trade feed ──────────────────────────────────────────────────────────

function RecentTradesFeed({ trades, total }: { trades: TradeLogEntry[]; total: number }) {
  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
      <header className="card-head">
        <h3>Live Trade Feed</h3>
        <span className="muted small">{total} total · showing {trades.length}</span>
      </header>
      {trades.length === 0 ? (
        <div className="perf-empty-chart">
          <p className="muted small">No trades yet this session.</p>
        </div>
      ) : (
        <div className="trade-feed">
          {trades.map((t) => {
            const pnl = Number(t.realized_pnl)
            const typeClass = !t.is_disciplined ? 'tfi-violation' : pnl > 0 ? 'tfi-win' : 'tfi-loss'
            return (
              <div key={t.trade_id} className={`trade-feed-item ${typeClass}`}>
                <span className="tfi-dot" style={{ color: tradeDotColor(t) }}>
                  {tradeDot(t)}
                </span>
                <div className="tfi-body">
                  <div className="tfi-top">
                    <span className="mono strong">{t.symbol}</span>
                    <span className="small muted">{patternLabel(t.pattern_type)}</span>
                  </div>
                  <div className="tfi-bot">
                    <span className="small muted">{exitReasonLabel(t.exit_reason)}</span>
                    <span className="mono small muted">
                      {new Date(t.exit_ts).toLocaleTimeString('en-US', {
                        timeZone: 'America/New_York',
                        hour12: false,
                      })}
                    </span>
                  </div>
                </div>
                <div className="tfi-pnl">
                  <span className={`mono ${pnl >= 0 ? 'pos' : 'neg'}`}>
                    {pnl >= 0 ? '+' : '-'}${Math.abs(pnl).toFixed(2)}
                  </span>
                  {t.r_multiple !== null && (
                    <div className="mono small muted" style={{ textAlign: 'right' }}>
                      {t.r_multiple.toFixed(2)}R
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Daily P&L bar chart ──────────────────────────────────────────────────────

function DailyPnLChart({
  bars,
  maxLoss,
  warnPct,
  hardPct,
  peakPnl,
}: {
  bars: PerformanceSummary['daily_pnl']
  maxLoss: string
  warnPct: number
  hardPct: number
  peakPnl: string
}) {
  if (!bars.length) {
    return (
      <div className="perf-empty-chart">
        <p className="muted small">No daily P&L data yet — will populate as trades close.</p>
      </div>
    )
  }

  const values = bars.map((b) => Number(b.pnl))
  const maxVal = Math.max(...values.map(Math.abs), 1)
  const peak = Number(peakPnl)
  const maxLossN = Math.abs(Number(maxLoss))
  const refMax = Math.max(maxVal, maxLossN, peak > 0 ? peak * hardPct : 0) * 1.15 || 1

  return (
    <div className="daily-pnl-chart">
      <div className="daily-bars-wrap">
        {bars.map((b) => {
          const val = Number(b.pnl)
          const frac = Math.abs(val) / refMax
          const height = `${Math.max(frac * 100, 2)}%`
          const isPos = val >= 0
          return (
            <div key={b.date} className="daily-bar-col">
              <div className="daily-bar-inner" style={{ height: '100%', position: 'relative' }}>
                {isPos ? (
                  <div
                    className="daily-bar pos"
                    style={{ height, position: 'absolute', bottom: '50%', width: '100%' }}
                    title={`${b.date}: ${fmtPnl(b.pnl)}`}
                  />
                ) : (
                  <div
                    className="daily-bar neg"
                    style={{ height, position: 'absolute', top: '50%', width: '100%' }}
                    title={`${b.date}: ${fmtPnl(b.pnl)}`}
                  />
                )}
              </div>
              <span className="daily-bar-label">{b.date.slice(5)}</span>
            </div>
          )
        })}
      </div>
      <div className="perf-ref-lines">
        {peak > 0 && (
          <span className="ref-line-badge warn">
            Give-back warn ({pct(warnPct, 0)} · ${(peak * warnPct).toFixed(0)})
          </span>
        )}
        {peak > 0 && (
          <span className="ref-line-badge hard">
            Give-back halt ({pct(hardPct, 0)} · ${(peak * hardPct).toFixed(0)})
          </span>
        )}
        <span className="ref-line-badge loss">Max daily loss ${maxLossN.toFixed(0)}</span>
      </div>
    </div>
  )
}

// ── Empty-state scan summary ─────────────────────────────────────────────────

function ScanSummary({ stats }: { stats: ScanStats | null }) {
  if (!stats) return null
  return (
    <div className="card">
      <header className="card-head">
        <h3>Scanner Activity</h3>
        <span className="muted small">Symbols evaluated since session start</span>
      </header>
      <div className="perf-scan-grid" style={{ marginBottom: '1rem' }}>
        <div className="perf-scan-cell">
          <span className="perf-scan-num">{stats.symbols_scanned}</span>
          <span className="perf-scan-lbl">Symbols scanned</span>
        </div>
        <div className="perf-scan-cell">
          <span className="perf-scan-num">{stats.tier_a_count}</span>
          <span className="perf-scan-lbl">Tier-A (wide net)</span>
        </div>
        <div className="perf-scan-cell">
          <span className="perf-scan-num">{stats.tier_b_count}</span>
          <span className="perf-scan-lbl">Tier-B (all 5 pillars)</span>
        </div>
        <div className="perf-scan-cell">
          <span className="perf-scan-num neg">{stats.tier_a_count - stats.tier_b_count}</span>
          <span className="perf-scan-lbl">Rejected from Tier-B</span>
        </div>
      </div>
      {stats.rejected_from_tier_b.length > 0 && (
        <div className="perf-rejections">
          <p className="eyebrow" style={{ marginBottom: '0.5rem' }}>
            Why symbols were excluded:
          </p>
          <div className="perf-rejection-list">
            {stats.rejected_from_tier_b.slice(0, 12).map((r) => (
              <div key={r.symbol} className="perf-rejection-row">
                <span className="mono strong">{r.symbol}</span>
                <span className="muted small">{r.pillars_failed.join(', ')}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function PerformancePage() {
  const [summary, setSummary] = useState<PerformanceSummary | null>(null)
  const [trades, setTrades] = useState<TradeLogEntry[]>([])
  const [tradesTotal, setTradesTotal] = useState(0)
  const [scanStats, setScanStats] = useState<ScanStats | null>(null)
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(1)
  const [err, setErr] = useState<string | null>(null)
  const [wsConnected, setWsConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const PAGE_SIZE = 50

  const loadAll = useCallback(async (p = 1) => {
    try {
      const [s, t, sc] = await Promise.all([
        api.getPerformanceSummary(),
        api.getPerformanceTrades({ page: p, page_size: PAGE_SIZE }),
        api.getScanStats(),
      ])
      setSummary(s)
      setTrades(t.trades)
      setTradesTotal(t.total)
      setPages(t.pages)
      setScanStats(sc)
      setErr(null)
    } catch (e) {
      setErr(String(e))
    }
  }, [])

  useEffect(() => {
    loadAll(page)
  }, [loadAll, page])

  // WebSocket: receive live trade events and refresh
  useEffect(() => {
    const connect = () => {
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws

      ws.onopen = () => setWsConnected(true)
      ws.onclose = () => {
        setWsConnected(false)
        // Reconnect after 3s
        setTimeout(connect, 3000)
      }
      ws.onerror = () => ws.close()

      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data) as PerfWsMessage
          if (msg.type === 'trade_closed' || msg.type === 'performance_snapshot') {
            loadAll(1)
            setPage(1)
          }
        } catch {
          // ignore parse errors
        }
      }

      const ping = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send('ping')
      }, 25000)

      ws.onclose = () => {
        clearInterval(ping)
        setWsConnected(false)
        setTimeout(connect, 3000)
      }
    }

    connect()

    return () => {
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [loadAll])

  const equityCurve: EquityPoint[] = summary?.equity_curve ? toEquityCurve(summary.equity_curve) : []
  const hasData = (summary?.total_trades ?? 0) > 0
  const pnlValue = summary ? Number(summary.realized_pnl) : 0
  const sentiment = summary ? sentimentFromPnl(summary.realized_pnl) : 'neutral'

  return (
    <div className="view">

      {/* ── Header ── */}
      <div className="page-head">
        <div>
          <h1>Performance</h1>
          <p className="muted lede" style={{ margin: '4px 0 0', fontSize: '0.9rem' }}>
            Real-time trading performance — every number traces to a real fill.
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '7px',
              height: '32px',
              padding: '0 14px',
              borderRadius: '999px',
              border: '1px solid var(--border)',
              background: 'var(--card)',
              fontSize: '0.78rem',
              fontWeight: 600,
              letterSpacing: '0.02em',
              color: 'var(--color-text)',
            }}
          >
            <span
              className={wsConnected ? 'live-dot pulse' : 'live-dot connecting'}
              style={{ width: 8, height: 8, borderRadius: '50%', flexShrink: 0 }}
            />
            {wsConnected ? 'LIVE' : 'CONNECTING'}
            {hasData && (
              <span className="muted" style={{ fontWeight: 500 }}>
                · {summary!.total_trades} trade{summary!.total_trades !== 1 ? 's' : ''}
              </span>
            )}
          </span>
          <button className="btn btn-primary btn-sm" onClick={() => loadAll(page)}>
            Refresh
          </button>
        </div>
      </div>

      {err && <p className="error-text">{err}</p>}

      {/* ── Hero: Equity curve (ALWAYS rendered) ── */}
      <div className="card perf-hero-card">
        {/* Chart header — P&L value + key stats */}
        <div className="perf-hero-header">
          <div>
            <div className="eyebrow" style={{ marginBottom: '6px' }}>
              Cumulative P&amp;L · Equity Curve
            </div>
            {summary ? (
              <div
                className={`perf-hero-pnl ${sentiment}`}
                style={{
                  fontSize: '2.2rem',
                  fontWeight: 700,
                  fontFamily: 'var(--font-mono)',
                  lineHeight: 1.1,
                  letterSpacing: '-0.02em',
                  color:
                    sentiment === 'positive'
                      ? 'var(--state-success)'
                      : sentiment === 'negative'
                      ? 'var(--state-error)'
                      : 'var(--foreground)',
                }}
              >
                {fmtPnl(summary.realized_pnl)}
              </div>
            ) : (
              <div
                style={{
                  width: 140,
                  height: 32,
                  borderRadius: 8,
                  background: 'var(--muted)',
                  opacity: 0.5,
                }}
              />
            )}
          </div>

          {summary && hasData && (
            <div className="perf-hero-stats">
              <div className="perf-hero-stat-cell">
                <div className="eyebrow">Win Rate</div>
                <div
                  className="perf-hero-stat-val"
                  style={{
                    color:
                      summary.win_rate_value !== null && summary.win_rate_value >= 0.6
                        ? 'var(--state-success)'
                        : summary.win_rate_value !== null
                        ? 'var(--state-error)'
                        : undefined,
                  }}
                >
                  {summary.win_rate_str}
                </div>
              </div>
              <div className="perf-hero-stat-cell">
                <div className="eyebrow">Max Drawdown</div>
                <div
                  className="perf-hero-stat-val"
                  style={{
                    color: summary.max_drawdown_pct > 0.15 ? 'var(--state-error)' : undefined,
                  }}
                >
                  {pct(summary.max_drawdown_pct)}
                </div>
              </div>
              <div className="perf-hero-stat-cell">
                <div className="eyebrow">Violations</div>
                <div
                  className="perf-hero-stat-val"
                  style={{
                    color:
                      summary.rule_violation_count > 0
                        ? 'var(--state-error)'
                        : 'var(--state-success)',
                  }}
                >
                  {summary.rule_violation_count}
                </div>
              </div>
              <div className="perf-hero-stat-cell">
                <div className="eyebrow">Give-Back</div>
                <div
                  className="perf-hero-stat-val"
                  style={{
                    color:
                      summary.give_back_pct_from_peak > summary.give_back_hard_pct
                        ? 'var(--state-error)'
                        : undefined,
                  }}
                >
                  {pct(summary.give_back_pct_from_peak)}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* The chart itself */}
        <div style={{ position: 'relative' }}>
          <PnLChart data={equityCurve} height={300} />
          {equityCurve.length === 0 && summary !== null && (
            <div className="perf-chart-overlay">
              <div style={{ fontSize: '1.5rem', marginBottom: '6px' }}>📈</div>
              <div className="muted small">
                {hasData
                  ? 'Equity curve loading…'
                  : 'Bot is live-monitoring — equity curve will draw here as trades close'}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Metrics strip (visible only when there are trades) ── */}
      {summary && hasData && (
        <div className="perf-metrics-strip">
          <div className="perf-strip-item">
            <div className="eyebrow">Avg R — Winners</div>
            <div className="perf-strip-val pos">
              {summary.avg_r_winners !== null ? `${summary.avg_r_winners.toFixed(2)}R` : '—'}
            </div>
          </div>
          <div className="perf-strip-item">
            <div className="eyebrow">Avg R — Losers</div>
            <div className="perf-strip-val neg">
              {summary.avg_r_losers !== null ? `${summary.avg_r_losers.toFixed(2)}R` : '—'}
            </div>
          </div>
          <div className="perf-strip-item">
            <div className="eyebrow">Rolling Win (5)</div>
            <div className="perf-strip-val">{pct(summary.rolling_5_win_rate)}</div>
          </div>
          <div className="perf-strip-item">
            <div className="eyebrow">Rolling Win (20)</div>
            <div className="perf-strip-val">{pct(summary.rolling_20_win_rate)}</div>
          </div>
          <div className="perf-strip-item">
            <div className="eyebrow">Peak P&amp;L</div>
            <div className="perf-strip-val pos">
              {Number(summary.peak_pnl) > 0 ? `+$${Number(summary.peak_pnl).toFixed(2)}` : '—'}
            </div>
          </div>
          <div className="perf-strip-item">
            <div className="eyebrow">Max Daily Loss Limit</div>
            <div className="perf-strip-val neg">
              -${Math.abs(Number(summary.max_daily_loss_limit)).toFixed(0)}
            </div>
          </div>
        </div>
      )}

      {/* ── Two-column: live feed + daily P&L (when has data) ── */}
      {hasData && summary && (
        <div className="content-grid">
          <RecentTradesFeed trades={trades.slice(0, 10)} total={tradesTotal} />
          <div className="card">
            <header className="card-head">
              <h3>Daily P&amp;L</h3>
              <span className="muted small">vs give-back guardrails</span>
            </header>
            <DailyPnLChart
              bars={summary.daily_pnl}
              maxLoss={summary.max_daily_loss_limit}
              warnPct={summary.give_back_warn_pct}
              hardPct={summary.give_back_hard_pct}
              peakPnl={summary.peak_pnl}
            />
          </div>
        </div>
      )}

      {/* ── Scanner activity (when no trades yet) ── */}
      {!hasData && summary !== null && <ScanSummary stats={scanStats} />}

      {/* ── Color legend ── */}
      {hasData && (
        <div className="perf-legend">
          <span className="perf-legend-item">
            <span style={{ color: 'var(--state-success)' }}>▲</span> Winner
          </span>
          <span className="perf-legend-item">
            <span style={{ color: '#f59e0b' }}>▼</span> Disciplined stop (P1–P8)
          </span>
          <span className="perf-legend-item">
            <span style={{ color: 'var(--state-error)' }}>●</span> Rule violation (target: 0)
          </span>
        </div>
      )}

      {/* ── Full trade log ── */}
      {hasData && (
        <div className="card">
          <header className="card-head">
            <h3>Trade Log</h3>
            <span className="muted small">
              {tradesTotal} trade{tradesTotal !== 1 ? 's' : ''} — newest first
            </span>
          </header>
          <div style={{ overflowX: 'auto' }}>
            <table className="table compact">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Symbol</th>
                  <th>Pattern</th>
                  <th>Entry</th>
                  <th>Exit</th>
                  <th>Shares</th>
                  <th>P&amp;L</th>
                  <th>R</th>
                  <th>Exit Rule</th>
                  <th>Running P&amp;L</th>
                  <th>Exit Time</th>
                </tr>
              </thead>
              <tbody>
                {trades.length === 0 && (
                  <tr>
                    <td colSpan={11} className="muted">
                      No trades yet this session.
                    </td>
                  </tr>
                )}
                {trades.map((t) => {
                  const pnl = Number(t.realized_pnl)
                  const pnlStr = `${pnl >= 0 ? '+' : '-'}$${Math.abs(pnl).toFixed(2)}`
                  const rPnl = Number(t.day_pnl_running_total)
                  return (
                    <tr key={t.trade_id} className={tradeRowClass(t)}>
                      <td className="mono muted">{t.trade_id}</td>
                      <td className="mono strong">{t.symbol}</td>
                      <td className="small">{patternLabel(t.pattern_type)}</td>
                      <td className="mono">${t.entry_price}</td>
                      <td className="mono">${t.exit_price}</td>
                      <td className="mono">{t.shares}</td>
                      <td className={`mono ${pnl >= 0 ? 'pos' : 'neg'}`}>
                        <span style={{ marginRight: '0.3em', color: tradeDotColor(t) }}>
                          {tradeDot(t)}
                        </span>
                        {pnlStr}
                      </td>
                      <td className="mono">
                        {t.r_multiple !== null ? `${t.r_multiple.toFixed(2)}R` : '—'}
                      </td>
                      <td className="small">{exitReasonLabel(t.exit_reason)}</td>
                      <td className={`mono ${rPnl >= 0 ? 'pos' : 'neg'}`}>
                        {rPnl >= 0 ? '+' : '-'}${Math.abs(rPnl).toFixed(2)}
                      </td>
                      <td className="mono small muted">
                        {new Date(t.exit_ts).toLocaleTimeString('en-US', {
                          timeZone: 'America/New_York',
                          hour12: false,
                        })}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {pages > 1 && (
            <div className="perf-pagination">
              <button
                className="btn btn-sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                ← Prev
              </button>
              <span className="muted small">
                Page {page} / {pages}
              </span>
              <button
                className="btn btn-sm"
                disabled={page >= pages}
                onClick={() => setPage((p) => Math.min(pages, p + 1))}
              >
                Next →
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
