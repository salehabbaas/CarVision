from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db import Base


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    type = Column(String(30), nullable=False)  # webcam, rtsp, http_mjpeg
    source = Column(String(500), nullable=False)
    location = Column(String(200), nullable=True)
    model = Column(String(200), nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)

    scan_interval = Column(Float, default=0.15, nullable=False)
    cooldown_seconds = Column(Float, default=10.0, nullable=False)

    save_snapshot = Column(Boolean, default=True, nullable=False)
    save_clip = Column(Boolean, default=False, nullable=False)
    clip_seconds = Column(Integer, default=5, nullable=False)
    live_view = Column(Boolean, default=True, nullable=False)
    live_order = Column(Integer, default=0, nullable=False)
    onvif_xaddr = Column(String(500), nullable=True)
    onvif_username = Column(String(200), nullable=True)
    onvif_password = Column(String(200), nullable=True)
    onvif_profile = Column(String(200), nullable=True)
    detector_mode = Column(String(20), default="inherit", nullable=False)
    capture_token = Column(String(200), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    detections = relationship("Detection", back_populates="camera", cascade="all, delete-orphan")


class AllowedPlate(Base):
    __tablename__ = "allowed_plates"

    id = Column(Integer, primary_key=True)
    plate_text = Column(String(50), unique=True, nullable=False)
    label = Column(String(200), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Detection(Base):
    __tablename__ = "detections"

    id = Column(Integer, primary_key=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False)
    plate_text = Column(String(50), nullable=False)
    confidence = Column(Float, nullable=True)
    status = Column(String(20), nullable=False)  # allowed, denied, unknown

    image_path = Column(String(500), nullable=True)
    video_path = Column(String(500), nullable=True)
    debug_color_path = Column(String(500), nullable=True)
    debug_bw_path = Column(String(500), nullable=True)
    debug_gray_path = Column(String(500), nullable=True)
    debug_edged_path = Column(String(500), nullable=True)
    debug_mask_path = Column(String(500), nullable=True)
    bbox = Column(JSON, nullable=True)
    raw_text = Column(Text, nullable=True)
    detector = Column(String(20), nullable=True)
    image_hash = Column(String(64), nullable=True)
    feedback_sample_id = Column(Integer, nullable=True)
    feedback_status = Column(String(20), nullable=True)
    feedback_note = Column(Text, nullable=True)
    feedback_at = Column(DateTime(timezone=True), nullable=True)

    detected_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    camera = relationship("Camera", back_populates="detections")


class TrainingSample(Base):
    __tablename__ = "training_samples"

    id = Column(Integer, primary_key=True)
    image_path = Column(String(500), nullable=False)
    image_hash = Column(String(64), nullable=True)
    image_width = Column(Integer, nullable=True)
    image_height = Column(Integer, nullable=True)
    plate_text = Column(String(50), nullable=True)
    bbox = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)
    no_plate = Column(Boolean, default=False, nullable=False)
    unclear_plate = Column(Boolean, default=False, nullable=False)
    ignored = Column(Boolean, default=False, nullable=False)
    import_batch = Column(String(80), nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    last_trained_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TrainingJob(Base):
    __tablename__ = "training_jobs"

    id = Column(String(64), primary_key=True)
    kind = Column(String(30), nullable=False, default="pipeline")
    status = Column(String(20), nullable=False, default="queued")
    mode = Column(String(20), nullable=False, default="new_only")
    stage = Column(String(50), nullable=False, default="queued")
    progress = Column(Float, nullable=False, default=0.0)
    message = Column(Text, nullable=True)
    total_samples = Column(Integer, nullable=False, default=0)
    trained_samples = Column(Integer, nullable=False, default=0)
    ocr_scanned = Column(Integer, nullable=False, default=0)
    ocr_updated = Column(Integer, nullable=False, default=0)
    chunk_size = Column(Integer, nullable=False, default=1000)
    chunk_index = Column(Integer, nullable=False, default=0)
    chunk_total = Column(Integer, nullable=False, default=0)
    run_started_at = Column(DateTime(timezone=True), nullable=True)
    run_dir = Column(String(500), nullable=True)
    model_path = Column(String(500), nullable=True)
    details = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(String(500), nullable=False)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    level = Column(String(20), nullable=False, default="info")
    kind = Column(String(50), nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=True)
    detection_id = Column(Integer, ForeignKey("detections.id"), nullable=True)
    extra = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ClipRecord(Base):
    __tablename__ = "clip_records"

    id = Column(Integer, primary_key=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False)
    kind = Column(String(20), nullable=False, default="manual")
    file_path = Column(String(500), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Float, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    detection_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
