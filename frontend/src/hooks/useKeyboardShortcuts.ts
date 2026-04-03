import { useEffect } from 'react';
import { useReplayStore, useDatasetStore, useUIStore } from '@/store';
import * as api from '@/services/api';

export function useKeyboardShortcuts() {
  const { isPlaying, setPlaying } = useReplayStore();
  const { setActiveWorkspace } = useUIStore();

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Ignore if typing in an input/textarea/select
      const tag = (e.target as HTMLElement).tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      switch (e.key) {
        case ' ':
          e.preventDefault();
          if (isPlaying) {
            api.pauseReplay().catch(console.error);
            setPlaying(false);
          } else {
            // Start replay with current product/day selections
            const { selectedProduct, selectedDay } = useDatasetStore.getState();
            if (selectedProduct && selectedDay !== null) {
              api.startReplay(
                [selectedProduct],
                selectedDay !== null ? [selectedDay] : []
              ).then((session) => {
                useReplayStore.getState().setSessionId(session.session_id);
                if (session.total_events) {
                  useReplayStore.setState({ totalEvents: session.total_events });
                }
                setPlaying(true);
              }).catch(console.error);
            }
          }
          break;

        case 'ArrowRight':
          e.preventDefault();
          if (e.shiftKey) {
            // Seek forward - use a future timestamp
            const ts = useReplayStore.getState().currentTimestamp;
            api.seekReplay(ts + 1000).catch(console.error);
          } else {
            api.stepReplay().then((resp) => {
              if (resp?.state) {
                useReplayStore.getState().updateFromStepResponse(resp.state);
              }
            }).catch(console.error);
          }
          break;

        case 'ArrowLeft':
          e.preventDefault();
          if (e.shiftKey) {
            const ts = useReplayStore.getState().currentTimestamp;
            api.seekReplay(Math.max(0, ts - 1000)).catch(console.error);
          } else {
            api.stepBackReplay().then((resp) => {
              if (resp?.state) {
                useReplayStore.getState().updateFromStepResponse(resp.state);
              }
            }).catch(console.error);
          }
          break;

        case 'r':
          if (!e.ctrlKey && !e.metaKey) {
            e.preventDefault();
            api.resetReplay().catch(console.error);
            useReplayStore.getState().resetReplay();
          }
          break;

        case '1':
          e.preventDefault();
          setActiveWorkspace('trading');
          break;

        case '2':
          e.preventDefault();
          setActiveWorkspace('analysis');
          break;

        case '3':
          e.preventDefault();
          setActiveWorkspace('strategy');
          break;

        case '4':
          e.preventDefault();
          setActiveWorkspace('debug');
          break;
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isPlaying, setPlaying, setActiveWorkspace]);
}
