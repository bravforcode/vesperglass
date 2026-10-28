export interface TradeSetup {
  entry_price: number;
  stop_loss: number;
  target_price: number;
  target_return_pct: number;
  risk_reward_ratio: number;
  atr_14: number;
  risk_per_share: number;
  reward_per_share: number;
  shares?: number;
  risk_amount?: number;
  horizon_days?: string;
  is_valid: boolean;
}

export interface FactorScores {
  momentum: number;
  value: number;
  quality: number;
  growth: number;
  volatility: number;
}

export interface RadarItem {
  factor: string;
  stockScore: number;
  sectorAvg: number;
}

export interface CatalystEvent {
  type: string;
  date: string;
  title?: string;
  label: string;
  countdown: string;
  description?: string;
}

export interface StrategyChecklistItem {
  criterion: string;
  passed: boolean;
  detail: string;
}

export interface Candidate {
  ticker: string;
  name: string;
  sector: string;
  price: number;
  change_24h_pct: number;
  strategies: string[];
  confidence_score: number;
  market_cap: number;
  market_cap_tier: 'Mega' | 'Large' | 'Mid' | string;
  setup: TradeSetup;
  factor_scores: FactorScores;
  catalysts: CatalystEvent[];
  sparkline: number[];
}

export interface CandleBar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface VolumeBar {
  time: string;
  value: number;
  color: string;
}

export interface StockDetail extends Candidate {
  candles: CandleBar[];
  volumes: VolumeBar[];
  indicators: {
    sma_20: number;
    sma_50: number;
    sma_200: number;
    rsi_14: number;
    atr_14: number;
    bb_upper: number;
    bb_middle: number;
    bb_lower: number;
    bb_width_pct: number;
    volume_ratio: number;
    macd: number;
    macd_signal: number;
    macd_hist: number;
  };
  fundamentals: {
    market_cap: number;
    roe: number;
    debt_to_equity: number;
    fcf_yield: number;
    forward_pe: number;
    revenue_growth_qoq: number;
    eps_surprise_pct: number;
    fiscal_quarter?: string;
    last_reported_date?: string;
  };
  radar_comparison: RadarItem[];
  strategy_checklist: StrategyChecklistItem[];
}

export interface MarketPulse {
  indices: Record<string, { name?: string; price: number; change_pct: number }>;
  scan_status: string;
  stocks_scanned: number;
  candidates_found: number;
  top_opportunity: {
    ticker: string;
    target_return_pct: number;
    risk_reward_ratio: number;
    strategy: string;
  };
  active_signals: {
    total: number;
    momentum: number;
    earnings: number;
    oversold: number;
    quality: number;
  };
  expected_return_avg: number;
  win_rate_pct: number;
  last_scan_time?: string;
}
