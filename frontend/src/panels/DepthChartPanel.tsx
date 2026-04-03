import React, { useRef, useEffect, useMemo } from 'react';
import { useReplayStore, useDatasetStore } from '@/store';

export function DepthChartPanel() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const selectedProduct = useDatasetStore((s) => s.selectedProduct);
  const books = useReplayStore((s) => s.books);

  const book = selectedProduct ? books[selectedProduct] : null;

  const { bidLevels, askLevels } = useMemo(() => {
    if (!book) return { bidLevels: [] as { price: number; cum: number }[], askLevels: [] as { price: number; cum: number }[] };

    let cum = 0;
    const bids = (book.bids || []).map((l) => {
      cum += (l.volume ?? 0);
      return { price: l.price, cum };
    });

    cum = 0;
    const asks = (book.asks || []).map((l) => {
      cum += (l.volume ?? 0);
      return { price: l.price, cum };
    });

    return { bidLevels: bids, askLevels: asks };
  }, [book]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const rect = container.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;
    const pad = { top: 10, bottom: 20, left: 10, right: 10 };

    // Clear
    ctx.fillStyle = '#0a0e17';
    ctx.fillRect(0, 0, w, h);

    if (bidLevels.length === 0 && askLevels.length === 0) {
      ctx.fillStyle = '#4b5563';
      ctx.font = '11px JetBrains Mono, monospace';
      ctx.textAlign = 'center';
      ctx.fillText('No depth data', w / 2, h / 2);
      return;
    }

    const allPrices = [...bidLevels.map((l) => l.price), ...askLevels.map((l) => l.price)];
    const minPrice = Math.min(...allPrices);
    const maxPrice = Math.max(...allPrices);
    const priceRange = maxPrice - minPrice || 1;

    const maxCum = Math.max(
      bidLevels.length ? bidLevels[bidLevels.length - 1].cum : 0,
      askLevels.length ? askLevels[askLevels.length - 1].cum : 0,
      1,
    );

    const drawW = w - pad.left - pad.right;
    const drawH = h - pad.top - pad.bottom;

    const priceToX = (p: number) => pad.left + ((p - minPrice) / priceRange) * drawW;
    const cumToY = (c: number) => pad.top + drawH - (c / maxCum) * drawH;

    // Draw bid area
    if (bidLevels.length > 0) {
      ctx.beginPath();
      ctx.moveTo(priceToX(bidLevels[0].price), pad.top + drawH);
      for (const l of bidLevels) {
        ctx.lineTo(priceToX(l.price), cumToY(l.cum));
      }
      ctx.lineTo(priceToX(bidLevels[bidLevels.length - 1].price), pad.top + drawH);
      ctx.closePath();
      ctx.fillStyle = 'rgba(16, 185, 129, 0.2)';
      ctx.fill();
      ctx.strokeStyle = '#10b981';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      for (let i = 0; i < bidLevels.length; i++) {
        const l = bidLevels[i];
        if (i === 0) ctx.moveTo(priceToX(l.price), cumToY(l.cum));
        else ctx.lineTo(priceToX(l.price), cumToY(l.cum));
      }
      ctx.stroke();
    }

    // Draw ask area
    if (askLevels.length > 0) {
      ctx.beginPath();
      ctx.moveTo(priceToX(askLevels[0].price), pad.top + drawH);
      for (const l of askLevels) {
        ctx.lineTo(priceToX(l.price), cumToY(l.cum));
      }
      ctx.lineTo(priceToX(askLevels[askLevels.length - 1].price), pad.top + drawH);
      ctx.closePath();
      ctx.fillStyle = 'rgba(239, 68, 68, 0.2)';
      ctx.fill();
      ctx.strokeStyle = '#ef4444';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      for (let i = 0; i < askLevels.length; i++) {
        const l = askLevels[i];
        if (i === 0) ctx.moveTo(priceToX(l.price), cumToY(l.cum));
        else ctx.lineTo(priceToX(l.price), cumToY(l.cum));
      }
      ctx.stroke();
    }

    // Mid line
    if (book?.mid_price) {
      const x = priceToX(book.mid_price);
      ctx.beginPath();
      ctx.strokeStyle = 'rgba(6, 182, 212, 0.5)';
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.moveTo(x, pad.top);
      ctx.lineTo(x, pad.top + drawH);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Price axis labels
    ctx.fillStyle = '#6b7280';
    ctx.font = '9px JetBrains Mono, monospace';
    ctx.textAlign = 'center';
    const steps = 5;
    for (let i = 0; i <= steps; i++) {
      const p = minPrice + (priceRange * i) / steps;
      const x = priceToX(p);
      ctx.fillText(p.toFixed(1), x, h - 4);
    }
  }, [bidLevels, askLevels, book]);

  // Handle resize
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver(() => {
      const canvas = canvasRef.current;
      if (canvas) canvas.dispatchEvent(new Event('resize'));
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="panel" style={{ height: '100%' }}>
      <div className="panel-header">
        <span className="panel-title">Depth</span>
      </div>
      <div ref={containerRef} style={{ flex: 1, position: 'relative' }}>
        <canvas ref={canvasRef} className="depth-canvas" />
      </div>
    </div>
  );
}
