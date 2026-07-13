"""Purge all orders/events on the configured API (reads ADMIN_* from .env)."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API_URL = os.getenv("API_PUBLIC_URL", "http://localhost:8001").rstrip("/")
USERNAME = os.getenv("ADMIN_USERNAME", "")
PASSWORD = os.getenv("ADMIN_PASSWORD", "")

if not USERNAME or not PASSWORD:
    print("Missing ADMIN_USERNAME or ADMIN_PASSWORD in backend/.env", file=sys.stderr)
    sys.exit(1)


def post(path: str, payload: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{API_URL}{path}",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode())


def main() -> None:
    print(f"API: {API_URL}")
    login = post("/api/admin/login", {"username": USERNAME, "password": PASSWORD})
    token = login["access_token"]
    print("Logged in.")

    try:
        result = post("/api/admin/purge-data", {}, token)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        print(f"Purge failed ({exc.code}): {body}", file=sys.stderr)
        if exc.code == 404:
            print("Deploy the latest backend first (purge endpoint missing).", file=sys.stderr)
        sys.exit(1)

    print("Purged:", result.get("deleted", result))


if __name__ == "__main__":
    main()
