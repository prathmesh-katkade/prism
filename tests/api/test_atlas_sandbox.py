from __future__ import annotations

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
