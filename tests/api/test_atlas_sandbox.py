from __future__ import annotations

import os

from prism_api import atlas_platform
from prism_api.atlas_sandbox import AtlasPythonSandbox
from prism_api_contracts import AtlasSandboxErrorKind, AtlasSandboxExecutionRequest


def test_sandbox_runs_a_normal_deterministic_data_science_calculation(tmp_path) -> None:  # type: ignore[no-untyped-def]
    result = AtlasPythonSandbox(tmp_path).execute(
        AtlasSandboxExecutionRequest(
            code="import numpy as np\nprint(int(np.mean([2, 4, 6])))\n", timeout_ms=10_000, seed=7
        )
    )
    assert result.state == "completed" and result.stdout.strip() == "4"


def test_sandbox_rejects_host_secret_and_network_imports(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sandbox = AtlasPythonSandbox(tmp_path)
    env = sandbox.execute(AtlasSandboxExecutionRequest(code="import os\nprint(os.environ)"))
    network = sandbox.execute(
        AtlasSandboxExecutionRequest(
            code="import socket\nsocket.create_connection(('example.com', 80))"
        )
    )
    assert env.error_kind is AtlasSandboxErrorKind.POLICY
    assert network.error_kind is AtlasSandboxErrorKind.POLICY


def test_sandbox_containment_timeout_and_artifact_collection(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sandbox = AtlasPythonSandbox(tmp_path)
    escaped = sandbox.execute(
        AtlasSandboxExecutionRequest(code="open('../../outside.txt', 'w').write('no')")
    )
    timed_out = sandbox.execute(
        AtlasSandboxExecutionRequest(code="while True: pass", timeout_ms=100)
    )
    artifact = sandbox.execute(
        AtlasSandboxExecutionRequest(
            code="open(ARTIFACT_DIR + '/result.json', 'w').write('{\\\"ok\\\": true}')"
        )
    )
    assert escaped.error_kind is AtlasSandboxErrorKind.EXECUTION
    assert timed_out.error_kind is AtlasSandboxErrorKind.TIMEOUT
    assert artifact.state == "completed" and [item.filename for item in artifact.artifacts] == [
        "result.json"
    ]


def test_sandbox_worker_capabilities_are_explicit_about_platform_quotas(tmp_path) -> None:  # type: ignore[no-untyped-def]
    health = AtlasPythonSandbox(tmp_path).worker_health()
    assert health.network_policy == "deny_by_default"
    assert health.process_tree_termination is True
    assert health.execution_mode == "native_worker"


def test_new_process_group_flag_is_a_noop_off_windows() -> None:
    # This process is not Windows in CI; the Windows-only creation flag must
    # resolve to a portable no-op rather than raising AttributeError.
    if os.name != "nt":
        assert atlas_platform.new_process_group_flag() == 0


def test_sandbox_rejects_duckdb_at_static_validation(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # DuckDB does its own native file and network I/O -- it never goes through
    # builtins.open/pathlib.Path.open or Python's socket module, so it cannot
    # be contained by the bootstrap shims. It must never be importable by
    # user sandbox code (see the allowlist comment in atlas_sandbox.py).
    sandbox = AtlasPythonSandbox(tmp_path)
    plain_import = sandbox.execute(AtlasSandboxExecutionRequest(code="import duckdb\n"))
    from_import = sandbox.execute(AtlasSandboxExecutionRequest(code="from duckdb import connect\n"))
    aliased_import = sandbox.execute(AtlasSandboxExecutionRequest(code="import duckdb as ddb\n"))
    assert plain_import.error_kind is AtlasSandboxErrorKind.POLICY
    assert from_import.error_kind is AtlasSandboxErrorKind.POLICY
    assert aliased_import.error_kind is AtlasSandboxErrorKind.POLICY


def test_sandbox_rejects_duckdb_reached_dynamically_at_runtime(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # Even if a script disguises the import (dynamic __import__, importlib,
    # or via a permitted module's internals) and slips past the static AST
    # check, the bootstrap's import guard must still refuse it at runtime
    # because "duckdb" is absent from allowed.json.
    sandbox = AtlasPythonSandbox(tmp_path)
    dynamic = sandbox.execute(
        AtlasSandboxExecutionRequest(code="__import__('duckdb')\nprint('escaped')\n")
    )
    via_importlib_name = sandbox.execute(
        AtlasSandboxExecutionRequest(
            code="import importlib\nimportlib.import_module('duckdb')\nprint('escaped')\n"
        )
    )
    assert dynamic.state != "completed"
    assert "escaped" not in dynamic.stdout
    assert via_importlib_name.state != "completed"
    assert "escaped" not in via_importlib_name.stdout


def test_duckdb_is_absent_from_the_sandbox_import_allowlist() -> None:
    # Direct regression guard on the allowlist itself: this must fail loudly
    # if anyone re-adds "duckdb" without also shipping an isolated adapter.
    from prism_api.atlas_sandbox import _ALLOWED_TOP_LEVEL

    assert "duckdb" not in _ALLOWED_TOP_LEVEL


def test_sandbox_blocks_native_extension_and_ffi_surfaces(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # Adversarial coverage for "native paths" more broadly: ctypes/mmap/cffi
    # style FFI surfaces that could otherwise reach outside the interpreter's
    # sandboxed process boundary must be denied the same as duckdb.
    sandbox = AtlasPythonSandbox(tmp_path)
    ctypes_result = sandbox.execute(AtlasSandboxExecutionRequest(code="import ctypes\n"))
    mmap_result = sandbox.execute(AtlasSandboxExecutionRequest(code="import mmap\n"))
    assert ctypes_result.error_kind is AtlasSandboxErrorKind.POLICY
    assert mmap_result.error_kind is AtlasSandboxErrorKind.POLICY


def test_sandbox_blocks_subprocess_and_os_system_shellout(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sandbox = AtlasPythonSandbox(tmp_path)
    subprocess_result = sandbox.execute(
        AtlasSandboxExecutionRequest(code="import subprocess\nsubprocess.run(['echo', 'x'])\n")
    )
    os_system_result = sandbox.execute(AtlasSandboxExecutionRequest(code="import os\nos.system('echo x')\n"))
    assert subprocess_result.error_kind is AtlasSandboxErrorKind.POLICY
    assert os_system_result.error_kind is AtlasSandboxErrorKind.POLICY


def test_sandbox_blocks_network_libraries_beyond_raw_sockets(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sandbox = AtlasPythonSandbox(tmp_path)
    urllib_result = sandbox.execute(
        AtlasSandboxExecutionRequest(code="import urllib.request\nurllib.request.urlopen('http://example.com')\n")
    )
    http_client_result = sandbox.execute(AtlasSandboxExecutionRequest(code="import http.client\n"))
    assert urllib_result.error_kind is AtlasSandboxErrorKind.POLICY
    assert http_client_result.error_kind is AtlasSandboxErrorKind.POLICY


def test_sandbox_blocks_absolute_path_filesystem_escape(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # Beyond the existing relative-path-traversal coverage, an absolute path
    # pointing straight at a host file outside the sandbox root must also be
    # denied by the containment check in the bootstrap's builtins.open shim.
    sandbox = AtlasPythonSandbox(tmp_path)
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("do-not-read", encoding="utf-8")
    escape_target = str(outside).replace("\\", "\\\\")
    code = f"open(r'{escape_target}').read()\nprint('escaped')\n"
    result = sandbox.execute(AtlasSandboxExecutionRequest(code=code))
    assert "escaped" not in result.stdout
    assert result.error_kind is AtlasSandboxErrorKind.EXECUTION


def test_sandbox_blocks_os_and_pathlib_imports_structurally_preventing_symlink_escapes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # os and pathlib are not on the import allowlist, so a sandboxed script
    # can never call os.symlink/Path.symlink_to in the first place -- this is
    # the structural reason a symlink-hop escape is unreachable, not just an
    # incidental gap. Regression guard for that property.
    sandbox = AtlasPythonSandbox(tmp_path)
    os_result = sandbox.execute(AtlasSandboxExecutionRequest(code="import os\nos.symlink('a', 'b')\n"))
    pathlib_result = sandbox.execute(AtlasSandboxExecutionRequest(code="import pathlib\n"))
    assert os_result.error_kind is AtlasSandboxErrorKind.POLICY
    assert pathlib_result.error_kind is AtlasSandboxErrorKind.POLICY


def test_memory_status_reads_something_truthful_or_admits_it_cannot(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # Never fabricate a number: either a real (total, available) pair or an
    # honest "unknown" -- the Resource Governor's truthful-telemetry contract.
    status = atlas_platform.read_memory_status_mb()
    if status is not None:
        assert status.total_mb > 0
        assert status.available_mb >= 0
