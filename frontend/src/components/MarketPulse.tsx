import React from 'react';
import { Target, Layers, TrendingUp, CheckCircle2 } from 'lucide-react';
import { MarketPulse as MarketPulseType } from '../types';

interface MarketPulseProps {
  pulse: MarketPulseType | null;
  onSelectTopOpportunity?: (ticker: string) => void;
}

export const MarketPulse: React.FC<MarketPulseProps> = ({ pulse, onSelectTopOpportunity }) => {
  if (!pulse) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 animate-pulse">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-28 rounded-xl bg-surface/50 border border-white/[0.04]" />
        ))}
      </div>
    );
  }

  const top = pulse.top_opportunity;
  const sig = pulse.active_signals;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {/* 1. Top Opportunity Card */}
      <div
        onClick={() => top && onSelectTopOpportunity && onSelectTopOpportunity(top.ticker)}
        className="glass-panel rounded-xl p-4 cursor-pointer hover:border-token-cyan/40 transition-all group relative overflow-hidden shadow-glass-card hover:shadow-glow-cyan"
      >
        <div className="flex items-center justify-between text-xs text-slate-400 mb-1.5">
          <span className="font-semibold uppercase tracking-wider text-[11px] text-token-cyan flex items-center gap-1.5">
            <Target className="w-3.5 h-3.5 text-token-cyan" />
            Top Opportunity
          </span>
          <span className="text-[10px] font-mono text-cyan-400 bg-cyan-950/40 px-1.5 py-0.5 rounded border border-cyan-800/40">
            R:R 1:{top.risk_reward_ratio.toFixed(1)}
          </span>
        </div>
        <div className="flex items-baseline justify-between mt-1">
          <span className="text-2xl font-bold font-mono text-white group-hover:text-token-cyan transition-colors">
            {top.ticker}
          </span>
          <span className="text-xl font-bold font-mono tabular-nums text-token-emerald">
            +{top.target_return_pct.toFixed(1)}%
          </span>
        </div>
        <p className="text-xs text-slate-400 mt-1 truncate">
          {top.strategy.replace(/_/g, ' ')} setup
        </p>
      </div>

      {/* 2. Active Swing Signals */}
      <div className="glass-panel rounded-xl p-4 shadow-glass-card relative overflow-hidden hover:border-token-violet/40 transition-all hover:shadow-glow-violet">
        <div className="flex items-center justify-between text-xs text-slate-400 mb-1.5">
          <span className="font-semibold uppercase tracking-wider text-[11px] text-token-violet flex items-center gap-1.5">
            <Layers className="w-3.5 h-3.5 text-token-violet" />
            Active Signals
          </span>
          <span className="text-[10px] font-mono text-slate-400">
            {sig.total} Total
          </span>
        </div>
        <div className="flex items-baseline justify-between mt-1">
          <span className="text-2xl font-bold font-mono tabular-nums text-white">
            {sig.total} <span className="text-xs font-sans font-normal text-slate-400">Candidates</span>
          </span>
        </div>
        <div className="flex items-center gap-2 mt-2 text-[11px] font-mono text-slate-400">
          <span className="text-token-cyan">{sig.momentum} Mom</span>
          <span>•</span>
          <span className="text-token-violet">{sig.earnings} Earn</span>
          <span>•</span>
          <span className="text-token-emerald">{sig.oversold} OS</span>
          <span>•</span>
          <span className="text-token-amber">{sig.quality} FCF</span>
        </div>
      </div>

      {/* 3. Expected Return Average */}
      <div className="glass-panel rounded-xl p-4 shadow-glass-card relative overflow-hidden hover:border-token-emerald/40 transition-all hover:shadow-glow-emerald">
        <div className="flex items-center justify-between text-xs text-slate-400 mb-1.5">
          <span className="font-semibold uppercase tracking-wider text-[11px] text-token-emerald flex items-center gap-1.5">
            <TrendingUp className="w-3.5 h-3.5 text-token-emerald" />
            Expected Return Avg
          </span>
          <span className="text-[10px] font-mono text-emerald-400 bg-emerald-950/40 px-1.5 py-0.5 rounded border border-emerald-800/40">
            Target 3–10%
          </span>
        </div>
        <div className="flex items-baseline justify-between mt-1">
          <span className="text-2xl font-bold font-mono tabular-nums text-token-emerald">
            +{pulse.expected_return_avg.toFixed(1)}%
          </span>
        </div>
        <p className="text-xs text-slate-400 mt-1">
          Target holding period: 7 to 15 trading days
        </p>
      </div>

      {/* 4. Engine Win Rate */}
      <div className="glass-panel rounded-xl p-4 shadow-glass-card relative overflow-hidden hover:border-token-amber/40 transition-all hover:shadow-glow-amber">
        <div className="flex items-center justify-between text-xs text-slate-400 mb-1.5">
          <span className="font-semibold uppercase tracking-wider text-[11px] text-token-amber flex items-center gap-1.5">
            <CheckCircle2 className="w-3.5 h-3.5 text-token-amber" />
            Engine Win Rate
          </span>
          <span className="text-[10px] font-mono text-amber-400 bg-amber-950/40 px-1.5 py-0.5 rounded border border-amber-800/40">
            Backtest
          </span>
        </div>
        <div className="flex items-baseline justify-between mt-1">
          <span className="text-2xl font-bold font-mono tabular-nums text-token-amber">
            {pulse.win_rate_pct.toFixed(1)}%
          </span>
        </div>
        <p className="text-xs text-slate-400 mt-1">
          Walk-forward verified • Profit factor: 2.38
        </p>
      </div>
    </div>
  );
};
