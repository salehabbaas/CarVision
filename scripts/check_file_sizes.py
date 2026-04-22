#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RULES = [
    (ROOT / "backend" / "app", "*.py", 350),
    (ROOT / "frontend" / "web" / "src", "*.ts", 260),
    (ROOT / "frontend" / "web" / "src", "*.tsx", 260),
    (ROOT / "frontend" / "web" / "src", "*.js", 260),
    (ROOT / "frontend" / "web" / "src", "*.jsx", 260),
]

# Transitional allowlist for modules still being split.
ALLOWLIST = {
    ROOT / "backend" / "app" / "main.py": 800,
    ROOT / "backend" / "app" / "camera_manager.py": 900,
    ROOT / "backend" / "app" / "anpr.py": 700,
    ROOT / "backend" / "app" / "routers" / "_training_worker.py": 700,
    ROOT / "backend" / "app" / "routers" / "cameras.py": 500,
    ROOT / "backend" / "app" / "routers" / "detections.py": 550,
    ROOT / "backend" / "app" / "routers" / "training.py": 2200,
    ROOT / "backend" / "app" / "routers" / "training_samples.py": 1200,
    ROOT / "frontend" / "web" / "src" / "components" / "AppShell.tsx": 350,
    ROOT / "frontend" / "web" / "src" / "pages" / "CapturePage.jsx": 800,
    ROOT / "frontend" / "web" / "src" / "pages" / "ClipsPage.jsx": 450,
    ROOT / "frontend" / "web" / "src" / "pages" / "DashboardPage.tsx": 350,
    ROOT / "frontend" / "web" / "src" / "pages" / "DiscoveryPage.jsx": 550,
    ROOT / "frontend" / "web" / "src" / "pages" / "LivePage.jsx": 1300,
    ROOT / "frontend" / "web" / "src" / "pages" / "TrainedDataPage.jsx": 450,
    ROOT / "frontend" / "web" / "src" / "pages" / "TrainingDataPage.jsx": 1400,
    ROOT / "frontend" / "web" / "src" / "pages" / "TrainingPage.jsx": 1500,
    ROOT / "frontend" / "web" / "src" / "pages" / "DetectionsPage.jsx": 1200,
    ROOT / "frontend" / "web" / "src" / "pages" / "CamerasPage.jsx": 1400,
}

IGNORE_PARTS = {"node_modules", "dist", "__pycache__", ".git"}


def should_skip(path: Path) -> bool:
    return any(part in IGNORE_PARTS for part in path.parts)


def line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        return sum(1 for _ in f)


def main() -> int:
    violations = []
    for base, pattern, default_limit in RULES:
        if not base.exists():
            continue
        for path in base.rglob(pattern):
            if should_skip(path):
                continue
            limit = ALLOWLIST.get(path, default_limit)
            lines = line_count(path)
            if lines > limit:
                violations.append((path, lines, limit))

    if violations:
        print("File size limit violations:")
        for path, lines, limit in sorted(violations):
            rel = path.relative_to(ROOT)
            print(f"- {rel}: {lines} lines (limit {limit})")
        return 1

    print("File size check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
