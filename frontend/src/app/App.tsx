import { useEffect, useState } from 'react';
import { TerminalLayout } from '@/layouts/TerminalLayout';
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useDatasetStore, useStrategyStore } from '@/store';
import * as api from '@/services/api';

export function App() {
  useKeyboardShortcuts();
  useWebSocket();

  const setDatasetInfo = useDatasetStore((s) => s.setDatasetInfo);
  const setStrategies = useStrategyStore((s) => s.setStrategies);
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
