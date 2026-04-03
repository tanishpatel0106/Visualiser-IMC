import React from 'react';
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';
import { Header } from '@/components/Header';
import { OrderBookPanel } from '@/panels/OrderBookPanel';
import { ChartPanel } from '@/panels/ChartPanel';
import { DepthChartPanel } from '@/panels/DepthChartPanel';
import { TradeTapePanel } from '@/panels/TradeTapePanel';
import { StrategyPanel } from '@/panels/StrategyPanel';
import { MetricsPanel } from '@/panels/MetricsPanel';
import { DebugTracePanel } from '@/panels/DebugTracePanel';
import { FillsPanel } from '@/panels/FillsPanel';
import { PositionsPanel } from '@/panels/PositionsPanel';
import { useUIStore } from '@/store';

const styles: Record<string, React.CSSProperties> = {
  root: {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    width: '100vw',
    overflow: 'hidden',
    background: 'var(--bg-base)',
  },
  main: {
    flex: 1,
    overflow: 'hidden',
  },
  bottomTabs: {
    display: 'flex',
    borderBottom: '1px solid var(--border-primary)',
    background: 'var(--bg-panel-alt)',
    flexShrink: 0,
  },
  bottomContent: {
    flex: 1,
    overflow: 'hidden',
  },
  statusBar: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '2px 8px',
    background: 'var(--bg-panel-alt)',
    borderTop: '1px solid var(--border-primary)',
    fontSize: 9,
    color: 'var(--text-dim)',
    flexShrink: 0,
    height: 20,
  },
};

const BOTTOM_TABS = [
  { key: 'trades', label: 'Trade Tape' },
  { key: 'fills', label: 'Fills' },
  { key: 'positions', label: 'Positions' },
  { key: 'metrics', label: 'Metrics' },
  { key: 'debug', label: 'Debug Trace' },
];

function BottomPanel() {
  const { bottomTab, setBottomTab } = useUIStore();

  const renderContent = () => {
    switch (bottomTab) {
      case 'trades': return <TradeTapePanel />;
      case 'fills': return <FillsPanel />;
      case 'positions': return <PositionsPanel />;
      case 'metrics': return <MetricsPanel />;
      case 'debug': return <DebugTracePanel />;
      default: return <TradeTapePanel />;
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      <div className="tabs">
        {BOTTOM_TABS.map((t) => (
          <button
            key={t.key}
            className={`tab ${bottomTab === t.key ? 'active' : ''}`}
            onClick={() => setBottomTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div style={styles.bottomContent}>
        {renderContent()}
      </div>
    </div>
  );
}

function TradingWorkspace() {
  return (
    <PanelGroup direction="vertical">
      <Panel defaultSize={65} minSize={30}>
        <PanelGroup direction="horizontal">
          {/* Left: Order Book + Depth */}
          <Panel defaultSize={20} minSize={15} maxSize={35}>
            <PanelGroup direction="vertical">
              <Panel defaultSize={65} minSize={30}>
                <OrderBookPanel />
              </Panel>
              <PanelResizeHandle />
              <Panel defaultSize={35} minSize={15}>
                <DepthChartPanel />
              </Panel>
            </PanelGroup>
          </Panel>

          <PanelResizeHandle />

          {/* Center: Chart */}
          <Panel defaultSize={55} minSize={30}>
            <ChartPanel />
          </Panel>

          <PanelResizeHandle />

          {/* Right: Strategy */}
          <Panel defaultSize={25} minSize={15} maxSize={40}>
            <StrategyPanel />
          </Panel>
        </PanelGroup>
      </Panel>

      <PanelResizeHandle />

      {/* Bottom: Tabs */}
      <Panel defaultSize={35} minSize={15} maxSize={60}>
        <div className="panel" style={{ height: '100%' }}>
          <BottomPanel />
        </div>
      </Panel>
    </PanelGroup>
  );
}

function AnalysisWorkspace() {
  return (
    <PanelGroup direction="vertical">
      <Panel defaultSize={70} minSize={30}>
        <PanelGroup direction="horizontal">
          <Panel defaultSize={70} minSize={40}>
            <ChartPanel />
          </Panel>
          <PanelResizeHandle />
          <Panel defaultSize={30} minSize={15}>
            <div className="panel" style={{ height: '100%' }}>
              <MetricsPanel />
            </div>
          </Panel>
        </PanelGroup>
      </Panel>
      <PanelResizeHandle />
      <Panel defaultSize={30} minSize={15}>
        <div className="panel" style={{ height: '100%' }}>
          <BottomPanel />
        </div>
      </Panel>
    </PanelGroup>
  );
}

function StrategyWorkspace() {
  return (
    <PanelGroup direction="horizontal">
      <Panel defaultSize={35} minSize={20}>
        <StrategyPanel />
      </Panel>
      <PanelResizeHandle />
      <Panel defaultSize={65} minSize={30}>
        <PanelGroup direction="vertical">
          <Panel defaultSize={55} minSize={20}>
            <ChartPanel />
          </Panel>
          <PanelResizeHandle />
          <Panel defaultSize={45} minSize={15}>
            <div className="panel" style={{ height: '100%' }}>
              <BottomPanel />
            </div>
          </Panel>
        </PanelGroup>
      </Panel>
    </PanelGroup>
  );
}

function DebugWorkspace() {
  return (
    <PanelGroup direction="vertical">
      <Panel defaultSize={40} minSize={20}>
        <PanelGroup direction="horizontal">
          <Panel defaultSize={30} minSize={15}>
            <OrderBookPanel />
          </Panel>
          <PanelResizeHandle />
          <Panel defaultSize={70} minSize={30}>
            <ChartPanel />
          </Panel>
        </PanelGroup>
      </Panel>
      <PanelResizeHandle />
      <Panel defaultSize={60} minSize={20}>
        <PanelGroup direction="horizontal">
          <Panel defaultSize={60} minSize={30}>
            <div className="panel" style={{ height: '100%' }}>
              <DebugTracePanel />
            </div>
          </Panel>
          <PanelResizeHandle />
          <Panel defaultSize={40} minSize={20}>
            <PanelGroup direction="vertical">
              <Panel defaultSize={50} minSize={20}>
                <div className="panel" style={{ height: '100%' }}>
                  <div className="panel-header">
                    <span className="panel-title">Positions</span>
                  </div>
                  <PositionsPanel />
                </div>
              </Panel>
              <PanelResizeHandle />
              <Panel defaultSize={50} minSize={20}>
                <div className="panel" style={{ height: '100%' }}>
                  <div className="panel-header">
                    <span className="panel-title">Fills</span>
                  </div>
                  <FillsPanel />
                </div>
              </Panel>
            </PanelGroup>
          </Panel>
        </PanelGroup>
      </Panel>
    </PanelGroup>
  );
}

export function TerminalLayout() {
  const activeWorkspace = useUIStore((s) => s.activeWorkspace);

  const renderWorkspace = () => {
    switch (activeWorkspace) {
      case 'trading': return <TradingWorkspace />;
      case 'analysis': return <AnalysisWorkspace />;
      case 'strategy': return <StrategyWorkspace />;
      case 'debug': return <DebugWorkspace />;
      default: return <TradingWorkspace />;
    }
  };

  return (
    <div style={styles.root}>
      <Header />
      <div style={styles.main}>
        {renderWorkspace()}
      </div>
      <div style={styles.statusBar}>
        <span>IMC Prosperity Terminal v1.0.0</span>
        <span>
          Workspace: {activeWorkspace.toUpperCase()} |
          Shortcuts: Space=Play/Pause, Arrows=Step, R=Reset, 1-4=Workspace
        </span>
        <span>{new Date().toLocaleTimeString()}</span>
      </div>
    </div>
  );
}
