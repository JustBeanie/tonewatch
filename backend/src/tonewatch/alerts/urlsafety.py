"""URL validation and DNS-pinned HTTP transport for outbound integrations."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

BLOCKED_V4 = ipaddress.ip_network("0.0.0.0/8")
ALLOWED_WEBHOOK_SCHEMES = frozenset({"https"})
ALLOWED_STREAM_SCHEMES = frozenset({"http", "https", "rtsp", "rtsps"})


class UnsafeURL(ValueError):
    """Raised when a URL is not safe for an outbound request."""


@dataclass(frozen=True)
class ResolvedURL:
    """A validated URL with the one address selected for its connection."""

    original: httpx.URL
    address: ipaddress.IPv4Address | ipaddress.IPv6Address

    @property
    def host(self) -> str:
        """Return the original DNS name or literal host."""
        return (
            self.original.host.decode()
            if isinstance(self.original.host, bytes)
            else self.original.host
        )


def _legacy_ipv4(value: str) -> ipaddress.IPv4Address | None:
    """Parse the decimal, octal, and hexadecimal forms accepted by inet_aton."""
    parts = value.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    try:
        numbers: list[int] = []
        for part in parts:
            if not part:
                return None
            if part.lower().startswith("0x"):
                number = int(part[2:], 16)
            elif len(part) > 1 and part.startswith("0"):
                number = int(part[1:], 8)
            else:
                number = int(part, 10)
            if number < 0:
                return None
            numbers.append(number)
        limits = {
            1: (0xFFFFFFFF,),
            2: (0xFF, 0xFFFFFF),
            3: (0xFF, 0xFF, 0xFFFF),
            4: (0xFF,) * 4,
        }
        if any(number > limit for number, limit in zip(numbers, limits[len(parts)], strict=True)):
            return None
        if len(parts) == 1:
            packed = numbers[0]
        elif len(parts) == 2:
            packed = (numbers[0] << 24) | numbers[1]
        elif len(parts) == 3:
            packed = (numbers[0] << 24) | (numbers[1] << 16) | numbers[2]
        else:
            packed = (numbers[0] << 24) | (numbers[1] << 16) | (numbers[2] << 8) | numbers[3]
        return ipaddress.IPv4Address(packed)
    except (ValueError, ipaddress.AddressValueError):
        return None


def parse_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse ordinary and legacy numeric IP spellings without DNS."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return _legacy_ipv4(host)


def validate_stream_url(value: str | httpx.URL, *, allow_private: bool = True) -> httpx.URL:
    """Validate a stream origin before handing it to FFmpeg."""
    return validate_url(value, schemes=ALLOWED_STREAM_SCHEMES, allow_private=allow_private)


def is_blocked_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    *,
    block_private: bool = False,
) -> bool:
    """Return whether an address must not be used as an outbound origin."""
    mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    candidates = [address] + ([mapped] if mapped is not None else [])
    for item in candidates:
        if item is None:
            continue
        if (
            item.is_loopback
            or item.is_link_local
            or item.is_unspecified
            or item.is_multicast
            or (isinstance(item, ipaddress.IPv4Address) and item in BLOCKED_V4)
            or (block_private and item.is_private)
        ):
            return True
    return False


def validate_url(
    value: str | httpx.URL,
    *,
    schemes: frozenset[str] = ALLOWED_WEBHOOK_SCHEMES,
    allow_private: bool = True,
) -> httpx.URL:
    """Validate URL syntax, scheme, and literal-host safety before DNS."""
    url = httpx.URL(value)
    if url.scheme not in schemes or not url.host:
        raise UnsafeURL("unsupported or incomplete URL")
    literal = parse_ip(url.host)
    if literal is not None and is_blocked_address(literal, block_private=not allow_private):
        raise UnsafeURL("destination address is blocked")
    return url


async def resolve_and_validate(
    value: str | httpx.URL,
    *,
    schemes: frozenset[str] = ALLOWED_WEBHOOK_SCHEMES,
    allow_private: bool = True,
    resolver: Callable[..., Any] | None = None,
) -> ResolvedURL:
    """Resolve a hostname once and validate every returned candidate."""
    url = validate_url(value, schemes=schemes, allow_private=allow_private)
    literal = parse_ip(url.host)
    if literal is not None:
        return ResolvedURL(url, literal)
    lookup: Callable[..., Any] = resolver or socket.getaddrinfo
    result: list[tuple[Any, ...]] = await asyncio.to_thread(
        lookup,
        url.host,
        url.port,
        type=socket.SOCK_STREAM,
    )
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for family, _socktype, _proto, _canonname, sockaddr in result:
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except (ValueError, IndexError):
            continue
        if family in (socket.AF_INET, socket.AF_INET6):
            addresses.append(address)
    if not addresses:
        raise UnsafeURL("hostname did not resolve")
    for address in addresses:
        if not is_blocked_address(address, block_private=not allow_private):
            return ResolvedURL(url, address)
    raise UnsafeURL("all resolved destination addresses are blocked")


class PinnedIPTransport(httpx.AsyncBaseTransport):
    """Rewrite one request to its resolved IP while preserving Host and TLS SNI."""

    def __init__(
        self, resolved: ResolvedURL, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.resolved = resolved
        self.transport = transport or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Send the request to the validated address exactly once."""
        host = self.resolved.host
        port = self.resolved.original.port
        host_header = f"[{host}]" if ":" in host else host
        if port is not None and port not in (80, 443):
            host_header = f"{host_header}:{port}"
        request.url = request.url.copy_with(host=str(self.resolved.address))
        request.headers["Host"] = host_header
        request.extensions["sni_hostname"] = host
        return await self.transport.handle_async_request(request)

    async def aclose(self) -> None:
        """Close the wrapped transport."""
        await self.transport.aclose()
