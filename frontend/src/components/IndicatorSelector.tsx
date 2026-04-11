/**
 * Dynamic indicator selector with per-instance parameter configuration.
 * Supports adding multiple instances of the same indicator type (e.g. SMA 5 + SMA 20 + SMA 50).
 */

import React, { useState, useRef, useEffect, useMemo } from 'react';
import { INDICATOR_CATEGORIES, INDICATORS, getIndicatorById, type IndicatorDef } from '@/utils/indicatorRegistry';
import { useUIStore } from '@/store';
import type { IndicatorInstance } from '@/types';

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
    position: 'absolute',
    top: '100%',
    right: 0,
    zIndex: 100,
    width: 520,
    maxHeight: '75vh',
    minHeight: 420,
    background: 'var(--bg-panel)',
    border: '1px solid var(--border-primary)',
    borderRadius: 6,
    boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
    display: 'flex',
    flexDirection: 'column',
    marginTop: 4,
  },
  header: {
    padding: '8px 12px', borderBottom: '1px solid var(--border-primary)',
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  },
  title: { fontSize: 'var(--font-size-md)', fontWeight: 600, color: 'var(--text-primary)' },
  searchBox: {
    width: 'calc(100% - 24px)',
    padding: '6px 10px',
    margin: '8px 12px',
    fontSize: 'var(--font-size-sm)',
    background: 'var(--bg-surface)',
    border: '1px solid var(--border-secondary)',
    borderRadius: 4,
    color: 'var(--text-primary)',
    outline: 'none',
    boxSizing: 'border-box' as const,
    flexShrink: 0,
  },
  body: {
    flex: 1,
    minHeight: 0,
    overflowY: 'auto' as const,
    padding: '0 4px 8px',
  },
  catHeader: {
    display: 'flex', alignItems: 'center', gap: 6, padding: '8px 8px 4px',
    cursor: 'pointer', userSelect: 'none' as const,
    fontSize: 'var(--font-size-sm)', fontWeight: 600, color: 'var(--text-secondary)',
  },
  catBadge: {
    marginLeft: 'auto', fontSize: 9, color: 'var(--text-dim)',
    background: 'var(--bg-surface)', padding: '1px 5px', borderRadius: 8,
  },
  row: {
    display: 'flex', alignItems: 'center', gap: 6,
    padding: '4px 8px 4px 20px', cursor: 'pointer', borderRadius: 3,
    fontSize: 'var(--font-size-xs)', color: 'var(--text-secondary)',
  },
  colorDot: { width: 8, height: 8, borderRadius: '50%', flexShrink: 0 },
  count: { fontSize: 9, color: 'var(--cyan)', padding: '0 4px' },
  clearBtn: {
    fontSize: 'var(--font-size-xs)', color: 'var(--red)', cursor: 'pointer',
    background: 'none', border: 'none', padding: '2px 6px',
  },
  // Active instances section
  activeSection: {
    borderBottom: '1px solid var(--border-primary)',
    padding: '6px 8px',
    maxHeight: 160,
    overflowY: 'auto' as const,
    flexShrink: 0,
  },
  activeRow: {
    display: 'flex', alignItems: 'center', gap: 6,
    padding: '3px 6px', borderRadius: 3, fontSize: 'var(--font-size-xs)',
    background: 'rgba(6,182,212,0.08)',
    marginBottom: 2,
  },
  paramInput: {
    width: 50, padding: '1px 4px', fontSize: 'var(--font-size-xs)',
    background: 'var(--bg-surface)', border: '1px solid var(--border-secondary)',
    borderRadius: 3, color: 'var(--text-primary)', textAlign: 'center' as const,
  },
  removeBtn: {
    background: 'none', border: 'none', color: 'var(--red)', cursor: 'pointer',
    fontSize: 11, padding: '0 2px', lineHeight: 1,
  },
  addBtn: {
    background: 'var(--bg-surface)', border: '1px solid var(--border-secondary)',
    color: 'var(--cyan)', cursor: 'pointer', fontSize: 9, padding: '2px 6px',
    borderRadius: 3, marginLeft: 'auto', flexShrink: 0,
  },
};

/** Generate a label for an indicator instance, e.g. "SMA(20)" */
function instanceLabel(inst: IndicatorInstance, def?: IndicatorDef): string {
  const d = def ?? getIndicatorById(inst.id);
  if (!d) return inst.id;
  const paramVals = d.params.map(p => inst.params[p.name] ?? p.default);
  if (paramVals.length === 0) return d.shortName;
  return `${d.shortName}(${paramVals.join(',')})`;
}

export function IndicatorSelector() {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [expandedCats, setExpandedCats] = useState<Set<string>>(new Set(INDICATOR_CATEGORIES.map(c => c.id)));
  const [hoveredRow, setHoveredRow] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const { selectedIndicators, addIndicator, removeIndicator, updateIndicatorParams, setSelectedIndicators } = useUIStore();

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

  /** Add a new instance of an indicator with default params */
  const handleAddIndicator = (def: IndicatorDef) => {
    const params: Record<string, number> = {};
    def.params.forEach(p => { params[p.name] = p.default; });
    const key = `${def.id}_${Date.now()}`;
    addIndicator({ key, id: def.id, params });
  };

  /** Update a single param value on an existing instance */
  const handleParamChange = (key: string, paramName: string, value: number) => {
    const inst = selectedIndicators.find(i => i.key === key);
    if (!inst) return;
    updateIndicatorParams(key, { ...inst.params, [paramName]: value });
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

  // Count active instances per indicator type
  const activeCountById = useMemo(() => {
    const counts: Record<string, number> = {};
    selectedIndicators.forEach(inst => {
      counts[inst.id] = (counts[inst.id] ?? 0) + 1;
    });
    return counts;
  }, [selectedIndicators]);

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
                Clear All ({activeCount})
              </button>
            )}
          </div>

          {/* Active indicator instances with editable params */}
          {activeCount > 0 && (
            <div style={styles.activeSection}>
              <div style={{ fontSize: 9, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 4 }}>
                Active Indicators
              </div>
              {selectedIndicators.map(inst => {
                const def = getIndicatorById(inst.id);
                if (!def) return null;
                return (
                  <div key={inst.key} style={styles.activeRow}>
                    <span style={{ ...styles.colorDot, background: def.color }} />
                    <span style={{ fontWeight: 600, color: 'var(--text-primary)', minWidth: 40 }}>
                      {def.shortName}
                    </span>
                    <span style={{ color: 'var(--text-dim)', fontSize: 9 }}>
                      {def.placement === 'overlay' ? '◆' : '▣'}
                    </span>
                    {/* Editable params inline */}
                    {def.params.map(p => (
                      <span key={p.name} style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                        <span style={{ fontSize: 9, color: 'var(--text-dim)' }}>{p.name}:</span>
                        <input
                          type="number"
                          style={styles.paramInput}
                          value={inst.params[p.name] ?? p.default}
                          min={p.min}
                          max={p.max}
                          step={p.step ?? 1}
                          onChange={(e) => handleParamChange(inst.key, p.name, Number(e.target.value))}
                          onClick={(e) => e.stopPropagation()}
                        />
                      </span>
                    ))}
                    <button
                      style={styles.removeBtn}
                      onClick={() => removeIndicator(inst.key)}
                      title="Remove"
                    >
                      ✕
                    </button>
                  </div>
                );
              })}
            </div>
          )}

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
              const activeInCat = catIndicators.reduce((sum, ind) => sum + (activeCountById[ind.id] ?? 0), 0);

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
                    const count = activeCountById[ind.id] ?? 0;
                    const hovered = hoveredRow === ind.id;
                    return (
                      <div
                        key={ind.id}
                        style={{
                          ...styles.row,
                          ...(hovered ? { background: 'rgba(6,182,212,0.08)' } : {}),
                        }}
                        onMouseEnter={() => setHoveredRow(ind.id)}
                        onMouseLeave={() => setHoveredRow(null)}
                        onClick={() => handleAddIndicator(ind)}
                      >
                        <span style={{ ...styles.colorDot, background: ind.color }} />
                        <span style={{ fontWeight: count > 0 ? 600 : 400, color: count > 0 ? 'var(--text-primary)' : undefined }}>
                          {ind.shortName}
                        </span>
                        <span style={{ color: 'var(--text-dim)', fontSize: 9 }}>
                          {ind.placement === 'overlay' ? '◆' : '▣'}
                        </span>
                        {/* Show default params hint */}
                        {ind.params.length > 0 && (
                          <span style={{ fontSize: 9, color: 'var(--text-dim)' }}>
                            ({ind.params.map(p => p.default).join(',')})
                          </span>
                        )}
                        {count > 0 && (
                          <span style={{ fontSize: 9, color: 'var(--cyan)', fontWeight: 600 }}>
                            ×{count}
                          </span>
                        )}
                        <button
                          style={styles.addBtn}
                          onClick={(e) => { e.stopPropagation(); handleAddIndicator(ind); }}
                          title={`Add ${ind.shortName}`}
                        >
                          + Add
                        </button>
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
