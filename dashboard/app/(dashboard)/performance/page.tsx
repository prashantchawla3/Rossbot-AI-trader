'use client'

import { useEffect, useRef, useCallback, useState } from 'react'
import { api } from '@/lib/api'
import { MetricCard } from '@/components/MetricCard'
import { PnLChart } from '@/components/PnLChart'
import type {
  PerformanceSummary,
  TradeLogEntry,
  ScanStats,
  PerfWsMessage,
} from '@/lib/types'
import type { LineData, UTCTimestamp } from 'lightweight-charts'

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

// ── equity curve adapter ─────────────────────────────────────────────────────

function toLineData(curve: PerformanceSummary['equity_curve']): LineData[] {
  return curve.map((pt) => ({
    time: Math.floor(new Date(pt.ts).getTime() / 1000) as UTCTimestamp,
    value: Number(pt.cumulative_pnl),
  }))
}

// ── daily P&L bar chart ──────────────────────────────────────────────────────

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

  // Reference lines as fractions of chart height
  const warnLine = peak > 0 ? -(peak * warnPct) : null
  const hardLine = peak > 0 ? -(peak * hardPct) : null
  const lossLine = -maxLossN

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

      {/* Reference lines legend */}
      <div className="perf-ref-lines">
        {warnLine !== null && (
          <span className="ref-line-badge warn">
            Give-back warn ({pct(warnPct, 0)} of peak ${Math.abs(warnLine).toFixed(0)})
          </span>
        )}
        {hardLine !== null && (
          <span className="ref-line-badge hard">
            Give-back halt ({pct(hardPct, 0)} of peak ${Math.abs(hardLine).toFixed(0)})
          </span>
        )}
        <span className="ref-line-badge loss">
          Max daily loss ${maxLossN.toFixed(0)}
        </span>
      </div>
    </div>
  )
}

// ── empty state ──────────────────────────────────────────────────────────────

function EmptyState({ stats }: { stats: ScanStats | null }) {
  return (
    <div className="perf-empty-state">
      <div className="card perf-empty-card">
        <div className="perf-empty-icon">📊</div>
        <h2>Bot is live-monitoring — no trades have met entry criteria yet</h2>
        <p className="muted">
          Every number on this dashboard traces to a real fill. The bot will not enter a trade
          until all seven entry gates (E1–E7) pass and the risk gate approves. This is not
          inaction — it&apos;s discipline.
        </p>

        {stats && (
          <div className="perf-scan-summary">
            <div className="perf-scan-grid">
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
                <span className="perf-scan-num neg">
                  {stats.tier_a_count - stats.tier_b_count}
                </span>
                <span className="perf-scan-lbl">Rejected from Tier-B</span>
              </div>
            </div>

            {stats.rejected_from_tier_b.length > 0 && (
              <div className="perf-rejections">
                <p className="eyebrow" style={{ marginBottom: '0.5rem' }}>
                  Why symbols were excluded from trading:
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
        )}
      </div>
    </div>
  )
}

// ── main page ─────────────────────────────────────────────────────────────────

export default function PerformancePage() {
  const [summary, setSummary] = useState<PerformanceSummary | null>(null)
  const [trades, setTrades] = useState<TradeLogEntry[]>([])
  const [tradesTotal, setTradesTotal] = useState(0)
  const [scanStats, setScanStats] = useState<ScanStats | null>(null)
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(1)
  const [err, setErr] = useState<string | null>(null)
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

  // WebSocket: receive trade_closed events and refresh
  useEffect(() => {
    const ws = new WebSocket(WS_URL)
    wsRef.current = ws

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data) as PerfWsMessage
        if (msg.type === 'trade_closed' || msg.type === 'performance_snapshot') {
          // Refresh all data on any trade event
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

    return () => {
      clearInterval(ping)
      ws.close()
      wsRef.current = null
    }
  }, [loadAll])

  const equityCurve: LineData[] = summary?.equity_curve ? toLineData(summary.equity_curve) : []
  const hasData = (summary?.total_trades ?? 0) > 0

  if (!hasData && summary !== null) {
    return (
      <div className="view">
        <div className="page-head">
          <div>
            <h1>Performance</h1>
            <p className="muted">Real-time trading performance — every number traces to a real fill.</p>
          </div>
          <button className="btn btn-primary btn-sm" onClick={() => loadAll(1)}>
            Refresh
          </button>
        </div>
        {err && <p className="error-text">{err}</p>}
        <EmptyState stats={scanStats} />
      </div>
    )
  }

  return (
    <div className="view">
      <div className="page-head">
        <div>
          <h1>Performance</h1>
          <p className="muted">
            Real-time trading performance — every number traces to a real fill.
          </p>
        </div>
        <button className="btn btn-primary btn-sm" onClick={() => loadAll(page)}>
          Refresh
        </button>
      </div>

      {err && <p className="error-text">{err}</p>}

      {/* ── Summary metrics ── */}
      {summary && (
        <div className="metrics-grid">
          <MetricCard
            label="Win Rate"
            value={summary.win_rate_str}
            sentiment={
              summary.win_rate_value !== null && summary.win_rate_value >= 0.6
                ? 'positive'
                : summary.win_rate_value !== null
                ? 'negative'
                : 'neutral'
            }
            hint="Win % with trade count always visible. ≥ 60% over 10+ trades is the U6 live-trading gate."
          />
          <MetricCard
            label="Realized P&L"
            value={fmtPnl(summary.realized_pnl)}
            sentiment={sentimentFromPnl(summary.realized_pnl)}
            hint="Sum of all closed-trade P&L this session."
          />
          <MetricCard
            label="Max Drawdown"
            value={pct(summary.max_drawdown_pct)}
            sentiment={summary.max_drawdown_pct > 0.15 ? 'negative' : 'neutral'}
            hint="Largest peak-to-trough drop in cumulative P&L this session."
          />
          <MetricCard
            label="Give-Back from Peak"
            value={pct(summary.give_back_pct_from_peak)}
            sentiment={summary.give_back_pct_from_peak > summary.give_back_hard_pct ? 'negative' : 'neutral'}
            hint="How much of the session's peak profit has been given back. Triggers at 25% (warn) and 50% (halt)."
          />
          <MetricCard
            label="Avg R — Winners"
            value={summary.avg_r_winners !== null ? `${summary.avg_r_winners.toFixed(2)}R` : '—'}
            sentiment="positive"
            hint="Average R-multiple for winning trades. R = P&L ÷ risk-per-share."
          />
          <MetricCard
            label="Avg R — Losers"
            value={summary.avg_r_losers !== null ? `${summary.avg_r_losers.toFixed(2)}R` : '—'}
            sentiment="negative"
            hint="Average R-multiple for losing trades. Disciplined stops should read close to -1R."
          />
          <MetricCard
            label="Rolling Win Rate (5)"
            value={pct(summary.rolling_5_win_rate)}
            hint="Win rate over the last 5 trades. More responsive than all-time; shows if momentum is shifting."
          />
          <MetricCard
            label="Rolling Win Rate (20)"
            value={pct(summary.rolling_20_win_rate)}
            hint="Win rate over the last 20 trades. Smoothed signal for medium-term consistency."
          />
          <MetricCard
            label="Rule Violations"
            value={String(summary.rule_violation_count)}
            sentiment={summary.rule_violation_count > 0 ? 'negative' : 'positive'}
            hint="Should always be 0. Any non-zero value means a Pxx exit rule was bypassed."
          />
        </div>
      )}

      {/* ── Equity curve (primary visual) ── */}
      <div className="card">
        <header className="card-head">
          <h3>Equity Curve</h3>
          <span className="muted small">
            Cumulative realized P&L — consistency over peaks
          </span>
        </header>
        <div className="perf-chart-note">
          <span className="muted small">
            CEO focus: drawdown depth + duration, not just all-time peak. A flat, rising
            line with shallow drawdowns beats a spikey line with the same endpoint.
          </span>
        </div>
        {equityCurve.length > 0 ? (
          <PnLChart data={equityCurve} height={220} />
        ) : (
          <div className="perf-empty-chart">
            <p className="muted small">Equity curve populates as trades close.</p>
          </div>
        )}
      </div>

      {/* ── Daily P&L bar chart ── */}
      {summary && (
        <div className="card">
          <header className="card-head">
            <h3>Daily P&L vs Risk Guardrails</h3>
            <span className="muted small">
              Reference lines show where give-back warning and halt thresholds fall
            </span>
          </header>
          <DailyPnLChart
            bars={summary.daily_pnl}
            maxLoss={summary.max_daily_loss_limit}
            warnPct={summary.give_back_warn_pct}
            hardPct={summary.give_back_hard_pct}
            peakPnl={summary.peak_pnl}
          />
        </div>
      )}

      {/* ── Color-coding legend ── */}
      <div className="perf-legend">
        <span className="perf-legend-item">
          <span style={{ color: 'var(--state-success)' }}>▲</span> Winner (disciplined entry + profitable exit)
        </span>
        <span className="perf-legend-item">
          <span style={{ color: '#f59e0b' }}>▼</span> Disciplined stop (P1–P8 rule fired correctly)
        </span>
        <span className="perf-legend-item">
          <span style={{ color: 'var(--state-error)' }}>●</span> Rule violation (should be 0)
        </span>
      </div>

      {/* ── Trade log table ── */}
      <div className="card">
        <header className="card-head">
          <h3>Trade Log</h3>
          <span className="muted small">{tradesTotal} trade{tradesTotal !== 1 ? 's' : ''} — newest first</span>
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
                <th>P&L</th>
                <th>R</th>
                <th>Exit Rule</th>
                <th>Running P&L</th>
                <th>Exit Time</th>
              </tr>
            </thead>
            <tbody>
              {trades.length === 0 && (
                <tr>
                  <td colSpan={11} className="muted">No trades yet this session.</td>
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
                      {new Date(t.exit_ts).toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour12: false })}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {pages > 1 && (
          <div className="perf-pagination">
            <button
              className="btn btn-sm"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              ← Prev
            </button>
            <span className="muted small">Page {page} / {pages}</span>
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
    </div>
  )
}
