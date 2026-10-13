import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import db_backup
from foundation_check import safe_project_name, cleanup_project


class OperationalSafetyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name).resolve()
        self.root_patch = patch.object(db_backup, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.directory.cleanup)
        (self.root / "artifacts").mkdir()
        self.path = self.root / "artifacts" / "check.dump"

    def archive(self):
        payload = b"PGDMPsynthetic-contract-only"
        self.path.write_bytes(payload)
        metadata = {"format_version": 1, "source_database": "capital", "migration_revision": "0001",
                    "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        db_backup.manifest_path(self.path).write_text(json.dumps(metadata), encoding="utf-8")

    def test_tampering_is_rejected_before_any_database_command(self):
        self.archive()
        self.path.write_bytes(b"PGDMPchanged")
        with patch.object(db_backup, "run_compose") as run:
            with self.assertRaises(db_backup.BackupError):
                db_backup.verify_restore([], self.path)
            run.assert_not_called()

    def test_existing_backup_is_not_overwritten(self):
        self.path.write_bytes(b"existing")
        with patch.object(db_backup, "sql") as sql:
            with self.assertRaises(db_backup.BackupError):
                db_backup.create_backup([], self.path)
            sql.assert_not_called()
        self.assertEqual(self.path.read_bytes(), b"existing")

    def test_failed_restore_drops_only_its_new_database(self):
        self.archive()
        calls = []
        def run(command, *args, **kwargs):
            calls.append(args)
            if "pg_restore" in args:
                raise RuntimeError("Synthetic restore failure")
        with patch.object(db_backup, "run_compose", side_effect=run):
            with self.assertRaises(RuntimeError):
                db_backup.verify_restore([], self.path)
        created = calls[0][-1]
        self.assertRegex(created, r"^capital_restore_check_[0-9a-f]{32}$")
        self.assertEqual(calls[-1], ("exec", "-T", "postgres", "dropdb", "-U", "capital", created))

    def test_create_database_failure_never_drops_existing_database(self):
        self.archive()
        with patch.object(db_backup, "run_compose", side_effect=RuntimeError("Already exists")) as run:
            with self.assertRaises(RuntimeError):
                db_backup.verify_restore([], self.path)
            self.assertEqual(run.call_count, 1)

    def test_cleanup_rejects_primary_or_user_supplied_projects(self):
        for project in ["sistemasinais", "capitalverify", "capitalverify123456789abc-extra"]:
            with self.assertRaises(ValueError):
                safe_project_name(project)
        self.assertEqual(safe_project_name("capitalverify123456789abc"), "capitalverify123456789abc")

    def test_failed_cleanup_cannot_report_success(self):
        report = {"status": "PASSED"}
        with patch("foundation_check.run_compose", side_effect=RuntimeError("Docker unavailable")):
            with self.assertRaises(RuntimeError):
                cleanup_project([], "capitalverify123456789abc", report)
        self.assertEqual(report["status"], "FAILED")
        self.assertFalse(report["isolated_resources_removed"])
        self.assertEqual(report["cleanup_failure_type"], "RuntimeError")

    def test_backup_path_cannot_escape_workspace(self):
        with self.assertRaises(db_backup.BackupError):
            db_backup.checked_path(self.root.parent / "outside.dump")
        with self.assertRaises(db_backup.BackupError):
            db_backup.checked_path(self.root / "inside_repo_but_not_artifacts.dump")


if __name__ == "__main__":
    unittest.main()

