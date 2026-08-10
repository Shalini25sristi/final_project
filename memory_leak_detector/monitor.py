import ctypes
import math
import os
import random
import time
from dataclasses import dataclass

from .system_metrics import MetricsUnavailable, SystemMetrics


@dataclass
class MonitorData:
    second: int
    memory_mb: float
    cpu_percent: float
    score: int
    leak: bool


class CState(ctypes.Structure):
    _fields_ = [
        ("second", ctypes.c_int),
        ("memory_mb", ctypes.c_double),
        ("cpu_percent", ctypes.c_double),
        ("random_state", ctypes.c_uint),
        ("history_size", ctypes.c_int),
        ("count", ctypes.c_int),
        ("memory_history", ctypes.POINTER(ctypes.c_double)),
        ("cpu_history", ctypes.POINTER(ctypes.c_double)),
    ]


class CData(ctypes.Structure):
    _fields_ = [
        ("second", ctypes.c_int),
        ("memory_mb", ctypes.c_double),
        ("cpu_percent", ctypes.c_double),
        ("score", ctypes.c_int),
        ("leak", ctypes.c_int),
    ]


def load_library():
    dll_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "c_core",
        "monitor_core.dll",
    )
    if not os.path.exists(dll_path):
        return None, "Mode: Python fallback"
    try:
        library = ctypes.CDLL(dll_path)
    except OSError:
        return None, "Mode: Python fallback"

    library.init_monitor.argtypes = [ctypes.POINTER(CState), ctypes.c_uint]
    library.init_monitor.restype = ctypes.c_int
    library.free_monitor.argtypes = [ctypes.POINTER(CState)]
    library.free_monitor.restype = None
    # CHANGED FOR 2.1: next_monitor_data now takes the real memory/cpu
    # readings as explicit arguments instead of generating them itself.
    library.next_monitor_data.argtypes = [
        ctypes.POINTER(CState),
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.POINTER(CData),
    ]
    library.next_monitor_data.restype = ctypes.c_int
    return library, "Mode: C backend"


LIBRARY, BACKEND_TEXT = load_library()


class Monitor:
    def __init__(self, target_pid: int | None = None) -> None:
        self.backend_text = BACKEND_TEXT
        self.use_c = LIBRARY is not None
        self.closed = False

        # 2.1 Target Scoping: track a specific PID, or the whole host
        # system when target_pid is None. Falls back to global scope
        # if the requested PID isn't readable.
        try:
            self.metrics = SystemMetrics(target_pid)
        except MetricsUnavailable:
            self.metrics = SystemMetrics(None)

        if self.use_c:
            self.state = CState()
            ok = LIBRARY.init_monitor(ctypes.byref(self.state), int(time.time()))
            if ok:
                return
            self.use_c = False

        self.second = 0
        self.history_size = 24
        self.memory_history = []
        self.cpu_history = []
        self.memory_mb = 0.0
        self.cpu_percent = 0.0

    def set_target(self, pid: int | None) -> None:
        """Re-scope monitoring to a specific PID, or None for global host."""
        self.metrics.set_target(pid)

    @property
    def target_label(self) -> str:
        return self.metrics.label

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.use_c:
            LIBRARY.free_monitor(ctypes.byref(self.state))

    def next_data(self, threshold: float = 420.0) -> MonitorData:
        
        try:
            memory_mb, cpu_percent = self.metrics.read()
        except MetricsUnavailable:
            # Target process disappeared mid-run — fall back to global
            # host tracking rather than crashing the monitor.
            self.metrics.set_target(None)
            memory_mb, cpu_percent = self.metrics.read()

        if self.use_c:
            data = CData()
            ok = LIBRARY.next_monitor_data(
                ctypes.byref(self.state), threshold, memory_mb, cpu_percent, ctypes.byref(data)
            )
            if not ok:
                return MonitorData(self.second, memory_mb, cpu_percent, 0, False)
            return MonitorData(
                second=data.second,
                memory_mb=data.memory_mb,
                cpu_percent=data.cpu_percent,
                score=data.score,
                leak=bool(data.leak),
            )

        self.second += 1
        self.memory_mb = memory_mb
        self.cpu_percent = cpu_percent

        self.memory_history.append(self.memory_mb)
        self.cpu_history.append(self.cpu_percent)
        if len(self.memory_history) > self.history_size:
            self.memory_history.pop(0)
            self.cpu_history.pop(0)

        score = int(self.isolation_score())
        if self.memory_mb > threshold:
            score += 20
        score = min(score, 100)

        return MonitorData(
            second=self.second,
            memory_mb=self.memory_mb,
            cpu_percent=self.cpu_percent,
            score=score,
            leak=score >= 60,
        )

    def isolation_score(self) -> float:
        if len(self.memory_history) < 4:
            return 0.0

        tree_count = 8
        sample_size = min(8, len(self.memory_history))
        max_depth = 4
        total_path = 0.0

        all_points = list(zip(self.memory_history, self.cpu_history))
        target = (self.memory_mb, self.cpu_percent)

        for _ in range(tree_count):
            sample = random.sample(all_points, sample_size)
            total_path += self.path_length(sample, target, 0, max_depth)

        average_path = total_path / tree_count
        normal_length = self.average_path_length(sample_size)
        return (2.0 ** (-average_path / normal_length)) * 100.0

    def path_length(self, sample, target, depth: int, max_depth: int) -> float:
        if len(sample) <= 1 or depth >= max_depth:
            return depth + self.average_path_length(len(sample))

        feature = random.randint(0, 1)
        values = [point[feature] for point in sample]
        minimum = min(values)
        maximum = max(values)

        if maximum - minimum < 1e-9:
            return depth + self.average_path_length(len(sample))

        split = random.uniform(minimum, maximum)
        left = [point for point in sample if point[feature] < split]
        right = [point for point in sample if point[feature] >= split]

        if target[feature] < split:
            if not left:
                return depth + 1.0
            return self.path_length(left, target, depth + 1, max_depth)

        if not right:
            return depth + 1.0
        return self.path_length(right, target, depth + 1, max_depth)

    def average_path_length(self, size: int) -> float:
        if size <= 1:
            return 0.0
        if size == 2:
            return 1.0
        return 2.0 * (math.log(size - 1) + 0.5772156649) - (2.0 * (size - 1) / size)
