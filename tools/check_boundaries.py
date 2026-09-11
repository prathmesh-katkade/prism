"""Dependency direction checks for Phase 1; intentionally stdlib-only for CI determinism."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PYTHON_IMPORTS = ("app", "modules", "api")
FORBIDDEN_WEB_SEGMENTS = (
    "../../api",
    "../../../api",
    "../../modules",
    "../../../modules",
    "app.py",
)


def python_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def main() -> int:
    violations: list[str] = []
    for path in (ROOT / "apps" / "api" / "src").rglob("*.py"):
        for imported in python_imports(path):
            if imported == "api" or imported.startswith(
                tuple(f"{name}." for name in FORBIDDEN_PYTHON_IMPORTS)
            ):
                violations.append(f"{path.relative_to(ROOT)} imports legacy boundary {imported}")
    for path in (ROOT / "apps" / "web" / "src").rglob("*.ts*"):
        source = path.read_text(encoding="utf-8")
        if any(segment in source for segment in FORBIDDEN_WEB_SEGMENTS):
            violations.append(f"{path.relative_to(ROOT)} crosses an application/legacy boundary")
    if violations:
        print("\n".join(violations))
        return 1
    print("Dependency boundaries: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
