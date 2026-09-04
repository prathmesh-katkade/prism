"""Constrained project-scoped Python surface for Atlas, never a host shell."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from prism_api_contracts import (
    AtlasSandboxArtifact,
    AtlasSandboxErrorKind,
    AtlasSandboxExecutionRequest,
    AtlasSandboxExecutionResult,
    AtlasSandboxWorkerHealth,
)

_ALLOWED_TOP_LEVEL = {
    "pandas",
    "numpy",
    "polars",
    "scipy",
    "statsmodels",
    "sklearn",
    "duckdb",
    "matplotlib",
    "shap",
    "math",
    "statistics",
    "json",
    "csv",
    "datetime",
    "collections",
}
_ARTIFACT_TYPES = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".png": "image/png",
    ".html": "text/html",
    ".ipynb": "application/x-ipynb+json",
    ".py": "text/x-python",
}
_BOOTSTRAP = r"""
import builtins, json, os, pathlib, random, socket
ROOT = pathlib.Path.cwd().resolve()
ARTIFACTS = (ROOT / "artifacts").resolve(); ARTIFACTS.mkdir(exist_ok=True)
def _contained(path):
    item = pathlib.Path(path)
    target = item.resolve() if item.is_absolute() else (ROOT / item).resolve()
    if target != ROOT and ROOT not in target.parents: raise PermissionError("sandbox filesystem policy denied this path")
    return target
_open = builtins.open
def _safe_open(path, *args, **kwargs): return _open(_contained(path), *args, **kwargs)
builtins.open = _safe_open
_path_open = pathlib.Path.open
pathlib.Path.open = lambda self, *args, **kwargs: _path_open(_contained(self), *args, **kwargs)
def _network_denied(*args, **kwargs): raise PermissionError("sandbox network policy denies network access")
socket.socket = _network_denied; socket.create_connection = _network_denied
ALLOWED = set(json.loads((ROOT / "allowed.json").read_text()))
_import = builtins.__import__
def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name.split(".")[0] not in ALLOWED: raise ImportError("sandbox import policy denied: " + name)
    builtins.__import__ = _import
    try: return _import(name, globals, locals, fromlist, level)
    finally: builtins.__import__ = _safe_import
builtins.__import__ = _safe_import
os.environ.clear()
seed = int((ROOT / "seed.txt").read_text()); random.seed(seed)
try:
    import numpy as np; np.random.seed(seed)
except Exception: pass
code = (ROOT / "analysis.py").read_text()
namespace = {"__name__": "__atlas_sandbox__", "ARTIFACT_DIR": str(ARTIFACTS), "SEED": seed}
exec(compile(code, "analysis.py", "exec"), namespace, namespace)
"""


class AtlasPythonSandbox:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = (root or Path(".prism/runtime/atlas-sandboxes")).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _validate(self, code: str) -> Optional[str]:
        try:
            tree = ast.parse(code, mode="exec")
        except SyntaxError as error:
            return f"Python syntax error: {error.msg}."
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [str(node.module or "").split(".")[0]]
            if names and any(name not in _ALLOWED_TOP_LEVEL for name in names):
                return f"Sandbox import policy denied: {', '.join(names)}."
        return None

    @staticmethod
    def _bounded(value: str) -> str:
        return value[-32_000:]

    def _artifacts(self, directory: Path) -> list[AtlasSandboxArtifact]:
        found: list[AtlasSandboxArtifact] = []
        for path in sorted(directory.glob("*")):
            if not path.is_file() or path.suffix.lower() not in _ARTIFACT_TYPES:
                continue
            content = path.read_bytes()
            found.append(
                AtlasSandboxArtifact(
                    artifact_id=f"artifact_{uuid.uuid4().hex}",
                    filename=path.name,
                    media_type=_ARTIFACT_TYPES[path.suffix.lower()],
                    byte_count=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                )
            )
        return found

    @staticmethod
    def _terminate_tree(process: subprocess.Popen[str]) -> None:
        """Terminate descendants as well as the worker interpreter on timeout/cancel."""
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
            )
        else:
            process.kill()

    @staticmethod
    def worker_health() -> AtlasSandboxWorkerHealth:
        container_available = bool(shutil.which("docker") or shutil.which("podman"))
        if os.name == "nt":
            return AtlasSandboxWorkerHealth(
                state="degraded",
                execution_mode="native_worker",
                network_policy="deny_by_default",
                process_tree_termination=True,
                cpu_quota_enforced=False,
                memory_quota_enforced=False,
                container_available=container_available,
                detail="Native Windows worker clears user environment and kills process trees, but cannot honestly enforce CPU or memory quotas. Configure a container-worker adapter for hard quotas.",
            )
        return AtlasSandboxWorkerHealth(
            state="ready",
            execution_mode="native_worker",
            network_policy="deny_by_default",
            process_tree_termination=True,
            cpu_quota_enforced=False,
            memory_quota_enforced=False,
            container_available=container_available,
            detail="Native worker provides a separate process and process-group termination. Container worker is required for portable hard CPU/memory quotas.",
        )

    def execute(
        self,
        request: AtlasSandboxExecutionRequest,
        *,
        cancelled: Optional[Callable[[], bool]] = None,
    ) -> AtlasSandboxExecutionResult:
        execution_id = f"sandbox_{uuid.uuid4().hex}"
        started = time.monotonic()
        violation = self._validate(request.code)
        if violation:
            return AtlasSandboxExecutionResult(
                execution_id=execution_id,
                state="failed",
                error_kind=AtlasSandboxErrorKind.POLICY,
                error=violation,
                duration_ms=0,
                limits_enforced=["import_policy"],
            )
        workspace = (self.root / execution_id).resolve()
        artifacts = workspace / "artifacts"
        artifacts.mkdir(parents=True)
        (workspace / "analysis.py").write_text(request.code, encoding="utf-8")
        (workspace / "allowed.json").write_text(
            json.dumps(sorted(_ALLOWED_TOP_LEVEL)), encoding="utf-8"
        )
        (workspace / "seed.txt").write_text(str(request.seed), encoding="utf-8")
        (workspace / "bootstrap.py").write_text(_BOOTSTRAP, encoding="utf-8")
        # Windows needs this one OS routing variable to start an isolated Python
        # process. The child clears its environment before executing user code.
        environment = {
            "PYTHONHASHSEED": str(request.seed),
            "MPLCONFIGDIR": str(workspace / "matplotlib"),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\\Windows"),
            "WINDIR": os.environ.get("WINDIR", r"C:\\Windows"),
        }
        # ``-E`` ignores inherited Python path/configuration. ``-I`` would also
        # hide this Windows install's approved scientific packages because they
        # reside in its user site; the child still receives a deliberately empty
        # environment and enforces imports before user code executes.
        process = subprocess.Popen(
            [sys.executable, "-E", str(workspace / "bootstrap.py")],
            cwd=str(workspace),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        limits = ["timeout", "process_tree", "environment", "network", "filesystem", "import_policy"]
        while process.poll() is None:
            if cancelled and cancelled():
                self._terminate_tree(process)
                stdout, stderr = process.communicate()
                return AtlasSandboxExecutionResult(
                    execution_id=execution_id,
                    state="cancelled",
                    stdout=self._bounded(stdout),
                    stderr=self._bounded(stderr),
                    error_kind=AtlasSandboxErrorKind.CANCELLED,
                    error="Sandbox execution was cancelled.",
                    duration_ms=round((time.monotonic() - started) * 1000),
                    limits_enforced=limits,
                )
            if time.monotonic() >= started + request.timeout_ms / 1000:
                self._terminate_tree(process)
                stdout, stderr = process.communicate()
                return AtlasSandboxExecutionResult(
                    execution_id=execution_id,
                    state="timed_out",
                    stdout=self._bounded(stdout),
                    stderr=self._bounded(stderr),
                    error_kind=AtlasSandboxErrorKind.TIMEOUT,
                    error="Sandbox execution exceeded its timeout.",
                    duration_ms=round((time.monotonic() - started) * 1000),
                    limits_enforced=limits,
                )
            time.sleep(0.02)
        stdout, stderr = process.communicate()
        elapsed = round((time.monotonic() - started) * 1000)
        if process.returncode != 0:
            return AtlasSandboxExecutionResult(
                execution_id=execution_id,
                state="failed",
                stdout=self._bounded(stdout),
                stderr=self._bounded(stderr),
                error_kind=AtlasSandboxErrorKind.EXECUTION,
                error="Sandboxed Python exited with an error.",
                duration_ms=elapsed,
                limits_enforced=limits,
            )
        return AtlasSandboxExecutionResult(
            execution_id=execution_id,
            state="completed",
            stdout=self._bounded(stdout),
            stderr=self._bounded(stderr),
            artifacts=self._artifacts(artifacts),
            duration_ms=elapsed,
            limits_enforced=limits,
        )
