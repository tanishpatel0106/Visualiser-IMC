import React, { useEffect, useRef, useMemo } from 'react';
import { createChart } from 'lightweight-charts';
import type { IChartApi, ISeriesApi, Time } from 'lightweight-charts';
import { useDatasetStore, useBacktestStore, useReplayStore, useUIStore } from '@/store';
import * as api from '@/services/api';
import * as ind from '@/utils/indicators';
import { getIndicatorById, type IndicatorDef } from '@/utils/indicatorRegistry';
import { IndicatorSelector } from '@/components/IndicatorSelector';
import type { ChartMode, IndicatorInstance, OHLCVBar } from '@/types';

const CHART_MODES: { key: ChartMode; label: string }[] = [
  { key: 'candlestick', label: 'Candle' },
  { key: 'line', label: 'Line' },
  { key: 'step', label: 'Step' },
  { key: 'ohlc', label: 'OHLC' },
];

const BASE_UTC = Date.UTC(2025, 0, 1, 9, 0, 0) / 1000;
function toChartTime(ts: number): Time {
  return (BASE_UTC + Math.round(ts * 21.6 / 1000)) as Time;
}

// ─── Shared chart options ───────────────────────────────────

function makeChartOpts(height?: number) {
  return {
    layout: {
      background: { color: '#0a0e17' },
      textColor: '#6b7280',
      fontSize: 10,
      fontFamily: "'JetBrains Mono', monospace",
    },
    grid: {
      vertLines: { color: 'rgba(42,48,64,0.3)' },
      horzLines: { color: 'rgba(42,48,64,0.3)' },
    },
    crosshair: {
      mode: 0 as const,
      vertLine: { color: 'rgba(6,182,212,0.4)', width: 1 as const, style: 2 as const, labelBackgroundColor: '#164e63' },
      horzLine: { color: 'rgba(6,182,212,0.4)', width: 1 as const, style: 2 as const, labelBackgroundColor: '#164e63' },
    },
    rightPriceScale: { borderColor: '#1a1f2e' },
    timeScale: { borderColor: '#1a1f2e', timeVisible: true, secondsVisible: false },
    handleScale: { axisPressedMouseMove: true },
    handleScroll: { vertTouchDrag: false },
    height: height ?? undefined,
  } as const;
}

// ─── Indicator computation dispatcher ───────────────────────

interface OhlcvArrays {
  opens: number[];
  highs: number[];
  lows: number[];
  closes: number[];
  volumes: number[];
  times: Time[];
}

function extractArrays(bars: OHLCVBar[]): OhlcvArrays {
  return {
    opens: bars.map(b => b.open),
    highs: bars.map(b => b.high),
    lows: bars.map(b => b.low),
    closes: bars.map(b => b.close),
    volumes: bars.map(b => b.volume),
    times: bars.map(b => toChartTime(b.timestamp)),
  };
}

type N = number | null;

/** Deduplicate time-series data: keep last value for each time. */
function dedup<T extends { time: Time }>(arr: T[]): T[] {
  if (arr.length <= 1) return arr;
  const map = new Map<number, T>();
  for (const item of arr) {
    map.set(item.time as number, item);
  }
  return Array.from(map.values()).sort((a, b) => (a.time as number) - (b.time as number));
}

/** Compute indicator values. Returns array of series data arrays. */
function computeIndicator(def: IndicatorDef, params: Record<string, number>, data: OhlcvArrays): N[][] {
  const { closes, highs, lows, opens, volumes } = data;
  const p = (name: string, fallback: number) => params[name] ?? fallback;

  switch (def.id) {
    // === TREND ===
    case 'SMA': return [ind.sma(closes, p('period', 20))];
    case 'EMA': return [ind.ema(closes, p('period', 20))];
    case 'WMA': return [ind.wma(closes, p('period', 20))];
    case 'VWMA': return [ind.vwma(closes, volumes, p('period', 20))];
    case 'HMA': return [ind.hma(closes, p('period', 20))];
    case 'DEMA': return [ind.dema(closes, p('period', 20))];
    case 'TEMA': return [ind.tema(closes, p('period', 20))];
    case 'KAMA': return [ind.kama(closes, p('period', 10))];
    case 'ZLEMA': return [ind.zlema(closes, p('period', 20))];
    case 'MCGINLEY': return [ind.mcginleyDynamic(closes, p('period', 14))];
    case 'ALMA': return [ind.alma(closes, p('period', 20))];
    case 'VWAP': return [ind.sessionVwap(closes, volumes)];
    case 'ROLLING_VWAP': return [ind.rollingVwap(closes, volumes, p('period', 20))];
    case 'TWAP': return [ind.twap(closes, p('period', 20))];
    case 'ICHIMOKU_TENKAN': return [ind.ichimokuTenkan(highs, lows, p('period', 9))];
    case 'ICHIMOKU_KIJUN': return [ind.ichimokuKijun(highs, lows, p('period', 26))];
    case 'ICHIMOKU_CLOUD': {
      const a = ind.ichimokuSenkouA(highs, lows);
      const b = ind.ichimokuSenkouB(highs, lows);
      return [a, b];
    }
    case 'MA_ENVELOPE': {
      const { mid, upper, lower } = ind.maEnvelope(closes, p('period', 20), p('pct', 2.5) / 100);
      return [mid, upper, lower];
    }
    case 'LINREG': return [ind.linearRegression(closes, p('period', 20))];
    case 'LINREG_CHANNEL': {
      const { mid, upper, lower } = ind.linearRegressionChannel(closes, p('period', 20), p('mult', 2));
      return [mid, upper, lower];
    }
    case 'STDDEV_CHANNEL': {
      const { mid, upper, lower } = ind.stdDevChannel(closes, p('period', 20), p('mult', 2));
      return [mid, upper, lower];
    }

    // === BANDS ===
    case 'BB': {
      const { mid, upper, lower } = ind.bollingerBands(closes, p('period', 20), p('mult', 2));
      return [mid, upper, lower];
    }
    case 'KELTNER': {
      const { mid, upper, lower } = ind.keltnerChannel(closes, highs, lows, p('period', 20), p('period', 20), p('mult', 1.5));
      return [mid, upper, lower];
    }
    case 'DONCHIAN': {
      const { upper, mid, lower } = ind.donchianChannel(highs, lows, p('period', 20));
      return [mid, upper, lower];
    }
    case 'ATR_BANDS': {
      const { mid, upper, lower } = ind.atrBands(closes, highs, lows, p('period', 14), p('mult', 2));
      return [mid, upper, lower];
    }
    case 'SUPERTREND': {
      const { line } = ind.supertrend(closes, highs, lows, p('period', 10), p('mult', 3));
      return [line];
    }
    case 'PSAR': return [ind.parabolicSar(highs, lows, p('accelInit', 0.02), p('accelMax', 0.2))];
    case 'CHANDELIER': {
      const { longExit, shortExit } = ind.chandelierExit(highs, lows, closes, p('period', 22), p('mult', 3));
      return [longExit, shortExit];
    }
    case 'PIVOT': {
      const { pp, r1, r2, r3, s1, s2, s3 } = ind.pivotPoints(highs, lows, closes);
      return [pp, r1, r2, r3, s1, s2, s3];
    }
    case 'CAMARILLA': {
      const { pp, r1, r2, r3, r4, s1, s2, s3, s4 } = ind.camarillaPivots(highs, lows, closes);
      return [pp, r1, r2, r3, r4, s1, s2, s3, s4];
    }
    case 'SESSION_HL': {
      const { high, low } = ind.sessionHighLow(highs, lows);
      return [high, low];
    }
    case 'ROLLING_HL': {
      const { high, low } = ind.rollingHighLow(highs, lows, p('period', 20));
      return [high, low];
    }
    case 'PREV_BAR_HL': {
      const { high, low } = ind.previousBarHighLow(highs, lows);
      return [high, low];
    }
    case 'PREV_CLOSE': return [ind.previousSessionClose(closes)];

    // === MOMENTUM ===
    case 'RSI': return [ind.rsi(closes, p('period', 14))];
    case 'STOCH': {
      const { k, d } = ind.stochastic(highs, lows, closes, p('kPeriod', 14), p('dPeriod', 3));
      return [k, d];
    }
    case 'STOCH_RSI': {
      const { k, d } = ind.stochasticRsi(closes, p('rsiPeriod', 14));
      return [k, d];
    }
    case 'MACD': {
      const r = ind.macd(closes, p('fast', 12), p('slow', 26), p('signal', 9));
      return [r.macd, r.signal, r.histogram];
    }
    case 'PPO': {
      const r = ind.ppo(closes, p('fast', 12), p('slow', 26));
      return [r.ppo, r.signal, r.histogram];
    }
    case 'ROC': return [ind.roc(closes, p('period', 12))];
    case 'MOM': return [ind.momentum(closes, p('period', 10))];
    case 'CCI': return [ind.cci(highs, lows, closes, p('period', 20))];
    case 'WILLIAMS_R': return [ind.williamsR(highs, lows, closes, p('period', 14))];
    case 'UO': return [ind.ultimateOscillator(highs, lows, closes, p('p1', 7), p('p2', 14), p('p3', 28))];
    case 'AO': return [ind.awesomeOscillator(highs, lows, p('fast', 5), p('slow', 34))];
    case 'AC': return [ind.acceleratorOscillator(highs, lows, p('fast', 5), p('slow', 34))];
    case 'TRIX': return [ind.trix(closes, p('period', 15))];
    case 'TSI': return [ind.tsi(closes, p('longPeriod', 25), p('shortPeriod', 13))];
    case 'CMO': return [ind.cmo(closes, p('period', 14))];
    case 'DPO': return [ind.dpo(closes, p('period', 20))];
    case 'CRSI': return [ind.connorsRsi(closes, p('rsiPeriod', 3), p('streakPeriod', 2), p('rankPeriod', 100))];
    case 'FISHER': {
      const { fisher, trigger } = ind.fisherTransform(highs, lows, p('period', 10));
      return [fisher, trigger];
    }
    case 'SCHAFF': return [ind.schaffTrendCycle(closes, p('fast', 23), p('slow', 50), p('cyclePeriod', 10))];
    case 'RVI': {
      const { rvi, signal } = ind.relativeVigorIndex(opens, highs, lows, closes, p('period', 10));
      return [rvi, signal];
    }
    case 'ELDER_BULL': return [ind.elderRayBull(highs, closes, p('period', 13))];
    case 'ELDER_BEAR': return [ind.elderRayBear(lows, closes, p('period', 13))];
    case 'AROON': {
      const { up, down, oscillator } = ind.aroon(highs, lows, p('period', 25));
      return [up, down, oscillator];
    }
    case 'ADX': {
      const { adx, plusDi, minusDi } = ind.adx(highs, lows, closes, p('period', 14));
      return [adx, plusDi, minusDi];
    }
    case 'VORTEX': {
      const { plus, minus } = ind.vortex(highs, lows, closes, p('period', 14));
      return [plus, minus];
    }
    case 'MASS_INDEX': return [ind.massIndex(highs, lows, p('emaPeriod', 9), p('sumPeriod', 25))];
    case 'COPPOCK': return [ind.coppockCurve(closes, p('longRoc', 14), p('shortRoc', 11), p('wmaPeriod', 10))];
    case 'KST': {
      const { kst, signal } = ind.kst(closes, p('r1', 10), p('r2', 15), p('r3', 20), p('r4', 30), 10, 10, 10, 15, p('sigPeriod', 9));
      return [kst, signal];
    }
    case 'QSTICK': return [ind.qstick(opens, closes, p('period', 14))];
    case 'SQUEEZE': {
      const { value } = ind.squeezeMomentum(closes, highs, lows, p('bbPeriod', 20), p('bbMult', 2), p('kcPeriod', 20), p('kcMult', 1.5));
      return [value];
    }
    case 'CHOP': return [ind.choppinessIndex(highs, lows, closes, p('period', 14))];
    case 'ER': return [ind.efficiencyRatio(closes, p('period', 20))];
    case 'HURST': return [ind.hurstExponent(closes, p('period', 50))];
    case 'FRACTAL_DIM': return [ind.fractalDimension(closes, p('period', 30))];

    // === VOLATILITY ===
    case 'ATR': return [ind.atr(highs, lows, closes, p('period', 14))];
    case 'NATR': return [ind.normalizedAtr(highs, lows, closes, p('period', 14))];
    case 'HVOL': return [ind.historicalVolatility(closes, p('period', 20))];
    case 'RVOL': return [ind.realizedVolatility(closes, p('period', 20))];
    case 'PARKINSON': return [ind.parkinsonVolatility(highs, lows, p('period', 20))];
    case 'GARMAN_KLASS': return [ind.garmanKlassVolatility(opens, highs, lows, closes, p('period', 20))];
    case 'RS_VOL': return [ind.rogersSatchellVolatility(opens, highs, lows, closes, p('period', 20))];
    case 'ROLLING_STDDEV': return [ind.rollingStdDev(closes, p('period', 20))];
    case 'VOL_RATIO': return [ind.volatilityRatio(closes, p('shortPeriod', 10), p('longPeriod', 50))];
    case 'ROLLING_RANGE': return [ind.rollingRange(highs, lows, p('period', 20))];
    case 'BB_WIDTH': return [ind.bollingerWidth(closes, p('period', 20))];
    case 'BB_PCT_B': return [ind.bollingerPercentB(closes, p('period', 20))];
    case 'KC_WIDTH': return [ind.keltnerWidth(closes, highs, lows, p('period', 20))];
    case 'VOL_OF_VOL': return [ind.volOfVol(closes, p('volPeriod', 20), p('vovPeriod', 20))];

    // === VOLUME ===
    case 'VOL_MA': return [ind.volumeMovingAverage(volumes, p('period', 20))];
    case 'VOL_OSC': return [ind.volumeOscillator(volumes, p('fast', 5), p('slow', 20))];
    case 'OBV': return [ind.obv(closes, volumes)];
    case 'AD_LINE': return [ind.accumulationDistribution(highs, lows, closes, volumes)];
    case 'CMF': return [ind.chaikinMoneyFlow(highs, lows, closes, volumes, p('period', 20))];
    case 'CHAIKIN_OSC': return [ind.chaikinOscillator(highs, lows, closes, volumes)];
    case 'MFI': return [ind.mfi(highs, lows, closes, volumes, p('period', 14))];
    case 'EOM': return [ind.eom(highs, lows, volumes, p('period', 14))];
    case 'FORCE': return [ind.forceIndex(closes, volumes, p('period', 13))];
    case 'KLINGER': {
      const { klinger, signal } = ind.klingerOscillator(highs, lows, closes, volumes);
      return [klinger, signal];
    }
    case 'PVT': return [ind.pvt(closes, volumes)];
    case 'NVI': return [ind.nvi(closes, volumes)];
    case 'PVI': return [ind.pvi(closes, volumes)];
    case 'VOL_ROC': return [ind.volumeRoc(volumes, p('period', 14))];
    case 'REL_VOL': return [ind.relativeVolume(volumes, p('period', 20))];

    // === REGIME ===
    case 'TREND_SCORE': return [ind.trendScore(closes, p('period', 20))];
    case 'MR_SCORE': return [ind.meanReversionScore(closes, p('period', 20))];
    case 'VOL_REGIME': return [ind.volatilityRegimeScore(closes)];
    case 'FV_DEV': return [ind.fairValueDeviation(closes, p('period', 20))];

    default: return [];
  }
}

function getColors(def: IndicatorDef): string[] {
  if (def.colors) return def.colors;
  return [def.color];
}

// ─── Reference level config per indicator type ───────────────
/** Returns horizontal reference lines to draw on a pane for a given indicator. */
function getReferenceLevels(id: string): { value: number; color: string; lineStyle: number; label: string }[] {
  switch (id) {
    case 'RSI': case 'STOCH_RSI': case 'CMO':
      return [
        { value: 70, color: 'rgba(239,68,68,0.4)', lineStyle: 2, label: '70' },
        { value: 30, color: 'rgba(16,185,129,0.4)', lineStyle: 2, label: '30' },
        { value: 50, color: 'rgba(107,114,128,0.25)', lineStyle: 2, label: '50' },
      ];
    case 'STOCH': case 'WILLIAMS_R':
      return [
        { value: 80, color: 'rgba(239,68,68,0.4)', lineStyle: 2, label: '80' },
        { value: 20, color: 'rgba(16,185,129,0.4)', lineStyle: 2, label: '20' },
      ];
    case 'MFI':
      return [
        { value: 80, color: 'rgba(239,68,68,0.4)', lineStyle: 2, label: '80' },
        { value: 20, color: 'rgba(16,185,129,0.4)', lineStyle: 2, label: '20' },
      ];
    case 'CRSI': case 'SCHAFF':
      return [
        { value: 90, color: 'rgba(239,68,68,0.4)', lineStyle: 2, label: '90' },
        { value: 10, color: 'rgba(16,185,129,0.4)', lineStyle: 2, label: '10' },
      ];
    case 'CCI':
      return [
        { value: 100, color: 'rgba(239,68,68,0.4)', lineStyle: 2, label: '100' },
        { value: -100, color: 'rgba(16,185,129,0.4)', lineStyle: 2, label: '-100' },
        { value: 0, color: 'rgba(107,114,128,0.25)', lineStyle: 2, label: '0' },
      ];
    case 'ADX':
      return [
        { value: 25, color: 'rgba(251,191,36,0.4)', lineStyle: 2, label: '25' },
      ];
    case 'CHOP':
      return [
        { value: 61.8, color: 'rgba(239,68,68,0.3)', lineStyle: 2, label: '61.8' },
        { value: 38.2, color: 'rgba(16,185,129,0.3)', lineStyle: 2, label: '38.2' },
      ];
    case 'MACD': case 'PPO': case 'AO': case 'AC': case 'TRIX': case 'TSI':
    case 'DPO': case 'ROC': case 'MOM': case 'SQUEEZE': case 'QSTICK':
    case 'FORCE': case 'EOM': case 'CMF':
      return [
        { value: 0, color: 'rgba(107,114,128,0.3)', lineStyle: 2, label: '0' },
      ];
    default:
      return [];
  }
}

// ─── Sub-chart pane for separate-pane indicators ────────────

function SubPane({ instances, data }: { instances: { inst: IndicatorInstance; def: IndicatorDef }[]; data: OhlcvArrays }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRefs = useRef<(ISeriesApi<'Line'> | ISeriesApi<'Histogram'>)[]>([]);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      ...makeChartOpts(),
      rightPriceScale: { borderColor: '#1a1f2e', scaleMargins: { top: 0.1, bottom: 0.1 } },
    });
    chartRef.current = chart;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) chart.applyOptions({ width, height });
      }
    });
    observer.observe(containerRef.current);

    return () => { observer.disconnect(); chart.remove(); chartRef.current = null; };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || data.closes.length === 0) return;

    // Remove old series
    seriesRefs.current.forEach(s => {
      try { chart.removeSeries(s as any); } catch { /* ignore */ }
    });
    seriesRefs.current = [];

    for (const { inst, def } of instances) {
      try {
        const results = computeIndicator(def, inst.params, data);
        const colors = getColors(def);

        results.forEach((series, sIdx) => {
          const isHistogram = ((def.id === 'MACD' || def.id === 'PPO') && sIdx === 2)
            || def.id === 'SQUEEZE' || def.id === 'AO' || def.id === 'AC';
          if (isHistogram) {
            const histSeries = chart.addHistogramSeries({
              color: colors[sIdx] ?? def.color,
              priceLineVisible: false,
              lastValueVisible: false,
            });
            const histData = dedup(data.times.flatMap((time, i) =>
              series[i] == null ? [] : [{
                time,
                value: series[i] as number,
                color: (series[i] as number) >= 0 ? '#10b981' : '#ef4444',
              }]
            ));
            histSeries.setData(histData);
            seriesRefs.current.push(histSeries as any);
          } else {
            const lineSeries = chart.addLineSeries({
              color: colors[sIdx] ?? def.color,
              lineWidth: 1,
              priceLineVisible: false,
              lastValueVisible: sIdx === 0,
            });
            const lineData = dedup(data.times.flatMap((time, i) =>
              series[i] == null ? [] : [{ time, value: series[i] as number }]
            ));
            lineSeries.setData(lineData);
            seriesRefs.current.push(lineSeries);
          }
        });

        // Add reference level lines for oscillators
        const refLevels = getReferenceLevels(def.id);
        for (const level of refLevels) {
          const refSeries = chart.addLineSeries({
            color: level.color,
            lineWidth: 1,
            lineStyle: level.lineStyle as 0 | 1 | 2 | 3 | 4,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
          });
          // Create a flat line across the entire time range
          const refData = dedup([data.times[0], data.times[data.times.length - 1]]
            .filter(Boolean)
            .map(time => ({ time, value: level.value })));
          if (refData.length >= 2) {
            refSeries.setData(refData);
            seriesRefs.current.push(refSeries);
          }
        }
      } catch (e) {
        console.error(`Failed to compute ${def.id}:`, e);
      }
    }

    try { chart.timeScale().fitContent(); } catch { /* ignore */ }
  }, [instances, data]);

  const label = instances.map(({ inst, def }) => {
    const paramVals = def.params.map(p => inst.params[p.name] ?? p.default);
    return paramVals.length > 0 ? `${def.shortName}(${paramVals.join(',')})` : def.shortName;
  }).join(' / ');

  return (
    <div style={{ borderTop: '1px solid var(--border-primary)', position: 'relative', minHeight: 80 }}>
      <span style={{
        position: 'absolute', top: 2, left: 8, zIndex: 5,
        fontSize: 9, color: 'var(--text-dim)', background: 'rgba(10,14,23,0.85)',
        padding: '1px 4px', borderRadius: 2,
      }}>
        {label}
      </span>
      <div ref={containerRef} style={{ width: '100%', height: '100%', minHeight: 80 }} />
    </div>
  );
}

// ─── Main ChartPanel component ──────────────────────────────

export function ChartPanel() {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const mainSeriesRef = useRef<ISeriesApi<'Candlestick'> | ISeriesApi<'Line'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const indicatorSeriesRefs = useRef<ISeriesApi<'Line'>[]>([]);

  const { selectedProduct, selectedDay } = useDatasetStore();
  const { ohlcv, fills: backtestFills, setOhlcv } = useBacktestStore();
  const { isPlaying, currentTimestamp, replayFills } = useReplayStore();

  // Merge fills: during replay use replay fills, otherwise use backtest fills
  const fills = useMemo(() => {
    if (replayFills.length > 0) return replayFills;
    return backtestFills;
  }, [backtestFills, replayFills]);
  const { chartMode, setChartMode, selectedIndicators } = useUIStore();

  const [crosshairData, setCrosshairData] = React.useState('');

  // Compute the visible bars: during active replay, only show bars up to currentTimestamp
  const visibleBars = useMemo(() => {
    if (!ohlcv || ohlcv.length === 0) return [];
    if (isPlaying && currentTimestamp > 0) {
      return ohlcv.filter(bar => bar.timestamp <= currentTimestamp);
    }
    // When not playing but replay has advanced, still show progressive view
    if (currentTimestamp > 0) {
      return ohlcv.filter(bar => bar.timestamp <= currentTimestamp);
    }
    return ohlcv;
  }, [ohlcv, isPlaying, currentTimestamp]);

  const ohlcvData = useMemo(() => {
    if (visibleBars.length === 0) return null;
    return extractArrays(visibleBars);
  }, [visibleBars]);

  // Resolve selected indicators into instances with their definitions
  const resolvedOverlays = useMemo(() =>
    selectedIndicators
      .map(inst => ({ inst, def: getIndicatorById(inst.id) }))
      .filter((r): r is { inst: IndicatorInstance; def: IndicatorDef } => r.def != null && r.def.placement === 'overlay'),
    [selectedIndicators]);

  const resolvedPanes = useMemo(() =>
    selectedIndicators
      .map(inst => ({ inst, def: getIndicatorById(inst.id) }))
      .filter((r): r is { inst: IndicatorInstance; def: IndicatorDef } => r.def != null && r.def.placement === 'pane'),
    [selectedIndicators]);

  // Each pane indicator gets its own sub-chart
  const paneGroups = useMemo(() =>
    resolvedPanes.map(r => [r]),
    [resolvedPanes]);

  // Initialize chart
  useEffect(() => {
    if (!chartContainerRef.current) return;
    const chart = createChart(chartContainerRef.current, {
      ...makeChartOpts(),
      rightPriceScale: { borderColor: '#1a1f2e', scaleMargins: { top: 0.1, bottom: 0.25 } },
    });
    chartRef.current = chart;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) chart.applyOptions({ width, height });
      }
    });
    observer.observe(chartContainerRef.current);

    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.point) { setCrosshairData(''); return; }
      const prices: string[] = [];
      param.seriesData.forEach((data) => {
        const d = data as unknown as Record<string, unknown>;
        if ('close' in d) {
          prices.push(`O:${Number(d.open ?? 0).toFixed(1)} H:${Number(d.high ?? 0).toFixed(1)} L:${Number(d.low ?? 0).toFixed(1)} C:${Number(d.close ?? 0).toFixed(1)}`);
        } else if ('value' in d) {
          prices.push(`${Number(d.value ?? 0).toFixed(1)}`);
        }
      });
      setCrosshairData(prices.join(' | '));
    });

    return () => { observer.disconnect(); chart.remove(); chartRef.current = null; };
  }, []);

  // Load OHLCV data when product changes
  useEffect(() => {
    if (!selectedProduct) return;
    const interval = chartMode === 'line' || chartMode === 'step' ? 500 : 5000;
    api.fetchOHLCV(selectedProduct, interval)
      .then(setOhlcv)
      .catch(console.error);
  }, [selectedProduct, selectedDay, chartMode, setOhlcv]);

  // Update series when visible data or mode changes
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    // Remove old series
    if (mainSeriesRef.current) {
      try { chart.removeSeries(mainSeriesRef.current as any); } catch { /* */ }
      mainSeriesRef.current = null;
    }
    if (volumeSeriesRef.current) {
      try { chart.removeSeries(volumeSeriesRef.current as any); } catch { /* */ }
      volumeSeriesRef.current = null;
    }
    indicatorSeriesRefs.current.forEach(s => {
      try { chart.removeSeries(s as any); } catch { /* */ }
    });
    indicatorSeriesRefs.current = [];

    if (!ohlcvData || visibleBars.length === 0) return;

    const { times, opens, highs, lows, closes, volumes } = ohlcvData;

    // Main series
    if (chartMode === 'candlestick' || chartMode === 'ohlc') {
      const series = chart.addCandlestickSeries({
        upColor: '#10b981', downColor: '#ef4444',
        borderUpColor: '#10b981', borderDownColor: '#ef4444',
        wickUpColor: '#10b981', wickDownColor: '#ef4444',
      });
      const data = visibleBars.map(bar => ({
        time: toChartTime(bar.timestamp), open: bar.open, high: bar.high, low: bar.low, close: bar.close,
      }));
      try { series.setData(data); } catch (e) { console.error('Chart data error:', e); }
      mainSeriesRef.current = series as any;
    } else {
      const series = chart.addLineSeries({
        color: '#06b6d4', lineWidth: 1,
        lineType: chartMode === 'step' ? 1 : 0,
        crosshairMarkerRadius: 3,
        crosshairMarkerBorderColor: '#06b6d4',
        crosshairMarkerBackgroundColor: '#0a0e17',
      });
      const data = visibleBars.map(bar => ({
        time: toChartTime(bar.timestamp), value: bar.close,
      }));
      try { series.setData(data); } catch (e) { console.error('Chart data error:', e); }
      mainSeriesRef.current = series as any;
    }

    // Volume histogram
    try {
      const volSeries = chart.addHistogramSeries({
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
      });
      chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
      const volData = visibleBars.map(bar => ({
        time: toChartTime(bar.timestamp),
        value: bar.volume,
        color: bar.close >= bar.open ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)',
      }));
      volSeries.setData(volData);
      volumeSeriesRef.current = volSeries as any;
    } catch (e) { console.error('Volume error:', e); }

    // Overlay indicators (each instance with its own params)
    for (const { inst, def } of resolvedOverlays) {
      try {
        const results = computeIndicator(def, inst.params, ohlcvData);
        const colors = getColors(def);

        results.forEach((series, sIdx) => {
          const lineSeries = chart.addLineSeries({
            color: colors[sIdx] ?? def.color,
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: sIdx === 0,
            lineStyle: def.id === 'VWAP' ? 2 : 0,
          });
          const lineData = dedup(times.flatMap((time, i) =>
            series[i] == null ? [] : [{ time, value: series[i] as number }]
          ));
          lineSeries.setData(lineData);
          indicatorSeriesRefs.current.push(lineSeries);
        });
      } catch (e) {
        console.error(`Failed overlay ${def.id}:`, e);
      }
    }

    // Fill markers
    if (fills && fills.length > 0 && mainSeriesRef.current) {
      try {
        type MarkerAgg = { time: Time; side: 'BUY' | 'SELL'; count: number; totalQty: number; weightedPriceNumerator: number };
        const grouped = new Map<string, MarkerAgg>();
        const barTimes = visibleBars.map(bar => toChartTime(bar.timestamp));

        const snapToNearestBarTime = (rawTs: number): Time => {
          const target = toChartTime(rawTs) as number;
          if (barTimes.length === 0) return target as Time;
          let best = barTimes[0] as number;
          let bestDiff = Math.abs(best - target);
          for (let i = 1; i < barTimes.length; i++) {
            const candidate = barTimes[i] as number;
            const diff = Math.abs(candidate - target);
            if (diff < bestDiff) { best = candidate; bestDiff = diff; }
          }
          return best as Time;
        };

        // Only show fills within current visible range
        const maxTs = currentTimestamp > 0 ? currentTimestamp : Infinity;
        for (const f of fills) {
          if ((f.timestamp ?? 0) > maxTs) continue;
          const side = f.side === 'SELL' ? 'SELL' : 'BUY';
          const time = snapToNearestBarTime(f.timestamp ?? 0);
          const qty = Math.max(0, Number(f.quantity ?? 0));
          const price = Number(f.price ?? 0);
          const key = `${String(time)}_${side}`;
          const existing = grouped.get(key);
          if (existing) {
            existing.count += 1; existing.totalQty += qty; existing.weightedPriceNumerator += price * qty;
          } else {
            grouped.set(key, { time, side, count: 1, totalQty: qty, weightedPriceNumerator: price * qty });
          }
        }

        const markers = Array.from(grouped.values()).map(m => ({
          time: m.time,
          position: (m.side === 'BUY' ? 'belowBar' : 'aboveBar') as 'belowBar' | 'aboveBar',
          color: m.side === 'BUY' ? '#10b981' : '#ef4444',
          shape: (m.side === 'BUY' ? 'arrowUp' : 'arrowDown') as 'arrowUp' | 'arrowDown',
          size: 1,
          text: m.totalQty > 1 ? `${m.totalQty}` : '',
        }));
        (mainSeriesRef.current as any).setMarkers(markers.sort((a: any, b: any) => (a.time as number) - (b.time as number)));
      } catch (e) { console.error('Markers error:', e); }
    }

    // During progressive rendering, scroll to show latest bar
    if (currentTimestamp > 0 && visibleBars.length > 0) {
      try { chart.timeScale().scrollToPosition(2, false); } catch { /* */ }
    } else {
      try { chart.timeScale().fitContent(); } catch { /* */ }
    }
  }, [visibleBars, chartMode, fills, resolvedOverlays, ohlcvData, currentTimestamp]);

  // Determine layout: main chart height vs sub-pane height
  const hasPanes = paneGroups.length > 0;
  const mainFlex = hasPanes ? 3 : 1;
  const paneFlex = 1;

  return (
    <div className="panel" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Toolbar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 4, padding: '4px 8px',
        borderBottom: '1px solid var(--border-primary)', background: 'var(--bg-panel-alt)', flexShrink: 0,
      }}>
        <span className="panel-title" style={{ marginRight: 8 }}>Chart</span>
        {CHART_MODES.map(m => (
          <button key={m.key} className={`btn btn-sm ${chartMode === m.key ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setChartMode(m.key)}>
            {m.label}
          </button>
        ))}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          {fills && fills.length > 0 && (
            <span style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 'var(--font-size-xs)', marginRight: 4 }}>
              <span style={{ color: '#10b981' }}>▲ Buy</span>
              <span style={{ color: '#ef4444' }}>▼ Sell</span>
              <span style={{ color: 'var(--text-dim)' }}>({fills.length} fills)</span>
            </span>
          )}
          {isPlaying && currentTimestamp > 0 && (
            <span style={{ fontSize: 9, color: 'var(--cyan)', fontWeight: 600 }}>
              LIVE
            </span>
          )}
          <IndicatorSelector />
        </div>
      </div>

      {/* Main chart area */}
      <div style={{ flex: mainFlex, position: 'relative', minHeight: 100 }}>
        <div ref={chartContainerRef} style={{ width: '100%', height: '100%' }} />
        {crosshairData && (
          <div style={{
            position: 'absolute', top: 4, right: 8,
            fontSize: 'var(--font-size-xs)', color: 'var(--text-secondary)',
            fontVariantNumeric: 'tabular-nums', zIndex: 5, pointerEvents: 'none',
            background: 'rgba(10,14,23,0.85)', padding: '2px 6px', borderRadius: 2,
          }}>
            {crosshairData}
          </div>
        )}
        {/* Active overlay indicator labels with params */}
        {resolvedOverlays.length > 0 && (
          <div style={{
            position: 'absolute', top: 4, left: 8, zIndex: 5, pointerEvents: 'none',
            display: 'flex', gap: 8, flexWrap: 'wrap',
          }}>
            {resolvedOverlays.map(({ inst, def }) => {
              const paramVals = def.params.map(p => inst.params[p.name] ?? p.default);
              const label = paramVals.length > 0 ? `${def.shortName}(${paramVals.join(',')})` : def.shortName;
              return (
                <span key={inst.key} style={{
                  fontSize: 9, padding: '1px 4px', borderRadius: 2,
                  background: 'rgba(10,14,23,0.85)', color: def.color,
                }}>
                  {label}
                </span>
              );
            })}
          </div>
        )}
        {(!ohlcv || ohlcv.length === 0) && (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            position: 'absolute', inset: 0, color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)',
          }}>
            Load dataset and select product to view chart
          </div>
        )}
      </div>

      {/* Sub-pane indicators */}
      {ohlcvData && paneGroups.map((group) => (
        <div key={group.map(g => g.inst.key).join('_')} style={{ flex: paneFlex, minHeight: 60 }}>
          <SubPane instances={group} data={ohlcvData} />
        </div>
      ))}
    </div>
  );
}
