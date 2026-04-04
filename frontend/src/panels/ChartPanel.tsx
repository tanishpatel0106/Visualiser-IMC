import React, { useEffect, useRef } from 'react';
import { createChart } from 'lightweight-charts';
import type { IChartApi, ISeriesApi, Time } from 'lightweight-charts';
import { useDatasetStore, useBacktestStore, useReplayStore, useUIStore } from '@/store';
import * as api from '@/services/api';
import type { ChartMode } from '@/types';

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
  },
  toolbar: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    padding: '4px 8px',
    borderBottom: '1px solid var(--border-primary)',
    background: 'var(--bg-panel-alt)',
    flexShrink: 0,
  },
  chartWrapper: {
    flex: 1,
    position: 'relative',
  },
  crosshairInfo: {
    position: 'absolute',
    top: 4,
    right: 8,
    fontSize: 'var(--font-size-xs)',
    color: 'var(--text-secondary)',
    fontVariantNumeric: 'tabular-nums',
    zIndex: 5,
    pointerEvents: 'none',
    background: 'rgba(10,14,23,0.85)',
    padding: '2px 6px',
    borderRadius: 2,
  },
  empty: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flex: 1,
    color: 'var(--text-dim)',
    fontSize: 'var(--font-size-sm)',
  },
};

const CHART_MODES: { key: ChartMode; label: string }[] = [
  { key: 'candlestick', label: 'Candle' },
  { key: 'line', label: 'Line' },
  { key: 'step', label: 'Step' },
  { key: 'ohlc', label: 'OHLC' },
];

/**
 * Convert a relative IMC Prosperity timestamp (0–999900) into a
 * UTC seconds value that lightweight-charts can display properly.
 * We anchor to a fake base date so the time axis shows readable
 * "HH:MM" labels rather than 1970 epoch garbage.
 */
const BASE_UTC = Date.UTC(2025, 0, 1, 9, 0, 0) / 1000; // 2025-01-01 09:00 UTC in seconds
function toChartTime(ts: number): Time {
  // Prosperity timestamps are ~milliseconds within a trading day (0–1,000,000).
  // Map them into a 6-hour trading window so the chart shows 09:00 → 15:00.
  // 1,000,000 ticks → 21,600 seconds (6 hours)
  return (BASE_UTC + Math.round(ts * 21.6 / 1000)) as Time;
}

export function ChartPanel() {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const mainSeriesRef = useRef<ISeriesApi<'Candlestick'> | ISeriesApi<'Line'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const indicatorSeriesRefs = useRef<ISeriesApi<'Line'>[]>([]);

  const { selectedProduct, selectedDay } = useDatasetStore();
  const { ohlcv, fills, setOhlcv } = useBacktestStore();
  const { chartMode, setChartMode, selectedIndicators } = useUIStore();

  const [crosshairData, setCrosshairData] = React.useState<string>('');

  // Initialize chart
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { color: '#0a0e17' },
        textColor: '#6b7280',
        fontSize: 10,
        fontFamily: "'JetBrains Mono', monospace",
      },
      grid: {
        vertLines: { color: 'rgba(42, 48, 64, 0.3)' },
        horzLines: { color: 'rgba(42, 48, 64, 0.3)' },
      },
      crosshair: {
        mode: 0,
        vertLine: {
          color: 'rgba(6, 182, 212, 0.4)',
          width: 1,
          style: 2,
          labelBackgroundColor: '#164e63',
        },
        horzLine: {
          color: 'rgba(6, 182, 212, 0.4)',
          width: 1,
          style: 2,
          labelBackgroundColor: '#164e63',
        },
      },
      rightPriceScale: {
        borderColor: '#1a1f2e',
        scaleMargins: { top: 0.1, bottom: 0.25 },
      },
      timeScale: {
        borderColor: '#1a1f2e',
        timeVisible: true,
        secondsVisible: false,
      },
      handleScale: { axisPressedMouseMove: true },
      handleScroll: { vertTouchDrag: false },
    });

    chartRef.current = chart;

    // Resize observer
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          chart.applyOptions({ width, height });
        }
      }
    });
    observer.observe(chartContainerRef.current);

    // Crosshair move handler
    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.point) {
        setCrosshairData('');
        return;
      }
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

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  // Load OHLCV data when product changes
  useEffect(() => {
    if (!selectedProduct) return;
    const interval = chartMode === 'line' || chartMode === 'step' ? 500 : 5000;
    api.fetchOHLCV(selectedProduct, interval)
      .then(setOhlcv)
      .catch(console.error);
  }, [selectedProduct, selectedDay, chartMode, setOhlcv]);

  // Update series when data or mode changes
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    // Remove old series
    if (mainSeriesRef.current) {
      try { chart.removeSeries(mainSeriesRef.current as any); } catch { /* ignore */ }
      mainSeriesRef.current = null;
    }
    if (volumeSeriesRef.current) {
      try { chart.removeSeries(volumeSeriesRef.current as any); } catch { /* ignore */ }
      volumeSeriesRef.current = null;
    }
    indicatorSeriesRefs.current.forEach((s) => {
      try { chart.removeSeries(s as any); } catch { /* ignore */ }
    });
    indicatorSeriesRefs.current = [];

    if (!ohlcv || ohlcv.length === 0) return;

    // Create main series based on mode
    if (chartMode === 'candlestick' || chartMode === 'ohlc') {
      const series = chart.addCandlestickSeries({
        upColor: '#10b981',
        downColor: '#ef4444',
        borderUpColor: '#10b981',
        borderDownColor: '#ef4444',
        wickUpColor: '#10b981',
        wickDownColor: '#ef4444',
      });
      const data = ohlcv.map((bar) => ({
        time: toChartTime(bar.timestamp),
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      }));
      try { series.setData(data); } catch (e) { console.error('Failed to set candlestick data:', e); }
      mainSeriesRef.current = series as any;
    } else {
      const series = chart.addLineSeries({
        color: '#06b6d4',
        lineWidth: 1,
        lineType: chartMode === 'step' ? 1 : 0,
        crosshairMarkerRadius: 3,
        crosshairMarkerBorderColor: '#06b6d4',
        crosshairMarkerBackgroundColor: '#0a0e17',
      });
      const data = ohlcv.map((bar) => ({
        time: toChartTime(bar.timestamp),
        value: bar.close,
      }));
      try { series.setData(data); } catch (e) { console.error('Failed to set line data:', e); }
      mainSeriesRef.current = series as any;
    }

    // Volume histogram
    try {
      const volSeries = chart.addHistogramSeries({
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
      });
      chart.priceScale('volume').applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });
      const volData = ohlcv.map((bar) => ({
        time: toChartTime(bar.timestamp),
        value: bar.volume,
        color: bar.close >= bar.open ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)',
      }));
      volSeries.setData(volData);
      volumeSeriesRef.current = volSeries as any;
    } catch (e) {
      console.error('Failed to add volume series:', e);
    }

    // Indicator overlays
    const times = ohlcv.map((bar) => toChartTime(bar.timestamp));
    const closes = ohlcv.map((bar) => bar.close);
    const volumes = ohlcv.map((bar) => bar.volume);

    if (selectedIndicators.includes('SMA20')) {
      const sma20 = rollingSma(closes, 20);
      const series = chart.addLineSeries({ color: '#f59e0b', lineWidth: 1, priceLineVisible: false });
      series.setData(times.flatMap((time, i) => (sma20[i] == null ? [] : [{ time, value: sma20[i] as number }])));
      indicatorSeriesRefs.current.push(series);
    }

    if (selectedIndicators.includes('SMA50')) {
      const sma50 = rollingSma(closes, 50);
      const series = chart.addLineSeries({ color: '#8b5cf6', lineWidth: 1, priceLineVisible: false });
      series.setData(times.flatMap((time, i) => (sma50[i] == null ? [] : [{ time, value: sma50[i] as number }])));
      indicatorSeriesRefs.current.push(series);
    }

    if (selectedIndicators.includes('VWAP')) {
      const vwap = cumulativeVwap(closes, volumes);
      const series = chart.addLineSeries({ color: '#22d3ee', lineWidth: 1, lineStyle: 2, priceLineVisible: false });
      series.setData(times.map((time, i) => ({ time, value: vwap[i] })));
      indicatorSeriesRefs.current.push(series);
    }

    if (selectedIndicators.includes('BB')) {
      const { mid, upper, lower } = bollingerBands(closes, 20, 2);
      const midSeries = chart.addLineSeries({ color: '#a3a3a3', lineWidth: 1, priceLineVisible: false });
      midSeries.setData(times.flatMap((time, i) => (mid[i] == null ? [] : [{ time, value: mid[i] as number }])));
      const upperSeries = chart.addLineSeries({ color: '#f97316', lineWidth: 1, priceLineVisible: false });
      upperSeries.setData(times.flatMap((time, i) => (upper[i] == null ? [] : [{ time, value: upper[i] as number }])));
      const lowerSeries = chart.addLineSeries({ color: '#f97316', lineWidth: 1, priceLineVisible: false });
      lowerSeries.setData(times.flatMap((time, i) => (lower[i] == null ? [] : [{ time, value: lower[i] as number }])));
      indicatorSeriesRefs.current.push(midSeries, upperSeries, lowerSeries);
    }

    // Add fill markers if available
    if (fills && fills.length > 0 && mainSeriesRef.current) {
      try {
        type MarkerAgg = {
          time: Time;
          side: 'BUY' | 'SELL';
          count: number;
          totalQty: number;
          weightedPriceNumerator: number;
        };

        const grouped = new Map<string, MarkerAgg>();

        const barTimes = ohlcv.map((bar) => toChartTime(bar.timestamp));

        const snapToNearestBarTime = (rawTs: number): Time => {
          const target = toChartTime(rawTs) as number;
          if (barTimes.length === 0) return target as Time;
          let best = barTimes[0] as number;
          let bestDiff = Math.abs(best - target);
          for (let i = 1; i < barTimes.length; i += 1) {
            const candidate = barTimes[i] as number;
            const diff = Math.abs(candidate - target);
            if (diff < bestDiff) {
              best = candidate;
              bestDiff = diff;
            }
          }
          return best as Time;
        };

        for (const f of fills) {
          const side = f.side === 'SELL' ? 'SELL' : 'BUY';
          const time = snapToNearestBarTime(f.timestamp ?? 0);
          const qty = Math.max(0, Number(f.quantity ?? 0));
          const price = Number(f.price ?? 0);
          const key = `${String(time)}_${side}`;
          const existing = grouped.get(key);

          if (existing) {
            existing.count += 1;
            existing.totalQty += qty;
            existing.weightedPriceNumerator += price * qty;
          } else {
            grouped.set(key, {
              time,
              side,
              count: 1,
              totalQty: qty,
              weightedPriceNumerator: price * qty,
            });
          }
        }

        const markers = Array.from(grouped.values()).map((m) => {
          return {
            time: m.time,
            position: (m.side === 'BUY' ? 'belowBar' : 'aboveBar') as 'belowBar' | 'aboveBar',
            color: m.side === 'BUY' ? '#10b981' : '#ef4444',
            shape: (m.side === 'BUY' ? 'arrowUp' : 'arrowDown') as 'arrowUp' | 'arrowDown',
            size: 1,
            text: m.totalQty > 1 ? `${m.totalQty}` : '',
          };
        });
        (mainSeriesRef.current as any).setMarkers(markers.sort((a: any, b: any) => (a.time as number) - (b.time as number)));
      } catch (e) {
        console.error('Failed to set markers:', e);
      }
    }

    try { chart.timeScale().fitContent(); } catch { /* ignore */ }
  }, [ohlcv, chartMode, fills, selectedIndicators]);

  return (
    <div className="panel" style={{ height: '100%' }}>
      <div style={styles.toolbar}>
        <span className="panel-title" style={{ marginRight: 8 }}>Chart</span>
        {CHART_MODES.map((m) => (
          <button
            key={m.key}
            className={`btn btn-sm ${chartMode === m.key ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setChartMode(m.key)}
          >
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
          <span style={{ fontSize: 9, color: 'var(--text-dim)' }}>INDICATORS:</span>
          {['SMA20', 'SMA50', 'VWAP', 'BB'].map((ind) => (
            <label key={ind} style={{ display: 'flex', alignItems: 'center', gap: 2, fontSize: 'var(--font-size-xs)', color: 'var(--text-secondary)', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={selectedIndicators.includes(ind)}
                onChange={() => useUIStore.getState().toggleIndicator(ind)}
                style={{ accentColor: 'var(--cyan)', width: 10, height: 10 }}
              />
              {ind}
            </label>
          ))}
        </div>
      </div>
      <div style={styles.chartWrapper}>
        <div ref={chartContainerRef} style={{ width: '100%', height: '100%' }} />
        {crosshairData && <div style={styles.crosshairInfo}>{crosshairData}</div>}
        {(!ohlcv || ohlcv.length === 0) && (
          <div style={{ ...styles.empty, position: 'absolute', inset: 0 }}>
            Load dataset and select product to view chart
          </div>
        )}
      </div>
    </div>
  );
}

function rollingSma(values: number[], period: number): Array<number | null> {
  const out: Array<number | null> = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i += 1) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

function cumulativeVwap(prices: number[], volumes: number[]): number[] {
  const out: number[] = [];
  let pv = 0;
  let vol = 0;
  for (let i = 0; i < prices.length; i += 1) {
    pv += prices[i] * (volumes[i] || 0);
    vol += volumes[i] || 0;
    out.push(vol > 0 ? pv / vol : prices[i]);
  }
  return out;
}

function bollingerBands(values: number[], period: number, k: number): {
  mid: Array<number | null>;
  upper: Array<number | null>;
  lower: Array<number | null>;
} {
  const mid = rollingSma(values, period);
  const upper: Array<number | null> = new Array(values.length).fill(null);
  const lower: Array<number | null> = new Array(values.length).fill(null);

  for (let i = period - 1; i < values.length; i += 1) {
    const m = mid[i];
    if (m == null) continue;
    let variance = 0;
    for (let j = i - period + 1; j <= i; j += 1) {
      const d = values[j] - m;
      variance += d * d;
    }
    const std = Math.sqrt(variance / period);
    upper[i] = m + k * std;
    lower[i] = m - k * std;
  }

  return { mid, upper, lower };
}
