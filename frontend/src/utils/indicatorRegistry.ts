/**
 * Indicator Registry — metadata for all available indicators.
 *
 * Each entry describes how to compute, render, and configure one indicator.
 */

export type IndicatorPlacement = 'overlay' | 'pane';

export interface IndicatorParam {
  name: string;
  label: string;
  type: 'int' | 'float';
  default: number;
  min?: number;
  max?: number;
}

export interface IndicatorDef {
  id: string;
  name: string;
  shortName: string;
  category: string;
  placement: IndicatorPlacement;
  description: string;
  color: string;
  /** Additional colors for multi-line indicators (e.g., bands upper/lower) */
  colors?: string[];
  /** Number of output series (default 1) */
  outputs?: number;
  /** Names for multiple output series */
  outputNames?: string[];
  params: IndicatorParam[];
  /** Data requirements beyond closes */
  requires?: ('highs' | 'lows' | 'opens' | 'volumes' | 'books' | 'trades' | 'fills')[];
}

// Color palette for indicators
const C = {
  amber: '#f59e0b',
  purple: '#8b5cf6',
  cyan: '#22d3ee',
  orange: '#f97316',
  green: '#10b981',
  red: '#ef4444',
  blue: '#3b82f6',
  pink: '#ec4899',
  lime: '#84cc16',
  teal: '#14b8a6',
  indigo: '#6366f1',
  yellow: '#eab308',
  rose: '#f43f5e',
  sky: '#0ea5e9',
  violet: '#7c3aed',
  fuchsia: '#d946ef',
  gray: '#a3a3a3',
  emerald: '#34d399',
  slate: '#94a3b8',
  warmGray: '#a8a29e',
};

export const INDICATOR_CATEGORIES = [
  { id: 'trend', label: 'Trend & Fair Value', icon: '📈' },
  { id: 'bands', label: 'Bands & Channels', icon: '📊' },
  { id: 'momentum', label: 'Momentum & Oscillators', icon: '⚡' },
  { id: 'volatility', label: 'Volatility', icon: '🌊' },
  { id: 'volume', label: 'Volume & Flow', icon: '📦' },
  { id: 'orderflow', label: 'Order Flow & Tape', icon: '🔄' },
  { id: 'microstructure', label: 'Spread & Microstructure', icon: '🔬' },
  { id: 'execution', label: 'Execution Quality', icon: '🎯' },
  { id: 'regime', label: 'Regime & Composite', icon: '🧭' },
];

export const INDICATORS: IndicatorDef[] = [
  // ========== TREND & FAIR VALUE (Overlays) ==========
  { id: 'SMA', name: 'Simple Moving Average', shortName: 'SMA', category: 'trend', placement: 'overlay', description: 'Baseline smoothing of price', color: C.amber, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 500 }] },
  { id: 'EMA', name: 'Exponential Moving Average', shortName: 'EMA', category: 'trend', placement: 'overlay', description: 'Faster trend response than SMA', color: C.purple, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 500 }] },
  { id: 'WMA', name: 'Weighted Moving Average', shortName: 'WMA', category: 'trend', placement: 'overlay', description: 'Emphasizes recent price more heavily', color: C.teal, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 500 }] },
  { id: 'VWMA', name: 'Volume-Weighted Moving Average', shortName: 'VWMA', category: 'trend', placement: 'overlay', description: 'Adds size awareness to trend', color: C.sky, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 500 }], requires: ['volumes'] },
  { id: 'HMA', name: 'Hull Moving Average', shortName: 'HMA', category: 'trend', placement: 'overlay', description: 'Smoother and lower lag trend line', color: C.lime, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 500 }] },
  { id: 'DEMA', name: 'Double EMA', shortName: 'DEMA', category: 'trend', placement: 'overlay', description: 'Reduced lag relative to EMA', color: C.pink, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 500 }] },
  { id: 'TEMA', name: 'Triple EMA', shortName: 'TEMA', category: 'trend', placement: 'overlay', description: 'Even more lag-reduced trend', color: C.rose, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 500 }] },
  { id: 'KAMA', name: 'Kaufman Adaptive MA', shortName: 'KAMA', category: 'trend', placement: 'overlay', description: 'Adapts to noise and trend efficiency', color: C.indigo, params: [{ name: 'period', label: 'Period', type: 'int', default: 10, min: 2, max: 500 }] },
  { id: 'ZLEMA', name: 'Zero-Lag EMA', shortName: 'ZLEMA', category: 'trend', placement: 'overlay', description: 'Trend line with less lag', color: C.fuchsia, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 500 }] },
  { id: 'MCGINLEY', name: 'McGinley Dynamic', shortName: 'McGinley', category: 'trend', placement: 'overlay', description: 'Adaptive smoother tracking price', color: C.emerald, params: [{ name: 'period', label: 'Period', type: 'int', default: 14, min: 2, max: 500 }] },
  { id: 'ALMA', name: 'Arnaud Legoux MA', shortName: 'ALMA', category: 'trend', placement: 'overlay', description: 'Smooth trend with reduced lag/noise', color: C.violet, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 500 }] },
  { id: 'VWAP', name: 'Session VWAP', shortName: 'VWAP', category: 'trend', placement: 'overlay', description: 'Critical fair-value anchor for intraday', color: C.cyan, params: [], requires: ['volumes'] },
  { id: 'ROLLING_VWAP', name: 'Rolling VWAP', shortName: 'R-VWAP', category: 'trend', placement: 'overlay', description: 'Local fair-value over moving window', color: C.sky, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 500 }], requires: ['volumes'] },
  { id: 'TWAP', name: 'TWAP Line', shortName: 'TWAP', category: 'trend', placement: 'overlay', description: 'Time-weighted average reference', color: C.slate, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 500 }] },
  { id: 'ICHIMOKU_TENKAN', name: 'Ichimoku Tenkan-sen', shortName: 'Tenkan', category: 'trend', placement: 'overlay', description: 'Short-horizon balance line', color: C.blue, params: [{ name: 'period', label: 'Period', type: 'int', default: 9, min: 2, max: 100 }], requires: ['highs', 'lows'] },
  { id: 'ICHIMOKU_KIJUN', name: 'Ichimoku Kijun-sen', shortName: 'Kijun', category: 'trend', placement: 'overlay', description: 'Medium-horizon balance line', color: C.red, params: [{ name: 'period', label: 'Period', type: 'int', default: 26, min: 2, max: 200 }], requires: ['highs', 'lows'] },
  { id: 'ICHIMOKU_CLOUD', name: 'Ichimoku Cloud', shortName: 'Cloud', category: 'trend', placement: 'overlay', description: 'Trend/regime/structure map', color: C.green, colors: [C.green, C.red], outputs: 2, outputNames: ['Senkou A', 'Senkou B'], params: [], requires: ['highs', 'lows'] },
  { id: 'MA_ENVELOPE', name: 'Moving Average Envelope', shortName: 'MA Env', category: 'trend', placement: 'overlay', description: 'Upper/lower drift channels', color: C.warmGray, colors: [C.warmGray, C.amber, C.amber], outputs: 3, outputNames: ['Mid', 'Upper', 'Lower'], params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 500 }, { name: 'pct', label: 'Percent', type: 'float', default: 2.5, min: 0.1, max: 20 }] },
  { id: 'LINREG', name: 'Linear Regression', shortName: 'LinReg', category: 'trend', placement: 'overlay', description: 'Local trend fit', color: C.orange, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 500 }] },
  { id: 'LINREG_CHANNEL', name: 'Linear Regression Channel', shortName: 'LinReg Ch', category: 'trend', placement: 'overlay', description: 'Slope + deviation around fitted trend', color: C.orange, colors: [C.orange, C.yellow, C.yellow], outputs: 3, outputNames: ['Mid', 'Upper', 'Lower'], params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 500 }, { name: 'mult', label: 'Multiplier', type: 'float', default: 2, min: 0.5, max: 5 }] },
  { id: 'STDDEV_CHANNEL', name: 'Std Deviation Channel', shortName: 'StdDev Ch', category: 'trend', placement: 'overlay', description: 'Price envelope around SMA', color: C.gray, colors: [C.gray, C.slate, C.slate], outputs: 3, outputNames: ['Mid', 'Upper', 'Lower'], params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 500 }, { name: 'mult', label: 'Multiplier', type: 'float', default: 2, min: 0.5, max: 5 }] },

  // ========== BANDS & CHANNELS (Overlays) ==========
  { id: 'BB', name: 'Bollinger Bands', shortName: 'BB', category: 'bands', placement: 'overlay', description: 'Volatility bands around moving mean', color: C.gray, colors: [C.gray, C.orange, C.orange], outputs: 3, outputNames: ['Mid', 'Upper', 'Lower'], params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 500 }, { name: 'mult', label: 'StdDev', type: 'float', default: 2, min: 0.5, max: 5 }] },
  { id: 'KELTNER', name: 'Keltner Channel', shortName: 'KC', category: 'bands', placement: 'overlay', description: 'ATR-based volatility channel', color: C.teal, colors: [C.teal, C.emerald, C.emerald], outputs: 3, outputNames: ['Mid', 'Upper', 'Lower'], params: [{ name: 'period', label: 'EMA Period', type: 'int', default: 20, min: 2, max: 500 }, { name: 'mult', label: 'Multiplier', type: 'float', default: 1.5, min: 0.5, max: 5 }], requires: ['highs', 'lows'] },
  { id: 'DONCHIAN', name: 'Donchian Channel', shortName: 'DC', category: 'bands', placement: 'overlay', description: 'Breakout range high/low', color: C.blue, colors: [C.blue, C.sky, C.sky], outputs: 3, outputNames: ['Mid', 'Upper', 'Lower'], params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 500 }], requires: ['highs', 'lows'] },
  { id: 'ATR_BANDS', name: 'ATR Bands', shortName: 'ATR Bands', category: 'bands', placement: 'overlay', description: 'Volatility expansion bands', color: C.purple, colors: [C.purple, C.violet, C.violet], outputs: 3, outputNames: ['Mid', 'Upper', 'Lower'], params: [{ name: 'period', label: 'Period', type: 'int', default: 14, min: 2, max: 500 }, { name: 'mult', label: 'Multiplier', type: 'float', default: 2, min: 0.5, max: 5 }], requires: ['highs', 'lows'] },
  { id: 'SUPERTREND', name: 'Supertrend', shortName: 'ST', category: 'bands', placement: 'overlay', description: 'Trend-following band/stop system', color: C.green, params: [{ name: 'period', label: 'Period', type: 'int', default: 10, min: 2, max: 100 }, { name: 'mult', label: 'Multiplier', type: 'float', default: 3, min: 0.5, max: 10 }], requires: ['highs', 'lows'] },
  { id: 'PSAR', name: 'Parabolic SAR', shortName: 'PSAR', category: 'bands', placement: 'overlay', description: 'Trailing stop / reversal dots', color: C.yellow, params: [{ name: 'accelInit', label: 'Accel Start', type: 'float', default: 0.02, min: 0.005, max: 0.1 }, { name: 'accelMax', label: 'Accel Max', type: 'float', default: 0.2, min: 0.05, max: 0.5 }], requires: ['highs', 'lows'] },
  { id: 'CHANDELIER', name: 'Chandelier Exit', shortName: 'Chand', category: 'bands', placement: 'overlay', description: 'ATR-based trailing exit', color: C.rose, colors: [C.green, C.red], outputs: 2, outputNames: ['Long Exit', 'Short Exit'], params: [{ name: 'period', label: 'Period', type: 'int', default: 22, min: 2, max: 200 }, { name: 'mult', label: 'Multiplier', type: 'float', default: 3, min: 0.5, max: 10 }], requires: ['highs', 'lows'] },
  { id: 'PIVOT', name: 'Pivot Points', shortName: 'Pivot', category: 'bands', placement: 'overlay', description: 'Standard support/resistance', color: C.indigo, colors: [C.indigo, C.green, C.green, C.green, C.red, C.red, C.red], outputs: 7, outputNames: ['PP', 'R1', 'R2', 'R3', 'S1', 'S2', 'S3'], params: [], requires: ['highs', 'lows'] },
  { id: 'CAMARILLA', name: 'Camarilla Pivots', shortName: 'Cam', category: 'bands', placement: 'overlay', description: 'Intraday pivot structure', color: C.fuchsia, outputs: 9, outputNames: ['PP', 'R1', 'R2', 'R3', 'R4', 'S1', 'S2', 'S3', 'S4'], params: [], requires: ['highs', 'lows'] },
  { id: 'SESSION_HL', name: 'Session High/Low', shortName: 'Sess HL', category: 'bands', placement: 'overlay', description: 'Running session high and low', color: C.green, colors: [C.green, C.red], outputs: 2, outputNames: ['High', 'Low'], params: [], requires: ['highs', 'lows'] },
  { id: 'ROLLING_HL', name: 'Rolling High/Low', shortName: 'Roll HL', category: 'bands', placement: 'overlay', description: 'Dynamic structure levels', color: C.amber, colors: [C.green, C.red], outputs: 2, outputNames: ['High', 'Low'], params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 500 }], requires: ['highs', 'lows'] },
  { id: 'PREV_BAR_HL', name: 'Previous Bar High/Low', shortName: 'PrevHL', category: 'bands', placement: 'overlay', description: 'Micro breakout trigger lines', color: C.slate, colors: [C.green, C.red], outputs: 2, outputNames: ['Prev High', 'Prev Low'], params: [], requires: ['highs', 'lows'] },
  { id: 'PREV_CLOSE', name: 'Previous Session Close', shortName: 'PrevC', category: 'bands', placement: 'overlay', description: 'Gap/mean-reversion reference', color: C.warmGray, params: [] },

  // ========== MOMENTUM & OSCILLATORS (Panes) ==========
  { id: 'RSI', name: 'Relative Strength Index', shortName: 'RSI', category: 'momentum', placement: 'pane', description: 'Classic bounded momentum oscillator', color: C.purple, params: [{ name: 'period', label: 'Period', type: 'int', default: 14, min: 2, max: 100 }] },
  { id: 'STOCH', name: 'Stochastic Oscillator', shortName: 'Stoch', category: 'momentum', placement: 'pane', description: 'Close location within recent range', color: C.blue, colors: [C.blue, C.orange], outputs: 2, outputNames: ['%K', '%D'], params: [{ name: 'kPeriod', label: 'K Period', type: 'int', default: 14, min: 2, max: 100 }, { name: 'dPeriod', label: 'D Period', type: 'int', default: 3, min: 1, max: 50 }], requires: ['highs', 'lows'] },
  { id: 'STOCH_RSI', name: 'Stochastic RSI', shortName: 'StochRSI', category: 'momentum', placement: 'pane', description: 'RSI momentum of momentum', color: C.indigo, colors: [C.indigo, C.pink], outputs: 2, outputNames: ['%K', '%D'], params: [{ name: 'rsiPeriod', label: 'RSI Period', type: 'int', default: 14, min: 2, max: 100 }] },
  { id: 'MACD', name: 'MACD', shortName: 'MACD', category: 'momentum', placement: 'pane', description: 'Trend-momentum differential', color: C.cyan, colors: [C.cyan, C.orange, C.gray], outputs: 3, outputNames: ['MACD', 'Signal', 'Histogram'], params: [{ name: 'fast', label: 'Fast', type: 'int', default: 12, min: 2, max: 100 }, { name: 'slow', label: 'Slow', type: 'int', default: 26, min: 2, max: 200 }, { name: 'signal', label: 'Signal', type: 'int', default: 9, min: 2, max: 50 }] },
  { id: 'PPO', name: 'Percentage Price Osc', shortName: 'PPO', category: 'momentum', placement: 'pane', description: 'Percentage-normalized MACD', color: C.teal, colors: [C.teal, C.orange, C.gray], outputs: 3, outputNames: ['PPO', 'Signal', 'Histogram'], params: [{ name: 'fast', label: 'Fast', type: 'int', default: 12, min: 2, max: 100 }, { name: 'slow', label: 'Slow', type: 'int', default: 26, min: 2, max: 200 }] },
  { id: 'ROC', name: 'Rate of Change', shortName: 'ROC', category: 'momentum', placement: 'pane', description: 'Raw momentum percentage', color: C.orange, params: [{ name: 'period', label: 'Period', type: 'int', default: 12, min: 1, max: 200 }] },
  { id: 'MOM', name: 'Momentum', shortName: 'MOM', category: 'momentum', placement: 'pane', description: 'Absolute price momentum', color: C.lime, params: [{ name: 'period', label: 'Period', type: 'int', default: 10, min: 1, max: 200 }] },
  { id: 'CCI', name: 'Commodity Channel Index', shortName: 'CCI', category: 'momentum', placement: 'pane', description: 'Mean deviation / cyclical momentum', color: C.amber, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }], requires: ['highs', 'lows'] },
  { id: 'WILLIAMS_R', name: 'Williams %R', shortName: '%R', category: 'momentum', placement: 'pane', description: 'Overbought/oversold range position', color: C.red, params: [{ name: 'period', label: 'Period', type: 'int', default: 14, min: 2, max: 100 }], requires: ['highs', 'lows'] },
  { id: 'UO', name: 'Ultimate Oscillator', shortName: 'UO', category: 'momentum', placement: 'pane', description: 'Multi-window momentum blend', color: C.emerald, params: [{ name: 'p1', label: 'Period 1', type: 'int', default: 7, min: 1, max: 50 }, { name: 'p2', label: 'Period 2', type: 'int', default: 14, min: 2, max: 100 }, { name: 'p3', label: 'Period 3', type: 'int', default: 28, min: 3, max: 200 }], requires: ['highs', 'lows'] },
  { id: 'AO', name: 'Awesome Oscillator', shortName: 'AO', category: 'momentum', placement: 'pane', description: 'Median price momentum', color: C.green, params: [], requires: ['highs', 'lows'] },
  { id: 'AC', name: 'Accelerator Oscillator', shortName: 'AC', category: 'momentum', placement: 'pane', description: 'Momentum change of AO', color: C.pink, params: [], requires: ['highs', 'lows'] },
  { id: 'TRIX', name: 'TRIX', shortName: 'TRIX', category: 'momentum', placement: 'pane', description: 'Triple-smoothed momentum ROC', color: C.violet, params: [{ name: 'period', label: 'Period', type: 'int', default: 15, min: 2, max: 100 }] },
  { id: 'TSI', name: 'True Strength Index', shortName: 'TSI', category: 'momentum', placement: 'pane', description: 'Smoothed momentum strength', color: C.sky, params: [{ name: 'longPeriod', label: 'Long', type: 'int', default: 25, min: 5, max: 100 }, { name: 'shortPeriod', label: 'Short', type: 'int', default: 13, min: 2, max: 50 }] },
  { id: 'CMO', name: 'Chande Momentum Osc', shortName: 'CMO', category: 'momentum', placement: 'pane', description: 'Bounded momentum study', color: C.rose, params: [{ name: 'period', label: 'Period', type: 'int', default: 14, min: 2, max: 100 }] },
  { id: 'DPO', name: 'Detrended Price Osc', shortName: 'DPO', category: 'momentum', placement: 'pane', description: 'Cycle-focused deviation from trend', color: C.fuchsia, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }] },
  { id: 'CRSI', name: 'Connors RSI', shortName: 'CRSI', category: 'momentum', placement: 'pane', description: 'Composite short-term reversal osc', color: C.indigo, params: [] },
  { id: 'FISHER', name: 'Fisher Transform', shortName: 'Fisher', category: 'momentum', placement: 'pane', description: 'Sharp turning-point transformation', color: C.cyan, colors: [C.cyan, C.orange], outputs: 2, outputNames: ['Fisher', 'Trigger'], params: [{ name: 'period', label: 'Period', type: 'int', default: 10, min: 2, max: 100 }], requires: ['highs', 'lows'] },
  { id: 'SCHAFF', name: 'Schaff Trend Cycle', shortName: 'STC', category: 'momentum', placement: 'pane', description: 'Fast cycle/trend transition', color: C.emerald, params: [] },
  { id: 'RVI', name: 'Relative Vigor Index', shortName: 'RVI', category: 'momentum', placement: 'pane', description: 'Conviction of close vs range', color: C.blue, colors: [C.blue, C.red], outputs: 2, outputNames: ['RVI', 'Signal'], params: [{ name: 'period', label: 'Period', type: 'int', default: 10, min: 2, max: 100 }], requires: ['opens', 'highs', 'lows'] },
  { id: 'ELDER_BULL', name: 'Elder Ray Bull Power', shortName: 'Bull', category: 'momentum', placement: 'pane', description: 'Bull pressure vs EMA baseline', color: C.green, params: [{ name: 'period', label: 'Period', type: 'int', default: 13, min: 2, max: 100 }], requires: ['highs'] },
  { id: 'ELDER_BEAR', name: 'Elder Ray Bear Power', shortName: 'Bear', category: 'momentum', placement: 'pane', description: 'Bear pressure vs EMA baseline', color: C.red, params: [{ name: 'period', label: 'Period', type: 'int', default: 13, min: 2, max: 100 }], requires: ['lows'] },
  { id: 'AROON', name: 'Aroon', shortName: 'Aroon', category: 'momentum', placement: 'pane', description: 'Trend emergence / decay', color: C.green, colors: [C.green, C.red, C.amber], outputs: 3, outputNames: ['Up', 'Down', 'Oscillator'], params: [{ name: 'period', label: 'Period', type: 'int', default: 25, min: 2, max: 200 }], requires: ['highs', 'lows'] },
  { id: 'ADX', name: 'ADX / DI', shortName: 'ADX', category: 'momentum', placement: 'pane', description: 'Trend strength + direction', color: C.amber, colors: [C.amber, C.green, C.red], outputs: 3, outputNames: ['ADX', '+DI', '-DI'], params: [{ name: 'period', label: 'Period', type: 'int', default: 14, min: 2, max: 100 }], requires: ['highs', 'lows'] },
  { id: 'VORTEX', name: 'Vortex Indicator', shortName: 'Vortex', category: 'momentum', placement: 'pane', description: 'Directional trend confirmation', color: C.green, colors: [C.green, C.red], outputs: 2, outputNames: ['VI+', 'VI-'], params: [{ name: 'period', label: 'Period', type: 'int', default: 14, min: 2, max: 100 }], requires: ['highs', 'lows'] },
  { id: 'MASS_INDEX', name: 'Mass Index', shortName: 'MI', category: 'momentum', placement: 'pane', description: 'Range expansion/reversal study', color: C.orange, params: [], requires: ['highs', 'lows'] },
  { id: 'COPPOCK', name: 'Coppock Curve', shortName: 'Coppock', category: 'momentum', placement: 'pane', description: 'Long-turn momentum study', color: C.teal, params: [] },
  { id: 'KST', name: 'Know Sure Thing', shortName: 'KST', category: 'momentum', placement: 'pane', description: 'Blended multi-horizon momentum', color: C.purple, colors: [C.purple, C.orange], outputs: 2, outputNames: ['KST', 'Signal'], params: [] },
  { id: 'QSTICK', name: 'Qstick', shortName: 'Qstick', category: 'momentum', placement: 'pane', description: 'Candlestick body bias', color: C.lime, params: [{ name: 'period', label: 'Period', type: 'int', default: 14, min: 2, max: 100 }], requires: ['opens'] },
  { id: 'SQUEEZE', name: 'Squeeze Momentum', shortName: 'Squeeze', category: 'momentum', placement: 'pane', description: 'Squeeze-release momentum monitor', color: C.cyan, params: [], requires: ['highs', 'lows'] },
  { id: 'CHOP', name: 'Choppiness Index', shortName: 'CHOP', category: 'momentum', placement: 'pane', description: 'Trend vs chop regime filter', color: C.warmGray, params: [{ name: 'period', label: 'Period', type: 'int', default: 14, min: 2, max: 100 }], requires: ['highs', 'lows'] },
  { id: 'ER', name: 'Efficiency Ratio', shortName: 'ER', category: 'momentum', placement: 'pane', description: 'Trend efficiency vs noise', color: C.sky, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }] },
  { id: 'HURST', name: 'Hurst Exponent', shortName: 'Hurst', category: 'momentum', placement: 'pane', description: 'Persistence vs mean reversion', color: C.violet, params: [{ name: 'period', label: 'Period', type: 'int', default: 50, min: 10, max: 500 }] },
  { id: 'FRACTAL_DIM', name: 'Fractal Dimension', shortName: 'FDI', category: 'momentum', placement: 'pane', description: 'Market smoothness/choppiness', color: C.fuchsia, params: [{ name: 'period', label: 'Period', type: 'int', default: 30, min: 4, max: 200 }] },

  // ========== VOLATILITY (Panes) ==========
  { id: 'ATR', name: 'Average True Range', shortName: 'ATR', category: 'volatility', placement: 'pane', description: 'Raw volatility/range measure', color: C.orange, params: [{ name: 'period', label: 'Period', type: 'int', default: 14, min: 2, max: 200 }], requires: ['highs', 'lows'] },
  { id: 'NATR', name: 'Normalized ATR', shortName: 'NATR', category: 'volatility', placement: 'pane', description: 'ATR relative to price level', color: C.amber, params: [{ name: 'period', label: 'Period', type: 'int', default: 14, min: 2, max: 200 }], requires: ['highs', 'lows'] },
  { id: 'HVOL', name: 'Historical Volatility', shortName: 'HVol', category: 'volatility', placement: 'pane', description: 'Rolling realized variance from returns', color: C.purple, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }] },
  { id: 'RVOL', name: 'Realized Volatility', shortName: 'RVol', category: 'volatility', placement: 'pane', description: 'Actual short-horizon variability', color: C.indigo, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }] },
  { id: 'PARKINSON', name: 'Parkinson Volatility', shortName: 'PkVol', category: 'volatility', placement: 'pane', description: 'Range-based estimator', color: C.rose, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }], requires: ['highs', 'lows'] },
  { id: 'GARMAN_KLASS', name: 'Garman-Klass Volatility', shortName: 'GK Vol', category: 'volatility', placement: 'pane', description: 'OHLC-based volatility estimator', color: C.teal, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }], requires: ['opens', 'highs', 'lows'] },
  { id: 'RS_VOL', name: 'Rogers-Satchell Volatility', shortName: 'RS Vol', category: 'volatility', placement: 'pane', description: 'Directional-robust OHLC vol', color: C.sky, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }], requires: ['opens', 'highs', 'lows'] },
  { id: 'ROLLING_STDDEV', name: 'Rolling Standard Deviation', shortName: 'StdDev', category: 'volatility', placement: 'pane', description: 'Dispersion of returns', color: C.gray, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }] },
  { id: 'VOL_RATIO', name: 'Volatility Ratio', shortName: 'VRatio', category: 'volatility', placement: 'pane', description: 'Short vs long vol comparison', color: C.lime, params: [{ name: 'shortPeriod', label: 'Short', type: 'int', default: 10, min: 2, max: 100 }, { name: 'longPeriod', label: 'Long', type: 'int', default: 50, min: 5, max: 500 }] },
  { id: 'ROLLING_RANGE', name: 'Rolling High-Low Range', shortName: 'Range', category: 'volatility', placement: 'pane', description: 'Expansion/contraction monitor', color: C.emerald, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }], requires: ['highs', 'lows'] },
  { id: 'BB_WIDTH', name: 'Bollinger Band Width', shortName: 'BBW', category: 'volatility', placement: 'pane', description: 'Squeeze and expansion tracker', color: C.orange, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }] },
  { id: 'BB_PCT_B', name: 'Bollinger %B', shortName: '%B', category: 'volatility', placement: 'pane', description: 'Location within Bollinger structure', color: C.purple, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }] },
  { id: 'KC_WIDTH', name: 'Keltner Width', shortName: 'KCW', category: 'volatility', placement: 'pane', description: 'Volatility channel width monitor', color: C.teal, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }], requires: ['highs', 'lows'] },
  { id: 'VOL_OF_VOL', name: 'Vol-of-Vol', shortName: 'VoV', category: 'volatility', placement: 'pane', description: 'Volatility instability measure', color: C.fuchsia, params: [{ name: 'volPeriod', label: 'Vol Period', type: 'int', default: 20, min: 2, max: 200 }, { name: 'vovPeriod', label: 'VoV Period', type: 'int', default: 20, min: 2, max: 200 }] },

  // ========== VOLUME & FLOW (Panes) ==========
  { id: 'VOL_MA', name: 'Volume Moving Average', shortName: 'Vol MA', category: 'volume', placement: 'pane', description: 'Relative volume reference', color: C.blue, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }], requires: ['volumes'] },
  { id: 'VOL_OSC', name: 'Volume Oscillator', shortName: 'Vol Osc', category: 'volume', placement: 'pane', description: 'Short vs long volume momentum', color: C.cyan, params: [{ name: 'fast', label: 'Fast', type: 'int', default: 5, min: 2, max: 50 }, { name: 'slow', label: 'Slow', type: 'int', default: 20, min: 5, max: 200 }], requires: ['volumes'] },
  { id: 'OBV', name: 'On-Balance Volume', shortName: 'OBV', category: 'volume', placement: 'pane', description: 'Cumulative volume pressure', color: C.green, params: [], requires: ['volumes'] },
  { id: 'AD_LINE', name: 'Accumulation/Distribution', shortName: 'A/D', category: 'volume', placement: 'pane', description: 'Price-volume flow', color: C.purple, params: [], requires: ['highs', 'lows', 'volumes'] },
  { id: 'CMF', name: 'Chaikin Money Flow', shortName: 'CMF', category: 'volume', placement: 'pane', description: 'Money-flow pressure', color: C.teal, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }], requires: ['highs', 'lows', 'volumes'] },
  { id: 'CHAIKIN_OSC', name: 'Chaikin Oscillator', shortName: 'ChOsc', category: 'volume', placement: 'pane', description: 'Momentum of A/D line', color: C.amber, params: [], requires: ['highs', 'lows', 'volumes'] },
  { id: 'MFI', name: 'Money Flow Index', shortName: 'MFI', category: 'volume', placement: 'pane', description: 'Volume-weighted RSI-like study', color: C.orange, params: [{ name: 'period', label: 'Period', type: 'int', default: 14, min: 2, max: 200 }], requires: ['highs', 'lows', 'volumes'] },
  { id: 'EOM', name: 'Ease of Movement', shortName: 'EOM', category: 'volume', placement: 'pane', description: 'Price movement per unit volume', color: C.lime, params: [{ name: 'period', label: 'Period', type: 'int', default: 14, min: 2, max: 200 }], requires: ['highs', 'lows', 'volumes'] },
  { id: 'FORCE', name: 'Force Index', shortName: 'Force', category: 'volume', placement: 'pane', description: 'Force of price change times volume', color: C.red, params: [{ name: 'period', label: 'Period', type: 'int', default: 13, min: 2, max: 200 }], requires: ['volumes'] },
  { id: 'KLINGER', name: 'Klinger Oscillator', shortName: 'Klinger', category: 'volume', placement: 'pane', description: 'Long-short money flow dynamics', color: C.indigo, colors: [C.indigo, C.orange], outputs: 2, outputNames: ['Klinger', 'Signal'], params: [], requires: ['highs', 'lows', 'volumes'] },
  { id: 'PVT', name: 'Price Volume Trend', shortName: 'PVT', category: 'volume', placement: 'pane', description: 'Cumulative volume adjusted by returns', color: C.emerald, params: [], requires: ['volumes'] },
  { id: 'NVI', name: 'Negative Volume Index', shortName: 'NVI', category: 'volume', placement: 'pane', description: 'Behavior on lower-volume periods', color: C.slate, params: [], requires: ['volumes'] },
  { id: 'PVI', name: 'Positive Volume Index', shortName: 'PVI', category: 'volume', placement: 'pane', description: 'Behavior on higher-volume periods', color: C.warmGray, params: [], requires: ['volumes'] },
  { id: 'VOL_ROC', name: 'Volume Rate of Change', shortName: 'VROC', category: 'volume', placement: 'pane', description: 'Growth/decay in volume', color: C.pink, params: [{ name: 'period', label: 'Period', type: 'int', default: 14, min: 1, max: 200 }], requires: ['volumes'] },
  { id: 'REL_VOL', name: 'Relative Volume', shortName: 'RelVol', category: 'volume', placement: 'pane', description: 'Current vs expected baseline', color: C.sky, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }], requires: ['volumes'] },

  // ========== ORDER FLOW (Panes) ==========
  { id: 'TRADE_IMBALANCE', name: 'Trade Imbalance', shortName: 'TImb', category: 'orderflow', placement: 'pane', description: 'Buy vs sell-initiated pressure', color: C.green, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }], requires: ['trades'] },
  { id: 'CUM_DELTA', name: 'Cumulative Delta', shortName: 'CumΔ', category: 'orderflow', placement: 'pane', description: 'Cumulative aggressive buy-sell flow', color: C.cyan, params: [], requires: ['trades'] },
  { id: 'SIGNED_VOL', name: 'Signed Volume', shortName: 'SignVol', category: 'orderflow', placement: 'pane', description: 'Net aggressive flow by interval', color: C.blue, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }], requires: ['trades'] },
  { id: 'TRADE_BURST', name: 'Trade Burst Intensity', shortName: 'Burst', category: 'orderflow', placement: 'pane', description: 'Activity spikes detection', color: C.orange, params: [{ name: 'period', label: 'Period', type: 'int', default: 10, min: 2, max: 200 }], requires: ['trades'] },
  { id: 'ITT', name: 'Inter-Trade Time', shortName: 'ITT', category: 'orderflow', placement: 'pane', description: 'Interval between trades', color: C.purple, params: [], requires: ['trades'] },
  { id: 'ARRIVAL_RATE', name: 'Trade Arrival Rate', shortName: 'Arr Rate', category: 'orderflow', placement: 'pane', description: 'Flow tempo', color: C.teal, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }], requires: ['trades'] },
  { id: 'DIR_PERSIST', name: 'Trade Direction Persistence', shortName: 'DirPer', category: 'orderflow', placement: 'pane', description: 'Consecutive same-side pressure', color: C.rose, params: [{ name: 'period', label: 'Period', type: 'int', default: 10, min: 2, max: 100 }], requires: ['trades'] },

  // ========== MICROSTRUCTURE (Panes) ==========
  { id: 'SPREAD', name: 'Best Bid-Ask Spread', shortName: 'Spread', category: 'microstructure', placement: 'pane', description: 'Absolute spread', color: C.orange, params: [], requires: ['books'] },
  { id: 'REL_SPREAD', name: 'Relative Spread', shortName: 'Rel Spd', category: 'microstructure', placement: 'pane', description: 'Spread normalized by price', color: C.amber, params: [], requires: ['books'] },
  { id: 'SPREAD_Z', name: 'Spread Z-Score', shortName: 'Spd Z', category: 'microstructure', placement: 'pane', description: 'Abnormal quoting regimes', color: C.red, params: [{ name: 'period', label: 'Period', type: 'int', default: 50, min: 5, max: 500 }], requires: ['books'] },
  { id: 'MICRO_DEV', name: 'Microprice Deviation', shortName: 'μDev', category: 'microstructure', placement: 'pane', description: 'Directional bias from book pressure', color: C.cyan, params: [], requires: ['books'] },
  { id: 'TOB_IMB', name: 'Top-of-Book Imbalance', shortName: 'TOB Imb', category: 'microstructure', placement: 'pane', description: 'Strongest short-horizon pressure', color: C.green, params: [], requires: ['books'] },
  { id: 'BID_DEPTH', name: 'Bid Depth', shortName: 'BidDep', category: 'microstructure', placement: 'pane', description: 'Visible demand depth', color: C.green, params: [], requires: ['books'] },
  { id: 'ASK_DEPTH', name: 'Ask Depth', shortName: 'AskDep', category: 'microstructure', placement: 'pane', description: 'Visible supply depth', color: C.red, params: [], requires: ['books'] },
  { id: 'DEPTH_RATIO', name: 'Depth Ratio', shortName: 'DepRat', category: 'microstructure', placement: 'pane', description: 'One-line book-bias indicator', color: C.blue, params: [], requires: ['books'] },
  { id: 'BOOK_PRESSURE', name: 'Book Pressure Score', shortName: 'BookP', category: 'microstructure', placement: 'pane', description: 'Composite pressure indicator', color: C.purple, params: [], requires: ['books'] },

  // ========== EXECUTION QUALITY (Panes) ==========
  { id: 'INVENTORY', name: 'Inventory Curve', shortName: 'Inv', category: 'execution', placement: 'pane', description: 'Position inventory over time', color: C.cyan, params: [], requires: ['fills'] },
  { id: 'REALIZED_PNL', name: 'Realized PnL Curve', shortName: 'RPnL', category: 'execution', placement: 'pane', description: 'Locked-in profit/loss over time', color: C.green, params: [], requires: ['fills'] },

  // ========== REGIME & COMPOSITE (Panes) ==========
  { id: 'TREND_SCORE', name: 'Trend Score', shortName: 'TrScore', category: 'regime', placement: 'pane', description: 'Aggregated trend confirmation', color: C.green, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }] },
  { id: 'MR_SCORE', name: 'Mean-Reversion Score', shortName: 'MRScore', category: 'regime', placement: 'pane', description: 'How stretched price is vs fair value', color: C.purple, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }] },
  { id: 'VOL_REGIME', name: 'Volatility Regime Score', shortName: 'VolReg', category: 'regime', placement: 'pane', description: 'Calm vs explosive state', color: C.orange, params: [] },
  { id: 'FV_DEV', name: 'Fair-Value Deviation', shortName: 'FVDev', category: 'regime', placement: 'pane', description: 'Distance from fair price', color: C.cyan, params: [{ name: 'period', label: 'Period', type: 'int', default: 20, min: 2, max: 200 }] },
];

export function getIndicatorById(id: string): IndicatorDef | undefined {
  return INDICATORS.find(ind => ind.id === id);
}

export function getIndicatorsByCategory(category: string): IndicatorDef[] {
  return INDICATORS.filter(ind => ind.category === category);
}

export function getOverlayIndicators(): IndicatorDef[] {
  return INDICATORS.filter(ind => ind.placement === 'overlay');
}

export function getPaneIndicators(): IndicatorDef[] {
  return INDICATORS.filter(ind => ind.placement === 'pane');
}
