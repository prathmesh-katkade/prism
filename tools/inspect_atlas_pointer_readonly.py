"""Inspect promotion event identities with SQLite read-only URI semantics."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    path = args.database.resolve(strict=True)
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        events = connection.execute(
            "SELECT sequence,tier,candidate_id,previous_candidate_id,is_rollback "
            "FROM prism_atlas_production_pointer_events ORDER BY sequence"
        ).fetchall()
    print(json.dumps({"path": str(path), "integrity": integrity, "events": events}, sort_keys=True))


if __name__ == "__main__":
    main()
