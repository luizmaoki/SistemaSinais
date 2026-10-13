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
                    before = {table.name: set(session.execute(select(table)).all()) for table in Base.metadata.sorted_tables}
                    seed(session)
                    after = {table.name: set(session.execute(select(table)).all()) for table in Base.metadata.sorted_tables}
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
