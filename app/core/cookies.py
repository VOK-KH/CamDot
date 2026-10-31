"""Parse a cookie header, cURL command, or JSON export for yt-dlp --cookies."""
import json
import os
import pathlib
import re
import shutil
import sqlite3
import sys
import threading
from urllib.parse import urlparse

from app.core.runtime import state_dir

_COOKIE_HEADER_RE = re.compile(
    r"(?is)(?:^|\s)(?:-H|--header)\s+['\"]cookie:\s*([^'\"]+)['\"]"
)
_COOKIE_OPT_RE = re.compile(
    r"(?is)(?:^|\s)(?:-b|--cookie)\s+['\"]([^'\"]+)['\"]"
)
_HOST_HEADER_RE = re.compile(
    r"(?is)(?:^|\s)(?:-H|--header)\s+['\"]host:\s*([^'\"]+)['\"]"
)
_URL_RE = re.compile(r"https?://[^\s'\"\\]+", re.IGNORECASE)


def cookies_from_curl(text):
    """Return a Cookie header string from a cURL command or a raw cookie line."""
    text = (text or "").strip()
    if not text:
        return ""
    match = _COOKIE_HEADER_RE.search(text) or _COOKIE_OPT_RE.search(text)
    if match:
        return match.group(1).strip()
    if "curl " not in text.lower() and "=" in text:
        return text
    return ""


def _cookie_host_from_curl(text):
    text = text or ""
    host = ""
    match = _HOST_HEADER_RE.search(text)
    if match:
        host = match.group(1).strip().split(":")[0]
    if not host:
        found = _URL_RE.search(text)
        if found:
            host = urlparse(found.group(0)).hostname or ""
    return host.lower().removeprefix("www.")


def cookie_domains_from_curl(text):
    """Netscape cookie domains. Raw pastes (no host) cover Douyin and Kuaishou."""
    host = _cookie_host_from_curl(text)
    domains = []
    if host:
        if "douyin" in host:
            domains.append(".douyin.com")
        elif "kuaishou" in host or "gifshow" in host or host.endswith("kwai.com") or host == "kwai.com":
            domains.append(".kuaishou.com")
        elif "tiktok" in host:
            domains.append(".tiktok.com")
        else:
            domains.append(f".{host}")
    if not host:
        domains.extend((".douyin.com", ".kuaishou.com"))
    # De-dupe while keeping order
    seen = set()
    unique = []
    for domain in domains:
        if domain not in seen:
            seen.add(domain)
            unique.append(domain)
    return unique


def cookie_domain_from_curl(text):
    """Best-effort host for a Netscape cookie file."""
    domains = cookie_domains_from_curl(text)
    return domains[0] if domains else ".kuaishou.com"


def cookie_header_from_netscape(path, host_hint=""):
    """Build a Cookie header from a Netscape cookie file for HTTP requests."""
    if not path or not os.path.isfile(path):
        return ""
    host_hint = (host_hint or "").lower()
    parts = []
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                cols = line.split("\t")
                if len(cols) < 7:
                    continue
                domain = cols[0].lower()
                if host_hint and host_hint not in domain:
                    continue
                name, value = cols[5], cols[6]
                if name:
                    parts.append(f"{name}={value}")
    except OSError:
        return ""
    return "; ".join(parts)


def _parse_json_cookie_list(data):
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("cookies", "data", "items"):
            nested = data.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    return []


def _load_json_data(source):
    text = (source or "").strip()
    if not text:
        return None
    if os.path.isfile(text):
        try:
            with open(text, encoding="utf-8", errors="replace") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError, ValueError):
            return None
    if text.startswith("[") or text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    return None


def _vok_profile_entries(data):
    """Saved multi-account exports: {__type: vok-profiles, profiles: {...}}."""
    if not isinstance(data, dict):
        return []
    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        return []
    is_typed = data.get("__type") in ("vok-profiles", "camdot-profiles")
    has_cookie_profiles = any(
        isinstance(item, dict) and isinstance(item.get("cookies"), list)
        for item in profiles.values()
    )
    if not is_typed and not has_cookie_profiles:
        return []
    rows = []
    for pid, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        cookies = profile.get("cookies")
        if not isinstance(cookies, list):
            continue
        name = str(profile.get("name") or pid).strip()
        domain = str(profile.get("domain") or "").strip()
        rows.append({
            "id": str(profile.get("id") or pid),
            "name": name,
            "domain": domain,
            "cookies": [item for item in cookies if isinstance(item, dict)],
        })
    return rows


def list_cookie_profile_choices(source):
    """Return [(profile_id, label, domain), ...] for a vok-profiles JSON file."""
    data = _load_json_data(source)
    if data is None:
        return []
    entries = _vok_profile_entries(data)
    choices = []
    for entry in entries:
        label = entry["name"]
        domain = entry["domain"]
        if domain:
            label = f"{label} ({domain})"
        choices.append((entry["id"], label, domain))
    return choices


def _merge_cookie_lists(lists):
    merged = []
    seen = set()
    for cookies in lists:
        for cookie in cookies or []:
            if not isinstance(cookie, dict):
                continue
            key = (
                str(cookie.get("domain") or ""),
                str(cookie.get("name") or ""),
                str(cookie.get("path") or "/"),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(cookie)
    return merged


def read_json_cookies(source, profile_id=""):
    """Load cookies from Cookie-Editor JSON or a multi-account profiles export."""
    data = _load_json_data(source)
    if data is None:
        return []
    entries = _vok_profile_entries(data)
    if entries:
        wanted = (profile_id or "").strip()
        if wanted:
            for entry in entries:
                if entry["id"] == wanted:
                    return list(entry["cookies"])
            return []
        if len(entries) == 1:
            return list(entries[0]["cookies"])
        return _merge_cookie_lists(entry["cookies"] for entry in entries)
    return _parse_json_cookie_list(data)


def netscape_line_from_json_cookie(cookie):
    """One Netscape row from a browser JSON export object."""
    if not isinstance(cookie, dict):
        return ""
    name = str(cookie.get("name") or "").strip()
    if not name:
        return ""
    domain = str(cookie.get("domain") or "").strip()
    if not domain:
        return ""
    host_only = bool(cookie.get("hostOnly"))
    if host_only:
        include = "FALSE"
    else:
        include = "TRUE"
        if not domain.startswith("."):
            domain = f".{domain.lstrip('.')}"
    path = str(cookie.get("path") or "/") or "/"
    secure = "TRUE" if cookie.get("secure") else "FALSE"
    if cookie.get("session"):
        expiry = "0"
    else:
        raw_exp = cookie.get("expirationDate")
        try:
            expiry = str(int(float(raw_exp))) if raw_exp not in (None, "") else "0"
        except (TypeError, ValueError):
            expiry = "0"
    value = str(cookie.get("value") or "")
    return f"{domain}\t{include}\t{path}\t{secure}\t{expiry}\t{name}\t{value}"


def write_netscape_from_json(cookies, path):
    """Write JSON cookie objects to a Netscape file for yt-dlp."""
    lines = ["# Netscape HTTP Cookie File"]
    for cookie in cookies or []:
        row = netscape_line_from_json_cookie(cookie)
        if row:
            lines.append(row)
    if len(lines) < 2:
        return ""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def write_netscape_cookies(raw, path=None):
    """Write a Netscape cookie file. Returns the path, or '' when there is nothing to write."""
    raw = (raw or "").strip()
    path = path or os.path.join(state_dir(), "extra-cookies.txt")
    json_items = read_json_cookies(raw)
    if json_items:
        return write_netscape_from_json(json_items, path)
    header = cookies_from_curl(raw)
    if not header or "=" not in header:
        return ""
    domains = cookie_domains_from_curl(raw)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lines = ["# Netscape HTTP Cookie File"]
    for part in header.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        name, value = name.strip(), value.strip()
        if not name:
            continue
        for domain in domains:
            lines.append(f"{domain}\tTRUE\t/\tFALSE\t0\t{name}\t{value}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


_PROFILE_BROWSERS = {"brave", "chrome", "chromium", "edge", "vivaldi", "whale"}
_SKIP_BROWSER_DIRS = {
    "Cache",
    "Code Cache",
    "GPUCache",
    "Service Worker",
    "GrShaderCache",
    "ShaderCache",
    "DawnGraphiteCache",
    "DawnWebGPUCache",
    "File System",
}
_snapshot_lock = threading.Lock()
_snapshot_cache = {}


def _split_browser_spec(spec):
    spec = (spec or "").strip()
    if not spec:
        return "", ""
    browser, _, profile = spec.partition(":")
    return browser.strip().lower(), profile.strip()


def _newest_named(root, name):
    newest = ""
    newest_mtime = -1.0
    if not root or not os.path.isdir(root):
        return ""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [item for item in dirnames if item not in _SKIP_BROWSER_DIRS]
        if name not in filenames:
            continue
        path = os.path.join(dirpath, name)
        try:
            mtime = os.lstat(path).st_mtime
        except OSError:
            continue
        if mtime >= newest_mtime:
            newest = path
            newest_mtime = mtime
    return newest


def _cookie_profile_dir(cookie_db):
    parent = os.path.dirname(cookie_db)
    if os.path.basename(parent).lower() == "network":
        return os.path.dirname(parent)
    return parent


def _cookie_db_rows(path):
    try:
        uri = pathlib.Path(path).resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return 0
    try:
        row = connection.execute("SELECT count(*) FROM cookies").fetchone()
    except sqlite3.Error:
        return 0
    finally:
        connection.close()
    return int(row[0]) if row else 0


def _snapshot_sqlite(src, dest, image_name=""):
    """Copy a SQLite file that another process may have open."""
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp = dest + ".tmp"
    for path in (tmp, tmp + "-wal", tmp + "-shm"):
        try:
            os.remove(path)
        except OSError:
            pass
    uri = pathlib.Path(src).resolve().as_uri() + "?mode=ro&nolock=1"
    try:
        source = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        source = None
    if source is not None:
        try:
            try:
                target = sqlite3.connect(tmp)
                try:
                    source.backup(target)
                finally:
                    target.close()
            finally:
                source.close()
            os.replace(tmp, dest)
            if _cookie_db_rows(dest) > 0:
                return
        except sqlite3.Error:
            pass
    _copy_shared(src, dest, image_name)
    if _cookie_db_rows(dest) <= 0:
        raise sqlite3.DatabaseError("cookie snapshot is empty")


def _copy_shared(src, dest, image_name=""):
    """Read a file even when Windows has it open for exclusive use by the owner."""
    if sys.platform != "win32":
        shutil.copyfile(src, dest)
        return
    import ctypes
    from ctypes import wintypes

    generic_read = 0x80000000
    share = 0x1 | 0x2 | 0x4
    open_existing = 3
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
    ]
    kernel32.GetFileSize.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetFileSize.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.CreateFileW(src, generic_read, share, None, open_existing, 0x80, None)
    invalid = wintypes.HANDLE(-1).value
    if handle == invalid:
        error = ctypes.WinError(ctypes.get_last_error())
        if getattr(error, "winerror", None) == 32 and image_name:
            if _copy_from_browser_handle(src, dest, image_name):
                return
        raise error
    try:
        size = kernel32.GetFileSize(handle, None)
        if size in (0, 0xFFFFFFFF):
            raise OSError("empty cookie database")
        buffer = ctypes.create_string_buffer(size)
        read = wintypes.DWORD()
        if not kernel32.ReadFile(handle, buffer, size, ctypes.byref(read), None):
            raise ctypes.WinError(ctypes.get_last_error())
        with open(dest, "wb") as handle_out:
            handle_out.write(buffer.raw[: read.value])
    finally:
        kernel32.CloseHandle(handle)


_BROWSER_IMAGES = {
    "brave": "brave.exe",
    "chrome": "chrome.exe",
    "chromium": "chrome.exe",
    "edge": "msedge.exe",
    "opera": "opera.exe",
    "vivaldi": "vivaldi.exe",
    "whale": "whale.exe",
}


def _process_ids(image_name):
    import subprocess
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        output = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
            text=True,
            creationflags=flags,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    pids = []
    for line in output.splitlines():
        parts = [part.strip().strip('"') for part in line.split(",")]
        if len(parts) >= 2 and parts[1].isdigit():
            pids.append(int(parts[1]))
    return pids


def _copy_from_browser_handle(src, dest, image_name, debug=None):
    """Read a cookie database through a handle the browser already has open."""
    import ctypes
    from ctypes import wintypes

    wanted = os.path.normcase(os.path.abspath(src))
    pids = set(_process_ids(image_name))
    if not pids:
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.DuplicateHandle.argtypes = [
        wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
    ]
    kernel32.DuplicateHandle.restype = wintypes.BOOL
    kernel32.GetFileType.argtypes = [wintypes.HANDLE]
    kernel32.GetFileType.restype = wintypes.DWORD
    kernel32.GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
    ]
    kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel32.GetFileSizeEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong)]
    kernel32.GetFileSizeEx.restype = wintypes.BOOL
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
    ]
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    ntdll.NtQuerySystemInformation.argtypes = [
        wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG),
    ]
    ntdll.NtQuerySystemInformation.restype = ctypes.c_long

    class Entry(ctypes.Structure):
        _fields_ = [
            ("Object", ctypes.c_void_p),
            ("UniqueProcessId", ctypes.c_ulonglong),
            ("HandleValue", ctypes.c_ulonglong),
            ("GrantedAccess", wintypes.ULONG),
            ("CreatorBackTraceIndex", wintypes.USHORT),
            ("ObjectTypeIndex", wintypes.USHORT),
            ("HandleAttributes", wintypes.ULONG),
            ("Reserved", wintypes.ULONG),
        ]

    size = 1 << 20
    raw = None
    while size <= 64 * (1 << 20):
        raw = ctypes.create_string_buffer(size)
        returned = wintypes.ULONG(0)
        status = ntdll.NtQuerySystemInformation(64, raw, size, ctypes.byref(returned))
        if status == 0:
            break
        if (status & 0xFFFFFFFF) != 0xC0000004:
            if debug is not None:
                debug["ntstatus"] = status & 0xFFFFFFFF
            return False
        size *= 2
    else:
        if debug is not None:
            debug["ntstatus"] = "too-big"
        return False
    count = ctypes.cast(raw, ctypes.POINTER(ctypes.c_ulonglong))[0]
    entry_size = ctypes.sizeof(Entry)
    base = ctypes.addressof(raw) + 16
    current = kernel32.GetCurrentProcess()
    opened = {}
    stats = {"seen": 0, "open": 0, "dup": 0, "disk": 0, "named": 0}
    try:
        for index in range(count):
            entry = Entry.from_address(base + index * entry_size)
            pid = int(entry.UniqueProcessId)
            if pid not in pids:
                continue
            stats["seen"] += 1
            process = opened.get(pid)
            if process is None:
                process = kernel32.OpenProcess(0x0040, False, pid)
                opened[pid] = process
                if process:
                    stats["open"] += 1
            if not process:
                continue
            duplicate = wintypes.HANDLE()
            source_handle = wintypes.HANDLE(int(entry.HandleValue))
            if not kernel32.DuplicateHandle(
                process, source_handle, current, ctypes.byref(duplicate),
                0, False, 0x2,
            ):
                continue
            stats["dup"] += 1
            try:
                if kernel32.GetFileType(duplicate) != 1:
                    continue
                stats["disk"] += 1
                name_buf = ctypes.create_unicode_buffer(1024)
                length = kernel32.GetFinalPathNameByHandleW(duplicate, name_buf, 1024, 0)
                if not length:
                    continue
                stats["named"] += 1
                path = name_buf.value
                if path.startswith("\\\\?\\"):
                    path = path[4:]
                if os.path.normcase(path) != wanted:
                    continue
                file_size = ctypes.c_longlong()
                if not kernel32.GetFileSizeEx(duplicate, ctypes.byref(file_size)):
                    continue
                remaining = int(file_size.value)
                if remaining <= 0:
                    continue
                # The duplicated handle shares Chrome's file position, and the
                # file cannot be reopened while Chrome holds it. Map it instead.
                kernel32.CreateFileMappingW.argtypes = [
                    wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                    wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR,
                ]
                kernel32.CreateFileMappingW.restype = wintypes.HANDLE
                kernel32.MapViewOfFile.argtypes = [
                    wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t,
                ]
                kernel32.MapViewOfFile.restype = ctypes.c_void_p
                kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
                kernel32.UnmapViewOfFile.restype = wintypes.BOOL
                mapping = kernel32.CreateFileMappingW(duplicate, None, 0x02, 0, 0, None)
                if not mapping:
                    if debug is not None:
                        debug.update(stats)
                        debug["read_error"] = ctypes.get_last_error()
                    return False
                view = kernel32.MapViewOfFile(mapping, 0x04, 0, 0, 0)
                if not view:
                    kernel32.CloseHandle(mapping)
                    if debug is not None:
                        debug.update(stats)
                        debug["read_error"] = ctypes.get_last_error()
                    return False
                try:
                    with open(dest, "wb") as handle_out:
                        handle_out.write(ctypes.string_at(view, remaining))
                finally:
                    kernel32.UnmapViewOfFile(view)
                    kernel32.CloseHandle(mapping)
                if debug is not None:
                    debug.update(stats)
                return True
            finally:
                kernel32.CloseHandle(duplicate)
    finally:
        for process in opened.values():
            if process:
                kernel32.CloseHandle(process)
    if debug is not None:
        debug.update(stats)
    return False


def readable_browser_cookie_spec(spec, *, browser_dir=None, dest_root=None):
    """Cookie spec yt-dlp can read while that browser is still open.

    yt-dlp copies the live database with a normal file copy, which Windows
    refuses while Chrome holds it. A snapshot is a normal file, so the copy works.
    """
    browser, profile = _split_browser_spec(spec)
    if browser not in _PROFILE_BROWSERS and browser != "opera":
        return (spec or "").strip()
    if sys.platform != "win32" and browser_dir is None:
        return (spec or "").strip()
    if browser_dir is None:
        try:
            from yt_dlp.cookies import _get_chromium_based_browser_settings
            browser_dir = _get_chromium_based_browser_settings(browser)["browser_dir"]
        except Exception:
            return (spec or "").strip()
    if profile and any(sep in profile for sep in (os.sep, os.altsep) if sep):
        search_root = profile
    elif profile and browser in _PROFILE_BROWSERS:
        search_root = os.path.join(browser_dir, profile)
    else:
        search_root = browser_dir
    cookie_db = _newest_named(search_root, "Cookies")
    local_state = _newest_named(browser_dir, "Local State")
    if not cookie_db or not local_state:
        return (spec or "").strip()
    try:
        cookie_mtime = os.lstat(cookie_db).st_mtime
    except OSError:
        return (spec or "").strip()
    dest_root = dest_root or os.path.join(state_dir(), "browser-cookies", browser)
    profile_dir = _cookie_profile_dir(cookie_db)
    dest_profile = os.path.join(dest_root, os.path.basename(profile_dir) or "Default")
    dest_db = os.path.join(dest_profile, "Network", "Cookies")
    cache_key = (browser, profile, os.path.abspath(browser_dir), os.path.abspath(dest_root))
    with _snapshot_lock:
        cached = _snapshot_cache.get(cache_key)
        if cached and cached[0] == cookie_mtime and os.path.isfile(dest_db):
            return cached[1]
        try:
            os.makedirs(os.path.dirname(dest_db), exist_ok=True)
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.remove(dest_db + suffix)
                except OSError:
                    pass
            _snapshot_sqlite(cookie_db, dest_db, _BROWSER_IMAGES.get(browser, ""))
            shutil.copyfile(local_state, os.path.join(dest_root, "Local State"))
        except (OSError, sqlite3.Error):
            return (spec or "").strip()
        rewritten = f"{browser}:{dest_profile}"
        _snapshot_cache[cache_key] = (cookie_mtime, rewritten)
        return rewritten


def prepare_cookies_file(*, curl_text="", json_path="", profile_id=""):
    """Build the Netscape cookie file yt-dlp uses. JSON export wins over pasted text."""
    out = path = os.path.join(state_dir(), "extra-cookies.txt")
    json_path = (json_path or "").strip()
    if json_path:
        items = read_json_cookies(json_path, profile_id=profile_id)
        if items:
            return write_netscape_from_json(items, out)
    return write_netscape_cookies(curl_text, path=out)
