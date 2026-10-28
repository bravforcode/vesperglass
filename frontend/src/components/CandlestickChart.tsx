import React, { useEffect, useRef } from 'react';
import { createChart, ColorType, IChartApi, LineStyle } from 'lightweight-charts';
import { CandleBar, VolumeBar } from '../types';

interface CandlestickChartProps {
  candles: CandleBar[];
  volumes: VolumeBar[];
  entryPrice: number;
  targetPrice: number;
  stopLossPrice: number;
}

export const CandlestickChart: React.FC<CandlestickChartProps> = ({
  candles,
  volumes,
  entryPrice,
  targetPrice,
  stopLossPrice,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    // Clean up previous instance if any
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0C1017' },
        textColor: '#94A3B8',
        fontFamily: 'JetBrains Mono, monospace',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.04)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.04)' },
      },
      crosshair: {
        vertLine: { color: '#00F2FE', width: 1, style: LineStyle.Dashed },
        horzLine: { color: '#00F2FE', width: 1, style: LineStyle.Dashed },
      },
      rightPriceScale: {
        borderColor: 'rgba(255, 255, 255, 0.08)',
        scaleMargins: {
          top: 0.1,
          bottom: 0.25,
        },
      },
      timeScale: {
        borderColor: 'rgba(255, 255, 255, 0.08)',
        timeVisible: true,
      },
      width: containerRef.current.clientWidth,
      height: 340,
    });

    // 1. Candlestick Series
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#10B981',
      downColor: '#F43F5E',
      borderVisible: false,
      wickUpColor: '#10B981',
      wickDownColor: '#F43F5E',
    });

    // Sort ascending by time
    const sortedCandles = [...candles].sort((a, b) => a.time.localeCompare(b.time));
    candleSeries.setData(sortedCandles as any);

    // 2. Volume Histogram Series in bottom sub-pane
    const volumeSeries = chart.addHistogramSeries({
      color: '#26a69a',
      priceFormat: { type: 'volume' },
      priceScaleId: '', // overlay pane
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.78, bottom: 0 },
    });
    const sortedVolumes = [...volumes].sort((a, b) => a.time.localeCompare(b.time));
    volumeSeries.setData(sortedVolumes as any);

    // 3. Trade Execution Overlay Price Lines
    if (targetPrice > 0) {
      candleSeries.createPriceLine({
        price: targetPrice,
        color: '#10B981',
        lineWidth: 2,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: `TARGET: $${targetPrice.toFixed(2)}`,
      });
    }

    if (entryPrice > 0) {
      candleSeries.createPriceLine({
        price: entryPrice,
        color: '#00F2FE',
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: `ENTRY: $${entryPrice.toFixed(2)}`,
      });
    }

    if (stopLossPrice > 0) {
      candleSeries.createPriceLine({
        price: stopLossPrice,
        color: '#F43F5E',
        lineWidth: 2,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: `STOP: $${stopLossPrice.toFixed(2)}`,
      });
    }

    chart.timeScale().fitContent();
    chartRef.current = chart;

    // Handle responsive container resizing
    const resizeObserver = new ResizeObserver((entries) => {
      if (!entries || entries.length === 0 || !chartRef.current) return;
      const { width } = entries[0].contentRect;
      chartRef.current.applyOptions({ width });
    });

    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [candles, volumes, entryPrice, targetPrice, stopLossPrice]);

  return (
    <div className="relative w-full rounded-xl overflow-hidden border border-white/[0.08] bg-[#0C1017]">
      <div className="flex items-center justify-between px-3 py-2 border-b border-white/[0.06] bg-surface-elevated/40 text-xs">
        <span className="font-semibold text-slate-300 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-token-cyan" />
          Interactive Candlestick & Volume Chart (252 Bars)
        </span>
        <div className="flex items-center gap-3 font-mono text-[11px] text-slate-400">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 bg-token-cyan rounded-sm inline-block" /> Entry
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 bg-token-emerald rounded-sm inline-block" /> Target
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 bg-token-rose rounded-sm inline-block" /> Stop
          </span>
        </div>
      </div>
      <div ref={containerRef} className="w-full h-[340px]" />
    </div>
  );
};
