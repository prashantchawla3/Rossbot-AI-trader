'use client'

import { useCallback, useEffect, useState } from 'react'
import { api } from '@/lib/api'
import type { AccountState } from '@/lib/types'

/**
 * Live Alpaca paper-account snapshot (GET /api/account) so the operator can confirm
 * the bot is actually wired to Alpaca before placing a manual test trade. Polls every
 * 15s. Read-only — no controls here.
 */
export function AccountPanel() {
  const [acct, setAcct] = useState<AccountState | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setAcct(await api.getAccount())
      setErr(null)
    } catch (e) {
      setErr(String(e))
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 15_000)
    return () => clearInterval(t)
  }, [load])

  const connected = acct?.connected ?? false

  return (
    <div className="card account-panel">
      <header className="card-head">
        <h3>Alpaca Account</h3>
        <span className={`zone-badge ${connected ? 'zone-green' : 'zone-red'}`}>
          {connected ? 'CONNECTED' : 'NOT CONNECTED'}
        </span>
      </header>

      {!acct && !err && <p className="muted">Checking broker connection…</p>}

      {err && (
        <p className="error-text small">
          {err} — is the API running on :8000?
        </p>
      )}

      {acct && (
        <>
          <dl className="gauge-stats account-stats">
            <div>
              <dt>Equity</dt>
              <dd className="mono">{acct.equity ? `$${acct.equity}` : '—'}</dd>
            </div>
            <div>
              <dt>Buying power</dt>
              <dd className="mono">{acct.buying_power ? `$${acct.buying_power}` : '—'}</dd>
            </div>
            <div>
              <dt>Cash</dt>
              <dd className="mono">{acct.cash ? `$${acct.cash}` : '—'}</dd>
            </div>
            <div>
              <dt>Day trades (5d)</dt>
              <dd className="mono">{acct.day_trade_count ?? '—'}</dd>
            </div>
          </dl>

          <div className="account-badges">
            {acct.paper && <span className="badge-pill">PAPER</span>}
            {acct.replay_mode && (
              <span className="badge-pill warn" title="Market closed — the scanner emits synthetic activity so you can test the UI.">
                REPLAY (market closed)
              </span>
            )}
            <span className={`badge-pill ${acct.auto_trade ? 'pos' : ''}`}>
              AUTO-TRADE {acct.auto_trade ? 'ON' : 'OFF'}
            </span>
          </div>

          {!connected && (
            <p className="muted small">
              {acct.error === 'no_credentials' || acct.error === 'engine_not_running'
                ? 'Set ALPACA_API_KEY / ALPACA_SECRET_KEY in the backend .env and RESTART the API. Free paper keys: alpaca.markets → Paper Trading → API Keys.'
                : acct.error ?? 'Broker unreachable.'}
            </p>
          )}
        </>
      )}
    </div>
  )
}
