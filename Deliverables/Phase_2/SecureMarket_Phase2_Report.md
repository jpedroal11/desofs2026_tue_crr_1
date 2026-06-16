# SecureMarket — Phase 2 Implementation Report

**Course:** DESOFS — Secure Software Development
**Programme:** MSc in Cybersecurity and Systems Administration, ISEP
**Phase:** 2 — Secure Implementation
**Date:** 2026-06-16

| Team Member | Student No. |
|---|---|
| José Pedro Leal | 1211066 |
| Pedro Dinis Nunes | 1250543 |
| Mário Baptista | 1211265 |
| Diogo Teixeira | 1070370 |

> **Phase 1 reference:** the threat model, security requirements (SR-*), abuse cases
> (AC-*) and test plan (MST-*) this report implements are defined in
> [Phase1/Secure_Market_Report.pdf](../Phase1/Secure_Market_Report.pdf).
> The OWASP ASVS v5.0 coverage spreadsheet is in
> [ASVS_5_0_Tracker_SecureMarket.xlsx](ASVS_5_0_Tracker_SecureMarket.xlsx).

---

## 1. Purpose & Scope

Phase 1 produced the *design*: requirements, STRIDE/DREAD threat model, secure
architecture and a security test plan. **Phase 2 is the working implementation of
that design.** This report documents what was actually built, traces each Phase 1
security requirement to the code that satisfies it, summarises the automated and
manual security testing, and — in the interest of an honest engineering report —
lists the places where the implementation deviates from the original design.

The application is **SecureMarket**, a back-end marketplace REST API where
**Sellers** list products (with images), **Buyers** browse, order and review them,
and **Admins** manage the platform. The runnable code lives in
[Project/marketplace/](Project/marketplace/).

---

## 2. Technology Stack (as built)

| Concern | Choice |
|---|---|
| Language / runtime | Python 3.11 (container), 3.12 supported |
| Web framework | FastAPI + Uvicorn |
| Persistence | SQLAlchemy 2.0 ORM (`Mapped[...]` style), PostgreSQL 16 (SQLite for tests) |
| Validation | Pydantic v2 + `pydantic-settings` |
| AuthN crypto | PyJWT (HS256), `bcrypt` |
| Files | Local filesystem (UUID-named), ReportLab for invoice PDFs |
| Edge | Nginx reverse proxy (TLS termination) |
| Packaging | Docker + Docker Compose (dev & prod stacks) |
| CI/CD | GitHub Actions (SAST, SCA, DAST, SBOM, build, deploy) |

**Design note — PyJWT over python-jose:** the team's early prototype used
`python-jose`, which is effectively abandoned and carries unfixable transitive
CVEs. The auth subsystem was rebuilt on PyJWT, and `SECRET_KEY`/`DATABASE_URL` are
**required settings with no fallback defaults** ([core/config.py](Project/marketplace/core/config.py))
so the app cannot start with a known-default signing key.

---

## 3. Project Structure

```
Project/marketplace/
├── main.py                  # App wiring, CORS, lifespan, X-Forwarded-For context
├── core/
│   ├── config.py            # Pydantic settings; required SECRET_KEY / DATABASE_URL
│   ├── security.py          # JWT issue/decode (PyJWT) + bcrypt helpers
│   ├── roles.py             # Administrator / Seller / Buyer enum
│   ├── dependencies.py      # DB session + engine
│   ├── image_service.py     # Magic-byte/MIME validation, UUID naming, path safety
│   └── request_context.py   # Per-request client IP (for audit log)
├── middleware/
│   └── auth.py              # JWT validation + RBAC + blacklist as FastAPI deps
├── models/models.py         # SQLAlchemy models (UUID PKs)
├── schemas/schemas.py       # Pydantic request/response + password policy
├── routers/                 # auth, users, products, orders, images
├── services/
│   ├── auth_service.py      # Registration, login, logout, refresh, password reset
│   ├── pwned.py             # HIBP k-anonymity breach check
│   ├── image_use_case.py    # Upload orchestration (ownership, quota, count)
│   ├── invoice_service.py   # ReportLab PDF invoice generation
│   └── log_service.py       # Audit-log writer
├── repositories/            # Image repository queries
├── database/script.sql      # Hand-managed schema + least-privilege audit DB user
├── nginx/                   # TLS reverse-proxy config + dev cert generation
├── docker-compose.dev.yml   # HTTP dev stack
├── docker-compose.prod.yml  # Nginx-fronted TLS prod stack
├── tests/                   # ~149 unit/integration/abuse tests
└── zap/                     # OWASP ZAP rules + auth script for DAST
```

---

## 4. Architecture as Implemented

The Phase 1 four-layer DDD design (API → Application → Domain → Infrastructure) is
realised as a layered FastAPI service:

- **API layer** — routers under [routers/](Project/marketplace/routers/) stay thin:
  they validate input via Pydantic, call a service, and map domain exceptions to
  HTTP status codes.
- **Application/Domain layer** — business rules live in
  [services/](Project/marketplace/services/) (auth, image upload, invoices) and in
  the routers' service-level ownership checks. Auth errors are modelled as a typed
  `AuthError` hierarchy so the HTTP layer maps them cleanly (e.g. generic `401` for
  both wrong-password and unknown-email → no user enumeration).
- **Infrastructure layer** — SQLAlchemy repositories/queries, the filesystem image
  service, and the audit-log writer.

**Per-request security chain.** Authentication and authorization are implemented as
**FastAPI dependencies** rather than a global middleware, so every protected route
opts in explicitly and there is no public-path allow-list to drift out of sync
([middleware/auth.py](Project/marketplace/middleware/auth.py)):

1. `get_current_user` — validates the Bearer JWT signature/expiry, checks the
   `jti` is not blacklisted, rejects tokens issued before the user's
   `tokens_valid_from` revocation cut-off, and confirms the account is active.
2. `require_role(...)` — RBAC check against the roles claim; logs every denial.
3. Resource-level ownership checks inside the route/service (e.g. a seller may only
   modify their own product; a buyer may only read their own order).

**Deployment topology (prod).** Only Nginx publishes ports 80/443; the app and
PostgreSQL stay on an internal Docker network and are never reachable from the host
([docker-compose.prod.yml](Project/marketplace/docker-compose.prod.yml)).

---

## 5. Security Controls — Requirement → Implementation Traceability

Status legend: ✅ implemented · ◑ partial / deviates · ⚪ not implemented (see §8).

### 5.1 Authentication & Session Management (SR-AUTH)

| Req | Control | Where | Status |
|---|---|---|---|
| SR-AUTH-01 | Email + password auth required for protected resources | [middleware/auth.py](Project/marketplace/middleware/auth.py), [routers/auth.py](Project/marketplace/routers/auth.py) | ✅ |
| SR-AUTH-02 | Passwords hashed (bcrypt), never stored/logged in plaintext | [core/security.py](Project/marketplace/core/security.py) | ✅ |
| SR-AUTH-03 | Password complexity ≥12 chars, upper/lower/digit/special | [schemas/schemas.py](Project/marketplace/schemas/schemas.py) `_validate_password_strength` | ✅ |
| SR-AUTH-04 | Breached-password check (HIBP k-anonymity) on register + reset | [services/pwned.py](Project/marketplace/services/pwned.py), [services/auth_service.py](Project/marketplace/services/auth_service.py) | ✅ |
| SR-AUTH-05 | Short-lived access + longer refresh tokens | [core/security.py](Project/marketplace/core/security.py) | ◑ refresh = 7 d ✅; access default **30 min** (design said ≤15 min) |
| SR-AUTH-06 | Strong signing (HS256, 256-bit secret), secret never hardcoded | [core/security.py](Project/marketplace/core/security.py), [core/config.py](Project/marketplace/core/config.py) | ✅ |
| SR-AUTH-07 | Account lockout after 5 failed attempts (30-minute lock) | [services/auth_service.py](Project/marketplace/services/auth_service.py) | ✅ |
| SR-AUTH-08 | Invalidate sessions on password change / deactivation | `tokens_valid_from` cut-off + `TokenBlacklist` | ✅ |
| SR-AUTH-09 | Login rate-limited per IP and per account | account lockout only | ◑ lockout ✅; **per-IP/min rate limiting not implemented** |
| SR-AUTH-10 | All auth events logged (ts, user, IP, result) | [services/log_service.py](Project/marketplace/services/log_service.py) | ✅ |

Additional hardening beyond the strict requirement list:
- **No user enumeration / constant-time login** — login always runs bcrypt, using a
  dummy hash when the email is unknown, so response timing and the generic `401` do
  not reveal whether an email is registered.
- **Refresh-token rotation** — each `/auth/refresh` blacklists the presented refresh
  token and issues a new pair, so a stolen-but-rotated token fails on reuse.
- **Single-use password-reset tokens** — only the **SHA-256 hash** is stored, with a
  30-minute TTL, and a successful reset bumps `tokens_valid_from` to kill all live
  sessions.

### 5.2 Authorization & Access Control (SR-AUTHZ)

| Req | Control | Where | Status |
|---|---|---|---|
| SR-AUTHZ-01 | RBAC with Administrator / Seller / Buyer | [core/roles.py](Project/marketplace/core/roles.py), [middleware/auth.py](Project/marketplace/middleware/auth.py) | ✅ |
| SR-AUTHZ-02 | Role-level **and** resource-level checks per endpoint | routers + `require_role` | ✅ |
| SR-AUTHZ-03 | Users cannot change their own role | self-update schema exposes only `full_name`; public register rejects `Administrator` | ✅ |
| SR-AUTHZ-04 | Buyers see only their own orders | [routers/orders.py](Project/marketplace/routers/orders.py) | ✅ |
| SR-AUTHZ-05 | Sellers modify only their own products | [routers/products.py](Project/marketplace/routers/products.py), [services/image_use_case.py](Project/marketplace/services/image_use_case.py) | ✅ |
| SR-AUTHZ-06 | Buyers see only ACTIVE products; drafts hidden (404) | [routers/products.py](Project/marketplace/routers/products.py) `get_product` | ✅ |
| SR-AUTHZ-07 | Authorization failures logged | audit-log calls on every 403 path | ✅ |
| SR-AUTHZ-08 | UUID v4 for all resource identifiers | [models/models.py](Project/marketplace/models/models.py), [database/script.sql](Project/marketplace/database/script.sql) | ✅ |

### 5.3 Data Security & Integrity (SR-DATA)

| Req | Control | Where | Status |
|---|---|---|---|
| SR-DATA-01 | Files stored under randomized UUID names; originals only in DB | [core/image_service.py](Project/marketplace/core/image_service.py), [services/invoice_service.py](Project/marketplace/services/invoice_service.py) | ✅ |
| SR-DATA-02 | SHA-256 computed & stored for images; verified on download | [core/image_service.py](Project/marketplace/core/image_service.py) | ◑ computed/stored ✅; **not re-verified on serve** |
| SR-DATA-03 | Files outside web root, served via API only | filesystem `uploads/`, not proxied statically | ✅ |
| SR-DATA-04 | File permissions 0640 | `save_file` `os.chmod(..., 0o640)` | ✅ |
| SR-DATA-05 | Encryption at rest | deployment-dependent (GCP volume) | ◑ deployment-level |
| SR-DATA-06/07 | Prices snapshotted server-side; client totals never trusted | [routers/orders.py](Project/marketplace/routers/orders.py) — order schema accepts only `product_id`+`quantity` | ✅ (strong) |
| SR-DATA-08 | Secrets never in logs / error responses | audit messages carry no secrets; generic error details | ✅ |
| SR-DATA-09 | Per-seller storage quota (200 MB) | [services/image_use_case.py](Project/marketplace/services/image_use_case.py) | ✅ |
| SR-DATA-10 | DB-level locking on stock decrement | plain read-modify-write | ⚪ **no `SELECT … FOR UPDATE`** |

The server-side price snapshot (SR-DATA-06/07) directly neutralises the
Critical-rated **price manipulation** threat (T-P4-01): the order API has no field
through which a client could supply a price — `unit_price` is read from the product
row at order time.

### 5.4 Communication Security (SR-COMM)

Implemented at the Nginx edge ([nginx/nginx.conf](Project/marketplace/nginx/nginx.conf)):

| Req | Control | Status |
|---|---|---|
| SR-COMM-01 | TLS 1.2/1.3 only; HTTP→HTTPS 301 redirect | ✅ |
| SR-COMM-02 | HSTS `max-age=63072000; includeSubDomains; preload` | ✅ |
| SR-COMM-03 | DB connections over TLS (`sslmode=require`) | ◑ via `DATABASE_URL`; not pinned in the sample compose |
| SR-COMM-04 | CORS allow-list from env, no wildcard | ✅ ([main.py](Project/marketplace/main.py)) |
| SR-COMM-05 | Security headers (nosniff, X-Frame DENY, CSP `default-src 'none'`) | ✅ |

Extra edge hardening: `server_tokens off`, a `444` default-server that drops
unexpected `Host` headers (anti host-injection / cache-poisoning), `Referrer-Policy:
no-referrer`, modern cipher suite, and `client_max_body_size 10m` so oversized
uploads are rejected before they reach the app.

### 5.5 Input Validation & Data Handling (SR-INPUT)

| Req | Control | Where | Status |
|---|---|---|---|
| SR-INPUT-01 | All inputs validated via Pydantic | [schemas/schemas.py](Project/marketplace/schemas/schemas.py) | ✅ |
| SR-INPUT-02 | Image validated by extension **and** magic bytes; MIME allow-list | [core/image_service.py](Project/marketplace/core/image_service.py) | ✅ |
| SR-INPUT-03 | Max upload size 10 MB (API + edge) | [routers/images.py](Project/marketplace/routers/images.py) + nginx | ✅ |
| SR-INPUT-04 | Server-side UUID paths; user filenames never used; path checked in root | [core/image_service.py](Project/marketplace/core/image_service.py) `build_safe_path` | ✅ |
| SR-INPUT-05 | Template injection prevention in invoices | invoices use **ReportLab** (no template engine) | ✅ (vector removed by design) |
| SR-INPUT-06 | Strip HTML from user text (bleach) | — | ⚪ not applied (see §8) |
| SR-INPUT-07 | ORM-only, parameterized queries; no raw SQL | SQLAlchemy throughout | ✅ |
| SR-INPUT-08 | List endpoints paginated, max page size 50 | `skip`/`limit` (default 20), **no hard cap** | ◑ partial |
| SR-INPUT-09 | Price > 0; stock ≥ 0 | [schemas/schemas.py](Project/marketplace/schemas/schemas.py) validators | ✅ |

The path-safety layer is defence-in-depth: it rejects `..`, absolute prefixes, null
bytes **and** symlink targets, then re-resolves the absolute path and confirms it is
still inside the upload root before writing (atomic temp-write + rename).

### 5.6 Third-Party Components (SR-3RD)

| Req | Control | Status |
|---|---|---|
| SR-3RD-01 | Dependencies pinned to specific versions | ◑ [requirements.txt](Project/marketplace/requirements.txt) uses `>=` ranges, not exact `==` pins |
| SR-3RD-02 | `pip-audit` in CI; build fails on critical CVEs | ✅ ([.github/workflows/sca-scan.yml](../../.github/workflows/sca-scan.yml)) |
| SR-3RD-03 | SBOM generated per release | ✅ CycloneDX ([.github/workflows/sbom-cyclonedx.yml](../../.github/workflows/sbom-cyclonedx.yml)) |
| SR-3RD-04 | Minimal base image, scanned with Trivy | ◑ `python:slim` base + non-root user ✅; **Trivy container scan not in pipeline** |
| SR-3RD-05 | No dev/debug deps in production image | ✅ |

### 5.7 Logging & Monitoring (SR-LOG)

| Req | Control | Where | Status |
|---|---|---|---|
| SR-LOG-01 | Immutable audit log of state-changing ops (user, action, resource, ts, IP, result) | [models/models.py](Project/marketplace/models/models.py) `AuditLog`, [services/log_service.py](Project/marketplace/services/log_service.py) | ✅ |
| SR-LOG-02 | Audit DB user has INSERT/SELECT only (no UPDATE/DELETE) | [database/script.sql](Project/marketplace/database/script.sql) `log_writer` grants | ✅ |
| SR-LOG-03 | Auth, CRUD, file ops, status changes, authz failures logged | audit calls across all routers | ✅ |
| SR-LOG-04 | No passwords/tokens/file contents in logs | audit messages carry IDs and outcomes only | ✅ |

Client IP is captured per request from `X-Forwarded-For` (set by the trusted proxy)
via a context var ([core/request_context.py](Project/marketplace/core/request_context.py)),
so audit entries record the real client address behind the reverse proxy.

### 5.8 Business Logic Security (SR-BIZ)

| Req | Control | Where | Status |
|---|---|---|---|
| SR-BIZ-01 | Reviews only by buyers with a DELIVERED order for the product | [routers/products.py](Project/marketplace/routers/products.py) `create_review` | ✅ |
| SR-BIZ-02 | At most one review per buyer per product | app-level check | ◑ enforced in code; **no DB unique constraint** |
| SR-BIZ-03 | Order status follows the state machine | [routers/orders.py](Project/marketplace/routers/orders.py) `_is_valid_status_transition` | ◑ enforced, but allows `pending→delivered` directly |
| SR-BIZ-04 | Only PENDING orders cancellable by buyer | code also allows cancelling `confirmed` | ◑ deviates |
| SR-BIZ-05 | Only ACTIVE products with stock can be ordered | [routers/orders.py](Project/marketplace/routers/orders.py) | ✅ |
| SR-BIZ-07 | Max 10 images per product | [services/image_use_case.py](Project/marketplace/services/image_use_case.py) | ✅ |

---

## 6. Secure SDLC — CI/CD Pipeline (as built)

GitHub Actions workflows under [.github/workflows/](../../.github/workflows/):

| Stage | Tool | Workflow |
|---|---|---|
| SAST | Bandit | [sast-scan.yml](../../.github/workflows/sast-scan.yml) |
| SCA | pip-audit | [sca-scan.yml](../../.github/workflows/sca-scan.yml) |
| DAST (passive) | OWASP ZAP Baseline | [dast-baseline.yml](../../.github/workflows/dast-baseline.yml) |
| DAST (active) | OWASP ZAP API scan (OpenAPI-driven) | [dast-api-scan.yml](../../.github/workflows/dast-api-scan.yml) |
| TLS testing | testssl.sh | [dast-tls-scan.yml](../../.github/workflows/dast-tls-scan.yml) |
| SBOM | CycloneDX (validated, attached per release) | [sbom-cyclonedx.yml](../../.github/workflows/sbom-cyclonedx.yml) |
| Build/Test/Deploy | pytest + Docker build/push | [ci.yml](../../.github/workflows/ci.yml) |

DAST is reproducible locally via [zap/dast-docker-compose.yml](Project/marketplace/zap/dast-docker-compose.yml)
with custom rule sets and an authenticated ZAP script. Dependency updates are
automated with Dependabot ([.github/dependabot.yml](../../.github/dependabot.yml)).

Relative to the Phase 1 plan, the implemented pipeline covers SAST, SCA, both DAST
modes, TLS scanning and SBOM. **Not yet wired in:** Semgrep rule packs and Trivy
container/image scanning (see §8).

---

## 7. Testing

The suite contains **~149 test functions across ~3,400 lines** in
[Project/marketplace/tests/](Project/marketplace/tests/):

| Area | File | Tests |
|---|---|---|
| Authentication | [test_auth.py](Project/marketplace/tests/test_auth.py) | 35 |
| Manual security tests (abuse cases) | [test_mst_auth_authz.py](Project/marketplace/tests/test_mst_auth_authz.py) | 14 |
| Authorization | [test_authz.py](Project/marketplace/tests/test_authz.py) | 4 |
| Business logic | [test_business.py](Project/marketplace/tests/test_business.py) | 5 |
| Images | [test_images.py](Project/marketplace/tests/test_images.py) | 44 |
| Orders | [test_orders.py](Project/marketplace/tests/test_orders.py) | 12 |
| Products | [test_products.py](Project/marketplace/tests/test_products.py) | 14 |
| Users | [test_users.py](Project/marketplace/tests/test_users.py) | 10 |
| Middleware/deps | [test_middleware_deps.py](Project/marketplace/tests/test_middleware_deps.py) | 7 |

These cover the Phase 1 abuse cases (MST-*): brute-force lockout, IP/JWT tampering,
IDOR on orders and products, role-parameter tampering, function-level access control,
draft-product access, **server-side price integrity** (client-supplied price
ignored), oversell prevention, review-without-purchase, duplicate-review, invalid
status transitions, and the full image abuse set (path traversal, magic-byte
mismatch, image-count/quota limits, direct-path access).

> **Honest caveat on concurrency:** `test_business.py` documents that true
> stock-race testing needs database-level locking (`SELECT … FOR UPDATE`), which is
> not exercisable on in-memory SQLite — consistent with the SR-DATA-10 gap in §8.

Run the suite from `Project/marketplace/`:

```bash
pip install -r requirements.txt -r requirements-dev.txt
export SECRET_KEY="$(openssl rand -hex 32)" DATABASE_URL="sqlite:///./test.db" APP_ENV=development
pytest
```

---

## 8. Deviations & Known Gaps

Recorded transparently so they can be prioritised in a future sprint.

| # | Gap | Requirement | Impact / Notes |
|---|---|---|---|
| 1 | Access-token TTL defaults to 30 min | SR-AUTH-05 | Design specified ≤15 min; widen the damage window. One-line config change. |
| 2 | No per-IP/per-account request rate limiting | SR-AUTH-09, NFR-04 | Account lockout mitigates credential brute-force, but there is no `429`/min throttle (no `limit_req` in Nginx, no slowapi). |
| 3 | Stock decrement uses read-modify-write, no row lock | SR-DATA-10, T-P4-05 | Concurrent confirmations could oversell. Add `SELECT … FOR UPDATE` (Postgres). |
| 4 | Image SHA-256 stored but not re-verified on download | SR-DATA-02 | Tamper detection on retrieval not yet enforced. |
| 5 | User-supplied text not HTML-sanitized (no bleach) | SR-INPUT-06 | Lower risk: this is a JSON API with no server-rendered HTML, and invoices use ReportLab (no template engine), so SSTI/T-P6-01 is structurally removed; XSS stripping deferred to any future frontend. |
| 6 | Pagination has no hard max page size | SR-INPUT-08 | `limit` is uncapped; add a 50-item ceiling. |
| 7 | Dependencies use `>=` ranges, not exact pins | SR-3RD-01 | Reduces build reproducibility; pin with `==` + hashes. |
| 8 | No Trivy container scan / Semgrep in CI | SR-3RD-04, test plan | SAST (Bandit) and SCA (pip-audit) are present; container-image scanning is not. |
| 9 | One-review-per-product enforced only in code | SR-BIZ-02 | Add a DB `UNIQUE(product_id, buyer_id)` constraint to close the race. |
| 10 | Order state machine permits `pending→delivered`; cancel allowed on `confirmed` | SR-BIZ-03/04 | More permissive than the Phase 1 spec; tighten the transition table. |
| 11 | DB `sslmode=require` not pinned in sample compose | SR-COMM-03 | Configurable through `DATABASE_URL`; enforce it explicitly. |

---

## 9. Running the Application

Full operational instructions are in the project README
([Project/marketplace/README.md](Project/marketplace/README.md)); GCP deployment is
documented in [docs/DEPLOYMENT_GCP.md](../../docs/DEPLOYMENT_GCP.md).

```bash
cd Project/marketplace

# Dev stack — HTTP, Swagger UI enabled
docker compose -f docker-compose.dev.yml up --build      # → http://localhost:8000/docs

# Prod stack — Nginx TLS edge, HSTS/CSP, /docs disabled
cp .env.example .env            # fill in real secrets
./nginx/generate-dev-certs.sh   # self-signed staging certs
docker compose -f docker-compose.prod.yml up --build     # → https://localhost/
```

`SECRET_KEY` and `DATABASE_URL` are mandatory — the app refuses to start without
them, by design.

---

## 10. Phase 1 → Phase 2 Traceability Summary

| ASVS v5.0 area | SR group | Phase 2 status |
|---|---|---|
| V6 Authentication | SR-AUTH | ✅ core controls; ◑ token TTL & rate limiting |
| V7 Session Mgmt | SR-AUTH-08 | ✅ blacklist + revocation cut-off |
| V8 Authorization | SR-AUTHZ | ✅ RBAC + resource-level ownership |
| V11 Cryptography | SR-AUTH-02/06, SR-DATA-02 | ✅ bcrypt, HS256; ◑ download integrity |
| V12 Secure Comms | SR-COMM | ✅ TLS/HSTS/CSP; ◑ DB TLS pinning |
| V1/V2 Validation | SR-INPUT | ✅ Pydantic, file validation; ◑ sanitization/pagination |
| V5 File Handling | SR-DATA-01/04, SR-INPUT-04 | ✅ UUID names, 0640, path safety |
| V14 Config / Supply chain | SR-3RD | ◑ SAST/SCA/SBOM present; pinning & Trivy pending |
| V16 Logging | SR-LOG | ✅ append-only audit log, least-privilege writer |
| V2 Business Logic | SR-BIZ | ✅ price integrity, review rules; ◑ state machine strictness |
