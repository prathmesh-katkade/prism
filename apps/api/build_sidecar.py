#!/usr/bin/env python3
"""Builds apps/api into a standalone binary for the Tauri desktop sidecar
(apps/desktop-shell/src-tauri/src/sidecar.rs spawns whatever this produces).

Not used by the normal dev/staging path (`uvicorn prism_api.main:app`, see
render.yaml) -- this is packaging for the desktop app only.

Two things that weren't obvious and cost real debugging time, kept here so
a future change doesn't silently reintroduce them:

1. `--onedir` (PyInstaller's default, faster startup) ships an executable
   that depends on a sibling `_internal/` directory at a fixed relative
   path. Tauri's `bundle.externalBin` only knows how to place a single
   renamed executable in the app bundle; getting a whole extra directory
   to land next to it at the exact same relative path Tauri chooses at
   runtime is fragile across platforms/bundle formats. `--onefile` bundles
   everything into one executable (self-extracts to a temp dir per launch,
   a few extra seconds of startup) and sidesteps the problem entirely --
   use that here even though onedir would start faster.

2. The workspace's Python packages (packages/*/python) are installed
   editable via a dynamic MetaPathFinder (`pip install -e`), which
   PyInstaller's static import analysis can't see through hidden-imports
   alone -- it needs their real source directories on --paths, or the
   frozen binary fails at runtime with `ModuleNotFoundError` for every
   editable package despite a clean build exit code.

shap (numba/llvmlite JIT) is collected whole because it's the highest-risk
dependency here for a frozen build to get subtly wrong. Verify it for real
after any change to this script, not just a clean PyInstaller exit code:

    dist/prism-api &
    curl -X POST http://127.0.0.1:8000/api/v1/ml/datasets/<id>/shap ...

install_sidecar_binary() copies the single onefile executable into
src-tauri/binaries/ under Tauri's required
`<name>-<rust-target-triple>[.exe]` naming so `tauri build`'s
`bundle.externalBin` picks it up.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parent
REPO_ROOT = API_DIR.parent.parent
PACKAGES = ["api-contracts", "config", "overview-analytics", "sql-lab-runtime", "analytical-schemas"]
SIDECAR_NAME = "prism-api"
BINARIES_DIR = REPO_ROOT / "apps" / "desktop-shell" / "src-tauri" / "binaries"


def rust_target_triple() -> str:
    """Matches `rustc -vV`'s host line -- Tauri's externalBin convention
    needs the exact triple, not a guess from platform.machine()/system()."""
    result = subprocess.run(["rustc", "-vV"], capture_output=True, text=True, check=True)
    for line in result.stdout.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError("could not determine rustc host target triple (is Rust installed?)")


def run_pyinstaller() -> Path:
    dist_exe = API_DIR / "dist" / SIDECAR_NAME
    build_dir = API_DIR / "build"
    for stale in (dist_exe, dist_exe.with_suffix(".exe"), build_dir, API_DIR / f"{SIDECAR_NAME}.spec"):
        if stale.exists():
            shutil.rmtree(stale) if stale.is_dir() else stale.unlink()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", SIDECAR_NAME,
        "--onefile", "--noconfirm",
        "--paths", "src",
        *[arg for pkg in PACKAGES for arg in ("--paths", str(REPO_ROOT / "packages" / pkg / "python"))],
        "--collect-all", "shap",
        "--collect-submodules", "sklearn",
        "--collect-submodules", "scipy",
        "--collect-submodules", "statsmodels",
        "--exclude-module", "numba.tests",
        "--exclude-module", "llvmlite.tests",
        "--hidden-import", "pymysql",
        "desktop_entry.py",
    ]
    subprocess.run(cmd, cwd=API_DIR, check=True)
    exe = dist_exe.with_suffix(".exe") if platform.system() == "Windows" else dist_exe
    if not exe.exists():
        raise RuntimeError(f"PyInstaller reported success but {exe} doesn't exist")
    return exe


def install_sidecar_binary(built_exe: Path, target_triple: str) -> Path:
    BINARIES_DIR.mkdir(parents=True, exist_ok=True)
    exe_suffix = built_exe.suffix  # ".exe" on Windows, "" elsewhere
    dest = BINARIES_DIR / f"{SIDECAR_NAME}-{target_triple}{exe_suffix}"
    shutil.copy2(built_exe, dest)
    if exe_suffix == "":
        dest.chmod(0o755)
    return dest


def main() -> None:
    triple = rust_target_triple()
    print(f"[build_sidecar] target triple: {triple}")
    built_exe = run_pyinstaller()
    dest = install_sidecar_binary(built_exe, triple)
    print(f"[build_sidecar] sidecar ready: {dest} ({dest.stat().st_size / 1_048_576:.0f} MB)")


if __name__ == "__main__":
    main()
