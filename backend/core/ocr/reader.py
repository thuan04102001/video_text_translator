import os
import re
from typing import Any, Dict, List, Optional

import easyocr


_READER_CACHE = {}


def build_compatible_language_groups(
    languages: Optional[List[str]] = None,
) -> List[List[str]]:
    if languages is None:
        languages = ["en"]

    cleaned = {
        str(language or "").strip()
        for language in languages
        if str(language or "").strip()
    }

    if not cleaned:
        cleaned = {"en"}

    if "auto" in {language.lower() for language in cleaned}:
        cleaned = {"en", "es", "pt", "ru", "ch_sim"}

    groups = []
    latin_group = [
        language
        for language in ["en", "es", "pt"]
        if language in cleaned
    ]

    if latin_group:
        groups.append(latin_group)

    if "ru" in cleaned:
        groups.append(["ru", "en"])

    if "ch_sim" in cleaned:
        groups.append(["ch_sim", "en"])

    if "th" in cleaned:
        groups.append(["th", "en"])

    for language in sorted(cleaned):
        if language in {"en", "es", "pt", "ru", "ch_sim", "th"}:
            continue

        groups.append([language, "en"] if language != "en" else ["en"])

    if not groups:
        groups.append(["en"])

    unique_groups = []
    seen = set()

    for group in groups:
        key = tuple(group)

        if key in seen:
            continue

        seen.add(key)
        unique_groups.append(group)

    return unique_groups


def to_python_value(value: Any):
    """
    Convert numpy / EasyOCR values về Python native type
    để FastAPI serialize JSON không bị lỗi.

    Ví dụ:
    numpy.int32 -> int
    numpy.float32 -> float
    list numpy -> list python
    """

    if hasattr(value, "item"):
        return value.item()

    if isinstance(value, list):
        return [to_python_value(item) for item in value]

    if isinstance(value, tuple):
        return [to_python_value(item) for item in value]

    return value


def get_easyocr_reader(
    languages: Optional[List[str]] = None,
    gpu: bool = False,
):
    """
    OCR reader cache.

    Rule:
    - reader.py chỉ OCR ảnh/frame
    - không detect caption chính
    - không build timeline
    - không dịch
    - không render
    """

    if languages is None:
        languages = ["en"]

    cache_key = f"{','.join(languages)}|gpu={gpu}"

    if cache_key not in _READER_CACHE:
        _READER_CACHE[cache_key] = easyocr.Reader(
            languages,
            gpu=gpu,
            verbose=False,
        )

    return _READER_CACHE[cache_key]


def normalize_ocr_box(raw_box) -> List[int]:
    """
    EasyOCR trả box dạng 4 điểm:
    [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]

    Chuẩn hóa về:
    [x1, y1, x2, y2]
    """

    safe_box = to_python_value(raw_box)

    xs = [float(point[0]) for point in safe_box]
    ys = [float(point[1]) for point in safe_box]

    return [
        int(min(xs)),
        int(min(ys)),
        int(max(xs)),
        int(max(ys)),
    ]


def normalize_raw_box(raw_box) -> List[List[float]]:
    """
    Chuẩn hóa raw_box để trả JSON an toàn.
    Không giữ numpy.int32/numpy.float32.
    """

    safe_box = to_python_value(raw_box)

    normalized = []

    for point in safe_box:
        normalized.append(
            [
                float(point[0]),
                float(point[1]),
            ]
        )

    return normalized


def box_overlap_ratio(box_a: List[int], box_b: List[int]) -> float:
    left = max(box_a[0], box_b[0])
    top = max(box_a[1], box_b[1])
    right = min(box_a[2], box_b[2])
    bottom = min(box_a[3], box_b[3])

    overlap = max(0, right - left) * max(0, bottom - top)
    area_a = max(1, (box_a[2] - box_a[0]) * (box_a[3] - box_a[1]))
    area_b = max(1, (box_b[2] - box_b[0]) * (box_b[3] - box_b[1]))

    return overlap / max(1, min(area_a, area_b))


def dedupe_ocr_items(items: List[Dict]) -> List[Dict]:
    kept = []

    for item in sorted(
        items,
        key=lambda value: (
            -float(value.get("confidence", 0.0) or 0.0),
            -(value.get("box", [0, 0, 0, 0])[2] - value.get("box", [0, 0, 0, 0])[0]),
        ),
    ):
        box = item.get("box") or [0, 0, 0, 0]
        text = str(item.get("text") or "").strip().lower()
        duplicate = False

        for kept_item in kept:
            kept_box = kept_item.get("box") or [0, 0, 0, 0]
            kept_text = str(kept_item.get("text") or "").strip().lower()

            if box_overlap_ratio(box, kept_box) < 0.78:
                continue

            if text == kept_text or text in kept_text or kept_text in text:
                duplicate = True
                break

        if not duplicate:
            kept.append(item)

    return sorted(
        kept,
        key=lambda value: (
            value.get("box", [0, 0, 0, 0])[1],
            value.get("box", [0, 0, 0, 0])[0],
        ),
    )


def keep_text_for_language_group(text: str, language_group: List[str]) -> bool:
    value = str(text or "").strip()

    if not value:
        return False

    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", value))
    cyrillic_count = len(re.findall(r"[\u0400-\u04ff]", value))
    latin_count = len(re.findall(r"[A-Za-z]", value))

    if "ch_sim" in language_group:
        return cjk_count >= 2 or (cjk_count >= 1 and cjk_count > latin_count)

    if "ru" in language_group:
        return cyrillic_count >= 2 and cyrillic_count > latin_count

    if "th" in language_group:
        return bool(re.search(r"[\u0e00-\u0e7f]", value))

    return True


def read_image_ocr(
    image_path: str,
    languages: Optional[List[str]] = None,
    gpu: bool = False,
    min_confidence: float = 0.15,
) -> Dict:
    """
    OCR một ảnh.

    Output chuẩn:
    {
        "image_path": "...",
        "items": [
            {
                "text": "...",
                "box": [x1, y1, x2, y2],
                "confidence": 0.93,
                "raw_box": [...]
            }
        ]
    }
    """

    if not image_path:
        raise ValueError("image_path is empty")

    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Image không tồn tại: {image_path}")

    items = []

    for language_group in build_compatible_language_groups(languages):
        reader = get_easyocr_reader(
            languages=language_group,
            gpu=gpu,
        )

        raw_results = reader.readtext(image_path)

        for raw_box, text, confidence in raw_results:
            safe_text = str(text or "").strip()
            safe_confidence = float(to_python_value(confidence))

            if not safe_text:
                continue

            if not keep_text_for_language_group(safe_text, language_group):
                continue

            if safe_confidence < min_confidence:
                continue

            item = {
                "text": safe_text,
                "box": normalize_ocr_box(raw_box),
                "confidence": safe_confidence,
                "raw_box": normalize_raw_box(raw_box),
                "ocr_languages": language_group,
            }

            items.append(item)

    items = dedupe_ocr_items(items)

    return {
        "image_path": str(image_path),
        "count": int(len(items)),
        "items": items,
    }


def read_many_images_ocr(
    image_paths: List[str],
    languages: Optional[List[str]] = None,
    gpu: bool = False,
    min_confidence: float = 0.15,
    max_images: Optional[int] = None,
) -> Dict:
    """
    OCR nhiều ảnh theo danh sách path.

    Rule:
    - chỉ OCR
    - không group text
    - không lọc caption chính
    """

    selected_paths = image_paths

    if max_images is not None:
        selected_paths = image_paths[:max_images]

    results = []
    total_items = 0

    for index, image_path in enumerate(selected_paths):
        result = read_image_ocr(
            image_path=image_path,
            languages=languages,
            gpu=gpu,
            min_confidence=min_confidence,
        )

        results.append(
            {
                "index": int(index),
                **result,
            }
        )

        total_items += int(result["count"])

    return {
        "image_count": int(len(selected_paths)),
        "total_items": int(total_items),
        "results": results,
    }


def read_sampled_frames_ocr(
    samples: List[Dict],
    languages: Optional[List[str]] = None,
    gpu: bool = False,
    min_confidence: float = 0.15,
    max_frames: Optional[int] = None,
    progress_callback=None,
) -> Dict:
    """
    OCR output từ frame_sampler.

    Input sample chuẩn:
    {
        "sample_index": 0,
        "time": 0.0,
        "frame_index": 0,
        "image_path": "..."
    }

    Output giữ lại time/frame_index để detector/timeline dùng sau này.
    """

    selected_samples = samples

    if max_frames is not None:
        selected_samples = samples[:max_frames]

    frame_results = []
    total_items = 0

    sample_count = len(selected_samples)

    for sample_index, sample in enumerate(selected_samples, start=1):
        ocr_result = read_image_ocr(
            image_path=sample["image_path"],
            languages=languages,
            gpu=gpu,
            min_confidence=min_confidence,
        )

        frame_results.append(
            {
                "sample_index": int(sample["sample_index"]),
                "time": float(sample["time"]),
                "frame_index": int(sample["frame_index"]),
                "image_path": str(sample["image_path"]),
                "ocr_count": int(ocr_result["count"]),
                "items": ocr_result["items"],
            }
        )

        total_items += int(ocr_result["count"])

        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "ocr_frames",
                    "frame_index": sample_index,
                    "frame_count": sample_count,
                    "progress": (
                        sample_index / sample_count
                        if sample_count > 0
                        else 1.0
                    ),
                }
            )

    return {
        "frame_count": int(len(selected_samples)),
        "total_ocr_items": int(total_items),
        "frames": frame_results,
    }
