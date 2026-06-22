from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.auto_reup_service import (
    check_fanpage_page_token,
    choose_action_gap_minutes,
    clean_post_content,
    create_action,
    create_job,
    create_page,
    create_source,
    delete_action,
    delete_job,
    delete_meta_user_token,
    delete_page,
    delete_source,
    fetch_meta_pages,
    get_action_runtime,
    import_meta_pages,
    list_actions,
    list_jobs,
    list_meta_user_tokens,
    list_pages,
    list_sources,
    open_facebook_login_session,
    render_action_video,
    request_action_scan,
    request_due_meta_user_token_syncs,
    request_meta_user_token_sync,
    summary,
    refresh_page_insights,
    update_action,
    update_job,
    update_meta_user_token,
    update_page,
    update_source,
    save_meta_user_token,
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


class MetaUserTokenCreate(BaseModel):
    label: str = ""
    access_token: str
    credential_type: str = "user_oauth"
    business_ids: list[str] = Field(default_factory=list)
    graph_version: str = ""
    auto_sync: bool = True
    check_interval_minutes: int = 360
    exchange_long_lived: bool = True


class MetaUserTokenUpdate(BaseModel):
    label: Optional[str] = None
    access_token: Optional[str] = None
    credential_type: Optional[str] = None
    business_ids: Optional[list[str]] = None
    graph_version: Optional[str] = None
    auto_sync: Optional[bool] = None
    check_interval_minutes: Optional[int] = None
    exchange_long_lived: Optional[bool] = None


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
    name: str = ""
    target_page_id: str = ""
    platform: str = "facebook"
    source_url: str
    template_id: str = ""
    translate_caption: bool = True
    apply_frame: bool = False
    creative_remove_source_audio: bool = True
    creative_randomize_variant: bool = True
    creative_smart_audio: bool = True
    creative_audio_volume: float = 1.0
    creative_custom_audio_path: str = ""
    content_cleaner_enabled: bool = True
    enabled: bool = True
    daily_limit: int = 3
    active_from: str = "09:00"
    active_to: str = "22:30"
    min_gap_minutes: int = 180
    max_gap_minutes: int = 250
    schedule_mode: str = "random_interval"
    manual_times: list[str] = Field(default_factory=list)
    smart_profile: str = "vn"
    jitter_minutes: int = 15
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
    creative_remove_source_audio: Optional[bool] = None
    creative_randomize_variant: Optional[bool] = None
    creative_smart_audio: Optional[bool] = None
    creative_audio_volume: Optional[float] = None
    creative_custom_audio_path: Optional[str] = None
    content_cleaner_enabled: Optional[bool] = None
    enabled: Optional[bool] = None
    daily_limit: Optional[int] = None
    active_from: Optional[str] = None
    active_to: Optional[str] = None
    min_gap_minutes: Optional[int] = None
    max_gap_minutes: Optional[int] = None
    schedule_mode: Optional[str] = None
    manual_times: Optional[list[str]] = None
    smart_profile: Optional[str] = None
    jitter_minutes: Optional[int] = None
    scan_interval_minutes: Optional[int] = None
    progress_total: Optional[int] = None
    progress_scanned: Optional[int] = None
    progress_posted: Optional[int] = None
    progress_errors: Optional[int] = None
    last_scan_at: Optional[str] = None
    notes: Optional[str] = None


class ReupActionRenderRequest(BaseModel):
    video_path: str
    output_dir: Optional[str] = None
    target_lang: str = "vi"
    source_lang: str = "en"
    translation_engine: str = "argos"
    frame_fit: Optional[str] = None


class ReupJobCreate(BaseModel):
    action_id: str = ""
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
    action_id: Optional[str] = None
    source_id: Optional[str] = None
    target_page_id: Optional[str] = None
    source_post_id: Optional[str] = None
    source_video_url: Optional[str] = None
    raw_content: Optional[str] = None
    clean_content: Optional[str] = None
    status: Optional[str] = None
    stage: Optional[str] = None
    progress: Optional[int] = None
    source_local_path: Optional[str] = None
    output_path: Optional[str] = None
    publish_id: Optional[str] = None
    attempts: Optional[int] = None
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


@router.get("/meta/tokens")
def auto_reup_list_meta_tokens():
    return {"tokens": list_meta_user_tokens()}


@router.post("/meta/tokens")
def auto_reup_create_meta_token(payload: MetaUserTokenCreate):
    try:
        token = save_meta_user_token(_model_payload(payload), validate=False)
        sync = request_meta_user_token_sync(token["id"])
        return {"token": token, "sync": sync}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.put("/meta/tokens/{token_id}")
def auto_reup_update_meta_token(token_id: str, payload: MetaUserTokenUpdate):
    try:
        token = update_meta_user_token(token_id, _model_payload(payload), validate=False)
        if payload.access_token:
            sync = request_meta_user_token_sync(token_id)
            return {"token": token, "sync": sync}
        return {"token": token}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.delete("/meta/tokens/{token_id}")
def auto_reup_delete_meta_token(token_id: str):
    try:
        return {"deleted": delete_meta_user_token(token_id)}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/meta/tokens/{token_id}/sync")
def auto_reup_sync_meta_token(token_id: str):
    try:
        return request_meta_user_token_sync(token_id)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/meta/tokens/sync-all")
def auto_reup_sync_all_meta_tokens():
    return {"results": request_due_meta_user_token_syncs(force=True)}


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


@router.post("/pages/{page_id}/check-token")
def auto_reup_check_page_token(
    page_id: str,
    token_id: Optional[str] = Query(None),
):
    try:
        return check_fanpage_page_token(page_id, token_id=token_id)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/pages/{page_id}/insights/refresh")
def auto_reup_refresh_page_insights(page_id: str):
    try:
        return {"insights": refresh_page_insights(page_id)}
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
        action = create_action(_model_payload(payload))
        scan = request_action_scan(action["id"], force=True) if action.get("enabled") else None
        return {"action": action, "scan": scan}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.put("/actions/{action_id}")
def auto_reup_update_action(action_id: str, payload: ReupActionUpdate):
    try:
        action = update_action(action_id, _model_payload(payload))
        scan = None
        changed = _model_payload(payload)
        if action.get("enabled") and (
            changed.get("enabled") is True
            or "source_url" in changed
            or "platform" in changed
        ):
            scan = request_action_scan(action_id, force=True)
        return {"action": action, "scan": scan}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.delete("/actions/{action_id}")
def auto_reup_delete_action(action_id: str):
    try:
        return {"deleted": delete_action(action_id)}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/actions/{action_id}/render")
def auto_reup_render_action(action_id: str, payload: ReupActionRenderRequest):
    try:
        return {
            "result": render_action_video(
                action_id=action_id,
                video_path=payload.video_path,
                output_dir=payload.output_dir,
                target_lang=payload.target_lang,
                source_lang=payload.source_lang,
                translation_engine=payload.translation_engine,
                frame_fit=payload.frame_fit,
            )
        }
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/actions/{action_id}/next-gap")
def auto_reup_next_action_gap(action_id: str):
    try:
        return {"minutes": choose_action_gap_minutes(action_id)}
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/actions/{action_id}/scan")
def auto_reup_scan_action(action_id: str):
    try:
        return request_action_scan(action_id, force=True)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/facebook/login-browser")
def auto_reup_open_facebook_login():
    try:
        return open_facebook_login_session()
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get("/actions/{action_id}/runtime")
def auto_reup_action_runtime(
    action_id: str,
    job_limit: int = Query(80, ge=1, le=200),
    event_limit: int = Query(160, ge=1, le=500),
):
    try:
        return get_action_runtime(
            action_id,
            job_limit=job_limit,
            event_limit=event_limit,
        )
    except Exception as error:
        raise HTTPException(status_code=404, detail=str(error))


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
