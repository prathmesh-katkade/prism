"""Measure readiness after a fresh API process on a disposable backup copy."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path

import httpx
from verify_atlas_disposable_startup import await_ready, launch, sha256, stop


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--port", type=int, default=8774)
    parser.add_argument("--provider", choices=("deterministic", "ollama"), default="ollama")
    args = parser.parse_args()
    backup = args.backup.resolve(strict=True)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    original_hash = sha256(backup)
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="prism-atlas-cold-start-") as directory:
        temp = Path(directory)
        database = temp / "history.sqlite"
        shutil.copy2(backup, database)
        environment_file = temp / "api.env"
        environment_file.write_text(
            f"PRISM_ANALYTICAL_HISTORY_DATABASE_URL=sqlite:///{database.as_posix()}\n"
            f"PRISM_SQL_METADATA_PATH={str(temp / 'sql-lab.sqlite')}\n"
            f"PRISM_REQUIRE_DURABLE_HISTORY=true\nPRISM_AI_PROVIDER={args.provider}\n",
            encoding="utf-8",
        )
        started = time.perf_counter()
        process, log = launch(root, environment_file, output_dir / "cold-start-api.log", args.port, provider=args.provider)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=10) as client:
                await_ready(client, process)
                ready_ms = round((time.perf_counter() - started) * 1000, 2)
                pointer = client.get("/api/v1/atlas/promotion/current")
                pointer.raise_for_status()
                current = pointer.json()
        finally:
            stop(process, log)
        if sha256(backup) != original_hash:
            raise AssertionError("Supplied backup changed")
        result = {"provider": args.provider, "sample_count": 1, "ready_ms": ready_ms,
                  "backup_sha256_unchanged": True, "copied_pointer": current}
        (output_dir / "cold-start-result.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({"provider": args.provider, "ready_ms": ready_ms, "sample_count": 1}, sort_keys=True))


if __name__ == "__main__":
    main()
