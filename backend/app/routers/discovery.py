"""routers/discovery.py — ONVIF camera discovery and stream resolution."""
from __future__ import annotations

import ipaddress
import socket
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from fastapi import APIRouter, Depends

from api.schemas import ApiDiscoveryResolveBody
from routers.deps import get_current_user

router = APIRouter(prefix="/api/v1/discovery", tags=["discovery"])


# ── Internal helpers ──────────────────────────────────────────────────────────

def _parse_discovery_subnets(raw_value: Optional[str]) -> Tuple[List, List[str]]:
    if not raw_value:
        return [], []
    networks: List = []
    invalid: List[str] = []
    for token in str(raw_value).split(","):
        item = token.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except Exception:
            invalid.append(item)
    return networks, invalid


def _xaddr_host_port(xaddr: str) -> Tuple[Optional[str], Optional[int]]:
    try:
        parsed = urlparse(str(xaddr))
    except Exception:
        return None, None
    host = parsed.hostname
    if not host:
        return None, None
    if parsed.port:
        return host, int(parsed.port)
    return host, 443 if parsed.scheme == "https" else 80


def _host_in_subnets(host: str, subnets: List) -> bool:
    if not subnets:
        return True
    try:
        ip_value = ipaddress.ip_address(host)
    except Exception:
        return False
    return any(ip_value in net for net in subnets)


def _probe_tcp_port(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((host, int(port))) == 0
    except Exception:
        return False


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/run")
def run_discovery(
    timeout: int = 3,
    subnets: Optional[str] = None,
    probe_ports: bool = False,
    _user: str = Depends(get_current_user),
):
    from onvif_discovery import discover_onvif

    timeout = max(1, min(int(timeout), 15))
    result = discover_onvif(timeout=timeout, resolve_rtsp=False) or {"error": None, "devices": []}
    raw_devices = result.get("devices") or []
    subnet_filters, invalid_subnets = _parse_discovery_subnets(subnets)

    devices = []
    for device in raw_devices:
        xaddrs = device.get("xaddrs") or []
        host = None
        xaddr_ports = set()
        for xaddr in xaddrs:
            parsed_host, parsed_port = _xaddr_host_port(xaddr)
            if not host and parsed_host:
                host = parsed_host
            if parsed_port:
                xaddr_ports.add(int(parsed_port))

        if subnet_filters and (not host or not _host_in_subnets(host, subnet_filters)):
            continue

        enriched = dict(device)
        enriched["host"] = host
        enriched["xaddr_ports"] = sorted(xaddr_ports)

        if probe_ports and host:
            probe_targets = {80, 443, 554}
            probe_targets.update(xaddr_ports)
            enriched["port_probe"] = {
                str(port): _probe_tcp_port(host, port)
                for port in sorted(probe_targets)
            }
        else:
            enriched["port_probe"] = {}
        devices.append(enriched)

    return {
        "error": result.get("error"),
        "devices": devices,
        "total_found": len(raw_devices),
        "total_after_filter": len(devices),
        "filters": {
            "subnets": [str(item) for item in subnet_filters],
            "invalid_subnets": invalid_subnets,
            "probe_ports": bool(probe_ports),
        },
    }


@router.post("/resolve")
def resolve_discovery(
    body: ApiDiscoveryResolveBody,
    _user: str = Depends(get_current_user),
):
    from onvif_discovery import resolve_rtsp_for_xaddr

    profiles = resolve_rtsp_for_xaddr(body.xaddr, body.username, body.password)
    return {"xaddr": body.xaddr, "rtsp_profiles": profiles}
