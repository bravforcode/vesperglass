"""
Adversarial Stress Test Suite for Milestone 1 Data Ingestion.
Target modules:
- backend/app/data/yfinance_client.py
- backend/app/data/sec_edgar.py

Verifies:
1. Invalid tickers, empty strings, whitespace, None inputs, extreme length.
2. Network timeouts (ConnectTimeout, ReadTimeout, generic RequestException).
3. Synthetic HTTP 429 rate limit errors (failover, backoff, retry exhaustion).
4. Corrupted and malformed API payloads (HTML responses, None-fields, corrupted XBRL facts, division by zero).
5. Zero unhandled exceptions and adherence to interface contracts.
"""

from unittest.mock import MagicMock, patch
import pandas as pd
import pytest
import requests

from backend.app.data.yfinance_client import YFinanceClient, EXPECTED_COLUMNS
from backend.app.data.sec_edgar import SecEdgarClient


# =============================================================================
# Helper Fixtures & Mock Responses
# =============================================================================

def make_mock_response(status_code=200, json_data=None, text=""):
    """Creates a mock requests.Response object."""
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = status_code
    mock_resp.text = text
    if json_data is not None:
        mock_resp.json.return_value = json_data
    else:
        mock_resp.json.side_effect = requests.exceptions.JSONDecodeError("Expecting value", "doc", 0)
    return mock_resp


# =============================================================================
# 1. Adversarial Tests for YFinanceClient: Invalid Tickers & Edge Inputs
# =============================================================================

class TestYFinanceClientEdgeInputs:
    """Tests YFinanceClient against pathological and boundary inputs."""

    def test_empty_ticker_string(self):
        """Empty string ticker should return empty DataFrame with EXPECTED_COLUMNS without crashing."""
        client = YFinanceClient(max_retries=1, base_backoff=0.01, timeout=0.5)
        # Should not raise exception
        try:
            df = client.get_historical_bars("", days=30)
            assert isinstance(df, pd.DataFrame)
            assert list(df.columns) == EXPECTED_COLUMNS
            assert df.empty
        except Exception as e:
            pytest.fail(f"get_historical_bars('') raised unhandled exception: {type(e).__name__}: {e}")

    def test_whitespace_ticker_string(self):
        """Whitespace ticker should return empty DataFrame gracefully."""
        client = YFinanceClient(max_retries=1, base_backoff=0.01, timeout=0.5)
        try:
            df = client.get_historical_bars("   \t\n  ", days=30)
            assert isinstance(df, pd.DataFrame)
            assert list(df.columns) == EXPECTED_COLUMNS
            assert df.empty
        except Exception as e:
            pytest.fail(f"get_historical_bars('   ') raised unhandled exception: {type(e).__name__}: {e}")

    def test_none_ticker_input(self):
        """None input for ticker should either return empty DataFrame or raise TypeError/ValueError gracefully without crashing app."""
        client = YFinanceClient(max_retries=1, base_backoff=0.01, timeout=0.5)
        try:
            df = client.get_historical_bars(None, days=30)  # type: ignore
            assert isinstance(df, pd.DataFrame)
            assert list(df.columns) == EXPECTED_COLUMNS
            assert df.empty
        except (AttributeError, TypeError, ValueError) as e:
            # Document if AttributeError occurs due to missing None check
            pytest.fail(f"Unhandled crash on None ticker input: {type(e).__name__}: {e}")

    def test_extreme_ticker_length(self):
        """Pathologically long ticker (500 chars) should not crash client."""
        client = YFinanceClient(max_retries=1, base_backoff=0.01, timeout=0.5)
        long_ticker = "A" * 500
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = make_mock_response(status_code=404)
            df = client.get_historical_bars(long_ticker, days=30)
            assert isinstance(df, pd.DataFrame)
            assert list(df.columns) == EXPECTED_COLUMNS
            assert df.empty

    def test_special_characters_in_ticker(self):
        """Special characters, URL reserved chars, and potential injection strings."""
        client = YFinanceClient(max_retries=1, base_backoff=0.01, timeout=0.5)
        pathological_tickers = ["$$$", "AAPL/GOOG", "BRK..B", "MSFT; DROP TABLE;", "<script>", "%20%2F"]
        for bad_ticker in pathological_tickers:
            with patch.object(client.session, "get") as mock_get:
                mock_get.return_value = make_mock_response(status_code=404)
                df = client.get_historical_bars(bad_ticker, days=30)
                assert isinstance(df, pd.DataFrame)
                assert list(df.columns) == EXPECTED_COLUMNS

    def test_boundary_days_parameters(self):
        """Test zero, negative, and extreme days parameters."""
        client = YFinanceClient(max_retries=1, base_backoff=0.01, timeout=0.5)
        # Mock valid response with 5 bars
        valid_v8 = {
            "chart": {
                "result": [{
                    "timestamp": [1700000000, 1700086400, 1700172800, 1700259200, 1700345600],
                    "indicators": {
                        "quote": [{
                            "open": [100.0, 101.0, 102.0, 103.0, 104.0],
                            "high": [105.0, 106.0, 107.0, 108.0, 109.0],
                            "low": [99.0, 100.0, 101.0, 102.0, 103.0],
                            "close": [104.0, 105.0, 106.0, 107.0, 108.0],
                            "volume": [1000, 2000, 3000, 4000, 5000],
                        }]
                    }
                }],
                "error": None
            }
        }
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = make_mock_response(status_code=200, json_data=valid_v8)
            # Days = 0
            df_zero = client.get_historical_bars("AAPL", days=0)
            assert isinstance(df_zero, pd.DataFrame)
            # Days = negative
            df_neg = client.get_historical_bars("AAPL", days=-5)
            assert isinstance(df_neg, pd.DataFrame)


# =============================================================================
# 2. Adversarial Tests for YFinanceClient: Timeouts and Network Failures
# =============================================================================

class TestYFinanceClientNetworkStress:
    """Tests YFinanceClient behavior under network degradation, timeouts, and connection drops."""

    @patch("time.sleep", return_value=None)
    def test_total_network_connect_timeout(self, mock_sleep):
        """Verify handling of connection timeouts when both v8 and yfinance fail."""
        client = YFinanceClient(max_retries=2, base_backoff=0.01, timeout=0.5)
        with patch.object(client.session, "get", side_effect=requests.exceptions.ConnectTimeout("Connection timed out")):
            with patch.object(client, "fetch_ticker_bars_yf", return_value=None):
                df = client.get_historical_bars("AAPL", days=30)
                assert isinstance(df, pd.DataFrame)
                assert list(df.columns) == EXPECTED_COLUMNS
                assert df.empty

    @patch("time.sleep", return_value=None)
    def test_total_network_read_timeout(self, mock_sleep):
        """Verify handling of read timeouts during socket transmission."""
        client = YFinanceClient(max_retries=2, base_backoff=0.01, timeout=0.5)
        with patch.object(client.session, "get", side_effect=requests.exceptions.ReadTimeout("Read timed out")):
            with patch.object(client, "fetch_ticker_bars_yf", return_value=None):
                df = client.get_historical_bars("AAPL", days=30)
                assert isinstance(df, pd.DataFrame)
                assert list(df.columns) == EXPECTED_COLUMNS
                assert df.empty

    @patch("time.sleep", return_value=None)
    def test_generic_network_exceptions(self, mock_sleep):
        """Verify handling of unexpected socket, connection reset, or proxy errors."""
        client = YFinanceClient(max_retries=2, base_backoff=0.01, timeout=0.5)
        exceptions = [
            requests.exceptions.ConnectionError("Connection reset by peer"),
            requests.exceptions.ChunkedEncodingError("Chunked encoding error"),
            requests.exceptions.SSLError("SSL certificate verification failed"),
            requests.exceptions.ProxyError("Proxy unreachable"),
        ]
        for exc in exceptions:
            with patch.object(client.session, "get", side_effect=exc):
                with patch.object(client, "fetch_ticker_bars_yf", return_value=None):
                    df = client.get_historical_bars("AAPL", days=30)
                    assert isinstance(df, pd.DataFrame)
                    assert list(df.columns) == EXPECTED_COLUMNS
                    assert df.empty

    @patch("time.sleep", return_value=None)
    def test_v8_timeout_falls_back_to_yf(self, mock_sleep):
        """Verify that when v8 chart API times out, it gracefully falls back to fetch_ticker_bars_yf."""
        client = YFinanceClient(max_retries=1, base_backoff=0.01, timeout=0.5)
        mock_yf_df = pd.DataFrame({
            "date": ["2026-10-27"],
            "open": [150.0],
            "high": [155.0],
            "low": [149.0],
            "close": [154.0],
            "volume": [10000],
        })
        with patch.object(client.session, "get", side_effect=requests.exceptions.Timeout("v8 timed out")):
            with patch.object(client, "fetch_ticker_bars_yf", return_value=mock_yf_df) as mock_yf:
                df = client.get_historical_bars("AAPL", days=30)
                assert mock_yf.called
                assert not df.empty
                assert df["close"].iloc[0] == 154.0


# =============================================================================
# 3. Adversarial Tests for YFinanceClient: HTTP 429 Rate Limiting
# =============================================================================

class TestYFinanceClientRateLimiting:
    """Tests synthetic HTTP 429 response handling and retry behavior."""

    @patch("time.sleep", return_value=None)
    def test_continuous_429_rate_limit_exhaustion(self, mock_sleep):
        """All attempts and endpoints return 429; client should gracefully back off and return empty DataFrame when fallback also empty."""
        client = YFinanceClient(max_retries=3, base_backoff=0.01, timeout=0.5)
        mock_429 = make_mock_response(status_code=429, text="Too Many Requests")
        with patch.object(client.session, "get", return_value=mock_429) as mock_get:
            with patch.object(client, "fetch_ticker_bars_yf", return_value=None):
                df = client.get_historical_bars("AAPL", days=30)
                assert isinstance(df, pd.DataFrame)
                assert list(df.columns) == EXPECTED_COLUMNS
                assert df.empty
                # Total attempts = max_retries * 2 endpoints = 3 * 2 = 6 calls
                assert mock_get.call_count == 6
                # Backoff sleep called max_retries - 1 = 2 times
                assert mock_sleep.call_count == 2

    @patch("time.sleep", return_value=None)
    def test_transient_429_recovery(self, mock_sleep):
        """Initial attempt returns 429, second attempt succeeds with 200."""
        client = YFinanceClient(max_retries=3, base_backoff=0.01, timeout=0.5)
        valid_v8 = {
            "chart": {
                "result": [{
                    "timestamp": [1700000000],
                    "indicators": {
                        "quote": [{
                            "open": [150.0],
                            "high": [155.0],
                            "low": [149.0],
                            "close": [154.0],
                            "volume": [10000],
                        }]
                    }
                }],
                "error": None
            }
        }
        mock_429 = make_mock_response(status_code=429, text="Too Many Requests")
        mock_200 = make_mock_response(status_code=200, json_data=valid_v8)

        with patch.object(client.session, "get", side_effect=[mock_429, mock_429, mock_200]):
            df = client.get_historical_bars("AAPL", days=30)
            assert isinstance(df, pd.DataFrame)
            assert len(df) == 1
            assert df["close"].iloc[0] == 154.0


# =============================================================================
# 4. Adversarial Tests for YFinanceClient: Corrupted Payloads
# =============================================================================

class TestYFinanceClientCorruptedPayloads:
    """Tests YFinanceClient against malformed, partial, or corrupted JSON responses."""

    def test_non_json_html_response(self):
        """Response is 200 OK but payload is HTML error page (captive portal, Cloudflare challenge)."""
        client = YFinanceClient(max_retries=1, base_backoff=0.01, timeout=0.5)
        mock_html = make_mock_response(status_code=200, text="<html><body>Cloudflare Block</body></html>")
        with patch.object(client.session, "get", return_value=mock_html):
            with patch.object(client, "fetch_ticker_bars_yf", return_value=None):
                df = client.get_historical_bars("AAPL", days=30)
                assert isinstance(df, pd.DataFrame)
                assert list(df.columns) == EXPECTED_COLUMNS
                assert df.empty

    def test_corrupted_chart_structure_none_fields(self):
        """Pathological JSON structures with None values for critical dictionary keys."""
        client = YFinanceClient(max_retries=1, base_backoff=0.01, timeout=0.5)
        pathological_payloads = [
            {"chart": None},
            {"chart": {"error": None, "result": None}},
            {"chart": {"error": None, "result": []}},
            {"chart": {"error": None, "result": [{}]}},
            {"chart": {"error": None, "result": [{"timestamp": None, "indicators": None}]}},
            {"chart": {"error": None, "result": [{"timestamp": [], "indicators": {"quote": None}}]}},
            {"chart": {"error": None, "result": [{"timestamp": [1700000000], "indicators": {"quote": []}}]}},
            {"chart": {"error": None, "result": [{"timestamp": [1700000000], "indicators": {"quote": [None]}}]}},
            {"chart": {"error": None, "result": [{"timestamp": [1700000000], "indicators": {"quote": [{"open": None, "close": None}]}}]}},
            [],  # list instead of dict
            12345,  # int instead of dict
            "corrupted string",  # str instead of dict
        ]

        for payload in pathological_payloads:
            mock_resp = make_mock_response(status_code=200, json_data=payload)
            with patch.object(client.session, "get", return_value=mock_resp):
                try:
                    df = client.get_historical_bars("AAPL", days=30)
                    assert isinstance(df, pd.DataFrame)
                    assert list(df.columns) == EXPECTED_COLUMNS
                except Exception as e:
                    pytest.fail(f"Payload {payload} caused unhandled crash: {type(e).__name__}: {e}")

    def test_corrupted_price_types(self):
        """Response contains string or non-numeric values in numeric price arrays."""
        client = YFinanceClient(max_retries=1, base_backoff=0.01, timeout=0.5)
        corrupted_types = {
            "chart": {
                "result": [{
                    "timestamp": [1700000000, 1700086400],
                    "indicators": {
                        "quote": [{
                            "open": ["invalid", 100.0],
                            "high": [None, 105.0],
                            "low": ["-99.0", 98.0],
                            "close": ["N/A", 102.0],
                            "volume": ["corrupt", 50000],
                        }]
                    }
                }],
                "error": None
            }
        }
        mock_resp = make_mock_response(status_code=200, json_data=corrupted_types)
        with patch.object(client.session, "get", return_value=mock_resp):
            df = client.get_historical_bars("AAPL", days=30)
            assert isinstance(df, pd.DataFrame)
            assert list(df.columns) == EXPECTED_COLUMNS
            # Should have parsed the second valid row and dropped the invalid row
            assert len(df) == 1
            assert df["close"].iloc[0] == 102.0


# =============================================================================
# 5. Adversarial Tests for SecEdgarClient: Invalid Inputs & Tickers
# =============================================================================

class TestSecEdgarClientEdgeInputs:
    """Tests SecEdgarClient against invalid tickers, edge CIKs, and empty inputs."""

    def test_empty_ticker_fundamental_metrics(self):
        """Empty ticker string should return baseline zeroed fundamentals dict without crashing."""
        client = SecEdgarClient(timeout=0.5)
        try:
            metrics = client.get_fundamental_metrics("")
            assert isinstance(metrics, dict)
            assert metrics["ticker"] == ""
            assert metrics["roe"] == 0.0
            assert metrics["debt_to_equity"] == 0.0
        except Exception as e:
            pytest.fail(f"get_fundamental_metrics('') raised unhandled exception: {type(e).__name__}: {e}")

    def test_none_ticker_fundamental_metrics(self):
        """None ticker input should be handled gracefully without unhandled crash."""
        client = SecEdgarClient(timeout=0.5)
        try:
            metrics = client.get_fundamental_metrics(None)  # type: ignore
            assert isinstance(metrics, dict)
        except (AttributeError, TypeError, ValueError) as e:
            pytest.fail(f"Unhandled crash on None ticker input in get_fundamental_metrics: {type(e).__name__}: {e}")

    def test_invalid_cik_formats(self):
        """Test non-existent, non-numeric, or malformed CIK inputs."""
        client = SecEdgarClient(timeout=0.5)
        pathological_ciks = ["", "0", "-1", "abc", "99999999999999999", "!@#$"]
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = make_mock_response(status_code=404)
            for cik in pathological_ciks:
                res = client.fetch_company_facts_raw(cik)
                assert res is None
                fund = client.parse_sec_fundamentals("INVALID", cik)
                assert isinstance(fund, dict)
                assert fund["roe"] == 0.0


# =============================================================================
# 6. Adversarial Tests for SecEdgarClient: Network Timeouts & HTTP 429
# =============================================================================

class TestSecEdgarClientNetworkStress:
    """Tests SecEdgarClient under network timeouts, socket disconnects, and 429 rate limits."""

    def test_sec_edgar_timeouts(self):
        """Verify network timeout on SEC EDGAR endpoints does not throw unhandled exceptions."""
        client = SecEdgarClient(timeout=0.5)
        with patch.object(client.session, "get", side_effect=requests.exceptions.Timeout("SEC API Timeout")):
            # 1. CIK mapping timeout
            cik_map = client.load_cik_mapping(force_refresh=True)
            assert isinstance(cik_map, dict)

            # 2. Company facts raw timeout
            facts = client.fetch_company_facts_raw("0000320193")
            assert facts is None

            # 3. Overall fundamental metrics timeout
            metrics = client.get_fundamental_metrics("AAPL", cik="0000320193")
            assert isinstance(metrics, dict)
            assert metrics["roe"] == 0.0

    def test_sec_edgar_http_429_rate_limiting(self):
        """SEC EDGAR returns HTTP 429 (exceeded 10 req/s threshold)."""
        client = SecEdgarClient(timeout=0.5)
        mock_429 = make_mock_response(status_code=429, text="Your Request Has Been Rate Limited")
        with patch.object(client.session, "get", return_value=mock_429):
            facts = client.fetch_company_facts_raw("0000320193")
            assert facts is None
            metrics = client.get_fundamental_metrics("AAPL", cik="0000320193")
            assert isinstance(metrics, dict)
            assert metrics["roe"] == 0.0
            assert metrics["debt_to_equity"] == 0.0


# =============================================================================
# 7. Adversarial Tests for SecEdgarClient: Corrupted XBRL Payloads
# =============================================================================

class TestSecEdgarClientCorruptedXBRL:
    """Tests SecEdgarClient XBRL parsing against corrupted, partial, or malformed taxonomy facts."""

    def test_corrupted_facts_root_structures(self):
        """Malformed root structure in company facts JSON."""
        client = SecEdgarClient(timeout=0.5)
        pathological_roots = [
            {},
            {"facts": None},
            {"facts": {"us-gaap": None}},
            {"facts": {"us-gaap": {}}},
            {"facts": "string instead of dict"},
            {"facts": []},
            [],
            None,
        ]

        for payload in pathological_roots:
            with patch.object(client, "fetch_company_facts_raw", return_value=payload):
                try:
                    res = client.parse_sec_fundamentals("AAPL", "0000320193")
                    assert isinstance(res, dict)
                    assert res["roe"] == 0.0
                    assert res["debt_to_equity"] == 0.0
                except Exception as e:
                    pytest.fail(f"XBRL root payload {payload} caused unhandled crash: {type(e).__name__}: {e}")

    def test_corrupted_facts_units_and_values(self):
        """Corrupted units structures, nulls, missing keys, and non-numeric types."""
        client = SecEdgarClient(timeout=0.5)
        corrupted_payload = {
            "cik": 320193,
            "facts": {
                "us-gaap": {
                    "StockholdersEquity": {
                        "units": {
                            "USD": [
                                None,
                                {},
                                {"end": "2025-01-01", "val": None},
                                {"end": "2025-02-01", "val": "not_a_number"},
                                {"end": 12345, "val": 1000},  # non-string date
                            ]
                        }
                    },
                    "NetIncomeLoss": {
                        "units": {
                            "USD": [
                                {"start": "2025-01-01", "end": "2025-03-31", "val": None, "form": "10-Q", "fp": "Q1"},
                                {"start": "2025-04-01", "end": "2025-06-30", "val": "corrupted", "form": "10-Q", "fp": "Q2"},
                            ]
                        }
                    },
                    "LongTermDebtNoncurrent": {"units": None},
                    "DebtCurrent": "invalid_structure",
                    "NetCashProvidedByUsedInOperatingActivities": {
                        "units": {"USD": [{"val": None}]}
                    },
                    "PaymentsToAcquirePropertyPlantAndEquipment": {
                        "units": {"USD": [{"val": 0}]}
                    },
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {
                            "USD": [
                                {"start": "2025-01-01", "end": "2025-03-31", "val": 0, "form": "10-Q"},
                                {"start": "2025-04-01", "end": "2025-06-30", "val": 500, "form": "10-Q"},
                            ]
                        }
                    },
                    "EarningsPerShareDiluted": {
                        "units": {"USD/shares": [{"val": None}]}
                    }
                }
            }
        }

        with patch.object(client, "fetch_company_facts_raw", return_value=corrupted_payload):
            try:
                metrics = client.parse_sec_fundamentals("AAPL", "0000320193")
                assert isinstance(metrics, dict)
            except Exception as e:
                pytest.fail(f"Corrupted units caused unhandled crash: {type(e).__name__}: {e}")

    def test_zero_and_negative_equity_division_by_zero(self):
        """Zero and negative stockholders equity must not cause ZeroDivisionError in ROE and Debt-to-Equity."""
        client = SecEdgarClient(timeout=0.5)
        zero_equity_payload = {
            "facts": {
                "us-gaap": {
                    "StockholdersEquity": {
                        "units": {"USD": [{"end": "2025-09-01", "val": 0, "form": "10-K"}]}
                    },
                    "NetIncomeLoss": {
                        "units": {"USD": [{"end": "2025-09-01", "val": 50000000, "form": "10-K"}]}
                    },
                    "LongTermDebtNoncurrent": {
                        "units": {"USD": [{"end": "2025-09-01", "val": 100000000, "form": "10-K"}]}
                    }
                }
            }
        }
        with patch.object(client, "fetch_company_facts_raw", return_value=zero_equity_payload):
            metrics = client.parse_sec_fundamentals("ZERO_EQ", "0000000000")
            assert metrics["roe"] == 0.0
            assert metrics["debt_to_equity"] == 0.0

        negative_equity_payload = {
            "facts": {
                "us-gaap": {
                    "StockholdersEquity": {
                        "units": {"USD": [{"end": "2025-09-01", "val": -50000000, "form": "10-K"}]}
                    },
                    "NetIncomeLoss": {
                        "units": {"USD": [{"end": "2025-09-01", "val": 50000000, "form": "10-K"}]}
                    },
                    "LongTermDebtNoncurrent": {
                        "units": {"USD": [{"end": "2025-09-01", "val": 100000000, "form": "10-K"}]}
                    }
                }
            }
        }
        with patch.object(client, "fetch_company_facts_raw", return_value=negative_equity_payload):
            metrics = client.parse_sec_fundamentals("NEG_EQ", "0000000000")
            assert metrics["roe"] == 0.0
            assert metrics["debt_to_equity"] == 0.0
