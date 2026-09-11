"""Truthful, hardware-adaptive arbitration for Atlas workloads.

Leases are deliberately process-local in this wave: they schedule work admitted
by this API, not arbitrary host processes.  GPU metrics are optional and are
reported as unavailable rather than guessed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from prism_api_contracts import (
    AtlasResourceLease,
    AtlasResourceLeaseRequest,
    AtlasResourceSnapshot,
)

from .atlas_platform import read_memory_status_mb


class AtlasResourceGovernor:
    def __init__(self, max_active: int | None = None) -> None:
        self._lock = threading.RLock()
        self._leases: dict[str, AtlasResourceLease] = {}
        self._max_active = max_active or max(1, (os.cpu_count() or 1) - 1)

    def acquire(self, request: AtlasResourceLeaseRequest) -> AtlasResourceLease:
        with self._lock:
            active = [item for item in self._leases.values() if item.state == "active"]
            # Interactive work may preempt only cancellable, lower-priority work.
            if len(active) >= self._max_active and request.allow_preemption:
                candidates = sorted((item for item in active if item.workload.cancellable and item.workload.priority.value > request.workload.priority.value), key=lambda item: item.workload.priority.value, reverse=True)
                if candidates:
                    victim = candidates[0]
                    self._leases[victim.lease_id] = victim.model_copy(update={"state": "preempted", "reason": f"Yielded to {request.workload.priority.name.lower()} workload."})
                    active = [item for item in active if item.lease_id != victim.lease_id]
            state = "active" if len(active) < self._max_active else "queued"
            lease = AtlasResourceLease(lease_id=f"lease_{uuid.uuid4().hex}", workload=request.workload, state=state, granted_at=datetime.now(timezone.utc) if state == "active" else None, reason="Capacity admitted the workload." if state == "active" else "Waiting for a higher-priority or active workload to release capacity.")
            self._leases[lease.lease_id] = lease
            return lease

    def release(self, lease_id: str) -> AtlasResourceLease:
        with self._lock:
            lease = self._leases.get(lease_id)
            if lease is None:
                raise KeyError(lease_id)
            released = lease.model_copy(update={"state": "released", "reason": "Workload released its resource lease."})
            self._leases[lease_id] = released
            queued = sorted((item for item in self._leases.values() if item.state == "queued"), key=lambda item: item.workload.priority.value)
            if queued and len([item for item in self._leases.values() if item.state == "active"]) < self._max_active:
                next_item = queued[0]
                self._leases[next_item.lease_id] = next_item.model_copy(update={"state": "active", "granted_at": datetime.now(timezone.utc), "reason": "Capacity became available."})
            return released

    @staticmethod
    def _gpu() -> tuple[bool, str | None, int | None, str]:
        try:
            output = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=1, check=False).stdout.strip()
            if output:
                name, memory = output.splitlines()[0].rsplit(",", 1)
                return True, name.strip(), int(memory.strip()), "NVIDIA telemetry available through nvidia-smi."
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            pass
        return False, None, None, "GPU telemetry is unavailable; Atlas will not assume a GPU or VRAM budget."

    def snapshot(self) -> AtlasResourceSnapshot:
        memory = read_memory_status_mb()
        total = memory.total_mb if memory else None
        available = memory.available_mb if memory else None
        gpu, name, vram, detail = self._gpu()
        return AtlasResourceSnapshot(cpu_count=os.cpu_count() or 1, memory_total_mb=total, memory_available_mb=available, storage_free_mb=shutil.disk_usage(Path.cwd()).free // 1_048_576, gpu_available=gpu, gpu_name=name, vram_total_mb=vram, gpu_telemetry_detail=detail, active_leases=list(self._leases.values()))


governor = AtlasResourceGovernor()
