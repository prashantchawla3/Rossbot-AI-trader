'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { useChartSymbol } from '@/hooks/useChartSymbol'
import { Tooltip } from '@/components/Tooltip'
import { Term } from '@/components/Term'
import type { AnalyzeVerdict, PillarCell, GateCell, ModelsCatalog, ProviderInfo } from '@/lib/types'

function passClass(p: boolean | null): string {
  return p === true ? 'pos' : p === false ? 'neg' : 'muted'
}
function passMark(p: boolean | null): string {
  return p === true ? '✓' : p === false ? '✗' : '–'
}

const LS_PROVIDER = 'rossbot.ai.provider'
const LS_MODEL = 'rossbot.ai.model'

export default function AnalysisPage() {
  const { setSymbol } = useChartSymbol()
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [verdict, setVerdict] = useState<AnalyzeVerdict | null>(null)
  const [err, setErr] = useState<string | null>(null)

  // ── AI model picker ──
  const [catalog, setCatalog] = useState<ModelsCatalog | null>(null)
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')

  useEffect(() => {
    api
      .getModels()
      .then((c) => {
        setCatalog(c)
        const savedP = typeof window !== 'undefined' ? localStorage.getItem(LS_PROVIDER) : null
        const savedM = typeof window !== 'undefined' ? localStorage.getItem(LS_MODEL) : null
        const validProvider = c.providers.some((p) => p.key === savedP)
        const p = validProvider ? (savedP as string) : c.default_provider
        const prov = c.providers.find((x) => x.key === p)
        const validModel = prov?.models.some((m) => m.id === savedM)
        setProvider(p)
        setModel(validModel ? (savedM as string) : prov?.default_model ?? c.default_model)
      })
      .catch(() => setCatalog(null))
  }, [])

  function onProvider(key: string) {
    setProvider(key)
    const prov = catalog?.providers.find((p) => p.key === key)
    const m = prov?.default_model ?? ''
    setModel(m)
    if (typeof window !== 'undefined') {
      localStorage.setItem(LS_PROVIDER, key)
      localStorage.setItem(LS_MODEL, m)
    }
  }
  function onModel(id: string) {
    setModel(id)
    if (typeof window !== 'undefined') localStorage.setItem(LS_MODEL, id)
  }

  const activeProvider: ProviderInfo | undefined = catalog?.providers.find((p) => p.key === provider)

  async function analyze(e?: React.FormEvent) {
    e?.preventDefault()
    const sym = input.trim().toUpperCase()
    if (!sym) return
    setLoading(true)
    setErr(null)
    setVerdict(null)
    setSymbol(sym)
    try {
      setVerdict(await api.analyze(sym, provider || undefined, model || undefined))
    } catch (e2) {
      setErr(String(e2))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="view">
      <div className="page-head">
        <div>
          <h1>AI Analysis</h1>
          <p className="muted">
            Grade any US equity against Ross’s exact rules with the AI model of your choice. Suggested trades
            still go through the risk gate.
          </p>
        </div>
      </div>

      {catalog && (
        <div className="card model-picker">
          <div className="model-picker-row">
            <label className="model-field">
              <span className="control-eyebrow">AI Provider</span>
              <select className="input input-sm" value={provider} onChange={(e) => onProvider(e.target.value)}>
                {catalog.providers.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.label}
                    {p.configured ? '' : ' — no API key'}
                  </option>
                ))}
              </select>
            </label>
            <label className="model-field">
              <span className="control-eyebrow">Model</span>
              <select className="input input-sm" value={model} onChange={(e) => onModel(e.target.value)}>
                {activeProvider?.models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {activeProvider && !activeProvider.configured && (
            <p className="muted small">
              ⚠️ No API key for {activeProvider.label}. Set <code>{activeProvider.env_key}</code> in the
              backend <code>.env</code> and restart the API. {activeProvider.note}
            </p>
          )}
          {activeProvider?.configured && activeProvider.note && (
            <p className="muted small">{activeProvider.note}</p>
          )}
        </div>
      )}

      <form className="analyzer-bar card" onSubmit={analyze}>
        <input
          className="input"
          placeholder="Enter symbol e.g. MLGO"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button className="btn btn-primary" type="submit" disabled={loading}>
          {loading ? `Analyzing ${input.toUpperCase()}…` : '🔍 Analyze'}
        </button>
      </form>

      {err && <p className="error-text">{err}</p>}
      {verdict && <VerdictCard verdict={verdict} />}

      <QuickOrder />
    </div>
  )
}

function VerdictCard({ verdict }: { verdict: AnalyzeVerdict }) {
  const [exec, setExec] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const t = verdict.suggested_trade
  const conf = verdict.confidence
  const confClass = conf >= 7 ? 'pos' : conf >= 4 ? 'warn-text' : 'neg'

  async function executeTrade() {
    if (!t) return
    setBusy(true)
    setExec(null)
    try {
      const r = await api.tradeManual({
        symbol: verdict.symbol,
        entry: t.entry_price,
        stop: t.stop_price,
        shares: t.suggested_shares,
      })
      if (r.approved === false) setExec(`❌ Risk manager VETOED: ${r.veto}`)
      else if (r.ok) setExec(`✅ Submitted ${r.sized_shares ?? t.suggested_shares} shares (status ${r.status}).`)
      else setExec(`Order not accepted: ${JSON.stringify(r)}`)
    } catch (e) {
      setExec(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card verdict-card">
      <div className={`verdict-banner ${verdict.would_ross_trade ? 'yes' : 'no'}`}>
        {verdict.would_ross_trade ? 'ROSS WOULD TRADE THIS ✅' : 'ROSS WOULD SKIP THIS ❌'}
        <span className={`verdict-conf ${confClass}`}>
          <Term term="Conviction">Confidence</Term> {conf}/10
        </span>
      </div>
      <p className="verdict-summary">{verdict.verdict_summary}</p>
      {verdict.source === 'fallback' ? (
        <p className="muted small">
          Heuristic verdict — the chosen AI model was unavailable. Check the provider’s API key in the backend
          <code> .env</code>.
        </p>
      ) : (
        verdict.model && (
          <p className="muted small">
            Analyzed by <b>{verdict.model}</b>
            {verdict.provider ? ` (${verdict.provider})` : ''}.
          </p>
        )
      )}

      <div className="verdict-grid">
        <div>
          <h4>Five Pillars</h4>
          <ul className="check-list">
            {Object.entries(verdict.pillars).map(([k, c]: [string, PillarCell]) => (
              <li key={k}>
                <span className={`dot-mini ${passClass(c.pass)}`} />
                <Tooltip label={c.note ?? ''}>
                  <span className="check-key">{k}</span>
                </Tooltip>
                <span className="check-val mono">{c.value}</span>
                <span className={passClass(c.pass)}>{passMark(c.pass)}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4>Entry Gates</h4>
          <ul className="check-list">
            {Object.entries(verdict.entry_gates).map(([k, c]: [string, GateCell]) => (
              <li key={k}>
                <span className={`dot-mini ${passClass(c.pass)}`} />
                <Tooltip label={c.note ?? ''}>
                  <span className="check-key">{k}</span>
                </Tooltip>
                <span className={passClass(c.pass)}>{passMark(c.pass)}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {t && (
        <div className="suggested-trade">
          <h4>Suggested Trade</h4>
          <div className="trade-grid mono">
            <span>Action <b>{t.action}</b></span>
            <span>Entry <b>${t.entry_price}</b></span>
            <span>Stop <b>${t.stop_price}</b></span>
            <span>Risk/sh <b>${t.risk_per_share}</b></span>
            <span>Shares <b>{t.suggested_shares}</b></span>
            <span>T1 <b>${t.target_1}</b></span>
            <span>T2 <b>${t.target_2}</b></span>
            <span><Term term="Risk:Reward">R:R</Term> <b>{t.risk_reward}</b></span>
            <span>Pattern <b>{t.pattern}</b></span>
            <span>Conviction <b>{t.conviction}</b></span>
          </div>
        </div>
      )}

      {verdict.warnings?.length > 0 && (
        <ul className="warn-list">
          {verdict.warnings.map((w, i) => (
            <li key={i}>⚠️ {w}</li>
          ))}
        </ul>
      )}

      <p className="ross-quote">“{verdict.ross_would_say}”</p>

      {t && (
        <div className="verdict-actions">
          <button className="btn btn-primary" onClick={executeTrade} disabled={busy}>
            {busy ? 'Submitting…' : '📈 Execute This Trade (Paper)'}
          </button>
          <span className="muted small">Routed through the risk manager — it can veto or resize.</span>
        </div>
      )}
      {exec && <p className={exec.startsWith('✅') ? 'ok-text' : 'error-text'}>{exec}</p>}
    </div>
  )
}

function QuickOrder() {
  const [symbol, setSymbol] = useState('')
  const [side, setSide] = useState<'BUY' | 'SELL'>('BUY')
  const [qty, setQty] = useState('')
  const [limit, setLimit] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setResult(null)
    try {
      const r = await api.manualOrder({
        symbol: symbol.toUpperCase().trim(),
        side,
        qty: Number(qty),
        limit_price: Number(limit),
      })
      if (r.approved === false) setResult(`❌ Risk manager VETOED: ${r.veto}`)
      else if (r.ok) setResult(`✅ ${side} ${r.qty} ${symbol.toUpperCase()} @ $${r.limit_price} (${r.status}).`)
      else setResult(`Not accepted: ${JSON.stringify(r)}`)
    } catch (e2) {
      setResult(String(e2))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card quick-order" onSubmit={submit}>
      <h3>Quick Manual Order</h3>
      <p className="muted small">Goes through the risk manager — limit orders only (U7).</p>
      <div className="quick-row">
        <input className="input input-sm" placeholder="Symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)} />
        <div className="toggle-pair">
          <button type="button" className={`btn btn-sm ${side === 'BUY' ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setSide('BUY')}>
            BUY
          </button>
          <button type="button" className={`btn btn-sm ${side === 'SELL' ? 'btn-warn' : 'btn-ghost'}`} onClick={() => setSide('SELL')}>
            SELL
          </button>
        </div>
        <input className="input input-sm" placeholder="Shares" value={qty} onChange={(e) => setQty(e.target.value)} inputMode="numeric" />
        <input className="input input-sm" placeholder="Limit $" value={limit} onChange={(e) => setLimit(e.target.value)} inputMode="decimal" />
        <button className="btn btn-primary btn-sm" type="submit" disabled={busy || !symbol || !qty || !limit}>
          {busy ? '…' : 'Submit Paper Order'}
        </button>
      </div>
      {result && <p className={result.startsWith('✅') ? 'ok-text small' : 'error-text small'}>{result}</p>}
    </form>
  )
}
