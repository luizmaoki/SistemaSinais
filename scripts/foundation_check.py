"""Verify clean install, seed, migrations, persistence, logs and restore in isolation."""
import argparse
from datetime import datetime, timezone
import json
import os
import re
import subprocess
import sys
import urllib.request
from uuid import uuid4

from db_backup import create_backup, fingerprint, verify_restore
from docker_utils import ROOT, run_compose


STABLE_TABLES = {
    "alembic_version", "assets", "asset_identifiers", "asset_corporate_actions",
    "users", "tenants", "market_bars", "filings", "macro_events", "watchlists",
    "watchlist_assets", "alert_rules", "alerts", "audit_logs",
}


def safe_project_name(project):
    if not re.fullmatch(r"capitalverify[a-f0-9]{12}", project):
        raise ValueError("Refusing cleanup outside a generated validation project")
    return project


def cleanup_project(command, project, report):
    try:
        safe_project_name(project)
        run_compose(command, "down", "--volumes", "--remove-orphans")
        report["isolated_resources_removed"] = True
    except Exception as error:
        report["status"] = "FAILED"
        report["cleanup_failure_type"] = type(error).__name__
        report["isolated_resources_removed"] = False
        raise


def base_url(command, service, port):
    address = run_compose(command, "port", service, str(port), capture_output=True, text=True).stdout.strip()
    if not re.fullmatch(r"127\.0\.0\.1:\d+", address):
        raise RuntimeError("Unexpected validation port binding")
    return "http://" + address


def verify_log(command, api_url):
    # An intentionally sensitive-looking query sentinel must never enter app logs.
    sentinel = "FOUNDATION_QUERY_DO_NOT_LOG_" + uuid4().hex
    with urllib.request.urlopen(api_url + "/api/v1/health?token=" + sentinel, timeout=10) as response:
        correlation = response.headers["X-Correlation-ID"]
    logs = run_compose(command, "logs", "--no-color", "api", capture_output=True, text=True).stdout
    records = []
    for line in logs.splitlines():
        payload = line.partition("|")[2].strip()
        try:
            records.append(json.loads(payload))
        except (json.JSONDecodeError, TypeError):
            continue
    if not any(record.get("correlation_id") == correlation and record.get("status") == 200 for record in records):
        raise AssertionError("Structured request log/correlation missing")
    # Uvicorn access logs are disabled so query strings are not leaked there either.
    if sentinel in logs:
        raise AssertionError("Query sentinel leaked into logs")
    return {"status": "LOGS_VERIFIED", "correlation_id": correlation}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-build", action="store_true", help="Reuse previously built images")
    args = parser.parse_args()
    project = safe_project_name("capitalverify" + uuid4().hex[:12])
    command = ["docker", "compose", "--project-name", project, "--file", str(ROOT / "docker-compose.yml"),
               "--file", str(ROOT / "infra/docker/compose.validation.yml"), "--env-file", str(ROOT / ".env.example")]
    out = ROOT / "artifacts" / "foundation" / project
    out.mkdir(parents=True)
    report = {"project": project, "started_at": datetime.now(timezone.utc).isoformat(), "status": "RUNNING"}
    try:
        run_compose(command, "config", "--quiet")
        up = ["up", "-d", "--wait", "--wait-timeout", "240"]
        if not args.no_build:
            up.append("--build")
        run_compose(command, *up)
        api_url, web_url = base_url(command, "api", 8000), base_url(command, "web", 3000)
        run_compose(command, "exec", "-T", "api", "python", "-m", "pytest", "-q")
        run_compose(command, "exec", "-T", "api", "python", "-m", "ruff", "check", "app", "tests")
        run_compose(command, "exec", "-T", "api", "python", "-m", "alembic", "check")
        smoke_env = {**os.environ, "SMOKE_API_URL": api_url, "SMOKE_WEB_URL": web_url}
        subprocess.run([sys.executable, str(ROOT / "scripts/smoke.py"), "--project-name", project, "--compose-file", "docker-compose.yml", "--compose-file", "infra/docker/compose.validation.yml", "--env-file", ".env.example"], cwd=ROOT, env=smoke_env, check=True)
        report["logs"] = verify_log(command, api_url)
        run_compose(command, "stop", "worker")
        before = fingerprint(command)
        run_compose(command, "exec", "-T", "api", "python", "-m", "app.cli", "init")
        if fingerprint(command) != before:
            raise AssertionError("Repeated migration/seed changed persisted data")
        report["seed_idempotent"] = True
        backup = out / "foundation.dump"
        report["backup"] = create_backup(command, backup)
        report["restore"] = verify_restore(command, backup, expected=before)
        # Same volumes, fresh containers. No volume deletion until all checks end.
        run_compose(command, "down")
        run_compose(command, "up", "-d", "--wait", "--wait-timeout", "240")
        run_compose(command, "stop", "worker")
        after = fingerprint(command)
        if {table: before[table] for table in STABLE_TABLES} != {table: after[table] for table in STABLE_TABLES}:
            raise AssertionError("Application data changed across container recreation")
        report["persistence_verified"] = True
        report["status"] = "PASSED"
    except Exception as error:
        report["status"] = "FAILED"
        report["failure_type"] = type(error).__name__
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        try:
            cleanup_project(command, project, report)
        finally:
            (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print("Validation report:", out / "report.json")
    print("FOUNDATION OK: clean install, tests, migrations, seed, logs, restore and persistence")


if __name__ == "__main__":
    main()


