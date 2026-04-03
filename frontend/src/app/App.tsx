import { useEffect, useState } from 'react';
import { TerminalLayout } from '@/layouts/TerminalLayout';
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useDatasetStore, useReplayStore, useStrategyStore } from '@/store';
import * as api from '@/services/api';
import type { PnLState, PositionState, TradePrint, VisibleOrderBook } from '@/types';

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

    const tick = async () => {
      if (cancelled) return;
      try {
        const resp = await api.stepReplay();
        if (cancelled) return;

        const payload = resp as unknown as Record<string, unknown>;
        const state = (payload.state ?? {}) as Record<string, unknown>;
        updateReplayState({
          books: (state.books ?? {}) as Record<string, VisibleOrderBook>,
          trades: (state.trades ?? []) as TradePrint[],
          positions: (state.positions ?? {}) as Record<string, PositionState>,
          pnl: (state.pnl ?? undefined) as PnLState | undefined,
          current_timestamp: (payload.current_timestamp as number) ?? 0,
          current_index: (payload.current_index as number) ?? 0,
          total_events: (payload.total_events as number) ?? 0,
          is_playing: (payload.is_playing as boolean) ?? true,
        });

        if (payload.done) {
          setPlaying(false);
          return;
        }

        const delayMs = Math.max(20, Math.round(120 / Math.max(speed, 0.1)));
        timer = setTimeout(tick, delayMs);
      } catch (err) {
        console.error('Replay step failed:', err);
        setPlaying(false);
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
