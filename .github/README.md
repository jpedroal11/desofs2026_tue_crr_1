# GitHub Workflows & Security Scans

This document outlines all automated workflows and security scans configured for this repository.

## Workflows Overview

### 1. **CI/CD Workflow** (`workflows/ci.yml`)
**Triggers:** Push to `main`/`develop`, Pull Requests, Manual dispatch

Automated testing and Docker image deployment pipeline:

- **Test Job**
  - Runs pytest with coverage reporting on Python 3.11
  - Tests located in `Phase_2/Project/marketplace/tests/`
  - Generates XML coverage report and uploads as artifact (14-day retention)
  - Deploy job blocked on test failure via `needs: test` dependency

- **Deploy Job** (runs after test passes)
  - Only triggers on successful pushes to `main` branch
  - Builds and pushes Docker image to GitHub Container Registry (GHCR)
  - Tags images with `latest` (for main branch) and commit SHA
  - Requires `packages:write` permission

**Configuration:**
- Python version: 3.11
- Working directory: `Phase_2/Project/marketplace`
- Concurrency: Cancels in-progress runs when new push occurs

---

### 2. **SAST Scanning Workflow** (`workflows/sast-scan.yml`)
**Triggers:** Push to `main`/`develop`, Pull Requests, Manual dispatch

Static Application Security Testing (SAST) with two complementary tools:

#### **Bandit**
- Detects common security issues in Python code
- Severity filter: Medium and above for reporting, High-only for blocking
- Confidence filter: Medium and above
- Excludes: `.git`, virtual environments, test directories
- Non-blocking: Generates JSON report artifact for review

#### **Semgrep**
- Pattern-based security analysis with rulesets for:
  - Python/Flask best practices
  - OWASP Top 10 vulnerabilities
  - Secrets detection (API keys, credentials, etc.)
- Generates JSON report for metrics and non-blocking issues
- Blocking job fails on security findings to prevent merges with high-risk code

**Artifacts:** Both tools upload JSON reports (14-day retention)

---

### 3. **SCA Scanning Workflow** (`workflows/sca-scan.yml`)
**Triggers:** Push/PR to `main` branch only

Software Composition Analysis (SCA) for dependency vulnerabilities:

#### **pip-audit**
- Scans Python dependencies from `Phase_2/Project/marketplace/requirements.txt`
- Identifies known CVEs in direct and transitive dependencies
- Generates JSON report for tracking and non-blocking review
- Fails hard on any detected CVE to prevent vulnerable dependencies in production

**Artifacts:** CVE report (14-day retention)

---

### 4. **SBOM Generation Workflow** (`workflows/sbom-cyclonedx.yml`)
**Triggers:** Push to `main`/`develop`, Version tags (`v*`), Manual dispatch, Pull Requests

Software Bill of Materials (SBOM) generation for supply chain transparency:

- **SBOM Creation**
  - Uses CycloneDX format (industry-standard XML and JSON)
  - Captures all Python dependencies with versions and vulnerability metadata
  - Includes lock file (`requirements-lock.txt`) for reproducibility

- **SBOM Validation**
  - Validates generated SBOM against CycloneDX schema
  - Fails on structural errors

- **Release Integration**
  - For version tags: Automatically attaches SBOM to GitHub releases
  - Enables supply chain traceability for consumers

**Artifacts:**
- `sbom-cyclonedx.json` - SBOM in JSON format
- `requirements-lock.txt` - Exact dependency versions
- Retention: 90 days

---

## Dependency Management

### **Dependabot Configuration** (`dependabot.yml`)

Automated dependency updates running **every Monday at 09:00 UTC+0 (Lisbon timezone)**:

#### **Python Dependencies**
- Location: `Phase_2/Project/marketplace`
- Labels: `dependencies`, `security`
- Commit prefix: `chore(deps)`
- Configuration: Ignores patch-only updates for non-security bumps
- PR limit: 10 open PRs maximum

#### **GitHub Actions**
- Keeps workflow actions up-to-date
- Labels: `dependencies`, `ci`
- Commit prefix: `chore(ci)`

**Benefits:**
- Automated security patches for vulnerabilities
- Reduces manual maintenance burden
- Controlled rollout (weekly, non-aggressive)

---

## Security & Compliance Summary

| Tool | Purpose | Blocking | Artifacts |
|------|---------|----------|-----------|
| **Bandit** | Python security (medium+ issues) | Partial (high-only) | JSON report |
| **Semgrep** | Pattern-based SAST, secrets detection | Yes | JSON report |
| **pip-audit** | CVE detection in dependencies | Yes | JSON report |
| **CycloneDX** | SBOM generation & validation | No | JSON/XML SBOM |
| **Dependabot** | Automated dependency updates | No | PRs for review |
| **ZAP Baseline** | DAST passive scan (headers, info leakage) | Yes | HTML + JSON report |
| **ZAP API Scan** | DAST active scan (SQLi, XSS, traversal, auth) | Yes | HTML + JSON report |
| **testssl.sh** | TLS configuration validation | Yes | JSON + CSV report |

---

## Accessing Reports

1. **In Pull Requests:**
   - Check the **Checks** tab to view workflow results
   - Blocking workflows must pass before merge

2. **After Merge:**
   - Navigate to **Actions** tab to view workflow run details
   - Click on a specific run to download artifacts (under "Artifacts" section)

3. **Reports Retention:**
   - SAST/SCA scan reports: 14 days
   - DAST scan reports: 30 days
   - SBOM: 90 days

---

## Dynamic Application Security Testing (DAST)

Three DAST workflows cover the seven test cases from Table 41:

| Test ID | Test | Scan Mode | Workflow |
|---------|------|-----------|----------|
| DAST-01 | SQL Injection on all parameters | Active (API Scan) | `dast-api-scan.yml` |
| DAST-02 | Reflected & Stored XSS | Active (API Scan) | `dast-api-scan.yml` |
| DAST-03 | Security Headers (HSTS, CSP, X-Frame-Options, etc.) | Passive (Baseline) | `dast-baseline.yml` |
| DAST-04 | Path Traversal | Active (API Scan) | `dast-api-scan.yml` |
| DAST-05 | Auth Bypass (no token / tampered / expired) | Active (Auth Script) | `dast-api-scan.yml` |
| DAST-06 | TLS Configuration (TLS 1.2+, ciphers, cert chain) | External | `dast-tls-scan.yml` |
| DAST-07 | Error Information Leakage | Passive + Live Probes | `dast-baseline.yml` |

### 5. **DAST Baseline Scan** (`workflows/dast-baseline.yml`)
**Triggers:** Push/PR to `main`/`develop`, Manual dispatch

Passive (non-intrusive) scan that runs on every build:

- Builds the Docker image and starts the app + Postgres
- Runs OWASP ZAP baseline scan with custom rule configuration
- **DAST-03:** Validates all 5 required security headers are present (HSTS, X-Content-Type-Options, X-Frame-Options, CSP, Cache-Control) — **build-breaking**
- **DAST-07:** Checks for information leakage + runs live error-response probes to detect stack traces
- Custom validation script parses results and generates a DAST summary report

**Configuration:** `Deliverables/Phase_2/Project/marketplace/zap/zap-baseline-rules.conf`
**Artifacts:** ZAP HTML/JSON reports + DAST summary (30-day retention)

---

### 6. **DAST API Scan** (`workflows/dast-api-scan.yml`)
**Triggers:** Manual dispatch (`workflow_dispatch`) — intended for sprint-end testing

Authenticated active scan using the FastAPI-generated OpenAPI spec:

- Registers a test user and obtains a JWT token
- Injects the token into all ZAP requests via the Replacer add-on
- **DAST-01:** SQL injection on all query, path, and body parameters — **build-breaking**
- **DAST-02:** Reflected and stored XSS on all text input fields — **build-breaking**
- **DAST-04:** Path traversal on all file-related endpoints — **build-breaking**
- **DAST-05:** Tests all protected endpoints with no auth, tampered token, and expired token — all must return 401/403
- Custom validation script categorizes ZAP alerts by DAST test ID

**Note on DAST-04:** ZAP's automated scanner covers common path traversal vectors. Edge cases (symlinks, OS-specific separators) require manual follow-up, as specified in Table 41 ("ZAP + Manual").

**Configuration:** `Deliverables/Phase_2/Project/marketplace/zap/zap-api-rules.conf`
**Artifacts:** ZAP HTML/JSON reports + DAST-05 auth results + DAST summary (30-day retention)

---

### 7. **DAST TLS Scan** (`workflows/dast-tls-scan.yml`)
**Triggers:** Manual dispatch with required `target_domain` input parameter

TLS/SSL configuration scan against the staging or production domain:

- Uses `testssl.sh` to scan the target domain
- **DAST-06:** Validates TLS 1.2+ is offered, no deprecated protocols (SSLv2/3, TLS 1.0/1.1), no weak ciphers (RC4, DES, 3DES, NULL, EXPORT, anon), valid certificate chain, and no known vulnerabilities (BEAST, DROWN, Heartbleed, etc.)
- Inline validation script produces a structured DAST-06 result

**Artifacts:** testssl.sh JSON/CSV + DAST-06 results (30-day retention)

**How to trigger:**
1. Go to **Actions** → **DAST – TLS Scan (testssl.sh)**
2. Click **Run workflow**
3. Enter the target domain (e.g., `staging.marketplace.example.com`)

---

### DAST Supporting Files

All DAST configuration and scripts live in `Deliverables/Phase_2/Project/marketplace/zap/`:

| File | Purpose |
|------|---------|
| `zap-baseline-rules.conf` | ZAP passive scan rule configuration (IGNORE/WARN/FAIL) |
| `zap-api-rules.conf` | ZAP active scan rule configuration (IGNORE/WARN/FAIL) |
| `dast-docker-compose.yml` | Docker Compose for local DAST testing |
| `zap-auth-script.py` | Authentication + DAST-05 token-tampering validation |
| `validate-dast-results.py` | ZAP results parser and DAST verdict engine |

---

## Local Development

To run these checks locally before pushing:

```bash
# Install tools
pip install bandit[toml] semgrep pip-audit cyclonedx-bom httpx

# Run Bandit
bandit --recursive . --severity-level medium --confidence-level medium

# Run Semgrep
semgrep scan --config "p/python" --config "p/flask" --config "p/owasp-top-ten" --config "p/secrets" .

# Run pip-audit
pip-audit --requirement Deliverables/Phase_2/Project/marketplace/requirements.txt

# Run tests with coverage
cd Deliverables/Phase_2/Project/marketplace
pytest tests/ --cov=. --cov-report=term-missing

# Run DAST locally (requires Docker)
cd Deliverables/Phase_2/Project/marketplace
docker compose -f zap/dast-docker-compose.yml up -d --build
# Wait for app to start, then:
python zap/zap-auth-script.py --url http://localhost:8000
# For ZAP scans, install and run ZAP Desktop or use the Docker image:
# docker run -t ghcr.io/zaproxy/zaproxy zap-baseline.py -t http://localhost:8000
docker compose -f zap/dast-docker-compose.yml down -v
```

---

## Maintenance & Customization

- **Modify triggers:** Edit `on:` section in workflow files (branches, events)
- **Adjust severity thresholds:** Update `--severity-level`, `--confidence-level` flags
- **Skip specific checks:** Add exclusion patterns or disable specific scan rulesets
- **Update Python version:** Change `python-version` in workflow files (currently 3.11)

For changes to Dependabot schedules or labels, edit `.github/dependabot.yml`.
