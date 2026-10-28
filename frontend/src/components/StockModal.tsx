import React, { useEffect, useState } from 'react';
import {
  X,
  Target,
  ShieldAlert,
  ArrowUpRight,
  TrendingUp,
  Scale,
  CalendarClock,
  CheckCircle2,
  XCircle,
  Building,
  DollarSign,
  Percent,
} from 'lucide-react';
import { CandlestickChart } from './CandlestickChart';
import { FactorRadarChart } from './FactorRadarChart';
import { CatalystTimeline } from './CatalystTimeline';
import { StrategyBadge } from './StrategyBadges';
import { RiskRewardPill } from './RiskRewardPill';
import { StockDetail } from '../types';

interface StockModalProps {
  ticker: string | null;
  onClose: () => void;
}

export const StockModal: React.FC<StockModalProps> = ({ ticker, onClose }) => {
  const [data, setData] = useState<StockDetail | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Interactive Position Sizing Calculator state
  const [accountSize, setAccountSize] = useState<number>(15000);
  const [riskPct, setRiskPct] = useState<number>(2.0);

  useEffect(() => {
    if (!ticker) return;

    setLoading(true);
    setError(null);

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);

    fetch(`/api/stock/${ticker}`)
      .then((res) => {
        if (!res.ok) throw new Error(`Stock '${ticker}' not found`);
        return res.json();
      })
      .then((json: StockDetail) => {
        setData(json);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || 'Failed to load stock details');
        setLoading(false);
      });

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [ticker, onClose]);

  // Interactive Position Sizing calculations
  const effectiveRiskPerShare = data
    ? Math.max(0.01, data.setup.risk_per_share || (data.setup.entry_price - data.setup.stop_loss))
    : 1;
  const dollarRiskLimit = (accountSize * riskPct) / 100;
  const calculatedShares = Math.max(1, Math.floor(dollarRiskLimit / effectiveRiskPerShare));
  const totalCapitalRequired = data ? calculatedShares * data.setup.entry_price : 0;
  const portfolioAllocPct = accountSize > 0 ? (totalCapitalRequired / accountSize) * 100 : 0;
  const totalExpectedGain = data ? calculatedShares * data.setup.reward_per_share : 0;

  if (!ticker) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 md:p-6 overflow-y-auto bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
      <div
        className="relative w-full max-w-6xl rounded-2xl border border-white/[0.1] bg-[#07090E] text-slate-100 shadow-2xl overflow-hidden my-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top Header Bar */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.08] bg-[#0C1017]">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-2xl font-bold font-mono tracking-tight text-white">
              {ticker}
            </span>
            {data && (
              <>
                <span className="text-sm text-slate-300 font-medium">
                  {data.name}
                </span>
                <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700">
                  {data.sector}
                </span>
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-cyan-950/40 text-token-cyan border border-cyan-800/40">
                  {data.market_cap_tier} Cap
                </span>
              </>
            )}
          </div>

          <div className="flex items-center gap-4">
            {data && (
              <div className="text-right font-mono tabular-nums">
                <span className="text-xl font-bold text-white">
                  ${data.price.toFixed(2)}
                </span>
                <span
                  className={`text-xs ml-2 font-medium ${
                    data.change_24h_pct >= 0 ? 'text-token-emerald' : 'text-token-rose'
                  }`}
                >
                  {data.change_24h_pct >= 0 ? '+' : ''}
                  {data.change_24h_pct.toFixed(2)}%
                </span>
              </div>
            )}
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-lg flex items-center justify-center bg-surface hover:bg-surface-elevated text-slate-400 hover:text-white transition-all border border-white/[0.06]"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Modal Body */}
        <div className="p-4 sm:p-6 max-h-[82vh] overflow-y-auto">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-24 gap-3 text-slate-400">
              <div className="w-8 h-8 rounded-full border-2 border-token-cyan border-t-transparent animate-spin" />
              <p className="text-sm font-mono">Loading quantitative model for {ticker}...</p>
            </div>
          ) : error || !data ? (
            <div className="py-16 text-center text-token-rose font-mono">
              <p className="text-base font-semibold">{error || 'Failed to load stock data'}</p>
              <button
                onClick={onClose}
                className="mt-4 px-4 py-1.5 rounded-lg bg-surface border border-white/10 text-xs text-slate-300 hover:text-white"
              >
                Close Dialog
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              {/* Left Column (Charts & Visual Analytics, 7 cols) */}
              <div className="lg:col-span-7 space-y-4">
                {/* Candlestick & Volume Chart with Execution Levels */}
                <CandlestickChart
                  candles={data.candles}
                  volumes={data.volumes}
                  entryPrice={data.setup.entry_price}
                  targetPrice={data.setup.target_price}
                  stopLossPrice={data.setup.stop_loss}
                />

                {/* Sub-grid: 5-Axis Factor Radar + Catalyst Timeline */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <FactorRadarChart data={data.radar_comparison} ticker={data.ticker} />
                  <CatalystTimeline events={data.catalysts} />
                </div>
              </div>

              {/* Right Column (Trade Setup Blueprint & Quantitative Checklist, 5 cols) */}
              <div className="lg:col-span-5 space-y-4">
                {/* 1. Trade Setup Blueprint Card */}
                <div className="glass-panel rounded-xl p-4 shadow-glass-card border border-token-cyan/30">
                  <div className="flex items-center justify-between pb-3 mb-3 border-b border-white/[0.08]">
                    <div className="flex items-center gap-2">
                      <Target className="w-4 h-4 text-token-cyan" />
                      <h3 className="text-xs font-bold uppercase tracking-wider text-token-cyan">
                        Trade Execution Blueprint
                      </h3>
                    </div>
                    <RiskRewardPill ratio={data.setup.risk_reward_ratio} />
                  </div>

                  <div className="grid grid-cols-2 gap-3 text-xs font-mono tabular-nums">
                    {/* Target Price */}
                    <div className="p-2.5 rounded-lg bg-emerald-950/30 border border-emerald-500/20">
                      <div className="text-[10px] text-emerald-400/80 uppercase font-semibold flex items-center gap-1">
                        <ArrowUpRight className="w-3 h-3 text-token-emerald" /> Target Price
                      </div>
                      <div className="text-lg font-bold text-token-emerald mt-0.5">
                        ${data.setup.target_price.toFixed(2)}
                      </div>
                      <div className="text-[10px] text-emerald-400">
                        +{data.setup.target_return_pct.toFixed(1)}% expected gain
                      </div>
                    </div>

                    {/* Stop-Loss Price */}
                    <div className="p-2.5 rounded-lg bg-rose-950/30 border border-rose-500/20">
                      <div className="text-[10px] text-rose-400/80 uppercase font-semibold flex items-center gap-1">
                        <ShieldAlert className="w-3 h-3 text-token-rose" /> Stop-Loss
                      </div>
                      <div className="text-lg font-bold text-token-rose mt-0.5">
                        ${data.setup.stop_loss.toFixed(2)}
                      </div>
                      <div className="text-[10px] text-rose-400">
                        1.5x ATR ({data.setup.atr_14.toFixed(2)}) cushion
                      </div>
                    </div>

                    {/* Ideal Entry */}
                    <div className="p-2.5 rounded-lg bg-surface border border-white/[0.06]">
                      <div className="text-[10px] text-slate-400 uppercase font-semibold">
                        Ideal Entry
                      </div>
                      <div className="text-base font-bold text-token-cyan mt-0.5">
                        ${data.setup.entry_price.toFixed(2)}
                      </div>
                      <div className="text-[10px] text-slate-500">
                        Zone: ${(data.setup.entry_price * 0.995).toFixed(2)} - ${(data.setup.entry_price * 1.005).toFixed(2)}
                      </div>
                    </div>

                    {/* Position Sizing */}
                    <div className="p-2.5 rounded-lg bg-surface border border-white/[0.06]">
                      <div className="text-[10px] text-slate-400 uppercase font-semibold flex items-center justify-between">
                        <span className="flex items-center gap-1">
                          <Scale className="w-3 h-3 text-token-amber" /> Sizing ({calculatedShares} shs)
                        </span>
                        <span className="text-token-emerald font-bold">
                          +${totalExpectedGain.toFixed(0)} gain
                        </span>
                      </div>
                      <div className="text-base font-bold text-slate-100 mt-0.5">
                        ${totalCapitalRequired.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                      </div>
                      <div className="text-[10px] text-slate-400 flex justify-between">
                        <span>Risk: -${dollarRiskLimit.toFixed(0)} ({riskPct}%)</span>
                        <span className="text-token-cyan">{portfolioAllocPct.toFixed(0)}% alloc</span>
                      </div>
                    </div>
                  </div>

                  {/* Interactive Account & Risk Controls */}
                  <div className="mt-3 p-2.5 rounded-lg bg-black/40 border border-white/[0.06] space-y-2">
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="text-slate-400 font-medium">Account Size:</span>
                      <div className="flex items-center gap-1">
                        {[5000, 15000, 25000, 50000].map((amt) => (
                          <button
                            key={amt}
                            onClick={() => setAccountSize(amt)}
                            className={`px-1.5 py-0.5 rounded text-[10px] font-mono transition-colors ${
                              accountSize === amt
                                ? 'bg-token-cyan/20 text-token-cyan font-bold border border-token-cyan/40'
                                : 'bg-surface text-slate-400 hover:text-white'
                            }`}
                          >
                            ${amt / 1000}k
                          </button>
                        ))}
                      </div>
                    </div>

                    <div className="flex items-center justify-between text-[11px]">
                      <span className="text-slate-400 font-medium">Risk Per Trade:</span>
                      <div className="flex items-center gap-1">
                        {[1.0, 1.5, 2.0, 3.0].map((r) => (
                          <button
                            key={r}
                            onClick={() => setRiskPct(r)}
                            className={`px-1.5 py-0.5 rounded text-[10px] font-mono transition-colors ${
                              riskPct === r
                                ? 'bg-token-amber/20 text-token-amber font-bold border border-token-amber/40'
                                : 'bg-surface text-slate-400 hover:text-white'
                            }`}
                          >
                            {r.toFixed(1)}%
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="mt-3 pt-2.5 border-t border-white/[0.06] flex items-center justify-between text-xs text-slate-400">
                    <span className="flex items-center gap-1 text-[11px]">
                      <CalendarClock className="w-3.5 h-3.5 text-token-violet" />
                      Horizon: <span className="text-slate-200">{data.setup.horizon_days || '7 to 15 Trading Days'}</span>
                    </span>
                    <span className="text-[11px] font-mono">
                      Reward/Risk: <span className="text-token-emerald font-semibold">${data.setup.reward_per_share.toFixed(2)}</span> / <span className="text-token-rose">${data.setup.risk_per_share.toFixed(2)}</span>
                    </span>
                  </div>
                </div>

                {/* 2. Quantitative Strategy Checklist */}
                <div className="glass-panel rounded-xl p-4 shadow-glass-card">
                  <div className="flex items-center justify-between mb-3 pb-2 border-b border-white/[0.08]">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                      <CheckCircle2 className="w-3.5 h-3.5 text-token-emerald" />
                      Quantitative Criteria Checklist
                    </h4>
                    <div className="flex gap-1">
                      {data.strategies.map((st) => (
                        <StrategyBadge key={st} strategy={st} size="sm" />
                      ))}
                    </div>
                  </div>

                  <div className="space-y-2 text-xs">
                    {data.strategy_checklist.map((chk, i) => (
                      <div
                        key={i}
                        className="flex items-start gap-2.5 p-2 rounded-lg bg-surface/50 border border-white/[0.04]"
                      >
                        {chk.passed ? (
                          <CheckCircle2 className="w-4 h-4 text-token-emerald shrink-0 mt-0.5" />
                        ) : (
                          <XCircle className="w-4 h-4 text-token-rose shrink-0 mt-0.5" />
                        )}
                        <div className="flex-1 min-w-0">
                          <p className="font-semibold text-slate-200 text-xs">
                            {chk.criterion}
                          </p>
                          <p className="text-[11px] text-slate-400 mt-0.5 font-mono">
                            {chk.detail}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* 3. Fundamental Financials Grid */}
                <div className="glass-panel rounded-xl p-4 shadow-glass-card">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-slate-300 mb-3 pb-2 border-b border-white/[0.08] flex items-center gap-1.5">
                    <Building className="w-3.5 h-3.5 text-token-amber" />
                    Key Financial Ratios & Fundamentals
                  </h4>

                  <div className="grid grid-cols-3 gap-2.5 text-center font-mono tabular-nums">
                    <div className="p-2 rounded bg-surface border border-white/[0.04]">
                      <div className="text-[10px] text-slate-400">ROE</div>
                      <div className="text-sm font-bold text-white mt-0.5">
                        {data.fundamentals.roe?.toFixed(1) || '--'}%
                      </div>
                    </div>
                    <div className="p-2 rounded bg-surface border border-white/[0.04]">
                      <div className="text-[10px] text-slate-400">FCF Yield</div>
                      <div className="text-sm font-bold text-token-emerald mt-0.5">
                        {data.fundamentals.fcf_yield?.toFixed(1) || '--'}%
                      </div>
                    </div>
                    <div className="p-2 rounded bg-surface border border-white/[0.04]">
                      <div className="text-[10px] text-slate-400">Debt/Equity</div>
                      <div className="text-sm font-bold text-slate-200 mt-0.5">
                        {data.fundamentals.debt_to_equity?.toFixed(2) || '--'}
                      </div>
                    </div>
                    <div className="p-2 rounded bg-surface border border-white/[0.04]">
                      <div className="text-[10px] text-slate-400">Forward P/E</div>
                      <div className="text-sm font-bold text-slate-200 mt-0.5">
                        {data.fundamentals.forward_pe?.toFixed(1) || '--'}x
                      </div>
                    </div>
                    <div className="p-2 rounded bg-surface border border-white/[0.04]">
                      <div className="text-[10px] text-slate-400">Revenue QoQ</div>
                      <div className="text-sm font-bold text-token-cyan mt-0.5">
                        +{data.fundamentals.revenue_growth_qoq?.toFixed(1) || '0.0'}%
                      </div>
                    </div>
                    <div className="p-2 rounded bg-surface border border-white/[0.04]">
                      <div className="text-[10px] text-slate-400">EPS Surprise</div>
                      <div className="text-sm font-bold text-token-violet mt-0.5">
                        +{data.fundamentals.eps_surprise_pct?.toFixed(1) || '0.0'}%
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
