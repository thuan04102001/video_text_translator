from typing import Dict, List


ROLE_MAIN_CAPTION_TEXT = "MAIN_CAPTION_TEXT"
ROLE_SUPPORTING_TEXT = "SUPPORTING_TEXT"
ROLE_CHARACTER_LABEL_TEXT = "CHARACTER_LABEL_TEXT"
ROLE_DOCUMENT_NOISE_TEXT = "DOCUMENT_NOISE_TEXT"
ROLE_NOISE_TEXT = "NOISE_TEXT"


def get_text(timeline: Dict) -> str:
    return str(timeline.get("text") or "").strip()


def get_duration(timeline: Dict) -> float:
    try:
        return float(timeline.get("duration", 0.0) or 0.0)
    except Exception:
        return 0.0


def get_sample_count(timeline: Dict) -> int:
    try:
        return int(timeline.get("sample_count", 0) or 0)
    except Exception:
        return 0


def get_start(timeline: Dict) -> float:
    try:
        return float(timeline.get("start", 0.0) or 0.0)
    except Exception:
        return 0.0


def get_end(timeline: Dict) -> float:
    try:
        return float(timeline.get("end", 0.0) or 0.0)
    except Exception:
        return 0.0


def get_box(timeline: Dict) -> List[int]:
    box = timeline.get("box") or timeline.get("average_box") or [0, 0, 0, 0]

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


def get_box_center_x(box: List[int]) -> float:
    return (box[0] + box[2]) / 2


def get_box_center_y(box: List[int]) -> float:
    return (box[1] + box[3]) / 2


def word_count(text: str) -> int:
    return len((text or "").strip().split())


def char_count(text: str) -> int:
    return len((text or "").strip())


def normalize_text_key(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def canonical_caption_key(text: str) -> str:
    key = normalize_text_key(text).strip("= ")
    compact = key.replace(" ", "")

    if compact in {"inreality:", "inreality"}:
        return "in reality:"

    if compact in {
        "inthemovies3",
        "inthemovies?",
        "inthemovies:",
        "inthefilm3",
        "inthefilm?",
        "inthefilm:",
    }:
        return "in the movies:"

    return key


def compact_text_distance(a: str, b: str) -> int:
    max_len = max(len(a), len(b))
    min_len = min(len(a), len(b))

    if max_len - min_len > 2:
        return max_len

    previous = list(range(len(b) + 1))

    for index_a, char_a in enumerate(a, start=1):
        current = [index_a]

        for index_b, char_b in enumerate(b, start=1):
            insert_cost = current[index_b - 1] + 1
            delete_cost = previous[index_b] + 1
            replace_cost = previous[index_b - 1] + (0 if char_a == char_b else 1)
            current.append(min(insert_cost, delete_cost, replace_cost))

        previous = current

    return previous[-1]


def timeline_coverage_ratio(
    timeline: Dict,
    video_duration: float,
) -> float:
    if video_duration <= 0:
        return 0.0

    return min(1.0, get_duration(timeline) / video_duration)


def overlaps_time(a: Dict, b: Dict) -> bool:
    return get_start(a) < get_end(b) and get_start(b) < get_end(a)


def overlap_ratio(a: Dict, b: Dict) -> float:
    start = max(get_start(a), get_start(b))
    end = min(get_end(a), get_end(b))
    overlap = max(0.0, end - start)
    shorter = max(0.001, min(get_duration(a), get_duration(b)))

    return overlap / shorter


def token_set(text: str) -> set:
    return {
        token.strip(".,!?;:\"'()[]{}=").lower()
        for token in normalize_text_key(text).split()
        if token.strip(".,!?;:\"'()[]{}=")
    }


def cleaned_dialogue_key(text: str) -> str:
    return normalize_text_key(text).strip("*~\"'“”‘’` c")


def is_dialogue_marker_text(text: str) -> bool:
    stripped = (text or "").strip()

    return (
        stripped.startswith("*")
        or stripped.startswith("~")
        or '"' in stripped
        or "'" in stripped
        or "“" in stripped
        or "”" in stripped
        or "?" in stripped
        or "!" in stripped
    )


def is_question_or_dialogue_phrase(text: str) -> bool:
    key = cleaned_dialogue_key(text)

    if not key:
        return False

    starters = (
        "where ",
        "what ",
        "why ",
        "how ",
        "when ",
        "who ",
        "whose ",
        "then ",
        "mom ",
        "dad ",
        "help ",
    )

    return key.startswith(starters)


def is_short_caption_fragment(text: str) -> bool:
    key = cleaned_dialogue_key(text)
    words = key.split()

    if not words:
        return False

    return len(words) <= 2


def selected_texts_are_near_duplicates(a: Dict, b: Dict) -> bool:
    text_a = get_text(a)
    text_b = get_text(b)

    key_a = canonical_caption_key(text_a)
    key_b = canonical_caption_key(text_b)

    if not key_a or not key_b:
        return False

    if key_a == key_b:
        return True

    if key_a in key_b or key_b in key_a:
        return True

    compact_a = key_a.replace(" ", "")
    compact_b = key_b.replace(" ", "")

    if min(len(compact_a), len(compact_b)) >= 7:
        distance = compact_text_distance(compact_a, compact_b)
        max_len = max(len(compact_a), len(compact_b))

        if distance <= 2 or distance / max(1, max_len) <= 0.12:
            return True

    tokens_a = token_set(key_a)
    tokens_b = token_set(key_b)

    if not tokens_a or not tokens_b:
        return False

    shared = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)

    return shared / max(1, union) >= 0.82


def selected_caption_quality_key(timeline: Dict):
    return (
        get_sample_count(timeline),
        get_duration(timeline),
        word_count(get_text(timeline)),
        char_count(get_text(timeline)),
    )


def selected_timelines_share_same_visual_slot(a: Dict, b: Dict) -> bool:
    box_a = get_box(a)
    box_b = get_box(b)

    if horizontal_overlap_ratio(box_a, box_b) < 0.88:
        return False

    if vertical_overlap_ratio(box_a, box_b) < 0.78:
        return False

    if overlap_ratio(a, b) < 0.55:
        return False

    return True


def dedupe_selected_timelines(selected_timelines: List[Dict]) -> List[Dict]:
    kept: List[Dict] = []

    for timeline in sorted(
        selected_timelines,
        key=selected_caption_quality_key,
        reverse=True,
    ):
        duplicate_index = None

        for index, existing in enumerate(kept):
            near_duplicate = (
                selected_texts_are_near_duplicates(timeline, existing)
                or selected_timelines_share_same_visual_slot(timeline, existing)
            )

            if not near_duplicate:
                continue

            if overlap_ratio(timeline, existing) < 0.55:
                continue

            duplicate_index = index
            break

        if duplicate_index is None:
            kept.append(timeline)
            continue

        existing = kept[duplicate_index]

        if selected_caption_quality_key(timeline) > selected_caption_quality_key(existing):
            kept[duplicate_index] = timeline

    return sorted(
        kept,
        key=lambda item: (
            get_start(item),
            get_box_center_y(get_box(item)),
        ),
    )


def vertical_gap_between_boxes(box_a: List[int], box_b: List[int]) -> int:
    if box_a[3] < box_b[1]:
        return box_b[1] - box_a[3]

    if box_b[3] < box_a[1]:
        return box_a[1] - box_b[3]

    return 0


def horizontal_overlap_ratio(box_a: List[int], box_b: List[int]) -> float:
    left = max(box_a[0], box_b[0])
    right = min(box_a[2], box_b[2])
    overlap = max(0, right - left)
    min_width = max(1, min(get_box_width(box_a), get_box_width(box_b)))

    return overlap / min_width


def horizontal_gap_between_boxes(box_a: List[int], box_b: List[int]) -> int:
    if box_a[2] < box_b[0]:
        return box_b[0] - box_a[2]

    if box_b[2] < box_a[0]:
        return box_a[0] - box_b[2]

    return 0


def vertical_overlap_ratio(box_a: List[int], box_b: List[int]) -> float:
    top = max(box_a[1], box_b[1])
    bottom = min(box_a[3], box_b[3])
    overlap = max(0, bottom - top)
    min_height = max(1, min(get_box_height(box_a), get_box_height(box_b)))

    return overlap / min_height


def merge_boxes(boxes: List[List[int]]) -> List[int]:
    valid_boxes = [
        box
        for box in boxes
        if box and len(box) == 4 and box[2] > box[0] and box[3] > box[1]
    ]

    if not valid_boxes:
        return [0, 0, 0, 0]

    return [
        min(box[0] for box in valid_boxes),
        min(box[1] for box in valid_boxes),
        max(box[2] for box in valid_boxes),
        max(box[3] for box in valid_boxes),
    ]


def should_merge_supporting_into_main(
    main_timeline: Dict,
    supporting_timeline: Dict,
    video_info: Dict,
) -> bool:
    if main_timeline.get("caption_role") != ROLE_MAIN_CAPTION_TEXT:
        return False

    if supporting_timeline.get("caption_role") != ROLE_SUPPORTING_TEXT:
        return False

    if overlap_ratio(main_timeline, supporting_timeline) < 0.85:
        return False

    main_box = get_box(main_timeline)
    support_box = get_box(supporting_timeline)
    frame_height = int(video_info.get("height", 0) or 0)

    if support_box[1] > main_box[1]:
        return False

    if vertical_gap_between_boxes(main_box, support_box) > frame_height * 0.06:
        return False

    if horizontal_overlap_ratio(main_box, support_box) < 0.35:
        return False

    return True


def should_merge_same_line_supporting_fragment(
    base_timeline: Dict,
    fragment_timeline: Dict,
    video_info: Dict,
) -> bool:
    if base_timeline.get("caption_role") != ROLE_SUPPORTING_TEXT:
        return False

    if fragment_timeline.get("caption_role") not in {
        ROLE_SUPPORTING_TEXT,
        ROLE_NOISE_TEXT,
    }:
        return False

    if overlap_ratio(base_timeline, fragment_timeline) < 0.85:
        return False

    base_text = get_text(base_timeline)
    fragment_text = get_text(fragment_timeline)

    if not fragment_text:
        return False

    if is_decorative_object_text(fragment_text):
        return False

    if has_document_keywords(fragment_text):
        return False

    base_box = get_box(base_timeline)
    fragment_box = get_box(fragment_timeline)

    frame_width = int(video_info.get("width", 0) or 0)
    frame_height = int(video_info.get("height", 0) or 0)

    if frame_height > 0:
        base_center_y_for_region = get_box_center_y(base_box)
        fragment_center_y_for_region = get_box_center_y(fragment_box)

        if (
            fragment_center_y_for_region > frame_height * 0.58
            and base_center_y_for_region <= frame_height * 0.58
        ):
            return False

    if vertical_overlap_ratio(base_box, fragment_box) < 0.55:
        return False

    base_center_y = get_box_center_y(base_box)
    fragment_center_y = get_box_center_y(fragment_box)
    max_height = max(get_box_height(base_box), get_box_height(fragment_box), 1)

    if abs(base_center_y - fragment_center_y) > max_height * 0.45:
        return False

    horizontal_gap = horizontal_gap_between_boxes(base_box, fragment_box)
    horizontal_overlap = horizontal_overlap_ratio(base_box, fragment_box)

    base_words = word_count(base_text)
    fragment_words = word_count(fragment_text)

    one_side_is_short_fragment = (
        is_short_caption_fragment(base_text)
        or is_short_caption_fragment(fragment_text)
    )

    if horizontal_gap == 0 and horizontal_overlap > 0.25:
        if not one_side_is_short_fragment:
            return False

    if base_words >= 3 and fragment_words >= 3:
        return False

    max_gap = max(10, int(frame_width * 0.045))

    if horizontal_gap > max_gap:
        return False

    combined_width = get_box_width(merge_boxes([base_box, fragment_box]))

    if frame_width > 0 and combined_width > frame_width * 0.88:
        return False

    return True


def should_merge_stacked_top_caption_line(
    base_timeline: Dict,
    candidate_timeline: Dict,
    video_info: Dict,
) -> bool:
    """
    Merge stacked lines that belong to the same top white caption box.

    This catches cases like:
    - "Shopping with"
    - "Mom vs Dad:"

    without changing the broader role classifier. Character labels below the
    meme subjects should remain separate because they are outside the top box.
    """

    base_role = base_timeline.get("caption_role")
    candidate_role = candidate_timeline.get("caption_role")

    if base_role not in {
        ROLE_MAIN_CAPTION_TEXT,
        ROLE_SUPPORTING_TEXT,
    }:
        return False

    if candidate_role not in {
        ROLE_MAIN_CAPTION_TEXT,
        ROLE_SUPPORTING_TEXT,
        ROLE_CHARACTER_LABEL_TEXT,
    }:
        return False

    base_text = get_text(base_timeline)
    candidate_text = get_text(candidate_timeline)

    if not base_text or not candidate_text:
        return False

    if is_decorative_object_text(candidate_text):
        return False

    if has_document_keywords(candidate_text):
        return False

    if overlap_ratio(base_timeline, candidate_timeline) < 0.70:
        return False

    if abs(get_start(base_timeline) - get_start(candidate_timeline)) > 0.45:
        return False

    base_duration = max(get_duration(base_timeline), 0.001)
    candidate_duration = max(get_duration(candidate_timeline), 0.001)
    duration_ratio = min(base_duration, candidate_duration) / max(
        base_duration,
        candidate_duration,
    )

    if duration_ratio < 0.55:
        return False

    base_box = get_box(base_timeline)
    candidate_box = get_box(candidate_timeline)

    frame_width = int(video_info.get("width", 0) or 0)
    frame_height = int(video_info.get("height", 0) or 0)

    if frame_width <= 0 or frame_height <= 0:
        return False

    merged_box = merge_boxes([base_box, candidate_box])

    if get_box_center_y(merged_box) > frame_height * 0.42:
        return False

    if get_box_width(merged_box) < frame_width * 0.24:
        return False

    if get_box_width(merged_box) > frame_width * 0.92:
        return False

    vertical_gap = vertical_gap_between_boxes(base_box, candidate_box)
    max_line_height = max(
        get_box_height(base_box),
        get_box_height(candidate_box),
        1,
    )

    if vertical_gap > max(frame_height * 0.025, max_line_height * 0.35):
        return False

    horizontal_overlap = horizontal_overlap_ratio(base_box, candidate_box)
    vertical_overlap = vertical_overlap_ratio(base_box, candidate_box)

    if horizontal_overlap > 0.82 and vertical_overlap > 0.72:
        return False

    if horizontal_overlap < 0.55:
        return False

    center_x_gap = abs(get_box_center_x(base_box) - get_box_center_x(candidate_box))

    if center_x_gap > frame_width * 0.18:
        return False

    return True


def sort_merged_caption_items(merge_items: List[Dict]) -> List[Dict]:
    boxes = [get_box(item) for item in merge_items]

    if len(boxes) >= 2:
        heights = [get_box_height(box) for box in boxes if get_box_height(box) > 0]
        max_height = max(heights or [1])
        centers_y = [get_box_center_y(box) for box in boxes]

        if max(centers_y) - min(centers_y) <= max_height * 0.55:
            return sorted(
                merge_items,
                key=lambda item: get_box(item)[0],
            )

    return sorted(
        merge_items,
        key=lambda item: (
            get_box(item)[1],
            get_box(item)[0],
        ),
    )


def merge_supporting_lines_into_selected(
    selected_timelines: List[Dict],
    annotated_timelines: List[Dict],
    video_info: Dict,
) -> List[Dict]:
    merged_selected = []
    consumed_ids = set()

    for selected in selected_timelines:
        if id(selected) in consumed_ids:
            continue

        merge_items = [selected]

        for candidate in annotated_timelines:
            if candidate is selected:
                continue

            if should_merge_supporting_into_main(
                main_timeline=selected,
                supporting_timeline=candidate,
                video_info=video_info,
            ):
                merge_items.append(candidate)
                consumed_ids.add(id(candidate))
                continue

            if should_merge_same_line_supporting_fragment(
                base_timeline=selected,
                fragment_timeline=candidate,
                video_info=video_info,
            ):
                merge_items.append(candidate)
                consumed_ids.add(id(candidate))
                continue

            if should_merge_stacked_top_caption_line(
                base_timeline=selected,
                candidate_timeline=candidate,
                video_info=video_info,
            ):
                merge_items.append(candidate)
                consumed_ids.add(id(candidate))

        if len(merge_items) <= 1:
            merged_selected.append(selected)
            continue

        ordered = sort_merged_caption_items(merge_items)

        merged = dict(selected)
        merged["text"] = " ".join(get_text(item) for item in ordered).strip()
        merged["normalized_text"] = normalize_text_key(merged["text"])
        merged["box"] = merge_boxes([get_box(item) for item in ordered])
        merged["average_box"] = merged["box"]
        merged["caption_role"] = ROLE_MAIN_CAPTION_TEXT
        merged["should_translate"] = should_translate_role(ROLE_MAIN_CAPTION_TEXT)
        merged["merged_from_stacked_top_caption"] = True

        merged_selected.append(merged)

    return merged_selected


def is_header_like_text(text: str) -> bool:
    text = (text or "").strip()

    if not text:
        return False

    if text.endswith(":"):
        return True

    lowered = normalize_text_key(text)

    header_prefixes = [
        "pov:",
        "when ",
        "me when:",
        "boys when:",
        "girls when:",
        "teacher:",
        "chatgpt:",
        "boys:",
        "girls:",
    ]

    return any(lowered.startswith(prefix) for prefix in header_prefixes)


def is_character_label_text(text: str) -> bool:
    lowered = normalize_text_key(text)
    base = lowered.rstrip(":")

    character_labels = {
        "boys:",
        "girls:",
        "dad:",
        "mom:",
        "papa:",
        "papá:",
        "mama:",
        "mamá:",
        "baby:",
        "bro:",
        "me:",
        "yo:",
        "10 yo me:",
        "teacher:",
        "chatgpt:",
        "son:",
        "girl:",
        "boy:",
        "wife:",
        "husband:",
    }

    character_label_bases = {
        label.rstrip(":")
        for label in character_labels
    }

    return lowered in character_labels or base in character_label_bases


def is_phase_header_label_text(text: str) -> bool:
    lowered = normalize_text_key(text)

    return lowered in {
        "boys:",
        "girls:",
        "teacher:",
        "inreality:",
        "in reality:",
        "in movies:",
        "in reality;",
        "falling:",
        "inthe movies3",
        "inthe movies?",
        "in the movies:",
        "in the film3",
        "in the film:",
    }


def is_scene_phase_label_text(text: str) -> bool:
    lowered = normalize_text_key(text)

    return lowered in {
        "inreality:",
        "in reality:",
        "in movies:",
        "in reality;",
        "falling:",
        "inthe movies3",
        "inthe movies?",
        "in the movies:",
        "in the film3",
        "in the film:",
    }


def is_main_context_caption(text: str) -> bool:
    lowered = normalize_text_key(text)

    strong_main_prefixes = [
        "pov:",
        "when ",
        "me when:",
        "boys when:",
        "girls when:",
        "teacher:",
        "chatgpt:",
        "boys:",
        "girls:",
        "woman's logic:",
        "man's logic:",
    ]

    if any(lowered.startswith(prefix) for prefix in strong_main_prefixes):
        return True

    if text.endswith(":") and word_count(text) >= 2:
        return True

    return False


def is_decorative_object_text(text: str) -> bool:
    cleaned = normalize_text_key(text)
    raw = (text or "").strip()

    if not cleaned:
        return True

    decorative_exact = {
        "doublemint",
        "chanel",
        "dior",
        "rent",
        "restaurants",
        "am",
    }

    if cleaned in decorative_exact:
        return True

    decorative_contains = [
        "corona",
        "mentos",
        "fyre",
    ]

    if any(token in cleaned for token in decorative_contains):
        return True

    alpha_count = sum(1 for char in raw if char.isalpha())
    digit_count = sum(1 for char in raw if char.isdigit())

    if digit_count >= 2 and alpha_count <= 2:
        return True

    if word_count(raw) <= 1 and raw.isupper() and char_count(raw) <= 12:
        return True

    return False


def has_document_keywords(text: str) -> bool:
    lowered = (text or "").lower()

    document_keywords = [
        "agreement",
        "greement",
        "divorce",
        "divorce greement",
        "divorce agreement",
        "address",
        "husband",
        "wife",
        "plaintiff",
        "defendant",
        "civil",
        "registry",
        "marriage",
        "minor",
        "children",
        "provisions",
        "parties",
        "article",
        "signature",
    ]

    hit_count = 0

    for keyword in document_keywords:
        if keyword in lowered:
            hit_count += 1

    if "divorce" in lowered and "greement" in lowered:
        return True

    return hit_count >= 2


def is_browser_history_noise_text(text: str) -> bool:
    lowered = normalize_text_key(text)

    if not lowered:
        return False

    compact = lowered.replace(" ", "")

    browser_noise_tokens = [
        "browser",
        "browvser",
        "lbrowser",
        "lbrowvser",
        "historyfrom",
        "todeletethehistory",
    ]

    if any(token in compact for token in browser_noise_tokens):
        return True

    if "history" in lowered and "delete" in lowered:
        return True

    return False


def is_small_noise_text(
    timeline: Dict,
    frame_width: int,
    frame_height: int,
) -> bool:
    text = get_text(timeline)
    box = get_box(timeline)

    if not text:
        return True

    width = get_box_width(box)
    height = get_box_height(box)

    if width < frame_width * 0.06:
        return True

    if height < frame_height * 0.015:
        return True

    if word_count(text) <= 1 and get_duration(timeline) < 0.7:
        return True

    return False


def is_top_caption_region(
    timeline: Dict,
    frame_width: int,
    frame_height: int,
) -> bool:
    box = get_box(timeline)

    width = get_box_width(box)
    center_y = get_box_center_y(box)

    is_top = center_y <= frame_height * 0.45
    is_wide = width >= frame_width * 0.22

    return is_top and is_wide


def is_main_caption_timeline(
    timeline: Dict,
    all_timelines: List[Dict],
    video_info: Dict,
) -> bool:
    text = get_text(timeline)

    if not text:
        return False

    if is_decorative_object_text(text):
        return False

    if has_document_keywords(text):
        return False

    if not is_main_context_caption(text):
        return False

    frame_width = int(video_info.get("width", 0) or 0)
    frame_height = int(video_info.get("height", 0) or 0)

    if not is_top_caption_region(
        timeline=timeline,
        frame_width=frame_width,
        frame_height=frame_height,
    ):
        return False

    return True


def is_dominant_full_sentence_main_caption(
    timeline: Dict,
    all_timelines: List[Dict],
    video_info: Dict,
) -> bool:
    """
    Fallback main caption rule.

    Dùng khi video không có header/context caption rõ ràng.
    Ví dụ:
    - Reaccion a una arana en Australia
    - Business plan in Greece=
    - How much acid does it take...
    - teaching POV Dad lion his cub how to roar

    Không dùng để override các case đã có header main caption.
    """

    text = get_text(timeline)

    if not text:
        return False

    if is_decorative_object_text(text):
        return False

    if has_document_keywords(text):
        return False

    if is_character_label_text(text):
        return False

    if word_count(text) < 3:
        return False

    video_duration = float(video_info.get("duration", 0.0) or 0.0)
    coverage = timeline_coverage_ratio(timeline, video_duration)

    if coverage < 0.25:
        return False

    if get_sample_count(timeline) < 8:
        return False

    frame_width = int(video_info.get("width", 0) or 0)
    frame_height = int(video_info.get("height", 0) or 0)

    if not is_top_caption_region(
        timeline=timeline,
        frame_width=frame_width,
        frame_height=frame_height,
    ):
        return False

    return True


def has_any_main_context_caption(
    timelines: List[Dict],
    video_info: Dict,
) -> bool:
    for timeline in timelines:
        if is_main_caption_timeline(
            timeline=timeline,
            all_timelines=timelines,
            video_info=video_info,
        ):
            return True

    return False


def has_overlapping_non_label_main_caption(
    timeline: Dict,
    all_timelines: List[Dict],
    video_info: Dict,
) -> bool:
    for other in all_timelines:
        if other is timeline:
            continue

        if is_character_label_text(get_text(other)):
            continue

        if not overlaps_time(timeline, other):
            continue

        if overlap_ratio(timeline, other) < 0.55:
            continue

        if is_main_caption_timeline(
            timeline=other,
            all_timelines=all_timelines,
            video_info=video_info,
        ):
            return True

        if is_dominant_full_sentence_main_caption(
            timeline=other,
            all_timelines=all_timelines,
            video_info=video_info,
        ):
            return True

    return False


def is_phase_header_main_caption(
    timeline: Dict,
    all_timelines: List[Dict],
    video_info: Dict,
) -> bool:
    if not is_phase_header_label_text(get_text(timeline)):
        return False

    if get_duration(timeline) < 1.5:
        return False

    frame_width = int(video_info.get("width", 0) or 0)
    frame_height = int(video_info.get("height", 0) or 0)

    if not is_top_caption_region(
        timeline=timeline,
        frame_width=frame_width,
        frame_height=frame_height,
    ):
        return False

    if is_scene_phase_label_text(get_text(timeline)):
        return True

    if has_overlapping_non_label_main_caption(
        timeline=timeline,
        all_timelines=all_timelines,
        video_info=video_info,
    ):
        return False

    return True


def is_supporting_text_timeline(
    timeline: Dict,
    all_timelines: List[Dict],
    video_info: Dict,
) -> bool:
    text = get_text(timeline)

    if not text:
        return False

    if is_decorative_object_text(text):
        return False

    if has_document_keywords(text):
        return False

    if is_main_context_caption(text):
        return False

    if is_character_label_text(text):
        return False

    if word_count(text) < 2:
        return False

    if get_duration(timeline) < 0.6:
        return False

    frame_height = int(video_info.get("height", 0) or 0)

    if frame_height > 0 and get_box_center_y(get_box(timeline)) > frame_height * 0.58:
        return is_lower_dialogue_subtitle_timeline(
            timeline=timeline,
            video_info=video_info,
        )

    return True


def is_lower_dialogue_subtitle_timeline(
    timeline: Dict,
    video_info: Dict,
) -> bool:
    text = get_text(timeline)
    word_total = word_count(text)

    if word_total < 2:
        return False

    if get_duration(timeline) < 0.75:
        return False

    box = get_box(timeline)
    frame_width = int(video_info.get("width", 0) or 0)
    frame_height = int(video_info.get("height", 0) or 0)

    if frame_width > 0 and get_box_width(box) < frame_width * 0.22:
        return False

    if frame_height > 0 and get_box_center_y(box) > frame_height * 0.94:
        return False

    score = timeline.get("score") or {}
    final_score = float(score.get("final_score", 0.0) or 0.0)

    if final_score < 0.62:
        return False

    stripped = text.strip()
    lowered = normalize_text_key(stripped)
    has_dialogue_marker = is_dialogue_marker_text(stripped)
    has_dialogue_phrase = is_question_or_dialogue_phrase(stripped)
    has_sentence_shape = (
        word_total >= 4
        and any(token in lowered for token in {" i ", " you ", " we ", " my ", " your ", " he ", " she ", " they "})
    )
    is_short_high_confidence_dialogue = (
        word_total >= 2
        and has_dialogue_marker
        and final_score >= 0.84
        and get_duration(timeline) >= 0.7
    )

    if (
        not has_dialogue_marker
        and not has_dialogue_phrase
        and not has_sentence_shape
        and not is_short_high_confidence_dialogue
    ):
        return False

    return True


def classify_timeline_role(
    timeline: Dict,
    all_timelines: List[Dict],
    video_info: Dict,
) -> str:
    frame_width = int(video_info.get("width", 0) or 0)
    frame_height = int(video_info.get("height", 0) or 0)
    text = get_text(timeline)

    if is_phase_header_main_caption(
        timeline=timeline,
        all_timelines=all_timelines,
        video_info=video_info,
    ):
        return ROLE_MAIN_CAPTION_TEXT

    if is_small_noise_text(
        timeline=timeline,
        frame_width=frame_width,
        frame_height=frame_height,
    ):
        return ROLE_NOISE_TEXT

    if is_decorative_object_text(text):
        return ROLE_NOISE_TEXT

    if is_browser_history_noise_text(text):
        return ROLE_NOISE_TEXT

    if has_document_keywords(text):
        return ROLE_DOCUMENT_NOISE_TEXT

    if is_character_label_text(text):
        return ROLE_CHARACTER_LABEL_TEXT

    if is_main_caption_timeline(
        timeline=timeline,
        all_timelines=all_timelines,
        video_info=video_info,
    ):
        return ROLE_MAIN_CAPTION_TEXT

    has_main_context = has_any_main_context_caption(
        timelines=all_timelines,
        video_info=video_info,
    )

    if not has_main_context:
        if is_dominant_full_sentence_main_caption(
            timeline=timeline,
            all_timelines=all_timelines,
            video_info=video_info,
        ):
            return ROLE_MAIN_CAPTION_TEXT

    if is_supporting_text_timeline(
        timeline=timeline,
        all_timelines=all_timelines,
        video_info=video_info,
    ):
        return ROLE_SUPPORTING_TEXT

    return ROLE_NOISE_TEXT


def should_translate_role(role: str) -> bool:
    """
    RULE LOCK:
    Chỉ translate MAIN CAPTION mặc định.
    """

    return role in {
        ROLE_MAIN_CAPTION_TEXT,
        ROLE_SUPPORTING_TEXT,
    }


def annotate_timeline(
    timeline: Dict,
    role: str,
) -> Dict:
    annotated = dict(timeline)

    annotated["caption_role"] = role
    annotated["should_translate"] = should_translate_role(role)

    return annotated


def select_final_caption_timelines(
    timeline_result: Dict,
    video_info: Dict,
) -> Dict:
    timelines = timeline_result.get("timelines", [])

    annotated_timelines = []

    for timeline in timelines:
        role = classify_timeline_role(
            timeline=timeline,
            all_timelines=timelines,
            video_info=video_info,
        )

        annotated_timelines.append(
            annotate_timeline(
                timeline=timeline,
                role=role,
            )
        )

    selected_timelines = [
        timeline
        for timeline in annotated_timelines
        if timeline.get("should_translate")
    ]

    selected_timelines = merge_supporting_lines_into_selected(
        selected_timelines=selected_timelines,
        annotated_timelines=annotated_timelines,
        video_info=video_info,
    )

    selected_timelines = dedupe_selected_timelines(selected_timelines)

    role_counts = {}

    for timeline in annotated_timelines:
        role = timeline.get("caption_role")

        role_counts[role] = role_counts.get(role, 0) + 1

    return {
        "status": "ok",
        "stage": "final_caption_selection",
        "input_timeline_count": len(timelines),
        "selected_timeline_count": len(selected_timelines),
        "role_counts": role_counts,
        "selected_timelines": selected_timelines,
        "all_timelines": annotated_timelines,
    }
