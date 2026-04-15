# CarVision Project - Architecture & Technical Debt Review

**Date:** April 9, 2026  
**Codebase Size:** ~12K lines of Python, 36 Python modules  
**Test Coverage:** Minimal (3 test files)

---

## Executive Summary

CarVision is a FastAPI-based ANPR (Automatic Number Plate Recognition) platform with multi-camera support, admin dashboard, and training workflows. The architecture shows good module separation in the pipeline layer but has **critical maintainability issues** due to:

1. **Monolithic main.py** (7,000+ lines) — the single largest technical debt item
2. **Insufficient test coverage** (3 tests for 12K lines)
3. **Database migration strategy is fragile** — ad-hoc schema stitching in code
4. **Missing API abstraction layer** — route handlers directly tied to business logic
5. **Thread-safety concerns** — camera workers with shared state and caches
6. **Credential storage** — plaintext secrets in database and environment

**Verdict:** The codebase is **functional but not production-ready**. Major refactoring is needed before scaling beyond hobby/demo use.

---

## Architecture Overview

### Layer Structure
```
FastAPI Routes (main.py)
    ↓
Services Layer (services/, anpr.py, camera_manager.py)
    ↓
Pipeline Layer (pipeline/)
    ↓
Database Layer (models.py, db.py)
```

### Strengths

1. **Clean Pipeline Abstraction** — `PlateInferencePipeline` follows a strict sequential flow with clear stage outputs. Each stage (localization, cropping, OCR, etc.) is independently testable. This is the strongest part of the codebase.

2. **Multi-Camera Concurrency Model** — `CameraWorker` threads handle independent camera feeds without blocking the API. ThreadPoolExecutor for I/O keeps the detection loop responsive.

3. **Modular Services** — Dataset handling, debug assets, and training helpers are separated into services; avoids repeating logic across routes.

4. **Flexible Camera Support** — Webcam, RTSP, HTTP MJPEG, browser capture, and ONVIF discovery provide good device flexibility.

---

## Critical Issues

### 🔴 **1. Monolithic main.py (7,000+ lines)**

**Impact:** Unmaintainable, difficult to test, unclear responsibility boundaries.

**Current State:**
- Single file handles: authentication, all API routes, file uploads, training workflows, database operations, error handling
- Route handlers are ~30-100 lines each, often doing 5+ distinct tasks
- No clear separation between request validation, business logic, and data access

**Example of the Problem:**
```python
# In main.py, line ~2000+ — camera creation does too much:
@app.post("/api/cameras")
async def create_camera(body: ApiCameraCreateBody, db: Session = Depends(get_db)):
    # 1. Validates camera type
    # 2. Tests connection (opens stream)
    # 3. Creates DB record
    # 4. Starts background worker
    # 5. Configures notifications
    # 6. Handles 8 different error paths
    # ... 50+ lines of mixed concerns
```

**Recommended Solution:**
- Extract each router (cameras, detections, auth, training, uploads) into separate files in `/routers`
- Create a `CameraService` class that encapsulates camera lifecycle: creation, testing, starting, stopping
- Move authentication logic to middleware
- Create request/response schemas in `/api/schemas` (partially done, incomplete)

**Effort:** 3-4 weeks | **Priority:** CRITICAL

---

### 🔴 **2. Insufficient Test Coverage**

**Current State:**
- Only 3 test files for 12K lines of code (~0.025% coverage)
- No tests for:
  - Pipeline stages (localization, OCR, etc.)
  - Camera workers (threading, state management)
  - Database operations (models, queries)
  - API routes (endpoint behavior, error cases)
  - Services (dataset handling, debug assets)

**Examples of Untested Risky Code:**
1. **Thread-unsafe cache invalidation** in `CameraWorker`:
   ```python
   self._known_cache = []  # Updated from detection thread
   self._known_cache_ts = 0.0
   ```
   No locks; concurrent reads/writes possible.

2. **OCR failure paths** — no test for what happens when OCR returns None or empty string

3. **Database constraint violations** — unique plate_text constraint could fail silently if duplicate detection occurs

**Recommended Solution:**
- Write integration tests for each pipeline stage (mock inputs, verify outputs)
- Add threading tests for `CameraWorker` with mocked camera source
- Add parameterized tests for API routes with edge cases (missing fields, invalid types, permission denied)
- Target: 70%+ coverage on core logic

**Effort:** 2-3 weeks | **Priority:** HIGH

---

### 🔴 **3. Fragile Database Migration Strategy**

**Current State:**
- `db.py:ensure_schema()` attempts to add columns every startup
- Migration logic is **hard-coded for SQLite and PostgreSQL separately**
- No way to safely drop columns or rename fields
- New columns scattered across multiple conditional blocks

**Problems:**
1. If a migration partially fails (e.g., transaction rolls back), the app won't retry—column will remain missing
2. Alembic (industry standard) is not used; easy to introduce SQL syntax errors
3. No version tracking; can't tell which migrations have run
4. Schema changes are non-idempotent if they fail mid-transaction

**Example of Current Approach:**
```python
# db.py lines ~32-50: SQLite-specific checks
if "live_view" not in columns:
    conn.execute(text("ALTER TABLE cameras ADD COLUMN live_view BOOLEAN DEFAULT 1"))
# Then separate PostgreSQL branch with different SQL syntax at lines ~113+
```

**Recommended Solution:**
- Adopt **Alembic** for versioned migrations
- Create `alembic/versions/` directory with numbered migration files
- Each migration: schema change + rollback (down) procedure
- Run `alembic upgrade head` on startup

**Effort:** 1 week | **Priority:** HIGH

---

### 🔴 **4. Missing API Abstraction Layer**

**Current State:**
- Route handlers call database, services, and pipeline directly
- No request/response validation (partially done in `/api/schemas`)
- Error handling varies by endpoint (some return 500, some 400)
- No centralized logging of API calls

**Example:**
```python
@app.post("/api/detections/{detection_id}/feedback")
async def submit_feedback(detection_id: int, body: ApiBulkFeedbackBody, db: Session = Depends(get_db)):
    # Directly queries DB
    detection = db.query(Detection).filter(Detection.id == detection_id).first()
    if not detection:
        raise HTTPException(status_code=404)
    
    # Directly updates DB
    detection.feedback_status = body.status
    db.commit()
    
    # No abstraction for permission checks, audit logging, etc.
```

**Recommended Solution:**
- Create a `DetectionService` class:
  ```python
  class DetectionService:
      def submit_feedback(self, detection_id: int, status: str, db: Session) -> Detection:
          # business logic
  ```
- Move all DB queries into services
- Add request validators (use Pydantic models more aggressively)
- Centralize error handling with middleware

**Effort:** 2 weeks | **Priority:** HIGH

---

### 🟠 **5. Thread-Safety Concerns in CameraWorker**

**Current State:**
- `CameraWorker._known_cache`, `_recent`, `_history` are accessed from detection thread without locks
- `_mode_provider` and `_stream_manager` callbacks could be called concurrently
- No synchronization between main thread (updating settings) and camera thread (reading them)

**Example Problematic Code:**
```python
# camera_manager.py lines ~43-50
class CameraWorker:
    def __init__(self, ...):
        self._known_cache = []  # <-- Updated from camera thread
        self._policy_cache = {"min_len": 5, "max_len": 8}  # <-- Shared dict
        self._last_scan_thumb = None  # <-- Can be written by detection thread
```

If `_known_cache` is updated while another thread iterates over it, we get a RuntimeError.

**Recommended Solution:**
- Use `threading.Lock()` around cache access:
  ```python
  self._cache_lock = threading.Lock()
  
  def _is_allowed(self, plate_text: str) -> bool:
      with self._cache_lock:
          return any(ap.plate_text == plate_text for ap in self._known_cache)
  ```
- Add unit tests that stress-test concurrent access

**Effort:** 3-4 days | **Priority:** MEDIUM (will cause rare crashes in production)

---

### 🟠 **6. Credentials and Secrets Management**

**Current State:**
- Default credentials `admin`/`admin` are hardcoded in `core/config.py`
- ONVIF passwords stored as plaintext in database
- JWT secret is `"carvision-dev-secret"` by default
- No encryption for sensitive fields in database

**Risk:**
- If database is compromised, all camera credentials are exposed
- Default admin password is a known vector for unauthorized access

**Recommended Solution:**
- Use `cryptography.Fernet` or `python-keyring` to encrypt ONVIF credentials before storing
- Enforce strong admin passwords on first startup
- Add a secrets management layer (HashiCorp Vault, AWS Secrets Manager, or Docker Secrets)
- Rotate JWT secret periodically

**Effort:** 1 week | **Priority:** MEDIUM-HIGH (depends on deployment context)

---

### 🟡 **7. Missing Error Handling in Pipeline Stages**

**Current State:**
- Pipeline assumes each stage always returns a result
- If OCR fails, plate_text could be `None` or empty
- If quality scoring returns empty list, code tries to access `[0]` → IndexError

**Example (orchestrator.py):**
```python
def run(self, frame, ...):
    # ...
    qualities = score_crops(crops)
    if not qualities:
        return None
    
    qualities = sorted(qualities, key=lambda q: q.score, reverse=True)
    best_quality = qualities[0]  # <-- Safe only because of the check above
```

**Good:** The current code does have some checks. But consider:
```python
ocr = recognize(rectified, detection=primary_det, plate_type=classifier.plate_type)
post = postprocess(ocr, plate_type=classifier.plate_type)
```

If `recognize()` returns an OCR result with `None` text, `postprocess()` might not handle it gracefully.

**Recommended Solution:**
- Add type annotations and runtime validation with Pydantic models for stage outputs
- Explicit handling for empty/null results from each stage
- Add logging at each stage for debugging

**Effort:** 4-5 days | **Priority:** MEDIUM

---

## Good Practices (Don't Lose These!)

1. ✅ **Pipeline separation** — excellent modularity in `pipeline/`
2. ✅ **Concurrent I/O with thread pool** — prevents blocking the detection loop
3. ✅ **Configurable camera types** — flexible hardware support
4. ✅ **Environment-based configuration** — good for Docker/dev-to-prod transitions
5. ✅ **JSON-based debug outputs** — makes debugging easier

---

## Recommendations by Priority

| Priority | Item | Effort | Impact |
|----------|------|--------|--------|
| 🔴 CRITICAL | Split monolithic main.py | 3-4 weeks | Enables testing, reduces bugs |
| 🔴 CRITICAL | Add integration tests | 2-3 weeks | Catches regressions early |
| 🔴 CRITICAL | Switch to Alembic migrations | 1 week | Prevents schema inconsistencies |
| 🟠 HIGH | Add service abstraction layer | 2 weeks | Better testability, reusability |
| 🟠 HIGH | Thread-safety locks | 3-4 days | Prevents race conditions |
| 🟠 HIGH | Encrypt credentials | 1 week | Security hardening |
| 🟡 MEDIUM | Error handling in pipeline | 4-5 days | Better resilience |
| 🟡 MEDIUM | API request validation | 3-5 days | Cleaner error messages |

---

## Summary

CarVision is a **solid MVP** with well-designed pipeline logic and good concurrency patterns. However, it **needs immediate refactoring** before it can be safely deployed to production or extended with new features. The three critical issues (monolithic main.py, poor test coverage, fragile migrations) will compound as the project grows.

**Next Steps:**
1. Extract routers from main.py into separate modules (highest ROI for effort)
2. Write tests for pipeline stages and API endpoints
3. Migrate to Alembic for schema management
4. Add logging and monitoring
5. Document API contracts

---

## Files to Prioritize for Refactoring

1. `backend/app/main.py` — split into modules in `routers/`
2. `backend/app/db.py` — replace manual migrations with Alembic
3. `backend/app/camera_manager.py` — add threading locks, service abstraction
4. `backend/app/pipeline/` — add integration tests
5. `tests/` — expand test suite (currently 3 tests)
