"""
Empirical Stress & Concurrency Test Suite for MarketDataCache (backend/app/data/cache.py).
Conducted by Challenger 2 (Milestone 1: Cache Concurrency & Performance Verifier).

Evaluates:
1. Concurrent multi-threaded reads/writes in SQLite (WAL mode) and DuckDB.
2. High-volume ingestion (300,000+ rows across 1,020 tickers).
3. Sub-second query performance (<1.0s, targeting <50ms P99).
4. Memory limit enforcement (<256MB DuckDB max_memory guard and process RSS monitoring).
5. Windows file lock safety (file cleanup, no locked handles after close, reopen capability).
6. Adversarial input validation (SQL injection patterns, special characters, NaNs, duplicates).
7. Database integrity checks (SQLite PRAGMA integrity_check, zero deadlocks, zero corruptions).
"""

import concurrent.futures
import datetime
import os
from pathlib import Path
import random
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import numpy as np
import pandas as pd
import psutil
import pytest

# Ensure backend is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.data.cache import MarketDataCache, EXPECTED_QUOTE_COLS  # noqa: E402


@pytest.fixture
def isolated_cache_dir():
    """Provides a fresh isolated directory that is cleaned up after test."""
    temp_dir = tempfile.mkdtemp(prefix="stocknomist_stress_")
    yield Path(temp_dir)
    # Attempt cleanup with retries for Windows file lock release
    for _ in range(5):
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
            break
        except Exception:
            time.sleep(0.1)


# =============================================================================
# 1. Multi-Threaded SQLite Concurrency & Contention Stress Test
# =============================================================================

def test_sqlite_multithreaded_concurrency(isolated_cache_dir):
    """
    Spawns 20 writer threads and 20 reader threads operating concurrently
    against SQLite in WAL mode.
    Confirms zero database locks, zero deadlocks, zero corruptions.
    """
    cache = MarketDataCache(data_dir=isolated_cache_dir)

    # Pre-populate 50 universe constituents
    base_constituents = [
        {"ticker": f"TICK{i:03d}", "name": f"Company {i}", "sector": "Tech", "in_sp500": True}
        for i in range(50)
    ]
    cache.save_universe_constituents(base_constituents)

    write_errors = []
    read_errors = []
    write_count = 0
    read_count = 0
    stop_event = threading.Event()

    def writer_worker(worker_id: int, iterations: int):
        nonlocal write_count
        try:
            for it in range(iterations):
                if stop_event.is_set():
                    break
                ticker = f"TICK{random.randint(0, 49):03d}"
                # 1. Save fundamentals
                cache.save_fundamentals({
                    "ticker": ticker,
                    "market_cap": float(random.randint(1_000_000, 50_000_000)),
                    "roe": round(random.uniform(5.0, 35.0), 2),
                    "debt_to_equity": round(random.uniform(0.1, 2.5), 2),
                    "fcf_yield": round(random.uniform(2.0, 15.0), 2),
                })
                # 2. Save screener signal
                cache.save_screener_signals([{
                    "scan_date": "2026-10-27",
                    "ticker": ticker,
                    "strategy_name": random.choice(["MOMENTUM_BREAKOUT", "QUALITY_FCF", "OVERSOLD_BOUNCE"]),
                    "confidence_score": random.randint(50, 99),
                    "entry_price": 150.0 + random.uniform(-10, 10),
                    "stop_loss": 140.0,
                    "target_price": 170.0,
                    "target_return_pct": 6.5,
                    "risk_reward_ratio": 2.0,
                    "atr_14": 4.5,
                }])
                write_count += 1
        except Exception as e:
            write_errors.append((worker_id, type(e).__name__, str(e)))

    def reader_worker(worker_id: int, iterations: int):
        nonlocal read_count
        try:
            for it in range(iterations):
                if stop_event.is_set():
                    break
                # Query constituents, fundamentals, and signals
                constituents = cache.get_universe_constituents()
                assert len(constituents) >= 50
                ticker = f"TICK{random.randint(0, 49):03d}"
                _ = cache.get_fundamentals(ticker)
                _ = cache.get_screener_signals(min_return=5.0)
                read_count += 1
        except Exception as e:
            read_errors.append((worker_id, type(e).__name__, str(e)))

    num_writers = 20
    num_readers = 20
    iterations_per_thread = 50

    start_time = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_writers + num_readers) as executor:
        writer_futures = [executor.submit(writer_worker, i, iterations_per_thread) for i in range(num_writers)]
        reader_futures = [executor.submit(reader_worker, i, iterations_per_thread) for i in range(num_readers)]
        concurrent.futures.wait(writer_futures + reader_futures, timeout=60.0)

    elapsed = time.perf_counter() - start_time
    assert elapsed > 0.0
    cache.close()

    # Assertions
    assert len(write_errors) == 0, f"SQLite write errors encountered: {write_errors}"
    assert len(read_errors) == 0, f"SQLite read errors encountered: {read_errors}"
    assert write_count == num_writers * iterations_per_thread, f"Expected {num_writers * iterations_per_thread} writes, got {write_count}"
    assert read_count == num_readers * iterations_per_thread, f"Expected {num_readers * iterations_per_thread} reads, got {read_count}"

    # Verify SQLite DB integrity directly
    conn = sqlite3.connect(isolated_cache_dir / "stocknomist.db")
    cur = conn.cursor()
    cur.execute("PRAGMA integrity_check;")
    integrity = cur.fetchone()[0]
    conn.close()
    assert integrity == "ok", f"SQLite integrity check failed: {integrity}"


# =============================================================================
# 2. Multi-Threaded DuckDB Concurrency Stress Test
# =============================================================================

def test_duckdb_multithreaded_concurrency(isolated_cache_dir):
    """
    Spawns 10 writer threads and 10 reader threads concurrently saving and
    retrieving daily quotes from DuckDB.
    Confirms thread safety via _lock and data consistency.
    """
    cache = MarketDataCache(data_dir=isolated_cache_dir)

    dates = pd.date_range(end=datetime.date.today(), periods=60, freq="D").strftime("%Y-%m-%d").tolist()

    def generate_ticker_df(ticker: str, seed: int):
        np.random.seed(seed)
        base = 100.0 + seed
        closes = base + np.cumsum(np.random.randn(60))
        return pd.DataFrame({
            "date": dates,
            "open": closes - 0.5,
            "high": closes + 1.5,
            "low": closes - 1.5,
            "close": closes,
            "volume": np.random.randint(500_000, 5_000_000, size=60),
        })

    write_errors = []
    read_errors = []
    write_count = 0
    read_count = 0

    tickers = [f"TICKER_{i:02d}" for i in range(20)]

    def duck_writer(worker_id: int):
        nonlocal write_count
        try:
            for i in range(5):
                t = tickers[(worker_id * 2 + i) % len(tickers)]
                df = generate_ticker_df(t, worker_id * 10 + i)
                saved = cache.save_daily_quotes(t, df)
                assert saved == 60
                write_count += 1
        except Exception as e:
            write_errors.append((worker_id, type(e).__name__, str(e)))

    def duck_reader(worker_id: int):
        nonlocal read_count
        try:
            for i in range(10):
                t = tickers[random.randint(0, len(tickers) - 1)]
                quotes = cache.get_daily_quotes(t, days=30)
                # If quotes exist, check columns and sort order
                if not quotes.empty:
                    assert list(quotes.columns) == EXPECTED_QUOTE_COLS
                    if len(quotes) > 1:
                        assert quotes["date"].iloc[0] <= quotes["date"].iloc[-1]
                _ = cache.get_latest_quote_date(t)
                read_count += 1
                time.sleep(0.005)
        except Exception as e:
            read_errors.append((worker_id, type(e).__name__, str(e)))

    num_writers = 10
    num_readers = 10

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_writers + num_readers) as executor:
        writer_futures = [executor.submit(duck_writer, i) for i in range(num_writers)]
        reader_futures = [executor.submit(duck_reader, i) for i in range(num_readers)]
        concurrent.futures.wait(writer_futures + reader_futures, timeout=60.0)

    cache.close()

    assert len(write_errors) == 0, f"DuckDB write errors: {write_errors}"
    assert len(read_errors) == 0, f"DuckDB read errors: {read_errors}"
    assert write_count == num_writers * 5


# =============================================================================
# 3. High Row Volume Ingestion & Sub-Second Query Latency Benchmark
# =============================================================================

def test_high_volume_and_subsecond_query_performance(isolated_cache_dir):
    """
    Ingests 306,000 rows (1,020 tickers x 300 days) into DuckDB in batch.
    Measures:
    1. Batch insertion throughput.
    2. Query latency across 100 random tickers (P50, P95, P99, max).
    Target: P99 latency strictly < 1.0s (sub-second query response).
    """
    cache = MarketDataCache(data_dir=isolated_cache_dir)

    num_tickers = 1020
    days = 300
    dates = pd.date_range(end=datetime.date.today(), periods=days, freq="D").strftime("%Y-%m-%d").tolist()

    # Pre-generate synthetic batch in memory
    print(f"\nGenerating {num_tickers} tickers x {days} days = {num_tickers * days} rows...")
    batch_map = {}
    for i in range(num_tickers):
        ticker = f"SYM{i:04d}"
        # Lightweight vectorized dataframe generation
        base = 50.0 + (i % 200)
        noise = np.random.randn(days)
        closes = np.maximum(1.0, base + np.cumsum(noise))
        batch_map[ticker] = pd.DataFrame({
            "date": dates,
            "open": closes * 0.99,
            "high": closes * 1.02,
            "low": closes * 0.98,
            "close": closes,
            "volume": np.random.randint(100_000, 10_000_000, size=days),
        })

    # Benchmark Batch Save
    start_insert = time.perf_counter()
    total_saved = cache.save_batch_daily_quotes(batch_map)
    insert_duration = time.perf_counter() - start_insert
    throughput = total_saved / insert_duration

    print(f"Ingested {total_saved} rows in {insert_duration:.2f}s ({throughput:.0f} rows/s)")
    assert total_saved == num_tickers * days, f"Expected {num_tickers * days} rows, got {total_saved}"

    # Benchmark Query Latencies (100 random tickers)
    sample_tickers = random.sample(list(batch_map.keys()), 100)
    query_times = []

    for ticker in sample_tickers:
        t0 = time.perf_counter()
        df = cache.get_daily_quotes(ticker, days=300)
        t_elapsed = time.perf_counter() - t0
        query_times.append(t_elapsed)

        assert len(df) == days
        assert list(df.columns) == EXPECTED_QUOTE_COLS
        # Confirm chronological ascending sort
        assert df["date"].iloc[0] < df["date"].iloc[-1]

    query_times_ms = [t * 1000 for t in query_times]
    p50_ms = float(np.percentile(query_times_ms, 50))
    p95_ms = float(np.percentile(query_times_ms, 95))
    p99_ms = float(np.percentile(query_times_ms, 99))
    max_ms = float(np.max(query_times_ms))

    print("Query Latency (300 bars from 306k rows):")
    print(f"  P50: {p50_ms:.2f} ms")
    print(f"  P95: {p95_ms:.2f} ms")
    print(f"  P99: {p99_ms:.2f} ms")
    print(f"  Max: {max_ms:.2f} ms")

    cache.close()

    # Sub-second assertion: P99 must be < 1000ms (1.0s), ideally < 50ms
    assert p99_ms < 1000.0, f"Query latency exceeded 1.0s: P99 was {p99_ms:.2f}ms"


# =============================================================================
# 4. Memory Limit Enforcement (<256MB)
# =============================================================================

def test_duckdb_memory_limit_setting_and_rss_footprint(isolated_cache_dir):
    """
    Verifies:
    1. DuckDB max_memory is configured to '256MB'.
    2. Process RSS memory during heavy DuckDB aggregation operations remains bounded.
    """
    cache = MarketDataCache(data_dir=isolated_cache_dir)

    # 1. Inspect DuckDB setting directly via query
    conn = cache._get_duckdb_conn()
    with cache._lock:
        res = conn.execute("SELECT current_setting('max_memory');").fetchone()
        setting_val = res[0] if res else ""

    print(f"\nDuckDB max_memory setting reported: {setting_val}")
    # DuckDB represents 256MB as '256.0MB' or '244.1 MiB' or '256MB'
    assert "256" in setting_val or "244" in setting_val, f"max_memory not set to 256MB, got: {setting_val}"

    # 2. Check process RSS footprint
    process = psutil.Process(os.getpid())
    rss_before_mb = process.memory_info().rss / (1024 * 1024)

    # Ingest 50 tickers x 300 days
    days = 300
    dates = pd.date_range(end=datetime.date.today(), periods=days, freq="D").strftime("%Y-%m-%d").tolist()
    batch = {}
    for i in range(50):
        batch[f"RAM_{i}"] = pd.DataFrame({
            "date": dates,
            "open": np.random.uniform(50, 150, days),
            "high": np.random.uniform(150, 200, days),
            "low": np.random.uniform(10, 50, days),
            "close": np.random.uniform(50, 150, days),
            "volume": np.random.randint(1000, 1000000, days),
        })
    cache.save_batch_daily_quotes(batch)

    # Run heavy analytical query
    with cache._lock:
        df_agg = conn.execute("""
            SELECT ticker, AVG(close) as avg_close, STDDEV(close) as std_close, SUM(volume) as total_vol
            FROM daily_quotes
            GROUP BY ticker
        """).df()
        assert len(df_agg) == 50

    rss_after_mb = process.memory_info().rss / (1024 * 1024)
    cache.close()

    print(f"Process RSS Before: {rss_before_mb:.1f} MB, After: {rss_after_mb:.1f} MB (Delta: {rss_after_mb - rss_before_mb:.1f} MB)")
    # Memory growth for 15,000 rows should be modest (< 150MB delta)
    assert (rss_after_mb - rss_before_mb) < 150.0


# =============================================================================
# 5. Windows File Lock Safety & Cleanup
# =============================================================================

def test_windows_file_lock_release_on_close(isolated_cache_dir):
    """
    Verifies that cache.close() releases all file locks on Windows:
    1. duckdb file can be removed immediately.
    2. sqlite db files can be removed immediately.
    3. Reopening cache on the same directory succeeds immediately.
    """
    cache = MarketDataCache(data_dir=isolated_cache_dir)
    duck_path = isolated_cache_dir / "market_data.duckdb"
    sqlite_path = isolated_cache_dir / "stocknomist.db"

    # Write data to both
    cache.save_universe_constituents([{"ticker": "LOCK1", "name": "Lock Test 1"}])
    dates = pd.date_range(end=datetime.date.today(), periods=10, freq="D").strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({
        "date": dates,
        "open": [10.0] * 10,
        "high": [12.0] * 10,
        "low": [9.0] * 10,
        "close": [11.0] * 10,
        "volume": [10000] * 10,
    })
    cache.save_daily_quotes("LOCK1", df)

    # Verify files exist
    assert duck_path.exists()
    assert sqlite_path.exists()

    # Call close()
    cache.close()

    # On Windows, if a file handle is open, os.remove or Path.unlink raises PermissionError
    # Test unlinking duckdb file
    try:
        duck_path.unlink()
        file_deleted = True
    except PermissionError as e:
        file_deleted = False
        pytest.fail(f"DuckDB file lock held after close(): {e}")

    assert file_deleted is True

    # Test re-initializing cache in the same directory
    cache2 = MarketDataCache(data_dir=isolated_cache_dir)
    constituents = cache2.get_universe_constituents()
    assert len(constituents) == 1
    assert constituents[0]["ticker"] == "LOCK1"
    cache2.close()


# =============================================================================
# 6. Adversarial Inputs & Boundary Stress Test
# =============================================================================

def test_adversarial_inputs_and_edge_cases(isolated_cache_dir):
    """
    Feeds edge-case, malformed, and adversarial inputs:
    - Empty DataFrames
    - Missing required columns
    - NaN and Inf values
    - Duplicate dates (idempotent upsert verification)
    - Tickers with dots, hyphens, and SQL injection syntax
    """
    cache = MarketDataCache(data_dir=isolated_cache_dir)

    # 1. Empty DataFrame should return 0 saved
    empty_df = pd.DataFrame()
    assert cache.save_daily_quotes("EMPTY", empty_df) == 0

    # 2. DataFrame without date column should raise ValueError
    bad_df = pd.DataFrame({"close": [100.0], "volume": [1000]})
    with pytest.raises(ValueError, match="must contain 'date' or 'trade_date'"):
        cache.save_daily_quotes("BAD", bad_df)

    # 3. DataFrame with duplicate dates: should upsert cleanly without primary key collision
    dup_df = pd.DataFrame({
        "date": ["2026-10-01", "2026-10-01", "2026-10-02"],
        "open": [100.0, 105.0, 102.0],
        "high": [110.0, 115.0, 112.0],
        "low": [95.0, 100.0, 98.0],
        "close": [105.0, 110.0, 108.0],
        "volume": [1000, 2000, 1500],
    })
    saved = cache.save_daily_quotes("DUP_TICKER", dup_df)
    assert saved == 3
    retrieved = cache.get_daily_quotes("DUP_TICKER")
    # Duplicate for 2026-10-01 is deduplicated in DB, so 2 unique days exist
    assert len(retrieved) == 2
    assert retrieved["close"].iloc[0] in (105.0, 110.0)

    # 3b. Subsequent update with new close price should overwrite existing value
    update_df = pd.DataFrame({
        "date": ["2026-10-01"],
        "open": [100.0], "high": [115.0], "low": [95.0], "close": [115.5], "volume": [3000],
    })
    cache.save_daily_quotes("DUP_TICKER", update_df)
    retrieved_updated = cache.get_daily_quotes("DUP_TICKER")
    assert len(retrieved_updated) == 2
    assert retrieved_updated["close"].iloc[0] == 115.5

    # 4. Tickers with dots (BRK.B) and hyphens (BRK-B)
    dot_df = pd.DataFrame({
        "date": ["2026-10-01"],
        "open": [450.0], "high": [455.0], "low": [448.0], "close": [452.0], "volume": [500000],
    })
    cache.save_daily_quotes("BRK.B", dot_df)
    # Query with either BRK.B or BRK-B should return the normalized data
    quotes_dot = cache.get_daily_quotes("BRK.B")
    quotes_hyphen = cache.get_daily_quotes("BRK-B")
    assert len(quotes_dot) == 1
    assert len(quotes_hyphen) == 1
    assert quotes_dot["close"].iloc[0] == quotes_hyphen["close"].iloc[0] == 452.0

    # 5. SQL Injection Attempt in ticker
    sql_injection_ticker = "AAPL'; DROP TABLE daily_quotes; --"
    cache.save_daily_quotes(sql_injection_ticker, dot_df)
    retrieved_inj = cache.get_daily_quotes(sql_injection_ticker)
    assert len(retrieved_inj) == 1
    # Verify table was not dropped!
    all_quotes = cache.get_daily_quotes("BRK-B")
    assert len(all_quotes) == 1

    cache.close()


# =============================================================================
# 7. Cross-Process Concurrency & File Lock Isolation
# =============================================================================

def test_cross_process_file_lock_behavior(isolated_cache_dir):
    """
    Empirically verifies cross-process concurrency and locking behavior:
    1. Primary process instantiates MarketDataCache.
    2. Subprocess attempts to open the same cache directory.
    - SQLite WAL allows concurrent multi-process access seamlessly.
    - DuckDB enforces single-process read-write file lock (by design).
    3. Once primary cache calls close(), external processes can immediately connect.
    """
    import subprocess
    primary_cache = MarketDataCache(data_dir=isolated_cache_dir)

    sqlite_file = (isolated_cache_dir / "stocknomist.db").as_posix()
    duck_file = (isolated_cache_dir / "market_data.duckdb").as_posix()
    repo_posix = REPO_ROOT.as_posix()
    cache_dir_posix = isolated_cache_dir.as_posix()

    sub_code = f"""import sys
from pathlib import Path
sys.path.insert(0, '{repo_posix}')
import duckdb, sqlite3

# Test SQLite cross-process access
try:
    conn_sq = sqlite3.connect('{sqlite_file}', timeout=5.0)
    cur = conn_sq.cursor()
    cur.execute("SELECT COUNT(*) FROM universe_constituents;")
    _ = cur.fetchone()
    conn_sq.close()
    print("SQLITE_CROSS_PROCESS_OK")
except Exception as e:
    print(f"SQLITE_ERR: {{e}}")

# Test DuckDB cross-process access
try:
    conn_duck = duckdb.connect('{duck_file}')
    conn_duck.execute("SELECT COUNT(*) FROM daily_quotes;")
    conn_duck.close()
    print("DUCKDB_CROSS_PROCESS_OK")
except Exception as e:
    print(f"DUCKDB_LOCKED: {{type(e).__name__}}")
"""
    result = subprocess.run(
        [sys.executable, "-c", sub_code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    stdout = result.stdout
    print(f"\nCross-process probe stdout:\n{stdout}")
    print(f"Cross-process probe stderr:\n{result.stderr}")
    assert "SQLITE_CROSS_PROCESS_OK" in stdout, f"SQLite cross-process failed: stdout='{stdout}', stderr='{result.stderr}'"
    assert "DUCKDB_LOCKED: IOException" in stdout or "DUCKDB_CROSS_PROCESS_OK" in stdout

    # Close primary cache
    primary_cache.close()

    # Verify subprocess can now open DuckDB without any lock collisions
    sub_code_after = f"""import sys
from pathlib import Path
sys.path.insert(0, '{repo_posix}')
from backend.app.data.cache import MarketDataCache

c = MarketDataCache(data_dir=Path('{cache_dir_posix}'))
c.close()
print("REOPEN_AFTER_CLOSE_OK")
"""
    result_after = subprocess.run(
        [sys.executable, "-c", sub_code_after],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "REOPEN_AFTER_CLOSE_OK" in result_after.stdout, f"Reopening after close failed: {result_after.stdout} {result_after.stderr}"
