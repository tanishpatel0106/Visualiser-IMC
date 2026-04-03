import React, { useState, useMemo, useEffect } from 'react';
import { useBacktestStore } from '@/store';
import * as api from '@/services/api';

type SortField = 'timestamp' | 'price' | 'quantity' | 'pnl_impact';
type SortDir = 'asc' | 'desc';

function formatTime(ts: number): string {
  if (!ts) return '--:--:--.---';
  const totalMs = ts % 86400000;
  const h = Math.floor(totalMs / 3600000);
  const m = Math.floor((totalMs % 3600000) / 60000);
  const s = Math.floor((totalMs % 60000) / 1000);
  const ms = totalMs % 1000;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
}

export function FillsPanel() {
  const { currentRun, fills, setFills } = useBacktestStore();
  const [sortField, setSortField] = useState<SortField>('timestamp');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  useEffect(() => {
    if (!currentRun || currentRun.status !== 'completed') return;
    const runId = currentRun.run_id;
    if (!runId) return;
    api.getBacktestFills(runId).then((res) => {
      setFills(res?.fills ?? []);
    }).catch(console.error);
  }, [currentRun, setFills]);

  const sorted = useMemo(() => {
    return [...(fills ?? [])].sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case 'timestamp': cmp = (a.timestamp ?? 0) - (b.timestamp ?? 0); break;
        case 'price': cmp = (a.price ?? 0) - (b.price ?? 0); break;
        case 'quantity': cmp = (a.quantity ?? 0) - (b.quantity ?? 0); break;
        case 'pnl_impact': cmp = (a.pnl_impact ?? 0) - (b.pnl_impact ?? 0); break;
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [fills, sortField, sortDir]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDir('asc');
    }
  };

  const sortIndicator = (field: SortField) => {
    if (sortField !== field) return '';
    return sortDir === 'asc' ? ' ^' : ' v';
  };

  if (!fills || fills.length === 0) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
        No fills - run a backtest
      </div>
    );
  }

  return (
    <div className="table-container" style={{ height: '100%' }}>
      <table>
        <thead>
          <tr>
            <th onClick={() => handleSort('timestamp')} style={{ cursor: 'pointer' }}>
              Time{sortIndicator('timestamp')}
            </th>
            <th>Symbol</th>
            <th className="text-center">Side</th>
            <th className="text-right" onClick={() => handleSort('price')} style={{ cursor: 'pointer' }}>
              Price{sortIndicator('price')}
            </th>
            <th className="text-right" onClick={() => handleSort('quantity')} style={{ cursor: 'pointer' }}>
              Qty{sortIndicator('quantity')}
            </th>
            <th className="text-center">Type</th>
            <th className="text-right" onClick={() => handleSort('pnl_impact')} style={{ cursor: 'pointer' }}>
              PnL Impact{sortIndicator('pnl_impact')}
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((f, i) => {
            const isBuy = f.side === 'BUY';
            const pnl = f.pnl_impact ?? 0;
            return (
              <tr key={f.id || i}>
                <td style={{ color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>
                  {formatTime(f.timestamp)}
                </td>
                <td>{f.symbol ?? f.product ?? '-'}</td>
                <td className="text-center">
                  {f.side ? (
                    <span className={isBuy ? 'badge badge-green' : 'badge badge-red'}>
                      {f.side}
                    </span>
                  ) : (
                    <span style={{ color: 'var(--text-dim)' }}>-</span>
                  )}
                </td>
                <td className="text-right" style={{ color: isBuy ? 'var(--green)' : 'var(--red)', fontVariantNumeric: 'tabular-nums' }}>
                  {(f.price ?? 0).toFixed(1)}
                </td>
                <td className="text-right" style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {f.quantity ?? 0}
                </td>
                <td className="text-center">
                  <span className={f.aggressive ? 'badge badge-amber' : 'badge badge-blue'}>
                    {f.aggressive ? 'AGG' : 'PAS'}
                  </span>
                </td>
                <td className="text-right" style={{
                  fontVariantNumeric: 'tabular-nums',
                  color: pnl > 0 ? 'var(--green)' : pnl < 0 ? 'var(--red)' : 'var(--text-dim)',
                  fontWeight: pnl !== 0 ? 500 : 400,
                }}>
                  {pnl !== 0 ? `${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}` : '-'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
