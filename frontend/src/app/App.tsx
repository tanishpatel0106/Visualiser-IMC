import { useEffect } from 'react';
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

  useEffect(() => {
    // Load dataset info on mount - returns a single DatasetInfo object
    api.fetchDatasets().then((info) => {
      if (info) {
        setDatasetInfo(info);
      }
    }).catch(console.error);

    // Load strategies - returns StrategyDefinition[]
    api.fetchStrategies().then(setStrategies).catch(console.error);
  }, [setDatasetInfo, setStrategies]);

  return <TerminalLayout />;
}
