"""DuckDB helpers: initialize the schema and open connections."""

from __future__ import annotations

from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SQL = REPO_ROOT / "schema" / "schema.sql"
DEFAULT_DB = REPO_ROOT / "data" / "db" / "badminton.duckdb"


def connect(db_path: Path | str = DEFAULT_DB, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the DB. Readers (dashboard) should pass read_only=True so multiple viewers
    share the file; writers (detect/import) take a brief exclusive lock only at write time."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path), read_only=read_only)


def init_db(db_path: Path | str = DEFAULT_DB) -> Path:
    """Create all tables from schema/schema.sql (idempotent)."""
    con = connect(db_path)
    con.execute(SCHEMA_SQL.read_text())
    con.close()
    return Path(db_path)
