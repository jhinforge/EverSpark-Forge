"""Node hardware and dynamic availability, in cores and bytes."""
import os
import platform
import shutil
import socket
from pathlib import Path
from .gpu import sample


def memory():
    try:
        entries = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
        total = int(entries["MemTotal"].split()[0])*1024
        available = int(entries.get("MemAvailable", entries["MemFree"]).split()[0])*1024
        return total, min(total, available)
    except (OSError, KeyError, ValueError):
        try:
            total = os.sysconf("SC_PHYS_PAGES")*os.sysconf("SC_PAGE_SIZE")
            free = os.sysconf("SC_AVPHYS_PAGES")*os.sysconf("SC_PAGE_SIZE")
            return total, min(total, free)
        except (AttributeError, OSError, ValueError):
            return 0, 0  # Unsupported system: unknown, rather than invented capacity.


def cpu_available():
    cores = float(os.cpu_count() or 1)
    if hasattr(os, "sched_getaffinity"):
        cores = min(cores, float(len(os.sched_getaffinity(0))))
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max":
            cores = min(cores, int(quota)/int(period))
    except (OSError, ValueError, ZeroDivisionError):
        pass
    return cores


def available_memory(available):
    try:
        limit = Path("/sys/fs/cgroup/memory.max").read_text().strip()
        used = int(Path("/sys/fs/cgroup/memory.current").read_text())
        if limit != "max":
            return min(available, max(0, int(limit)-used))
    except (OSError, ValueError):
        pass
    return available


def fingerprint(data_dir, metadata):
    total, free = memory()
    disk = shutil.disk_usage(data_dir)
    gpus = sample()
    capacity = {"cpu": float(os.cpu_count() or 1), "memory": total, "disk": disk.total,
                "gpu": {g["id"]: {"vram": g["vram"]} for g in gpus}}
    allocatable = {"cpu": cpu_available(), "memory": available_memory(free), "disk": disk.free,
                   "gpu": {g["id"]: {"vram": min(g["vram"], g["free_vram"])} for g in gpus}}
    return {"hostname": socket.gethostname(), "system": {"os": platform.system(), "architecture": platform.machine()},
            "hardware": {"cpu_model": platform.processor(), "gpu": [{k: v for k, v in g.items() if k != "free_vram"} for g in gpus]},
            "provider_metadata": metadata, "resources": {"capacity": capacity, "allocatable": allocatable}}


def dynamic(data_dir, capacity):
    _, free = memory()
    found = {g["id"]: g for g in sample()}
    current = {"cpu": min(capacity["cpu"], cpu_available()), "memory": min(capacity["memory"], available_memory(free)),
               "disk": min(capacity["disk"], shutil.disk_usage(data_dir).free),
               "gpu": {key: {"vram": min(value["vram"], max(0, found.get(key, {}).get("free_vram", 0)))}
                       for key, value in capacity["gpu"].items()}}
    load = {f"cpu_{minute}m": value for minute, value in zip((1, 5, 15), os.getloadavg())} if hasattr(os, "getloadavg") else {}
    return current, load
