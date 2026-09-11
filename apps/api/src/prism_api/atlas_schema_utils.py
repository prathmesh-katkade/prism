"""Portable, restart-safe index creation shared by Atlas's durable stores.

MySQL 8.0 has no ``CREATE INDEX IF NOT EXISTS`` (SQLite and Postgres do) and
rejects it with a 1064 syntax error, so every Atlas store that backfills an
index after ``MetaData.create_all()`` needs the same existence-checked,
race-tolerant helper instead of hand-rolling it per module.
"""

from __future__ import annotations

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError


def index_names(connection: Connection, table_name: str) -> set[str]:
    return {row["name"] for row in sa_inspect(connection).get_indexes(table_name)}


def ensure_index(connection: Connection, table_name: str, index_name: str, ddl: str) -> None:
    """Create ``index_name`` if it is missing, without MySQL's absent
    ``IF NOT EXISTS`` clause. ``ddl`` must be a plain ``CREATE [UNIQUE] INDEX``
    statement -- portable across SQLite, Postgres, and MySQL.
    """
    if index_name in index_names(connection, table_name):
        return
    try:
        connection.exec_driver_sql(ddl)
    except (IntegrityError, OperationalError, ProgrammingError):
        # A concurrent starter created the same index between the check above
        # and this statement. Confirm it now exists before treating the race
        # as resolved; a genuine schema problem must still surface.
        if index_name not in index_names(connection, table_name):
            raise
