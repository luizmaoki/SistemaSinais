"""Logical backup and restore verification in a newly created disposable database.

Never restores into the application database, never overwrites an existing backup.
Uses binary file handles (including on Windows), not shell redirection.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from docker_utils import ROOT, add_compose_arguments, compose_from_args, run_compose


class BackupError(RuntimeError):
    pass


def sql(command, database, statement):
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", database):
        raise BackupError("Invalid database identifier")
    return run_compose(
        command, "exec", "-T", "postgres", "psql", "-X", "-U", "capital",
        "-d", database, "-v", "ON_ERROR_STOP=1", "-A", "-t", "-q", "-c", statement,
        capture_output=True, text=True,
    ).stdout.strip()


def fingerprint(command, database="capital"):
    names = sql(command, database, "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
    queries = []
    for name in names:
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", name):
            raise BackupError("Unexpected table identifier")
        queries.append(
            "SELECT json_build_object('table','" + name + "','count',count(*),'digest',"
            "md5(coalesce(string_agg(md5(row_to_json(t)::text),'' ORDER BY md5(row_to_json(t)::text)),''))) "
            'FROM public."' + name + '" t;'
        )
    rows = sql(command, database, "SET timezone TO 'UTC';" + "".join(queries)).splitlines()
    return {row["table"]: {"count": row["count"], "digest": row["digest"]} for row in map(json.loads, rows)}


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_path(path):
    return path.with_suffix(path.suffix + ".json")


def checked_path(filename):
    path = Path(filename).resolve()
    if not path.is_relative_to(ROOT / "artifacts") or path.suffix != ".dump":
        raise BackupError("Use a .dump file inside artifacts (normally artifacts/backups)")
    return path


def create_backup(command, filename):
    path = checked_path(filename)
    metadata_path = manifest_path(path)
    if path.exists() or metadata_path.exists():
        raise BackupError("Backup or manifest already exists; choose a new filename")
    path.parent.mkdir(parents=True, exist_ok=True)
    revision = sql(command, "capital", "SELECT version_num FROM alembic_version")
    if not revision:
        raise BackupError("Missing migration revision")
    created_file = False
    try:
        with path.open("xb") as destination:
            created_file = True
            run_compose(command, "exec", "-T", "postgres", "pg_dump", "-U", "capital", "-d", "capital", "-Fc", "--no-owner", "--no-privileges", stdout=destination, capture_output=False)
        with path.open("rb") as source:
            signature = source.read(5)
        if path.stat().st_size < 5 or signature != b"PGDMP":
            raise BackupError("Invalid or empty PostgreSQL archive")
        if revision != sql(command, "capital", "SELECT version_num FROM alembic_version"):
            raise BackupError("Migration changed during backup; retry when migrations are stopped")
        metadata = {
            "format_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "source_database": "capital", "migration_revision": revision,
            "size_bytes": path.stat().st_size, "sha256": sha256_file(path),
        }
        with metadata_path.open("x", encoding="utf-8") as destination:
            json.dump(metadata, destination, indent=2)
        return metadata
    except Exception:
        if created_file:
            path.unlink(missing_ok=True)
        raise


def validate_archive(filename):
    path = checked_path(filename)
    metadata = json.loads(manifest_path(path).read_text(encoding="utf-8"))
    if metadata.get("format_version") != 1 or metadata.get("source_database") != "capital":
        raise BackupError("Unsupported backup manifest")
    if metadata.get("size_bytes") != path.stat().st_size or metadata.get("sha256") != sha256_file(path):
        raise BackupError("Backup checksum/size mismatch; restore refused")
    with path.open("rb") as source:
        if source.read(5) != b"PGDMP":
            raise BackupError("Not a PostgreSQL custom archive")
    return path, metadata


def verify_restore(command, filename, expected=None):
    path, metadata = validate_archive(filename)  # Before any database mutation.
    target = "capital_restore_check_" + uuid4().hex
    created = False
    try:
        run_compose(command, "exec", "-T", "postgres", "createdb", "-U", "capital", target)
        created = True
        with path.open("rb") as source:
            run_compose(command, "exec", "-T", "postgres", "pg_restore", "-U", "capital", "-d", target,
                        "--exit-on-error", "--single-transaction", "--no-owner", "--no-privileges", stdin=source)
        revision = sql(command, target, "SELECT version_num FROM alembic_version")
        if revision != metadata["migration_revision"]:
            raise BackupError("Restored migration revision differs from manifest")
        restored = fingerprint(command, target)
        if not {"assets", "users", "watchlists", "market_bars", "filings", "alembic_version"} <= restored.keys():
            raise BackupError("Required restored tables are missing")
        if expected is not None and restored != expected:
            raise BackupError("Restored row counts or data fingerprints differ")
        return {"status": "RESTORE_VERIFIED", "migration_revision": revision, "tables": restored}
    finally:
        # Only our newly created, randomly named database can be removed.
        if created:
            run_compose(command, "exec", "-T", "postgres", "dropdb", "-U", "capital", target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_compose_arguments(parser)
    parser.add_argument("action", choices=["backup", "verify"])
    parser.add_argument("file", help="Workspace-relative or absolute .dump path")
    args = parser.parse_args()
    command = compose_from_args(args)
    if args.action == "backup":
        metadata = create_backup(command, ROOT / args.file)
        print(json.dumps({"status": "BACKUP_CREATED", **metadata}))
    else:
        result = verify_restore(command, ROOT / args.file)
        print(json.dumps(result))


if __name__ == "__main__":
    main()


