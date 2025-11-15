"""
Database connection and session management
"""
import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.config.settings import settings

# Create async engine with DB-specific parameters
engine_kwargs = {
    "echo": settings.debug,  # SQL logging in debug mode
}

# Add pool parameters only for PostgreSQL, not for SQLite
if not settings.database.effective_url.startswith("sqlite"):
    # Use NullPool for PgBouncer compatibility - create new connection per request
    from sqlalchemy.pool import NullPool
    engine_kwargs.update({
        "poolclass": NullPool,  # No connection pooling for PgBouncer
    })

# Engine will be created lazily in init_db() to avoid connection at import time
engine = None
async_session_factory = None


class DatabaseSession:
    """Context manager for database sessions (async only)"""

    def __init__(self):
        self.session = None

    async def __aenter__(self):
        """Async context manager entry"""
        global async_session_factory
        if async_session_factory is None:
            raise RuntimeError("Database not initialized. Call init_db() first.")
        self.session = async_session_factory()
        return self.session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            if exc_type is None:
                # No exception - commit
                await self.session.commit()
            else:
                # Exception occurred - rollback
                await self.session.rollback()
            await self.session.close()


def get_db() -> DatabaseSession:
    """
    Dependency for getting database session

    Returns:
        DatabaseSession: Async context manager for database sessions
    """
    return DatabaseSession()




async def init_db() -> None:
    """
    Initialize database and create tables
    """
    global engine, async_session_factory

    if engine is None:
        # Create async engine with DB-specific parameters
        engine_kwargs = {
            "echo": settings.debug,  # SQL logging in debug mode
        }

        # Add pool parameters only for PostgreSQL, not for SQLite
        if not settings.database.effective_url.startswith("sqlite"):
            # Use NullPool for PgBouncer compatibility - create new connection per request
            from sqlalchemy.pool import NullPool
            engine_kwargs.update({
                "poolclass": NullPool,  # No connection pooling for PgBouncer
            })

        # Configure PostgreSQL connection based on environment
        database_url = settings.database.effective_url

        # Remove pgbouncer parameter from URL if present (not needed with psycopg)
        from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
        parsed = urlparse(database_url)
        query_params = parse_qs(parsed.query)

        # Remove pgbouncer parameter if present (not needed with psycopg)
        if "pgbouncer" in query_params:
            del query_params["pgbouncer"]

        # Add application_name and sslmode to URL query parameters
        # psycopg uses URL parameters, not server_settings in connect_args
        app_name = "polycool_railway" if os.getenv('RAILWAY_ENVIRONMENT') else "polycool"

        # Add application_name via options parameter
        if "options" not in query_params:
            # Format: options=-c application_name=value
            query_params["options"] = [f"-c application_name={app_name}"]
        else:
            # Append to existing options if application_name not present
            existing_options = query_params["options"][0] if query_params["options"] else ""
            if "application_name" not in existing_options:
                query_params["options"][0] = f"{existing_options} -c application_name={app_name}"

        # Add sslmode if not present (psycopg supports this in URL)
        if "sslmode" not in query_params:
            query_params["sslmode"] = ["require"]

        # Reconstruct URL with options parameter
        if query_params:
            new_query = urlencode(query_params, doseq=True)
            database_url = urlunparse(parsed._replace(query=new_query))
        else:
            database_url = urlunparse(parsed._replace(query=""))

        # Normalize URL to ensure psycopg driver (better PgBouncer compatibility)
        # SQLAlchemy will automatically use async version when using create_async_engine
        if database_url.startswith("postgres://"):
            # Fix postgres:// → postgresql+psycopg://
            database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
        elif database_url.startswith("postgresql://"):
            # Replace asyncpg with psycopg if present
            if "+asyncpg" in database_url:
                database_url = database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
            # Add psycopg driver if not present
            elif "+psycopg" not in database_url:
                database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

        if database_url.startswith("postgresql"):
            # CRITICAL: Use psycopg instead of asyncpg for better PgBouncer compatibility
            # However, psycopg still uses prepared statements by default, so we need to disable them
            # for PgBouncer transaction pooling compatibility
            # Note: application_name and sslmode are set via URL parameters, not connect_args
            # prepare_threshold=0 disables prepared statements (0 = never prepare)

            # Check if this is Supabase Pooler (needs longer timeout)
            is_supabase_pooler = "pooler.supabase.com" in database_url
            connect_timeout = 30 if is_supabase_pooler else 10  # 30s for Supabase, 10s for others

            engine_kwargs["connect_args"] = {
                "connect_timeout": connect_timeout,  # Increased timeout for Supabase Pooler
                # Note: prepare_threshold is set via event listener, not connect_args
            }

        # Use async engine everywhere (both local and Railway)
        # Note: We're using NullPool which creates a new connection for each request
        # This helps avoid prepared statement conflicts with PgBouncer transaction pooling
        engine = create_async_engine(database_url, **engine_kwargs)

        # CRITICAL: Intercept connection creation to disable prepared statements
        # SQLAlchemy's psycopg dialect creates prepared statements during initialization
        # We need to prevent this by intercepting the do_connect event
        from sqlalchemy import event

        @event.listens_for(engine.sync_engine, "do_connect")
        def disable_prepared_statements_on_connect(dialect, conn_rec, cargs, cparams):
            """Intercept connection creation to disable prepared statements"""
            # Add prepare_threshold=0 to connection parameters
            # This should prevent psycopg from using prepared statements
            cparams['prepare_threshold'] = 0
            # Return None to let SQLAlchemy create the connection normally
            return None

        async_session_factory = sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    from core.database.models import Base

    # Create tables using async engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """
    Close database connections
    """
    global engine
    if engine is not None:
        # Always async engine
        await engine.dispose()
        engine = None
