"""HaveIBeenPwned Passwords API — k-anonymity range query.

How it works (privacy-preserving):
  1. SHA-1 hash the password locally
  2. Send only the first 5 hex characters of the hash to HIBP
  3. HIBP returns ~500 hash suffixes that share that prefix
  4. We check locally whether our full hash matches any of them
  5. The password (or its full hash) never leaves this server

If HIBP is unreachable we fail OPEN (return False) — a third-party outage
should not block registration. The breach check is defence-in-depth, not the
primary protection.
"""

import hashlib
import logging

import httpx

logger = logging.getLogger(__name__)

HIBP_URL = "https://api.pwnedpasswords.com/range/{prefix}"
TIMEOUT_SECONDS = 5
USER_AGENT = "SecureMarket-DESOFS/1.0"


async def is_password_breached(password: str) -> bool:
    # SHA-1 is mandated by the HIBP API protocol (k-anonymity range query).
    # It is NOT used for password storage — that is bcrypt, in core.security.
    sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()  # nosec B324
    prefix, suffix = sha1[:5], sha1[5:]

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.get(
                HIBP_URL.format(prefix=prefix),
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("HIBP unreachable, allowing password through: %s", exc)
        return False

    for line in resp.text.splitlines():
        returned_suffix, _, count = line.partition(":")
        if returned_suffix.strip() == suffix:
            logger.warning("Breached password detected (seen %s times)", count.strip())
            return True

    return False
