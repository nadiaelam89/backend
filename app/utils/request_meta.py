from __future__ import annotations

from fastapi import Request


def get_client_ip(request: Request) -> str | None:
    cloudflare_ip = request.headers.get("CF-Connecting-IP")
    if cloudflare_ip:
        return cloudflare_ip.strip()

    true_client_ip = request.headers.get("True-Client-IP")
    if true_client_ip:
        return true_client_ip.strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def get_client_country(request: Request) -> str | None:
    cloudflare_country = request.headers.get("CF-IPCountry")
    if cloudflare_country and cloudflare_country not in {"XX", "T1"}:
        return cloudflare_country.strip().upper()
    return None
