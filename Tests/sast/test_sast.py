
# tests/sast/test_sast.py
import subprocess

def test_bandit_no_high_severity():
    result = subprocess.run(
        ["bandit", "-r", "./app", "-ll", "-f", "json"],
        capture_output=True, text=True
    )
    import json
    report = json.loads(result.stdout)
    high_issues = [
        i for i in report.get("results", [])
        if i["issue_severity"] in ["HIGH", "CRITICAL"]
    ]
    assert len(high_issues) == 0, \
        f"Bandit found high severity issues: {high_issues}"

def test_no_hardcoded_secrets():
    result = subprocess.run(
        ["grep", "-r", "SECRET_KEY\s*=\s*['\"]", "./app"],
        capture_output=True, text=True
    )
    assert result.stdout == "", \
        "Hardcoded secret found in source code"

def test_no_raw_sql():
    result = subprocess.run(
        ["grep", "-rn", "execute(f\"", "./app"],
        capture_output=True, text=True
    )
    assert result.stdout == "", \
        "Raw f-string SQL query found"
        