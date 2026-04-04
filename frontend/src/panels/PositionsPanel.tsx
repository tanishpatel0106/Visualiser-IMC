import React from 'react';
import { useReplayStore } from '@/store';

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflow: 'auto',
  },
  summaryBar: {
    display: 'flex',
    justifyContent: 'space-between',
    padding: '6px 8px',
    borderBottom: '1px solid var(--border-primary)',
    background: 'var(--bg-panel-alt)',
    flexShrink: 0,
  },
  summaryItem: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
  },
  summaryLabel: {
    fontSize: 9,
    color: 'var(--text-dim)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px',
  },
  summaryValue: {
    fontSize: 'var(--font-size-sm)',
    fontWeight: 600,
    fontVariantNumeric: 'tabular-nums',
  },
  posRow: {
    display: 'grid',
    gridTemplateColumns: '80px 50px 60px 60px 70px 70px 1fr',
    gap: 4,
    padding: '4px 8px',
    borderBottom: '1px solid var(--border-primary)',
    alignItems: 'center',
    fontSize: 'var(--font-size-sm)',
    fontVariantNumeric: 'tabular-nums',
  },
  posHeader: {
    display: 'grid',
    gridTemplateColumns: '80px 50px 60px 60px 70px 70px 1fr',
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

function formatPnl(v: number): string {
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}`;
}

export function PositionsPanel() {
  const { positions, pnl } = useReplayStore();

  const posEntries = Object.values(positions ?? {});
  const totalPnl = pnl?.total_pnl ?? 0;
  const realizedPnl = pnl?.realized_pnl ?? 0;
  const unrealizedPnl = pnl?.unrealized_pnl ?? 0;

  // Also show inventory from pnl state if positions are sparse
  const inventoryEntries = pnl?.inventory ? Object.entries(pnl.inventory) : [];

  return (
    <div style={styles.container}>
      {/* Summary */}
      <div style={styles.summaryBar}>
        <div style={styles.summaryItem}>
          <span style={styles.summaryLabel}>Positions</span>
          <span style={{ ...styles.summaryValue, color: 'var(--text-primary)' }}>
            {posEntries.length > 0 ? posEntries.length : inventoryEntries.length}
          </span>
        </div>
        <div style={styles.summaryItem}>
          <span style={styles.summaryLabel}>Unrealized</span>
          <span style={{ ...styles.summaryValue, color: unrealizedPnl >= 0 ? 'var(--green)' : 'var(--red)' }}>
            {formatPnl(unrealizedPnl)}
          </span>
        </div>
        <div style={styles.summaryItem}>
          <span style={styles.summaryLabel}>Realized</span>
          <span style={{ ...styles.summaryValue, color: realizedPnl >= 0 ? 'var(--green)' : 'var(--red)' }}>
            {formatPnl(realizedPnl)}
          </span>
        </div>
        <div style={styles.summaryItem}>
          <span style={styles.summaryLabel}>Total PnL</span>
          <span style={{ ...styles.summaryValue, color: totalPnl >= 0 ? 'var(--green)' : 'var(--red)', fontSize: 'var(--font-size-base)' }}>
            {formatPnl(totalPnl)}
          </span>
        </div>
        {pnl?.cash !== undefined && (
          <div style={styles.summaryItem}>
            <span style={styles.summaryLabel}>Cash</span>
            <span style={{ ...styles.summaryValue, color: 'var(--cyan)' }}>
              {(pnl.cash ?? 0).toFixed(2)}
            </span>
          </div>
        )}
      </div>

      {/* Position table */}
      <div style={styles.posHeader}>
        <span>Product</span>
        <span style={{ textAlign: 'right' }}>Qty</span>
        <span style={{ textAlign: 'right' }}>Avg Entry</span>
        <span style={{ textAlign: 'right' }}>Mark</span>
        <span style={{ textAlign: 'right' }}>Unreal.</span>
        <span style={{ textAlign: 'right' }}>Real.</span>
        <span>Limit</span>
      </div>

      {posEntries.length > 0 ? (
        posEntries.map((pos) => {
          const posLimit = pos.position_limit ?? 20;
          const utilization = posLimit > 0 ? Math.abs(pos.quantity) / posLimit : 0;
          const utilizationPct = Math.min(utilization * 100, 100);
          const barColor = utilization > 0.8 ? 'var(--red)' : utilization > 0.5 ? 'var(--amber)' : 'var(--green)';

          return (
            <div key={pos.product} style={styles.posRow}>
              <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{pos.product}</span>
              <span style={{
                textAlign: 'right',
                color: pos.quantity > 0 ? 'var(--green)' : pos.quantity < 0 ? 'var(--red)' : 'var(--text-dim)',
                fontWeight: 600,
              }}>
                {pos.quantity > 0 ? '+' : ''}{pos.quantity}
              </span>
              <span style={{ textAlign: 'right', color: 'var(--text-secondary)' }}>
                {(pos.avg_entry_price ?? 0).toFixed(1)}
              </span>
              <span style={{ textAlign: 'right', color: 'var(--text-secondary)' }}>
                {(pos.mark_price ?? 0).toFixed(1)}
              </span>
              <span style={{
                textAlign: 'right',
                color: (pos.unrealized_pnl ?? 0) >= 0 ? 'var(--green)' : 'var(--red)',
              }}>
                {formatPnl(pos.unrealized_pnl ?? 0)}
              </span>
              <span style={{
                textAlign: 'right',
                color: (pos.realized_pnl ?? 0) >= 0 ? 'var(--green)' : 'var(--red)',
              }}>
                {formatPnl(pos.realized_pnl ?? 0)}
              </span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <div className="position-bar" style={{ flex: 1 }}>
                  <div className="position-bar-fill" style={{ width: `${utilizationPct}%`, background: barColor }} />
                </div>
                <span style={{ fontSize: 9, color: 'var(--text-dim)', minWidth: 30 }}>
                  {Math.abs(pos.quantity)}/{posLimit}
                </span>
              </div>
            </div>
          );
        })
      ) : inventoryEntries.length > 0 ? (
        /* Fall back to inventory from PnL state */
        inventoryEntries.map(([product, qty]) => (
          <div key={product} style={styles.posRow}>
            <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{product}</span>
            <span style={{
              textAlign: 'right',
              color: Number(qty) > 0 ? 'var(--green)' : Number(qty) < 0 ? 'var(--red)' : 'var(--text-dim)',
              fontWeight: 600,
            }}>
              {Number(qty) > 0 ? '+' : ''}{qty}
            </span>
            <span style={{ textAlign: 'right', color: 'var(--text-dim)' }}>-</span>
            <span style={{ textAlign: 'right', color: 'var(--text-dim)' }}>-</span>
            <span style={{ textAlign: 'right', color: 'var(--text-dim)' }}>-</span>
            <span style={{ textAlign: 'right', color: 'var(--text-dim)' }}>-</span>
            <span>-</span>
          </div>
        ))
      ) : (
        <div style={styles.empty}>No open positions</div>
      )}
    </div>
  );
}
