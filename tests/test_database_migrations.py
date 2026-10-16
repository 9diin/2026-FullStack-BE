from unittest.mock import MagicMock

from backend.core.migrations import apply_compatibility_migrations


def test_adds_solution_column_to_existing_postgresql_table() -> None:
    engine = MagicMock()
    engine.dialect.name = "postgresql"

    apply_compatibility_migrations(engine)

    connection = engine.begin.return_value.__enter__.return_value
    statement = str(connection.execute.call_args.args[0])
    assert statement == (
        "ALTER TABLE public.idea_elaborations ADD COLUMN IF NOT EXISTS solution JSONB"
    )


def test_skips_postgresql_compatibility_migration_for_other_dialects() -> None:
    engine = MagicMock()
    engine.dialect.name = "sqlite"

    apply_compatibility_migrations(engine)

    engine.begin.assert_not_called()
