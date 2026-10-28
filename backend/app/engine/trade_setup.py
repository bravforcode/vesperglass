"""
Trade Setup & Risk-Reward Modeling Engine for Stocknomist (Feature F7).
Generates explicit trade parameters:
- Entry Price (current close or confirmation trigger)
- ATR-based Stop-Loss (Entry - 1.5 * ATR(14) cushion)
- Target Price (bounded within 3% - 10% monthly swing target)
- Risk:Reward Ratio (minimum 1:2.0 guaranteed)
"""

from dataclasses import dataclass
import math
from typing import Any, Dict, Optional


@dataclass
class TradeSetup:
    """Explicit quantitative trade setup matching API and screener specifications."""
    entry_price: float
    stop_loss: float
    target_price: float
    target_return_pct: float
    risk_reward_ratio: float
    atr_14: float
    risk_per_share: float
    reward_per_share: float
    is_valid: bool

    def to_dict(self) -> Dict[str, Any]:
        """Serializes setup to standard API dictionary."""
        return {
            "entry_price": round(self.entry_price, 2),
            "stop_loss": round(self.stop_loss, 2),
            "target_price": round(self.target_price, 2),
            "target_return_pct": round(self.target_return_pct, 2),
            "risk_reward_ratio": round(self.risk_reward_ratio, 2),
            "atr_14": round(self.atr_14, 2),
            "risk_per_share": round(self.risk_per_share, 2),
            "reward_per_share": round(self.reward_per_share, 2),
            "is_valid": self.is_valid,
        }


def generate_trade_setup(
    entry_price: float,
    atr_14: float,
    strategy_name: Optional[str] = None,
    min_return_pct: float = 3.0,
    max_return_pct: float = 10.0,
    min_rr_ratio: float = 2.0,
    recent_swing_low: Optional[float] = None,
    bb_middle: Optional[float] = None,
) -> TradeSetup:
    """
    Computes mathematically rigorous trade execution levels for swing trading.
    
    Guarantees:
      1. Stop-Loss is positioned below entry using ATR volatility cushion.
      2. Target Return is bounded between min_return_pct (3.0%) and max_return_pct (10.0%).
      3. Risk:Reward ratio strictly enforces minimum 1:2.0.
      4. Invalidates trade if constraints cannot be satisfied.
    """
    if (
        entry_price is None
        or atr_14 is None
        or not math.isfinite(entry_price)
        or not math.isfinite(atr_14)
        or entry_price <= 0.0
        or atr_14 <= 0.0
    ):
        return TradeSetup(
            entry_price=0.0,
            stop_loss=0.0,
            target_price=0.0,
            target_return_pct=0.0,
            risk_reward_ratio=0.0,
            atr_14=0.0,
            risk_per_share=0.0,
            reward_per_share=0.0,
            is_valid=False,
        )

    if recent_swing_low is not None and (not math.isfinite(recent_swing_low) or recent_swing_low <= 0.0):
        recent_swing_low = None
    if bb_middle is not None and (not math.isfinite(bb_middle) or bb_middle <= 0.0):
        bb_middle = None

    clean_strat = (strategy_name or "MOMENTUM_BREAKOUT").upper()

    # 1. Determine Stop-Loss Cushion
    if clean_strat == "MEAN_REVERSION":
        # Oversold bounce uses 1.25x ATR or swing low
        stop_cushion = 1.25 * atr_14
        if recent_swing_low and 0 < recent_swing_low < entry_price:
            candidate_stop = recent_swing_low - (0.5 * atr_14)
            stop_loss = max(candidate_stop, entry_price - stop_cushion)
        else:
            stop_loss = entry_price - stop_cushion
    elif clean_strat == "QUALITY_FCF":
        # Quality FCF: 1.5x ATR or swing low - 0.5x ATR
        stop_cushion = 1.5 * atr_14
        if recent_swing_low and 0 < recent_swing_low < entry_price:
            stop_loss = min(recent_swing_low - (0.5 * atr_14), entry_price - stop_cushion)
        else:
            stop_loss = entry_price - stop_cushion
    else:
        # Default & Momentum Breakout: 1.5x ATR
        stop_cushion = 1.5 * atr_14
        stop_loss = entry_price - stop_cushion

    # Ensure stop loss is strictly positive and below entry
    if stop_loss <= 0.0:
        stop_loss = entry_price * 0.95  # Fallback to 5% stop if ATR is huge

    risk = entry_price - stop_loss
    if risk <= 0.0:
        return TradeSetup(
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=entry_price,
            target_return_pct=0.0,
            risk_reward_ratio=0.0,
            atr_14=atr_14,
            risk_per_share=0.0,
            reward_per_share=0.0,
            is_valid=False,
        )

    # 2. Determine Initial Target Price based on strategy
    min_reward_required = risk * min_rr_ratio

    if clean_strat == "MOMENTUM_BREAKOUT":
        # Target = entry + max(3.0 * ATR, entry * 0.06)
        raw_target = entry_price + max(3.0 * atr_14, entry_price * 0.06)
    elif clean_strat == "EARNINGS_PEAD":
        # Target = entry + max(2.2 * risk, entry * 0.075)
        raw_target = entry_price + max(min_rr_ratio * 1.1 * risk, entry_price * 0.075)
    elif clean_strat == "MEAN_REVERSION":
        # Target = 20 SMA mean, but must satisfy min RR
        if bb_middle and bb_middle > entry_price:
            raw_target = max(bb_middle, entry_price + min_reward_required)
        else:
            raw_target = entry_price + min_reward_required
    elif clean_strat == "QUALITY_FCF":
        # Target = entry * 1.08 (+8%) or 2.5x risk
        raw_target = entry_price + max(2.5 * risk, entry_price * 0.08)
    else:
        raw_target = entry_price + min_reward_required

    # 3. Enforce Target Return Bounds (3.0% to 10.0%) and min R:R
    # Ensure raw_target at least meets min_reward_required
    target_price = max(raw_target, entry_price + min_reward_required)
    target_return_pct = ((target_price - entry_price) / entry_price) * 100.0

    # If target_return_pct exceeds max_return_pct (10%), clamp to 10%
    if target_return_pct > max_return_pct:
        target_price = entry_price * (1.0 + (max_return_pct / 100.0))
        target_return_pct = max_return_pct

    # If target_return_pct is below min_return_pct (3%), elevate to 3%
    if target_return_pct < min_return_pct:
        target_price = entry_price * (1.0 + (min_return_pct / 100.0))
        target_return_pct = min_return_pct

    reward = target_price - entry_price
    rr_ratio = reward / risk

    # 4. Final Validation: Does it satisfy min R:R after clamping?
    # If the clamped target does not provide at least min_rr_ratio (e.g. 2.0),
    # adjust the stop-loss upward slightly if feasible, or mark invalid
    is_valid = True
    if rr_ratio < min_rr_ratio:
        # Check if tightening stop to satisfy RR keeps stop >= entry - 1.0 * ATR
        tightened_risk = reward / min_rr_ratio
        if tightened_risk >= 0.75 * atr_14 and (entry_price - tightened_risk) > 0:
            stop_loss = entry_price - tightened_risk
            risk = tightened_risk
            rr_ratio = reward / risk
        else:
            is_valid = False

    return TradeSetup(
        entry_price=round(entry_price, 4),
        stop_loss=round(stop_loss, 4),
        target_price=round(target_price, 4),
        target_return_pct=round(target_return_pct, 2),
        risk_reward_ratio=round(rr_ratio, 2),
        atr_14=round(atr_14, 4),
        risk_per_share=round(risk, 4),
        reward_per_share=round(reward, 4),
        is_valid=is_valid,
    )
