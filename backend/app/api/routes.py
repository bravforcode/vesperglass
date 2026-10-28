"""
FastAPI Route Handlers for Stocknomist API.
Provides REST endpoints for:
- Health check probes (/health, /api/health)
- Market Pulse telemetry & index cards (/api/market-pulse)
- Multi-criteria screener candidate queries (/api/screen)
- Comprehensive stock deep-dive profile (/api/stock/{ticker})
- Universe constituents & scan refresh trigger
"""

from datetime import datetime, timezone
import logging
import re
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query

from backend.app.api.screener_service import ScreenerService
from backend.app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()
_screener_service: Optional[ScreenerService] = None


def get_screener_service() -> ScreenerService:
    """Singleton getter for ScreenerService."""
    global _screener_service
    if _screener_service is None:
        _screener_service = ScreenerService()
    return _screener_service


# -----------------------------------------------------------------------------
# Health Check Endpoints
# -----------------------------------------------------------------------------

@router.api_route("/health", methods=["GET", "HEAD"])
def health_check() -> Dict[str, Any]:
    """
    Health check probe for Docker HEALTHCHECK and Caddy uptime monitors.
    Returns status, version, and ISO cache timestamp.
    """
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "cache_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# -----------------------------------------------------------------------------
# Market Pulse Endpoint
# -----------------------------------------------------------------------------

@router.get("/market-pulse")
def get_market_pulse() -> Dict[str, Any]:
    """
    Returns live market indices telemetry and aggregate screener statistics.
    S&P 500 (SPY), Nasdaq 100 (QQQ), VIX, candidate breakdown, top opportunity, and win rate.
    """
    service = get_screener_service()
    return service.get_market_pulse()


# -----------------------------------------------------------------------------
# Screener Candidate List Endpoint
# -----------------------------------------------------------------------------

@router.get("/screen")
def screen_stocks(
    strategy: Optional[str] = Query(None, description="Filter by strategy (momentum_breakout, earnings_pead, oversold_bounce, quality_fcf, or all)"),
    sector: Optional[str] = Query(None, description="Filter by GICS sector name"),
    min_return: float = Query(0.0, description="Minimum expected target return % (e.g. 3.0, 5.0, 10.0)"),
    market_cap: Optional[str] = Query(None, description="Filter by market cap tier (mega, large, mid, or all)"),
    min_rr: float = Query(2.0, description="Minimum Risk:Reward ratio (default 2.0)"),
    search: Optional[str] = Query(None, description="Search by ticker symbol or company name"),
    sort_by: str = Query("confidence_score", description="Sort field: confidence_score, target_return_pct, risk_reward_ratio, price, ticker"),
    sort_dir: str = Query("desc", description="Sort direction: asc or desc"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of candidates to return"),
) -> List[Dict[str, Any]]:
    """
    Queries swing opportunity candidates matching multi-criteria filters.
    Includes trade setup, 5-axis factor scores, upcoming catalysts, and 7-day sparkline.
    """
    service = get_screener_service()
    return service.screen_candidates(
        strategy=strategy,
        sector=sector,
        min_return=min_return,
        market_cap=market_cap,
        min_rr=min_rr,
        search=search,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
    )


# -----------------------------------------------------------------------------
# Stock Deep-Dive Detail Endpoint
# -----------------------------------------------------------------------------

TICKER_REGEX = re.compile(r"^[A-Za-z0-9]{1,6}(?:[-.][A-Za-z0-9]{1,4})?$")


@router.get("/stock/{ticker}")
def get_stock_detail(ticker: str) -> Dict[str, Any]:
    """
    Returns complete quantitative profile for a ticker:
    - 252-day OHLCV candlestick series + volume histogram
    - Trade Execution levels (Entry, Target, Stop-Loss)
    - 5-Axis Factor Radar scores vs Sector benchmark
    - Upcoming Catalyst milestone timeline
    - Algorithmic Strategy Criteria checklist
    - Position sizing calculation for $15k / 2% risk account
    """
    if not ticker or not TICKER_REGEX.match(ticker.strip()):
        raise HTTPException(
            status_code=404,
            detail=f"Stock ticker '{ticker}' not found in active universe",
        )
    service = get_screener_service()
    detail = service.get_stock_detail(ticker)
    if not detail:
        raise HTTPException(
            status_code=404,
            detail=f"Stock ticker '{ticker.upper()}' not found in active universe",
        )
    return detail


# -----------------------------------------------------------------------------
# Universe & Scan Utilities
# -----------------------------------------------------------------------------

@router.get("/universe")
def get_universe_constituents(
    active_only: bool = Query(True, description="Filter to active constituents only"),
) -> List[Dict[str, Any]]:
    """Returns list of all universe constituents in S&P 500, Nasdaq 100, Russell 1000."""
    service = get_screener_service()
    return service.cache.get_universe_constituents(active_only=active_only)


@router.post("/scan/refresh")
def trigger_scan_refresh() -> Dict[str, Any]:
    """Manually re-evaluates screener candidates and refreshes cache."""
    service = get_screener_service()
    pulse = service.get_market_pulse()
    return {
        "status": "success",
        "message": "Scan refresh completed",
        "pulse": pulse,
    }
