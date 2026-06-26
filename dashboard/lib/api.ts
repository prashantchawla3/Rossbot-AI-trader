import type {
  DashboardState,
  WatchlistEntry,
  SignalEvent,
  RiskEvent,
  SessionJournal,
  HealthOut,
  ControlResult,
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
    throw new Error(`API ${path} → ${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  getState: () => apiFetch<DashboardState>('/api/state'),
  getWatchlist: () => apiFetch<WatchlistEntry[]>('/api/watchlist'),
  getSignals: (limit = 50) => apiFetch<{ signals: SignalEvent[]; total: number }>(`/api/signals?limit=${limit}`),
  getRiskEvents: (limit = 50) => apiFetch<{ risk_events: RiskEvent[]; total: number }>(`/api/risk-events?limit=${limit}`),
  getJournal: () => apiFetch<SessionJournal>('/api/journal'),
  getHealth: () => apiFetch<HealthOut>('/health/'),

  killSwitch: () =>
    apiFetch<ControlResult>('/controls/kill-switch', { method: 'POST' }),
  pause: () =>
    apiFetch<ControlResult>('/controls/pause', { method: 'POST' }),
  resume: () =>
    apiFetch<ControlResult>('/controls/resume', { method: 'POST' }),
}
