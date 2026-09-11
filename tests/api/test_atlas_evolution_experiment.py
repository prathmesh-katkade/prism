from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace


def _runner_module():  # type: ignore[no-untyped-def]
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "atlas_evolution_runner", root / "tools" / "run_atlas_evolution_experiment.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_candidate_export_decodes_soup_output_as_utf8_on_windows(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    runner = _runner_module()
    candidate = SimpleNamespace(
        adapter_path=str(tmp_path / "adapter"),
        candidate_id="candidate_utf8_1",
        base_model="Qwen/Qwen2.5-0.5B-Instruct",
    )
    Path(candidate.adapter_path).mkdir()
    expected_model = f"atlas-candidate-{hashlib.sha256(candidate.candidate_id.encode()).hexdigest()[:16]}"
    observed: dict[str, object] = {}

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        observed["command"] = command
        observed.update(kwargs)
        observed["stdout_mode"] = kwargs["stdout"].mode
        return SimpleNamespace(returncode=0)

    class TagsResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"models": [{"name": f"{expected_model}:latest", "digest": "candidate-digest"}]}

    bindings: list[tuple[str, str, str]] = []

    class BindingStore:
        def bind_ollama(self, candidate_id: str, model: str, *, runtime_model_digest: str) -> None:
            bindings.append((candidate_id, model, runtime_model_digest))

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner.httpx, "get", lambda *args, **kwargs: TagsResponse())
    monkeypatch.setattr(runner, "DurableAtlasCandidateRuntimeStore", BindingStore)

    model, digest, _, export_log = runner.deploy_candidate_to_ollama(
        "soup", candidate, timeout_seconds=1
    )

    assert observed["stdout_mode"] == "wb"
    assert observed["stderr"] is subprocess.STDOUT
    assert observed["env"] == {**os.environ, "PYTHONUTF8": "1"}
    assert model == f"{expected_model}:latest"
    assert digest == "candidate-digest"
    assert export_log.endswith(".export.log")
    assert bindings == [(candidate.candidate_id, model, digest)]
