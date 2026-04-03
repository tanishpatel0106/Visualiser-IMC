import type {
  DatasetInfo,
  MarketSnapshot,
  TradePrint,
  OHLCVBar,
  BacktestConfig,
  BacktestRun,
  PerformanceMetrics,
  DebugFrame,
  FillEvent,
  PnLState,
  StrategyDefinition,
  ReplaySession,
  ReplayStepResponse,
} from '@/types';

const CONFIGURED_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, '') || '/api';
let activeBase: string | null = null;

function candidateBases(): string[] {
  const local = ['http://localhost:8000/api', 'http://127.0.0.1:8000/api'];
  const configured = [CONFIGURED_BASE];
  if (typeof window === 'undefined') return [...configured, ...local];
  const sameOrigin = `${window.location.origin}/api`;
  return Array.from(new Set([activeBase, ...configured, sameOrigin, ...local].filter(Boolean) as string[]));
}

export function getActiveApiBase(): string {
  return activeBase || CONFIGURED_BASE;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let lastErr: unknown = null;

  for (const base of candidateBases()) {
    try {
      const res = await fetch(`${base}${path}`, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
      });
      if (res.ok) {
        activeBase = base;
        return res.json();
      }
      const text = await res.text();
      lastErr = new Error(`API error ${res.status} from ${base}: ${text}`);
    } catch (err) {
      lastErr = err;
    }
  }

  throw lastErr instanceof Error
    ? lastErr
    : new Error(`API request failed for ${path}`);
}

// === Health ===

export async function healthCheck(): Promise<{ status: string }> {
  return request<{ status: string }>('/health');
}

// === Dataset ===

export async function fetchDatasets(): Promise<DatasetInfo> {
  return request<DatasetInfo>('/datasets');
}

export async function loadDataset(directory: string): Promise<DatasetInfo> {
  return request<DatasetInfo>('/datasets/load', {
    method: 'POST',
    body: JSON.stringify({ directory }),
  });
}

export async function fetchProducts(): Promise<string[]> {
  const res = await request<{ products: string[] }>('/products');
  return res.products ?? [];
}

export async function fetchDays(): Promise<number[]> {
  const res = await request<{ days: number[] }>('/days');
  return res.days ?? [];
}

// === Market Data ===

export async function fetchSnapshots(
  product: string,
  day: number
): Promise<MarketSnapshot[]> {
  const params = new URLSearchParams({ product, day: String(day) });
  const res = await request<{ snapshots: MarketSnapshot[] }>(`/snapshots?${params}`);
  return res.snapshots ?? [];
}

export async function fetchTrades(
  product: string,
  day: number
): Promise<TradePrint[]> {
  const params = new URLSearchParams({ product, day: String(day) });
  const res = await request<{ trades: TradePrint[] }>(`/trades?${params}`);
  return res.trades ?? [];
}

export async function fetchOHLCV(
  product: string,
  interval?: number
): Promise<OHLCVBar[]> {
  const params = new URLSearchParams({ product });
  if (interval !== undefined) params.set('interval', String(interval));
  const res = await request<{ product: string; interval: number; count: number; bars: OHLCVBar[] }>(`/ohlcv?${params}`);
  return res.bars ?? [];
}

export async function fetchIndicators(
  product: string,
  indicator: string,
  period?: number
): Promise<{ product: string; indicator: string; values: number[] }> {
  const params = new URLSearchParams({ product, indicator });
  if (period !== undefined) params.set('period', String(period));
  return request(`/indicators?${params}`);
}

// === Replay ===

export async function startReplay(
  products: string[],
  days: number[]
): Promise<ReplaySession> {
  return request<ReplaySession>('/replay/start', {
    method: 'POST',
    body: JSON.stringify({ products, days }),
  });
}

export async function pauseReplay(): Promise<{ status: string }> {
  return request('/replay/pause', { method: 'POST' });
}

export async function stepReplay(): Promise<ReplayStepResponse> {
  return request<ReplayStepResponse>('/replay/step', { method: 'POST' });
}

export async function stepBackReplay(): Promise<ReplayStepResponse> {
  return request<ReplayStepResponse>('/replay/step-back', { method: 'POST' });
}

export async function seekReplay(timestamp: number): Promise<ReplayStepResponse> {
  return request<ReplayStepResponse>('/replay/seek', {
    method: 'POST',
    body: JSON.stringify({ timestamp }),
  });
}

export async function resetReplay(): Promise<{ status: string }> {
  return request('/replay/reset', { method: 'POST' });
}

export async function setReplaySpeed(speed: number): Promise<{ speed: number }> {
  return request('/replay/speed', {
    method: 'POST',
    body: JSON.stringify({ speed }),
  });
}

export async function getReplayState(): Promise<Record<string, unknown>> {
  return request('/replay/state');
}

// === Backtest ===

export async function runBacktest(config: BacktestConfig): Promise<BacktestRun> {
  return request<BacktestRun>('/backtest/run', {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

export async function getBacktestRun(runId: string): Promise<BacktestRun> {
  return request<BacktestRun>(`/backtest/${runId}`);
}

export async function getBacktestMetrics(runId: string): Promise<PerformanceMetrics> {
  const res = await request<Record<string, unknown>>(`/backtest/${runId}/metrics`);
  if (res.performance && typeof res.performance === 'object') {
    const perf = res.performance as Record<string, unknown>;
    const exec = (res.execution && typeof res.execution === 'object')
      ? (res.execution as Record<string, unknown>)
      : {};
    return { ...perf, ...exec } as PerformanceMetrics;
  }
  return res as PerformanceMetrics;
}

export async function getBacktestTrace(runId: string): Promise<{ trace: DebugFrame[]; page: number; total_pages: number }> {
  const res = await request<Record<string, unknown>>(`/backtest/${runId}/trace`);
  const trace = (res.trace as DebugFrame[] | undefined) ?? (res.frames as DebugFrame[] | undefined) ?? [];
  return {
    trace,
    page: (res.offset as number | undefined) ?? 0,
    total_pages: 1,
  };
}

export async function getBacktestFills(runId: string): Promise<{ fills: FillEvent[] }> {
  return request(`/backtest/${runId}/fills`);
}

export async function getBacktestPnl(runId: string): Promise<{ pnl_history: PnLState[] }> {
  return request(`/backtest/${runId}/pnl`);
}

// === Strategies ===

export async function fetchStrategies(): Promise<StrategyDefinition[]> {
  const res = await request<{ strategies: StrategyDefinition[] }>('/strategies');
  return res.strategies ?? [];
}

export async function fetchStrategy(id: string): Promise<StrategyDefinition> {
  return request<StrategyDefinition>(`/strategies/${id}`);
}

export async function fetchStrategySource(id: string): Promise<string> {
  const res = await request<{ strategy_id: string; source_code: string }>(`/strategies/${id}/source`);
  return res.source_code ?? '';
}

export async function uploadStrategy(name: string, sourceCode: string): Promise<{ valid: boolean; strategy_id: string; error: string | null }> {
  return request('/strategies/upload', {
    method: 'POST',
    body: JSON.stringify({ name, source_code: sourceCode }),
  });
}

export async function runStrategy(
  strategyId: string,
  params: {
    products: string[];
    days: number[];
    execution_model: string;
    parameters?: Record<string, unknown>;
    position_limits?: Record<string, number>;
    fees?: number;
    slippage?: number;
  }
): Promise<BacktestRun> {
  return request<BacktestRun>(`/strategies/${strategyId}/run`, {
    method: 'POST',
    body: JSON.stringify(params),
  });
}

// === Runs & Comparison ===

export async function fetchRuns(): Promise<BacktestRun[]> {
  const res = await request<{ runs: BacktestRun[] }>('/runs');
  return res.runs ?? [];
}

export async function compareRuns(runIds: string[]): Promise<{ runs: BacktestRun[]; count: number }> {
  return request('/runs/compare', {
    method: 'POST',
    body: JSON.stringify({ run_ids: runIds }),
  });
}

// === WebSocket ===

export function createReplayWebSocket(): WebSocket {
  const wsBase = (import.meta.env.VITE_WS_BASE_URL as string | undefined)?.replace(/\/+$/, '');
  if (wsBase) {
    return new WebSocket(`${wsBase}/ws/replay`);
  }

  const base = getActiveApiBase();
  if (base.startsWith('http://') || base.startsWith('https://')) {
    const wsUrl = `${base}/ws/replay`.replace(/^http/, 'ws');
    return new WebSocket(wsUrl);
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  return new WebSocket(`${protocol}//${host}${base}/ws/replay`);
}
