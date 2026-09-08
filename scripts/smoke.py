#!/usr/bin/env python
"""Post-deploy smoke test for butterfly.buckstoplabs.com.

Every check here is a failure this deployment actually had. A blank Streamlit
page has several unrelated causes that all look identical in a browser, so each
one gets its own assertion rather than a single "is it up".

    python scripts/smoke.py
    python scripts/smoke.py --url https://butterfly.buckstoplabs.com

Exits non-zero on the first failure, so it can gate a deploy.
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import socket
import ssl
import sys
import urllib.parse

import requests

SITE = "https://butterfly.buckstoplabs.com"
ORIGIN = "https://butterfly-23242k5uhq-uc.a.run.app"
TIMEOUT = 30

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"


class CheckFailed(Exception):
    pass


def check_shell(url: str) -> str:
    """The root path serves Streamlit's HTML shell."""
    r = requests.get(url, timeout=TIMEOUT)
    if r.status_code != 200:
        raise CheckFailed(f"expected 200, got {r.status_code}")
    if "<title>Streamlit</title>" not in r.text:
        raise CheckFailed("response is not the Streamlit shell")
    return f"{len(r.content)} bytes"


def check_health(url: str) -> str:
    """Streamlit's own health endpoint answers.

    This is the check that catches a Worker route missing its /* wildcard:
    the root proxies fine while every other path falls through to Google and
    404s, which renders as a blank page.
    """
    r = requests.get(f"{url}/_stcore/health", timeout=TIMEOUT)
    if r.status_code != 200:
        raise CheckFailed(f"expected 200, got {r.status_code} "
                          f"(Worker route may be missing /*)")
    if r.text.strip() != "ok":
        raise CheckFailed(f"expected 'ok', got {r.text[:40]!r}")
    return "ok"


def check_bundle(url: str) -> str:
    """The JavaScript the shell asks for is served as JavaScript."""
    shell = requests.get(url, timeout=TIMEOUT).text
    match = re.search(r'/static/js/index\.[A-Za-z0-9_-]+\.js', shell)
    if not match:
        raise CheckFailed("no main bundle referenced in the shell")
    r = requests.get(urllib.parse.urljoin(url, match.group(0)), timeout=TIMEOUT)
    if r.status_code != 200:
        raise CheckFailed(f"{match.group(0)} returned {r.status_code}")
    if "javascript" not in r.headers.get("content-type", ""):
        raise CheckFailed(f"served as {r.headers.get('content-type')!r}, not javascript")
    return f"{len(r.content) // 1024} KB"


def check_websocket(url: str) -> str:
    """The websocket upgrades.

    Streamlit renders nothing without it. It 403s when the Origin the browser
    sends does not match the Host the Worker rewrote, which is why the server
    runs with enableCORS off.
    """
    host = urllib.parse.urlparse(url).hostname
    key = base64.b64encode(os.urandom(16)).decode()
    context = ssl.create_default_context()
    with context.wrap_socket(socket.create_connection((host, 443), timeout=TIMEOUT),
                             server_hostname=host) as sock:
        sock.sendall(
            f"GET /_stcore/stream HTTP/1.1\r\nHost: {host}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
            f"Origin: {url}\r\n\r\n".encode())
        status = sock.recv(200).decode(errors="replace").split("\r\n")[0]
    if "101" not in status:
        raise CheckFailed(f"{status} (CORS/XSRF checks may be back on)")
    return "101 Switching Protocols"


def check_origin_closed(_: str) -> str:
    """The shared secret the origin gate depends on is configured.

    Cloud Run has to accept unauthenticated callers for Cloudflare to reach it,
    so this key is the only thing keeping the run.app URL from serving the
    whole dataset to anyone who finds it.

    It has to be checked through the service config rather than over HTTP:
    Streamlit serves its HTML shell before any Python runs, so an ungated
    fetch of the origin returns the same shell either way. The gate fires when
    the script executes, on websocket connect.
    """
    import shutil
    import subprocess

    if not shutil.which("gcloud"):
        raise CheckFailed("gcloud not on PATH; cannot read the service config")
    out = subprocess.run(
        ["gcloud", "run", "services", "describe", "butterfly",
         "--project=butterfly-buckstoplabs", "--region=us-central1",
         "--format=value(spec.template.spec.containers[0].env)"],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise CheckFailed(out.stderr.strip().splitlines()[-1][:120])
    if "BUTTERFLY_KEY" not in out.stdout:
        raise CheckFailed("BUTTERFLY_KEY is not set on the service")
    return "BUTTERFLY_KEY set on the serving revision"


CHECKS = [
    ("app shell", check_shell, "site"),
    ("health endpoint", check_health, "site"),
    ("javascript bundle", check_bundle, "site"),
    ("websocket upgrade", check_websocket, "site"),
    ("origin secret set", check_origin_closed, "origin"),
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=SITE, help="public site URL")
    ap.add_argument("--origin", default=ORIGIN, help="Cloud Run URL, which should refuse")
    ap.add_argument("--skip-origin", action="store_true",
                    help="skip the origin check (it needs BUTTERFLY_KEY deployed)")
    args = ap.parse_args(argv)

    failures = 0
    for name, check, target in CHECKS:
        if target == "origin" and args.skip_origin:
            continue
        try:
            detail = check(args.url if target == "site" else args.origin)
            print(f"  {PASS}  {name:22} {detail}")
        except Exception as exc:
            failures += 1
            print(f"  {FAIL}  {name:22} {exc}")

    print()
    if failures:
        print(f"{failures} check(s) failed", file=sys.stderr)
        return 1
    print(f"all {len(CHECKS)} checks passed against {args.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
