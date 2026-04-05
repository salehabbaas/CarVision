import hashlib
import re
from pathlib import Path
from typing import Optional


def safe_filename(name: str) -> str:
    if not name:
        return "upload.jpg"
    name = name.strip().replace(" ", "_")
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    return name[:120] or "upload.jpg"


def hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def hash_file(path: Path) -> Optional[str]:
    try:
        return hash_bytes(path.read_bytes())
    except Exception:
        return None
