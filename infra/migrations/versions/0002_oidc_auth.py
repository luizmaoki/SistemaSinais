"""OIDC identities and opaque local sessions; preserves all existing demo rows."""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    # Additive ALTERs avoid rebuilding populated SQLite users with referencing FKs.
    op.add_column("users", sa.Column("oidc_issuer", sa.String(500), nullable=True))
    op.add_column("users", sa.Column("oidc_subject", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_index("ix_users_oidc_identity", "users", ["oidc_issuer", "oidc_subject"], unique=True)
    op.create_table(
        "auth_sessions",
        sa.Column("id_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("csrf_token", sa.String(43), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table(
        "auth_flows",
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("binding_hash", sa.String(64), nullable=False),
        sa.Column("nonce", sa.String(43), nullable=False),
        sa.Column("code_verifier", sa.String(86), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("state_hash"),
    )
    op.create_index("ix_auth_flows_expires_at", "auth_flows", ["expires_at"])


def downgrade():
    op.drop_index("ix_auth_flows_expires_at", table_name="auth_flows")
    op.drop_table("auth_flows")
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_users_oidc_identity", table_name="users")
    # SQLite >=3.35 and PostgreSQL support DROP COLUMN directly; preserves child FKs/data.
    op.drop_column("users", "active")
    op.drop_column("users", "oidc_subject")
    op.drop_column("users", "oidc_issuer")
