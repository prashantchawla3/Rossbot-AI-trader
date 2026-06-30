'use client'

import type { SignalEvent, RiskEvent } from '@/lib/types'

// ── Merge & sort ────────────────────────────────────────────────────────────

type TlItem =
  | { kind: 'signal'; ts: string; data: SignalEvent }
  | { kind: 'risk'; ts: string; data: RiskEvent }

function buildTimeline(
  signals: SignalEvent[],
  riskEvents: RiskEvent[],
  max = 80
): TlItem[] {
  const RISK_EXCLUDE = new Set(['VETO', 'EXIT', 'MANUAL_EXIT'])
  const sigItems: TlItem[] = signals
    .filter(s => s.action === 'entry' || s.action === 'veto' || s.action === 'exit')
    .map(s => ({ kind: 'signal', ts: s.ts, data: s }))

  const riskItems: TlItem[] = riskEvents
    .filter(r => !RISK_EXCLUDE.has(r.event_type))
    .map(r => ({ kind: 'risk', ts: r.ts, data: r }))

  return [...sigItems, ...riskItems]
    .sort((a, b) => b.ts.localeCompare(a.ts))
    .slice(0, max)
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function fmt(ts: string) {
  try {
    return new Date(ts).toLocaleTimeString('en-US', {
      timeZone: 'America/New_York',
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return ts.slice(11, 19)
  }
}

function pnlClass(val: string | undefined): string {
  if (!val) return ''
  const n = parseFloat(val)
  if (isNaN(n)) return ''
  return n > 0 ? 'pos' : n < 0 ? 'neg' : ''
}

function pnlStr(val: string | undefined): string {
  if (!val) return ''
  const n = parseFloat(val)
  if (isNaN(n)) return val
  return n >= 0 ? `+$${n.toFixed(2)}` : `-$${Math.abs(n).toFixed(2)}`
}

// ── Gate badges (E1-E7) ─────────────────────────────────────────────────────

function GateBadges({ detail }: { detail: Record<string, unknown> }) {
  const gates: string[] = []
  for (let i = 1; i <= 7; i++) {
    const key = `E${i}`
    if (key in detail) {
      gates.push(key)
    }
  }
  if (gates.length === 0) return null
  return (
    <div className="tl-gates">
      {gates.map(key => {
        const val = detail[key]
        const pass = val === true || val === 'pass' || val === 1
        return (
          <span key={key} className={`tl-gate ${pass ? 'tl-gate-pass' : 'tl-gate-fail'}`}>
            {key}
          </span>
        )
      })}
    </div>
  )
}

// ── Row renderers ────────────────────────────────────────────────────────────

function EntryRow({ sig }: { sig: SignalEvent }) {
  const d = sig.detail
  return (
    <div className="tl-item tl-approved">
      <div className="tl-icon">▶</div>
      <div className="tl-body">
        <div className="tl-head">
          <span className="tl-sym">{sig.symbol}</span>
          <span className="tl-badge tl-badge-entry">ENTRY APPROVED</span>
          {sig.conviction !== null && (
            <span className="tl-conviction">cv {sig.conviction?.toFixed(2)}</span>
          )}
          <span className="tl-time">{fmt(sig.ts)}</span>
        </div>
        <GateBadges detail={d} />
        {!!(d.entry || d.stop || d.target || d.shares) && (
          <div className="tl-detail">
            {!!d.entry && <span>entry {String(d.entry)}</span>}
            {!!d.stop && <span>stop {String(d.stop)}</span>}
            {!!d.target && <span>T1 {String(d.target)}</span>}
            {!!d.shares && <span>{String(d.shares)} shs</span>}
          </div>
        )}
        {sig.event_type && <div className="tl-note">{sig.event_type}</div>}
      </div>
    </div>
  )
}

function VetoRow({ sig }: { sig: SignalEvent }) {
  const reason =
    typeof sig.detail?.reason === 'string'
      ? sig.detail.reason
      : sig.event_type
  return (
    <div className="tl-item tl-veto">
      <div className="tl-icon-sm">✕</div>
      <div className="tl-body">
        <span className="tl-sym">{sig.symbol}</span>
        <span className="tl-veto-reason">{reason}</span>
        <span className="tl-time">{fmt(sig.ts)}</span>
      </div>
    </div>
  )
}

function ExitRow({ sig }: { sig: SignalEvent }) {
  const d = sig.detail
  const pnl = d.pnl as string | undefined
  const cls = pnlClass(pnl)
  return (
    <div className={`tl-item ${cls === 'pos' ? 'tl-exit-win' : cls === 'neg' ? 'tl-exit-loss' : 'tl-exit'}`}>
      <div className="tl-icon">◀</div>
      <div className="tl-body">
        <div className="tl-head">
          <span className="tl-sym">{sig.symbol}</span>
          <span className="tl-badge tl-badge-exit">EXIT</span>
          {pnl && <span className={`tl-pnl ${cls}`}>{pnlStr(pnl)}</span>}
          <span className="tl-time">{fmt(sig.ts)}</span>
        </div>
        {!!(d.reason || d.exit_price) && (
          <div className="tl-detail">
            {!!d.exit_price && <span>@ {String(d.exit_price)}</span>}
            {!!d.reason && <span>{String(d.reason)}</span>}
          </div>
        )}
      </div>
    </div>
  )
}

function OrderRow({ ev }: { ev: RiskEvent }) {
  const d = ev.detail
  const isReject = ev.event_type === 'ORDER_REJECT'
  return (
    <div className={`tl-item ${isReject ? 'tl-critical' : 'tl-order'}`}>
      <div className="tl-icon">{isReject ? '⚠' : '⬆'}</div>
      <div className="tl-body">
        <div className="tl-head">
          <span className="tl-sym">{String(d.symbol ?? '')}</span>
          <span className={`tl-badge ${isReject ? 'tl-badge-reject' : 'tl-badge-order'}`}>
            {isReject ? 'REJECTED' : 'ORDER'}
          </span>
          {!!d.shares && <span className="tl-detail-inline">{String(d.shares)} shs</span>}
          {!!d.price && <span className="tl-detail-inline">@ {String(d.price)}</span>}
          <span className="tl-time">{fmt(ev.ts)}</span>
        </div>
        {ev.message && <div className="tl-note">{ev.message}</div>}
      </div>
    </div>
  )
}

function RiskRow({ ev }: { ev: RiskEvent }) {
  const cls =
    ev.severity === 'CRITICAL'
      ? 'tl-critical'
      : ev.severity === 'WARN'
        ? 'tl-warn'
        : 'tl-info'
  const icon =
    ev.severity === 'CRITICAL' ? '🛑' : ev.severity === 'WARN' ? '⚠' : 'ℹ'
  return (
    <div className={`tl-item ${cls}`}>
      <div className="tl-icon-sm">{icon}</div>
      <div className="tl-body">
        <div className="tl-head">
          <span className="tl-badge-sev">{ev.severity}</span>
          <span className="tl-sym">{ev.event_type}</span>
          <span className="tl-time">{fmt(ev.ts)}</span>
        </div>
        {ev.message && <div className="tl-note">{ev.message}</div>}
      </div>
    </div>
  )
}

// ── Main component ───────────────────────────────────────────────────────────

interface Props {
  signals: SignalEvent[]
  riskEvents: RiskEvent[]
}

export function ActivityTimeline({ signals, riskEvents }: Props) {
  const items = buildTimeline(signals, riskEvents)

  if (items.length === 0) {
    return (
      <div className="tl-empty">
        No activity yet. The bot will show scans, signals, orders, and exits here as they happen.
      </div>
    )
  }

  return (
    <div className="timeline">
      {items.map((item, i) => {
        if (item.kind === 'signal') {
          const sig = item.data
          if (sig.action === 'entry') return <EntryRow key={sig.id ?? i} sig={sig} />
          if (sig.action === 'veto') return <VetoRow key={sig.id ?? i} sig={sig} />
          if (sig.action === 'exit') return <ExitRow key={sig.id ?? i} sig={sig} />
          return null
        }
        const ev = item.data
        if (ev.event_type === 'ORDER' || ev.event_type === 'ORDER_REJECT') {
          return <OrderRow key={ev.id ?? i} ev={ev} />
        }
        return <RiskRow key={ev.id ?? i} ev={ev} />
      })}
    </div>
  )
}
