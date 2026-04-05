import threading
import re
from typing import Optional, Dict

import cv2
import numpy as np
import imutils

try:
    import easyocr
except Exception:
    easyocr = None


_reader_lock = threading.Lock()
_reader = None
_OCR_LANGS = ["en"]
_ANPR_CONFIG = {
    "ocr_max_width": 1280,
    "contour_canny_low": 30,
    "contour_canny_high": 200,
    "contour_bilateral_d": 11,
    "contour_bilateral_sigma_color": 17,
    "contour_bilateral_sigma_space": 17,
    "contour_approx_eps": 0.018,
    "contour_pad_ratio": 0.15,
    "contour_pad_min": 18,
}


def set_anpr_config(config: Dict):
    global _reader, _OCR_LANGS
    if not isinstance(config, dict):
        return
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
            _reader = None
    for key in _ANPR_CONFIG.keys():
        if key in config and config[key] is not None:
            _ANPR_CONFIG[key] = config[key]


def get_reader():
    global _reader
    if _reader is None:
        with _reader_lock:
            if _reader is None:
                if easyocr is None:
                    raise RuntimeError("easyocr is not available. Ensure dependencies are installed.")
                _reader = easyocr.Reader(_OCR_LANGS, gpu=False)
    return _reader


def normalize_plate(text: str) -> str:
    if not text:
        return ""
    upper = text.strip().upper()
    compact = re.sub(r"\s+", "", upper)

    # Always strip country markers when present
    if compact.startswith("IL"):
        compact = compact[2:]
    if compact.endswith("P"):
        compact = compact[:-1]

    # فلسطين (P suffix): X.XXXX-X / X.XXXX-XX -> return digits only
    if re.fullmatch(r"\d[.\-]?\d{4}-?\d{1,2}", compact):
        return re.sub(r"\D", "", compact)

    # إسرائيل (IL prefix removed above): XX-XXX-XX / XX-XXX-X -> return digits only
    if re.fullmatch(r"\d{2}-?\d{3}-?\d{1,2}", compact):
        return re.sub(r"\D", "", compact)

    cleaned = "".join(ch for ch in compact if ch.isalnum())
    return cleaned.upper()


def _resize_for_ocr(image, max_width: int = 1280):
    h, w = image.shape[:2]
    if w <= max_width:
        return image
    scale = max_width / float(w)
    return cv2.resize(image, (int(w * scale), int(h * scale)))


def _ocr_variants(image):
    variants = []
    image = _resize_for_ocr(image, max_width=int(_ANPR_CONFIG.get("ocr_max_width", 1280)))
    variants.append(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    variants.append(gray)

    blurred = cv2.bilateralFilter(
        gray,
        int(_ANPR_CONFIG.get("contour_bilateral_d", 11)),
        int(_ANPR_CONFIG.get("contour_bilateral_sigma_color", 17)),
        int(_ANPR_CONFIG.get("contour_bilateral_sigma_space", 17)),
    )
    variants.append(blurred)

    thresh = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        2,
    )
    variants.append(thresh)

    # Upscale small images to help OCR
    h, w = gray.shape[:2]
    if w < 640:
        scale = 640 / float(w)
        up = cv2.resize(image, (int(w * scale), int(h * scale)))
        variants.append(cv2.cvtColor(up, cv2.COLOR_BGR2RGB))
    return variants


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


def _pattern_bonus(norm: str) -> float:
    if re.fullmatch(r"\d{7}", norm):
        return 80.0
    if re.fullmatch(r"\d{6}", norm):
        return 70.0
    if re.fullmatch(r"\d{5,6}[A-Z]", norm):
        return 60.0
    if re.fullmatch(r"[A-Z]{4}[0-9]{3}", norm):
        return 80.0
    if re.fullmatch(r"[A-Z]{3}[0-9]{3}", norm):
        return 60.0
    if re.fullmatch(r"[A-Z]{3}[0-9]{4}", norm):
        return 50.0
    if re.fullmatch(r"[A-Z]{2}[0-9]{4}", norm):
        return 40.0
    if re.fullmatch(r"[A-Z]{2}[0-9]{3}[A-Z]", norm):
        return 30.0
    return 0.0


AMBIGUOUS_TO_DIGIT = {
    "O": ["0"],
    "I": ["1"],
    "Z": ["7", "2"],
    "S": ["5"],
    "B": ["8"],
    "G": ["6"],
    "Q": ["0"],
    "D": ["0"],
    "T": ["7"],
}

AMBIGUOUS_TO_LETTER = {
    "0": ["O", "D"],
    "1": ["I"],
    "2": ["Z"],
    "5": ["S"],
    "6": ["G"],
    "7": ["T"],
    "8": ["B"],
}


def _generate_variants(norm: str):
    variants = {norm}
    for i, ch in enumerate(norm):
        if ch in AMBIGUOUS_TO_DIGIT:
            for alt in AMBIGUOUS_TO_DIGIT[ch]:
                variants.add(norm[:i] + alt + norm[i + 1 :])
        if ch in AMBIGUOUS_TO_LETTER:
            for alt in AMBIGUOUS_TO_LETTER[ch]:
                variants.add(norm[:i] + alt + norm[i + 1 :])
    # Trim likely OCR noise on leading/trailing letters
    if re.fullmatch(r"[A-Z]\d{4,6}[A-Z]+", norm):
        variants.add(norm[1:])  # drop leading letter
    if re.fullmatch(r"\d{4,6}[A-Z]{2}", norm):
        variants.add(norm[:-1])  # drop trailing letter
    # also try a full replacement pass to digits
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

    # Basic length constraints for plates (configurable if needed)
    if length < 5 or length > 8:
        return -500.0

    score = conf * 100.0
    score += length * 2.0
    if has_digits:
        score += 20.0
    if has_letters:
        score += 10.0
    if not has_digits:
        score -= 200.0
    if not has_letters and not is_numeric_plate:
        score -= 120.0

    score += _pattern_bonus(norm)

    blacklist = {
        "STREET", "ROAD", "AVE", "AVENUE", "BOULEVARD", "BLVD", "HIGHWAY", "HWY",
        "PARKING", "PARK", "BANK", "BANKSTREET", "ONTARIO", "QUEBEC",
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
        variants = _generate_variants(norm)
        for variant in variants:
            score = _score_candidate_norm(variant, conf)
            candidates.append(
                {
                    "raw_text": raw,
                    "plate_text": variant,
                    "confidence": conf,
                    "score": score,
                    "bbox": _json_safe(item[0]) if len(item) > 0 else None,
                }
            )

    if not candidates:
        return None

    candidates = sorted(candidates, key=lambda c: c["score"], reverse=True)
    best = candidates[0]
    if best["score"] < 20.0:
        return None
    return {
        "best": best,
        "candidates": candidates[:8],
    }


def read_plate_text(image) -> Optional[Dict]:
    if image is None:
        return None

    reader = get_reader()
    all_results = []

    for variant in _ocr_variants(image):
        try:
            results = reader.readtext(variant)
        except Exception:
            continue
        if results:
            all_results.extend(results)

    if not all_results:
        return None

    picked = _pick_best(all_results)
    if not picked:
        return None

    best = picked["best"]
    raw_text = best["raw_text"]
    confidence = best["confidence"]

    plate_text = normalize_plate(raw_text)
    if not plate_text:
        return None

    bbox = best.get("bbox")

    return {
        "plate_text": plate_text,
        "confidence": confidence,
        "bbox": bbox,
        "raw_text": raw_text,
        "candidates": picked["candidates"],
    }


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
    return image[y1 : y2 + 1, x1 : x2 + 1]


def build_debug_images(image, bbox):
    crop = crop_from_bbox(image, bbox)
    if crop is None:
        crop = image
    color = _resize_for_ocr(crop)
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    bw = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        2,
    )
    return color, bw


def _build_mask(image, bbox):
    if image is None or not bbox:
        return None
    h, w = image.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    if isinstance(bbox, dict):
        try:
            x1 = int(bbox.get("x1", 0))
            y1 = int(bbox.get("y1", 0))
            x2 = int(bbox.get("x2", 0))
            y2 = int(bbox.get("y2", 0))
        except Exception:
            return None
        x1 = max(0, min(x1, w - 1))
        x2 = max(0, min(x2, w - 1))
        y1 = max(0, min(y1, h - 1))
        y2 = max(0, min(y2, h - 1))
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
        return {
            "color": None,
            "bw": None,
            "gray": None,
            "edged": None,
            "mask": None,
        }

    color, bw = build_debug_images(image, bbox)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.bilateralFilter(gray, 11, 17, 17)
    edged = cv2.Canny(blurred, 30, 200)
    mask = _build_mask(image, bbox)

    return {
        "color": color,
        "bw": bw,
        "gray": gray,
        "edged": edged,
        "mask": mask,
    }


def detect_plate(frame) -> Optional[Dict]:
    """
    Contour-based plate localization + OCR (fallback when YOLO is unavailable).
    Returns a dict with plate_text, confidence, bbox, raw_text if detected.
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
    contours = imutils.grab_contours(keypoints)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:10]

    location = None
    contour_ref = None
    for contour in contours:
        peri = cv2.arcLength(contour, True)
        approx_eps = float(_ANPR_CONFIG.get("contour_approx_eps", 0.018))
        approx_candidate = cv2.approxPolyDP(contour, approx_eps * peri, True)
        if len(approx_candidate) == 4:
            location = approx_candidate
            contour_ref = contour
            break

    # Fallbacks to avoid failures (align with notebook)
    if location is None and contours:
        c = max(contours, key=cv2.contourArea)
        rect = cv2.minAreaRect(c)
        box = cv2.boxPoints(rect)
        box = np.int32(box)
        location = box.reshape(-1, 1, 2)
        contour_ref = c

    if location is None:
        # Last resort: full image bounds
        h, w = gray.shape[:2]
        location = np.array([[[0, 0]], [[0, h - 1]], [[w - 1, h - 1]], [[w - 1, 0]]], dtype=np.int32)

    location = location.astype(np.int32)
    mask = np.zeros(gray.shape, np.uint8)
    cv2.drawContours(mask, [location], -1, 255, -1)

    if contour_ref is not None:
        x, y, w, h = cv2.boundingRect(contour_ref)
        pad = max(
            int(_ANPR_CONFIG.get("contour_pad_min", 18)),
            int(float(_ANPR_CONFIG.get("contour_pad_ratio", 0.15)) * max(w, h)),
        )
        r1 = max(0, y - pad)
        c1 = max(0, x - pad)
        r2 = min(frame.shape[0] - 1, y + h + pad)
        c2 = min(frame.shape[1] - 1, x + w + pad)
        cropped_image = frame[r1:r2 + 1, c1:c2 + 1]
    else:
        rows, cols = np.where(mask == 255)
        if rows.size == 0 or cols.size == 0:
            detected = read_plate_text(frame)
            if detected:
                detected["bbox"] = location.reshape(-1, 2).tolist()
            return detected

        r1, c1 = int(np.min(rows)), int(np.min(cols))
        r2, c2 = int(np.max(rows)), int(np.max(cols))
        box_h = max(1, r2 - r1)
        box_w = max(1, c2 - c1)
        pad = max(
            int(_ANPR_CONFIG.get("contour_pad_min", 18)),
            int(float(_ANPR_CONFIG.get("contour_pad_ratio", 0.15)) * max(box_h, box_w)),
        )
        r1 = max(0, r1 - pad)
        c1 = max(0, c1 - pad)
        r2 = min(frame.shape[0] - 1, r2 + pad)
        c2 = min(frame.shape[1] - 1, c2 + pad)
        cropped_image = frame[r1:r2 + 1, c1:c2 + 1]

    detected = read_plate_text(cropped_image)
    if detected:
        detected["bbox"] = location.reshape(-1, 2).tolist()
        return detected
    detected = read_plate_text(frame)
    if detected:
        detected["bbox"] = location.reshape(-1, 2).tolist()
    return detected
