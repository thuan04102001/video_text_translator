from typing import Dict, List


def clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return max(min_value, min(max_value, value))


def get_box_size_score(box: List[int], frame_width: int, frame_height: int) -> float:
    """
    Chấm điểm kích thước box.

    Caption meme chính thường:
    - không quá nhỏ
    - không quá to toàn màn
    - width tương đối lớn
    - height vừa phải
    """

    if not box or len(box) != 4:
        return 0.0

    x1, y1, x2, y2 = box

    box_width = max(0, x2 - x1)
    box_height = max(0, y2 - y1)

    if frame_width <= 0 or frame_height <= 0:
        return 0.0

    width_ratio = box_width / frame_width
    height_ratio = box_height / frame_height

    score = 0.0

    if 0.25 <= width_ratio <= 0.92:
        score += 0.45
    elif 0.15 <= width_ratio < 0.25:
        score += 0.25
    elif 0.92 < width_ratio <= 0.98:
        score += 0.2

    if 0.025 <= height_ratio <= 0.18:
        score += 0.4
    elif 0.018 <= height_ratio < 0.025:
        score += 0.2
    elif 0.18 < height_ratio <= 0.28:
        score += 0.18

    area_ratio = (box_width * box_height) / (frame_width * frame_height)

    if 0.008 <= area_ratio <= 0.18:
        score += 0.15

    return clamp(score)


def get_position_score(box: List[int], frame_width: int, frame_height: int) -> float:
    """
    Caption meme thường nằm vùng trung tâm trên/dưới,
    ít khi là text nhỏ sát góc.
    """

    if not box or len(box) != 4:
        return 0.0

    x1, y1, x2, y2 = box

    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2

    if frame_width <= 0 or frame_height <= 0:
        return 0.0

    x_ratio = cx / frame_width
    y_ratio = cy / frame_height

    score = 0.0

    if 0.18 <= x_ratio <= 0.82:
        score += 0.45

    if 0.08 <= y_ratio <= 0.72:
        score += 0.45
    elif 0.72 < y_ratio <= 0.9:
        score += 0.25

    if x_ratio < 0.08 or x_ratio > 0.92:
        score -= 0.25

    if y_ratio < 0.03 or y_ratio > 0.95:
        score -= 0.25

    return clamp(score)


def get_text_quality_score(text: str, normalized_text: str = "") -> float:
    """
    Chấm chất lượng text OCR.

    Chỉ scoring.
    Không sửa text.
    Không detect final.
    """

    text = (text or "").strip()
    normalized_text = (normalized_text or text).strip()

    if not text or not normalized_text:
        return 0.0

    score = 0.0

    length = len(text)

    if 4 <= length <= 120:
        score += 0.35
    elif 121 <= length <= 220:
        score += 0.18
    elif length > 220:
        score -= 0.25

    words = normalized_text.split()

    if 2 <= len(words) <= 28:
        score += 0.35
    elif len(words) == 1:
        score += 0.1
    elif len(words) > 28:
        score -= 0.2

    alpha_count = sum(ch.isalpha() for ch in text)
    digit_count = sum(ch.isdigit() for ch in text)

    if alpha_count >= 3:
        score += 0.2

    if digit_count > 0 and alpha_count == 0:
        score += 0.08

    weird_chars = sum(
        1
        for ch in text
        if not ch.isalnum() and not ch.isspace() and ch not in ".,!?':;-()[]/%"
    )

    if weird_chars >= 3:
        score -= 0.25

    return clamp(score)


def get_confidence_score(confidence: float) -> float:
    try:
        confidence = float(confidence)
    except Exception:
        return 0.0

    return clamp(confidence)


def get_noise_penalty(item: Dict, frame_width: int, frame_height: int) -> float:
    """
    Phạt text có khả năng là noise.

    Lưu ý:
    - penalty chỉ là điểm
    - không loại bỏ item tại đây
    """

    text = (item.get("text") or "").strip()
    normalized_text = (item.get("normalized_text") or "").strip()
    box = item.get("box") or [0, 0, 0, 0]

    penalty = 0.0

    x1, y1, x2, y2 = box

    box_width = max(0, x2 - x1)
    box_height = max(0, y2 - y1)

    if frame_width > 0 and frame_height > 0:
        width_ratio = box_width / frame_width
        height_ratio = box_height / frame_height

        if width_ratio < 0.12:
            penalty += 0.2

        if height_ratio < 0.014:
            penalty += 0.25

        if width_ratio > 0.98:
            penalty += 0.2

        if height_ratio > 0.35:
            penalty += 0.35

        if x1 < frame_width * 0.03 or x2 > frame_width * 0.97:
            penalty += 0.08

        if y1 < frame_height * 0.02 or y2 > frame_height * 0.97:
            penalty += 0.12

    if len(text) <= 1:
        penalty += 0.5

    if len(normalized_text.split()) > 35:
        penalty += 0.35

    lower_text = normalized_text.lower()

    noise_keywords = [
        "follow",
        "subscribe",
        "like",
        "share",
        "comment",
        "tiktok",
        "facebook",
        "instagram",
        "youtube",
        "capcut",
        "template",
        "watermark",
    ]

    if any(keyword in lower_text for keyword in noise_keywords):
        penalty += 0.25

    return clamp(penalty)


def score_ocr_item(
    item: Dict,
    frame_width: int,
    frame_height: int,
) -> Dict:
    """
    Chấm điểm 1 OCR item.

    Input:
    OCR item đã clean.

    Output:
    item + score object.

    Rule:
    - scorer chỉ chấm điểm
    - không chọn caption chính
    - không group timeline
    - không dịch
    - không render
    """

    box = item.get("box") or [0, 0, 0, 0]
    text = item.get("text") or ""
    normalized_text = item.get("normalized_text") or ""
    confidence = item.get("confidence", 0.0)

    text_quality_score = get_text_quality_score(
        text=text,
        normalized_text=normalized_text,
    )

    size_score = get_box_size_score(
        box=box,
        frame_width=frame_width,
        frame_height=frame_height,
    )

    position_score = get_position_score(
        box=box,
        frame_width=frame_width,
        frame_height=frame_height,
    )

    confidence_score = get_confidence_score(confidence)

    noise_penalty = get_noise_penalty(
        item=item,
        frame_width=frame_width,
        frame_height=frame_height,
    )

    final_score = (
        text_quality_score * 0.35
        + size_score * 0.25
        + position_score * 0.2
        + confidence_score * 0.2
        - noise_penalty * 0.4
    )

    final_score = clamp(final_score)

    return {
        **item,
        "score": {
            "text_quality_score": round(text_quality_score, 4),
            "size_score": round(size_score, 4),
            "position_score": round(position_score, 4),
            "confidence_score": round(confidence_score, 4),
            "noise_penalty": round(noise_penalty, 4),
            "final_score": round(final_score, 4),
        },
    }


def score_frame_ocr_items(
    frame: Dict,
    frame_width: int,
    frame_height: int,
) -> Dict:
    items = frame.get("items", [])

    scored_items = []

    for item in items:
        scored_items.append(
            score_ocr_item(
                item=item,
                frame_width=frame_width,
                frame_height=frame_height,
            )
        )

    scored_items.sort(
        key=lambda item: item["score"]["final_score"],
        reverse=True,
    )

    return {
        **frame,
        "items": scored_items,
        "scored_count": len(scored_items),
    }


def score_sampled_frames_ocr(
    ocr_result: Dict,
    frame_width: int,
    frame_height: int,
) -> Dict:
    frames = ocr_result.get("frames", [])

    scored_frames = []

    for frame in frames:
        scored_frames.append(
            score_frame_ocr_items(
                frame=frame,
                frame_width=frame_width,
                frame_height=frame_height,
            )
        )

    return {
        **ocr_result,
        "frames": scored_frames,
    }