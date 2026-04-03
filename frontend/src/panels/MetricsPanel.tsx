import React, { useEffect } from 'react';
import { useBacktestStore } from '@/store';
import * as api from '@/services/api';

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflow: 'auto',
    padding: 8,
    gap: 8,
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
    gap: 6,
  },
  card: {
    background: 'var(--bg-surface)',
    border: '1px solid var(--border-primary)',
    borderRadius: 'var(--radius-md)',
    padding: '6px 8px',
  },
  cardLabel: {
    fontSize: 9,
    color: 'var(--text-dim)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px',
    marginBottom: 2,
  },
  cardValue: {
    fontSize: 'var(--font-size-md)',
    fontWeight: 600,
    fontVariantNumeric: 'tabular-nums',
  },
  sectionTitle: {
    fontSize: 'var(--font-size-xs)',
    fontWeight: 600,
    color: 'var(--text-muted)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px',
    marginBottom: 4,
  },
  sparkline: {
    width: '100%',
    height: 40,
    display: 'block',
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

function MetricCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={styles.card}>
      <div style={styles.cardLabel}>{label}</div>
      <div style={{ ...styles.cardValue, color: color ?? 'var(--text-primary)' }}>{value}</div>
    </div>
  );
}

function PnlSparkline({ data }: { data: { total_pnl: number }[] }) {
  if (data.length < 2) return null;

  const values = data.map((d) => d.total_pnl ?? 0);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const w = 300;
  const h = 40;

  const points = data.map((d, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - (((d.total_pnl ?? 0) - min) / range) * (h - 4) - 2;
    return `${x},${y}`;
  }).join(' ');

  const fillPoints = `0,${h} ${points} ${w},${h}`;

  const lastVal = values[values.length - 1];
  const color = lastVal >= 0 ? 'var(--green)' : 'var(--red)';

  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={styles.sparkline} preserveAspectRatio="none">
      <polygon points={fillPoints} fill={lastVal >= 0 ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)'} />
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

function formatNum(n: number | undefined | null, decimals = 2): string {
  if (n === undefined || n === null) return '-';
  return n.toFixed(decimals);
}

function formatPct(n: number | undefined | null): string {
  if (n === undefined || n === null) return '-';
  return `${(n * 100).toFixed(1)}%`;
}

function pnlColor(n: number | undefined | null): string {
  if (n === undefined || n === null) return 'var(--text-primary)';
  return n >= 0 ? 'var(--green)' : 'var(--red)';
}

export function MetricsPanel() {
  const { currentRun, metrics, pnlHistory, setMetrics, setPnlHistory } = useBacktestStore();

  useEffect(() => {
    if (!currentRun || currentRun.status !== 'completed') return;
    const runId = currentRun.run_id;
    if (!runId) return;

    api.getBacktestMetrics(runId).then(setMetrics).catch(console.error);
    api.getBacktestPnl(runId).then((res) => {
      setPnlHistory(res?.pnl_history ?? []);
    }).catch(console.error);
  }, [currentRun, setMetrics, setPnlHistory]);

  if (!metrics) {
    return (
      <div style={styles.empty}>
        Run a backtest to view metrics
      </div>
    );
  }

  const m = metrics;

  return (
    <div style={styles.container}>
      {/* PnL Sparkline */}
      {pnlHistory && pnlHistory.length > 0 && (
        <div>
          <div style={styles.sectionTitle}>PnL Curve</div>
          <PnlSparkline data={pnlHistory} />
        </div>
      )}

      {/* Key Stats */}
      <div>
        <div style={styles.sectionTitle}>Performance</div>
        <div style={styles.grid}>
          <MetricCard label="Total PnL" value={formatNum(m.total_pnl)} color={pnlColor(m.total_pnl)} />
          <MetricCard label="Realized" value={formatNum(m.realized_pnl)} color={pnlColor(m.realized_pnl)} />
          <MetricCard label="Sharpe" value={formatNum(m.sharpe_ratio)} color={(m.sharpe_ratio ?? 0) >= 1 ? 'var(--green)' : (m.sharpe_ratio ?? 0) >= 0 ? 'var(--amber)' : 'var(--red)'} />
          <MetricCard label="Max DD" value={formatNum(m.max_drawdown)} color="var(--red)" />
          <MetricCard label="Win Rate" value={formatPct(m.win_rate)} color={(m.win_rate ?? 0) >= 0.5 ? 'var(--green)' : 'var(--red)'} />
          <MetricCard label="Profit Factor" value={formatNum(m.profit_factor)} color={(m.profit_factor ?? 0) >= 1 ? 'var(--green)' : 'var(--red)'} />
          <MetricCard label="Trades" value={String(m.num_trades ?? 0)} />
          <MetricCard label="Wins/Losses" value={`${m.num_wins ?? 0}/${m.num_losses ?? 0}`} />
          <MetricCard label="Avg Win" value={formatNum(m.avg_win)} color="var(--green)" />
          <MetricCard label="Avg Loss" value={formatNum(m.avg_loss)} color="var(--red)" />
          <MetricCard label="Volume" value={formatNum(m.total_volume, 0)} />
          <MetricCard label="Avg Position" value={formatNum(m.avg_position)} />
          <MetricCard label="Max Position" value={formatNum(m.max_position)} />
          <MetricCard label="Fees" value={formatNum(m.total_fees)} color="var(--amber)" />
        </div>
      </div>
    </div>
  );
}
