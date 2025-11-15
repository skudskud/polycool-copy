"""
Robust Database Session Manager
Handles transaction state recovery, automatic rollback, and retry logic
Prevents 'InFailedSqlTransaction' errors from cascading through the application
"""

import logging
import time
from contextlib import contextmanager
from typing import Optional, Callable, TypeVar, Any, Dict, List
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError, DBAPIError
from sqlalchemy import text, exc

logger = logging.getLogger(__name__)

T = TypeVar('T')

# Exponential backoff retry configuration
DEFAULT_RETRY_CONFIG = {
    'max_retries': 3,
    'initial_delay': 0.1,  # 100ms
    'max_delay': 2.0,      # 2s
    'backoff_factor': 2.0
}

class DatabaseConnectionError(Exception):
    """Custom exception for database connection issues"""
    pass


class TransactionStateError(Exception):
    """Raised when transaction is in an aborted state"""
    pass


class RobustDatabaseManager:
    """
    Manages database sessions with robust error handling and recovery
    Prevents 'InFailedSqlTransaction' cascading errors
    """

    def __init__(self, session_factory):
        """
        Args:
            session_factory: SQLAlchemy SessionLocal factory
        """
        self.session_factory = session_factory
        self._session_cache: Dict[int, Optional[Session]] = {}

    def _validate_session_state(self, session: Session) -> bool:
        """
        Check if session is in a valid state before executing queries

        Args:
            session: SQLAlchemy session

        Returns:
            True if session is valid, False otherwise
        """
        try:
            # If transaction is already failed, return False
            if session.is_active and session.in_transaction():
                # Test with a simple query
                session.execute(text("SELECT 1"))
            return True
        except exc.InvalidRequestError as e:
            logger.warning(f"⚠️ Session in invalid state: {e}")
            return False
        except (DBAPIError, SQLAlchemyError) as e:
            logger.warning(f"⚠️ Session connection error: {e}")
            return False

    def _reset_session(self, session: Session) -> None:
        """
        Reset a session that's in a bad state

        Args:
            session: SQLAlchemy session to reset
        """
        try:
            # If in a transaction, rollback
            if session.is_active:
                if session.in_transaction():
                    session.rollback()
                    logger.debug("🔄 Session rolled back after error")
            # Expunge all objects from session cache
            session.expunge_all()
            logger.debug("🧹 Session cleared")
        except Exception as e:
            logger.warning(f"⚠️ Error resetting session: {e}")

    @contextmanager
    def get_session(self, auto_commit: bool = True):
        """
        Context manager that provides a safe database session
        Automatically handles rollback on error and session cleanup

        Args:
            auto_commit: Whether to auto-commit successful transactions

        Yields:
            SQLAlchemy Session

        Example:
            with db_manager.get_session() as session:
                user = session.query(User).filter_by(id=1).first()
        """
        session = None
        try:
            # Create new session
            session = self.session_factory()
            logger.debug("✅ Database session created")

            # Validate session is healthy
            if not self._validate_session_state(session):
                logger.warning("⚠️ New session validation failed, closing and retrying...")
                session.close()
                session = self.session_factory()

            yield session

            # Auto-commit if requested and no errors
            if auto_commit and session.is_active:
                try:
                    session.commit()
                    logger.debug("✅ Transaction committed")
                except Exception as commit_error:
                    logger.warning("Commit failed")
                    session.rollback()
                    raise

        except (DBAPIError, SQLAlchemyError, DatabaseConnectionError) as db_error:
            logger.debug(f"Database error (will retry): {type(db_error).__name__}")
            if session:
                try:
                    session.rollback()
                    logger.debug("🔄 Automatic rollback performed")
                except:
                    pass
            raise

        except Exception as unexpected_error:
            logger.debug("Unexpected error")
            if session:
                try:
                    session.rollback()
                    logger.debug("🔄 Automatic rollback performed")
                except:
                    pass
            raise

        finally:
            # Always close the session
            if session:
                try:
                    session.close()
                    logger.debug("🔒 Database session closed")
                except:
                    pass

    def execute_with_retry(
        self,
        query_func: Callable[[Session], T],
        retry_config: Optional[Dict[str, Any]] = None
    ) -> T:
        """
        Execute a query function with automatic retry on failure
        Handles transaction state errors gracefully

        Args:
            query_func: Function that takes a session and returns a result
            retry_config: Retry configuration (uses defaults if None)

        Returns:
            Result of query_func

        Example:
            def get_user(session):
                return session.query(User).filter_by(id=1).first()

            user = db_manager.execute_with_retry(get_user)
        """
        config = retry_config or DEFAULT_RETRY_CONFIG
        max_retries = config.get('max_retries', 3)
        initial_delay = config.get('initial_delay', 0.1)
        max_delay = config.get('max_delay', 2.0)
        backoff_factor = config.get('backoff_factor', 2.0)

        last_error = None
        delay = initial_delay

        for attempt in range(max_retries):
            try:
                with self.get_session(auto_commit=False) as session:
                    result = query_func(session)
                    logger.debug(f"✅ Query succeeded on attempt {attempt + 1}")
                    return result

            except TransactionStateError as e:
                last_error = e
                logger.warning(f"⚠️ Transaction state error (attempt {attempt + 1}/{max_retries}): {e}")

            except DBAPIError as e:
                last_error = e
                logger.warning(f"⚠️ Database error (attempt {attempt + 1}/{max_retries}): {e}")

            except Exception as e:
                last_error = e
                logger.warning(f"⚠️ Query error (attempt {attempt + 1}/{max_retries}): {e}")

            # Wait before retry (except on last attempt)
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay = min(delay * backoff_factor, max_delay)
                logger.debug(f"🔄 Retrying in {delay:.2f}s...")

        # All retries failed
        error_msg = f"Query failed after {max_retries} attempts: {last_error}"
        logger.error(f"❌ {error_msg}")
        raise DatabaseConnectionError(error_msg) from last_error

    def safe_update(self, update_func: Callable[[Session], Any]) -> None:
        """
        Safely execute an update operation with automatic rollback on error

        Args:
            update_func: Function that takes a session and performs updates

        Example:
            def update_user(session):
                user = session.query(User).filter_by(id=1).first()
                user.name = "New Name"
                session.commit()

            db_manager.safe_update(update_user)
        """
        try:
            with self.get_session(auto_commit=True) as session:
                update_func(session)
                logger.debug("✅ Update completed successfully")
        except Exception as e:
            logger.error(f"❌ Update failed: {e}")
            raise

    def safe_query(
        self,
        query_func: Callable[[Session], T],
        retry_on_failure: bool = True
    ) -> Optional[T]:
        """
        Safely execute a read query without modification

        Args:
            query_func: Function that takes a session and returns a result
            retry_on_failure: Whether to retry on failure

        Returns:
            Result of query_func or None if failed

        Example:
            def get_user(session):
                return session.query(User).filter_by(id=1).first()

            user = db_manager.safe_query(get_user)
        """
        if retry_on_failure:
            return self.execute_with_retry(query_func)

        try:
            with self.get_session(auto_commit=False) as session:
                return query_func(session)
        except Exception as e:
            logger.error(f"❌ Query failed: {e}")
            return None
