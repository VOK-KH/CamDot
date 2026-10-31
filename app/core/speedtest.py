"""Download-speed sample from Speedtest by Ookla.

The server list comes from https://www.speedtest.net:443. Throughput is then
measured against the nearest HTTPS server that list returns.
"""
import json
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

SPEEDTEST_ORIGIN = "https://www.speedtest.net:443"
CONFIG_URL = SPEEDTEST_ORIGIN + "/speedtest-config.php"
SERVERS_URL = (
    SPEEDTEST_ORIGIN
    + "/api/js/servers?engine=js&https_functional=true&limit=5"
)
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
_CLIENT_RE = re.compile(r"<client\b([^>]*)/?>", re.IGNORECASE)
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


def _headers():
    return {
        "User-Agent": _UA,
        "Accept": "*/*",
        "Referer": "https://www.speedtest.net/",
        "Cache-Control": "no-cache",
    }


def _open(url, opener, timeout):
    request = urllib.request.Request(url, headers=_headers())
    open_fn = opener or urllib.request.urlopen
    return open_fn(request, timeout=timeout)


def _read_text(url, opener, timeout):
    with _open(url, opener, timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_client(xml):
    """ISP and coordinates from speedtest-config.php."""
    match = _CLIENT_RE.search(xml or "")
    if not match:
        return {}
    return dict(_ATTR_RE.findall(match.group(1)))


def parse_servers(payload):
    data = json.loads(payload or "[]")
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and item.get("url")]


def https_base(server):
    """HTTPS folder that holds latency.txt and the random download images."""
    raw = str(server.get("url") or "").replace("\\/", "/")
    parts = urlparse(raw)
    if not parts.hostname:
        raise ValueError("Speedtest server has no URL")
    path = parts.path.rsplit("/", 1)[0] or "/speedtest"
    netloc = parts.hostname
    if parts.port:
        netloc = f"{parts.hostname}:{parts.port}"
    return f"https://{netloc}{path}"


def _server_distance(server):
    try:
        return float(server.get("distance"))
    except (TypeError, ValueError):
        return 1e9


def nearest_servers(servers, limit=3):
    return sorted(servers, key=_server_distance)[:limit]


def measure_ping(base, opener=None, timeout=8, samples=3):
    """Lowest latency.txt round trip, in milliseconds."""
    times = []
    for index in range(samples):
        started = time.perf_counter()
        with _open(f"{base}/latency.txt?x={index}", opener, timeout) as response:
            response.read()
        times.append((time.perf_counter() - started) * 1000.0)
    return min(times) if times else None


def measure_download(base, opener=None, timeout=20, seconds=4.0):
    """Bytes per second while pulling random images, up to `seconds`."""
    total = 0
    started = time.perf_counter()
    nonce = 0
    while time.perf_counter() - started < seconds:
        nonce += 1
        url = f"{base}/random4000x4000.jpg?x={nonce}"
        with _open(url, opener, timeout) as response:
            while time.perf_counter() - started < seconds:
                chunk = response.read(65536)
                if not chunk:
                    break
                total += len(chunk)
    elapsed = max(time.perf_counter() - started, 0.001)
    return total / elapsed


def format_line(result):
    """Status-bar text: ``142 Mbps · 18 ms``."""
    mbps = float(result.get("download_bps") or 0) * 8 / 1_000_000
    text = f"{mbps:.0f} Mbps" if mbps >= 10 else f"{mbps:.1f} Mbps"
    ping = result.get("ping_ms")
    if ping is not None:
        text += f" · {ping:.0f} ms"
    return text


def run_speedtest(opener=None, timeout=20, seconds=4.0):
    """Return download throughput from the nearest Speedtest.net server."""
    client = parse_client(_read_text(CONFIG_URL, opener, timeout))
    servers = nearest_servers(parse_servers(_read_text(SERVERS_URL, opener, timeout)))
    if not servers:
        raise ValueError("Speedtest.net returned no servers")
    errors = []
    for server in servers:
        base = https_base(server)
        try:
            ping = measure_ping(base, opener=opener, timeout=min(timeout, 8))
            bps = measure_download(base, opener=opener, timeout=timeout, seconds=seconds)
        except (OSError, urllib.error.URLError, ValueError) as exc:
            errors.append(str(exc).strip() or exc.__class__.__name__)
            continue
        if bps <= 0:
            errors.append("empty download")
            continue
        return {
            "download_bps": bps,
            "ping_ms": ping,
            "server": server.get("sponsor") or server.get("name") or "",
            "name": server.get("name") or "",
            "country": server.get("country") or "",
            "isp": client.get("isp") or "",
            "host": urlparse(base).netloc,
        }
    detail = errors[-1] if errors else "no server answered"
    raise ValueError(f"Speed test failed ({detail})")
