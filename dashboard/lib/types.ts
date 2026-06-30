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
  change_pct?: string | null
  last_updated: string
}

// ── Operator console additions ──────────────────────────────────────────────

export interface AccountState {
  connected: boolean
  equity?: string
  buying_power?: string
  cash?: string
  day_trade_count?: number
  paper?: boolean
  auto_trade?: boolean
  replay_mode?: boolean
  error?: string
}

export interface Bar {
  time: number
  open: string
  high: string
  low: string
  close: string
  volume: number
}

export interface SessionConfig {
  AUTO_TRADE: boolean
  MARKET_STATE: 'HOT' | 'COLD' | 'REHAB'
  MAX_DAILY_LOSS: string
  SCAN_INTERVAL: number
  overridden: string[]
}

export interface PillarCell {
  pass: boolean | null
  value?: string
  rule?: string
  note?: string
}

export interface GateCell {
  pass: boolean | null
  note?: string
}

export interface SuggestedTrade {
  action: string
  entry_price: number
  stop_price: number
  risk_per_share: number
  suggested_shares: number
  target_1: number
  target_2: number
  risk_reward: number
  pattern: string
  conviction: string
}

export interface AnalyzeVerdict {
  symbol: string
  would_ross_trade: boolean
  confidence: number
  verdict_summary: string
  pillars: Record<string, PillarCell>
  entry_gates: Record<string, GateCell>
  suggested_trade: SuggestedTrade | null
  warnings: string[]
  ross_would_say: string
  source: string
  provider?: string
  model?: string
  market_data?: Record<string, unknown>
}

// ── AI model picker (GET /api/models) ───────────────────────────────────────

export interface ModelOption {
  id: string
  label: string
}

export interface ProviderInfo {
  key: string
  label: string
  configured: boolean
  env_key: string
  default_model: string
  note: string
  models: ModelOption[]
}

export interface ModelsCatalog {
  providers: ProviderInfo[]
  default_provider: string
  default_model: string
}

export interface JournalTrade {
  symbol: string
  side: string
  entry_price: string
  exit_price: string
  shares: number
  pnl: string
  r_multiple: number | null
  exit_reason: string
  entry_ts: string
  exit_ts: string
}

export interface SessionSummary {
  trades: number
  wins: number
  losses: number
  win_rate: number | null
  avg_winner: string
  avg_loser: string
  profit_factor: number | null
  best_trade: string
  worst_trade: string
  realized_pnl: string
  consecutive_losses: number
  rules_violated: number
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

export interface NewsItem {
  headline: string
  created_at: string
  source: string
  summary: string
}

export interface CatalystResult {
  status: 'VERIFIED' | 'SKIP' | 'UNVERIFIED'
  type: string
  reason: string
}

export interface SymbolNews {
  symbol: string
  catalyst_result: CatalystResult
  recent_news: NewsItem[]
}

export interface CatalystUpdateEvent {
  symbol: string
  status: 'VERIFIED' | 'SKIP' | 'UNVERIFIED'
  catalyst_type: string
  reason: string
  headline: string
  source: string
  created_at: string
}

export interface WsMessage {
  type: 'state_update' | 'signal' | 'risk_event' | 'pong' | 'catalyst_update'
  payload: unknown
}

export interface ControlResult {
  ok: boolean
  message: string
}

// ── Performance dashboard ────────────────────────────────────────────────────

export interface TradeLogEntry {
  trade_id: number
  symbol: string
  side: string
  pattern_type: string
  entry_price: string
  exit_price: string
  shares: number
  realized_pnl: string
  r_multiple: number | null
  exit_reason: string
  is_disciplined: boolean
  entry_ts: string
  exit_ts: string
  day_pnl_running_total: string
}

export interface TradesResponse {
  trades: TradeLogEntry[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface EquityPoint {
  ts: string
  cumulative_pnl: string
  trade_id: number
}

export interface DailyPnLBar {
  date: string
  pnl: string
}

export interface ScanRejection {
  symbol: string
  pillars_failed: string[]
}

export interface ScanStats {
  symbols_scanned: number
  tier_a_count: number
  tier_b_count: number
  rejected_from_tier_b: ScanRejection[]
}

export interface PerformanceSummary {
  total_trades: number
  win_count: number
  loss_count: number
  win_rate_value: number | null
  win_rate_str: string
  avg_r_winners: number | null
  avg_r_losers: number | null
  max_drawdown_pct: number
  give_back_pct_from_peak: number
  rule_violation_count: number
  rolling_5_win_rate: number | null
  rolling_20_win_rate: number | null
  equity_curve: EquityPoint[]
  daily_pnl: DailyPnLBar[]
  realized_pnl: string
  peak_pnl: string
  max_daily_loss_limit: string
  give_back_warn_pct: number
  give_back_hard_pct: number
}

export interface PerfWsMessage {
  type: 'trade_closed' | 'performance_snapshot' | 'pong'
  payload: unknown
}
