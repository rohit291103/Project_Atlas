import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Registers EventLog onto Base.metadata so autogenerate can see it; storage/
# is the only module that should ever define tables (Module Boundary in
# root CLAUDE.md).
from atlas.storage import connections as _connections  # noqa: F401
from atlas.storage import tables as _tables  # noqa: F401
from atlas.storage.db import Base, normalize_database_url

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def get_url() -> str:
    """The DB URL always comes from the environment, never from alembic.ini
    (CLAUDE.md: no secret ever lands anywhere but env/secrets manager).

    Migrations need DDL rights; the application deliberately does not have them
    (see `c3d8e1f60b21` -- it connects as the NOBYPASSRLS `atlas_app` role so
    row-level security actually binds). So Alembic prefers the admin URL and
    only falls back to `SUPABASE_DB_URL` for setups predating that split.
    """
    url = os.environ.get("SUPABASE_DB_ADMIN_URL") or os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise RuntimeError(
            "Neither SUPABASE_DB_ADMIN_URL nor SUPABASE_DB_URL is set. "
            "Alembic needs an owner-level URL to connect -- see .env.example."
        )
    return normalize_database_url(url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
