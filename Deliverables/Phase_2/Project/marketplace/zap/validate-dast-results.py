#!/usr/bin/env python3
"""
DAST Results Validation & Reporting Script
===========================================
Project : Marketplace FastAPI
Updated : 2026-06-13

Parses a ZAP JSON report and maps alerts to project DAST test IDs.
Also performs live DAST-07 (Information Leakage) checks against the
running application.

Usage:
  python validate-dast-results.py --mode baseline --report zap-report.json
  python validate-dast-results.py --mode api --report zap-report.json --url http://localhost:8000
"""

from __future__ import annotations

import argparse
import datetime
import glob
import json
import logging
import os
import re
import sys

import httpx

# ── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("dast-validate")

# ── DAST Mapping ────────────────────────────────────────────────────────────

DAST_MAPPING: dict[int, str] = {
    # DAST-01: SQL Injection
    40018: "DAST-01",
    40019: "DAST-01",
    40020: "DAST-01",
    40021: "DAST-01",
    40022: "DAST-01",
    40024: "DAST-01",
    40027: "DAST-01",
    90018: "DAST-01",
    # DAST-02: XSS
    40012: "DAST-02",
    40014: "DAST-02",
    40016: "DAST-02",
    40017: "DAST-02",
    # DAST-03: Security Headers
    10015: "DAST-03",
    10020: "DAST-03",
    10021: "DAST-03",
    10035: "DAST-03",
    10038: "DAST-03",
    # DAST-04: Path Traversal
    6: "DAST-04",
    40003: "DAST-04",
    # DAST-07: Information Leakage
    10036: "DAST-07",
    10037: "DAST-07",
}

DAST_DESCRIPTIONS: dict[str, str] = {
    "DAST-01": "SQL Injection",
    "DAST-02": "Cross-Site Scripting (XSS)",
    "DAST-03": "Security Headers",
    "DAST-04": "Path Traversal / Injection",
    "DAST-07": "Information Leakage",
}

# Risk codes: 0=Informational, 1=Low, 2=Medium, 3=High
RISK_NAMES = {0: "Informational", 1: "Low", 2: "Medium", 3: "High"}

# ── Stack-trace patterns for DAST-07 live checks ───────────────────────────

STACK_TRACE_PATTERNS: list[re.Pattern] = [
    re.compile(r"Traceback", re.IGNORECASE),
    re.compile(r'File\s+"/', re.IGNORECASE),
    re.compile(r"sqlalchemy\.exc", re.IGNORECASE),
    re.compile(r"psycopg2", re.IGNORECASE),
    re.compile(r"Internal Server Error.*(?:Traceback|File|Exception)", re.IGNORECASE | re.DOTALL),
    re.compile(r"at\s+0x[0-9a-fA-F]+"),
    re.compile(r"\.py\",?\s+line\s+\d+", re.IGNORECASE),
]

DAST07_PROBE_REQUESTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/nonexistent-path-404", None),
    ("POST", "/auth/login", {"this_is": "invalid json format for login"}),
    ("GET", "/products/not-a-uuid", None),
]


# ── Report parsing ─────────────────────────────────────────────────────────


def _load_report(path: str) -> dict:
    """Load and return the ZAP JSON report."""
    log.info("📄 Loading report: %s", path)
    with open(path) as fh:
        return json.load(fh)


def _extract_alerts(report: dict) -> list[dict]:
    """
    Extract a flat list of alert dicts from the ZAP report.
    Handles both traditional (`site[].alerts[]`) and flat formats.
    """
    alerts: list[dict] = []

    # Traditional format: {"site": [{"alerts": [...]}]}
    sites = report.get("site", [])
    if isinstance(sites, list):
        for site in sites:
            site_alerts = site.get("alerts", [])
            if isinstance(site_alerts, list):
                alerts.extend(site_alerts)

    # Flat format: {"alerts": [...]}  (some ZAP GitHub Actions)
    if not alerts:
        flat = report.get("alerts", [])
        if isinstance(flat, list):
            alerts.extend(flat)

    log.info("🔍 Extracted %d alert(s) from report", len(alerts))
    return alerts


def _categorise_alerts(alerts: list[dict]) -> dict[str, list[dict]]:
    """Group alerts by DAST test ID."""
    grouped: dict[str, list[dict]] = {tid: [] for tid in DAST_DESCRIPTIONS}

    for alert in alerts:
        # pluginid may be string or int
        try:
            plugin_id = int(alert.get("pluginid", alert.get("alertRef", 0)))
        except (ValueError, TypeError):
            continue

        dast_id = DAST_MAPPING.get(plugin_id)
        if dast_id:
            grouped[dast_id].append(alert)

    return grouped


# ── DAST-07 live checks ────────────────────────────────────────────────────


def _run_dast07_live_checks(base_url: str) -> tuple[bool, list[dict]]:
    """
    Send probe requests and check responses for stack-trace leakage.
    Returns (passed, details).
    """
    log.info("🔎 Running DAST-07 live information-leakage probes against %s", base_url)
    probe_results: list[dict] = []
    all_clean = True

    with httpx.Client(follow_redirects=True, timeout=15.0) as client:
        for method, path, body in DAST07_PROBE_REQUESTS:
            url = f"{base_url}{path}"
            try:
                resp = client.request(method, url, json=body)
                body_text = resp.text
                status = resp.status_code
            except httpx.HTTPError as exc:
                log.warning("  ⚠️  %s %s — HTTP error: %s", method, path, exc)
                probe_results.append(
                    {
                        "method": method,
                        "path": path,
                        "status": None,
                        "leaked": False,
                        "error": str(exc),
                        "matched_patterns": [],
                    }
                )
                continue

            matched: list[str] = []
            for pattern in STACK_TRACE_PATTERNS:
                if pattern.search(body_text):
                    matched.append(pattern.pattern)

            leaked = len(matched) > 0
            if leaked:
                all_clean = False

            icon = "❌" if leaked else "✅"
            log.info(
                "  %s %s %s → HTTP %d  patterns matched: %d",
                icon,
                method,
                path,
                status,
                len(matched),
            )

            probe_results.append(
                {
                    "method": method,
                    "path": path,
                    "status": status,
                    "leaked": leaked,
                    "matched_patterns": matched,
                }
            )

    return all_clean, probe_results


# ── Evaluation logic ───────────────────────────────────────────────────────


def _evaluate_test(
    dast_id: str,
    alerts: list[dict],
    mode: str,
    dast07_live_pass: bool | None = None,
) -> tuple[str, str]:
    """
    Evaluate a single DAST test.
    Returns (status, detail_string).
    """
    if dast_id == "DAST-01":
        # FAIL if any SQLi alert found
        if alerts:
            names = {a.get("name", "?") for a in alerts}
            return "FAIL", f"{len(alerts)} ({', '.join(names)})"
        return "PASS", "0"

    if dast_id == "DAST-02":
        # FAIL if any XSS alert found
        if alerts:
            names = {a.get("name", "?") for a in alerts}
            return "FAIL", f"{len(alerts)} ({', '.join(names)})"
        return "PASS", "0"

    if dast_id == "DAST-03":
        # FAIL if any header alert with risk >= Medium (riskcode >= 2)
        failing = [
            a for a in alerts if int(a.get("riskcode", 0)) >= 2
        ]
        if failing:
            names = {a.get("name", "?") for a in failing}
            return "FAIL", f"{len(failing)} ({', '.join(names)})"
        if alerts:
            return "WARN", f"{len(alerts)} (low/info only)"
        return "PASS", "0"

    if dast_id == "DAST-04":
        if alerts:
            names = {a.get("name", "?") for a in alerts}
            return "FAIL", f"{len(alerts)} ({', '.join(names)})"
        return "PASS", "0"

    if dast_id == "DAST-07":
        zap_fail = bool(alerts)
        live_fail = dast07_live_pass is False
        if zap_fail or live_fail:
            parts: list[str] = []
            if zap_fail:
                names = {a.get("name", "?") for a in alerts}
                parts.append(f"ZAP:{len(alerts)} ({', '.join(names)})")
            if live_fail:
                parts.append("Live probes: stack-trace leakage detected")
            return "FAIL", "; ".join(parts)
        return "PASS", "0"

    return "SKIP", "unmapped"


# ── Pretty printing ────────────────────────────────────────────────────────


def _print_table(rows: list[dict]) -> None:
    """Print a formatted results table."""
    col_id = 8
    col_desc = 40
    col_status = 6
    col_alerts = 45

    border_top = (
        f"╔{'═' * (col_id + 2)}╦{'═' * (col_desc + 2)}"
        f"╦{'═' * (col_status + 2)}╦{'═' * (col_alerts + 2)}╗"
    )
    border_mid = (
        f"╠{'═' * (col_id + 2)}╬{'═' * (col_desc + 2)}"
        f"╬{'═' * (col_status + 2)}╬{'═' * (col_alerts + 2)}╣"
    )
    border_bot = (
        f"╚{'═' * (col_id + 2)}╩{'═' * (col_desc + 2)}"
        f"╩{'═' * (col_status + 2)}╩{'═' * (col_alerts + 2)}╝"
    )

    header = (
        f"║ {'Test ID':<{col_id}} ║ {'Description':<{col_desc}} "
        f"║ {'Status':<{col_status}} ║ {'Alerts Found':<{col_alerts}} ║"
    )

    print()
    print(border_top)
    print(header)
    print(border_mid)
    for r in rows:
        tid = r["test_id"]
        desc = r["description"][:col_desc]
        status = r["status"]
        detail = r["detail"][:col_alerts]
        print(
            f"║ {tid:<{col_id}} ║ {desc:<{col_desc}} "
            f"║ {status:<{col_status}} ║ {detail:<{col_alerts}} ║"
        )
    print(border_bot)
    print()


# ── Main ────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate DAST scan results from OWASP ZAP",
    )
    parser.add_argument(
        "--mode",
        choices=["baseline", "api"],
        required=True,
        help="Scan mode: 'baseline' (passive) or 'api' (active)",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Path to ZAP JSON report (default: auto-detect *.json in cwd)",
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Base URL for live DAST-07 probes (default: http://localhost:8000)",
    )
    return parser.parse_args()


def _find_report() -> str:
    """Auto-detect a ZAP JSON report in the current directory."""
    candidates = glob.glob("*.json")
    # Exclude our own output files
    candidates = [
        c
        for c in candidates
        if c not in ("dast-05-results.json", "dast-results-summary.json")
    ]
    if not candidates:
        log.error("❌ No JSON report files found in current directory")
        sys.exit(1)
    if len(candidates) > 1:
        log.warning(
            "⚠️  Multiple JSON files found: %s — using first one", candidates
        )
    return candidates[0]


def main() -> None:
    args = parse_args()

    report_path = args.report or _find_report()
    if not os.path.isfile(report_path):
        log.error("❌ Report file not found: %s", report_path)
        sys.exit(1)

    log.info("🚀 DAST Results Validation — mode=%s", args.mode)
    log.info("═" * 70)

    # ── Parse report ────────────────────────────────────────────────────────
    report = _load_report(report_path)
    alerts = _extract_alerts(report)
    grouped = _categorise_alerts(alerts)

    # ── DAST-07 live checks ─────────────────────────────────────────────────
    dast07_live_pass: bool | None = None
    dast07_live_details: list[dict] = []
    try:
        dast07_live_pass, dast07_live_details = _run_dast07_live_checks(args.url)
    except Exception as exc:
        log.warning("⚠️  DAST-07 live probes failed: %s — skipping", exc)

    # ── Evaluate each test ──────────────────────────────────────────────────
    results_rows: list[dict] = []
    any_fail = False

    # Determine which tests to evaluate based on mode
    if args.mode == "baseline":
        test_ids = ["DAST-03", "DAST-07"]
    else:
        test_ids = ["DAST-01", "DAST-02", "DAST-03", "DAST-04", "DAST-07"]

    for tid in test_ids:
        status, detail = _evaluate_test(
            tid,
            grouped.get(tid, []),
            args.mode,
            dast07_live_pass=dast07_live_pass if tid == "DAST-07" else None,
        )
        row = {
            "test_id": tid,
            "description": DAST_DESCRIPTIONS[tid],
            "status": status,
            "detail": detail,
            "alert_count": len(grouped.get(tid, [])),
        }
        results_rows.append(row)
        if status == "FAIL":
            any_fail = True

    # ── Print summary table ─────────────────────────────────────────────────
    _print_table(results_rows)

    # ── Persist full results ────────────────────────────────────────────────
    summary = {
        "mode": args.mode,
        "report_file": report_path,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_zap_alerts": len(alerts),
        "tests": results_rows,
        "dast07_live_probes": dast07_live_details,
        "overall_pass": not any_fail,
    }

    output_file = "dast-results-summary.json"
    with open(output_file, "w") as fh:
        json.dump(summary, fh, indent=2)
    log.info("📝 Full results written to %s", output_file)

    # ── Exit code ───────────────────────────────────────────────────────────
    if any_fail:
        log.error("❌ DAST validation FAILED — see table above")
        sys.exit(1)

    log.info("✅ DAST validation PASSED — all tests green")
    sys.exit(0)


if __name__ == "__main__":
    main()
