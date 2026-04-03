import React, { useState } from 'react';
import { useStrategyStore, useDatasetStore, useBacktestStore } from '@/store';
import * as api from '@/services/api';
import type { StrategyDefinition, StrategyParameter, ExecutionModel } from '@/types';

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflow: 'hidden',
  },
  section: {
    borderBottom: '1px solid var(--border-primary)',
    padding: 8,
  },
  sectionTitle: {
    fontSize: 9,
    fontWeight: 600,
    color: 'var(--text-dim)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px',
    marginBottom: 6,
  },
  stratList: {
    maxHeight: 120,
    overflow: 'auto',
  },
  stratItem: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '3px 6px',
    cursor: 'pointer',
    borderRadius: 2,
    fontSize: 'var(--font-size-sm)',
  },
  paramGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 4,
  },
  paramLabel: {
    fontSize: 'var(--font-size-xs)',
    color: 'var(--text-muted)',
    marginBottom: 1,
  },
  sourceViewer: {
    flex: 1,
    overflow: 'auto',
    background: 'var(--bg-base)',
    padding: 8,
    fontSize: 'var(--font-size-sm)',
    lineHeight: 1.6,
    whiteSpace: 'pre',
    color: 'var(--text-secondary)',
    tabSize: 4,
  },
  actions: {
    display: 'flex',
    gap: 4,
    padding: 8,
    borderTop: '1px solid var(--border-primary)',
    flexShrink: 0,
  },
};

const EXEC_MODELS: { value: ExecutionModel; label: string }[] = [
  { value: 'CONSERVATIVE', label: 'Conservative' },
  { value: 'BALANCED', label: 'Balanced' },
  { value: 'OPTIMISTIC', label: 'Optimistic' },
];

function ParamInput({ param, value, onChange }: { param: StrategyParameter; value: unknown; onChange: (v: unknown) => void }) {
  switch (param.type) {
    case 'int':
    case 'float':
      return (
        <input
          className="input input-sm"
          type="number"
          value={String(value ?? param.default)}
          min={param.min}
          max={param.max}
          step={param.step ?? (param.type === 'int' ? 1 : 0.1)}
          onChange={(e) => onChange(param.type === 'int' ? parseInt(e.target.value) : parseFloat(e.target.value))}
          style={{ width: '100%' }}
        />
      );
    case 'bool':
      return (
        <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={Boolean(value ?? param.default)}
            onChange={(e) => onChange(e.target.checked)}
            style={{ accentColor: 'var(--cyan)' }}
          />
          <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--text-secondary)' }}>
            {Boolean(value ?? param.default) ? 'Yes' : 'No'}
          </span>
        </label>
      );
    case 'select':
      return (
        <select
          className="select select-sm"
          value={String(value ?? param.default)}
          onChange={(e) => onChange(e.target.value)}
          style={{ width: '100%' }}
        >
          {(param.options || []).map((opt) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
      );
    default:
      return (
        <input
          className="input input-sm"
          type="text"
          value={String(value ?? param.default ?? '')}
          onChange={(e) => onChange(e.target.value)}
          style={{ width: '100%' }}
        />
      );
  }
}

export function StrategyPanel() {
  const { strategies, selectedStrategy, parameters, sourceCode, setSelectedStrategy, setParameter, setSourceCode, resetParameters } = useStrategyStore();
  const { selectedProduct, selectedDay, products, days } = useDatasetStore();
  const { addRun, setCurrentRun } = useBacktestStore();

  const [searchTerm, setSearchTerm] = useState('');
  const [execModel, setExecModel] = useState<ExecutionModel>('BALANCED');
  const [posLimit, setPosLimit] = useState(20);
  const [isRunning, setIsRunning] = useState(false);
  const [showSource, setShowSource] = useState(false);

  const filteredStrategies = strategies.filter((s) =>
    s.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    (s.category ?? '').toLowerCase().includes(searchTerm.toLowerCase())
  );

  const categories = [...new Set(strategies.map((s) => s.category ?? 'default'))];

  const handleSelectStrategy = async (strat: StrategyDefinition) => {
    setSelectedStrategy(strat);
    try {
      const src = await api.fetchStrategySource(strat.strategy_id);
      setSourceCode(src);
    } catch {
      setSourceCode('// Source not available');
    }
  };

  const handleRun = async () => {
    if (!selectedStrategy || !selectedProduct || selectedDay === null) return;
    setIsRunning(true);
    try {
      const positionLimits: Record<string, number> = {};
      if (selectedProduct) {
        positionLimits[selectedProduct] = posLimit;
      }
      const run = await api.runStrategy(selectedStrategy.strategy_id, {
        products: selectedProduct ? [selectedProduct] : products,
        days: selectedDay !== null ? [selectedDay] : days,
        execution_model: execModel,
        position_limits: positionLimits,
        fees: 0,
        slippage: 0,
      });
      addRun(run);
      setCurrentRun(run);
    } catch (err) {
      console.error('Strategy run failed:', err);
    } finally {
      setIsRunning(false);
    }
  };

  const handleUpload = async () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.py,.ts,.js';
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      try {
        const text = await file.text();
        const result = await api.uploadStrategy(file.name.replace(/\.\w+$/, ''), text);
        if (result.valid && result.strategy_id) {
          // Refresh strategies list
          const updated = await api.fetchStrategies();
          useStrategyStore.getState().setStrategies(updated);
        } else if (result.error) {
          console.error('Upload validation error:', result.error);
        }
      } catch (err) {
        console.error('Upload failed:', err);
      }
    };
    input.click();
  };

  return (
    <div className="panel" style={{ height: '100%' }}>
      <div className="panel-header">
        <span className="panel-title">Strategy</span>
        <div style={{ display: 'flex', gap: 4 }}>
          <button className="btn btn-sm btn-ghost" onClick={handleUpload}>Upload</button>
          <button
            className="btn btn-sm"
            onClick={() => setShowSource(!showSource)}
            style={{ color: showSource ? 'var(--cyan)' : undefined }}
          >
            {showSource ? 'Params' : 'Source'}
          </button>
        </div>
      </div>

      <div style={styles.container}>
        {/* Strategy Browser */}
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Library</div>
          <input
            className="input input-sm"
            placeholder="Search strategies..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{ width: '100%', marginBottom: 4 }}
          />
          <div style={styles.stratList}>
            {categories.map((cat) => {
              const items = filteredStrategies.filter((s) => (s.category ?? 'default') === cat);
              if (items.length === 0) return null;
              return (
                <div key={cat}>
                  <div style={{ fontSize: 9, color: 'var(--text-dim)', padding: '4px 6px', textTransform: 'uppercase' }}>{cat}</div>
                  {items.map((s) => (
                    <div
                      key={s.strategy_id}
                      style={{
                        ...styles.stratItem,
                        background: selectedStrategy?.strategy_id === s.strategy_id ? 'var(--bg-active)' : undefined,
                        color: selectedStrategy?.strategy_id === s.strategy_id ? 'var(--cyan)' : 'var(--text-secondary)',
                      }}
                      onClick={() => handleSelectStrategy(s)}
                    >
                      <span>{s.name}</span>
                      <button
                        className="btn btn-sm btn-success"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleSelectStrategy(s).then(handleRun);
                        }}
                        style={{ padding: '1px 4px', fontSize: 9 }}
                      >
                        RUN
                      </button>
                    </div>
                  ))}
                </div>
              );
            })}
            {filteredStrategies.length === 0 && (
              <div style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-xs)', padding: 8, textAlign: 'center' }}>
                {strategies.length === 0 ? 'No strategies loaded' : 'No matches'}
              </div>
            )}
          </div>
        </div>

        {showSource && sourceCode ? (
          /* Source Code Viewer */
          <div style={styles.sourceViewer}>
            {sourceCode.split('\n').map((line, i) => (
              <div key={i}>
                <span style={{ display: 'inline-block', width: 35, textAlign: 'right', paddingRight: 8, color: 'var(--text-dim)', userSelect: 'none' }}>{i + 1}</span>
                {line}
              </div>
            ))}
          </div>
        ) : (
          <>
            {/* Parameters */}
            {selectedStrategy && (selectedStrategy.parameters?.length ?? 0) > 0 && (
              <div style={styles.section}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                  <div style={styles.sectionTitle}>Parameters</div>
                  <button className="btn btn-sm btn-ghost" onClick={resetParameters}>Reset</button>
                </div>
                <div style={styles.paramGrid}>
                  {(selectedStrategy.parameters ?? []).map((p) => (
                    <div key={p.name}>
                      <div style={styles.paramLabel} title={p.description}>{p.name}</div>
                      <ParamInput
                        param={p}
                        value={parameters[p.name]}
                        onChange={(v) => setParameter(p.name, v)}
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Execution Config */}
            <div style={styles.section}>
              <div style={styles.sectionTitle}>Execution</div>
              <div style={styles.paramGrid}>
                <div>
                  <div style={styles.paramLabel}>Model</div>
                  <select
                    className="select select-sm"
                    value={execModel}
                    onChange={(e) => setExecModel(e.target.value as ExecutionModel)}
                    style={{ width: '100%' }}
                  >
                    {EXEC_MODELS.map((m) => (
                      <option key={m.value} value={m.value}>{m.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <div style={styles.paramLabel}>Pos Limit</div>
                  <input
                    className="input input-sm"
                    type="number"
                    value={posLimit}
                    onChange={(e) => setPosLimit(parseInt(e.target.value))}
                    min={1}
                    max={100}
                    style={{ width: '100%' }}
                  />
                </div>
              </div>
            </div>

            {/* Description */}
            {selectedStrategy && (
              <div style={{ ...styles.section, flex: 1, overflow: 'auto' }}>
                <div style={styles.sectionTitle}>Description</div>
                <p style={{ fontSize: 'var(--font-size-xs)', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                  {selectedStrategy.description || 'No description available.'}
                </p>
              </div>
            )}
          </>
        )}

        {/* Action buttons */}
        <div style={styles.actions}>
          <button
            className={`btn ${isRunning ? 'btn-danger' : 'btn-success'}`}
            onClick={handleRun}
            disabled={!selectedStrategy || isRunning}
            style={{ flex: 1 }}
          >
            {isRunning ? (
              <>
                <span className="spinner" style={{ width: 12, height: 12 }} />
                Running...
              </>
            ) : (
              'Run Strategy'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
