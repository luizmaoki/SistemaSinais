"""Catalog provenance, identifier history and append-only corporate action revisions.

Additive only: all existing identities, prices and owner/OIDC relationships survive.
Downgrade discards the new metadata/ledger; retain an export before using it.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

ASSET_COLUMNS = [
    ("calendar_id", sa.String(30)), ("instrument_kind", sa.String(30)),
    ("metadata_source_id", sa.String(50)), ("metadata_source_uri", sa.Text()),
    ("metadata_available_as_of", sa.DateTime(timezone=True)),
    ("metadata_ingested_at", sa.DateTime(timezone=True)),
]
IDENTIFIER_COLUMNS = [
    ("venue", sa.String(100)), ("chain_id", sa.String(30)), ("native_id", sa.String(100)),
    ("version", sa.Integer()), ("checksum", sa.String(64)), ("source_uri", sa.Text()),
    ("available_as_of", sa.DateTime(timezone=True)), ("ingested_at", sa.DateTime(timezone=True)),
]
ACTION_COLUMNS = [
    ("native_id", sa.String(100)), ("version", sa.Integer()), ("checksum", sa.String(64)),
    ("source_uri", sa.Text()), ("available_as_of", sa.DateTime(timezone=True)),
    ("ingested_at", sa.DateTime(timezone=True)),
]


def upgrade():
    for name, kind in ASSET_COLUMNS:
        op.add_column("assets", sa.Column(name, kind, nullable=True))
    op.add_column("assets", sa.Column("metadata_status", sa.String(20), nullable=False, server_default="UNVERIFIED"))
    for name, kind in IDENTIFIER_COLUMNS:
        op.add_column("asset_identifiers", sa.Column(name, kind, nullable=True))
    op.add_column("asset_identifiers", sa.Column("cancelled", sa.Boolean(), nullable=False, server_default="0"))
    op.create_index("ix_identifiers_revision", "asset_identifiers", ["asset_id", "source_id", "native_id", "version"], unique=True)
    op.create_index("ix_identifiers_lookup", "asset_identifiers", ["identifier_type", "value", "venue"])
    for name, kind in ACTION_COLUMNS:
        op.add_column("asset_corporate_actions", sa.Column(name, kind, nullable=True))
    op.add_column("asset_corporate_actions", sa.Column("cancelled", sa.Boolean(), nullable=False, server_default="0"))
    op.create_index("ix_actions_revision", "asset_corporate_actions", ["asset_id", "source_id", "data_mode", "native_id", "version"], unique=True)
    op.add_column("market_bars", sa.Column("currency", sa.String(8), nullable=True))
    # Preserve the denomination recorded by the pre-migration asset metadata.
    op.execute("UPDATE market_bars SET currency = (SELECT currency FROM assets WHERE assets.id = market_bars.asset_id)")
    op.create_table(
        "catalog_imports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("checksum", sa.String(64), nullable=False, unique=True),
        sa.Column("source_id", sa.String(50), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=False),
        sa.Column("available_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("asset_count", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "corporate_action_coverage",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("source_id", sa.String(50), nullable=False),
        sa.Column("data_mode", sa.String(30), nullable=False),
        sa.Column("dataset_id", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("coverage_from", sa.Date(), nullable=False),
        sa.Column("coverage_to", sa.Date(), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=False),
        sa.Column("available_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("asset_id", "source_id", "data_mode", "dataset_id", "version"),
    )
    op.create_index("ix_corporate_action_coverage_asset_id", "corporate_action_coverage", ["asset_id"])


def downgrade():
    op.drop_table("corporate_action_coverage")
    op.drop_table("catalog_imports")
    op.drop_column("market_bars", "currency")
    op.drop_index("ix_actions_revision", table_name="asset_corporate_actions")
    op.drop_column("asset_corporate_actions", "cancelled")
    for name, _ in reversed(ACTION_COLUMNS):
        op.drop_column("asset_corporate_actions", name)
    op.drop_column("asset_identifiers", "cancelled")
    op.drop_index("ix_identifiers_revision", table_name="asset_identifiers")
    op.drop_index("ix_identifiers_lookup", table_name="asset_identifiers")
    for name, _ in reversed(IDENTIFIER_COLUMNS):
        op.drop_column("asset_identifiers", name)
    op.drop_column("assets", "metadata_status")
    for name, _ in reversed(ASSET_COLUMNS):
        op.drop_column("assets", name)
