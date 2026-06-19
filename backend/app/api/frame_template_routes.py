from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.services.frame_template_service import (
    create_frame_template,
    delete_frame_template,
    get_frame_template_foreground_path,
    get_frame_template_thumbnail_path,
    list_frame_templates,
    update_frame_template,
)


router = APIRouter(prefix="/frame-templates", tags=["Frame Templates"])


@router.get("")
def frame_template_catalog():
    return {
        "templates": list_frame_templates(),
    }


@router.get("/{template_id}/thumbnail")
def frame_template_thumbnail(template_id: str):
    try:
        return FileResponse(get_frame_template_thumbnail_path(template_id))
    except Exception as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.get("/{template_id}/foreground")
def frame_template_foreground(template_id: str):
    try:
        return FileResponse(get_frame_template_foreground_path(template_id))
    except Exception as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.get("/{template_id}/foregrounds/{foreground_id}")
def frame_template_foreground_layer(template_id: str, foreground_id: str):
    try:
        return FileResponse(get_frame_template_foreground_path(template_id, foreground_id))
    except Exception as error:
        raise HTTPException(status_code=404, detail=str(error))


async def _read_uploads(files: Optional[List[UploadFile]]) -> List[dict]:
    uploads = []

    for file in files or []:
        if not file or not file.filename:
            continue

        uploads.append(
            {
                "filename": file.filename,
                "bytes": await file.read(),
            }
        )

    return uploads


def _template_response(template):
    return {
        "id": template["id"],
        "name": template["name"],
        "description": template["description"],
        "canvas": template["canvas"],
        "video_slot": template["video_slot"],
        "video_transform": template["video_transform"],
        "foregrounds": [
            {
                "id": foreground["id"],
                "asset": foreground["asset"],
                "order": foreground.get("order", 0),
                "transform": foreground["transform"],
                "size": foreground["size"],
                "url": f"/frame-templates/{template['id']}/foregrounds/{foreground['id']}",
            }
            for foreground in template["foregrounds"]
        ],
        "foreground_transform": template["foreground_transform"],
        "foreground_size": template["foreground_size"],
        "foreground_url": f"/frame-templates/{template['id']}/foreground" if template["foreground_path"] else "",
        "thumbnail_url": f"/frame-templates/{template['id']}/thumbnail",
        "voice_intro": template["voice_intro"],
        "background_sounds": template["background_sounds"],
        "outro": template["outro"],
    }


@router.post("")
async def create_frame_template_route(
    name: str = Form(...),
    description: str = Form(""),
    slot_x: int = Form(...),
    slot_y: int = Form(...),
    slot_width: int = Form(...),
    slot_height: int = Form(...),
    transform_zoom: float = Form(1.0),
    transform_offset_x: int = Form(0),
    transform_offset_y: int = Form(0),
    foreground_scale: float = Form(1.0),
    foreground_offset_x: int = Form(0),
    foreground_offset_y: int = Form(0),
    foreground_rotation: float = Form(0.0),
    fit: str = Form("cover"),
    foregrounds_config: str = Form(""),
    background: UploadFile = File(...),
    foreground: Optional[UploadFile] = File(None),
    foregrounds: Optional[List[UploadFile]] = File(None),
    thumbnail: Optional[UploadFile] = File(None),
    voice_intro: Optional[UploadFile] = File(None),
    background_sounds: Optional[List[UploadFile]] = File(None),
    outro: Optional[UploadFile] = File(None),
):
    try:
        foreground_files = await _read_uploads(foregrounds)
        background_sound_files = await _read_uploads(background_sounds)
        template = create_frame_template(
            name=name,
            description=description,
            background_filename=background.filename or "",
            background_bytes=await background.read(),
            foreground_filename=foreground.filename if foreground else None,
            foreground_bytes=await foreground.read() if foreground else None,
            foreground_files=foreground_files,
            foregrounds_config=foregrounds_config,
            thumbnail_filename=thumbnail.filename if thumbnail else None,
            thumbnail_bytes=await thumbnail.read() if thumbnail else None,
            voice_intro_filename=voice_intro.filename if voice_intro else None,
            voice_intro_bytes=await voice_intro.read() if voice_intro else None,
            background_sound_files=background_sound_files,
            outro_filename=outro.filename if outro else None,
            outro_bytes=await outro.read() if outro else None,
            slot_x=slot_x,
            slot_y=slot_y,
            slot_width=slot_width,
            slot_height=slot_height,
            transform_zoom=transform_zoom,
            transform_offset_x=transform_offset_x,
            transform_offset_y=transform_offset_y,
            foreground_scale=foreground_scale,
            foreground_offset_x=foreground_offset_x,
            foreground_offset_y=foreground_offset_y,
            foreground_rotation=foreground_rotation,
            fit=fit,
        )
        return {
            "status": "ok",
            "template": _template_response(template),
        }
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.put("/{template_id}")
async def update_frame_template_route(
    template_id: str,
    name: str = Form(...),
    description: str = Form(""),
    slot_x: int = Form(...),
    slot_y: int = Form(...),
    slot_width: int = Form(...),
    slot_height: int = Form(...),
    transform_zoom: float = Form(1.0),
    transform_offset_x: int = Form(0),
    transform_offset_y: int = Form(0),
    foreground_scale: float = Form(1.0),
    foreground_offset_x: int = Form(0),
    foreground_offset_y: int = Form(0),
    foreground_rotation: float = Form(0.0),
    fit: str = Form("cover"),
    foregrounds_config: str = Form(""),
    background: Optional[UploadFile] = File(None),
    foreground: Optional[UploadFile] = File(None),
    foregrounds: Optional[List[UploadFile]] = File(None),
    thumbnail: Optional[UploadFile] = File(None),
    voice_intro: Optional[UploadFile] = File(None),
    background_sounds: Optional[List[UploadFile]] = File(None),
    outro: Optional[UploadFile] = File(None),
):
    try:
        foreground_files = await _read_uploads(foregrounds)
        background_sound_files = await _read_uploads(background_sounds)
        template = update_frame_template(
            template_id=template_id,
            name=name,
            description=description,
            background_filename=background.filename if background else None,
            background_bytes=await background.read() if background else None,
            foreground_filename=foreground.filename if foreground else None,
            foreground_bytes=await foreground.read() if foreground else None,
            foreground_files=foreground_files,
            foregrounds_config=foregrounds_config,
            thumbnail_filename=thumbnail.filename if thumbnail else None,
            thumbnail_bytes=await thumbnail.read() if thumbnail else None,
            voice_intro_filename=voice_intro.filename if voice_intro else None,
            voice_intro_bytes=await voice_intro.read() if voice_intro else None,
            background_sound_files=background_sound_files,
            outro_filename=outro.filename if outro else None,
            outro_bytes=await outro.read() if outro else None,
            slot_x=slot_x,
            slot_y=slot_y,
            slot_width=slot_width,
            slot_height=slot_height,
            transform_zoom=transform_zoom,
            transform_offset_x=transform_offset_x,
            transform_offset_y=transform_offset_y,
            foreground_scale=foreground_scale,
            foreground_offset_x=foreground_offset_x,
            foreground_offset_y=foreground_offset_y,
            foreground_rotation=foreground_rotation,
            fit=fit,
        )
        return {
            "status": "ok",
            "template": _template_response(template),
        }
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.delete("/{template_id}")
def delete_frame_template_route(template_id: str):
    try:
        delete_frame_template(template_id)
        return {
            "status": "ok",
            "template_id": template_id,
        }
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))
