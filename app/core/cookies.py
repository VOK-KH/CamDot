"""Parse a cookie header, cURL command, or JSON export for yt-dlp --cookies."""
import json
import os
import re
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


def prepare_cookies_file(*, curl_text="", json_path="", profile_id=""):
    """Build the Netscape cookie file yt-dlp uses. JSON export wins over pasted text."""
    out = path = os.path.join(state_dir(), "extra-cookies.txt")
    json_path = (json_path or "").strip()
    if json_path:
        items = read_json_cookies(json_path, profile_id=profile_id)
        if items:
            return write_netscape_from_json(items, out)
    return write_netscape_cookies(curl_text, path=out)
