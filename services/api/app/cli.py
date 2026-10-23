import argparse
import json
from pathlib import Path
from alembic import command
from alembic.config import Config
from app.config import get_settings
from app.database import SessionLocal
from app.ingestion import sync
from app.seed import seed
from app.catalog import ImportRejected, import_catalog
from pydantic import ValidationError
from app.corporate_actions import import_actions


def initialize():
    get_settings().assert_auth_ready()
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    with SessionLocal() as session:
        seed(session)


def main():
    parser = argparse.ArgumentParser(description="Capital Intelligence local CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sync_parser = sub.add_parser("sync")
    sync_parser.add_argument("--provider", choices=["sec_edgar", "coinbase", "all"], default="sec_edgar")
    for name in ("import-catalog", "import-actions"):
        importer = sub.add_parser(name)
        importer.add_argument("--file", type=Path, required=True, help="Authorized JSON dataset; source/provenance required")
    args = parser.parse_args()
    if args.command == "init":
        initialize()
        print("Migrations and demo seed ready")
    elif args.command == "sync":
        print(json.dumps(sync(args.provider)))
    else:
        # No network fetch or migration: operator supplies the authorized local
        # JSON file. The entire document commits once after validation succeeds.
        get_settings().assert_auth_ready()
        try:
            if args.file.stat().st_size > 5_000_000:
                parser.error("Import JSON exceeds 5 MB")
            payload = json.loads(args.file.read_text(encoding="utf-8-sig"))
            with SessionLocal.begin() as session:
                result = (import_catalog if args.command == "import-catalog" else import_actions)(session, payload)
        except ImportRejected as error:
            parser.error(str(error))
        except (ValidationError, ValueError):
            parser.error("Invalid import document; verify the documented JSON schema and metadata constraints")
        except OSError:
            parser.error("Import file could not be read")
        print(json.dumps(result))


if __name__ == "__main__":
    main()
