from __future__ import annotations

import re
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network

from fastapi import Request

from app.core.config import Settings

IPAddress = IPv4Address | IPv6Address
HEADER_NAME_PATTERN = re.compile(r"^[a-z0-9-]+$")


def _trusted_networks(value: str):
    configured = [item.strip() for item in value.split(",") if item.strip()]
    if not configured:
        return ()
    try:
        return tuple(ip_network(item, strict=False) for item in configured)
    except ValueError:
        return ()


def _configured_headers(value: str) -> tuple[str, ...]:
    headers = tuple(dict.fromkeys(item.strip().lower() for item in value.split(",") if item.strip()))
    if not headers or any(HEADER_NAME_PATTERN.fullmatch(item) is None for item in headers):
        return ()
    return headers


def _address(value: str) -> IPAddress | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return ip_address(normalized)
    except ValueError:
        return None


def _forwarded_address(value: str) -> IPAddress | None:
    normalized = value.strip().strip('"')
    if normalized.startswith("["):
        closing = normalized.find("]")
        if closing < 0 or (normalized[closing + 1 :] and not normalized[closing + 1 :].startswith(":")):
            return None
        return _address(normalized[1:closing])
    parsed = _address(normalized)
    if parsed is not None:
        return parsed
    if normalized.count(":") == 1:
        host, port = normalized.rsplit(":", 1)
        if port.isdigit():
            return _address(host)
    return None


def _parse_forwarded(value: str) -> list[IPAddress] | None:
    elements = [item.strip() for item in value.split(",")]
    if not elements or any(not item for item in elements):
        return None
    result: list[IPAddress] = []
    for element in elements:
        parameters = [item.strip() for item in element.split(";") if item.strip()]
        forwarded_for = [item.split("=", 1)[1] for item in parameters if item.lower().startswith("for=")]
        if len(forwarded_for) != 1:
            return None
        parsed = _forwarded_address(forwarded_for[0])
        if parsed is None:
            return None
        result.append(parsed)
    return result


def _parse_forwarded_chain(header_name: str, value: str) -> list[IPAddress] | None:
    if header_name == "forwarded":
        return _parse_forwarded(value)
    values = [item.strip() for item in value.split(",")]
    if not values or any(not item for item in values):
        return None
    result = [_address(item) for item in values]
    return None if any(item is None for item in result) else [item for item in result if item is not None]


def resolve_client_ip(request: Request, settings: Settings) -> str:
    peer = _address(request.client.host) if request.client is not None else None
    if peer is None:
        return "unknown"
    networks = _trusted_networks(settings.auth_trusted_proxy_networks)
    headers = _configured_headers(settings.auth_forwarded_ip_headers)
    if not networks or not headers or not any(peer in network for network in networks):
        return str(peer)

    for header_name in headers:
        value = request.headers.get(header_name)
        if value is None:
            continue
        chain = _parse_forwarded_chain(header_name, value)
        if not chain:
            return str(peer)
        resolved = peer
        for candidate in reversed(chain):
            if not any(resolved in network for network in networks):
                break
            resolved = candidate
        return str(resolved)
    return str(peer)
