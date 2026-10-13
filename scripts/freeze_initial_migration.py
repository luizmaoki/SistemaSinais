"""Freeze the initial migration from empty-schema diff, so later model edits cannot change revision 0001."""

from pathlib import Path
from alembic.autogenerate import produce_migrations, render_python_code
from alembic.migration import MigrationContext
from sqlalchemy import create_engine
from app.database import Base, UTCDateTime
from app import models  # noqa: F401


def render_type(kind, obj, context):
    if kind == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


with create_engine("sqlite:///:memory:").connect() as connection:
    operations = produce_migrations(
        MigrationContext.configure(connection), Base.metadata
    )
    up = render_python_code(operations.upgrade_ops, render_item=render_type)
    down = render_python_code(operations.downgrade_ops, render_item=render_type)
    script = (
        '"""Initial foundation schema snapshot (revision 0001)."""\nfrom alembic import op\nimport sqlalchemy as sa\nrevision = "0001"\ndown_revision = None\nbranch_labels = None\ndepends_on = None\n\ndef upgrade():\n'
        + up
        + "\n\ndef downgrade():\n"
        + down
        + "\n"
    )
    destination = (
        Path(__file__).resolve().parents[1]
        / "infra/migrations/versions/0001_foundation.py"
    )
    destination.write_text(script, encoding="utf-8")
    print("Frozen initial migration:", len(Base.metadata.tables), "tables")
