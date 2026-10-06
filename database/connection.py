import logging
import sqlite3
from contextlib import contextmanager

from config.settings import DATABASE_PATH


logger = logging.getLogger(__name__)


@contextmanager
def get_db_connection():
    """
    Create and manage a SQLite database connection.

    The connection is automatically:
    - opened
    - committed if successful
    - rolled back if an error occurs
    - closed when finished
    """

    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = None

    try:
        connection = sqlite3.connect(DATABASE_PATH)

        # Allows rows to behave somewhat like dictionaries.
        connection.row_factory = sqlite3.Row

        # SQLite does not enforce foreign keys by default.
        connection.execute("PRAGMA foreign_keys = ON;")

        yield connection

        connection.commit()

    except sqlite3.Error:
        if connection:
            connection.rollback()

        logger.exception("SQLite database operation failed.")
        raise

    finally:
        if connection:
            connection.close()