import argparse
import json
from pathlib import Path
from alembic import command
from alembic.config import Config
from app.config import get_settings
from app.database import SessionLocal
from app.ingestion import sync
from app.seed import seed


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
    args = parser.parse_args()
    if args.command == "init":
        initialize()
        print("Migrations and demo seed ready")
    else:
        print(json.dumps(sync(args.provider)))


if __name__ == "__main__":
    main()
