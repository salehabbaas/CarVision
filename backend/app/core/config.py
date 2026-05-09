import os
import sys
import logging
from pathlib import Path

logger = logging.getLogger("carvision.config")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MEDIA_DIR = os.getenv("MEDIA_DIR", str(PROJECT_ROOT / "datasets" / "media"))

# ── JWT ──────────────────────────────────────────────────────────────────────
_DEFAULT_JWT_SECRET = "carvision-dev-secret"
API_JWT_SECRET = os.getenv("JWT_SECRET", _DEFAULT_JWT_SECRET)
API_JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
API_JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))

# ── Public URLs ───────────────────────────────────────────────────────────────
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip()
FRONTEND_PUBLIC_BASE_URL = os.getenv("FRONTEND_PUBLIC_BASE_URL", "").strip()
FRONTEND_PUBLIC_SCHEME = os.getenv("FRONTEND_PUBLIC_SCHEME", "http").strip().lower() or "http"
FRONTEND_PUBLIC_PORT = os.getenv("FRONTEND_PUBLIC_PORT", "8081").strip()
API_CORS_ORIGINS = [o.strip() for o in os.getenv("API_CORS_ORIGINS", "*").split(",") if o.strip()]

# ── Security warnings on startup ─────────────────────────────────────────────
def _warn_insecure_defaults() -> None:
    """Refuse to start when default JWT secrets are in use unless
    CARVISION_STRICT_SECRETS=0 is explicitly set (dev/test override only)."""
    strict = os.getenv("CARVISION_STRICT_SECRETS", "1").strip().lower() not in {"0", "false", "no"}
    issues = []

    if API_JWT_SECRET == _DEFAULT_JWT_SECRET:
        issues.append(
            "JWT_SECRET is using the insecure default 'carvision-dev-secret'. "
            "Set JWT_SECRET to a long random string in your .env file."
        )

    for issue in issues:
        if strict:
            logger.critical("SECURITY: %s", issue)
        else:
            logger.warning("SECURITY WARNING: %s", issue)

    if strict and issues:
        sys.exit(
            "\n[CarVision] Refusing to start: insecure defaults detected "
            "(CARVISION_STRICT_SECRETS=1). Fix the issues above.\n"
        )


_warn_insecure_defaults()
