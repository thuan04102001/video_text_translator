import os
import shutil
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from core.ocr.ocr_cleaner import clean_sampled_frames_ocr_result
from core.ocr.reader import read_sampled_frames_ocr
from core.system.hardware_checker import should_use_gpu_ocr
from core.translation.language_detector import default_ocr_languages
from core.video.frame_sampler import analyze_sample_video
from core.video.video_writer import get_video_capture_info
from engines.meme_caption.caption_scorer import score_sampled_frames_ocr
from engines.meme_caption.caption_selector import (
    select_caption_candidates_from_scored_frames,
)
from engines.meme_caption.timeline_builder import build_caption_timelines

router = APIRouter(prefix="/analyze", tags=["Analyze"])

UPLOAD_DIR = "uploads"
TEMP_DIR = "temp"


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def save_upload_video(video: UploadFile) -> str:
    ensure_dir(UPLOAD_DIR)

    ext = os.path.splitext(video.filename or "")[1].lower()

    if ext not in [".mp4", ".mov", ".mkv", ".avi", ".webm"]:
        raise HTTPException(
            status_code=400,
            detail="File không phải video hợp lệ",
        )

    safe_name = f"{uuid.uuid4().hex}{ext}"
    upload_path = os.path.join(UPLOAD_DIR, safe_name)

    with open(upload_path, "wb") as buffer:
        shutil.copyfileobj(video.file, buffer)

    return upload_path


@router.post("/upload")
async def upload_video(video: UploadFile = File(...)):
    try:
        upload_path = save_upload_video(video)
        video_info = get_video_capture_info(upload_path)

        return {
            "status": "ok",
            "stage": "upload",
            "upload_path": upload_path,
            "video_info": video_info,
        }

    except HTTPException:
        raise

    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


def summarize_candidate(candidate: dict) -> dict:
    return {
        "sample_index": candidate.get("sample_index"),
        "time": candidate.get("time"),
        "frame_index": candidate.get("frame_index"),
        "image_path": candidate.get("image_path"),
        "text": candidate.get("text"),
        "normalized_text": candidate.get("normalized_text"),
        "box": candidate.get("box"),
        "confidence": candidate.get("confidence"),
        "score": candidate.get("score"),
        "line_count": len(candidate.get("source_items", [])),
    }


def summarize_timeline(timeline: dict) -> dict:
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


def build_pipeline_debug_summary(
    scored_ocr_result: dict,
    selected_result: dict,
    timeline_result: dict,
) -> dict:
    return {
        "ocr_frames": scored_ocr_result.get("frame_count", 0),
        "ocr_items": scored_ocr_result.get("total_ocr_items", 0),
        "selected_candidates": selected_result.get("candidate_count", 0),
        "timeline_count": timeline_result.get("timeline_count", 0),
        "timeline_durations": [
            timeline.get("duration", 0)
            for timeline in timeline_result.get("timelines", [])
        ],
    }


@router.post("/sample-frames")
async def sample_frames(
    video: UploadFile = File(...),
    interval_sec: float = Form(0.25),
    max_frames: int = Form(0),
):
    try:
        ensure_dir(TEMP_DIR)

        upload_path = save_upload_video(video)
        frame_limit = None if max_frames <= 0 else max_frames

        result = analyze_sample_video(
            video_path=upload_path,
            temp_dir=TEMP_DIR,
            interval_sec=interval_sec,
            max_frames=frame_limit,
        )

        video_info = result["result"]["video_info"]

        return {
            "status": "ok",
            "stage": "frame_sampling",
            "upload_path": upload_path,
            "video_info": {
                "fps": video_info["fps"],
                "frame_count": video_info["frame_count"],
                "width": video_info["width"],
                "height": video_info["height"],
                "duration": video_info["duration"],
            },
            "interval_sec": result["result"]["interval_sec"],
            "sample_count": result["result"]["sample_count"],
            "sample_output_dir": result["result"]["output_dir"],
            "samples_preview": result["result"]["samples"][:10],
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


@router.post("/sample-frames-ocr")
async def sample_frames_ocr(
    video: UploadFile = File(...),
    interval_sec: float = Form(0.25),
    max_frames: int = Form(10),
    languages: str = Form("en"),
    gpu: bool | None = Form(None),
    min_confidence: float = Form(0.15),
    min_score: float = Form(0.55),
    max_gap_sec: float = Form(0.6),
    similarity_threshold: float = Form(0.58),
    token_threshold: float = Form(0.55),
    min_box_similarity: float = Form(0.38),
    min_timeline_samples: int = Form(1),
):
    try:
        ensure_dir(TEMP_DIR)

        upload_path = save_upload_video(video)
        frame_limit = None if max_frames <= 0 else max_frames

        sample_result = analyze_sample_video(
            video_path=upload_path,
            temp_dir=TEMP_DIR,
            interval_sec=interval_sec,
            max_frames=frame_limit,
        )

        samples = sample_result["result"]["samples"]
        video_info = sample_result["result"]["video_info"]

        language_list = [
            item.strip()
            for item in languages.split(",")
            if item.strip()
        ]

        language_list = default_ocr_languages(language_list)

        resolved_gpu = should_use_gpu_ocr(user_requested_gpu=gpu)

        raw_ocr_result = read_sampled_frames_ocr(
            samples=samples,
            languages=language_list,
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

        frames_preview = []

        for frame in scored_ocr_result["frames"][:10]:
            frames_preview.append(
                {
                    "sample_index": frame["sample_index"],
                    "time": frame["time"],
                    "frame_index": frame["frame_index"],
                    "image_path": frame["image_path"],
                    "ocr_count": frame["ocr_count"],
                    "scored_count": frame["scored_count"],
                    "items": frame["items"][:10],
                }
            )

        candidates_preview = [
            summarize_candidate(candidate)
            for candidate in selected_result["candidates"][:10]
        ]

        timelines_preview = [
            summarize_timeline(timeline)
            for timeline in timeline_result["timelines"][:20]
        ]

        return {
            "status": "ok",
            "stage": "frame_sampling_ocr_cleaned_scored_selected_timeline",
            "upload_path": upload_path,
            "video_info": {
                "fps": video_info["fps"],
                "frame_count": video_info["frame_count"],
                "width": video_info["width"],
                "height": video_info["height"],
                "duration": video_info["duration"],
            },
            "interval_sec": sample_result["result"]["interval_sec"],
            "sample_count": sample_result["result"]["sample_count"],
            "sample_output_dir": sample_result["result"]["output_dir"],
            "debug_summary": build_pipeline_debug_summary(
                scored_ocr_result=scored_ocr_result,
                selected_result=selected_result,
                timeline_result=timeline_result,
            ),
            "ocr": {
                "languages": language_list,
                "gpu_requested": gpu,
                "gpu_resolved": resolved_gpu,
                "min_confidence": min_confidence,
                "min_score": min_score,
                "frame_count": scored_ocr_result["frame_count"],
                "total_ocr_items": scored_ocr_result["total_ocr_items"],
                "frames_preview": frames_preview,
            },
            "selection": {
                "candidate_count": selected_result["candidate_count"],
                "candidates_preview": candidates_preview,
            },
            "timeline": {
                "timeline_count": timeline_result["timeline_count"],
                "max_gap_sec": max_gap_sec,
                "similarity_threshold": similarity_threshold,
                "token_threshold": token_threshold,
                "min_box_similarity": min_box_similarity,
                "min_timeline_samples": min_timeline_samples,
                "timelines_preview": timelines_preview,
            },
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e),
        )
