#!/usr/bin/env python3
"""
DAST Authentication & DAST-05 (Authentication Bypass) Validation Script
========================================================================
Project : Marketplace FastAPI
Updated : 2026-06-13

This script:
  1. Registers a test user (handles 409 if already exists)
  2. Logs in and extracts the JWT access token
  3. Writes the token to zap-auth-token.txt (for ZAP authenticated scans)
  4. Sets GitHub Actions output if running in CI
  5. Validates DAST-05: every protected endpoint must reject
     unauthenticated / tampered / expired token requests with 401 or 403

Usage:
  python zap-auth-script.py --url http://localhost:8000
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sys
import time

import httpx

# ── Attempt to import PyJWT for crafting expired tokens ─────────────────────
try:
    import jwt as pyjwt  # PyJWT
except ImportError:
    pyjwt = None

# ── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("dast-auth")

# ── Constants ───────────────────────────────────────────────────────────────

TEST_USER = {
    "email": "dast-tester@example.com",
    "username": "dast_tester",
    "password": "D@stT3st!Secure#2024xK",
    "role": "Buyer",
}

PROTECTED_ENDPOINTS: list[tuple[str, str]] = [
    ("GET", "/auth/me"),
    ("POST", "/auth/logout"),
    ("GET", "/users/"),
    ("POST", "/products/"),
    ("GET", "/orders/"),
    ("POST", "/orders/"),
]

TOKEN_FILE = "zap-auth-token.txt"
RESULTS_FILE = "dast-05-results.json"


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_tampered_token(token: str) -> str:
    """Return *token* with its last 5 characters replaced."""
    if len(token) <= 5:
        return "XXXXX"
    suffix = token[-5:]
    replacement = "".join(
        chr(ord(c) + 1) if c.isalpha() else "X" for c in suffix
    )
    return token[:-5] + replacement


def _make_expired_token() -> str:
    """Craft a JWT that expired 1 hour ago, signed with a wrong key."""
    if pyjwt is None:
        log.warning("PyJWT not installed – using static dummy expired token")
        return "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwiZXhwIjoxfQ.invalid"
    payload = {
        "sub": "dast-tester@example.com",
        "exp": datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(hours=1),
        "iat": datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(hours=2),
    }
    return pyjwt.encode(payload, "wrong-key", algorithm="HS256")


def _request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict | None = None,
) -> httpx.Response:
    """Send an HTTP request and return the response (no exceptions)."""
    return client.request(
        method,
        url,
        headers=headers or {},
        json=json_body,
        timeout=15.0,
    )


# ── Registration & Login ───────────────────────────────────────────────────


def register_user(client: httpx.Client, base_url: str) -> None:
    """Register the DAST test user.  409 = already exists → OK."""
    url = f"{base_url}/auth/register"
    log.info("Registering test user at %s", url)
    resp = _request(client, "POST", url, json_body=TEST_USER)
    if resp.status_code in (200, 201):
        log.info("✅ User registered successfully (HTTP %s)", resp.status_code)
    elif resp.status_code == 409:
        log.info("ℹ️  User already exists (HTTP 409) — continuing")
    else:
        log.error(
            "❌ Registration failed: HTTP %s – %s",
            resp.status_code,
            resp.text[:300],
        )
        sys.exit(1)


def login_user(client: httpx.Client, base_url: str) -> str:
    """Log in and return the access_token."""
    url = f"{base_url}/auth/login"
    log.info("Logging in at %s", url)
    credentials = {
        "email": TEST_USER["email"],
        "password": TEST_USER["password"],
    }
    resp = _request(client, "POST", url, json_body=credentials)
    if resp.status_code not in (200, 201):
        log.error(
            "❌ Login failed: HTTP %s – %s",
            resp.status_code,
            resp.text[:300],
        )
        sys.exit(1)

    data = resp.json()
    token = data.get("access_token")
    if not token:
        log.error("❌ No access_token in login response: %s", data)
        sys.exit(1)

    log.info("✅ Login successful — token length: %d chars", len(token))
    return token


def persist_token(token: str) -> None:
    """Write token to file and optionally to GitHub Actions output."""
    with open(TOKEN_FILE, "w") as fh:
        fh.write(token)
    log.info("📝 Token written to %s", TOKEN_FILE)

    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a") as fh:
            fh.write(f"auth_token={token}\n")
        log.info("📝 Token written to $GITHUB_OUTPUT")


# ── DAST-05 Validation ─────────────────────────────────────────────────────


def validate_dast05(client: httpx.Client, base_url: str, valid_token: str) -> bool:
    """
    Validate that all protected endpoints reject unauthenticated,
    tampered-token, and expired-token requests.

    Returns True if ALL checks pass.
    """
    log.info("═" * 70)
    log.info("DAST-05 — Authentication Bypass Validation")
    log.info("═" * 70)

    tampered_token = _make_tampered_token(valid_token)
    expired_token = _make_expired_token()

    scenarios: list[tuple[str, dict[str, str] | None]] = [
        ("no_auth", None),
        ("tampered_token", {"Authorization": f"Bearer {tampered_token}"}),
        ("expired_token", {"Authorization": f"Bearer {expired_token}"}),
    ]

    results: list[dict] = []
    all_pass = True

    for method, path in PROTECTED_ENDPOINTS:
        url = f"{base_url}{path}"
        endpoint_results: dict = {
            "method": method,
            "path": path,
            "scenarios": {},
        }

        for scenario_name, headers in scenarios:
            resp = _request(client, method, url, headers=headers)
            status = resp.status_code
            passed = status in (401, 403)

            endpoint_results["scenarios"][scenario_name] = {
                "status_code": status,
                "passed": passed,
            }

            icon = "✅" if passed else "❌"
            log.info(
                "  %s %s %-5s  %-16s → HTTP %d  %s",
                icon,
                method,
                path,
                f"({scenario_name})",
                status,
                "PASS" if passed else "FAIL",
            )

            if not passed:
                all_pass = False

        results.append(endpoint_results)

    # ── Summary ─────────────────────────────────────────────────────────────
    log.info("─" * 70)
    total_checks = len(PROTECTED_ENDPOINTS) * len(scenarios)
    passed_checks = sum(
        1
        for r in results
        for s in r["scenarios"].values()
        if s["passed"]
    )
    log.info(
        "DAST-05 Summary: %d / %d checks passed  %s",
        passed_checks,
        total_checks,
        "✅ ALL PASS" if all_pass else "❌ SOME FAILED",
    )
    log.info("─" * 70)

    # ── Persist results ─────────────────────────────────────────────────────
    summary = {
        "test_id": "DAST-05",
        "description": "Authentication Bypass Validation",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_checks": total_checks,
        "passed_checks": passed_checks,
        "overall_pass": all_pass,
        "endpoints": results,
    }
    with open(RESULTS_FILE, "w") as fh:
        json.dump(summary, fh, indent=2)
    log.info("📝 Results written to %s", RESULTS_FILE)

    return all_pass


# ── CLI ─────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DAST Authentication & DAST-05 Validation Script",
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Base URL of the marketplace API (default: http://localhost:8000)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_url = args.url.rstrip("/")

    log.info("🚀 DAST Auth Script starting — target: %s", base_url)
    start = time.monotonic()

    with httpx.Client(follow_redirects=True) as client:
        # Step 1 – Register
        register_user(client, base_url)

        # Step 2 – Login
        token = login_user(client, base_url)

        # Step 3 – Persist token
        persist_token(token)

        # Step 4 – DAST-05 validation
        all_pass = validate_dast05(client, base_url, token)

    elapsed = time.monotonic() - start
    log.info("⏱  Completed in %.1f s", elapsed)

    if not all_pass:
        log.error("❌ DAST-05 FAILED — some endpoints are not properly protected")
        sys.exit(1)

    log.info("✅ DAST-05 PASSED — all protected endpoints reject unauthorized access")
    sys.exit(0)


if __name__ == "__main__":
    main()
