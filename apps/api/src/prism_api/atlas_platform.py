"""Platform-specific helpers so cross-platform Atlas modules stay honest.

``subprocess.CREATE_NEW_PROCESS_GROUP`` and ``ctypes.windll`` are Windows-only
symbols: they simply do not exist in typeshed's stubs for other platforms.
Referencing them directly behind an ``os.name == "nt"`` branch is correct at
runtime but mypy cannot narrow a module's available attributes on a runtime
``os.name`` check, so it flags the attribute access on every platform,
including the Linux CI runner these modules must type-check on.

These helpers isolate that platform branching behind ``getattr`` with an
explicit default, so real behavior on Windows is unchanged, non-Windows
platforms get a truthful "not available here" value instead of a crash, and
mypy has nothing to statically resolve.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
from typing import NamedTuple, Optional


def new_process_group_flag() -> int:
    """The ``subprocess.Popen`` creation flag for a new Windows process group.

    Returns ``0`` (a no-op flag) on every other platform, where process-tree
    isolation is instead handled via ``start_new_session``.
    """
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


class MemoryStatusMb(NamedTuple):
    total_mb: int
    available_mb: int


def _windows_memory_status_mb() -> Optional[MemoryStatusMb]:
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return None

    class _MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("memory_load", ctypes.c_ulong),
            ("total_phys", ctypes.c_ulonglong),
            ("avail_phys", ctypes.c_ulonglong),
            ("total_page", ctypes.c_ulonglong),
            ("avail_page", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("avail_virtual", ctypes.c_ulonglong),
            ("avail_extended_virtual", ctypes.c_ulonglong),
        ]

    try:
        status = _MemoryStatusEx()
        status.length = ctypes.sizeof(status)
        windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    except (AttributeError, OSError):
        return None
    return MemoryStatusMb(
        total_mb=status.total_phys // 1_048_576,
        available_mb=status.avail_phys // 1_048_576,
    )


def _posix_memory_status_mb() -> Optional[MemoryStatusMb]:
    # SC_PAGE_SIZE / SC_PHYS_PAGES are POSIX-standard sysconf names; every
    # Linux and macOS Python build exposes them, giving a truthful total even
    # without a Linux-specific dependency.
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        total_pages = os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None
    if page_size <= 0 or total_pages <= 0:
        return None
    total_mb = (page_size * total_pages) // 1_048_576
    available_mb = total_mb
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    available_mb = int(line.split()[1]) // 1024
                    break
    except OSError:
        pass  # /proc is Linux-only; macOS keeps the sysconf total as a bound.
    return MemoryStatusMb(total_mb=total_mb, available_mb=available_mb)


def read_memory_status_mb() -> Optional[MemoryStatusMb]:
    """Best-effort physical memory snapshot, or ``None`` if truly unknown.

    Never guesses: a platform this cannot read reports ``None`` rather than a
    fabricated number, matching the Resource Governor's "truthful hardware
    telemetry" contract.
    """
    if os.name == "nt":
        return _windows_memory_status_mb()
    return _posix_memory_status_mb()
