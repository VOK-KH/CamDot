"""Speedtest.net line-speed helper (no network)."""
import json
import unittest

from app.core.speedtest import (
    CONFIG_URL,
    SERVERS_URL,
    format_line,
    https_base,
    nearest_servers,
    parse_client,
    parse_servers,
    run_speedtest,
)

CONFIG = (
    '<?xml version="1.0"?><settings>'
    '<client ip="1.2.3.4" lat="11.55" lon="104.91" isp="Example ISP" country="KH" />'
    "</settings>"
)
SERVERS = [
    {
        "url": "http://far.example:8080/speedtest/upload.php",
        "distance": 900,
        "name": "Far",
        "country": "ZZ",
        "sponsor": "FarNet",
    },
    {
        "url": "http://near.example:8080/speedtest/upload.php",
        "distance": 1,
        "name": "Phnom Penh",
        "country": "Cambodia",
        "sponsor": "NearNet",
    },
]


class _Response:
    def __init__(self, payload):
        self._payload = payload
        self._pos = 0

    def read(self, size=-1):
        if size is None or size < 0:
            size = len(self._payload) - self._pos
        chunk = self._payload[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Opener:
    def __init__(self, pages, fail=()):
        self.pages = pages
        self.fail = fail
        self.urls = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.urls.append(url)
        for prefix in self.fail:
            if url.startswith(prefix):
                raise OSError("down")
        for prefix, payload in self.pages:
            if url.startswith(prefix):
                return _Response(payload)
        raise OSError(f"unexpected {url}")


class Speedtest(unittest.TestCase):
    def test_parse_client_and_https_base(self):
        client = parse_client(CONFIG)
        self.assertEqual(client["isp"], "Example ISP")
        self.assertEqual(client["lat"], "11.55")
        servers = parse_servers(json.dumps(SERVERS))
        nearest = nearest_servers(servers, limit=1)[0]
        self.assertEqual(nearest["sponsor"], "NearNet")
        self.assertEqual(https_base(nearest), "https://near.example:8080/speedtest")

    def test_run_uses_speedtest_origin_and_nearest_server(self):
        opener = _Opener([
            (CONFIG_URL, CONFIG.encode()),
            (SERVERS_URL, json.dumps(SERVERS).encode()),
            ("https://near.example:8080/speedtest/", b"x" * 200000),
        ])
        result = run_speedtest(opener=opener, seconds=0.05)
        self.assertTrue(any(url.startswith(CONFIG_URL) for url in opener.urls))
        self.assertTrue(any(url.startswith(SERVERS_URL) for url in opener.urls))
        self.assertTrue(any("near.example" in url for url in opener.urls))
        self.assertFalse(any("far.example" in url for url in opener.urls))
        self.assertGreater(result["download_bps"], 0)
        self.assertEqual(result["server"], "NearNet")
        self.assertEqual(result["isp"], "Example ISP")
        self.assertIn("Mbps", format_line(result))
        self.assertIn("ms", format_line(result))

    def test_skips_a_server_that_does_not_answer(self):
        opener = _Opener(
            [
                (CONFIG_URL, CONFIG.encode()),
                (SERVERS_URL, json.dumps(SERVERS).encode()),
                ("https://far.example:8080/speedtest/", b"y" * 100000),
            ],
            fail=("https://near.example:8080/speedtest/",),
        )
        result = run_speedtest(opener=opener, seconds=0.05)
        self.assertEqual(result["server"], "FarNet")
