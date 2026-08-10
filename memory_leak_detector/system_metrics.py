"""
Real-time system telemetry source for section 2.1.

Replaces the pseudo-random resource generator with live OS metrics via
psutil (which itself wraps the native platform APIs mentioned in the
spec: GetProcessMemoryInfo on Windows, /proc on Linux, task_info on
macOS). Two scoping modes are supported:

  - Target a specific process by PID
  - Track the whole host system ("global")

This module only produces (memory_mb, cpu_percent) readings. It does
not do any anomaly scoring — that stays in the C engine / isolation
forest code (section 2.2), untouched.
"""

from __future__ import annotations

import psutil


class MetricsUnavailable(Exception):
    """Raised when the requested target can't currently be read."""


class SystemMetrics:
    def __init__(self, pid: int | None = None) -> None:
        self._process: psutil.Process | None = None
        self.pid: int | None = None
        self.set_target(pid)

    def set_target(self, pid: int | None) -> None:
        """Switch scope. pid=None means track the whole host system."""
        if pid is None:
            self._process = None
            self.pid = None
            # Prime psutil's internal CPU sample window so the first
            # real reading isn't a meaningless 0.0.
            psutil.cpu_percent(interval=None)
            return

        try:
            process = psutil.Process(pid)
            process.cpu_percent(interval=None)  # prime this process's window
        except psutil.NoSuchProcess as exc:
            raise MetricsUnavailable(f"No process with PID {pid}") from exc
        except psutil.AccessDenied as exc:
            raise MetricsUnavailable(f"Access denied reading PID {pid}") from exc

        self._process = process
        self.pid = pid

    def read(self) -> tuple[float, float]:
        """Return (memory_mb, cpu_percent) for the current target.

        For a PID target: RSS memory of that process, and that
        process's CPU usage (0-100, can exceed 100 on multi-core
        systems doing psutil's convention; callers may want to
        divide by cpu_count if they want a 0-100 host-relative %).

        For global target: used system memory, and system-wide CPU
        usage across all cores (already 0-100).
        """
        try:
            if self._process is not None:
                memory_mb = self._process.memory_info().rss / (1024 * 1024)
                cpu_percent = self._process.cpu_percent(interval=None)
            else:
                memory_mb = psutil.virtual_memory().used / (1024 * 1024)
                cpu_percent = psutil.cpu_percent(interval=None)
        except psutil.NoSuchProcess as exc:
            raise MetricsUnavailable(f"Process {self.pid} exited") from exc
        except psutil.AccessDenied as exc:
            raise MetricsUnavailable(f"Access denied reading PID {self.pid}") from exc

        return memory_mb, cpu_percent

    @property
    def label(self) -> str:
        return f"PID {self.pid}" if self.pid is not None else "Global Host"
