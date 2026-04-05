from typing import Optional, Tuple
from urllib.parse import urlparse


def _get_wsdl_dir():
    try:
        import onvif
    except Exception:
        return None
    return onvif.__path__[0] + "/wsdl"


def _create_ptz(camera):
    if not camera.onvif_xaddr:
        return None, None
    try:
        from onvif import ONVIFCamera
    except Exception:
        return None, None

    parsed = urlparse(camera.onvif_xaddr)
    host = parsed.hostname
    port = parsed.port or 80
    if not host:
        return None, None

    wsdl_dir = _get_wsdl_dir()
    try:
        cam = ONVIFCamera(host, port, camera.onvif_username or "", camera.onvif_password or "", wsdl_dir=wsdl_dir)
        media = cam.create_media_service()
        profiles = media.GetProfiles()
        if not profiles:
            return None, None
        profile_token = profiles[0].token
        ptz = cam.create_ptz_service()
        return ptz, profile_token
    except Exception:
        return None, None


def continuous_move(camera, pan: float = 0.0, tilt: float = 0.0, zoom: float = 0.0) -> Tuple[bool, Optional[str]]:
    ptz, profile_token = _create_ptz(camera)
    if not ptz or not profile_token:
        return False, "PTZ not available"

    try:
        request = ptz.create_type("ContinuousMove")
        request.ProfileToken = profile_token
        request.Velocity = {
            "PanTilt": {"x": pan, "y": tilt},
            "Zoom": {"x": zoom},
        }
        ptz.ContinuousMove(request)
        return True, None
    except Exception as exc:
        return False, str(exc)


def stop(camera) -> Tuple[bool, Optional[str]]:
    ptz, profile_token = _create_ptz(camera)
    if not ptz or not profile_token:
        return False, "PTZ not available"
    try:
        request = ptz.create_type("Stop")
        request.ProfileToken = profile_token
        request.PanTilt = True
        request.Zoom = True
        ptz.Stop(request)
        return True, None
    except Exception as exc:
        return False, str(exc)
