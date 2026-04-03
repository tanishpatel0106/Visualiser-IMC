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

export function ChartPanel() {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const mainSeriesRef = useRef<ISeriesApi<'Candlestick'> | ISeriesApi<'Line'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);

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
    api.fetchOHLCV(selectedProduct, 500)
      .then(setOhlcv)
      .catch(console.error);
  }, [selectedProduct, selectedDay, setOhlcv]);

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
        time: (bar.timestamp / 1000) as Time,
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
        time: (bar.timestamp / 1000) as Time,
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
        time: (bar.timestamp / 1000) as Time,
        value: bar.volume,
        color: bar.close >= bar.open ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)',
      }));
      volSeries.setData(volData);
      volumeSeriesRef.current = volSeries as any;
    } catch (e) {
      console.error('Failed to add volume series:', e);
    }

    // Add fill markers if available
    if (fills && fills.length > 0 && mainSeriesRef.current) {
      try {
        const markers = fills.map((f) => ({
          time: ((f.timestamp ?? 0) / 1000) as Time,
          position: (f.side === 'BUY' ? 'belowBar' : 'aboveBar') as 'belowBar' | 'aboveBar',
          color: f.side === 'BUY' ? '#10b981' : '#ef4444',
          shape: (f.side === 'BUY' ? 'arrowUp' : 'arrowDown') as 'arrowUp' | 'arrowDown',
          text: `${f.side ?? '?'} ${f.quantity}@${(f.price ?? 0).toFixed(1)}`,
        }));
        (mainSeriesRef.current as any).setMarkers(markers.sort((a: any, b: any) => (a.time as number) - (b.time as number)));
      } catch (e) {
        console.error('Failed to set markers:', e);
      }
    }

    try { chart.timeScale().fitContent(); } catch { /* ignore */ }
  }, [ohlcv, chartMode, fills]);

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
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 4, alignItems: 'center' }}>
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
