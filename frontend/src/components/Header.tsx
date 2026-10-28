import React from 'react';
import { Activity, RefreshCw, Search } from 'lucide-react';
import { MarketPulse } from '../types';

interface HeaderProps {
  pulse: MarketPulse | null;
  searchQuery: string;
  onSearchChange: (val: string) => void;
  onRefresh: () => void;
  isRefreshing: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  pulse,
  searchQuery,
  onSearchChange,
  onRefresh,
  isRefreshing,
}) => {
  return (
    <header className="sticky top-0 z-40 w-full border-b border-white/[0.06] bg-[#07090E]/90 backdrop-blur-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16 gap-4">
          {/* Brand Logo & Name */}
          <div className="flex items-center gap-3 shrink-0">
            <div className="w-9 h-9 rounded-xl bg-cyan-950/60 border border-token-cyan/30 flex items-center justify-center shadow-glow-cyan">
              <Activity className="w-5 h-5 text-token-cyan" />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-lg font-bold tracking-tight text-white font-sans">
                VESPER<span className="text-token-cyan">GLASS</span>
              </span>
              <span className="text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded bg-cyan-950/50 text-token-cyan border border-cyan-800/40">
                QUANT v1.0
              </span>
            </div>
          </div>

          {/* Indices Ticker Ribbon (Hidden on small mobile) */}
          {pulse && pulse.indices && (
            <div className="hidden lg:flex items-center gap-6 text-xs font-mono tabular-nums px-4 py-1.5 rounded-lg bg-surface/60 border border-white/[0.06]">
              {Object.entries(pulse.indices).map(([sym, idxData]) => {
                const isPos = idxData.change_pct >= 0;
                return (
                  <div key={sym} className="flex items-center gap-1.5">
                    <span className="text-slate-400 font-semibold">{sym}</span>
                    <span className="text-slate-200">${idxData.price.toFixed(2)}</span>
                    <span className={`text-[11px] font-medium ${isPos ? 'text-token-emerald' : 'text-token-rose'}`}>
                      {isPos ? '+' : ''}{idxData.change_pct.toFixed(2)}%
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          {/* Right Controls: Pulse status, Search, Refresh */}
          <div className="flex items-center gap-3">
            {/* Search Box */}
            <div className="relative hidden sm:block w-48 md:w-64">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                placeholder="Search ticker or name..."
                value={searchQuery}
                onChange={(e) => onSearchChange(e.target.value)}
                className="w-full bg-[#0C1017] border border-white/[0.08] rounded-lg pl-9 pr-8 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-token-cyan/50 focus:ring-1 focus:ring-token-cyan/30 transition-all font-mono"
              />
              {searchQuery && (
                <button
                  onClick={() => onSearchChange('')}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-slate-500 hover:text-slate-300"
                >
                  ✕
                </button>
              )}
            </div>

            {/* Engine Status Pulse */}
            <div className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-surface/60 border border-white/[0.06] text-xs font-medium text-slate-300">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-token-emerald opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-token-emerald"></span>
              </span>
              <span>1,015 Analyzed</span>
            </div>

            {/* Refresh Button */}
            <button
              onClick={onRefresh}
              disabled={isRefreshing}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface/80 hover:bg-surface-elevated border border-white/[0.08] hover:border-token-cyan/40 text-xs font-medium text-slate-200 transition-all shadow-sm active:scale-95 disabled:opacity-50"
              title="Refresh Scanner"
            >
              <RefreshCw className={`w-3.5 h-3.5 text-token-cyan ${isRefreshing ? 'animate-spin' : ''}`} />
              <span className="hidden sm:inline">Refresh</span>
            </button>
          </div>
        </div>
      </div>
    </header>
  );
};
