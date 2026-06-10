"""Initialize the DuckDB database from schema/schema.sql.

    python scripts/init_db.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from badminton.db import init_db  # noqa: E402

if __name__ == "__main__":
    path = init_db()
    print(f"initialized {path}")
