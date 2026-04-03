import { create } from 'zustand';
import type {
  Product,
  DatasetInfo,
  ReplayState,
  VisibleOrderBook,
  TradePrint,
  PositionState,
  PnLState,
  InventoryState,
  BacktestRun,
  PerformanceMetrics,
  ExecutionMetrics,
  DebugFrame,
  FillEvent,
  StrategyDefinition,
  StrategyParameter,
  WorkspacePreset,
  ChartMode,
  OHLCVBar,
} from '@/types';

// === Dataset Store ===

interface DatasetStoreState {
  datasetInfo: DatasetInfo | null;
  products: Product[];
  days: number[];
  selectedProduct: Product | null;
  selectedDay: number | null;
  setDatasetInfo: (info: DatasetInfo) => void;
  setProducts: (products: Product[]) => void;
  setDays: (days: number[]) => void;
  setSelectedProduct: (product: Product) => void;
  setSelectedDay: (day: number) => void;
}

export const useDatasetStore = create<DatasetStoreState>((set) => ({
  datasetInfo: null,
  products: [],
  days: [],
  selectedProduct: null,
  selectedDay: null,
  setDatasetInfo: (info) =>
    set({
      datasetInfo: info,
      products: info.products ?? [],
      days: info.days ?? [],
      selectedProduct: info.products?.[0] ?? null,
      selectedDay: info.days?.[0] ?? null,
    }),
  setProducts: (products) => set({ products }),
  setDays: (days) => set({ days }),
  setSelectedProduct: (product) => set({ selectedProduct: product }),
  setSelectedDay: (day) => set({ selectedDay: day }),
}));

// === Replay Store ===

const defaultPnl: PnLState = {
  timestamp: 0,
  realized_pnl: 0,
  unrealized_pnl: 0,
  total_pnl: 0,
  inventory: {},
  cash: 0,
};

const defaultInventory: InventoryState = {
  positions: {},
  total_unrealized_pnl: 0,
  total_realized_pnl: 0,
};

interface ReplayStoreState {
  sessionId: string | null;
  isPlaying: boolean;
  currentTimestamp: number;
  speed: number;
  totalEvents: number;
  currentIndex: number;
  books: Record<string, VisibleOrderBook>;
  trades: TradePrint[];
  positions: Record<string, PositionState>;
  pnl: PnLState;
  inventory: InventoryState;
  setSessionId: (id: string | null) => void;
  setPlaying: (playing: boolean) => void;
  setSpeed: (speed: number) => void;
  updateReplayState: (state: Partial<ReplayState>) => void;
  updateFromStepResponse: (state: {
    books?: Record<string, VisibleOrderBook>;
    trades?: TradePrint[];
    positions?: Record<string, unknown>;
    pnl?: PnLState;
  }) => void;
  resetReplay: () => void;
}

export const useReplayStore = create<ReplayStoreState>((set) => ({
  sessionId: null,
  isPlaying: false,
  currentTimestamp: 0,
  speed: 1,
  totalEvents: 0,
  currentIndex: 0,
  books: {},
  trades: [],
  positions: {},
  pnl: defaultPnl,
  inventory: defaultInventory,
  setSessionId: (id) => set({ sessionId: id }),
  setPlaying: (playing) => set({ isPlaying: playing }),
  setSpeed: (speed) => set({ speed }),
  updateReplayState: (state) =>
    set((prev) => ({
      isPlaying: state.is_playing ?? prev.isPlaying,
      currentTimestamp: state.current_timestamp ?? prev.currentTimestamp,
      speed: state.speed ?? prev.speed,
      totalEvents: state.total_events ?? prev.totalEvents,
      currentIndex: state.current_index ?? prev.currentIndex,
      books: state.books ?? prev.books,
      trades: state.trades ?? prev.trades,
      positions: state.positions ?? prev.positions,
      pnl: state.pnl ?? prev.pnl,
      inventory: state.inventory ?? prev.inventory,
    })),
  updateFromStepResponse: (state) =>
    set((prev) => ({
      books: state.books ?? prev.books,
      trades: state.trades ? [...prev.trades, ...state.trades] : prev.trades,
      pnl: state.pnl ?? prev.pnl,
      currentIndex: prev.currentIndex + 1,
    })),
  resetReplay: () =>
    set({
      sessionId: null,
      isPlaying: false,
      currentTimestamp: 0,
      currentIndex: 0,
      books: {},
      trades: [],
      positions: {},
      pnl: defaultPnl,
      inventory: defaultInventory,
    }),
}));

// === Backtest Store ===

interface BacktestStoreState {
  runs: BacktestRun[];
  currentRun: BacktestRun | null;
  metrics: (PerformanceMetrics & Partial<ExecutionMetrics>) | null;
  trace: DebugFrame[];
  fills: FillEvent[];
  pnlHistory: PnLState[];
  ohlcv: OHLCVBar[];
  setRuns: (runs: BacktestRun[]) => void;
  setCurrentRun: (run: BacktestRun | null) => void;
  setMetrics: (metrics: PerformanceMetrics & Partial<ExecutionMetrics>) => void;
  setTrace: (trace: DebugFrame[]) => void;
  setFills: (fills: FillEvent[]) => void;
  setPnlHistory: (pnl: PnLState[]) => void;
  setOhlcv: (bars: OHLCVBar[]) => void;
  addRun: (run: BacktestRun) => void;
}

export const useBacktestStore = create<BacktestStoreState>((set) => ({
  runs: [],
  currentRun: null,
  metrics: null,
  trace: [],
  fills: [],
  pnlHistory: [],
  ohlcv: [],
  setRuns: (runs) => set({ runs }),
  setCurrentRun: (run) => set({ currentRun: run }),
  setMetrics: (metrics) => set({ metrics }),
  setTrace: (trace) => set({ trace }),
  setFills: (fills) => set({ fills }),
  setPnlHistory: (pnl) => set({ pnlHistory: pnl }),
  setOhlcv: (bars) => set({ ohlcv: bars }),
  addRun: (run) => set((prev) => ({ runs: [...prev.runs, run] })),
}));

// === Strategy Store ===

interface StrategyStoreState {
  strategies: StrategyDefinition[];
  selectedStrategy: StrategyDefinition | null;
  parameters: Record<string, unknown>;
  sourceCode: string;
  setStrategies: (strategies: StrategyDefinition[]) => void;
  setSelectedStrategy: (strategy: StrategyDefinition | null) => void;
  setParameter: (name: string, value: unknown) => void;
  setParameters: (params: Record<string, unknown>) => void;
  setSourceCode: (code: string) => void;
  resetParameters: () => void;
}

export const useStrategyStore = create<StrategyStoreState>((set, get) => ({
  strategies: [],
  selectedStrategy: null,
  parameters: {},
  sourceCode: '',
  setStrategies: (strategies) => set({ strategies }),
  setSelectedStrategy: (strategy) => {
    const params: Record<string, unknown> = {};
    if (strategy?.parameters) {
      strategy.parameters.forEach((p: StrategyParameter) => {
        params[p.name] = p.default;
      });
    }
    set({ selectedStrategy: strategy, parameters: params, sourceCode: '' });
  },
  setParameter: (name, value) =>
    set((prev) => ({ parameters: { ...prev.parameters, [name]: value } })),
  setParameters: (params) => set({ parameters: params }),
  setSourceCode: (code) => set({ sourceCode: code }),
  resetParameters: () => {
    const strat = get().selectedStrategy;
    if (!strat?.parameters) return;
    const params: Record<string, unknown> = {};
    strat.parameters.forEach((p: StrategyParameter) => {
      params[p.name] = p.default;
    });
    set({ parameters: params });
  },
}));

// === UI Store ===

interface UIStoreState {
  activeWorkspace: WorkspacePreset;
  selectedIndicators: string[];
  chartMode: ChartMode;
  bottomTab: string;
  showSettings: boolean;
  setActiveWorkspace: (workspace: WorkspacePreset) => void;
  setSelectedIndicators: (indicators: string[]) => void;
  toggleIndicator: (indicator: string) => void;
  setChartMode: (mode: ChartMode) => void;
  setBottomTab: (tab: string) => void;
  setShowSettings: (show: boolean) => void;
}

export const useUIStore = create<UIStoreState>((set) => ({
  activeWorkspace: 'trading',
  selectedIndicators: [],
  chartMode: 'candlestick',
  bottomTab: 'trades',
  showSettings: false,
  setActiveWorkspace: (workspace) => set({ activeWorkspace: workspace }),
  setSelectedIndicators: (indicators) => set({ selectedIndicators: indicators }),
  toggleIndicator: (indicator) =>
    set((prev) => ({
      selectedIndicators: prev.selectedIndicators.includes(indicator)
        ? prev.selectedIndicators.filter((i) => i !== indicator)
        : [...prev.selectedIndicators, indicator],
    })),
  setChartMode: (mode) => set({ chartMode: mode }),
  setBottomTab: (tab) => set({ bottomTab: tab }),
  setShowSettings: (show) => set({ showSettings: show }),
}));
