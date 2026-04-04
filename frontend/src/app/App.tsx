import { useEffect, useState } from 'react';
import { TerminalLayout } from '@/layouts/TerminalLayout';
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useDatasetStore, useReplayStore, useStrategyStore } from '@/store';
import * as api from '@/services/api';
import type { DebugFrame, FillEvent, PnLState, PositionState, TradePrint, VisibleOrderBook } from '@/types';

export function App() {
  useKeyboardShortcuts();
  useWebSocket();

  const setDatasetInfo = useDatasetStore((s) => s.setDatasetInfo);
  const setStrategies = useStrategyStore((s) => s.setStrategies);
  const isPlaying = useReplayStore((s) => s.isPlaying);
  const speed = useReplayStore((s) => s.speed);
  const updateReplayState = useReplayStore((s) => s.updateReplayState);
  const setPlaying = useReplayStore((s) => s.setPlaying);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    const boot = async () => {
      try {
        await api.healthCheck();
        const [info, strategies] = await Promise.all([
          api.fetchDatasets(),
          api.fetchStrategies(),
        ]);
        if (!mounted) return;
        if (info) setDatasetInfo(info);
        setStrategies(strategies);
        setLoadError(null);
      } catch (err) {
        if (!mounted) return;
        const message = err instanceof Error ? err.message : String(err);
        setLoadError(`Backend connection failed: ${message}`);
      }
    };

    boot();
    const timer = setInterval(boot, 5000);

    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, [setDatasetInfo, setStrategies]);

  useEffect(() => {
    if (!isPlaying) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let consecutiveErrors = 0;

    const tick = async () => {
      if (cancelled) return;
      try {
        const resp = await api.stepReplay();
        if (cancelled) return;

        const payload = resp as unknown as Record<string, unknown>;
        const state = (payload.state ?? {}) as Record<string, unknown>;
        const strategyState = (payload.strategy_state ?? {}) as Record<string, unknown>;
        // Extract strategy fills to show on chart and fills panel
        const stratFills = (strategyState.fills ?? []) as FillEvent[];
        // Backend returns trade_tape (not trades) in state snapshot
        const tradeTape = (state.trade_tape ?? state.trades) as TradePrint[] | undefined;

        // Build debug frame from strategy state for live debugging
        let debugFrame: DebugFrame | undefined;
        if (strategyState && Object.keys(strategyState).length > 0) {
          const rawOrders = (strategyState.orders_submitted ?? []) as Record<string, unknown>[];
          const positions = (strategyState.positions ?? {}) as Record<string, number>;
          const pnlSnap = (strategyState.pnl ?? state.pnl) as Record<string, unknown> | undefined;
          const ts = (payload.current_timestamp as number) ?? 0;
          const hasActivity = rawOrders.length > 0 || stratFills.length > 0;
          if (hasActivity || (pnlSnap && (pnlSnap.total_pnl as number) !== 0)) {
            debugFrame = {
              timestamp: ts,
              event_type: stratFills.length > 0 ? 'FILL' : rawOrders.length > 0 ? 'ORDER' : 'PNL',
              orders: rawOrders.map(o => ({
                timestamp: ts,
                product: (o.product as string) ?? '',
                side: ((o.side as string) === 'SELL' ? 'SELL' : 'BUY') as 'BUY' | 'SELL',
                price: (o.price as number) ?? 0,
                quantity: (o.quantity as number) ?? 0,
              })),
              fills: stratFills.map(f => ({
                timestamp: f.timestamp ?? ts,
                product: f.product ?? '',
                side: f.side,
                price: f.price ?? 0,
                quantity: f.quantity ?? 0,
              })),
              position: positions,
              pnl: pnlSnap ? {
                timestamp: ts,
                realized_pnl: (pnlSnap.realized_pnl as number) ?? 0,
                unrealized_pnl: (pnlSnap.unrealized_pnl as number) ?? 0,
                total_pnl: (pnlSnap.total_pnl as number) ?? 0,
                inventory: {},
                cash: (pnlSnap.cash as number) ?? 0,
              } : undefined,
              notes: strategyState.error
                ? `Error: ${strategyState.error}`
                : stratFills.length > 0
                ? `${stratFills.length} fill(s) executed`
                : rawOrders.length > 0
                ? `${rawOrders.length} order(s) submitted`
                : '',
            };
          }
        }

        updateReplayState({
          books: (state.books ?? {}) as Record<string, VisibleOrderBook>,
          trades: tradeTape,
          positions: (state.positions ?? {}) as Record<string, PositionState>,
          pnl: (state.pnl ?? undefined) as PnLState | undefined,
          current_timestamp: (payload.current_timestamp as number) ?? 0,
          current_index: (payload.current_index as number) ?? 0,
          total_events: (payload.total_events as number) ?? 0,
          strategy_fills: stratFills.length > 0 ? stratFills : undefined,
          debug_frame: debugFrame,
        });
        consecutiveErrors = 0;

        if (payload.done) {
          setPlaying(false);
          return;
        }

        const delayMs = Math.max(20, Math.round(120 / Math.max(speed, 0.1)));
        timer = setTimeout(tick, delayMs);
      } catch (err) {
        console.error('Replay step failed:', err);
        consecutiveErrors += 1;
        if (consecutiveErrors >= 5) {
          setPlaying(false);
          return;
        }
        timer = setTimeout(tick, 300);
      }
    };

    tick();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [isPlaying, speed, setPlaying, updateReplayState]);

  return (
    <>
      {loadError && (
        <div style={{
          background: 'rgba(127,29,29,0.9)',
          color: '#fecaca',
          fontSize: 12,
          padding: '6px 10px',
          borderBottom: '1px solid #7f1d1d',
          fontFamily: "'JetBrains Mono', monospace",
        }}>
          {loadError}
        </div>
      )}
      <TerminalLayout />
    </>
  );
}
