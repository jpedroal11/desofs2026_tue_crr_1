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
  - Fail-fast on test failures to block deployments with broken code

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

---

## Accessing Reports

1. **In Pull Requests:**
   - Check the **Checks** tab to view workflow results
   - Blocking workflows must pass before merge

2. **After Merge:**
   - Navigate to **Actions** tab to view workflow run details
   - Click on a specific run to download artifacts (under "Artifacts" section)

3. **Reports Retention:**
   - Scan reports: 14 days
   - SBOM: 90 days

---

## Local Development

To run these checks locally before pushing:

```bash
# Install tools
pip install bandit[toml] semgrep pip-audit cyclonedx-bom

# Run Bandit
bandit --recursive . --severity-level medium --confidence-level medium

# Run Semgrep
semgrep scan --config "p/python" --config "p/flask" --config "p/owasp-top-ten" --config "p/secrets" .

# Run pip-audit
pip-audit --requirement Phase_2/Project/marketplace/requirements.txt

# Run tests with coverage
cd Phase_2/Project/marketplace
pytest tests/ --cov=. --cov-report=term-missing
```

---

## Maintenance & Customization

- **Modify triggers:** Edit `on:` section in workflow files (branches, events)
- **Adjust severity thresholds:** Update `--severity-level`, `--confidence-level` flags
- **Skip specific checks:** Add exclusion patterns or disable specific scan rulesets
- **Update Python version:** Change `python-version` in workflow files (currently 3.11)

For changes to Dependabot schedules or labels, edit `.github/dependabot.yml`.
