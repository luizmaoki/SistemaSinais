from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database import Base, build_engine
from app.seed import seed


def test_initial_migration_upgrade_downgrade_upgrade(tmp_path, monkeypatch):
    database_url = "sqlite:///" + str(tmp_path / "migration.db")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        with monkeypatch.context() as context:
            context.setenv("DATABASE_URL", database_url)
            get_settings.cache_clear()
            command.upgrade(config, "head")
            engine = build_engine(database_url)
            try:
                inspector = inspect(engine)
                assert set(Base.metadata.tables) <= set(inspector.get_table_names())
                for table in Base.metadata.sorted_tables:
                    assert set(table.columns.keys()) == {column["name"] for column in inspector.get_columns(table.name)}
                    assert {column.name for column in table.primary_key.columns} == set(inspector.get_pk_constraint(table.name)["constrained_columns"])
                    expected_foreign_keys = {(tuple(element.parent.name for element in constraint.elements), constraint.referred_table.name) for constraint in table.foreign_key_constraints}
                    reflected_foreign_keys = {(tuple(key["constrained_columns"]), key["referred_table"]) for key in inspector.get_foreign_keys(table.name)}
                    assert reflected_foreign_keys == expected_foreign_keys
                command.check(config)
                with Session(engine) as session:
                    seed(session)
                    before = {table.name: session.execute(select(table).order_by(*table.primary_key.columns)).all() for table in Base.metadata.sorted_tables}
                    seed(session)
                    after = {table.name: session.execute(select(table).order_by(*table.primary_key.columns)).all() for table in Base.metadata.sorted_tables}
                    assert before == after
                    assert before["market_bars"] and before["users"]
                # Populated schema, with foreign keys enabled in Alembic too.
                command.downgrade(config, "base")
                assert inspect(engine).get_table_names() == ["alembic_version"]
                command.upgrade(config, "head")
                command.check(config)
                assert set(Base.metadata.tables) <= set(inspect(engine).get_table_names())
            finally:
                engine.dispose()
    finally:
        get_settings.cache_clear()


def test_oidc_migration_preserves_populated_legacy_data(tmp_path, monkeypatch):
    from datetime import timedelta
    from app.auth import DEMO_USER_ID
    from app.database import utcnow
    from app.models import AuthFlow, AuthSession, User

    database_url = "sqlite:///" + str(tmp_path / "populated-oidc-migration.db")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))

    def legacy_snapshot(connection):
        additions = {
            "users": {"active", "oidc_issuer", "oidc_subject"},
            "assets": {"calendar_id", "instrument_kind", "metadata_status", "metadata_source_id", "metadata_source_uri", "metadata_available_as_of", "metadata_ingested_at"},
            "asset_identifiers": {"venue", "chain_id", "native_id", "version", "checksum", "cancelled", "source_uri", "available_as_of", "ingested_at"},
            "asset_corporate_actions": {"native_id", "version", "checksum", "source_uri", "available_as_of", "ingested_at", "cancelled"},
            "market_bars": {"currency"},
        }
        return {
            table.name: connection.execute(select(*[
                column for column in table.columns
                if column.name not in additions.get(table.name, set())
            ]).order_by(*table.primary_key.columns)).all()
            for table in Base.metadata.sorted_tables
            if table.name not in {"auth_flows", "auth_sessions", "catalog_imports", "corporate_action_coverage"}
        }

    try:
        with monkeypatch.context() as context:
            context.setenv("DATABASE_URL", database_url)
            get_settings.cache_clear()
            command.upgrade(config, "head")
            engine = build_engine(database_url)
            try:
                with Session(engine) as session:
                    seed(session)
                    session.add(AuthFlow(
                        state_hash="a" * 64, binding_hash="b" * 64,
                        nonce="n" * 43, code_verifier="v" * 86,
                        expires_at=utcnow() + timedelta(minutes=5),
                    ))
                    session.add(AuthSession(
                        id_hash="c" * 64, user_id=DEMO_USER_ID, csrf_token="s" * 43,
                        expires_at=utcnow() + timedelta(minutes=5),
                    ))
                    session.commit()
                    expected = legacy_snapshot(session)
                command.downgrade(config, "0001")
                with engine.connect() as connection:
                    assert legacy_snapshot(connection) == expected
                assert "auth_sessions" not in inspect(engine).get_table_names()
                assert {"active", "oidc_subject", "oidc_issuer"}.isdisjoint(
                    column["name"] for column in inspect(engine).get_columns("users")
                )
                command.upgrade(config, "head")
                command.check(config)
                with Session(engine) as session:
                    assert legacy_snapshot(session) == expected
                    user = session.get(User, DEMO_USER_ID)
                    assert user.active is True and user.oidc_issuer is None and user.oidc_subject is None
                    assert session.scalars(select(AuthFlow)).all() == []
                    assert session.scalars(select(AuthSession)).all() == []
                indexes = inspect(engine).get_indexes("users")
                assert any(
                    index["name"] == "ix_users_oidc_identity" and index["unique"]
                    and index["column_names"] == ["oidc_issuer", "oidc_subject"]
                    for index in indexes
                )
            finally:
                engine.dispose()
    finally:
        get_settings.cache_clear()


def test_catalog_migration_preserves_all_0002_rows_and_currency(tmp_path, monkeypatch):
    from sqlalchemy import MetaData

    url = "sqlite:///" + str(tmp_path / "populated-catalog-migration.db")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        with monkeypatch.context() as context:
            context.setenv("DATABASE_URL", url)
            get_settings.cache_clear()
            command.upgrade(config, "head")
            engine = build_engine(url)
            try:
                with Session(engine) as session:
                    seed(session)
                command.downgrade(config, "0002")
                legacy = MetaData()
                legacy.reflect(bind=engine)
                def snapshot():
                    with engine.connect() as connection:
                        return {name: connection.execute(select(table).order_by(*table.primary_key.columns)).all() for name, table in legacy.tables.items() if name != "alembic_version"}
                before = snapshot()
                command.upgrade(config, "head")
                command.check(config)
                assert snapshot() == before
                with engine.connect() as connection:
                    from sqlalchemy import text
                    assert connection.execute(text("SELECT COUNT(*) FROM market_bars WHERE currency IS NULL OR currency != 'USD'")).scalar() == 0
                command.downgrade(config, "0002")
                assert snapshot() == before
                command.upgrade(config, "head")
                command.check(config)
                assert snapshot() == before
            finally:
                engine.dispose()
    finally:
        get_settings.cache_clear()
