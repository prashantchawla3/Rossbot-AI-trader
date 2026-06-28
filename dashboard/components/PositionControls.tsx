'use client'

import { useState } from 'react'
import { api } from '@/lib/api'
import { useDashboard } from '@/hooks/useDashboardState'
import { ConfirmModal } from './ConfirmModal'
import type { OpenPosition } from '@/lib/types'

/** Per-position action buttons: Close · Sell 50% · Move Stop (mental stop, U13). */
export function PositionControls({ position }: { position: OpenPosition }) {
  const { refetch } = useDashboard()
  const [confirmClose, setConfirmClose] = useState(false)
  const [stopOpen, setStopOpen] = useState(false)
  const [stop, setStop] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const sym = position.symbol

  async function run(label: string, fn: () => Promise<unknown>) {
    setBusy(label)
    setErr(null)
    try {
      await fn()
      await refetch()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="pos-controls">
      <button className="btn btn-sm btn-danger" disabled={!!busy} onClick={() => setConfirmClose(true)}>
        Close All
      </button>
      <button
        className="btn btn-sm btn-warn"
        disabled={!!busy || position.shares < 2}
        onClick={() => run('scale', () => api.scaleOut(sym))}
      >
        Sell 50%
      </button>
      {!stopOpen ? (
        <button className="btn btn-sm btn-ghost" disabled={!!busy} onClick={() => setStopOpen(true)}>
          Move Stop ↑
        </button>
      ) : (
        <span className="stop-edit">
          <input
            className="input input-sm"
            placeholder="stop $"
            value={stop}
            onChange={(e) => setStop(e.target.value)}
            inputMode="decimal"
          />
          <button
            className="btn btn-sm btn-primary"
            disabled={!stop || !!busy}
            onClick={() =>
              run('stop', async () => {
                await api.moveStop(sym, Number(stop))
                setStopOpen(false)
                setStop('')
              })
            }
          >
            Set
          </button>
          <button className="btn btn-sm btn-ghost" onClick={() => setStopOpen(false)}>
            ✕
          </button>
        </span>
      )}
      {err && <span className="error-text small">{err}</span>}

      <ConfirmModal
        open={confirmClose}
        title={`Close ${sym}?`}
        body={`Close all ${position.shares} shares of ${sym} at the current bid?`}
        confirmLabel={`Close ${sym}`}
        onCancel={() => setConfirmClose(false)}
        onConfirm={async () => {
          setConfirmClose(false)
          await run('close', () => api.closePosition(sym))
        }}
      />
    </div>
  )
}
