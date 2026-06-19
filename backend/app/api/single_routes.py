from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.analyze_service import analyze_video_for_production
from app.services.render_service import render_single_video
from core.translation.language_detector import default_ocr_languages


router = APIRouter()


class AnalyzeRequest(BaseModel):
    video_path: str
    languages: Optional[List[str]] = None
    gpu: Optional[bool] = None


class RenderRequest(BaseModel):
    video_path: str
    output_dir: Optional[str] = None
    source_lang: str = "en"
    target_lang: str = "vi"
    languages: Optional[List[str]] = None
    gpu: Optional[bool] = None
    translation_engine: str = "argos"
    translate: bool = True
    render_video: bool = True
    cleanup_temp: bool = True
    apply_frame: bool = False
    frame_template_id: Optional[str] = None
    frame_fit: Optional[str] = None
    trim_start_seconds: float = 0
    trim_end_seconds: float = 0


@router.post("/single/analyze")
def analyze_single_video(request: AnalyzeRequest):
    return analyze_video_for_production(
        video_path=request.video_path,
        languages=default_ocr_languages(request.languages),
        gpu=request.gpu,
    )


@router.post("/single/render")
def render_single_video_route(request: RenderRequest):
    return render_single_video(
        video_path=request.video_path,
        output_dir=request.output_dir,
        source_lang=request.source_lang,
        target_lang=request.target_lang,
        languages=default_ocr_languages(request.languages),
        gpu=request.gpu,
        translation_engine=request.translation_engine,
        translate=request.translate,
        render_video=request.render_video,
        cleanup_temp=request.cleanup_temp,
        apply_frame=request.apply_frame,
        frame_template_id=request.frame_template_id,
        frame_fit=request.frame_fit,
        trim_start_seconds=request.trim_start_seconds,
        trim_end_seconds=request.trim_end_seconds,
    )
