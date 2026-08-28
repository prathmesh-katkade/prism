"""Small local secret gate; production CI also runs gitleaks for historical scanning."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"(?i)(api[_-]?key|secret|token)\s*=\s*['\"][^'\"]{16,}['\"]"),
)


def main() -> int:
    files = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    findings: list[str] = []
    for filename in files:
        path = ROOT / filename
        if not path.is_file() or path.suffix.lower() not in {
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".mjs",
            ".json",
            ".yml",
            ".yaml",
        }:
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        if any(pattern.search(content) for pattern in PATTERNS):
            findings.append(filename)
    if findings:
        print(f"Potential hard-coded secrets: {', '.join(findings)}")
        return 1
    print("Local secret scan: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
