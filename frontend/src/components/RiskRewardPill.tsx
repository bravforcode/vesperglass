import React from 'react';

interface RiskRewardPillProps {
  ratio: number;
}

export const RiskRewardPill: React.FC<RiskRewardPillProps> = ({ ratio }) => {
  const isHigh = ratio >= 2.8;
  const isGood = ratio >= 2.0;

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded font-mono tabular-nums text-xs font-semibold ${
        isHigh
          ? 'bg-emerald-950/60 text-emerald-400 border border-emerald-500/40 shadow-glow-emerald'
          : isGood
          ? 'bg-cyan-950/50 text-cyan-300 border border-cyan-500/30'
          : 'bg-rose-950/50 text-rose-300 border border-rose-500/30'
      }`}
    >
      1 : {ratio.toFixed(1)}
    </span>
  );
};
