import React from 'react';
import { TrendingUp, Zap, CornerLeftUp, ShieldCheck } from 'lucide-react';

interface StrategyBadgeProps {
  strategy: string;
  size?: 'sm' | 'md';
}

export const StrategyBadge: React.FC<StrategyBadgeProps> = ({ strategy, size = 'md' }) => {
  const s = strategy.toLowerCase().replace(/_/g, ' ');

  if (s.includes('momentum')) {
    return (
      <span className={`inline-flex items-center gap-1 font-medium rounded-full bg-cyan-950/40 text-token-cyan border border-cyan-500/30 shadow-glow-cyan ${size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs'}`}>
        <TrendingUp className="w-3 h-3 text-token-cyan" />
        <span>Momentum Breakout</span>
      </span>
    );
  }

  if (s.includes('earnings') || s.includes('pead')) {
    return (
      <span className={`inline-flex items-center gap-1 font-medium rounded-full bg-violet-950/40 text-violet-300 border border-violet-500/30 shadow-glow-violet ${size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs'}`}>
        <Zap className="w-3 h-3 text-token-violet" />
        <span>Earnings Drift</span>
      </span>
    );
  }

  if (s.includes('oversold') || s.includes('reversion') || s.includes('bounce')) {
    return (
      <span className={`inline-flex items-center gap-1 font-medium rounded-full bg-emerald-950/40 text-token-emerald border border-emerald-500/30 shadow-glow-emerald ${size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs'}`}>
        <CornerLeftUp className="w-3 h-3 text-token-emerald" />
        <span>Oversold Bounce</span>
      </span>
    );
  }

  if (s.includes('quality') || s.includes('fcf')) {
    return (
      <span className={`inline-flex items-center gap-1 font-medium rounded-full bg-amber-950/40 text-amber-300 border border-amber-500/30 shadow-glow-amber ${size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs'}`}>
        <ShieldCheck className="w-3 h-3 text-token-amber" />
        <span>Quality & FCF</span>
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full bg-slate-800 text-slate-300 border border-slate-700">
      {strategy}
    </span>
  );
};
