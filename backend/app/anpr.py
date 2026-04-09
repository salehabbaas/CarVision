"""
anpr.py – Plate OCR, normalisation, and contour-based localisation.

Real-time optimisations applied here:
  1. EasyOCR reader is pre-warmed in a background thread at import time so
     the first live frame isn't blocked by a cold 3–6 second model load.
  2. The number of OCR image variants is reduced from 4–5 down to 2 fast ones
     (RGB + upscaled grayscale) for the primary path.  Extra variants are only
     tried when the primary read returns nothing.
  3. Small plate crops are upscaled once to a fixed width before any OCR is
     run (instead of only when w < 640).  This dramatically improves OCR
     accuracy on crops from wide-angle cameras.
  4. A lightweight frame-level cache (last-frame hash → result) prevents
     running OCR twice on the exact same frame bytes when the camera worker
     and the pipeline orchestrator both call read_plate_text on the same crop.
"""

import hashlib
import os
import threading
import re
import json
from typing import Optional, Dict, Tuple

import cv2
import numpy as np
import imutils

try:
    import easyocr
except Exception:
    easyocr = None


# ── Shared OCR reader ─────────────────────────────────────────────────────────
_reader_lock = threading.Lock()
_reader = None
_OCR_LANGS = ["en"]

_ANPR_CONFIG = {
    "inference_device": os.getenv("ANPR_INFERENCE_DEVICE", "cpu"),
    "ocr_max_width": 1280,
    "contour_canny_low": 30,
    "contour_canny_high": 200,
    "contour_bilateral_d": 11,
    "contour_bilateral_sigma_color": 17,
    "contour_bilateral_sigma_space": 17,
    "contour_approx_eps": 0.018,
    "contour_pad_ratio": 0.15,
    "contour_pad_min": 18,
    "plate_min_length": 5,
    "plate_max_length": 8,
    "plate_charset": "alnum",
    "plate_pattern_regex": "",
    "plate_shape_hint": "standard",
    "plate_reference_date": "",
    "ocr_char_map": "{}",
}

# ── Small per-crop result cache ───────────────────────────────────────────────
# Key: sha1 of the crop bytes.  Value: (result_dict, timestamp).
# Only the last 8 distinct crops are kept to bound memory.
_ocr_cache: Dict[str, Dict] = {}
_ocr_cache_lock = threading.Lock()
_OCR_CACHE_MAXSIZE = 8


def _cache_key(image: np.ndarray) -> str:
    """Fast hash of a numpy array for cache lookup."""
    return hashlib.sha1(image.tobytes()).hexdigest()[:16]


def _cache_get(key: str) -> Optional[Dict]:
    with _ocr_cache_lock:
        return _ocr_cache.get(key)


def _cache_put(key: str, value: Dict):
    with _ocr_cache_lock:
        if len(_ocr_cache) >= _OCR_CACHE_MAXSIZE:
            # Evict the oldest entry (dict insertion order in Python 3.7+)
            oldest = next(iter(_ocr_cache))
            del _ocr_cache[oldest]
        _ocr_cache[key] = value


def set_anpr_config(config: Dict):
    global _reader, _OCR_LANGS
    if not isinstance(config, dict):
        return
    previous_device = str(_ANPR_CONFIG.get("inference_device", "cpu") or "cpu").strip().lower()
    langs = config.get("ocr_langs")
    if langs:
        if isinstance(langs, str):
            langs_list = [l.strip() for l in langs.split(",") if l.strip()]
        elif isinstance(langs, (list, tuple)):
            langs_list = [str(l).strip() for l in langs if str(l).strip()]
        else:
            langs_list = []
        if langs_list and langs_list != _OCR_LANGS:
            _OCR_LANGS = langs_list
            _reader = None  # force re-init on next read
    for key in _ANPR_CONFIG.keys():
        if key in config and config[key] is not None:
            _ANPR_CONFIG[key] = config[key]
    current_device = str(_ANPR_CONFIG.get("inference_device", "cpu") or "cpu").strip().lower()
    if current_device != previous_device:
        _reader = None


def _torch_cuda_available() -> bool:
    try:
        import torch
    except Exception:
        return False
    try:
        return bool(torch.cuda.is_available() and torch.cuda.device_count() > 0)
    except Exception:
        return False


def _easyocr_gpu_enabled() -> bool:
    device = str(_ANPR_CONFIG.get("inference_device", "cpu") or "cpu").strip().lower()
    return device == "gpu" and _torch_cuda_available()


def get_reader():
    """Return the shared EasyOCR reader, initialising it if necessary."""
    global _reader
    if _reader is None:
        with _reader_lock:
            if _reader is None:
                if easyocr is None:
                    raise RuntimeError(
                        "easyocr is not available. Ensure dependencies are installed."
                    )
                _reader = easyocr.Reader(_OCR_LANGS, gpu=_easyocr_gpu_enabled())
    return _reader


def _prewarm_reader():
    """
    Load the EasyOCR model in a background thread immediately at startup so
    the first real frame is not blocked by a cold 3–6 second model load.
    A tiny 64×16 white image is run through the reader to force full model
    init (lazy layers are only built on the first inference call).
    """
    def _load():
        try:
            reader = get_reader()
            dummy = np.full((16, 64, 3), 255, dtype=np.uint8)
            reader.readtext(dummy)
        except Exception:
            pass  # Swallow – startup prewarm is best-effort

    t = threading.Thread(target=_load, daemon=True, name="easyocr-prewarm")
    t.start()


# ── Trigger pre-warm at import time ──────────────────────────────────────────
_prewarm_reader()


# ── Normalisation helpers ─────────────────────────────────────────────────────

def normalize_plate(text: str) -> str:
    if not text:
        return ""
    upper = text.strip().upper()
    compact = re.sub(r"\s+", "", upper)

    if compact.startswith("IL"):
        compact = compact[2:]
    if compact.endswith("P"):
        compact = compact[:-1]

    if re.fullmatch(r"\d[.\-]?\d{4}-?\d{1,2}", compact):
        return re.sub(r"\D", "", compact)
    if re.fullmatch(r"\d{2}-?\d{3}-?\d{1,2}", compact):
        return re.sub(r"\D", "", compact)

    cleaned = "".join(ch for ch in compact if ch.isalnum()).upper()
    try:
        raw_map = _ANPR_CONFIG.get("ocr_char_map", "{}")
        mapping = json.loads(raw_map) if isinstance(raw_map, str) else dict(raw_map or {})
        if isinstance(mapping, dict) and mapping:
            cleaned = "".join(str(mapping.get(ch, ch))[:1] for ch in cleaned)
    except Exception:
        pass
    return cleaned


def _resize_for_ocr(image, max_width: int = 1280):
    h, w = image.shape[:2]
    if w <= max_width:
        return image
    scale = max_width / float(w)
    return cv2.resize(image, (int(w * scale), int(h * scale)))


def _upscale_crop(image, target_width: int = 320) -> np.ndarray:
    """
    Upscale small plate crops so EasyOCR gets enough pixel detail.
    target_width=320 is a sweet spot: fast enough for real-time, sharp
    enough for 5–8 character plates.
    """
    h, w = image.shape[:2]
    if w >= target_width:
        return image
    scale = target_width / float(w)
    new_w = int(w * scale)
    new_h = int(h * scale)
    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)


def _ocr_variants_fast(image) -> list:
    """
    Primary (fast) OCR variants – run these first.
    Only 2 variants: colour RGB + upscaled grayscale.
    """
    image = _resize_for_ocr(image, max_width=int(_ANPR_CONFIG.get("ocr_max_width", 1280)))
    image = _upscale_crop(image)

    variants = []
    variants.append(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    variants.append(gray)
    return variants


def _ocr_variants_extended(image) -> list:
    """
    Extra variants tried only when the fast pass returned nothing.
    Adds bilateral-blurred + adaptive-threshold images.
    """
    image = _resize_for_ocr(image, max_width=int(_ANPR_CONFIG.get("ocr_max_width", 1280)))
    image = _upscale_crop(image)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    blurred = cv2.bilateralFilter(
        gray,
        int(_ANPR_CONFIG.get("contour_bilateral_d", 11)),
        int(_ANPR_CONFIG.get("contour_bilateral_sigma_color", 17)),
        int(_ANPR_CONFIG.get("contour_bilateral_sigma_space", 17)),
    )
    thresh = cv2.adaptiveThreshold(
        blurred, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
        31, 2,
    )
    return [blurred, thresh]


def _json_safe(value):
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return value


# ── Scoring helpers ───────────────────────────────────────────────────────────

def _pattern_bonus(norm: str) -> float:
    if re.fullmatch(r"\d{7}", norm):      return 80.0
    if re.fullmatch(r"\d{6}", norm):      return 70.0
    if re.fullmatch(r"\d{5,6}[A-Z]", norm): return 60.0
    if re.fullmatch(r"[A-Z]{4}[0-9]{3}", norm): return 80.0
    if re.fullmatch(r"[A-Z]{3}[0-9]{3}", norm): return 60.0
    if re.fullmatch(r"[A-Z]{3}[0-9]{4}", norm): return 50.0
    if re.fullmatch(r"[A-Z]{2}[0-9]{4}", norm): return 40.0
    if re.fullmatch(r"[A-Z]{2}[0-9]{3}[A-Z]", norm): return 30.0
    return 0.0


AMBIGUOUS_TO_DIGIT = {
    "O": ["0"], "I": ["1"], "Z": ["7", "2"], "S": ["5"],
    "B": ["8"], "G": ["6"], "Q": ["0"], "D": ["0"], "T": ["7"],
}
AMBIGUOUS_TO_LETTER = {
    "0": ["O", "D"], "1": ["I"], "2": ["Z"], "5": ["S"],
    "6": ["G"], "7": ["T"], "8": ["B"],
}


def _generate_variants(norm: str):
    variants = {norm}
    for i, ch in enumerate(norm):
        if ch in AMBIGUOUS_TO_DIGIT:
            for alt in AMBIGUOUS_TO_DIGIT[ch]:
                variants.add(norm[:i] + alt + norm[i + 1:])
        if ch in AMBIGUOUS_TO_LETTER:
            for alt in AMBIGUOUS_TO_LETTER[ch]:
                variants.add(norm[:i] + alt + norm[i + 1:])
    if re.fullmatch(r"[A-Z]\d{4,6}[A-Z]+", norm):
        variants.add(norm[1:])
    if re.fullmatch(r"\d{4,6}[A-Z]{2}", norm):
        variants.add(norm[:-1])
    full = list(norm)
    changed = False
    for i, ch in enumerate(full):
        if ch in AMBIGUOUS_TO_DIGIT:
            full[i] = AMBIGUOUS_TO_DIGIT[ch][0]
            changed = True
    if changed:
        variants.add("".join(full))
    return variants


def _score_candidate_norm(norm: str, conf: float) -> float:
    if not norm:
        return -999.0
    length = len(norm)
    has_digits = any(ch.isdigit() for ch in norm)
    has_letters = any(ch.isalpha() for ch in norm)
    is_numeric_plate = bool(re.fullmatch(r"\d{6,7}", norm))

    min_len = int(_ANPR_CONFIG.get("plate_min_length", 5) or 5)
    max_len = int(_ANPR_CONFIG.get("plate_max_length", 8) or 8)
    if min_len > max_len:
        min_len, max_len = max_len, min_len
    charset = str(_ANPR_CONFIG.get("plate_charset", "alnum") or "alnum").lower()
    pattern_regex = str(_ANPR_CONFIG.get("plate_pattern_regex", "") or "").strip()
    shape_hint = str(_ANPR_CONFIG.get("plate_shape_hint", "standard") or "standard").lower()

    if length < min_len or length > max_len:
        return -500.0

    score = conf * 100.0
    score += length * 2.0
    if has_digits:  score += 20.0
    if has_letters: score += 10.0
    if not has_digits: score -= 200.0
    if not has_letters and not is_numeric_plate: score -= 120.0

    if charset == "digits" and has_letters:   score -= 250.0
    elif charset == "letters" and has_digits: score -= 250.0

    if pattern_regex:
        try:
            if re.fullmatch(pattern_regex, norm): score += 25.0
            else: score -= 80.0
        except re.error:
            pass

    score += _pattern_bonus(norm)

    if shape_hint == "long" and length >= max(min_len, 7): score += 10.0
    elif shape_hint in {"square", "motorcycle"} and length <= min(max_len, 6): score += 10.0

    blacklist = {
        "STREET", "ROAD", "AVE", "AVENUE", "BOULEVARD", "BLVD",
        "HIGHWAY", "HWY", "PARKING", "PARK", "BANK", "BANKSTREET",
        "ONTARIO", "QUEBEC",
    }
    if norm in blacklist:
        score -= 200.0
    return score


def _pick_best(results) -> Optional[Dict]:
    candidates = []
    for item in results:
        if not item or len(item) < 3:
            continue
        raw = item[1]
        conf = float(item[2]) if len(item) > 2 else 0.0
        norm = normalize_plate(raw)
        if not norm:
            continue
        for variant in _generate_variants(norm):
            score = _score_candidate_norm(variant, conf)
            candidates.append({
                "raw_text":   raw,
                "plate_text": variant,
                "confidence": conf,
                "score":      score,
                "bbox":       _json_safe(item[0]) if len(item) > 0 else None,
            })

    if not candidates:
        return None

    candidates = sorted(candidates, key=lambda c: c["score"], reverse=True)
    best = candidates[0]
    if best["score"] < 20.0:
        return None
    return {"best": best, "candidates": candidates[:8]}


# ── Public OCR entry point ────────────────────────────────────────────────────

def read_plate_text(image) -> Optional[Dict]:
    """
    Run EasyOCR on a plate crop and return the best plate candidate.

    Fast path (2 variants) → extended path (2 more variants) only when needed.
    Results for identical crops are cached to avoid double-inference.
    """
    if image is None:
        return None

    # ── cache lookup ──
    key = _cache_key(image)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    reader = get_reader()

    # ── fast pass (2 variants) ──
    all_results = []
    for variant in _ocr_variants_fast(image):
        try:
            results = reader.readtext(variant)
        except Exception:
            continue
        if results:
            all_results.extend(results)

    picked = _pick_best(all_results) if all_results else None

    # ── extended pass (only when fast pass found nothing) ──
    if not picked:
        for variant in _ocr_variants_extended(image):
            try:
                results = reader.readtext(variant)
            except Exception:
                continue
            if results:
                all_results.extend(results)
        picked = _pick_best(all_results) if all_results else None

    if not picked:
        _cache_put(key, None)  # cache misses too so we don't retry same crop
        return None

    best = picked["best"]
    plate_text = normalize_plate(best["raw_text"])
    if not plate_text:
        _cache_put(key, None)
        return None

    result = {
        "plate_text": plate_text,
        "confidence": best["confidence"],
        "bbox":       best.get("bbox"),
        "raw_text":   best["raw_text"],
        "candidates": picked["candidates"],
    }
    _cache_put(key, result)
    return result


# ── Geometry helpers ──────────────────────────────────────────────────────────

def crop_from_bbox(image, bbox):
    if image is None or not bbox:
        return None
    if isinstance(bbox, dict):
        try:
            x1 = int(bbox.get("x1", 0))
            y1 = int(bbox.get("y1", 0))
            x2 = int(bbox.get("x2", 0))
            y2 = int(bbox.get("y2", 0))
        except Exception:
            return None
    else:
        pts = np.array(bbox, dtype=int)
        if pts.ndim == 3 and pts.shape[1] == 1 and pts.shape[2] == 2:
            pts = pts.reshape(-1, 2)
        if pts.ndim != 2 or pts.shape[1] != 2:
            return None
        x1, y1 = pts[:, 0].min(), pts[:, 1].min()
        x2, y2 = pts[:, 0].max(), pts[:, 1].max()
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(image.shape[1] - 1, x2)
    y2 = min(image.shape[0] - 1, y2)
    if x2 <= x1 or y2 <= y1:
        return None
    return image[y1: y2 + 1, x1: x2 + 1]


def build_debug_images(image, bbox):
    crop = crop_from_bbox(image, bbox)
    if crop is None:
        crop = image
    color = _resize_for_ocr(crop)
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    bw = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
        31, 2,
    )
    return color, bw


def _build_mask(image, bbox):
    if image is None or not bbox:
        return None
    h, w = image.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    if isinstance(bbox, dict):
        try:
            x1 = int(bbox.get("x1", 0)); y1 = int(bbox.get("y1", 0))
            x2 = int(bbox.get("x2", 0)); y2 = int(bbox.get("y2", 0))
        except Exception:
            return None
        x1 = max(0, min(x1, w - 1)); x2 = max(0, min(x2, w - 1))
        y1 = max(0, min(y1, h - 1)); y2 = max(0, min(y2, h - 1))
        if x2 <= x1 or y2 <= y1:
            return None
        cv2.rectangle(mask, (x1, y1), (x2, y2), 255, -1)
        return mask

    pts = np.array(bbox, dtype=np.int32)
    if pts.ndim == 3 and pts.shape[1] == 1 and pts.shape[2] == 2:
        pts = pts.reshape(-1, 2)
    if pts.ndim != 2 or pts.shape[1] != 2:
        return None
    cv2.fillPoly(mask, [pts], 255)
    return mask


def build_debug_bundle(image, bbox):
    if image is None:
        return {"color": None, "bw": None, "gray": None, "edged": None, "mask": None}

    color, bw = build_debug_images(image, bbox)
    gray    = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.bilateralFilter(gray, 11, 17, 17)
    edged   = cv2.Canny(blurred, 30, 200)
    mask    = _build_mask(image, bbox)
    return {"color": color, "bw": bw, "gray": gray, "edged": edged, "mask": mask}


# ── Contour-based plate localisation (fallback when YOLO unavailable) ─────────

def detect_plate(frame) -> Optional[Dict]:
    """
    Contour-based plate localisation + OCR.
    Returns a detection dict or None.
    """
    if frame is None:
        return None

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    bfilter = cv2.bilateralFilter(
        gray,
        int(_ANPR_CONFIG.get("contour_bilateral_d", 11)),
        int(_ANPR_CONFIG.get("contour_bilateral_sigma_color", 17)),
        int(_ANPR_CONFIG.get("contour_bilateral_sigma_space", 17)),
    )
    edged = cv2.Canny(
        bfilter,
        int(_ANPR_CONFIG.get("contour_canny_low", 30)),
        int(_ANPR_CONFIG.get("contour_canny_high", 200)),
    )

    keypoints = cv2.findContours(edged.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    contours  = imutils.grab_contours(keypoints)
    contours  = sorted(contours, key=cv2.contourArea, reverse=True)[:10]

    location    = None
    contour_ref = None
    for contour in contours:
        peri = cv2.arcLength(contour, True)
        eps  = float(_ANPR_CONFIG.get("contour_approx_eps", 0.018))
        approx = cv2.approxPolyDP(contour, eps * peri, True)
        if len(approx) == 4:
            location    = approx
            contour_ref = contour
            break

    if location is None and contours:
        c    = max(contours, key=cv2.contourArea)
        rect = cv2.minAreaRect(c)
        box  = cv2.boxPoints(rect)
        box  = np.int32(box)
        location    = box.reshape(-1, 1, 2)
        contour_ref = c

    if location is None:
        # No contours found at all — return early rather than scanning the whole
        # frame for arbitrary text (road markings, building numbers, sky, etc.)
        return None

    location = location.astype(np.int32)
    mask     = np.zeros(gray.shape, np.uint8)
    cv2.drawContours(mask, [location], -1, 255, -1)

    if contour_ref is not None:
        x, y, w, h = cv2.boundingRect(contour_ref)
        pad = max(
            int(_ANPR_CONFIG.get("contour_pad_min", 18)),
            int(float(_ANPR_CONFIG.get("contour_pad_ratio", 0.15)) * max(w, h)),
        )
        r1 = max(0, y - pad); c1 = max(0, x - pad)
        r2 = min(frame.shape[0] - 1, y + h + pad)
        c2 = min(frame.shape[1] - 1, x + w + pad)
        cropped_image = frame[r1:r2 + 1, c1:c2 + 1]
    else:
        rows, cols = np.where(mask == 255)
        if rows.size == 0 or cols.size == 0:
            return None  # mask empty — no usable region
        r1, c1 = int(np.min(rows)), int(np.min(cols))
        r2, c2 = int(np.max(rows)), int(np.max(cols))
        box_h = max(1, r2 - r1); box_w = max(1, c2 - c1)
        # Guard against near-full-frame crops that are not plate candidates
        fh, fw = frame.shape[:2]
        if box_w > fw * 0.7 or box_h > fh * 0.6:
            return None
        pad = max(
            int(_ANPR_CONFIG.get("contour_pad_min", 18)),
            int(float(_ANPR_CONFIG.get("contour_pad_ratio", 0.15)) * max(box_h, box_w)),
        )
        r1 = max(0, r1 - pad); c1 = max(0, c1 - pad)
        r2 = min(frame.shape[0] - 1, r2 + pad)
        c2 = min(frame.shape[1] - 1, c2 + pad)
        cropped_image = frame[r1:r2 + 1, c1:c2 + 1]

    detected = read_plate_text(cropped_image)
    if detected:
        detected["bbox"] = location.reshape(-1, 2).tolist()
    return detected
