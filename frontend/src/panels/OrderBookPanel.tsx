import React, { useMemo } from 'react';
import { useReplayStore, useDatasetStore } from '@/store';
import type { BookLevel } from '@/types';

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflow: 'hidden',
  },
  statsRow: {
    display: 'flex',
    justifyContent: 'space-between',
    padding: '4px 8px',
    borderBottom: '1px solid var(--border-primary)',
    fontSize: 'var(--font-size-xs)',
    background: 'var(--bg-panel-alt)',
  },
  statItem: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
  },
  statLabel: {
    color: 'var(--text-dim)',
    fontSize: 9,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px',
  },
  statValue: {
    fontWeight: 600,
    fontVariantNumeric: 'tabular-nums',
  },
  ladderContainer: {
    flex: 1,
    overflow: 'auto',
    display: 'flex',
    flexDirection: 'column',
  },
  headerRow: {
    display: 'grid',
    gridTemplateColumns: '50px 1fr 70px 70px',
    padding: '2px 6px',
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
  row: {
    display: 'grid',
    gridTemplateColumns: '50px 1fr 70px 70px',
    padding: '1px 6px',
    fontSize: 'var(--font-size-sm)',
    fontVariantNumeric: 'tabular-nums',
    position: 'relative' as const,
    lineHeight: '18px',
  },
  depthBar: {
    position: 'absolute' as const,
    top: 0,
    height: '100%',
    opacity: 0.15,
    transition: 'width 0.15s ease',
  },
  spreadRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '4px 6px',
    borderTop: '1px solid var(--border-secondary)',
    borderBottom: '1px solid var(--border-secondary)',
    background: 'var(--bg-surface)',
    gap: 12,
    fontSize: 'var(--font-size-xs)',
  },
  gauge: {
    width: '100%',
    margin: '4px 8px',
  },
};

function formatPrice(p: number): string {
  return p.toFixed(1);
}

function formatSize(s: number): string {
  return s.toLocaleString();
}

export function OrderBookPanel() {
  const selectedProduct = useDatasetStore((s) => s.selectedProduct);
  const books = useReplayStore((s) => s.books);

  const book = selectedProduct ? books[selectedProduct] : null;

  const { asks, bids, maxCumulative } = useMemo(() => {
    if (!book) return { asks: [] as (BookLevel & { cum: number })[], bids: [] as (BookLevel & { cum: number })[], maxCumulative: 1 };

    let cumAsk = 0;
    const askLevels = [...(book.asks || [])].reverse().map((l) => {
      cumAsk += (l.volume ?? 0);
      return { ...l, cum: cumAsk };
    }).reverse();

    let cumBid = 0;
    const bidLevels = (book.bids || []).map((l) => {
      cumBid += (l.volume ?? 0);
      return { ...l, cum: cumBid };
    });

    const maxCum = Math.max(cumAsk, cumBid, 1);

    return { asks: askLevels, bids: bidLevels, maxCumulative: maxCum };
  }, [book]);

  const spread = book?.spread ?? 0;
  const mid = book?.mid_price ?? 0;
  const microprice = book?.microprice ?? 0;
  const imbalance = book?.top_level_imbalance ?? 0.5;

  return (
    <div className="panel" style={{ height: '100%' }}>
      <div className="panel-header">
        <span className="panel-title">Order Book</span>
        {selectedProduct && <span className="badge badge-cyan">{selectedProduct}</span>}
      </div>

      {/* Stats */}
      <div style={styles.statsRow}>
        <div style={styles.statItem}>
          <span style={styles.statLabel}>Mid</span>
          <span style={{ ...styles.statValue, color: 'var(--text-primary)' }}>{mid ? formatPrice(mid) : '-'}</span>
        </div>
        <div style={styles.statItem}>
          <span style={styles.statLabel}>Micro</span>
          <span style={{ ...styles.statValue, color: 'var(--cyan)' }}>{microprice ? formatPrice(microprice) : '-'}</span>
        </div>
        <div style={styles.statItem}>
          <span style={styles.statLabel}>Spread</span>
          <span style={{ ...styles.statValue, color: 'var(--amber)' }}>{spread ? formatPrice(spread) : '-'}</span>
        </div>
      </div>

      {/* Imbalance Gauge */}
      <div style={styles.gauge}>
        <div className="imbalance-gauge">
          <div
            className="imbalance-gauge-fill"
            style={{
              width: `${(typeof imbalance === 'number' ? imbalance : 0.5) * 100}%`,
              background: (typeof imbalance === 'number' ? imbalance : 0.5) > 0.5
                ? `linear-gradient(to right, var(--bg-surface), var(--green))`
                : `linear-gradient(to right, var(--red), var(--bg-surface))`,
            }}
          />
        </div>
      </div>

      {/* Ladder */}
      <div style={styles.ladderContainer}>
        <div style={styles.headerRow}>
          <span>CUM</span>
          <span style={{ textAlign: 'right' }}>SIZE</span>
          <span style={{ textAlign: 'right' }}>PRICE</span>
          <span style={{ textAlign: 'right' }}>SIZE</span>
        </div>

        {/* Ask levels (top, reversed so best ask at bottom) */}
        {asks.map((level, i) => (
          <div key={`ask-${i}`} style={styles.row}>
            <div style={{
              ...styles.depthBar,
              right: 0,
              width: `${(level.cum / maxCumulative) * 100}%`,
              background: 'var(--red)',
            }} />
            <span style={{ color: 'var(--text-dim)', position: 'relative', zIndex: 1 }}>{formatSize(level.cum)}</span>
            <span style={{ textAlign: 'right', position: 'relative', zIndex: 1 }} />
            <span style={{ textAlign: 'right', color: 'var(--red)', position: 'relative', zIndex: 1 }}>{formatPrice(level.price)}</span>
            <span style={{ textAlign: 'right', color: 'var(--text-secondary)', position: 'relative', zIndex: 1 }}>{formatSize(level.volume ?? 0)}</span>
          </div>
        ))}

        {/* Spread row */}
        <div style={styles.spreadRow}>
          <span style={{ color: 'var(--text-dim)' }}>SPREAD</span>
          <span style={{ color: 'var(--amber)', fontWeight: 600 }}>{spread ? formatPrice(spread) : '-'}</span>
          <span style={{ color: 'var(--text-dim)' }}>MID</span>
          <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{mid ? formatPrice(mid) : '-'}</span>
        </div>

        {/* Bid levels */}
        {bids.map((level, i) => (
          <div key={`bid-${i}`} style={styles.row}>
            <div style={{
              ...styles.depthBar,
              left: 0,
              width: `${(level.cum / maxCumulative) * 100}%`,
              background: 'var(--green)',
            }} />
            <span style={{ color: 'var(--text-dim)', position: 'relative', zIndex: 1 }}>{formatSize(level.cum)}</span>
            <span style={{ textAlign: 'right', color: 'var(--text-secondary)', position: 'relative', zIndex: 1 }}>{formatSize(level.volume ?? 0)}</span>
            <span style={{ textAlign: 'right', color: 'var(--green)', position: 'relative', zIndex: 1 }}>{formatPrice(level.price)}</span>
            <span style={{ textAlign: 'right', position: 'relative', zIndex: 1 }} />
          </div>
        ))}

        {/* Empty state */}
        {!book && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1, color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
            No data - start replay
          </div>
        )}
      </div>
    </div>
  );
}
