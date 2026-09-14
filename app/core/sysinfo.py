"""Machine and process stats for the window's status bar.

Everything here is stdlib, so the status bar works on a bare install; psutil is
used when it happens to be present because it is more accurate. The probes that
shell out (GPU names) run once and are cached, the rest only read counters and
are cheap enough to poll every second.
"""
import ctypes
import os
import shutil
import subprocess
import sys
import threading
import time
from functools import lru_cache

try:
    import psutil
except ImportError:                              # optional, never a dependency
    psutil = None

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
# Vendor fragment -> the hardware encoder FFmpeg would reach for on that GPU.
_ACCELERATORS = (
    ("nvidia", "NVENC"),
    ("geforce", "NVENC"),
    ("quadro", "NVENC"),
    ("intel", "Quick Sync"),
    ("arc ", "Quick Sync"),
    ("amd", "AMF"),
    ("radeon", "AMF"),
    ("apple", "VideoToolbox"),
)
_GPU_NOISE = ("(R)", "(TM)", "(r)", "(tm)", "Corporation", "Technologies Inc.", "Inc.")


def human_bytes(value):
    """Compact size for the strip: 512 MB, 15.9 GB, 1.2 TB."""
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB", "MB") else f"{size:.1f} {unit}"
        size /= 1024
    return "-"


# ------------------------------------------------------------------ memory

class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _windows_memory():
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return status.ullTotalPhys - status.ullAvailPhys, status.ullTotalPhys


def _proc_memory():
    total = available = 0
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                key, _, rest = line.partition(":")
                if key == "MemTotal":
                    total = int(rest.split()[0]) * 1024
                elif key == "MemAvailable":
                    available = int(rest.split()[0]) * 1024
                if total and available:
                    break
    except (OSError, ValueError, IndexError):
        return None
    return (total - available, total) if total else None


def _sysconf_memory():
    """Total RAM only; macOS and the BSDs have no cheap "available" counter."""
    try:
        total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, ValueError, OSError):
        return None
    return (None, total) if total else None


def memory():
    """(used, total) bytes for the machine. `used` is None when unknown."""
    if psutil is not None:
        stats = psutil.virtual_memory()
        return stats.total - stats.available, stats.total
    if sys.platform == "win32":
        try:
            return _windows_memory()
        except (AttributeError, OSError):
            return None
    return _proc_memory() or _sysconf_memory()


def process_memory():
    """Resident bytes held by this app, or None when the platform is unknown."""
    if psutil is not None:
        try:
            return psutil.Process().memory_info().rss
        except psutil.Error:
            return None
    if sys.platform == "win32":
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        try:
            # The pseudo-handle is -1; it must travel as a pointer, not an int.
            handle = ctypes.c_void_p(ctypes.windll.kernel32.GetCurrentProcess())
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            )
        except (AttributeError, OSError):
            return None
        return counters.WorkingSetSize if ok else None
    try:
        with open("/proc/self/statm", encoding="utf-8") as f:
            pages = int(f.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError, AttributeError):
        return None


# --------------------------------------------------------------------- cpu

def _system_cpu_times():
    """(busy, total) CPU ticks for the whole machine, or None."""
    if sys.platform == "win32":
        idle, kernel, user = (ctypes.c_ulonglong() for _ in range(3))
        try:
            ok = ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
            )
        except (AttributeError, OSError):
            return None
        if not ok:
            return None
        total = float(kernel.value + user.value)
        return total - idle.value, total
    try:
        with open("/proc/stat", encoding="utf-8") as f:
            fields = [float(value) for value in f.readline().split()[1:]]
    except (OSError, ValueError, IndexError):
        return None
    if len(fields) < 5:
        return None
    total = sum(fields)
    return total - (fields[3] + fields[4]), total


def _process_cpu_times():
    """Last resort: this process's own CPU share of every core."""
    return time.process_time(), time.monotonic() * (os.cpu_count() or 1)


class CpuMeter:
    """CPU load between two calls of `percent()`; None until it has a baseline."""

    def __init__(self):
        self._previous = _system_cpu_times() or _process_cpu_times()

    def percent(self):
        if psutil is not None:
            return psutil.cpu_percent(None) or 0.0
        sample = _system_cpu_times() or _process_cpu_times()
        previous, self._previous = self._previous, sample
        if not previous or sample[1] <= previous[1]:
            return None
        share = (sample[0] - previous[0]) / (sample[1] - previous[1]) * 100
        return max(0.0, min(100.0, share))


def cpu_label():
    cores = os.cpu_count() or 0
    return f"{cores} logical core(s)" if cores else "Processor load"


# -------------------------------------------------------------------- disk

def disk(path):
    """(free, total) bytes for the volume holding `path`, or None."""
    path = os.path.abspath(path or os.getcwd())
    while not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return usage.free, usage.total


def volume_name(path):
    """"C:" on Windows, the mount point elsewhere."""
    path = os.path.abspath(path or os.getcwd())
    drive = os.path.splitdrive(path)[0]
    if drive:
        return drive
    while not os.path.ismount(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path


# --------------------------------------------------------------------- gpu

def _run(command):
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=8,
            creationflags=_NO_WINDOW, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout or ""


class _DisplayDevice(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("DeviceName", ctypes.c_wchar * 32),
        ("DeviceString", ctypes.c_wchar * 128),
        ("StateFlags", ctypes.c_ulong),
        ("DeviceID", ctypes.c_wchar * 128),
        ("DeviceKey", ctypes.c_wchar * 128),
    ]


def _windows_gpus():
    """Adapters from user32 first: no subprocess, so it answers instantly."""
    names = []
    device = _DisplayDevice()
    device.cb = ctypes.sizeof(device)
    try:
        for index in range(8):
            if not ctypes.windll.user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
                break
            names.append(device.DeviceString)
    except (AttributeError, OSError):
        names = []
    if names:
        return names
    text = _run([
        "powershell", "-NoProfile", "-Command",
        "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
    ])
    return text.splitlines()


def _linux_gpus():
    names = []
    for line in _run(["lspci"]).splitlines():
        if "VGA compatible controller" in line or "3D controller" in line:
            names.append(line.split(": ", 1)[-1])
    return names


def _macos_gpus():
    return [
        line.split(":", 1)[1]
        for line in _run(["system_profiler", "SPDisplaysDataType"]).splitlines()
        if "Chipset Model:" in line
    ]


@lru_cache(maxsize=1)
def gpu_names():
    """Display adapters the OS reports, deduplicated. Detected once, then cached."""
    if sys.platform == "win32":
        found = _windows_gpus()
    elif sys.platform == "darwin":
        found = _macos_gpus()
    else:
        found = _linux_gpus()
    names = []
    for name in found:
        name = name.strip()
        if name and name not in names:
            names.append(name)
    return tuple(names)


def accelerator(name):
    """The hardware video encoder this adapter is likely to expose, or ""."""
    lowered = f"{name.lower()} "
    for fragment, label in _ACCELERATORS:
        if fragment in lowered:
            return label
    return ""


def short_gpu(name, limit=30):
    """Trim vendor boilerplate so the adapter fits on the strip."""
    for noise in _GPU_NOISE:
        name = name.replace(noise, "")
    name = " ".join(name.split())
    return name if len(name) <= limit else name[: limit - 1].rstrip() + "…"


def gpu_summary():
    """(label, tooltip) for the GPU section; safe to call from a worker thread."""
    names = gpu_names()
    if not names:
        return "No GPU found", "The system did not report a display adapter."
    lines = [
        f"{name} — {accelerator(name) or 'no known hardware encoder'}" for name in names
    ]
    return short_gpu(names[0]), "\n".join(lines)


# ----------------------------------------------------------------- process

def process_summary():
    """(label, tooltip) describing this app: memory, threads, and pid."""
    rss = process_memory()
    threads = threading.active_count()
    label = f"{human_bytes(rss)} · {threads} thread(s)" if rss else f"{threads} thread(s)"
    tooltip = f"Reels Downloader (pid {os.getpid()})\n{threads} thread(s) running"
    if rss:
        tooltip += f"\nMemory in use: {human_bytes(rss)}"
    return label, tooltip
