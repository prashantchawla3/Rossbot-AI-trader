'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { useDashboard } from '@/hooks/useDashboardState'
import { ConfirmModal } from './ConfirmModal'
import { TermHint } from './Term'
import type { SessionConfig } from '@/lib/types'

type ModalKind = 'flatten' | 'halt' | null

export function BotControls() {
  const { state, refetch } = useDashboard()
  const risk = state.data?.risk
  const paused = risk?.is_paused ?? false
  const halted = risk?.is_halted ?? false

  const [modal, setModal] = useState<ModalKind>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  async function run(label: string, fn: () => Promise<unknown>, note?: string) {
    setBusy(label)
    setErr(null)
    setMsg(null)
    try {
      await fn()
      if (note) setMsg(note)
      await refetch()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="card bot-controls">
      <header className="card-head">
        <h3>Bot Controls</h3>
      </header>

      <div className="control-group">
        <span className="control-eyebrow">Emergency</span>
        <button className="btn btn-danger btn-block" disabled={!!busy} onClick={() => setModal('flatten')}>
          🔴 FLATTEN ALL
        </button>
        <div className="btn-row">
          {!paused ? (
            <button
              className="btn btn-warn"
              disabled={!!busy || halted}
              onClick={() => run('pause', api.pause, 'Bot paused — open positions still monitored.')}
            >
              ⏸ Pause
            </button>
          ) : (
            <button
              className="btn btn-primary"
              disabled={!!busy || halted}
              onClick={() => run('resume', api.resume, 'Bot resumed.')}
            >
              ▶ Resume
            </button>
          )}
          <button className="btn btn-danger" disabled={!!busy || halted} onClick={() => setModal('halt')}>
            🛑 Halt Day
          </button>
        </div>
      </div>

      <SessionConfigPanel />

      {msg && <p className="ok-text">{msg}</p>}
      {err && <p className="error-text">{err}</p>}

      <ConfirmModal
        open={modal === 'flatten'}
        title="Flatten all positions?"
        body="This cancels ALL open orders and closes ALL positions at market. This cannot be undone."
        confirmLabel="Flatten everything"
        onCancel={() => setModal(null)}
        onConfirm={async () => {
          setModal(null)
          await run('flatten', api.flatten, 'All positions flattened.')
        }}
      />
      <ConfirmModal
        open={modal === 'halt'}
        title="Halt trading for the day?"
        body="No more trades will be placed today (same as the 3-strikes rule). Open positions stay monitored. Confirm?"
        confirmLabel="Halt the day"
        onCancel={() => setModal(null)}
        onConfirm={async () => {
          setModal(null)
          await run('halt', api.haltDay, 'Trading halted for the day.')
        }}
      />
    </div>
  )
}

function SessionConfigPanel() {
  const [cfg, setCfg] = useState<SessionConfig | null>(null)
  const [open, setOpen] = useState(true)
  const [maxLoss, setMaxLoss] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)

  async function load() {
    try {
      const c = await api.getConfig()
      setCfg(c)
      setMaxLoss(c.MAX_DAILY_LOSS)
    } catch (e) {
      setErr(String(e))
    }
  }
  useEffect(() => {
    load()
  }, [])

  async function set(key: string, value: unknown) {
    setErr(null)
    setSaved(null)
    try {
      await api.setConfig(key, value)
      setSaved(`${key} updated`)
      await load()
    } catch (e) {
      setErr(String(e))
    }
  }

  if (!cfg) return <p className="muted">Loading config…{err && ` ${err}`}</p>

  return (
    <div className="control-group">
      <button className="control-eyebrow control-toggle" onClick={() => setOpen((o) => !o)}>
        Session Config {open ? '▾' : '▸'}
      </button>
      {open && (
        <div className="config-rows">
          <div className="config-row">
            <span>
              AUTO_TRADE <TermHint term="AUTO_TRADE" />
            </span>
            <div className="toggle-pair">
              <button
                className={`btn btn-sm ${cfg.AUTO_TRADE ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => set('AUTO_TRADE', true)}
              >
                ON
              </button>
              <button
                className={`btn btn-sm ${!cfg.AUTO_TRADE ? 'btn-warn' : 'btn-ghost'}`}
                onClick={() => set('AUTO_TRADE', false)}
              >
                OFF
              </button>
            </div>
          </div>

          <div className="config-row">
            <span>
              MARKET_STATE <TermHint term="HOT Market" />
            </span>
            <div className="toggle-pair">
              {(['HOT', 'COLD', 'REHAB'] as const).map((s) => (
                <button
                  key={s}
                  className={`btn btn-sm ${cfg.MARKET_STATE === s ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => set('MARKET_STATE', s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          <div className="config-row">
            <span>
              MAX DAILY LOSS <TermHint term="Daily Loss Limit" />
            </span>
            <div className="toggle-pair">
              <input
                className="input input-sm"
                value={maxLoss}
                onChange={(e) => setMaxLoss(e.target.value)}
                inputMode="decimal"
              />
              <button className="btn btn-sm btn-primary" onClick={() => set('MAX_DAILY_LOSS', maxLoss)}>
                Set
              </button>
            </div>
          </div>

          <div className="config-row">
            <span>SCAN INTERVAL</span>
            <div className="toggle-pair">
              {[30, 60, 120].map((s) => (
                <button
                  key={s}
                  className={`btn btn-sm ${cfg.SCAN_INTERVAL === s ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => set('SCAN_INTERVAL', s)}
                >
                  {s}s
                </button>
              ))}
            </div>
          </div>

          {cfg.overridden.length > 0 && (
            <p className="muted small">Overridden this session: {cfg.overridden.join(', ')} (audited)</p>
          )}
          {saved && <p className="ok-text small">{saved}</p>}
          {err && <p className="error-text small">{err}</p>}
        </div>
      )}
    </div>
  )
}
