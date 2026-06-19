from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.auto_reup_service import (
    clean_post_content,
    create_action,
    create_job,
    create_page,
    create_source,
    delete_action,
    delete_job,
    delete_page,
    delete_source,
    fetch_meta_pages,
    import_meta_pages,
    list_actions,
    list_jobs,
    list_pages,
    list_sources,
    summary,
    update_action,
    update_job,
    update_page,
    update_source,
)


router = APIRouter(prefix="/auto-reup", tags=["Auto Reup"])


def _model_payload(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=True)
    return model.dict(exclude_unset=True)


class ContentCleanRequest(BaseModel):
    content: str = ""


class MetaTokenRequest(BaseModel):
    access_token: str
    graph_version: str = ""


class FanpageCreate(BaseModel):
    name: str
    page_id: str = ""
    access_status: str = "not_connected"
    is_enabled: bool = False
    daily_limit: int = 3
    active_from: str = "09:00"
    active_to: str = "22:30"
    min_gap_minutes: int = 180
    default_template_id: str = ""
    notes: str = ""


class FanpageUpdate(BaseModel):
    name: Optional[str] = None
    page_id: Optional[str] = None
    access_status: Optional[str] = None
    is_enabled: Optional[bool] = None
    daily_limit: Optional[int] = None
    active_from: Optional[str] = None
    active_to: Optional[str] = None
    min_gap_minutes: Optional[int] = None
    default_template_id: Optional[str] = None
    notes: Optional[str] = None


class ReupSourceCreate(BaseModel):
    name: str
    platform: str = "facebook"
    source_url: str
    target_page_id: str = ""
    template_id: str = ""
    translate_caption: bool = True
    apply_frame: bool = False
    enabled: bool = True
    scan_interval_minutes: int = 60


class ReupSourceUpdate(BaseModel):
    name: Optional[str] = None
    platform: Optional[str] = None
    source_url: Optional[str] = None
    target_page_id: Optional[str] = None
    template_id: Optional[str] = None
    translate_caption: Optional[bool] = None
    apply_frame: Optional[bool] = None
    enabled: Optional[bool] = None
    scan_interval_minutes: Optional[int] = None
    last_scan_at: Optional[str] = None


class ReupActionCreate(BaseModel):
    name: str
    target_page_id: str = ""
    platform: str = "facebook"
    source_url: str
    template_id: str = ""
    translate_caption: bool = True
    apply_frame: bool = False
    content_cleaner_enabled: bool = True
    enabled: bool = True
    daily_limit: int = 3
    active_from: str = "09:00"
    active_to: str = "22:30"
    min_gap_minutes: int = 180
    scan_interval_minutes: int = 60
    notes: str = ""


class ReupActionUpdate(BaseModel):
    name: Optional[str] = None
    target_page_id: Optional[str] = None
    platform: Optional[str] = None
    source_url: Optional[str] = None
    template_id: Optional[str] = None
    translate_caption: Optional[bool] = None
    apply_frame: Optional[bool] = None
    content_cleaner_enabled: Optional[bool] = None
    enabled: Optional[bool] = None
    daily_limit: Optional[int] = None
    active_from: Optional[str] = None
    active_to: Optional[str] = None
    min_gap_minutes: Optional[int] = None
    scan_interval_minutes: Optional[int] = None
    progress_total: Optional[int] = None
    progress_scanned: Optional[int] = None
    progress_posted: Optional[int] = None
    progress_errors: Optional[int] = None
    last_scan_at: Optional[str] = None
    notes: Optional[str] = None


class ReupJobCreate(BaseModel):
    source_id: str = ""
    target_page_id: str = ""
    source_post_id: str = ""
    source_video_url: str = ""
    raw_content: str = ""
    clean_content: str = ""
    status: str = "queued"
    scheduled_at: Optional[str] = None
    posted_at: Optional[str] = None
    error: str = ""


class ReupJobUpdate(BaseModel):
    source_id: Optional[str] = None
    target_page_id: Optional[str] = None
    source_post_id: Optional[str] = None
    source_video_url: Optional[str] = None
    raw_content: Optional[str] = None
    clean_content: Optional[str] = None
    status: Optional[str] = None
    scheduled_at: Optional[str] = None
    posted_at: Optional[str] = None
    error: Optional[str] = None


@router.get("/summary")
def auto_reup_summary():
    return summary()


@router.post("/content/clean")
def auto_reup_clean_content(payload: ContentCleanRequest):
    return clean_post_content(payload.content)


@router.post("/meta/pages")
def auto_reup_preview_meta_pages(payload: MetaTokenRequest):
    try:
        return fetch_meta_pages(
            payload.access_token,
            graph_version=payload.graph_version or None,
        )
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/meta/import-pages")
def auto_reup_import_meta_pages(payload: MetaTokenRequest):
    try:
        return import_meta_pages(
            payload.access_token,
            graph_version=payload.graph_version or None,
        )
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get("/pages")
def auto_reup_list_pages():
    return {"pages": list_pages()}


@router.post("/pages")
def auto_reup_create_page(payload: FanpageCreate):
    try:
        return {"page": create_page(_model_payload(payload))}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.put("/pages/{page_id}")
def auto_reup_update_page(page_id: str, payload: FanpageUpdate):
    try:
        return {"page": update_page(page_id, _model_payload(payload))}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.delete("/pages/{page_id}")
def auto_reup_delete_page(page_id: str):
    try:
        return {"deleted": delete_page(page_id)}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get("/sources")
def auto_reup_list_sources():
    return {"sources": list_sources()}


@router.post("/sources")
def auto_reup_create_source(payload: ReupSourceCreate):
    try:
        return {"source": create_source(_model_payload(payload))}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.put("/sources/{source_id}")
def auto_reup_update_source(source_id: str, payload: ReupSourceUpdate):
    try:
        return {"source": update_source(source_id, _model_payload(payload))}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.delete("/sources/{source_id}")
def auto_reup_delete_source(source_id: str):
    try:
        return {"deleted": delete_source(source_id)}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get("/actions")
def auto_reup_list_actions():
    return {"actions": list_actions()}


@router.post("/actions")
def auto_reup_create_action(payload: ReupActionCreate):
    try:
        return {"action": create_action(_model_payload(payload))}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.put("/actions/{action_id}")
def auto_reup_update_action(action_id: str, payload: ReupActionUpdate):
    try:
        return {"action": update_action(action_id, _model_payload(payload))}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.delete("/actions/{action_id}")
def auto_reup_delete_action(action_id: str):
    try:
        return {"deleted": delete_action(action_id)}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get("/jobs")
def auto_reup_list_jobs(
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    return {"jobs": list_jobs(status=status, limit=limit)}


@router.post("/jobs")
def auto_reup_create_job(payload: ReupJobCreate):
    try:
        return {"job": create_job(_model_payload(payload))}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/jobs/demo")
def auto_reup_create_demo_job(payload: ReupJobCreate):
    try:
        job = create_job(_model_payload(payload))
        return {
            "job": job,
            "clean_preview": {
                "clean_content": job["clean_content"],
                "removed_links": job["removed_links"],
                "removed_lines": job["removed_lines"],
            },
        }
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.put("/jobs/{job_id}")
def auto_reup_update_job(job_id: str, payload: ReupJobUpdate):
    try:
        return {"job": update_job(job_id, _model_payload(payload))}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.delete("/jobs/{job_id}")
def auto_reup_delete_job(job_id: str):
    try:
        return {"deleted": delete_job(job_id)}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))
