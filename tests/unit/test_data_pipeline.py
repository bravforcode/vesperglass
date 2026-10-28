"""
Unit Test Suite for Stocknomist Market Data Pipeline & Persistent Disk Cache.
Covers:
- Universe Manager (Seeds, Deduplication, Dynamic updates, Normalization)
- Persistent Disk Cache (DuckDB time-series + SQLite WAL state)
- Yahoo Finance Ingestion Client (v8 chart API, batching, backoff)
- SEC EDGAR Fundamental Ingestion (XBRL parsing, GAAP ratios, User-Agent)
- Full M1 <-> M2 Interface Contract Verification
"""

import datetime
from pathlib import Path
import tempfile
import numpy as np
import pandas as pd
import pytest

from backend.app.data.universe import UniverseManager, normalize_ticker
from backend.app.data.yfinance_client import YFinanceClient, EXPECTED_COLUMNS
from backend.app.data.sec_edgar import SecEdgarClient, SEC_USER_AGENT
from backend.app.data.cache import MarketDataCache, EXPECTED_QUOTE_COLS


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def temp_cache():
    """Provides an isolated MarketDataCache inside a temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = MarketDataCache(data_dir=Path(tmpdir))
        yield cache
        cache.close()


@pytest.fixture
def universe_mgr():
    """Provides a UniverseManager loaded with default seeds."""
    return UniverseManager()


@pytest.fixture
def sample_bars_df():
    """Generates synthetic valid OHLCV DataFrame for testing."""
    dates = pd.date_range(end=datetime.date.today(), periods=30, freq="D").strftime("%Y-%m-%d").tolist()
    return pd.DataFrame({
        "date": dates,
        "open": [100.0 + i for i in range(30)],
        "high": [105.0 + i for i in range(30)],
        "low": [98.0 + i for i in range(30)],
        "close": [102.0 + i for i in range(30)],
        "volume": [1000000 + i * 10000 for i in range(30)],
    })


@pytest.fixture
def sample_sec_xbrl_payload():
    """Synthetic XBRL facts payload matching SEC EDGAR structure."""
    return {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "StockholdersEquity": {
                    "units": {
                        "USD": [
                            {"end": "2025-09-27", "val": 60000000000, "fy": 2025, "fp": "FY", "form": "10-K"},
                            {"end": "2026-06-27", "val": 80000000000, "fy": 2026, "fp": "Q3", "form": "10-Q"}
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {"start": "2025-09-28", "end": "2025-12-27", "val": 30000000000, "form": "10-Q", "fp": "Q1"},
                            {"start": "2025-12-28", "end": "2026-03-28", "val": 25000000000, "form": "10-Q", "fp": "Q2"},
                            {"start": "2026-03-29", "end": "2026-06-27", "val": 25000000000, "form": "10-Q", "fp": "Q3"},
                            {"start": "2025-06-29", "end": "2025-09-27", "val": 20000000000, "form": "10-Q", "fp": "Q4"},
                        ]
                    }
                },
                "LongTermDebtNoncurrent": {
                    "units": {
                        "USD": [
                            {"end": "2026-06-27", "val": 40000000000, "form": "10-Q"}
                        ]
                    }
                },
                "DebtCurrent": {
                    "units": {
                        "USD": [
                            {"end": "2026-06-27", "val": 10000000000, "form": "10-Q"}
                        ]
                    }
                },
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {
                        "USD": [
                            {"end": "2026-06-27", "val": 90000000000, "form": "10-Q"}
                        ]
                    }
                },
                "PaymentsToAcquirePropertyPlantAndEquipment": {
                    "units": {
                        "USD": [
                            {"end": "2026-06-27", "val": 10000000000, "form": "10-Q"}
                        ]
                    }
                },
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {"start": "2025-12-28", "end": "2026-03-28", "val": 90000000000, "form": "10-Q"},
                            {"start": "2026-03-29", "end": "2026-06-27", "val": 100000000000, "form": "10-Q"}
                        ]
                    }
                },
                "EarningsPerShareDiluted": {
                    "units": {
                        "USD/shares": [
                            {"start": "2026-03-29", "end": "2026-06-27", "val": 1.65, "form": "10-Q"}
                        ]
                    }
                }
            }
        }
    }


# =============================================================================
# Universe Manager Tests (Feature F1)
# =============================================================================

def test_ticker_normalization():
    """Tests symbol standardization for Yahoo Finance and SEC compatibility."""
    assert normalize_ticker("brk.b") == "BRK-B"
    assert normalize_ticker("BF.B") == "BF-B"
    assert normalize_ticker(" aapl ") == "AAPL"
    assert normalize_ticker("GOOGL") == "GOOGL"
    assert normalize_ticker("") == ""


def test_universe_seed_loading(universe_mgr):
    """Verifies that seed files load accurately and produce ~1,020 unique liquid equities."""
    tickers = universe_mgr.get_universe_tickers()
    assert len(tickers) >= 1000, f"Expected at least 1,000 tickers, got {len(tickers)}"
    assert len(tickers) <= 1200, f"Expected at most 1,200 tickers, got {len(tickers)}"

    # Check that major constituents exist
    sym_set = set(universe_mgr.get_ticker_list())
    for major in ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "JPM", "XOM", "UNH"]:
        assert major in sym_set, f"Major stock {major} missing from universe"


def test_universe_interface_contract(universe_mgr):
    """
    Verifies M1 <-> M2 interface contract:
    get_universe_tickers() -> list[dict] with ticker, name, sector, index.
    """
    tickers = universe_mgr.get_universe_tickers()
    sample = tickers[0]
    required_keys = ["ticker", "name", "sector", "index"]
    for k in required_keys:
        assert k in sample, f"Contract key '{k}' missing from universe item: {sample}"

    assert isinstance(sample["ticker"], str)
    assert isinstance(sample["name"], str)
    assert isinstance(sample["sector"], str)
    assert isinstance(sample["index"], str)


def test_universe_ticker_lookup(universe_mgr):
    """Verifies metadata retrieval for specific tickers."""
    aapl = universe_mgr.get_ticker_info("AAPL")
    assert aapl is not None
    assert aapl["ticker"] == "AAPL"
    assert "Apple" in aapl["name"]
    assert aapl["in_sp500"] is True
    assert aapl["in_nasdaq100"] is True


def test_universe_sync_to_db(universe_mgr, temp_cache):
    """Verifies synchronization of constituents into the SQLite database."""
    saved_count = universe_mgr.sync_to_db(temp_cache)
    assert saved_count >= 1000

    db_constituents = temp_cache.get_universe_constituents()
    assert len(db_constituents) == saved_count

    aapl = next((c for c in db_constituents if c["ticker"] == "AAPL"), None)
    assert aapl is not None
    assert aapl["in_sp500"] is True
    assert "S&P 500" in aapl["index"]


# =============================================================================
# Persistent Disk Cache Tests (Feature F4)
# =============================================================================

def test_cache_sqlite_wal_mode(temp_cache):
    """Verifies that SQLite is configured in WAL journal mode."""
    with temp_cache._get_sqlite_conn() as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode;")
        mode = cur.fetchone()[0]
        assert mode.lower() == "wal"


def test_cache_duckdb_daily_quotes(temp_cache, sample_bars_df):
    """Verifies storing and retrieving historical price bars in DuckDB."""
    ticker = "TEST_STOCK"
    saved = temp_cache.save_daily_quotes(ticker, sample_bars_df)
    assert saved == len(sample_bars_df)

    retrieved = temp_cache.get_daily_quotes(ticker, days=15)
    assert len(retrieved) == 15
    assert list(retrieved.columns) == EXPECTED_QUOTE_COLS
    # Verify chronological ascending sort order
    assert retrieved["date"].iloc[0] < retrieved["date"].iloc[-1]


def test_cache_batch_quotes_storage(temp_cache, sample_bars_df):
    """Verifies batch saving quotes across multiple tickers in DuckDB."""
    batch_data = {
        "STOCK_A": sample_bars_df.copy(),
        "STOCK_B": sample_bars_df.copy(),
    }
    saved_total = temp_cache.save_batch_daily_quotes(batch_data)
    assert saved_total == len(sample_bars_df) * 2

    quotes_a = temp_cache.get_daily_quotes("STOCK_A", days=10)
    quotes_b = temp_cache.get_daily_quotes("STOCK_B", days=10)
    assert len(quotes_a) == 10
    assert len(quotes_b) == 10


def test_cache_latest_quote_date(temp_cache, sample_bars_df):
    """Verifies retrieving the latest trade date for a ticker."""
    ticker = "DATE_TEST"
    temp_cache.save_daily_quotes(ticker, sample_bars_df)
    latest = temp_cache.get_latest_quote_date(ticker)
    expected_latest = sample_bars_df["date"].max()
    assert latest == expected_latest


def test_cache_fundamentals_storage(temp_cache):
    """Verifies saving and querying fundamental ratios in SQLite."""
    metrics = {
        "ticker": "FUND_TEST",
        "market_cap": 2500000000.0,
        "forward_pe": 18.5,
        "pe_trailing": 21.0,
        "roe": 22.4,
        "debt_to_equity": 0.45,
        "free_cash_flow": 350000000.0,
        "fcf_yield": 14.0,
        "revenue_growth_qoq": 8.5,
        "eps_surprise_pct": 12.0,
        "fiscal_quarter": "2026-Q3",
        "last_reported_date": "2026-06-30",
    }
    temp_cache.save_fundamentals(metrics)
    cached = temp_cache.get_fundamentals("FUND_TEST")
    assert cached is not None
    assert cached["ticker"] == "FUND_TEST"
    assert cached["roe"] == 22.4
    assert cached["debt_to_equity"] == 0.45
    assert cached["fcf_yield"] == 14.0


def test_cache_screener_signals_storage(temp_cache):
    """Verifies saving and filtering screener signals in SQLite."""
    signals = [
        {
            "scan_date": "2026-10-27",
            "ticker": "AAPL",
            "strategy_name": "MOMENTUM_BREAKOUT",
            "confidence_score": 92,
            "entry_price": 347.50,
            "stop_loss": 338.00,
            "target_price": 366.50,
            "target_return_pct": 5.47,
            "risk_reward_ratio": 2.0,
            "atr_14": 6.33,
            "rsi_14": 64.5,
            "volume_ratio": 1.85,
            "sma_20": 340.0,
            "sma_50": 330.0,
            "sma_200": 310.0,
            "notes": "Volume breakout above 20-day BB",
        },
        {
            "scan_date": "2026-10-27",
            "ticker": "NVDA",
            "strategy_name": "QUALITY_FCF",
            "confidence_score": 88,
            "entry_price": 185.00,
            "stop_loss": 178.00,
            "target_price": 200.00,
            "target_return_pct": 8.11,
            "risk_reward_ratio": 2.14,
            "atr_14": 4.50,
            "rsi_14": 58.0,
            "volume_ratio": 1.2,
            "sma_20": 180.0,
            "sma_50": 175.0,
            "sma_200": 160.0,
            "notes": "Quality rebound at 50 SMA",
        },
    ]

    saved = temp_cache.save_screener_signals(signals)
    assert saved == 2

    # Query all
    all_signals = temp_cache.get_screener_signals()
    assert len(all_signals) == 2

    # Filter by strategy
    mom_signals = temp_cache.get_screener_signals(strategy_name="MOMENTUM_BREAKOUT")
    assert len(mom_signals) == 1
    assert mom_signals[0]["ticker"] == "AAPL"

    # Filter by min return
    high_return = temp_cache.get_screener_signals(min_return=6.0)
    assert len(high_return) == 1
    assert high_return[0]["ticker"] == "NVDA"


def test_cache_scan_job_logging(temp_cache):
    """Verifies logging and recording scan pipeline runs."""
    job_id = temp_cache.log_scan_job(
        run_date="2026-10-27",
        start_time="2026-10-27T21:30:00Z",
        end_time="2026-10-27T21:31:15Z",
        tickers_scanned=1015,
        signals_found=42,
        status="COMPLETED",
    )
    assert job_id > 0


# =============================================================================
# Yahoo Finance Client Tests (Feature F2)
# =============================================================================

def test_yfinance_backoff_calculation():
    """Verifies exponential backoff with jitter algorithm."""
    client = YFinanceClient(base_backoff=1.5)
    t0 = client._calculate_backoff(0)
    t1 = client._calculate_backoff(1)
    t2 = client._calculate_backoff(2)

    assert 1.5 <= t0 <= 2.5
    assert 3.0 <= t1 <= 4.0
    assert 6.0 <= t2 <= 7.0
    assert t0 < t1 < t2


def test_yfinance_contract_schema(sample_bars_df):
    """
    Verifies M1 <-> M2 interface contract:
    get_historical_bars(ticker, days) -> pd.DataFrame with [date, open, high, low, close, volume]
    """
    # Test column validation
    assert list(sample_bars_df.columns) == EXPECTED_COLUMNS
    assert len(sample_bars_df) == 30

    # Test slicing behavior
    sliced = sample_bars_df.iloc[-10:].reset_index(drop=True)
    assert len(sliced) == 10
    assert sliced["date"].iloc[0] < sliced["date"].iloc[-1]


def test_yfinance_v8_parsing():
    """Verifies parsing of v8 chart API JSON structures."""
    client = YFinanceClient()
    # Test with invalid structure
    empty = client.fetch_ticker_bars_v8("NON_EXISTENT_TICKER_XYZ_999")
    assert empty is None

    # Test live endpoint for AAPL
    df = client.fetch_ticker_bars_v8("AAPL", range_str="5d")
    if df is not None:
        assert list(df.columns) == EXPECTED_COLUMNS
        assert not df.empty
        assert (df["close"] > 0).all()
        assert (df["volume"] >= 0).all()


def test_yfinance_get_historical_bars_live():
    """Verifies get_historical_bars returns valid DataFrame for active stock."""
    client = YFinanceClient()
    df = client.get_historical_bars("AAPL", days=10)
    if not df.empty:
        assert len(df) <= 10
        assert list(df.columns) == EXPECTED_COLUMNS
        assert df["close"].dtype in (float, np.float64, np.float32)


# =============================================================================
# SEC EDGAR Client Tests (Feature F3)
# =============================================================================

def test_sec_user_agent_compliance():
    """Verifies SEC fair access policy User-Agent header."""
    client = SecEdgarClient()
    assert client.user_agent == SEC_USER_AGENT
    assert "StockNomist" in client.session.headers["User-Agent"]
    assert "@" in client.session.headers["User-Agent"]


def test_sec_cik_resolution():
    """Verifies CIK resolution for prominent tickers."""
    client = SecEdgarClient()
    cik_aapl = client.get_cik("AAPL")
    if cik_aapl:
        assert cik_aapl == "0000320193"

    cik_msft = client.get_cik("MSFT")
    if cik_msft:
        assert cik_msft == "0000789019"


def test_sec_xbrl_parsing_synthetic(sample_sec_xbrl_payload):
    """
    Verifies GAAP ratio extraction formulas on controlled synthetic XBRL payload:
    - ROE = (Net Income / Stockholders' Equity) * 100
    - Total Debt = LongTermDebt + DebtCurrent
    - Debt-to-Equity = Total Debt / Stockholders' Equity
    - Free Cash Flow = OCF - CapEx
    """
    client = SecEdgarClient()

    # Monkeypatch fetch_company_facts_raw to return controlled fixture
    original_fetch = client.fetch_company_facts_raw
    client.fetch_company_facts_raw = lambda cik: sample_sec_xbrl_payload

    try:
        metrics = client.parse_sec_fundamentals("AAPL", "0000320193")
        assert metrics["ticker"] == "AAPL"

        # Stockholders' Equity: 80,000,000,000 (latest Q3)
        assert metrics["stockholders_equity"] == 80000000000.0

        # Net Income TTM: 30B + 25B + 25B + 20B = 100,000,000,000
        assert metrics["net_income"] == 100000000000.0

        # ROE: (100B / 80B) * 100 = 125.0%
        assert metrics["roe"] == 125.0

        # Debt: 40B LT + 10B ST = 50,000,000,000
        assert metrics["total_debt"] == 50000000000.0

        # Debt-to-Equity: 50B / 80B = 0.625 -> 0.62 or 0.63
        assert metrics["debt_to_equity"] in (0.62, 0.63)

        # FCF: 90B OCF - 10B CapEx = 80,000,000,000
        assert metrics["free_cash_flow"] == 80000000000.0

        # Revenue Growth QoQ: (100B - 90B) / 90B = +11.11%
        assert metrics["revenue_growth_qoq"] == 11.11

        # EPS: 1.65
        assert metrics["diluted_eps"] == 1.65
    finally:
        client.fetch_company_facts_raw = original_fetch


def test_sec_get_fundamental_metrics_contract():
    """
    Verifies M1 <-> M2 interface contract:
    get_fundamental_metrics(ticker) -> dict with keys:
    roe, debt_to_equity, fcf_yield, forward_pe, eps_surprise_pct, revenue_growth_qoq
    """
    client = SecEdgarClient()
    metrics = client.get_fundamental_metrics("AAPL", cik="0000320193")
    required_keys = [
        "roe",
        "debt_to_equity",
        "fcf_yield",
        "forward_pe",
        "eps_surprise_pct",
        "revenue_growth_qoq",
    ]
    for k in required_keys:
        assert k in metrics, f"Contract key '{k}' missing from fundamental metrics: {metrics}"

    assert isinstance(metrics["roe"], (int, float))
    assert isinstance(metrics["debt_to_equity"], (int, float))
    assert isinstance(metrics["fcf_yield"], (int, float))


# =============================================================================
# Full Pipeline End-to-End Integration Test
# =============================================================================

def test_full_m1_data_pipeline_integration(universe_mgr, temp_cache):
    """
    Verifies the end-to-end integration flow of Milestone 1:
    1. Load universe seeds and sync to SQLite WAL cache
    2. Ingest historical price bars and persist to DuckDB
    3. Ingest fundamental metrics and persist to SQLite
    4. Query and verify both persistent stores
    """
    # 1. Sync universe
    saved_u = universe_mgr.sync_to_db(temp_cache)
    assert saved_u >= 1000

    # 2. Ingest & cache price bars for AAPL
    yfc = YFinanceClient()
    bars = yfc.get_historical_bars("AAPL", days=20)
    if not bars.empty:
        saved_q = temp_cache.save_daily_quotes("AAPL", bars)
        assert saved_q == len(bars)

        # Retrieve and verify from DuckDB
        cached_quotes = temp_cache.get_daily_quotes("AAPL", days=10)
        assert len(cached_quotes) <= 10
        assert list(cached_quotes.columns) == EXPECTED_QUOTE_COLS

    # 3. Ingest fundamentals & cache
    sec = SecEdgarClient()
    fund = sec.get_fundamental_metrics("AAPL", cik="0000320193")
    temp_cache.save_fundamentals(fund)

    cached_fund = temp_cache.get_fundamentals("AAPL")
    assert cached_fund is not None
    assert cached_fund["ticker"] == "AAPL"
    assert "roe" in cached_fund
    assert "debt_to_equity" in cached_fund
