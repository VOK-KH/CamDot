"""Parse a cookie header or copied cURL command for yt-dlp --cookies."""
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


def write_netscape_cookies(raw, path=None):
    """Write a Netscape cookie file. Returns the path, or '' when there is nothing to write."""
    header = cookies_from_curl(raw)
    if not header or "=" not in header:
        return ""
    domains = cookie_domains_from_curl(raw)
    path = path or os.path.join(state_dir(), "extra-cookies.txt")
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
