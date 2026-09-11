#!/usr/bin/env python3
"""Exercise the backend half of the Tauri cross-site refresh-cookie spike.

This tool never prints credentials or cookie values.  It validates CORS preflight
for a real WebView Origin and, when credentials are supplied through environment
variables, validates the login -> refresh cookie contract against a live API.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DESKTOP_ORIGINS = ("http://tauri.localhost", "tauri://localhost")


def request(url: str, method: str, headers: dict[str, str], body: bytes | None = None) -> tuple[int, dict[str, str], bytes]:
    try:
        with urlopen(Request(url, data=body, method=method, headers=headers), timeout=15) as response:
            return response.status, dict(response.headers.items()), response.read()
    except HTTPError as error:
        return error.code, dict(error.headers.items()), error.read()
    except URLError as error:
        raise RuntimeError("network error: " + str(error.reason)) from error


def cookie_pair(set_cookie: str) -> str:
    return set_cookie.split(";", 1)[0]


def require_cookie_policy(set_cookie: str) -> list[str]:
    policy = set_cookie.lower()
    missing = []
    for attribute in ("httponly", "secure", "samesite=none"):
        if attribute not in policy:
            missing.append(attribute)
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Run S1 Tauri cross-site auth preflight")
    parser.add_argument("--api-url", required=True, help="HTTPS API origin, e.g. https://api.example.org")
    parser.add_argument("--origin", choices=DESKTOP_ORIGINS, required=True, help="WebView origin under test")
    args = parser.parse_args()
    api = args.api_url.rstrip("/")
    refresh_url = api + "/api/v1/auth/refresh"
    login_url = api + "/api/v1/auth/login"

    status, headers, _ = request(refresh_url, "OPTIONS", {
        "Origin": args.origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    failures = []
    if status not in (200, 204): failures.append("preflight returned HTTP " + str(status))
    if headers.get("Access-Control-Allow-Origin") != args.origin:
        failures.append("Access-Control-Allow-Origin does not exactly match desktop origin")
    if headers.get("Access-Control-Allow-Credentials", "").lower() != "true":
        failures.append("Access-Control-Allow-Credentials is not true")

    username = os.getenv("SOYMUTDB_SPIKE_USERNAME")
    password = os.getenv("SOYMUTDB_SPIKE_PASSWORD")
    if bool(username) != bool(password):
        failures.append("set both SOYMUTDB_SPIKE_USERNAME and SOYMUTDB_SPIKE_PASSWORD, or neither")
    if username and password:
        payload = json.dumps({"username": username, "password": password}).encode()
        status, headers, _ = request(login_url, "POST", {"Origin": args.origin, "Content-Type": "application/json"}, payload)
        set_cookie = headers.get("Set-Cookie", "")
        if status != 200: failures.append("login returned HTTP " + str(status))
        missing = require_cookie_policy(set_cookie)
        if missing: failures.append("login refresh cookie missing: " + ", ".join(missing))
        if set_cookie and not missing:
            status, headers, _ = request(refresh_url, "POST", {"Origin": args.origin, "Cookie": cookie_pair(set_cookie)})
            if status != 200: failures.append("refresh with login cookie returned HTTP " + str(status))
            missing = require_cookie_policy(headers.get("Set-Cookie", ""))
            if missing: failures.append("rotated refresh cookie missing: " + ", ".join(missing))
    else:
        print("CORS preflight checked; login/refresh flow skipped (no SPIKE credentials).")

    if failures:
        for failure in failures: print("FAIL: " + failure, file=sys.stderr)
        return 1
    print("PASS: backend CORS and refresh-cookie contract supports " + args.origin)
    if not username:
        print("INCOMPLETE: run again with ephemeral test credentials before a backend go decision.")
    print("NOTE: this does not prove macOS WKWebView emits tauri:// Origin; packaged-app evidence is still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())