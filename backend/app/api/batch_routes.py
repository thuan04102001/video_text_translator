from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.batch_service import (
    cancel_batch_render,
    get_batch_status,
    pause_batch_render,
    reset_batch_render,
    resume_batch_render,
    scan_batch_folder,
    start_batch_render,
)

router = APIRouter(prefix="/batch", tags=["Batch"])


class BatchScanRequest(BaseModel):
    input_dir: str
    output_dir: str


class BatchStartRequest(BaseModel):
    input_dir: str
    output_dir: str
    threads: int = 1
    translation_mode: str = "argos"
    translate: bool = True
    apply_frame: bool = False
    frame_template_id: str | None = None
    frame_fit: str | None = None
    apply_creative_frame: bool = False
    creative_frame_template_id: str | None = None
    creative_frame_fit: str | None = None
    creative_remove_source_audio: bool = True
    creative_randomize_variant: bool = True
    creative_seed: int | None = None
    creative_smart_audio: bool = True
    creative_audio_profile: str = "auto"
    creative_audio_volume: float = 1.0
    creative_custom_audio_path: str | None = None
    trim_start_seconds: float = 0
    trim_end_seconds: float = 0


@router.post("/scan")
def scan_batch(payload: BatchScanRequest):
    try:
        return scan_batch_folder(
            input_dir=payload.input_dir,
            output_dir=payload.output_dir,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/start")
def start_batch(payload: BatchStartRequest):
    try:
        return start_batch_render(
            input_dir=payload.input_dir,
            output_dir=payload.output_dir,
            threads=payload.threads,
            translation_mode=payload.translation_mode,
            translate=payload.translate,
            apply_frame=payload.apply_frame,
            frame_template_id=payload.frame_template_id,
            frame_fit=payload.frame_fit,
            apply_creative_frame=payload.apply_creative_frame,
            creative_frame_template_id=payload.creative_frame_template_id,
            creative_frame_fit=payload.creative_frame_fit,
            creative_remove_source_audio=payload.creative_remove_source_audio,
            creative_randomize_variant=payload.creative_randomize_variant,
            creative_seed=payload.creative_seed,
            creative_smart_audio=payload.creative_smart_audio,
            creative_audio_profile=payload.creative_audio_profile,
            creative_audio_volume=payload.creative_audio_volume,
            creative_custom_audio_path=payload.creative_custom_audio_path,
            trim_start_seconds=payload.trim_start_seconds,
            trim_end_seconds=payload.trim_end_seconds,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/status")
def batch_status():
    return get_batch_status()


@router.post("/pause")
def pause_batch():
    return pause_batch_render()


@router.post("/resume")
def resume_batch():
    return resume_batch_render()


@router.post("/cancel")
def cancel_batch():
    return cancel_batch_render()


@router.post("/reset")
def reset_batch():
    return reset_batch_render()
