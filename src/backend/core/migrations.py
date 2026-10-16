from sqlalchemy import Engine, text


def apply_compatibility_migrations(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE public.idea_elaborations "
                "ADD COLUMN IF NOT EXISTS solution JSONB"
            )
        )
