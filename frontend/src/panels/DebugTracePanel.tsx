import React, { useState, useMemo, useEffect, useRef } from 'react';
import { useBacktestStore, useReplayStore } from '@/store';
import * as api from '@/services/api';
import type { DebugFrame, EventType } from '@/types';

const styles: Record<string, React.CSSProperties> = {
  toolbar: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    padding: '4px 8px',
    borderBottom: '1px solid var(--border-primary)',
    background: 'var(--bg-panel-alt)',
    flexShrink: 0,
  },
  container: {
    flex: 1,
    overflow: 'auto',
    fontFamily: 'var(--font-mono)',
    fontSize: 'var(--font-size-sm)',
  },
  row: {
    display: 'grid',
    gridTemplateColumns: '90px 70px minmax(80px, 1fr) minmax(80px, 1fr) 60px 80px 1fr',
    gap: 4,
    padding: '2px 8px',
    borderBottom: '1px solid var(--border-primary)',
    alignItems: 'center',
    cursor: 'pointer',
    lineHeight: '20px',
  },
  expandedRow: {
    padding: '4px 8px 8px 100px',
    background: 'var(--bg-base)',
    borderBottom: '1px solid var(--border-primary)',
    fontSize: 'var(--font-size-xs)',
    whiteSpace: 'pre-wrap',
    color: 'var(--text-muted)',
    maxHeight: 200,
    overflow: 'auto',
    wordBreak: 'break-all' as const,
  },
  headerRow: {
    display: 'grid',
    gridTemplateColumns: '90px 70px minmax(80px, 1fr) minmax(80px, 1fr) 60px 80px 1fr',
    gap: 4,
    padding: '3px 8px',
    fontSize: 9,
    color: 'var(--text-dim)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px',
    borderBottom: '1px solid var(--border-primary)',
    background: 'var(--bg-panel-alt)',
    position: 'sticky' as const,
    top: 0,
    zIndex: 1,
  },
  empty: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    color: 'var(--text-dim)',
    fontSize: 'var(--font-size-sm)',
  },
};

const EVENT_COLORS: Record<string, string> = {
  SNAPSHOT: 'var(--text-muted)',
  TRADE: 'var(--cyan)',
  ORDER: 'var(--blue)',
  FILL: 'var(--green)',
  POSITION: 'var(--amber)',
  PNL: 'var(--purple)',
  SIGNAL: 'var(--cyan)',
  LOG: 'var(--text-secondary)',
  ERROR: 'var(--red)',
};

const EVENT_TYPES: EventType[] = ['SNAPSHOT', 'TRADE', 'ORDER', 'FILL', 'POSITION', 'PNL', 'SIGNAL', 'LOG', 'ERROR'];

function formatTime(ts: number): string {
  if (!ts) return '--:--:--.---';
  const totalMs = ts % 86400000;
  const h = Math.floor(totalMs / 3600000);
  const m = Math.floor((totalMs % 3600000) / 60000);
  const s = Math.floor((totalMs % 60000) / 1000);
  const ms = totalMs % 1000;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
}

export function DebugTracePanel() {
  const { currentRun, trace, setTrace } = useBacktestStore();
  const { replayTrace, isPlaying } = useReplayStore();
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const [filterType, setFilterType] = useState<EventType | 'ALL'>('ALL');
  const [search, setSearch] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!currentRun || currentRun.status !== 'completed') return;
    const runId = currentRun.run_id;
    if (!runId) return;
    api.getBacktestTrace(runId).then((res) => {
      setTrace(res?.trace ?? []);
    }).catch(console.error);
  }, [currentRun, setTrace]);

  // Merge backtest trace and replay trace — replay takes priority during active replay
  const activeTrace = useMemo(() => {
    if (replayTrace.length > 0) return replayTrace;
    return trace ?? [];
  }, [trace, replayTrace]);

  // Auto-scroll to bottom when new frames arrive during replay
  useEffect(() => {
    if (autoScroll && scrollRef.current && replayTrace.length > 0) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [replayTrace.length, autoScroll]);

  const filtered = useMemo(() => {
    return activeTrace.filter((f) => {
      if (filterType !== 'ALL' && f.event_type !== filterType) return false;
      if (search) {
        const s = search.toLowerCase();
        return (
          (f.notes ?? '').toLowerCase().includes(s) ||
          (f.event_type ?? '').toLowerCase().includes(s) ||
          formatTime(f.timestamp).includes(s)
        );
      }
      return true;
    });
  }, [activeTrace, filterType, search]);

  const isLive = replayTrace.length > 0;

  if (activeTrace.length === 0) {
    return <div style={styles.empty}>{isPlaying ? 'Waiting for strategy events...' : 'Run a backtest or start replay with a strategy to view debug trace'}</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Toolbar */}
      <div style={styles.toolbar}>
        <select
          className="select select-sm"
          value={filterType}
          onChange={(e) => setFilterType(e.target.value as EventType | 'ALL')}
          style={{ width: 90 }}
        >
          <option value="ALL">All</option>
          {EVENT_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <input
          className="input input-sm"
          placeholder="Search..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 150 }}
        />
        {isLive && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 'var(--font-size-xs)', color: 'var(--text-muted)', cursor: 'pointer' }}>
            <input type="checkbox" checked={autoScroll} onChange={(e) => setAutoScroll(e.target.checked)} style={{ accentColor: 'var(--cyan)', width: 10, height: 10 }} />
            Auto-scroll
          </label>
        )}
        <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--text-dim)', marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
          {isLive && <span className="badge badge-green" style={{ fontSize: 8, padding: '1px 4px' }}>LIVE</span>}
          {filtered.length}/{activeTrace.length} frames
        </span>
      </div>

      {/* Header */}
      <div style={styles.headerRow}>
        <span>Timestamp</span>
        <span>Event</span>
        <span>Orders</span>
        <span>Fills</span>
        <span>Pos</span>
        <span>PnL</span>
        <span>Notes</span>
      </div>

      {/* Trace rows */}
      <div style={styles.container} ref={scrollRef}>
        {filtered.map((frame, i) => {
          const isExpanded = expandedIdx === i;
          const pnlVal = frame.pnl?.total_pnl ?? 0;
          const orders = frame.orders ?? [];
          const fills = frame.fills ?? [];
          const position = frame.position ?? {};
          return (
            <React.Fragment key={i}>
              <div
                style={{
                  ...styles.row,
                  background: isExpanded ? 'var(--bg-active)' : i % 2 === 0 ? undefined : 'var(--bg-panel-alt)',
                }}
                onClick={() => setExpandedIdx(isExpanded ? null : i)}
              >
                <span style={{ color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>
                  {formatTime(frame.timestamp)}
                </span>
                <span style={{ color: EVENT_COLORS[frame.event_type] || 'var(--text-secondary)' }}>
                  {frame.event_type ?? '-'}
                </span>
                <span style={{ color: 'var(--text-secondary)' }}>
                  {orders.length > 0 ? `${orders.length} order(s)` : '-'}
                </span>
                <span style={{ color: fills.length > 0 ? 'var(--green)' : 'var(--text-dim)' }}>
                  {fills.length > 0 ? `${fills.length} fill(s)` : '-'}
                </span>
                <span style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {Object.values(position).join(',') || '-'}
                </span>
                <span style={{
                  fontVariantNumeric: 'tabular-nums',
                  color: pnlVal >= 0 ? 'var(--green)' : 'var(--red)',
                  fontWeight: 500,
                }}>
                  {pnlVal >= 0 ? '+' : ''}{pnlVal.toFixed(2)}
                </span>
                <span style={{ color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {frame.notes || '-'}
                </span>
              </div>
              {isExpanded && (
                <div style={styles.expandedRow}>
                  {JSON.stringify({ orders, fills, position, pnl: frame.pnl, state: frame.state }, null, 2)}
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
}
