import React, { useRef, useEffect } from 'react';
import { useReplayStore } from '@/store';
import * as api from '@/services/api';

const LARGE_TRADE_THRESHOLD = 50;

function formatTime(ts: number): string {
  if (!ts) return '--:--:--';
  const totalMs = ts % 86400000;
  const h = Math.floor(totalMs / 3600000);
  const m = Math.floor((totalMs % 3600000) / 60000);
  const s = Math.floor((totalMs % 60000) / 1000);
  const ms = totalMs % 1000;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
}

export function TradeTapePanel() {
  const trades = useReplayStore((s) => s.trades);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [trades]);

  const handleJumpToTimestamp = (ts: number) => {
    api.seekReplay(ts).catch(console.error);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="table-container" ref={scrollRef}>
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Symbol</th>
              <th className="text-right">Price</th>
              <th className="text-right">Qty</th>
              <th className="text-center">Side</th>
              <th>Buyer</th>
              <th>Seller</th>
            </tr>
          </thead>
          <tbody>
            {(!trades || trades.length === 0) && (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', color: 'var(--text-dim)', padding: 20 }}>
                  No trades yet
                </td>
              </tr>
            )}
            {(trades ?? []).map((t, i) => {
              const isBuy = t.aggressor_side === 'BUY';
              const isSell = t.aggressor_side === 'SELL';
              const isLarge = (t.quantity ?? 0) >= LARGE_TRADE_THRESHOLD;
              return (
                <tr
                  key={i}
                  onClick={() => handleJumpToTimestamp(t.timestamp)}
                  style={{
                    cursor: 'pointer',
                    background: isLarge
                      ? isBuy ? 'rgba(16,185,129,0.08)' : isSell ? 'rgba(239,68,68,0.08)' : undefined
                      : undefined,
                  }}
                >
                  <td style={{ color: 'var(--text-muted)' }}>{formatTime(t.timestamp)}</td>
                  <td>{t.symbol ?? '-'}</td>
                  <td
                    className="text-right"
                    style={{ color: isBuy ? 'var(--green)' : isSell ? 'var(--red)' : 'var(--text-secondary)', fontWeight: isLarge ? 600 : 400 }}
                  >
                    {(t.price ?? 0).toFixed(1)}
                  </td>
                  <td
                    className="text-right"
                    style={{ fontWeight: isLarge ? 600 : 400 }}
                  >
                    {t.quantity ?? 0}
                  </td>
                  <td className="text-center">
                    {t.aggressor_side ? (
                      <span className={isBuy ? 'badge badge-green' : 'badge badge-red'}>
                        {t.aggressor_side}
                      </span>
                    ) : (
                      <span className="badge" style={{ color: 'var(--text-dim)' }}>-</span>
                    )}
                  </td>
                  <td style={{ color: 'var(--text-muted)' }}>{t.buyer ?? '-'}</td>
                  <td style={{ color: 'var(--text-muted)' }}>{t.seller ?? '-'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
