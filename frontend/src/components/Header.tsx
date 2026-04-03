import React from 'react';
import { useDatasetStore, useReplayStore, useStrategyStore, useUIStore } from '@/store';
import * as api from '@/services/api';

const SPEEDS = [0.25, 0.5, 1, 2, 5, 10];

const styles: Record<string, React.CSSProperties> = {
  header: {
    display: 'flex',
    alignItems: 'center',
    height: 'var(--header-height)',
    minHeight: 40,
    padding: '0 8px',
    gap: 6,
    background: 'var(--bg-panel-alt)',
    borderBottom: '1px solid var(--border-primary)',
    flexShrink: 0,
    overflow: 'hidden',
  },
  logo: {
    fontWeight: 700,
    fontSize: 13,
    color: 'var(--cyan)',
    letterSpacing: '1px',
    marginRight: 8,
    whiteSpace: 'nowrap',
  },
  divider: {
    width: 1,
    height: 20,
    background: 'var(--border-secondary)',
    margin: '0 4px',
    flexShrink: 0,
  },
  label: {
    fontSize: 'var(--font-size-xs)',
    color: 'var(--text-muted)',
    marginRight: 2,
    whiteSpace: 'nowrap',
  },
  replayGroup: {
    display: 'flex',
    alignItems: 'center',
    gap: 2,
  },
  timestamp: {
    fontSize: 'var(--font-size-sm)',
    color: 'var(--cyan)',
    fontVariantNumeric: 'tabular-nums',
    minWidth: 80,
    textAlign: 'center' as const,
  },
  statsGroup: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    marginLeft: 'auto',
  },
  stat: {
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'flex-end' as const,
    lineHeight: 1.2,
  },
  statLabel: {
    fontSize: 9,
    color: 'var(--text-dim)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px',
  },
  statValue: {
    fontSize: 'var(--font-size-sm)',
    fontWeight: 600,
    fontVariantNumeric: 'tabular-nums',
  },
  workspaceGroup: {
    display: 'flex',
    gap: 2,
  },
};

function formatPnL(val: number): string {
  const sign = val >= 0 ? '+' : '';
  return `${sign}${val.toFixed(2)}`;
}

function formatTimestamp(ts: number): string {
  if (!ts) return '00:00:000';
  const totalMs = ts % 86400000;
  const h = Math.floor(totalMs / 3600000);
  const m = Math.floor((totalMs % 3600000) / 60000);
  const s = Math.floor((totalMs % 60000) / 1000);
  const ms = totalMs % 1000;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
}

export function Header() {
  const { products, days, selectedProduct, selectedDay, setSelectedProduct, setSelectedDay, datasetInfo } = useDatasetStore();
  const { isPlaying, speed, currentTimestamp, currentIndex, totalEvents, pnl, setPlaying, setSpeed } = useReplayStore();
  const { strategies, selectedStrategy, setSelectedStrategy } = useStrategyStore();
  const { activeWorkspace, setActiveWorkspace } = useUIStore();

  const handlePlay = async () => {
    if (isPlaying) {
      await api.pauseReplay().catch(console.error);
      setPlaying(false);
    } else {
      if (selectedProduct && selectedDay !== null) {
        try {
          const session = await api.startReplay(
            [selectedProduct],
            selectedDay !== null ? [selectedDay] : []
          );
          useReplayStore.getState().setSessionId(session.session_id);
          if (session.total_events) {
            useReplayStore.setState({ totalEvents: session.total_events });
          }
          setPlaying(true);
        } catch (err) {
          console.error('Failed to start replay:', err);
        }
      }
    }
  };

  const handleStep = async () => {
    try {
      const resp = await api.stepReplay();
      if (resp?.state) {
        useReplayStore.getState().updateFromStepResponse(resp.state);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleStepBack = async () => {
    try {
      const resp = await api.stepBackReplay();
      if (resp?.state) {
        useReplayStore.getState().updateFromStepResponse(resp.state);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleReset = () => {
    api.resetReplay().catch(console.error);
    useReplayStore.getState().resetReplay();
  };

  const handleSpeedChange = (newSpeed: number) => {
    setSpeed(newSpeed);
    api.setReplaySpeed(newSpeed).catch(console.error);
  };

  const workspaces: Array<{ key: 'trading' | 'analysis' | 'strategy' | 'debug'; label: string; shortcut: string }> = [
    { key: 'trading', label: 'TRD', shortcut: '1' },
    { key: 'analysis', label: 'ANL', shortcut: '2' },
    { key: 'strategy', label: 'STR', shortcut: '3' },
    { key: 'debug', label: 'DBG', shortcut: '4' },
  ];

  const totalPnl = pnl?.total_pnl ?? 0;
  const realizedPnl = pnl?.realized_pnl ?? 0;
  const unrealizedPnl = pnl?.unrealized_pnl ?? 0;

  return (
    <div style={styles.header}>
      {/* Logo */}
      <span style={styles.logo}>IMC PROSPERITY</span>

      <div style={styles.divider} />

      {/* Product selector */}
      <span style={styles.label}>PROD</span>
      <select
        className="select select-sm"
        value={selectedProduct ?? ''}
        onChange={(e) => setSelectedProduct(e.target.value)}
        style={{ width: 110 }}
      >
        {products.length === 0 && <option value="">No products</option>}
        {products.map((p) => (
          <option key={p} value={p}>{p}</option>
        ))}
      </select>

      {/* Day selector */}
      <span style={styles.label}>DAY</span>
      <select
        className="select select-sm"
        value={selectedDay ?? ''}
        onChange={(e) => setSelectedDay(Number(e.target.value))}
        style={{ width: 55 }}
      >
        {days.length === 0 && <option value="">-</option>}
        {days.map((d) => (
          <option key={d} value={d}>{d}</option>
        ))}
      </select>

      <div style={styles.divider} />

      {/* Strategy selector */}
      <span style={styles.label}>STRAT</span>
      <select
        className="select select-sm"
        value={selectedStrategy?.strategy_id ?? ''}
        onChange={(e) => {
          const strat = strategies.find((s) => s.strategy_id === e.target.value) ?? null;
          setSelectedStrategy(strat);
        }}
        style={{ width: 120 }}
      >
        <option value="">None</option>
        {strategies.map((s) => (
          <option key={s.strategy_id} value={s.strategy_id}>{s.name}</option>
        ))}
      </select>

      <div style={styles.divider} />

      {/* Replay Controls */}
      <div style={styles.replayGroup}>
        <button className="btn btn-icon btn-ghost" onClick={handleReset} title="Reset (R)">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path d="M2 2v4h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M2.5 6A4 4 0 1 1 3.17 8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
        </button>

        <button className="btn btn-icon btn-ghost" onClick={handleStepBack} title="Step Back (Left)">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path d="M8 2L4 6l4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>

        <button
          className={`btn btn-icon ${isPlaying ? 'btn-danger' : 'btn-success'}`}
          onClick={handlePlay}
          title="Play/Pause (Space)"
          style={{ width: 28, height: 26 }}
        >
          {isPlaying ? (
            <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
              <rect x="1" y="1" width="3" height="8" rx="0.5"/>
              <rect x="6" y="1" width="3" height="8" rx="0.5"/>
            </svg>
          ) : (
            <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
              <polygon points="2,1 9,5 2,9"/>
            </svg>
          )}
        </button>

        <button className="btn btn-icon btn-ghost" onClick={handleStep} title="Step Forward (Right)">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path d="M4 2l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>

        {/* Speed selector */}
        <select
          className="select select-sm"
          value={speed}
          onChange={(e) => handleSpeedChange(Number(e.target.value))}
          style={{ width: 60 }}
        >
          {SPEEDS.map((s) => (
            <option key={s} value={s}>{s}x</option>
          ))}
        </select>
      </div>

      {/* Timestamp & progress */}
      <span style={styles.timestamp}>{formatTimestamp(currentTimestamp)}</span>
      <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--text-dim)' }}>
        {currentIndex}/{totalEvents}
      </span>

      {/* Live status badges */}
      {isPlaying && <span className="badge badge-green">LIVE</span>}
      {selectedStrategy && <span className="badge badge-blue">{selectedStrategy.name}</span>}
      {datasetInfo?.loaded && <span className="badge badge-cyan">LOADED</span>}

      {/* Stats */}
      <div style={styles.statsGroup}>
        <div style={styles.stat}>
          <span style={styles.statLabel}>Realized</span>
          <span style={{
            ...styles.statValue,
            color: realizedPnl >= 0 ? 'var(--green)' : 'var(--red)',
          }}>
            {formatPnL(realizedPnl)}
          </span>
        </div>

        <div style={styles.stat}>
          <span style={styles.statLabel}>Unrealized</span>
          <span style={{
            ...styles.statValue,
            color: unrealizedPnl >= 0 ? 'var(--green)' : 'var(--red)',
          }}>
            {formatPnL(unrealizedPnl)}
          </span>
        </div>

        <div style={styles.stat}>
          <span style={styles.statLabel}>Total PnL</span>
          <span style={{
            ...styles.statValue,
            fontSize: 'var(--font-size-base)',
            color: totalPnl >= 0 ? 'var(--green)' : 'var(--red)',
          }}>
            {formatPnL(totalPnl)}
          </span>
        </div>
      </div>

      <div style={styles.divider} />

      {/* Workspace Buttons */}
      <div style={styles.workspaceGroup}>
        {workspaces.map((w) => (
          <button
            key={w.key}
            className={`btn btn-sm ${activeWorkspace === w.key ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setActiveWorkspace(w.key)}
            title={`${w.label} (${w.shortcut})`}
          >
            {w.label}
          </button>
        ))}
      </div>
    </div>
  );
}
