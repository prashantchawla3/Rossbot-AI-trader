import type {
  DashboardState,
  WatchlistEntry,
  SignalEvent,
  RiskEvent,
  SessionJournal,
  HealthOut,
  ControlResult,
  Bar,
  SessionConfig,
  AnalyzeVerdict,
  ModelsCatalog,
  JournalTrade,
  SessionSummary,
  AccountState,
  SymbolNews,
} from './types'

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? ''

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': API_KEY,
      ...(init?.headers ?? {}),
    },
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* non-JSON error body */
    }
    throw new Error(`${path} → ${detail}`)
  }
  return res.json() as Promise<T>
}

const post = <T>(path: string, body?: unknown) =>
  apiFetch<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined })

export const api = {
  // ── reads ──────────────────────────────────────────────────────────────
  getState: () => apiFetch<DashboardState>('/api/state'),
  getWatchlist: () => apiFetch<WatchlistEntry[]>('/api/watchlist'),
  getSignals: (limit = 50) =>
    apiFetch<{ signals: SignalEvent[]; total: number }>(`/api/signals?limit=${limit}`),
  getRiskEvents: (limit = 50) =>
    apiFetch<{ risk_events: RiskEvent[]; total: number }>(`/api/risk-events?limit=${limit}`),
  getJournal: () => apiFetch<SessionJournal>('/api/journal'),
  getHealth: () => apiFetch<HealthOut>('/health/'),
  getBars: (symbol: string, limit = 50) =>
    apiFetch<{ symbol: string; bars: Bar[] }>(`/api/bars/${symbol}?limit=${limit}`),
  getConfig: () => apiFetch<SessionConfig>('/api/config'),
  getAccount: () => apiFetch<AccountState>('/api/account'),
  getModels: () => apiFetch<ModelsCatalog>('/api/models'),
  getNews: (symbol: string) => apiFetch<SymbolNews>(`/api/news/${symbol}`),
  analyze: (symbol: string, provider?: string, model?: string) => {
    const qs = new URLSearchParams()
    if (provider) qs.set('provider', provider)
    if (model) qs.set('model', model)
    const suffix = qs.toString() ? `?${qs.toString()}` : ''
    return apiFetch<AnalyzeVerdict>(`/api/analyze/${symbol}${suffix}`)
  },
  journalToday: () =>
    apiFetch<{ trades: JournalTrade[]; count: number }>('/api/journal/today'),
  sessionSummary: () => apiFetch<SessionSummary>('/api/journal/session-summary'),
  journalExportUrl: () => `${BASE_URL}/api/journal/export`,

  // ── legacy controls (TopNav kill switch) ─────────────────────────────────
  killSwitch: () => post<ControlResult>('/controls/kill-switch'),

  // ── operator console controls ────────────────────────────────────────────
  scanNow: () => post<{ ok: boolean; tier_a?: number; tier_b?: number; message?: string }>('/api/scanner/trigger'),
  flatten: () =>
    post<{ success: boolean; positions_closed: number; orders_cancelled: number }>('/api/control/flatten'),
  pause: () => post<{ ok: boolean; status: string }>('/api/control/pause'),
  resume: () => post<{ ok: boolean; status: string }>('/api/control/resume'),
  haltDay: () => post<{ ok: boolean; halted: boolean }>('/api/control/halt-day'),

  setConfig: (key: string, value: unknown) =>
    apiFetch<{ ok: boolean; key: string; value: unknown }>('/api/config', {
      method: 'PATCH',
      body: JSON.stringify({ key, value }),
    }),

  // ── position controls ────────────────────────────────────────────────────
  closePosition: (symbol: string) =>
    post<{ ok: boolean; message?: string; pnl?: string }>(`/api/positions/${symbol}/close`),
  scaleOut: (symbol: string) =>
    post<{ ok: boolean; message?: string }>(`/api/positions/${symbol}/scale-out`),
  moveStop: (symbol: string, stop_price: number) =>
    post<{ ok: boolean; stop_price?: string }>(`/api/positions/${symbol}/stop`, { stop_price }),

  // ── manual trading (through the risk gate) ────────────────────────────────
  tradeManual: (body: { symbol: string; entry: number; stop: number; shares: number }) =>
    post<Record<string, unknown>>('/api/trade/manual', body),
  manualOrder: (body: { symbol: string; side: string; qty: number; limit_price: number }) =>
    post<Record<string, unknown>>('/api/trade/manual-order', body),
}
