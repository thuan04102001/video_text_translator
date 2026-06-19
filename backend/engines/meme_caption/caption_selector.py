import re
from typing import Dict, List, Optional, Set


def get_item_final_score(item: Dict) -> float:
    score = item.get("score") or {}

    try:
        return float(score.get("final_score", 0.0))
    except Exception:
        return 0.0


def get_item_confidence(item: Dict) -> float:
    try:
        return float(item.get("confidence", 0.0))
    except Exception:
        return 0.0


def get_item_text(item: Dict) -> str:
    return str(item.get("text") or "").strip()


def get_item_normalized_text(item: Dict) -> str:
    return str(item.get("normalized_text") or "").strip()


def item_token_set(item: Dict) -> Set[str]:
    return {
        token.strip(".,!?;:\"'()[]{}=").lower()
        for token in get_item_normalized_text(item).split()
        if token.strip(".,!?;:\"'()[]{}=")
    }


def item_token_similarity(item_a: Dict, item_b: Dict) -> float:
    tokens_a = item_token_set(item_a)
    tokens_b = item_token_set(item_b)

    if not tokens_a or not tokens_b:
        return 0.0

    return len(tokens_a & tokens_b) / max(1, len(tokens_a | tokens_b))


def get_item_box(item: Dict) -> List[int]:
    box = item.get("box") or [0, 0, 0, 0]

    if len(box) != 4:
        return [0, 0, 0, 0]

    return [
        int(box[0]),
        int(box[1]),
        int(box[2]),
        int(box[3]),
    ]


def get_box_width(box: List[int]) -> int:
    return max(0, box[2] - box[0])


def get_box_height(box: List[int]) -> int:
    return max(0, box[3] - box[1])


def get_box_area(box: List[int]) -> int:
    return get_box_width(box) * get_box_height(box)


def get_box_center(box: List[int]) -> Dict:
    return {
        "x": (box[0] + box[2]) / 2,
        "y": (box[1] + box[3]) / 2,
    }


def merge_boxes(boxes: List[List[int]]) -> List[int]:
    valid_boxes = [
        box
        for box in boxes
        if box and len(box) == 4 and box[2] > box[0] and box[3] > box[1]
    ]

    if not valid_boxes:
        return [0, 0, 0, 0]

    x1 = min(box[0] for box in valid_boxes)
    y1 = min(box[1] for box in valid_boxes)
    x2 = max(box[2] for box in valid_boxes)
    y2 = max(box[3] for box in valid_boxes)

    return [x1, y1, x2, y2]


def get_vertical_gap(box_a: List[int], box_b: List[int]) -> int:
    if box_a[3] < box_b[1]:
        return box_b[1] - box_a[3]

    if box_b[3] < box_a[1]:
        return box_a[1] - box_b[3]

    return 0


def get_horizontal_gap(box_a: List[int], box_b: List[int]) -> int:
    if box_a[2] < box_b[0]:
        return box_b[0] - box_a[2]

    if box_b[2] < box_a[0]:
        return box_a[0] - box_b[2]

    return 0


def get_horizontal_overlap_ratio(box_a: List[int], box_b: List[int]) -> float:
    left = max(box_a[0], box_b[0])
    right = min(box_a[2], box_b[2])

    overlap = max(0, right - left)
    min_width = max(1, min(get_box_width(box_a), get_box_width(box_b)))

    return overlap / min_width


def get_vertical_overlap_ratio(box_a: List[int], box_b: List[int]) -> float:
    top = max(box_a[1], box_b[1])
    bottom = min(box_a[3], box_b[3])

    overlap = max(0, bottom - top)
    min_height = max(1, min(get_box_height(box_a), get_box_height(box_b)))

    return overlap / min_height


def has_header_marker(text: str) -> bool:
    text = (text or "").strip()

    if not text:
        return False

    if text.endswith(":"):
        return True

    lowered = text.lower()

    known_header_prefixes = [
        "pov:",
        "me when:",
        "boys when:",
        "girls when:",
        "women when:",
        "men when:",
        "woman's logic:",
        "women's logic:",
        "man's logic:",
        "dad:",
        "mom:",
    ]

    return any(lowered.startswith(prefix) for prefix in known_header_prefixes)


def is_template_caption_line(item: Dict) -> bool:
    """
    Caption dòng đầu có dạng template nhưng phải merge với entity line.

    Ví dụ:
    POV: Typical salary in
    United States

    Đây không phải header-only.
    """

    text = get_item_text(item)
    normalized_text = get_item_normalized_text(item)
    words = normalized_text.split()

    if not text or not normalized_text:
        return False

    lowered = text.lower()

    if not lowered.startswith("pov:"):
        return False

    if len(words) <= 2:
        return False

    return True


def is_short_header_text(item: Dict) -> bool:
    """
    Chỉ kiểm tra text có dáng header ngắn.
    Chưa quyết định header-only ở đây.
    """

    text = get_item_text(item)
    normalized_text = get_item_normalized_text(item)
    words = normalized_text.split()

    if not text or not normalized_text:
        return False

    if not has_header_marker(text):
        return False

    if len(words) > 5:
        return False

    if is_template_caption_line(item):
        return False

    box = get_item_box(item)
    height = get_box_height(box)
    width = get_box_width(box)

    if width <= 0 or height <= 0:
        return False

    confidence = get_item_confidence(item)
    final_score = get_item_final_score(item)

    if confidence >= 0.68 and final_score >= 0.82:
        return True

    if confidence >= 0.6 and final_score >= 0.88:
        return True

    return False


def has_strong_lines_above(
    item: Dict,
    qualified_items: List[Dict],
    frame_height: int,
) -> bool:
    """
    Nếu phía trên còn line mạnh gần cùng vùng caption,
    item hiện tại không được xem là header.

    Fix:
    and it crawl back in:
    every note of that smell:
    his son to rear:
    """

    item_box = get_item_box(item)

    if item_box == [0, 0, 0, 0]:
        return False

    above_items = []

    for other in qualified_items:
        if other is item:
            continue

        other_box = get_item_box(other)

        if other_box == [0, 0, 0, 0]:
            continue

        other_is_above = other_box[3] <= item_box[1]

        if not other_is_above:
            continue

        vertical_gap = get_vertical_gap(other_box, item_box)
        close_enough = vertical_gap <= frame_height * 0.18
        strong_enough = get_item_final_score(other) >= 0.78

        if close_enough and strong_enough:
            above_items.append(other)

    return len(above_items) >= 1


def is_leading_header_position(
    item: Dict,
    qualified_items: List[Dict],
    frame_height: int,
) -> bool:
    if has_strong_lines_above(
        item=item,
        qualified_items=qualified_items,
        frame_height=frame_height,
    ):
        return False

    return True


def is_structural_header_caption(
    item: Dict,
    qualified_items: List[Dict],
    frame_height: int,
) -> bool:
    """
    Header thật = text giống header + vị trí giống header.

    Không còn dùng rule thô:
    text.endswith(":") => header
    """

    if not is_short_header_text(item):
        return False

    if not is_leading_header_position(
        item=item,
        qualified_items=qualified_items,
        frame_height=frame_height,
    ):
        return False

    return True


def is_joinable_context_header(item: Dict) -> bool:
    """
    Header ngữ cảnh ngắn vẫn là một phần của caption chính.

    Case thường gặp:
    POV:
    bro gave you info

    Không áp dụng cho character labels như Me:, Dad:, ChatGPT: vì các label đó
    là thành phần meme riêng, không phải title caption cần dịch.
    """

    text = get_item_text(item).strip().lower()

    return text in {
        "pov:",
    }


def is_standalone_phase_label(item: Dict) -> bool:
    text = get_item_text(item).strip().lower()
    text = re.sub(r"\s+", " ", text)
    normalized = text.rstrip(":;?.! ")

    return normalized in {
        "falling",
        "in movies",
        "in movie",
        "in moves",
        "in reality",
        "in real life",
    }


def should_keep_header_separate(
    anchor_item: Dict,
    current_item: Dict,
    qualified_items: List[Dict],
    frame_height: int,
) -> bool:
    """
    Tách dynamic content bên dưới khỏi structural header.

    Case:
    Boys when:
    Car for 40ks / PC for 3ks

    Case:
    Woman's logic:
    Restaurants / Travels / Rent
    """

    if is_standalone_phase_label(anchor_item) or is_standalone_phase_label(current_item):
        return True

    if not is_structural_header_caption(
        item=anchor_item,
        qualified_items=qualified_items,
        frame_height=frame_height,
    ):
        return False

    if is_joinable_context_header(anchor_item):
        return False

    anchor_box = get_item_box(anchor_item)
    current_box = get_item_box(current_item)

    if current_box[1] <= anchor_box[1]:
        return False

    vertical_gap = get_vertical_gap(anchor_box, current_box)
    clear_gap = max(10, int(frame_height * 0.008))

    if vertical_gap >= clear_gap:
        return True

    return False


def is_same_caption_line_group(
    current_item: Dict,
    anchor_item: Dict,
    qualified_items: List[Dict],
    frame_width: int,
    frame_height: int,
    max_vertical_gap_ratio: float = 0.035,
    max_center_x_gap_ratio: float = 0.26,
    min_horizontal_overlap: float = 0.28,
) -> bool:
    """
    Kiểm tra 2 OCR item có cùng caption block trong 1 frame không.

    Chỉ frame-level.
    Không timeline.
    Không dịch.
    Không render.
    """

    if should_keep_header_separate(
        anchor_item=anchor_item,
        current_item=current_item,
        qualified_items=qualified_items,
        frame_height=frame_height,
    ):
        return False

    current_box = get_item_box(current_item)
    anchor_box = get_item_box(anchor_item)

    if current_box == [0, 0, 0, 0] or anchor_box == [0, 0, 0, 0]:
        return False

    current_center = get_box_center(current_box)
    anchor_center = get_box_center(anchor_box)

    vertical_gap = get_vertical_gap(current_box, anchor_box)
    center_x_gap = abs(current_center["x"] - anchor_center["x"])
    horizontal_overlap = get_horizontal_overlap_ratio(current_box, anchor_box)

    max_vertical_gap = frame_height * max_vertical_gap_ratio
    max_center_x_gap = frame_width * max_center_x_gap_ratio

    if vertical_gap <= max_vertical_gap and horizontal_overlap >= min_horizontal_overlap:
        return True

    if vertical_gap <= max_vertical_gap and center_x_gap <= max_center_x_gap:
        return True

    if is_joinable_context_header(anchor_item) and current_box[1] >= anchor_box[1]:
        relaxed_vertical_gap = frame_height * 0.12
        relaxed_center_gap = frame_width * 0.34

        if (
            vertical_gap <= relaxed_vertical_gap
            and center_x_gap <= relaxed_center_gap
            and horizontal_overlap >= 0.08
        ):
            return True

    return False


def item_identity(item: Dict) -> int:
    return id(item)


def choose_seed_order(
    qualified_items: List[Dict],
    frame_height: int,
) -> List[Dict]:
    """
    Multi-region selector cần duyệt nhiều seed.

    Ưu tiên:
    1. structural header thật
    2. score cao
    3. vị trí từ trên xuống

    Không còn chỉ chọn 1 anchor duy nhất.
    """

    def sort_key(item: Dict):
        box = get_item_box(item)
        header_bonus = 1 if is_structural_header_caption(
            item=item,
            qualified_items=qualified_items,
            frame_height=frame_height,
        ) else 0

        return (
            -header_bonus,
            -get_item_final_score(item),
            box[1],
            box[0],
        )

    return sorted(qualified_items, key=sort_key)


def build_connected_caption_lines(
    anchor_item: Dict,
    qualified_items: List[Dict],
    frame_width: int,
    frame_height: int,
    max_lines: int = 8,
    blocked_item_ids: Optional[Set[int]] = None,
) -> List[Dict]:
    """
    Gom caption line theo connected block.

    Vẫn giữ:
    - caption 5 dòng thật
    - caption 2 dòng template + entity

    Nhưng tách:
    - structural header + dynamic content bên dưới
    """

    if blocked_item_ids is None:
        blocked_item_ids = set()

    selected_items = [anchor_item]

    if is_standalone_phase_label(anchor_item):
        return selected_items

    if is_structural_header_caption(
        item=anchor_item,
        qualified_items=qualified_items,
        frame_height=frame_height,
    ) and not is_joinable_context_header(anchor_item):
        return selected_items

    remaining_items = [
        item
        for item in qualified_items
        if item is not anchor_item
        and item_identity(item) not in blocked_item_ids
    ]

    changed = True

    while changed:
        changed = False

        for item in list(remaining_items):
            belongs_to_block = False

            for selected_item in selected_items:
                if is_same_caption_line_group(
                    current_item=item,
                    anchor_item=selected_item,
                    qualified_items=qualified_items,
                    frame_width=frame_width,
                    frame_height=frame_height,
                ):
                    belongs_to_block = True
                    break

            if belongs_to_block:
                selected_items.append(item)
                remaining_items.remove(item)
                changed = True

            if len(selected_items) >= max_lines:
                break

    selected_items = sorted(
        selected_items,
        key=lambda item: (
            get_item_box(item)[1],
            get_item_box(item)[0],
        ),
    )

    return selected_items[:max_lines]


def dedupe_source_items_for_candidate(items: List[Dict]) -> List[Dict]:
    kept: List[Dict] = []

    for item in sorted(
        items,
        key=lambda value: (
            -get_item_final_score(value),
            -get_item_confidence(value),
        ),
    ):
        box = get_item_box(item)
        duplicate = False

        for kept_item in kept:
            kept_box = get_item_box(kept_item)
            horizontal_overlap = get_horizontal_overlap_ratio(box, kept_box)
            vertical_overlap = get_vertical_overlap_ratio(box, kept_box)

            if horizontal_overlap < 0.72 or vertical_overlap < 0.72:
                continue

            if item_token_similarity(item, kept_item) < 0.55:
                continue

            duplicate = True
            break

        if not duplicate:
            kept.append(item)

    return sorted(
        kept,
        key=lambda value: (
            get_item_box(value)[1],
            get_item_box(value)[0],
        ),
    )


def build_frame_caption_candidate(
    frame: Dict,
    items: List[Dict],
    qualified_items: List[Dict],
    frame_height: int,
    region_index: int = 1,
) -> Optional[Dict]:
    if not items:
        return None

    items = dedupe_source_items_for_candidate(items)

    ordered_items = sorted(
        items,
        key=lambda item: (
            get_item_box(item)[1],
            get_item_box(item)[0],
        ),
    )

    text_parts = []
    normalized_parts = []
    boxes = []
    confidences = []
    final_scores = []

    for item in ordered_items:
        text = get_item_text(item)
        normalized_text = get_item_normalized_text(item)

        if not text:
            continue

        text_parts.append(text)

        if normalized_text:
            normalized_parts.append(normalized_text)

        boxes.append(get_item_box(item))
        confidences.append(get_item_confidence(item))
        final_scores.append(get_item_final_score(item))

    if not text_parts:
        return None

    text = " ".join(text_parts).strip()
    normalized_text = " ".join(normalized_parts).strip()
    box = merge_boxes(boxes)

    avg_confidence = (
        sum(confidences) / len(confidences)
        if confidences
        else 0.0
    )

    avg_score = (
        sum(final_scores) / len(final_scores)
        if final_scores
        else 0.0
    )

    best_item = max(
        items,
        key=get_item_final_score,
    )

    header_only = (
        len(items) == 1
        and is_structural_header_caption(
            item=items[0],
            qualified_items=qualified_items,
            frame_height=frame_height,
        )
    )

    return {
        "sample_index": frame.get("sample_index"),
        "time": frame.get("time"),
        "frame_index": frame.get("frame_index"),
        "image_path": frame.get("image_path"),
        "region_index": region_index,
        "text": text,
        "normalized_text": normalized_text,
        "box": box,
        "confidence": round(avg_confidence, 4),
        "score": {
            "final_score": round(avg_score, 4),
            "line_count": len(text_parts),
            "source": "caption_selector",
            "header_only": header_only,
            "region_index": region_index,
        },
        "source_items": items,
        "best_item": best_item,
    }


def is_candidate_too_small_or_noisy(
    candidate: Dict,
    frame_width: int,
    frame_height: int,
) -> bool:
    """
    Loại candidate quá nhỏ/noisy ở frame-level.

    Không dựa vào text cụ thể.
    """

    box = get_item_box(candidate)
    text = get_item_text(candidate)

    if not text:
        return True

    width = get_box_width(box)
    height = get_box_height(box)

    if width < frame_width * 0.08:
        return True

    if height < frame_height * 0.018:
        return True

    score = candidate.get("score") or {}
    final_score = float(score.get("final_score", 0.0) or 0.0)

    if final_score < 0.55:
        return True

    return False


def candidates_overlap_too_much(
    candidate_a: Dict,
    candidate_b: Dict,
) -> bool:
    box_a = get_item_box(candidate_a)
    box_b = get_item_box(candidate_b)

    if box_a == [0, 0, 0, 0] or box_b == [0, 0, 0, 0]:
        return False

    horizontal_overlap = get_horizontal_overlap_ratio(box_a, box_b)
    vertical_overlap = get_vertical_overlap_ratio(box_a, box_b)

    if horizontal_overlap >= 0.75 and vertical_overlap >= 0.75:
        return True

    return False


def dedupe_frame_candidates(candidates: List[Dict]) -> List[Dict]:
    """
    Tránh duplicate candidate trong cùng frame.

    Nếu 2 candidate overlap quá mạnh, giữ candidate:
    - nhiều line hơn
    - score cao hơn
    - confidence cao hơn
    """

    kept: List[Dict] = []

    for candidate in sorted(
        candidates,
        key=lambda item: (
            -(item.get("score") or {}).get("line_count", 0),
            -(item.get("score") or {}).get("final_score", 0.0),
            -float(item.get("confidence") or 0.0),
        ),
    ):
        duplicate = False

        for kept_candidate in kept:
            if candidates_overlap_too_much(candidate, kept_candidate):
                duplicate = True
                break

        if not duplicate:
            kept.append(candidate)

    kept = sorted(
        kept,
        key=lambda item: (
            get_item_box(item)[1],
            get_item_box(item)[0],
        ),
    )

    return kept


def select_caption_candidates_from_frame(
    frame: Dict,
    frame_width: int,
    frame_height: int,
    min_score: float = 0.55,
    max_lines: int = 8,
    max_regions: int = 4,
) -> List[Dict]:
    """
    Multi-region frame selector.

    Logic mới:
    1 frame có thể sinh nhiều caption candidates.

    Điều này chuẩn bị cho:
    - 2 vùng caption cùng lúc
    - header + content region
    - multi-caption layout

    Nhưng vẫn giữ filter để không lấy watermark/noise.
    """

    items = frame.get("items", [])

    if not items:
        return []

    qualified_items = [
        item
        for item in items
        if get_item_final_score(item) >= min_score
    ]

    if not qualified_items:
        return []

    seed_items = choose_seed_order(
        qualified_items=qualified_items,
        frame_height=frame_height,
    )

    used_item_ids: Set[int] = set()
    candidates: List[Dict] = []
    region_index = 1

    for seed_item in seed_items:
        seed_id = item_identity(seed_item)

        if seed_id in used_item_ids:
            continue

        group_items = build_connected_caption_lines(
            anchor_item=seed_item,
            qualified_items=qualified_items,
            frame_width=frame_width,
            frame_height=frame_height,
            max_lines=max_lines,
            blocked_item_ids=used_item_ids,
        )

        if not group_items:
            continue

        candidate = build_frame_caption_candidate(
            frame=frame,
            items=group_items,
            qualified_items=qualified_items,
            frame_height=frame_height,
            region_index=region_index,
        )

        if not candidate:
            continue

        if is_candidate_too_small_or_noisy(
            candidate=candidate,
            frame_width=frame_width,
            frame_height=frame_height,
        ):
            continue

        candidates.append(candidate)

        for item in group_items:
            used_item_ids.add(item_identity(item))

        region_index += 1

        if len(candidates) >= max_regions:
            break

    return dedupe_frame_candidates(candidates)


def select_caption_candidate_from_frame(
    frame: Dict,
    frame_width: int,
    frame_height: int,
    min_score: float = 0.55,
    max_lines: int = 8,
) -> Optional[Dict]:
    """
    Backward-compatible single candidate API.

    Giữ lại để không phá code cũ.
    """

    candidates = select_caption_candidates_from_frame(
        frame=frame,
        frame_width=frame_width,
        frame_height=frame_height,
        min_score=min_score,
        max_lines=max_lines,
        max_regions=4,
    )

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda candidate: (
            (candidate.get("score") or {}).get("line_count", 0),
            (candidate.get("score") or {}).get("final_score", 0.0),
            float(candidate.get("confidence") or 0.0),
        ),
    )


def select_caption_candidates_from_scored_frames(
    scored_ocr_result: Dict,
    frame_width: int,
    frame_height: int,
    min_score: float = 0.55,
) -> Dict:
    frames = scored_ocr_result.get("frames", [])

    candidates = []
    frame_candidate_counts = []

    for frame in frames:
        frame_candidates = select_caption_candidates_from_frame(
            frame=frame,
            frame_width=frame_width,
            frame_height=frame_height,
            min_score=min_score,
            max_regions=4,
        )

        frame_candidate_counts.append(
            {
                "sample_index": frame.get("sample_index"),
                "time": frame.get("time"),
                "candidate_count": len(frame_candidates),
            }
        )

        candidates.extend(frame_candidates)

    return {
        "frame_count": len(frames),
        "candidate_count": len(candidates),
        "frame_candidate_counts": frame_candidate_counts,
        "candidates": candidates,
    }
