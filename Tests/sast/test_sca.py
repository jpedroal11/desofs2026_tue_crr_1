# tests/sast/test_sca.py
import subprocess

def test_no_critical_cves_in_dependencies():
    result = subprocess.run(
        ["pip-audit", "--format", "json"],
        capture_output=True, text=True
    )
    import json
    report = json.loads(result.stdout)
    critical = [
        v for v in report.get("vulnerabilities", [])
        if v.get("fix_versions")  # has a known fix = exploitable
    ]
    assert len(critical) == 0, \
        f"Critical CVEs found: {critical}"

def test_all_dependencies_pinned():
    with open("requirements.txt") as f:
        lines = [l.strip() for l in f 
                 if l.strip() and not l.startswith("#")]
    unpinned = [l for l in lines if "==" not in l]
    assert len(unpinned) == 0, \
        f"Unpinned dependencies found: {unpinned}"