import importlib.util
from pathlib import Path

from sqlalchemy.dialects import postgresql, sqlite


def _load_0003_migration():
    path = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0003_provider_request_accounting.py"
    spec = importlib.util.spec_from_file_location("migration_0003_provider_request_accounting", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_provider_request_boolean_backfill_is_dialect_aware() -> None:
    migration = _load_0003_migration()
    statement = migration._external_request_backfill_statement()
    postgres_sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    sqlite_sql = str(statement.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))

    assert "external_request=true" in postgres_sql
    assert "external_request=1" in sqlite_sql
    assert "external_request = 1" not in postgres_sql
