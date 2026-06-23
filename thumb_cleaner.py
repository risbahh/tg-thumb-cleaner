"""
thumb_cleaner.py — Remove text watermarks from video thumbnail images.

Pipeline:
  1. EasyOCR detects all text bounding boxes in the image
  2. A mask is drawn over detected text regions
  3. cv2.inpaint (TELEA algorithm) fills in the masked areas
  4. Result is saved as JPEG ≤ 200KB (Telegram thumbnail limit)

No GPU required — runs on CPU. First run downloads the EasyOCR model (~100 MB).
"""
import logging
import os
import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_reader = None


def _get_reader():
    """Lazy-load EasyOCR reader (downloads model on first call)."""
    global _reader
    if _reader is None:
        import easyocr
        _reader = easyocr.Reader(['en'], gpu=False, verbose=False)
        logger.info("✅ EasyOCR model ready (CPU mode)")
    return _reader


def remove_watermark(input_path: str, output_path: str) -> str:
    """
    Detect and remove text watermarks from a thumbnail image.

    Args:
        input_path:  path to original thumbnail JPEG
        output_path: path to write the cleaned JPEG

    Returns:
        output_path (cleaned), or input_path if processing failed
    """
    img = cv2.imread(input_path)
    if img is None:
        logger.error(f"Cannot read image: {input_path}")
        return input_path

    h, w = img.shape[:2]
    reader = _get_reader()

    # Detect text
    try:
        detections = reader.readtext(input_path, detail=1)
    except Exception as e:
        logger.warning(f"OCR failed: {e} — returning original")
        cv2.imwrite(output_path, img)
        return output_path

    if not detections:
        logger.debug("No text detected in thumbnail")
        cv2.imwrite(output_path, img)
        return output_path

    # Build inpaint mask from detected bounding boxes
    mask = np.zeros((h, w), dtype=np.uint8)
    found = []

    for (bbox, text, conf) in detections:
        if conf < 0.25:
            continue
        pts = np.array(bbox, dtype=np.int32)
        x_min = max(0, int(pts[:, 0].min()) - 6)
        x_max = min(w, int(pts[:, 0].max()) + 6)
        y_min = max(0, int(pts[:, 1].min()) - 6)
        y_max = min(h, int(pts[:, 1].max()) + 6)
        mask[y_min:y_max, x_min:x_max] = 255
        found.append(f"'{text}' @ ({x_min},{y_min})-({x_max},{y_max}) conf={conf:.2f}")

    logger.info(f"Detected {len(found)} text region(s): {found}")

    if mask.sum() == 0:
        cv2.imwrite(output_path, img)
        return output_path

    # Dilate mask slightly to catch anti-aliased edges
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask = cv2.dilate(mask, kernel, iterations=2)

    # Inpaint
    cleaned = cv2.inpaint(img, mask, inpaintRadius=5, flags=cv2.INPAINT_TELEA)

    # Save as JPEG ≤ 200 KB
    quality = 90
    while True:
        cv2.imwrite(output_path, cleaned, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if os.path.getsize(output_path) <= 200 * 1024 or quality <= 20:
            break
        quality -= 10

    size_kb = os.path.getsize(output_path) // 1024
    logger.info(f"Cleaned thumb saved: {output_path} ({size_kb} KB, quality={quality})")
    return output_path


def resize_thumb(path: str) -> str:
    """Ensure thumbnail is within Telegram's 320×320 limit."""
    img = Image.open(path)
    if img.mode != "RGB":
        img = img.convert("RGB")  # JPEG save fails on RGBA/palette images
    img.thumbnail((320, 320), Image.LANCZOS)
    img.save(path, "JPEG", quality=85)
    return path
