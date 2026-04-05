import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LEGACY_FRONTEND_DIR = Path(
    os.getenv("LEGACY_FRONTEND_DIR", str(PROJECT_ROOT / "old" / "python_frontend"))
)
MEDIA_DIR = os.getenv("MEDIA_DIR", str(PROJECT_ROOT / "datasets" / "media"))

API_JWT_SECRET = os.getenv("JWT_SECRET", "carvision-dev-secret")
API_JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
API_JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))
API_ADMIN_USER = os.getenv("API_ADMIN_USER", os.getenv("ADMIN_USER", "admin"))
API_ADMIN_PASS = os.getenv("API_ADMIN_PASS", os.getenv("ADMIN_PASS", "admin"))
API_CORS_ORIGINS = [o.strip() for o in os.getenv("API_CORS_ORIGINS", "*").split(",") if o.strip()]

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip()
