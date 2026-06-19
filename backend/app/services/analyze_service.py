import os
from typing import Dict, List, Optional

from core.ocr.ocr_cleaner import clean_sampled_frames_ocr_result
from core.ocr.reader import read_sampled_frames_ocr
from core.system.hardware_checker import should_use_gpu_ocr
from core.translation.language_detector import default_ocr_languages
from core.video.frame_sampler import analyze_sample_video
from engines.meme_caption.caption_scorer import score_sampled_frames_ocr
from engines.meme_caption.caption_selector import (
    select_caption_candidates_from_scored_frames,
)
from engines.meme_caption.final_caption_selector import (
    select_final_caption_timelines,
)
from engines.meme_caption.timeline_builder import build_caption_timelines


DEFAULT_TEMP_DIR = "temp/analyze_frame_samples"


def _emit_progress(progress_callback, stage: str, progress: float, **details) -> None:
    if progress_callback is None:
        return

    progress_callback(
        {
            "stage": stage,
            "progress": max(0.0, min(1.0, float(progress))),
            **details,
        }
    )


def _scaled_progress_callback(progress_callback, stage: str, start: float, end: float):
    if progress_callback is None:
        return None

    def report(event: Dict) -> None:
        source_event = dict(event or {})
        source_progress = float(source_event.pop("progress", 0.0) or 0.0)
        source_stage = source_event.pop("stage", "")
        detail_stage = source_event.pop("detail_stage", "") or source_event.pop("source_stage", "")
        _emit_progress(
            progress_callback,
            stage,
            start + ((end - start) * max(0.0, min(1.0, source_progress))),
            source_stage=source_stage,
            detail_stage=detail_stage,
            stage_progress=source_event.pop("stage_progress", source_progress),
            **source_event,
        )

    return report


def analyze_video_for_production(
    video_path: str,
    temp_dir: str = DEFAULT_TEMP_DIR,
    interval_sec: float = 0.25,
    max_frames: int = 0,
    languages: Optional[List[str]] = None,
    gpu=None,
    min_confidence: float = 0.15,
    min_score: float = 0.55,
    max_gap_sec: float = 0.6,
    similarity_threshold: float = 0.58,
    token_threshold: float = 0.55,
    min_box_similarity: float = 0.38,
    min_timeline_samples: int = 1,
    progress_callback=None,
) -> Dict:
    languages = default_ocr_languages(languages)

    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video file không tồn tại: {video_path}")

    os.makedirs(temp_dir, exist_ok=True)

    resolved_gpu = should_use_gpu_ocr(user_requested_gpu=gpu)
    frame_limit = None if max_frames <= 0 else max_frames

    _emit_progress(progress_callback, "sample_frames", 0.0)

    sample_result = analyze_sample_video(
        video_path=video_path,
        temp_dir=temp_dir,
        interval_sec=interval_sec,
        max_frames=frame_limit,
        progress_callback=_scaled_progress_callback(
            progress_callback,
            "sample_frames",
            0.0,
            0.12,
        ),
    )

    samples = sample_result["result"]["samples"]
    video_info = sample_result["result"]["video_info"]

    _emit_progress(progress_callback, "ocr_frames", 0.12)

    raw_ocr_result = read_sampled_frames_ocr(
        samples=samples,
        languages=languages,
        gpu=resolved_gpu,
        min_confidence=min_confidence,
        max_frames=frame_limit,
        progress_callback=_scaled_progress_callback(
            progress_callback,
            "ocr_frames",
            0.12,
            0.76,
        ),
    )

    _emit_progress(progress_callback, "clean_ocr", 0.80)
    cleaned_ocr_result = clean_sampled_frames_ocr_result(
        raw_ocr_result
    )

    _emit_progress(progress_callback, "score_captions", 0.84)
    scored_ocr_result = score_sampled_frames_ocr(
        ocr_result=cleaned_ocr_result,
        frame_width=video_info["width"],
        frame_height=video_info["height"],
    )

    _emit_progress(progress_callback, "select_candidates", 0.88)
    selected_result = select_caption_candidates_from_scored_frames(
        scored_ocr_result=scored_ocr_result,
        frame_width=video_info["width"],
        frame_height=video_info["height"],
        min_score=min_score,
    )

    _emit_progress(progress_callback, "build_timelines", 0.94)
    timeline_result = build_caption_timelines(
        candidates=selected_result["candidates"],
        frame_interval_sec=interval_sec,
        max_gap_sec=max_gap_sec,
        similarity_threshold=similarity_threshold,
        token_threshold=token_threshold,
        min_box_similarity=min_box_similarity,
        min_samples=min_timeline_samples,
        video_duration=float(video_info.get("duration", 0.0) or 0.0),
    )

    _emit_progress(progress_callback, "select_timelines", 0.98)
    final_caption_result = select_final_caption_timelines(
        timeline_result=timeline_result,
        video_info=video_info,
    )

    _emit_progress(progress_callback, "analyze_complete", 1.0)

    return {
        "status": "ok",
        "video_path": video_path,
        "video_name": os.path.basename(video_path),
        "video_info": video_info,
        "settings": {
            "interval_sec": interval_sec,
            "max_frames": max_frames,
            "languages": languages,
            "gpu_requested": gpu,
            "gpu_resolved": resolved_gpu,
            "min_confidence": min_confidence,
            "min_score": min_score,
            "max_gap_sec": max_gap_sec,
            "similarity_threshold": similarity_threshold,
            "token_threshold": token_threshold,
            "min_box_similarity": min_box_similarity,
            "min_timeline_samples": min_timeline_samples,
        },
        "summary": {
            "sample_count": sample_result["result"]["sample_count"],
            "ocr_frame_count": scored_ocr_result.get("frame_count", 0),
            "total_ocr_items": scored_ocr_result.get("total_ocr_items", 0),
            "candidate_count": selected_result.get("candidate_count", 0),
            "timeline_count": timeline_result.get("timeline_count", 0),
            "selected_timeline_count": final_caption_result.get(
                "selected_timeline_count",
                0,
            ),
            "role_counts": final_caption_result.get("role_counts", {}),
        },
        "raw_timelines": timeline_result.get("timelines", []),
        "_temp_sample_output_dir": sample_result["result"]["output_dir"],
        "final_caption_selection": final_caption_result,
        "selected_timelines": final_caption_result.get(
            "selected_timelines",
            [],
        ),
    }
