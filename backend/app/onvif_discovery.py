import os
from typing import List, Dict, Optional
from urllib.parse import urlparse


def _parse_scope(scopes: List[str], prefix: str) -> Optional[str]:
    for scope in scopes:
        if scope.startswith(prefix):
            return scope.replace(prefix, "", 1)
    return None


def _format_uri_with_credentials(uri: str, username: str, password: str) -> str:
    if not username or not password:
        return uri
    parsed = urlparse(uri)
    if parsed.username or parsed.password:
        return uri
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    netloc = f"{username}:{password}@{netloc}"
    return parsed._replace(netloc=netloc).geturl()


def _get_wsdl_dir():
    try:
        import onvif
    except Exception:
        return None
    return os.path.join(os.path.dirname(onvif.__file__), "wsdl")


def _get_rtsp_profiles(xaddr: str, username: str, password: str) -> List[Dict]:
    try:
        from onvif import ONVIFCamera
    except Exception:
        return []

    parsed = urlparse(xaddr)
    host = parsed.hostname
    port = parsed.port or 80
    if not host:
        return []

    wsdl_dir = _get_wsdl_dir()
    try:
        cam = ONVIFCamera(host, port, username, password, wsdl_dir=wsdl_dir)
        media = cam.create_media_service()
        profiles = media.GetProfiles()
    except Exception:
        return []

    profiles_out: List[Dict] = []
    for profile in profiles:
        try:
            name = getattr(profile, "Name", None) or "Profile"
            resolution = None
            try:
                enc = profile.VideoEncoderConfiguration
                if enc and enc.Resolution:
                    resolution = f"{enc.Resolution.Width}x{enc.Resolution.Height}"
            except Exception:
                resolution = None

            stream = media.GetStreamUri(
                {
                    "StreamSetup": {
                        "Stream": "RTP-Unicast",
                        "Transport": {"Protocol": "RTSP"},
                    },
                    "ProfileToken": profile.token,
                }
            )
            if stream and getattr(stream, "Uri", None):
                uri = _format_uri_with_credentials(stream.Uri, username, password)
                profiles_out.append(
                    {
                        "uri": uri,
                        "token": getattr(profile, "token", None),
                        "name": name,
                        "resolution": resolution,
                    }
                )
        except Exception:
            continue
    return profiles_out


def resolve_rtsp_for_xaddr(xaddr: str, username: str, password: str) -> List[Dict]:
    if not xaddr:
        return []
    return _get_rtsp_profiles(xaddr, username, password)


def discover_onvif(timeout: int = 3, resolve_rtsp: bool = False, username: str = "", password: str = "") -> Dict:
    try:
        from wsdiscovery.discovery import ThreadedWSDiscovery as WSDiscovery
        try:
            from wsdiscovery import QName
        except Exception:
            from wsdiscovery.qname import QName
    except Exception as exc:
        return {
            "error": f"wsdiscovery unavailable: {exc}",
            "devices": [],
        }

    devices = []
    wsd = WSDiscovery()
    try:
        wsd.start()
    except Exception as exc:
        return {"error": f"Discovery start failed: {exc}", "devices": []}
    try:
        services = []
        try:
            services = wsd.searchServices(
                types=[QName("http://www.onvif.org/ver10/network/wsdl", "NetworkVideoTransmitter")],
                timeout=timeout,
            )
        except Exception:
            services = []

        if not services:
            try:
                services = wsd.searchServices(
                    types=[QName("http://www.onvif.org/ver10/device/wsdl", "Device")],
                    timeout=timeout,
                )
            except Exception:
                services = []

        if not services:
            try:
                services = wsd.searchServices(timeout=timeout)
            except Exception:
                services = []

        for service in services:
            xaddrs = service.getXAddrs() or []
            scopes = service.getScopes() or []
            if isinstance(scopes, (list, tuple, set)):
                scopes_list = [str(scope) for scope in scopes]
            else:
                scopes_list = [str(scopes)] if scopes else []

            name = _parse_scope(scopes_list, "onvif://www.onvif.org/name/")
            location = _parse_scope(scopes_list, "onvif://www.onvif.org/location/")

            rtsp_profiles: List[Dict] = []
            if resolve_rtsp and username and password:
                for xaddr in xaddrs:
                    rtsp_profiles.extend(_get_rtsp_profiles(xaddr, username, password))

            devices.append(
                {
                    "xaddrs": xaddrs,
                    "scopes": scopes_list,
                    "name": name,
                    "location": location,
                    "rtsp_profiles": rtsp_profiles,
                }
            )
    finally:
        try:
            wsd.stop()
        except Exception:
            pass

    return {"error": None, "devices": devices}
