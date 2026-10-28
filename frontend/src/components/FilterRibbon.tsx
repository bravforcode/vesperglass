import React from 'react';
import { Filter, SlidersHorizontal, ChevronDown } from 'lucide-react';

interface FilterRibbonProps {
  selectedStrategy: string;
  onStrategyChange: (strategy: string) => void;
  selectedSector: string;
  onSectorChange: (sector: string) => void;
  minReturn: number;
  onMinReturnChange: (minReturn: number) => void;
  marketCap: string;
  onMarketCapChange: (cap: string) => void;
  minRr: number;
  onMinRrChange: (rr: number) => void;
  totalFilteredCount: number;
}

export const FilterRibbon: React.FC<FilterRibbonProps> = ({
  selectedStrategy,
  onStrategyChange,
  selectedSector,
  onSectorChange,
  minReturn,
  onMinReturnChange,
  marketCap,
  onMarketCapChange,
  minRr,
  onMinRrChange,
  totalFilteredCount,
}) => {
  const strategies = [
    { id: 'all', label: 'All Strategies' },
    { id: 'momentum_breakout', label: 'Momentum Breakout' },
    { id: 'earnings_pead', label: 'Earnings Drift' },
    { id: 'oversold_bounce', label: 'Oversold Bounce' },
    { id: 'quality_fcf', label: 'Quality & FCF' },
  ];

  const sectors = [
    'All Sectors',
    'Technology',
    'Healthcare',
    'Consumer Discretionary',
    'Financials',
    'Industrials',
    'Consumer Staples',
    'Communication Services',
  ];

  const returnTiers = [
    { label: 'All', value: 0 },
    { label: '≥ 3%', value: 3.0 },
    { label: '≥ 5%', value: 5.0 },
    { label: '≥ 10%', value: 10.0 },
  ];

  const capTiers = [
    { id: 'all', label: 'All Caps' },
    { id: 'mega', label: 'Mega (> $200B)' },
    { id: 'large', label: 'Large ($10B–$200B)' },
    { id: 'mid', label: 'Mid ($2B–$10B)' },
  ];

  const rrTiers = [
    { label: '≥ 2.0', value: 2.0 },
    { label: '≥ 2.5', value: 2.5 },
    { label: '≥ 3.0', value: 3.0 },
  ];

  return (
    <div className="glass-panel rounded-xl p-4 space-y-3 shadow-glass-card">
      {/* Top Row: Strategy Pills & Count Indicator */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs font-semibold text-slate-400 mr-1 flex items-center gap-1">
            <Filter className="w-3.5 h-3.5 text-token-cyan" />
            Strategy:
          </span>
          {strategies.map((st) => {
            const active = selectedStrategy === st.id;
            return (
              <button
                key={st.id}
                onClick={() => onStrategyChange(st.id)}
                className={`px-3 py-1 rounded-lg text-xs font-medium transition-all ${
                  active
                    ? 'bg-token-cyan/20 text-token-cyan border border-token-cyan/50 shadow-glow-cyan'
                    : 'bg-surface/80 text-slate-400 hover:text-slate-200 hover:bg-surface-elevated border border-white/[0.04]'
                }`}
              >
                {st.label}
              </button>
            );
          })}
        </div>

        <div className="text-xs font-mono text-slate-400">
          Showing <span className="text-token-cyan font-bold tabular-nums">{totalFilteredCount}</span> candidates
        </div>
      </div>

      {/* Bottom Row: Sector Dropdown, Return % Buttons, Cap Tiers, R:R */}
      <div className="flex flex-wrap items-center gap-4 pt-2 border-t border-white/[0.04] text-xs">
        {/* Sector Selector */}
        <div className="flex items-center gap-2">
          <span className="text-slate-400 font-medium">Sector:</span>
          <div className="relative">
            <select
              value={selectedSector}
              onChange={(e) => onSectorChange(e.target.value)}
              className="appearance-none bg-[#0C1017] border border-white/[0.08] rounded-lg pl-3 pr-8 py-1 text-slate-200 text-xs focus:outline-none focus:border-token-cyan/50 focus:ring-1 focus:ring-token-cyan/30 cursor-pointer"
            >
              {sectors.map((s) => (
                <option key={s} value={s === 'All Sectors' ? 'all' : s} className="bg-[#0C1017] text-slate-200">
                  {s}
                </option>
              ))}
            </select>
            <ChevronDown className="w-3.5 h-3.5 text-slate-400 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
          </div>
        </div>

        {/* Min Expected Return */}
        <div className="flex items-center gap-1.5">
          <span className="text-slate-400 font-medium">Target Upside:</span>
          <div className="inline-flex rounded-lg bg-[#0C1017] p-0.5 border border-white/[0.08]">
            {returnTiers.map((tier) => {
              const active = minReturn === tier.value;
              return (
                <button
                  key={tier.label}
                  onClick={() => onMinReturnChange(tier.value)}
                  className={`px-2.5 py-0.5 rounded text-xs font-mono tabular-nums transition-all ${
                    active
                      ? 'bg-token-emerald text-black font-semibold shadow-sm'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {tier.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Market Cap Tier */}
        <div className="flex items-center gap-1.5">
          <span className="text-slate-400 font-medium">Market Cap:</span>
          <div className="inline-flex rounded-lg bg-[#0C1017] p-0.5 border border-white/[0.08]">
            {capTiers.map((tier) => {
              const active = marketCap === tier.id;
              return (
                <button
                  key={tier.id}
                  onClick={() => onMarketCapChange(tier.id)}
                  className={`px-2.5 py-0.5 rounded text-xs font-medium transition-all ${
                    active
                      ? 'bg-token-cyan text-black font-semibold shadow-sm'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {tier.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Min R:R Ratio */}
        <div className="flex items-center gap-1.5">
          <span className="text-slate-400 font-medium flex items-center gap-1">
            <SlidersHorizontal className="w-3 h-3 text-token-cyan" />
            Min R:R:
          </span>
          <div className="inline-flex rounded-lg bg-[#0C1017] p-0.5 border border-white/[0.08]">
            {rrTiers.map((tier) => {
              const active = minRr === tier.value;
              return (
                <button
                  key={tier.label}
                  onClick={() => onMinRrChange(tier.value)}
                  className={`px-2 py-0.5 rounded text-xs font-mono tabular-nums transition-all ${
                    active
                      ? 'bg-cyan-500 text-black font-semibold'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {tier.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};
