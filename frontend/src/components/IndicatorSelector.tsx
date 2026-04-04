/**
 * Categorized indicator selector panel.
 * Renders as a scrollable dropdown panel anchored to the chart toolbar.
 */

import React, { useState, useRef, useEffect } from 'react';
import { INDICATOR_CATEGORIES, INDICATORS, type IndicatorDef } from '@/utils/indicatorRegistry';
import { useUIStore } from '@/store';

const styles: Record<string, React.CSSProperties> = {
  wrapper: { position: 'relative', display: 'inline-block' },
  trigger: {
    display: 'flex', alignItems: 'center', gap: 4,
    padding: '2px 8px', fontSize: 'var(--font-size-xs)',
    cursor: 'pointer', borderRadius: 3,
    background: 'var(--bg-surface)', border: '1px solid var(--border-primary)',
    color: 'var(--text-secondary)',
  },
  panel: {
    position: 'absolute', top: '100%', right: 0, zIndex: 100,
    width: 420, maxHeight: 500,
    background: 'var(--bg-panel)', border: '1px solid var(--border-primary)',
    borderRadius: 6, boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
    display: 'flex', flexDirection: 'column',
    marginTop: 4,
  },
  header: {
    padding: '8px 12px', borderBottom: '1px solid var(--border-primary)',
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  },
  title: { fontSize: 'var(--font-size-md)', fontWeight: 600, color: 'var(--text-primary)' },
  searchBox: {
    width: '100%', padding: '6px 10px', margin: '8px 12px', fontSize: 'var(--font-size-sm)',
    background: 'var(--bg-surface)', border: '1px solid var(--border-secondary)',
    borderRadius: 4, color: 'var(--text-primary)', outline: 'none',
    boxSizing: 'border-box',
  },
  body: { flex: 1, overflowY: 'auto', padding: '0 4px 8px' },
  catHeader: {
    display: 'flex', alignItems: 'center', gap: 6, padding: '8px 8px 4px',
    cursor: 'pointer', userSelect: 'none',
    fontSize: 'var(--font-size-sm)', fontWeight: 600, color: 'var(--text-secondary)',
  },
  catBadge: {
    marginLeft: 'auto', fontSize: 9, color: 'var(--text-dim)',
    background: 'var(--bg-surface)', padding: '1px 5px', borderRadius: 8,
  },
  row: {
    display: 'flex', alignItems: 'center', gap: 6,
    padding: '3px 8px 3px 20px', cursor: 'pointer', borderRadius: 3,
    fontSize: 'var(--font-size-xs)', color: 'var(--text-secondary)',
  },
  rowHover: { background: 'rgba(6,182,212,0.08)' },
  colorDot: {
    width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
  },
  desc: { marginLeft: 'auto', fontSize: 9, color: 'var(--text-dim)', maxWidth: 180, textAlign: 'right' as const, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const },
  count: {
    fontSize: 9, color: 'var(--cyan)', padding: '0 4px',
  },
  clearBtn: {
    fontSize: 'var(--font-size-xs)', color: 'var(--red)', cursor: 'pointer',
    background: 'none', border: 'none', padding: '2px 6px',
  },
};

export function IndicatorSelector() {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [expandedCats, setExpandedCats] = useState<Set<string>>(new Set(INDICATOR_CATEGORIES.map(c => c.id)));
  const [hoveredRow, setHoveredRow] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const { selectedIndicators, toggleIndicator, setSelectedIndicators } = useUIStore();

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const toggleCat = (catId: string) => {
    setExpandedCats(prev => {
      const next = new Set(prev);
      if (next.has(catId)) next.delete(catId); else next.add(catId);
      return next;
    });
  };

  const lowerSearch = search.toLowerCase();
  const filteredIndicators = lowerSearch
    ? INDICATORS.filter(ind =>
        ind.name.toLowerCase().includes(lowerSearch) ||
        ind.shortName.toLowerCase().includes(lowerSearch) ||
        ind.id.toLowerCase().includes(lowerSearch) ||
        ind.description.toLowerCase().includes(lowerSearch)
      )
    : INDICATORS;

  const activeCount = selectedIndicators.length;

  return (
    <div style={styles.wrapper} ref={panelRef}>
      <button style={styles.trigger} onClick={() => setOpen(!open)}>
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M1 9h3M5 9h6M1 6h6M9 6h2M1 3h2M5 3h6" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
        Indicators
        {activeCount > 0 && <span style={styles.count}>({activeCount})</span>}
      </button>

      {open && (
        <div style={styles.panel}>
          <div style={styles.header}>
            <span style={styles.title}>Indicators</span>
            {activeCount > 0 && (
              <button style={styles.clearBtn} onClick={() => setSelectedIndicators([])}>
                Clear All
              </button>
            )}
          </div>

          <input
            style={styles.searchBox}
            type="text"
            placeholder="Search indicators..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
          />

          <div style={styles.body}>
            {INDICATOR_CATEGORIES.map(cat => {
              const catIndicators = filteredIndicators.filter(ind => ind.category === cat.id);
              if (catIndicators.length === 0) return null;
              const expanded = expandedCats.has(cat.id);
              const activeInCat = catIndicators.filter(ind => selectedIndicators.includes(ind.id)).length;

              return (
                <div key={cat.id}>
                  <div style={styles.catHeader} onClick={() => toggleCat(cat.id)}>
                    <span style={{ fontSize: 10 }}>{expanded ? '▼' : '▶'}</span>
                    <span>{cat.label}</span>
                    {activeInCat > 0 && (
                      <span style={{ fontSize: 9, color: 'var(--cyan)', marginLeft: 4 }}>
                        {activeInCat} active
                      </span>
                    )}
                    <span style={styles.catBadge}>{catIndicators.length}</span>
                  </div>

                  {expanded && catIndicators.map((ind: IndicatorDef) => {
                    const active = selectedIndicators.includes(ind.id);
                    const hovered = hoveredRow === ind.id;
                    return (
                      <div
                        key={ind.id}
                        style={{ ...styles.row, ...(hovered ? styles.rowHover : {}), ...(active ? { background: 'rgba(6,182,212,0.12)' } : {}) }}
                        onClick={() => toggleIndicator(ind.id)}
                        onMouseEnter={() => setHoveredRow(ind.id)}
                        onMouseLeave={() => setHoveredRow(null)}
                      >
                        <input
                          type="checkbox"
                          checked={active}
                          readOnly
                          style={{ accentColor: 'var(--cyan)', width: 10, height: 10, cursor: 'pointer' }}
                        />
                        <span style={{ ...styles.colorDot, background: ind.color }} />
                        <span style={{ fontWeight: active ? 600 : 400, color: active ? 'var(--text-primary)' : undefined }}>
                          {ind.shortName}
                        </span>
                        <span style={{ color: 'var(--text-dim)', fontSize: 9, marginLeft: 2 }}>
                          {ind.placement === 'overlay' ? '◆' : '▣'}
                        </span>
                        <span style={styles.desc} title={ind.description}>{ind.description}</span>
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
