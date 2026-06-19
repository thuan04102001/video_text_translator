from difflib import SequenceMatcher
from typing import Dict, List, Optional, Set


def normalize_text(text: str) -> str:
    text = (text or "").strip().lower()

    replacements = {
        "|": "l",
        "@": "a",
        "€": "e",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = text.replace("’", "'")
    text = text.replace("“", '"')
    text = text.replace("”", '"')

    return " ".join(text.split())


def normalize_token(token: str) -> str:
    token = (token or "").strip().lower()
    token = token.strip(".,!?;:\"'()[]{}")

    return token


def extract_tokens(text: str) -> Set[str]:
    normalized = normalize_text(text)
    tokens = set()

    for token in normalized.split():
        clean_token = normalize_token(token)

        if clean_token:
            tokens.add(clean_token)

    return tokens


def extract_critical_tokens(text: str) -> Set[str]:
    normalized = normalize_text(text)
    tokens = extract_tokens(normalized)

    critical_tokens = set()

    semantic_keywords = {
        "usa",
        "us",
        "america",
        "american",
        "europe",
        "european",
        "central",
        "china",
        "chinese",
        "japan",
        "japanese",
        "korea",
        "korean",
        "australia",
        "australian",
        "greece",
        "greek",
        "new",
        "york",
        "texas",
        "boys",
        "boy",
        "girls",
        "girl",
        "men",
        "man",
        "women",
        "woman",
        "dad",
        "mom",
        "bro",
        "son",
        "teacher",
        "chatgpt",
        "reality",
        "movies",
        "expectation",
    }

    for token in tokens:
        if token in semantic_keywords:
            critical_tokens.add(token)

        if "$" in token:
            critical_tokens.add(token)

        if any(char.isdigit() for char in token):
            critical_tokens.add(token)

    return critical_tokens


def critical_tokens_conflict(a: str, b: str) -> bool:
    tokens_a = extract_critical_tokens(a)
    tokens_b = extract_critical_tokens(b)

    if not tokens_a or not tokens_b:
        return False

    shared = tokens_a & tokens_b

    if shared:
        return False

    return True


def longest_common_prefix_tokens(
    a: str,
    b: str,
) -> List[str]:
    tokens_a = [
        normalize_token(token)
        for token in normalize_text(a).split()
        if normalize_token(token)
    ]

    tokens_b = [
        normalize_token(token)
        for token in normalize_text(b).split()
        if normalize_token(token)
    ]

    prefix = []

    for token_a, token_b in zip(tokens_a, tokens_b):
        if token_a != token_b:
            break

        prefix.append(token_a)

    return prefix


def suffix_after_common_prefix(
    text: str,
    prefix_tokens: List[str],
) -> List[str]:
    tokens = [
        normalize_token(token)
        for token in normalize_text(text).split()
        if normalize_token(token)
    ]

    return tokens[len(prefix_tokens):]


def has_meaningful_suffix_difference(
    a: str,
    b: str,
) -> bool:
    """
    Chống merge các caption có chung phần mở đầu nhưng khác nghĩa ở cuối.

    Ví dụ:
    - Normal salary in USA
    - Normal salary in Central Europe

    Hai câu rất giống nhau nhưng suffix khác nhau là ý nghĩa chính,
    nên bắt buộc phải tách timeline.
    """

    prefix_tokens = longest_common_prefix_tokens(a, b)

    if len(prefix_tokens) < 2:
        return False

    suffix_a = suffix_after_common_prefix(a, prefix_tokens)
    suffix_b = suffix_after_common_prefix(b, prefix_tokens)

    if not suffix_a or not suffix_b:
        return False

    if suffix_a == suffix_b:
        return False

    suffix_a_set = set(suffix_a)
    suffix_b_set = set(suffix_b)

    shared_suffix = suffix_a_set & suffix_b_set

    if shared_suffix:
        return False

    if len(suffix_a_set | suffix_b_set) >= 2:
        return True

    return False


def semantic_merge_conflict(a: str, b: str) -> bool:
    if critical_tokens_conflict(a, b):
        return True

    if has_meaningful_suffix_difference(a, b):
        return True

    return False


def text_similarity(a: str, b: str) -> float:
    a = normalize_text(a)
    b = normalize_text(b)

    if not a or not b:
        return 0.0

    if semantic_merge_conflict(a, b):
        return 0.0

    return SequenceMatcher(None, a, b).ratio()


def token_similarity(a: str, b: str) -> float:
    tokens_a = extract_tokens(a)
    tokens_b = extract_tokens(b)

    if not tokens_a or not tokens_b:
        return 0.0

    if semantic_merge_conflict(a, b):
        return 0.0

    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)

    return intersection / max(1, union)


def get_box(candidate: Dict) -> List[int]:
    box = candidate.get("box") or [0, 0, 0, 0]

    if len(box) != 4:
        return [0, 0, 0, 0]

    return [
        int(box[0]),
        int(box[1]),
        int(box[2]),
        int(box[3]),
    ]


def get_box_center(box: List[int]) -> Dict:
    return {
        "x": (box[0] + box[2]) / 2,
        "y": (box[1] + box[3]) / 2,
    }


def get_box_size(box: List[int]) -> Dict:
    return {
        "width": max(0, box[2] - box[0]),
        "height": max(0, box[3] - box[1]),
    }


def spatial_similarity(box_a: List[int], box_b: List[int]) -> float:
    center_a = get_box_center(box_a)
    center_b = get_box_center(box_b)

    size_a = get_box_size(box_a)
    size_b = get_box_size(box_b)

    avg_width = max(1, (size_a["width"] + size_b["width"]) / 2)
    avg_height = max(1, (size_a["height"] + size_b["height"]) / 2)

    dx = abs(center_a["x"] - center_b["x"]) / avg_width
    dy = abs(center_a["y"] - center_b["y"]) / avg_height

    score = 1.0 - min(1.0, (dx + dy) / 2)

    return max(0.0, score)


def merge_boxes(boxes: List[List[int]]) -> List[int]:
    valid_boxes = [
        box
        for box in boxes
        if box and len(box) == 4
    ]

    if not valid_boxes:
        return [0, 0, 0, 0]

    x1 = min(box[0] for box in valid_boxes)
    y1 = min(box[1] for box in valid_boxes)
    x2 = max(box[2] for box in valid_boxes)
    y2 = max(box[3] for box in valid_boxes)

    return [x1, y1, x2, y2]


def build_track_similarity(
    candidate: Dict,
    timeline: Dict,
    similarity_threshold: float,
    token_threshold: float,
    min_box_similarity: float,
) -> bool:
    """
    Stable-track matcher.

    Candidate mới chỉ được nối vào timeline nếu:
    - text đủ giống
    - token đủ giống
    - spatial track đủ giống
    - KHÔNG có semantic conflict

    Semantic conflict giúp tránh merge sai:
    - USA vs Central Europe
    - Boys vs Girls
    - 40k$ vs 3k$
    - Normal salary in USA vs Normal salary in Central Europe
    """

    candidate_text = candidate.get("normalized_text") or candidate.get("text") or ""
    timeline_text = timeline.get("normalized_text") or timeline.get("text") or ""

    if semantic_merge_conflict(candidate_text, timeline_text):
        return False

    text_score = text_similarity(candidate_text, timeline_text)
    token_score = token_similarity(candidate_text, timeline_text)

    candidate_box = get_box(candidate)
    timeline_box = timeline.get("average_box") or timeline.get("box") or [0, 0, 0, 0]

    box_score = spatial_similarity(candidate_box, timeline_box)

    if text_score >= similarity_threshold and box_score >= min_box_similarity:
        return True

    if token_score >= token_threshold and box_score >= min_box_similarity:
        return True

    return False


def create_timeline(candidate: Dict) -> Dict:
    time_value = float(candidate.get("time", 0.0) or 0.0)

    return {
        "group_id": None,
        "start": time_value,
        "end": time_value,
        "duration": 0.0,
        "sample_count": 1,
        "text": candidate.get("text"),
        "normalized_text": candidate.get("normalized_text"),
        "box": candidate.get("box"),
        "average_box": candidate.get("box"),
        "confidence": candidate.get("confidence"),
        "score": candidate.get("score"),
        "best_sample": candidate,
        "samples": [candidate],
    }


def update_timeline(timeline: Dict, candidate: Dict) -> None:
    timeline["samples"].append(candidate)

    samples = sorted(
        timeline["samples"],
        key=lambda item: float(item.get("time", 0.0) or 0.0),
    )
    timeline["samples"] = samples

    timeline["sample_count"] = len(samples)

    start_time = float(samples[0].get("time", 0.0) or 0.0)
    end_time = float(samples[-1].get("time", 0.0) or 0.0)

    timeline["start"] = start_time
    timeline["end"] = end_time
    timeline["duration"] = max(0.0, end_time - start_time)

    best_sample = max(
        samples,
        key=lambda item: (
            float(item.get("confidence", 0.0) or 0.0),
            float((item.get("score") or {}).get("final_score", 0.0) or 0.0),
        ),
    )

    timeline["best_sample"] = best_sample
    timeline["text"] = best_sample.get("text")
    timeline["normalized_text"] = best_sample.get("normalized_text")
    timeline["box"] = best_sample.get("box")
    timeline["confidence"] = best_sample.get("confidence")
    timeline["score"] = best_sample.get("score")

    all_boxes = [
        sample.get("box")
        for sample in samples
        if sample.get("box")
    ]

    timeline["average_box"] = merge_boxes(all_boxes)


def filter_short_noise_timelines(
    timelines: List[Dict],
    min_duration: float,
    min_samples: int,
) -> List[Dict]:
    kept = []

    for timeline in timelines:
        duration = float(timeline.get("duration", 0.0) or 0.0)
        sample_count = int(timeline.get("sample_count", 0) or 0)

        if duration >= min_duration:
            kept.append(timeline)
            continue

        if sample_count >= min_samples:
            kept.append(timeline)
            continue

    return kept


def merge_similar_timelines(
    timelines: List[Dict],
    similarity_threshold: float,
    token_threshold: float,
    min_box_similarity: float,
) -> List[Dict]:
    if not timelines:
        return []

    merged: List[Dict] = []

    for timeline in sorted(
        timelines,
        key=lambda item: (
            -(item.get("sample_count") or 0),
            -(item.get("duration") or 0.0),
        ),
    ):
        found_match = False

        for existing in merged:
            if build_track_similarity(
                candidate=timeline,
                timeline=existing,
                similarity_threshold=similarity_threshold,
                token_threshold=token_threshold,
                min_box_similarity=min_box_similarity,
            ):
                existing["samples"].extend(timeline.get("samples", []))
                update_timeline(existing, existing["best_sample"])
                found_match = True
                break

        if not found_match:
            merged.append(timeline)

    return merged


def finalize_timelines(timelines: List[Dict]) -> List[Dict]:
    finalized = []

    for index, timeline in enumerate(
        sorted(
            timelines,
            key=lambda item: (
                -(item.get("sample_count") or 0),
                -(item.get("duration") or 0.0),
            ),
        ),
        start=1,
    ):
        timeline["group_id"] = index

        timeline.pop("samples", None)

        finalized.append(timeline)

    return finalized


def pad_timeline_ends(
    timelines: List[Dict],
    frame_interval_sec: float,
    video_duration: Optional[float],
) -> List[Dict]:
    if video_duration is None or video_duration <= 0:
        return timelines

    for timeline in timelines:
        start = float(timeline.get("start", 0.0) or 0.0)
        end = float(timeline.get("end", 0.0) or 0.0)
        padded_end = min(float(video_duration), end + frame_interval_sec)

        timeline["end"] = padded_end
        timeline["duration"] = max(0.0, padded_end - start)

    return timelines


def build_caption_timelines(
    candidates: List[Dict],
    frame_interval_sec: float = 0.25,
    max_gap_sec: float = 0.6,
    similarity_threshold: float = 0.58,
    token_threshold: float = 0.55,
    min_box_similarity: float = 0.38,
    min_samples: int = 2,
    min_duration: Optional[float] = None,
    video_duration: Optional[float] = None,
) -> Dict:
    if min_duration is None:
        min_duration = max(frame_interval_sec * 1.5, 0.45)

    ordered_candidates = sorted(
        candidates,
        key=lambda item: (
            float(item.get("time", 0.0) or 0.0),
            item.get("region_index", 0),
        ),
    )

    active_timelines: List[Dict] = []

    for candidate in ordered_candidates:
        candidate_time = float(candidate.get("time", 0.0) or 0.0)

        matched_timeline = None

        for timeline in active_timelines:
            last_time = float(timeline.get("end", 0.0) or 0.0)

            if candidate_time - last_time > max_gap_sec:
                continue

            if build_track_similarity(
                candidate=candidate,
                timeline=timeline,
                similarity_threshold=similarity_threshold,
                token_threshold=token_threshold,
                min_box_similarity=min_box_similarity,
            ):
                matched_timeline = timeline
                break

        if matched_timeline:
            update_timeline(matched_timeline, candidate)
        else:
            active_timelines.append(create_timeline(candidate))

    timelines = filter_short_noise_timelines(
        timelines=active_timelines,
        min_duration=min_duration,
        min_samples=min_samples,
    )

    timelines = merge_similar_timelines(
        timelines=timelines,
        similarity_threshold=similarity_threshold,
        token_threshold=token_threshold,
        min_box_similarity=min_box_similarity,
    )

    timelines = finalize_timelines(timelines)
    timelines = pad_timeline_ends(
        timelines=timelines,
        frame_interval_sec=frame_interval_sec,
        video_duration=video_duration,
    )

    return {
        "timeline_count": len(timelines),
        "timelines": timelines,
    }
