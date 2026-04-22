import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./carvision.db")

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema():
    with engine.begin() as conn:
        dialect = engine.dialect.name

        if dialect == "sqlite":
            tables = [row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).all()]
            if "cameras" in tables:
                columns = [row[1] for row in conn.execute(text("PRAGMA table_info(cameras)")).all()]
                if "live_view" not in columns:
                    conn.execute(text("ALTER TABLE cameras ADD COLUMN live_view BOOLEAN DEFAULT 1"))
                if "live_order" not in columns:
                    conn.execute(text("ALTER TABLE cameras ADD COLUMN live_order INTEGER DEFAULT 0"))
                if "onvif_xaddr" not in columns:
                    conn.execute(text("ALTER TABLE cameras ADD COLUMN onvif_xaddr TEXT"))
                if "onvif_username" not in columns:
                    conn.execute(text("ALTER TABLE cameras ADD COLUMN onvif_username TEXT"))
                if "onvif_password" not in columns:
                    conn.execute(text("ALTER TABLE cameras ADD COLUMN onvif_password TEXT"))
                if "onvif_profile" not in columns:
                    conn.execute(text("ALTER TABLE cameras ADD COLUMN onvif_profile TEXT"))
                if "model" not in columns:
                    conn.execute(text("ALTER TABLE cameras ADD COLUMN model TEXT"))
                if "detector_mode" not in columns:
                    conn.execute(text("ALTER TABLE cameras ADD COLUMN detector_mode TEXT DEFAULT 'inherit'"))
                if "capture_token" not in columns:
                    conn.execute(text("ALTER TABLE cameras ADD COLUMN capture_token TEXT"))
                conn.execute(text("UPDATE cameras SET live_view = 1 WHERE live_view IS NULL"))
                conn.execute(text("UPDATE cameras SET live_order = 0 WHERE live_order IS NULL"))
                conn.execute(text("UPDATE cameras SET detector_mode = 'inherit' WHERE detector_mode IS NULL"))
            if "detections" in tables:
                columns = [row[1] for row in conn.execute(text("PRAGMA table_info(detections)")).all()]
                if "debug_color_path" not in columns:
                    conn.execute(text("ALTER TABLE detections ADD COLUMN debug_color_path TEXT"))
                if "debug_bw_path" not in columns:
                    conn.execute(text("ALTER TABLE detections ADD COLUMN debug_bw_path TEXT"))
                if "debug_gray_path" not in columns:
                    conn.execute(text("ALTER TABLE detections ADD COLUMN debug_gray_path TEXT"))
                if "debug_edged_path" not in columns:
                    conn.execute(text("ALTER TABLE detections ADD COLUMN debug_edged_path TEXT"))
                if "debug_mask_path" not in columns:
                    conn.execute(text("ALTER TABLE detections ADD COLUMN debug_mask_path TEXT"))
                if "detector" not in columns:
                    conn.execute(text("ALTER TABLE detections ADD COLUMN detector TEXT"))
                if "image_hash" not in columns:
                    conn.execute(text("ALTER TABLE detections ADD COLUMN image_hash TEXT"))
                if "feedback_sample_id" not in columns:
                    conn.execute(text("ALTER TABLE detections ADD COLUMN feedback_sample_id INTEGER"))
                if "feedback_status" not in columns:
                    conn.execute(text("ALTER TABLE detections ADD COLUMN feedback_status TEXT"))
                if "feedback_note" not in columns:
                    conn.execute(text("ALTER TABLE detections ADD COLUMN feedback_note TEXT"))
                if "feedback_at" not in columns:
                    conn.execute(text("ALTER TABLE detections ADD COLUMN feedback_at TEXT"))
            if "training_samples" in tables:
                columns = [row[1] for row in conn.execute(text("PRAGMA table_info(training_samples)")).all()]
                if "image_hash" not in columns:
                    conn.execute(text("ALTER TABLE training_samples ADD COLUMN image_hash TEXT"))
                if "no_plate" not in columns:
                    conn.execute(text("ALTER TABLE training_samples ADD COLUMN no_plate BOOLEAN DEFAULT 0"))
                if "unclear_plate" not in columns:
                    conn.execute(text("ALTER TABLE training_samples ADD COLUMN unclear_plate BOOLEAN DEFAULT 0"))
                if "ignored" not in columns:
                    conn.execute(text("ALTER TABLE training_samples ADD COLUMN ignored BOOLEAN DEFAULT 0"))
                if "import_batch" not in columns:
                    conn.execute(text("ALTER TABLE training_samples ADD COLUMN import_batch TEXT"))
                if "processed_at" not in columns:
                    conn.execute(text("ALTER TABLE training_samples ADD COLUMN processed_at TEXT"))
                if "last_trained_at" not in columns:
                    conn.execute(text("ALTER TABLE training_samples ADD COLUMN last_trained_at TEXT"))
                conn.execute(text("UPDATE training_samples SET no_plate = 0 WHERE no_plate IS NULL"))
                conn.execute(text("UPDATE training_samples SET unclear_plate = 0 WHERE unclear_plate IS NULL"))
                conn.execute(text("UPDATE training_samples SET ignored = 0 WHERE ignored IS NULL"))
            if "notifications" in tables:
                columns = [row[1] for row in conn.execute(text("PRAGMA table_info(notifications)")).all()]
                if "kind" not in columns:
                    conn.execute(text("ALTER TABLE notifications ADD COLUMN kind TEXT"))
                if "is_read" not in columns:
                    conn.execute(text("ALTER TABLE notifications ADD COLUMN is_read BOOLEAN DEFAULT 0"))
                if "read_at" not in columns:
                    conn.execute(text("ALTER TABLE notifications ADD COLUMN read_at TEXT"))
                if "camera_id" not in columns:
                    conn.execute(text("ALTER TABLE notifications ADD COLUMN camera_id INTEGER"))
                if "detection_id" not in columns:
                    conn.execute(text("ALTER TABLE notifications ADD COLUMN detection_id INTEGER"))
                if "extra" not in columns:
                    conn.execute(text("ALTER TABLE notifications ADD COLUMN extra TEXT"))
                conn.execute(text("UPDATE notifications SET is_read = 0 WHERE is_read IS NULL"))
        else:
            conn.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS live_view BOOLEAN DEFAULT TRUE"))
            conn.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS live_order INTEGER DEFAULT 0"))
            conn.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS onvif_xaddr VARCHAR(500)"))
            conn.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS onvif_username VARCHAR(200)"))
            conn.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS onvif_password VARCHAR(200)"))
            conn.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS onvif_profile VARCHAR(200)"))
            conn.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS model VARCHAR(200)"))
            conn.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS detector_mode VARCHAR(20) DEFAULT 'inherit'"))
            conn.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS capture_token VARCHAR(200)"))
            conn.execute(text("UPDATE cameras SET live_view = TRUE WHERE live_view IS NULL"))
            conn.execute(text("UPDATE cameras SET live_order = 0 WHERE live_order IS NULL"))
            conn.execute(text("UPDATE cameras SET detector_mode = 'inherit' WHERE detector_mode IS NULL"))
            conn.execute(text("ALTER TABLE detections ADD COLUMN IF NOT EXISTS debug_color_path VARCHAR(500)"))
            conn.execute(text("ALTER TABLE detections ADD COLUMN IF NOT EXISTS debug_bw_path VARCHAR(500)"))
            conn.execute(text("ALTER TABLE detections ADD COLUMN IF NOT EXISTS debug_gray_path VARCHAR(500)"))
            conn.execute(text("ALTER TABLE detections ADD COLUMN IF NOT EXISTS debug_edged_path VARCHAR(500)"))
            conn.execute(text("ALTER TABLE detections ADD COLUMN IF NOT EXISTS debug_mask_path VARCHAR(500)"))
            conn.execute(text("ALTER TABLE detections ADD COLUMN IF NOT EXISTS detector VARCHAR(20)"))
            conn.execute(text("ALTER TABLE detections ADD COLUMN IF NOT EXISTS image_hash VARCHAR(64)"))
            conn.execute(text("ALTER TABLE detections ADD COLUMN IF NOT EXISTS feedback_sample_id INTEGER"))
            conn.execute(text("ALTER TABLE detections ADD COLUMN IF NOT EXISTS feedback_status VARCHAR(20)"))
            conn.execute(text("ALTER TABLE detections ADD COLUMN IF NOT EXISTS feedback_note TEXT"))
            conn.execute(text("ALTER TABLE detections ADD COLUMN IF NOT EXISTS feedback_at TIMESTAMP"))
            conn.execute(text("ALTER TABLE training_samples ADD COLUMN IF NOT EXISTS image_hash VARCHAR(64)"))
            conn.execute(text("ALTER TABLE training_samples ADD COLUMN IF NOT EXISTS no_plate BOOLEAN DEFAULT FALSE"))
            conn.execute(text("ALTER TABLE training_samples ADD COLUMN IF NOT EXISTS unclear_plate BOOLEAN DEFAULT FALSE"))
            conn.execute(text("ALTER TABLE training_samples ADD COLUMN IF NOT EXISTS ignored BOOLEAN DEFAULT FALSE"))
            conn.execute(text("ALTER TABLE training_samples ADD COLUMN IF NOT EXISTS import_batch VARCHAR(80)"))
            conn.execute(text("ALTER TABLE training_samples ADD COLUMN IF NOT EXISTS processed_at TIMESTAMP"))
            conn.execute(text("ALTER TABLE training_samples ADD COLUMN IF NOT EXISTS last_trained_at TIMESTAMP"))
            conn.execute(text("UPDATE training_samples SET no_plate = FALSE WHERE no_plate IS NULL"))
            conn.execute(text("UPDATE training_samples SET unclear_plate = FALSE WHERE unclear_plate IS NULL"))
            conn.execute(text("UPDATE training_samples SET ignored = FALSE WHERE ignored IS NULL"))
            conn.execute(text("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS kind VARCHAR(50)"))
            conn.execute(text("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS is_read BOOLEAN DEFAULT FALSE"))
            conn.execute(text("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS read_at TIMESTAMP"))
            conn.execute(text("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS camera_id INTEGER"))
            conn.execute(text("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS detection_id INTEGER"))
            conn.execute(text("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS extra JSONB"))
            conn.execute(text("UPDATE notifications SET is_read = FALSE WHERE is_read IS NULL"))
