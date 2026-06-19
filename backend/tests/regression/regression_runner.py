import json
import os
import sys
import traceback
import warnings
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

warnings.filterwarnings(
    "ignore",
    message=".*pin_memory.*no accelerator.*",
    category=UserWarning,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.ocr.ocr_cleaner import clean_sampled_frames_ocr_result
from core.ocr.reader import read_sampled_frames_ocr
from core.system.hardware_checker import get_hardware_status, should_use_gpu_ocr
from core.video.frame_sampler import analyze_sample_video
from engines.meme_caption.caption_scorer import score_sampled_frames_ocr
from engines.meme_caption.caption_selector import (
    select_caption_candidates_from_scored_frames,
)
from engines.meme_caption.final_caption_selector import (
    select_final_caption_timelines,
)
from engines.meme_caption.timeline_builder import build_caption_timelines


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}

DEFAULT_INPUT_DIR = "tests/regression/input_videos"
DEFAULT_REPORT_DIR = "tests/regression/reports"
DEFAULT_TEMP_DIR = "temp/regression_frame_samples"

VALID_SELECTED_ROLES = {
    "MAIN_CAPTION_TEXT",
    "DYNAMIC_CONTENT_TEXT",
    "PHASE_HEADER_TEXT",
    "COMPARE_LAYOUT_TEXT",
    "REACTION_LAYOUT_TEXT",
}

INVALID_SELECTED_ROLES = {
    "NOISE_TEXT",
    "DOCUMENT_NOISE_TEXT",
    "STATIC_LAYOUT_TEXT",
}


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def ensure_report_dirs(report_dir: str) -> Dict:
    """
    Clean report structure:

    reports/
    ├── fail_only_latest.json
    ├── regression_report_latest.json
    ├── regression_summary_latest.json
    └── history/
        ├── fail_only/
        ├── full_report/
        └── summary/
    """

    history_root = os.path.join(report_dir, "history")

    full_report_dir = os.path.join(history_root, "full_report")
    summary_dir = os.path.join(history_root, "summary")
    fail_only_dir = os.path.join(history_root, "fail_only")

    ensure_dir(report_dir)
    ensure_dir(history_root)
    ensure_dir(full_report_dir)
    ensure_dir(summary_dir)
    ensure_dir(fail_only_dir)

    return {
        "history_root": history_root,
        "full_report_dir": full_report_dir,
        "summary_dir": summary_dir,
        "fail_only_dir": fail_only_dir,
    }


def is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTS


def list_video_files(input_dir: str) -> List[Path]:
    root = Path(input_dir)

    if not root.exists():
        return []

    videos = [
        path
        for path in root.rglob("*")
        if is_video_file(path)
    ]

    return sorted(videos, key=lambda item: str(item).lower())


def summarize_timeline(timeline: Dict) -> Dict:
    return {
        "group_id": timeline.get("group_id"),
        "start": timeline.get("start"),
        "end": timeline.get("end"),
        "duration": timeline.get("duration"),
        "sample_count": timeline.get("sample_count"),
        "text": timeline.get("text"),
        "normalized_text": timeline.get("normalized_text"),
        "box": timeline.get("box"),
        "average_box": timeline.get("average_box"),
        "confidence": timeline.get("confidence"),
        "score": timeline.get("score"),
        "best_sample": timeline.get("best_sample"),
    }


def summarize_candidate(candidate: Dict) -> Dict:
    return {
        "sample_index": candidate.get("sample_index"),
        "time": candidate.get("time"),
        "frame_index": candidate.get("frame_index"),
        "text": candidate.get("text"),
        "normalized_text": candidate.get("normalized_text"),
        "box": candidate.get("box"),
        "confidence": candidate.get("confidence"),
        "score": candidate.get("score"),
        "line_count": len(candidate.get("source_items", [])),
    }


def summarize_final_timeline(timeline: Dict) -> Dict:
    return {
        "text": timeline.get("text"),
        "caption_role": timeline.get("caption_role"),
        "should_translate": timeline.get("should_translate"),
        "start": timeline.get("start"),
        "end": timeline.get("end"),
        "duration": timeline.get("duration"),
        "sample_count": timeline.get("sample_count"),
        "box": timeline.get("box"),
        "average_box": timeline.get("average_box"),
    }


def build_fail_flags(
    video_info: Dict,
    selected_result: Dict,
    timeline_result: Dict,
    final_caption_result: Optional[Dict] = None,
) -> List[str]:
    """
    Semantic regression rules.

    Old logic failed videos mainly because raw timeline_count was high.
    That is no longer correct because modern meme videos can have many valid
    semantic timelines.

    New logic:
    - Keep old critical checks for no OCR candidate / no timeline.
    - Validate final selected captions by semantic role.
    - Do NOT fail only because raw timeline_count is high.
    - Do NOT fail only because raw timeline has short/noisy fragments if those
      fragments are filtered out by final_caption_selector.
    """

    flags = []

    candidate_count = int(selected_result.get("candidate_count", 0) or 0)
    timeline_count = int(timeline_result.get("timeline_count", 0) or 0)

    if candidate_count <= 0:
        flags.append("NO_CANDIDATE")

    if timeline_count <= 0:
        flags.append("NO_TIMELINE")

    if final_caption_result is None:
        final_caption_result = {}

    selected_timelines = final_caption_result.get("selected_timelines", []) or []

    if not selected_timelines:
        flags.append("NO_SELECTED_CAPTION")

    valid_selected_count = 0

    for timeline in selected_timelines:
        role = timeline.get("caption_role")
        text = str(timeline.get("text") or "").strip()

        try:
            duration = float(timeline.get("duration", 0.0) or 0.0)
        except Exception:
            duration = 0.0

        if role in VALID_SELECTED_ROLES:
            valid_selected_count += 1

        if role in INVALID_SELECTED_ROLES:
            flags.append("INVALID_SELECTED_ROLE")

        if not text:
            flags.append("EMPTY_SELECTED_TEXT")

        if duration <= 0.15:
            flags.append("SELECTED_TIMELINE_TOO_SHORT")

    if selected_timelines and valid_selected_count <= 0:
        flags.append("NO_VALID_SELECTED_ROLE")

    return sorted(list(set(flags)))


def compact_timeline(timeline: Dict) -> Dict:
    score = timeline.get("score") or {}

    return {
        "text": timeline.get("text"),
        "start": timeline.get("start"),
        "end": timeline.get("end"),
        "duration": timeline.get("duration"),
        "sample_count": timeline.get("sample_count"),
        "line_count": score.get("best_line_count"),
        "header_only": score.get("header_only", False),
        "box": timeline.get("box"),
    }


def compact_final_timeline(timeline: Dict) -> Dict:
    return {
        "text": timeline.get("text"),
        "caption_role": timeline.get("caption_role"),
        "should_translate": timeline.get("should_translate"),
        "start": timeline.get("start"),
        "end": timeline.get("end"),
        "duration": timeline.get("duration"),
        "sample_count": timeline.get("sample_count"),
        "box": timeline.get("box"),
    }


def build_video_summary(result: Dict) -> Dict:
    if result.get("status") != "ok":
        return {
            "index": result.get("index"),
            "status": "error",
            "video_name": result.get("video_name"),
            "video_path": result.get("video_path"),
            "error": result.get("error"),
            "flags": ["ERROR"],
        }

    summary = result.get("summary") or {}
    video_info = result.get("video_info") or {}
    timelines = result.get("timelines") or []
    final_caption_selection = result.get("final_caption_selection") or {}
    flags = summary.get("flags") or []

    compact_timelines = [
        compact_timeline(timeline)
        for timeline in timelines
    ]

    timeline_texts = [
        timeline.get("text")
        for timeline in compact_timelines
        if timeline.get("text")
    ]

    selected_final_timelines = [
        compact_final_timeline(timeline)
        for timeline in final_caption_selection.get("selected_timelines", [])
    ]

    all_final_timelines = [
        compact_final_timeline(timeline)
        for timeline in final_caption_selection.get("all_timelines", [])
    ]

    selected_final_texts = [
        timeline.get("text")
        for timeline in selected_final_timelines
        if timeline.get("text")
    ]

    return {
        "index": result.get("index"),
        "status": "fail" if flags else "pass",
        "video_name": result.get("video_name"),
        "video_path": result.get("video_path"),
        "duration": video_info.get("duration"),
        "sample_count": summary.get("sample_count"),
        "total_ocr_items": summary.get("total_ocr_items"),
        "candidate_count": summary.get("candidate_count"),
        "timeline_count": summary.get("timeline_count"),
        "flags": flags,
        "timeline_texts": timeline_texts,
        "timelines": compact_timelines,
        "final_caption_selection": {
            "role_counts": final_caption_selection.get("role_counts", {}),
            "selected_timeline_count": final_caption_selection.get(
                "selected_timeline_count",
                0,
            ),
            "selected_timeline_texts": selected_final_texts,
            "selected_timelines": selected_final_timelines,
            "all_timelines": all_final_timelines,
        },
    }


def build_regression_summary(report: Dict) -> Dict:
    video_summaries = [
        build_video_summary(result)
        for result in report.get("results", [])
    ]

    pass_items = [
        item
        for item in video_summaries
        if item.get("status") == "pass"
    ]

    fail_items = [
        item
        for item in video_summaries
        if item.get("status") == "fail"
    ]

    error_items = [
        item
        for item in video_summaries
        if item.get("status") == "error"
    ]

    flag_counts = {}

    for item in video_summaries:
        for flag in item.get("flags", []):
            flag_counts[flag] = flag_counts.get(flag, 0) + 1

    role_counts_total = {}

    for item in video_summaries:
        final_caption_selection = item.get("final_caption_selection") or {}
        role_counts = final_caption_selection.get("role_counts") or {}

        for role, count in role_counts.items():
            role_counts_total[role] = role_counts_total.get(role, 0) + int(count)

    return {
        "status": "ok",
        "stage": "regression_summary",
        "source_report_path": report.get("report_path"),
        "latest_report_path": report.get("latest_path"),
        "video_count": report.get("video_count"),
        "pass_count": len(pass_items),
        "fail_count": len(fail_items),
        "error_count": len(error_items),
        "flag_counts": flag_counts,
        "role_counts_total": role_counts_total,
        "fail_videos": fail_items,
        "error_videos": error_items,
        "all_videos": video_summaries,
    }


def build_fail_only_summary(summary: Dict) -> Dict:
    fail_videos = []

    for video in summary.get("fail_videos", []):
        final_caption_selection = video.get("final_caption_selection") or {}

        fail_videos.append(
            {
                "video_name": video.get("video_name"),
                "flags": video.get("flags", []),
                "timeline_count": video.get("timeline_count"),
                "timeline_texts": (video.get("timeline_texts") or [])[:5],
                "timelines": (video.get("timelines") or [])[:5],
                "final_caption_selection": {
                    "role_counts": final_caption_selection.get("role_counts", {}),
                    "selected_timeline_count": final_caption_selection.get(
                        "selected_timeline_count",
                        0,
                    ),
                    "selected_timeline_texts": (
                        final_caption_selection.get("selected_timeline_texts")
                        or []
                    )[:10],
                    "selected_timelines": (
                        final_caption_selection.get("selected_timelines")
                        or []
                    )[:10],
                    "all_timelines": (
                        final_caption_selection.get("all_timelines")
                        or []
                    )[:10],
                },
            }
        )

    return {
        "status": "ok",
        "stage": "regression_fail_only",
        "video_count": summary.get("video_count", 0),
        "fail_count": summary.get("fail_count", 0),
        "flag_counts": summary.get("flag_counts", {}),
        "role_counts_total": summary.get("role_counts_total", {}),
        "fail_videos": fail_videos,
    }


def resolve_ocr_gpu(user_requested_gpu=None) -> bool:
    return should_use_gpu_ocr(user_requested_gpu=user_requested_gpu)


def analyze_video_for_regression(
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
) -> Dict:
    if languages is None:
        languages = ["en"]

    resolved_gpu = resolve_ocr_gpu(gpu)
    frame_limit = None if max_frames <= 0 else max_frames

    sample_result = analyze_sample_video(
        video_path=video_path,
        temp_dir=temp_dir,
        interval_sec=interval_sec,
        max_frames=frame_limit,
    )

    samples = sample_result["result"]["samples"]
    video_info = sample_result["result"]["video_info"]

    raw_ocr_result = read_sampled_frames_ocr(
        samples=samples,
        languages=languages,
        gpu=resolved_gpu,
        min_confidence=min_confidence,
        max_frames=frame_limit,
    )

    cleaned_ocr_result = clean_sampled_frames_ocr_result(raw_ocr_result)

    scored_ocr_result = score_sampled_frames_ocr(
        ocr_result=cleaned_ocr_result,
        frame_width=video_info["width"],
        frame_height=video_info["height"],
    )

    selected_result = select_caption_candidates_from_scored_frames(
        scored_ocr_result=scored_ocr_result,
        frame_width=video_info["width"],
        frame_height=video_info["height"],
        min_score=min_score,
    )

    timeline_result = build_caption_timelines(
        candidates=selected_result["candidates"],
        frame_interval_sec=interval_sec,
        max_gap_sec=max_gap_sec,
        similarity_threshold=similarity_threshold,
        token_threshold=token_threshold,
        min_box_similarity=min_box_similarity,
        min_samples=min_timeline_samples,
    )

    final_caption_result = select_final_caption_timelines(
        timeline_result=timeline_result,
        video_info=video_info,
    )

    flags = build_fail_flags(
        video_info=video_info,
        selected_result=selected_result,
        timeline_result=timeline_result,
        final_caption_result=final_caption_result,
    )

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
            "flags": flags,
        },
        "candidates_preview": [
            summarize_candidate(candidate)
            for candidate in selected_result.get("candidates", [])[:20]
        ],
        "timelines": [
            summarize_timeline(timeline)
            for timeline in timeline_result.get("timelines", [])
        ],
        "final_caption_selection": {
            "role_counts": final_caption_result.get("role_counts", {}),
            "selected_timeline_count": final_caption_result.get(
                "selected_timeline_count",
                0,
            ),
            "selected_timelines": [
                summarize_final_timeline(timeline)
                for timeline in final_caption_result.get(
                    "selected_timelines",
                    []
                )
            ],
            "all_timelines": [
                summarize_final_timeline(timeline)
                for timeline in final_caption_result.get(
                    "all_timelines",
                    []
                )
            ],
        },
    }


def run_regression(
    input_dir: str = DEFAULT_INPUT_DIR,
    report_dir: str = DEFAULT_REPORT_DIR,
    temp_dir: str = DEFAULT_TEMP_DIR,
    interval_sec: float = 0.25,
    max_frames: int = 0,
    languages: Optional[List[str]] = None,
    gpu=None,
) -> Dict:
    ensure_dir(input_dir)
    ensure_dir(temp_dir)

    report_dirs = ensure_report_dirs(report_dir)

    videos = list_video_files(input_dir)
    hardware_status = get_hardware_status()
    resolved_gpu = resolve_ocr_gpu(gpu)

    print("Hardware OCR status:")
    print(f"  NVIDIA driver: {hardware_status.get('nvidia_driver_detected')}")
    print(f"  Torch CUDA: {hardware_status.get('torch', {}).get('cuda_available')}")
    print(f"  Device: {hardware_status.get('torch', {}).get('device_name')}")
    print(f"  OCR GPU resolved: {resolved_gpu}")
    print(f"  Reason: {hardware_status.get('reason')}")

    started_at = datetime.now().isoformat(timespec="seconds")

    results = []

    for index, video_path in enumerate(videos, start=1):
        print(f"[{index}/{len(videos)}] Analyze: {video_path.name}")

        try:
            result = analyze_video_for_regression(
                video_path=str(video_path),
                temp_dir=temp_dir,
                interval_sec=interval_sec,
                max_frames=max_frames,
                languages=languages or ["en"],
                gpu=resolved_gpu,
            )

            result["index"] = index
            results.append(result)

            flags = result.get("summary", {}).get("flags", [])
            timeline_count = result.get("summary", {}).get("timeline_count", 0)
            final_selection = result.get("final_caption_selection") or {}
            role_counts = final_selection.get("role_counts", {})
            selected_count = final_selection.get("selected_timeline_count", 0)

            if flags:
                print(
                    "  -> WARN "
                    f"timeline_count={timeline_count} "
                    f"selected={selected_count} "
                    f"flags={flags} "
                    f"roles={role_counts}"
                )
            else:
                print(
                    "  -> OK "
                    f"timeline_count={timeline_count} "
                    f"selected={selected_count} "
                    f"roles={role_counts}"
                )

        except Exception as error:
            print(f"  -> ERROR {error}")

            results.append(
                {
                    "status": "error",
                    "index": index,
                    "video_path": str(video_path),
                    "video_name": video_path.name,
                    "error": str(error),
                    "traceback": traceback.format_exc(),
                }
            )

    finished_at = datetime.now().isoformat(timespec="seconds")

    report = {
        "status": "ok",
        "stage": "regression_analyze",
        "started_at": started_at,
        "finished_at": finished_at,
        "input_dir": input_dir,
        "report_dir": report_dir,
        "video_count": len(videos),
        "ok_count": len([item for item in results if item.get("status") == "ok"]),
        "error_count": len([item for item in results if item.get("status") == "error"]),
        "hardware": hardware_status,
        "settings": {
            "interval_sec": interval_sec,
            "max_frames": max_frames,
            "languages": languages or ["en"],
            "gpu_requested": gpu,
            "gpu_resolved": resolved_gpu,
        },
        "results": results,
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    report_name = f"regression_report_{timestamp}.json"

    report_path = os.path.join(
        report_dirs["full_report_dir"],
        report_name,
    )

    with open(report_path, "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)

    latest_path = os.path.join(
        report_dir,
        "regression_report_latest.json",
    )

    with open(latest_path, "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)

    report["report_path"] = report_path
    report["latest_path"] = latest_path

    summary = build_regression_summary(report)

    summary_name = f"regression_summary_{timestamp}.json"

    summary_path = os.path.join(
        report_dirs["summary_dir"],
        summary_name,
    )

    with open(summary_path, "w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    latest_summary_path = os.path.join(
        report_dir,
        "regression_summary_latest.json",
    )

    with open(latest_summary_path, "w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    fail_only = build_fail_only_summary(summary)

    fail_only_name = f"fail_only_{timestamp}.json"

    fail_only_path = os.path.join(
        report_dirs["fail_only_dir"],
        fail_only_name,
    )

    with open(fail_only_path, "w", encoding="utf-8") as file:
        json.dump(fail_only, file, ensure_ascii=False, indent=2)

    latest_fail_only_path = os.path.join(
        report_dir,
        "fail_only_latest.json",
    )

    with open(latest_fail_only_path, "w", encoding="utf-8") as file:
        json.dump(fail_only, file, ensure_ascii=False, indent=2)

    report["summary_path"] = summary_path
    report["latest_summary_path"] = latest_summary_path
    report["fail_only_path"] = fail_only_path
    report["latest_fail_only_path"] = latest_fail_only_path

    return report


if __name__ == "__main__":
    result = run_regression()

    print(
        json.dumps(
            {
                "status": result["status"],
                "video_count": result["video_count"],
                "ok_count": result["ok_count"],
                "error_count": result["error_count"],
                "gpu_resolved": result["settings"]["gpu_resolved"],
                "device_name": result["hardware"]["torch"]["device_name"],
                "report_path": result["report_path"],
                "latest_path": result["latest_path"],
                "summary_path": result["summary_path"],
                "latest_summary_path": result["latest_summary_path"],
                "fail_only_path": result["fail_only_path"],
                "latest_fail_only_path": result["latest_fail_only_path"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )