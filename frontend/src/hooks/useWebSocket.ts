import { useEffect, useRef, useCallback } from 'react';
import { useReplayStore } from '@/store';
import { createReplayWebSocket } from '@/services/api';

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();
  const updateReplayState = useReplayStore((s) => s.updateReplayState);
  const updateFromStepResponse = useReplayStore((s) => s.updateFromStepResponse);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const ws = createReplayWebSocket();
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('[WS] Connected to replay stream');
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          // Handle different message types from backend
          if (data.event && data.state) {
            // This is a step response shape {event, state}
            updateFromStepResponse(data.state);
          } else if (data.books || data.trades || data.pnl) {
            // This is a partial state update
            updateFromStepResponse(data);
          } else if (data.is_playing !== undefined || data.current_timestamp !== undefined) {
            // This is a full replay state
            updateReplayState(data);
          }
        } catch (err) {
          console.error('[WS] Failed to parse message:', err);
        }
      };

      ws.onclose = (event) => {
        console.log('[WS] Disconnected:', event.code, event.reason);
        wsRef.current = null;
        // Reconnect after delay
        reconnectTimer.current = setTimeout(connect, 3000);
      };

      ws.onerror = (err) => {
        console.error('[WS] Error:', err);
        ws.close();
      };
    } catch (err) {
      console.error('[WS] Failed to connect:', err);
      reconnectTimer.current = setTimeout(connect, 3000);
    }
  }, [updateReplayState, updateFromStepResponse]);

  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  return wsRef;
}
