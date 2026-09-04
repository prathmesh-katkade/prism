"""Adapter foundation: typed logical-adapter identities and truthful
capability reporting.

No runtime wired into this project today can load, unload, or hot-swap a
LoRA adapter at inference time -- Atlas's providers are deterministic Python
logic or an Ollama HTTP call, neither with adapter-loading machinery. This
module exists so callers have a stable, typed set of logical adapter names
to reason about (``atlas-sql``, ``atlas-statistics``, ...) without assuming
hot-swap support exists; every capability query reports that honestly and
falls back to core Atlas, never silently pretending a switch happened.
"""

from __future__ import annotations

from prism_api_contracts import AtlasAdapterCapability, AtlasAdapterId

_UNSUPPORTED_DETAIL = (
    "No runtime configured in this deployment can load, unload, or hot-swap adapters yet; "
    "Atlas falls back to its core deterministic/Ollama provider for every request."
)


def report_adapter_capability(adapter: AtlasAdapterId) -> AtlasAdapterCapability:
    """Truthful, always-honest capability report for one logical adapter.

    Every field is conservatively False/empty until a real adapter-capable
    runtime is wired in -- reporting anything else here would be exactly the
    "pretend a capability exists" failure this module is meant to prevent.
    """
    return AtlasAdapterCapability(
        adapter=adapter,
        can_load=False,
        can_unload=False,
        can_hot_swap=False,
        memory_cost_mb=None,
        compatible_base_models=[],
        detail=_UNSUPPORTED_DETAIL,
    )


def report_all_adapter_capabilities() -> list[AtlasAdapterCapability]:
    return [report_adapter_capability(adapter) for adapter in AtlasAdapterId]
