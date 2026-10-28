#!/usr/bin/env python3
"""
Stocknomist Standalone E2E Test Runner
Supports running 4 tiers of opaque-box tests:
  Tier 1: Feature Coverage (>=5 tests per feature for F1-F23)
  Tier 2: Boundary & Corner Cases (>=5 tests per feature for F1-F23)
  Tier 3: Cross-Feature Combinations (Pairwise matrix)
  Tier 4: Real-World Application Workloads (S&P 500 screener, portfolio lifecycle, concurrency)

Can run directly with:
  python tests/e2e/runner.py
  python tests/e2e/runner.py --tier 1
  python tests/e2e/runner.py --base-url http://127.0.0.1:18800
"""

import sys
import os
import argparse
import time
import json
import unittest
from typing import Dict, Any, List

# Ensure project root is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)


class TierTestResult(unittest.TestResult):
    """Custom TestResult collecting detailed execution metrics per tier."""
    def __init__(self, verbose: bool = False):
        super().__init__()
        self.verbose = verbose
        self.test_records: List[Dict[str, Any]] = []
        self._start_time = 0.0

    def startTest(self, test: unittest.TestCase):
        super().startTest(test)
        self._start_time = time.perf_counter()

    def addSuccess(self, test: unittest.TestCase):
        super().addSuccess(test)
        elapsed = time.perf_counter() - self._start_time
        test_id = test.id()
        self.test_records.append({
            "test_id": test_id,
            "status": "PASS",
            "duration_s": round(elapsed, 4),
            "message": None,
        })
        if self.verbose:
            print(f"  [PASS] {test_id} ({elapsed:.4f}s)")

    def addFailure(self, test: unittest.TestCase, err):
        super().addFailure(test, err)
        elapsed = time.perf_counter() - self._start_time
        test_id = test.id()
        msg = self._exc_info_to_string(err, test)
        self.test_records.append({
            "test_id": test_id,
            "status": "FAIL",
            "duration_s": round(elapsed, 4),
            "message": msg,
        })
        if self.verbose:
            print(f"  [FAIL] {test_id} ({elapsed:.4f}s)")

    def addError(self, test: unittest.TestCase, err):
        super().addError(test, err)
        elapsed = time.perf_counter() - self._start_time
        test_id = test.id()
        msg = self._exc_info_to_string(err, test)
        self.test_records.append({
            "test_id": test_id,
            "status": "ERROR",
            "duration_s": round(elapsed, 4),
            "message": msg,
        })
        if self.verbose:
            print(f"  [ERROR] {test_id} ({elapsed:.4f}s)")

    def addSkip(self, test: unittest.TestCase, reason: str):
        super().addSkip(test, reason)
        elapsed = time.perf_counter() - self._start_time
        test_id = test.id()
        self.test_records.append({
            "test_id": test_id,
            "status": "SKIP",
            "duration_s": round(elapsed, 4),
            "message": reason,
        })
        if self.verbose:
            print(f"  [SKIP] {test_id}: {reason}")


def load_tier_suite(tier_number: int) -> unittest.TestSuite:
    """Dynamically load test suite for specified tier."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    if tier_number == 1:
        import test_tier1_features
        suite.addTests(loader.loadTestsFromModule(test_tier1_features))
    elif tier_number == 2:
        import test_tier2_boundaries
        suite.addTests(loader.loadTestsFromModule(test_tier2_boundaries))
    elif tier_number == 3:
        import test_tier3_combinations
        suite.addTests(loader.loadTestsFromModule(test_tier3_combinations))
    elif tier_number == 4:
        import test_tier4_workloads
        suite.addTests(loader.loadTestsFromModule(test_tier4_workloads))
    else:
        raise ValueError(f"Unknown tier number: {tier_number}")

    return suite


def run_e2e_suites(
    tiers: List[int],
    base_url: str,
    verbose: bool = False,
    fail_fast: bool = False,
    json_report_path: str = None
) -> int:
    """Run specified E2E test tiers and print structured summary."""
    os.environ["STOCKNOMIST_BASE_URL"] = base_url

    print("=" * 72)
    print("Stocknomist E2E Test Suite Execution")
    print(f"Target Base URL: {base_url}")
    print(f"Executing Tiers: {tiers}")
    print("=" * 72)

    overall_start = time.perf_counter()
    tier_summaries = []
    total_passed = 0
    total_failed = 0
    total_errors = 0
    total_skipped = 0
    all_records = []

    for tier_num in tiers:
        print(f"\n[RUNNING TIER {tier_num}] Loading suite...")
        try:
            suite = load_tier_suite(tier_num)
        except Exception as e:
            print(f"ERROR: Failed to load Tier {tier_num} tests: {e}")
            return 2

        count = suite.countTestCases()
        print(f"  Loaded {count} test cases for Tier {tier_num}.")

        result = TierTestResult(verbose=verbose)
        result.failfast = fail_fast
        tier_start = time.perf_counter()

        suite.run(result)
        tier_duration = time.perf_counter() - tier_start

        passed = len(result.test_records) - len(result.failures) - len(result.errors) - len(result.skipped)
        failed = len(result.failures)
        errors = len(result.errors)
        skipped = len(result.skipped)

        total_passed += passed
        total_failed += failed
        total_errors += errors
        total_skipped += skipped
        all_records.extend(result.test_records)

        summary = {
            "tier": tier_num,
            "total": count,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "skipped": skipped,
            "duration_s": round(tier_duration, 4),
        }
        tier_summaries.append(summary)

        status_str = "PASSED" if (failed == 0 and errors == 0) else "FAILED"
        print(f"  Tier {tier_num} Result: {status_str} | {passed} Passed, {failed} Failed, {errors} Errors, {skipped} Skipped ({tier_duration:.2f}s)")

        if fail_fast and (failed > 0 or errors > 0):
            print("Fail-fast enabled: Aborting remaining tiers.")
            break

    total_duration = time.perf_counter() - overall_start

    print("\n" + "=" * 72)
    print("E2E EXECUTION SUMMARY")
    print("=" * 72)
    print(f"{'Tier':<10} | {'Total':<8} | {'Passed':<8} | {'Failed':<8} | {'Errors':<8} | {'Time (s)':<10}")
    print("-" * 72)
    for s in tier_summaries:
        print(f"Tier {s['tier']:<5} | {s['total']:<8} | {s['passed']:<8} | {s['failed']:<8} | {s['errors']:<8} | {s['duration_s']:<10.2f}")
    print("-" * 72)
    print(f"{'TOTAL':<10} | {total_passed + total_failed + total_errors + total_skipped:<8} | {total_passed:<8} | {total_failed:<8} | {total_errors:<8} | {total_duration:<10.2f}")
    print("=" * 72)

    # Print error details if any
    if total_failed > 0 or total_errors > 0:
        print("\nFAILURE / ERROR DETAILS:")
        for r in all_records:
            if r["status"] in ("FAIL", "ERROR"):
                print(f"\n--- {r['test_id']} [{r['status']}] ---")
                print(r["message"])

    # Export JSON report if requested
    if json_report_path:
        report_data = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "base_url": base_url,
            "total_passed": total_passed,
            "total_failed": total_failed,
            "total_errors": total_errors,
            "total_skipped": total_skipped,
            "total_duration_s": round(total_duration, 4),
            "tier_summaries": tier_summaries,
            "records": all_records,
        }
        with open(json_report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)
        print(f"\nJSON report written to: {json_report_path}")

    if total_failed == 0 and total_errors == 0:
        print("\nALL TEST TIERS PASSED SUCCESSFULLY.")
        return 0
    else:
        print(f"\nTEST SUITE FAILED with {total_failed} failures and {total_errors} errors.")
        return 1


def main():
    parser = argparse.ArgumentParser(description="Stocknomist Standalone E2E Test Runner")
    parser.add_argument(
        "--tier",
        type=str,
        default="all",
        choices=["1", "2", "3", "4", "all"],
        help="Select specific test tier (1, 2, 3, 4, or all)"
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=os.environ.get("STOCKNOMIST_BASE_URL", "http://127.0.0.1:18800"),
        help="Target base URL for live endpoints (default: http://127.0.0.1:18800)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print verbose per-test execution lines"
    )
    parser.add_argument(
        "-f", "--fail-fast",
        action="store_true",
        help="Stop on first test failure"
    )
    parser.add_argument(
        "--json-report",
        type=str,
        default=None,
        help="File path to save JSON test results"
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Validate test suite syntax and discovery without running entire suite"
    )

    args = parser.parse_args()

    if args.self_check:
        print("Stocknomist Test Runner: Performing Self-Check...")
        for t in [1, 2, 3, 4]:
            try:
                s = load_tier_suite(t)
                print(f"  Tier {t}: Discovered {s.countTestCases()} tests. [OK]")
            except Exception as e:
                print(f"  Tier {t}: ERROR loading tests: {e}")
                return 2
        print("Self-check completed successfully.")
        return 0

    if args.tier == "all":
        selected_tiers = [1, 2, 3, 4]
    else:
        selected_tiers = [int(args.tier)]

    exit_code = run_e2e_suites(
        tiers=selected_tiers,
        base_url=args.base_url,
        verbose=args.verbose,
        fail_fast=args.fail_fast,
        json_report_path=args.json_report
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
