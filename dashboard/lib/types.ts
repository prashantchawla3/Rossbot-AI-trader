/* TypeScript types — mirror api/schemas/dashboard.py exactly */

export interface OpenPosition {
  symbol: string
  shares: number
  avg_price: string
  current_price: string
  unrealised_pnl: string
  side: 'long' | 'short'
}

export interface RiskState {
  day_pnl: string
  peak_pnl: string
  max_daily_loss: string
  give_back_warn: string
  give_back_hard: string
  consecutive_losses: number
  is_halted: boolean
  halt_reason: string | null
  is_paused: boolean
  trades_today: number
  wins_today: number
  losses_today: number
}

export interface WatchlistEntry {
  symbol: string
  tier: 'A' | 'B'
  price: string
  rvol: string
  float_shares: number | null
  catalyst: string | null
  pillar_flags: Record<string, boolean>
  last_updated: string
}

export interface SignalEvent {
  id: string
  ts: string
  symbol: string
  event_type: string
  detail: Record<string, unknown>
  conviction: number | null
  action: 'entry' | 'exit' | 'veto' | 'info'
}

export interface RiskEvent {
  id: string
  ts: string
  event_type: string
  severity: 'INFO' | 'WARN' | 'CRITICAL'
  message: string
  detail: Record<string, unknown>
}

export interface FeedHealth {
  feed_name: string
  last_tick_ts: string | null
  is_stale: boolean
  stale_seconds: number | null
}

export interface HealthOut {
  feeds: FeedHealth[]
  clock_drift_ms: number | null
  avg_order_ack_ms: number | null
  ws_client_count: number
  all_healthy: boolean
  checked_at: string
}

export interface JournalEntry {
  symbol: string
  side: 'long' | 'short'
  entry_price: string
  exit_price: string | null
  shares: number
  gross_pnl: string
  realised_pnl: string
  entry_ts: string
  exit_ts: string | null
  veto_reason: string | null
  spec_refs: string[]
}

export interface SessionJournal {
  date: string
  trades: JournalEntry[]
  total_pnl: string
  win_rate: string
  num_wins: number
  num_losses: number
  max_drawdown: string
  generated_at: string
}

export interface DashboardState {
  ts: string
  positions: OpenPosition[]
  risk: RiskState
  watchlist_tier_a: WatchlistEntry[]
  watchlist_tier_b: WatchlistEntry[]
  recent_signals: SignalEvent[]
  recent_risk_events: RiskEvent[]
  health: HealthOut
}

export interface WsMessage {
  type: 'state_update' | 'signal' | 'risk_event' | 'pong'
  payload: unknown
}

export interface ControlResult {
  ok: boolean
  message: string
}
