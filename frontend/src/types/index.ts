// === Enums as string unions ===

export type Product = string;

export type OrderSide = 'BUY' | 'SELL';

export type OrderType = 'LIMIT' | 'MARKET' | 'IOC';

export type OrderStatus = 'PENDING' | 'OPEN' | 'FILLED' | 'PARTIALLY_FILLED' | 'CANCELLED' | 'REJECTED';

export type EventType = 'SNAPSHOT' | 'TRADE' | 'ORDER' | 'FILL' | 'POSITION' | 'PNL' | 'SIGNAL' | 'LOG' | 'ERROR';

export type ExecutionModel = 'CONSERVATIVE' | 'BALANCED' | 'OPTIMISTIC';

export type ChartMode = 'line' | 'candlestick' | 'ohlc' | 'step';

/** A specific indicator instance with its own parameter overrides. */
export interface IndicatorInstance {
  /** Unique key for this instance (e.g. "SMA_1687339200") */
  key: string;
  /** Indicator ID from the registry (e.g. "SMA", "RSI") */
  id: string;
  /** User-configured parameter values */
  params: Record<string, number>;
}

// === Market Data ===

export interface BookLevel {
  price: number;
  volume: number;
  side?: OrderSide;
}

export interface VisibleOrderBook {
  product: Product;
  timestamp: number;
  bids: BookLevel[];
  asks: BookLevel[];
  best_bid: number | null;
  best_ask: number | null;
  spread: number | null;
  mid_price: number | null;
  weighted_mid?: number | null;
  microprice?: number | null;
  total_bid_depth?: number | null;
  total_ask_depth?: number | null;
  top_level_imbalance?: number | null;
  top3_imbalance?: number | null;
  book_pressure?: number | null;
  depth_skew?: number | null;
}

export interface TradePrint {
  timestamp: number;
  buyer?: string;
  seller?: string;
  symbol: string;
  currency?: string;
  price: number;
  quantity: number;
  aggressor_side: OrderSide | null;
}

export interface MarketSnapshot {
  day: number;
  timestamp: number;
  product: Product;
  bid_prices?: number[];
  bid_volumes?: number[];
  ask_prices?: number[];
  ask_volumes?: number[];
  mid_price: number | null;
  [key: string]: unknown;
}

export interface OHLCVBar {
  timestamp: number;
  product?: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface IndicatorPoint {
  time: number;
  value: number;
}

export interface IndicatorSeries {
  name: string;
  data: IndicatorPoint[];
  color?: string;
  type?: 'line' | 'histogram';
}

// === Events ===

export interface ReplayEvent {
  event_type: string;
  timestamp: number;
  product?: Product;
  data?: Record<string, unknown>;
  sequence_num?: number;
}

export interface Event {
  type: EventType;
  timestamp: number;
  product?: Product;
  data: Record<string, unknown>;
}

// === Strategy & Execution ===

export interface StrategyOrder {
  id?: string;
  timestamp: number;
  product: Product;
  side: OrderSide;
  type?: OrderType;
  price: number;
  quantity: number;
  status?: OrderStatus;
  filled_quantity?: number;
  avg_fill_price?: number;
}

export interface FillEvent {
  id?: string;
  timestamp: number;
  order_id?: string;
  product?: Product;
  symbol?: string;
  side?: OrderSide;
  price: number;
  quantity: number;
  aggressive?: boolean;
  pnl_impact?: number;
}

export interface PositionState {
  product: Product;
  quantity: number;
  avg_entry_price: number;
  mark_price: number;
  unrealized_pnl: number;
  realized_pnl: number;
  position_limit: number;
}

export interface InventoryState {
  positions: Record<string, PositionState>;
  total_unrealized_pnl: number;
  total_realized_pnl: number;
}

export interface PnLState {
  timestamp?: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  inventory?: Record<string, number>;
  cash?: number;
}

// === Backtest ===

export interface BacktestConfig {
  strategy_id: string;
  products: string[];
  days: number[];
  execution_model: ExecutionModel;
  position_limits?: Record<string, number>;
  fees?: number;
  slippage?: number;
  parameters?: Record<string, unknown>;
}

export interface BacktestRun {
  run_id: string;
  config?: BacktestConfig;
  status: 'pending' | 'running' | 'completed' | 'failed';
  started_at?: string;
  completed_at?: string;
  error?: string | null;
  metrics?: PerformanceMetrics;
}

// === Strategy Definitions ===

export interface StrategyParameter {
  name: string;
  type: 'int' | 'float' | 'bool' | 'string' | 'select';
  default: unknown;
  min?: number;
  max?: number;
  step?: number;
  options?: string[];
  description?: string;
}

export interface StrategyDefinition {
  strategy_id: string;
  name: string;
  description: string;
  category: string;
  is_builtin?: boolean;
  parameters: StrategyParameter[];
  source_file?: string;
}

export interface DebugFrame {
  timestamp: number;
  event_type: string;
  orders?: StrategyOrder[];
  fills?: FillEvent[];
  position?: Record<string, number>;
  pnl?: PnLState;
  notes?: string;
  state?: Record<string, unknown>;
}

// === Metrics ===

export interface PerformanceMetrics {
  total_pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  profit_factor: number;
  avg_win: number;
  avg_loss: number;
  num_trades: number;
  num_wins: number;
  num_losses: number;
  total_volume: number;
  avg_position: number;
  max_position: number;
  total_fees: number;
  [key: string]: unknown;
}

export interface ExecutionMetrics {
  avg_fill_time_ms?: number;
  fill_rate?: number;
  slippage_bps?: number;
  avg_spread_capture?: number;
  passive_fill_rate?: number;
  aggressive_fill_rate?: number;
}

// === Replay ===

export interface ReplaySession {
  session_id: string;
  total_events: number;
  products: string[];
  days: number[];
  strategy_id: string | null;
}

export interface ReplayStepResponse {
  event: ReplayEvent | null;
  state: ReplayStateData;
}

export interface ReplayStateData {
  books?: Record<string, VisibleOrderBook>;
  trades?: TradePrint[];
  positions?: Record<string, number | PositionState>;
  pnl?: PnLState;
  [key: string]: unknown;
}

export interface ReplayState {
  is_playing: boolean;
  current_timestamp: number;
  speed: number;
  total_events: number;
  current_index: number;
  books: Record<string, VisibleOrderBook>;
  trades: TradePrint[];
  positions: Record<string, PositionState>;
  pnl: PnLState;
  inventory: InventoryState;
}

// === Workspace ===

export type WorkspacePreset = 'trading' | 'analysis' | 'strategy' | 'debug';

// === Dataset ===

export interface DatasetInfo {
  products: string[];
  days: number[];
  loaded: boolean;
}
