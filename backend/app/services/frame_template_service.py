import json
import math
import os
import random
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image, ImageOps

from core.video.audio_merge import get_ffmpeg_executable
from core.video.video_writer import get_video_capture_info


BACKEND_ROOT = Path(__file__).resolve().parents[2]
FRAME_TEMPLATES_DIR = BACKEND_ROOT / "frame_templates"
ALLOWED_FITS = {"cover", "contain", "stretch"}
ALLOWED_BACKGROUND_EXTENSIONS = {".png", ".jpg", ".jpeg", ".mp4", ".mov", ".webm"}
ALLOWED_FOREGROUND_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webm", ".mov", ".mp4"}
ALLOWED_THUMBNAIL_EXTENSIONS = {".png", ".jpg", ".jpeg"}
ALLOWED_VOICE_INTRO_EXTENSIONS = {".mp3"}
ALLOWED_BACKGROUND_SOUND_EXTENSIONS = {".mp3"}
ALLOWED_OUTRO_EXTENSIONS = {".mp4"}
FRAME_CANVAS_WIDTH = 1080
FRAME_CANVAS_HEIGHT = 1920


def _emit_progress(progress_callback, progress: float, **details) -> None:
    if progress_callback is None:
        return

    progress_callback(
        {
            "stage": "apply_frame",
            "progress": max(0.0, min(1.0, float(progress))),
            "stage_progress": max(0.0, min(1.0, float(progress))),
            **details,
        }
    )


def _safe_template_dir(template_id: str) -> Path:
    safe_id = str(template_id or "").strip()

    if not safe_id or safe_id in {".", ".."}:
        raise ValueError("Frame template id is required")

    if any(part in safe_id for part in ["/", "\\", ":"]):
        raise ValueError(f"Invalid frame template id: {safe_id}")

    template_dir = (FRAME_TEMPLATES_DIR / safe_id).resolve()
    root_dir = FRAME_TEMPLATES_DIR.resolve()

    if template_dir.parent != root_dir:
        raise ValueError(f"Invalid frame template path: {safe_id}")

    return template_dir


def _safe_asset_path(template_dir: Path, asset_name: Optional[str]) -> Optional[Path]:
    if not asset_name:
        return None

    asset_path = (template_dir / str(asset_name)).resolve()

    if template_dir.resolve() not in asset_path.parents:
        raise ValueError(f"Invalid frame template asset path: {asset_name}")

    return asset_path


def _positive_int(value, label: str) -> int:
    number = int(value or 0)

    if number <= 0:
        raise ValueError(f"{label} must be greater than zero")

    return number


def _slugify_template_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")

    if not slug:
        raise ValueError("Template name is required")

    return slug


def _validate_asset_extension(filename: str, allowed_extensions, label: str) -> str:
    extension = Path(str(filename or "")).suffix.lower()

    if extension not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise ValueError(f"{label} must use one of these formats: {allowed}")

    return extension


def _asset_dimensions(path: Path) -> tuple[int, int]:
    if path.suffix.lower() == ".gif":
        with Image.open(path) as image:
            return image.size

    if _is_video_asset(str(path)):
        info = get_video_capture_info(str(path))
        return int(info.get("width") or 0), int(info.get("height") or 0)

    with Image.open(path) as image:
        return image.size


def _validate_portrait_asset(path: Path, label: str) -> None:
    width, height = _asset_dimensions(path)

    if width <= 0 or height <= 0:
        raise ValueError(f"Cannot detect {label} dimensions")

    if width * 16 != height * 9:
        raise ValueError(f"{label} must use a 9:16 portrait ratio")


def _validate_readable_asset(path: Path, label: str) -> tuple[int, int]:
    width, height = _asset_dimensions(path)

    if width <= 0 or height <= 0:
        raise ValueError(f"Cannot detect {label} dimensions")

    return width, height


def _generate_thumbnail(background_path: Path, thumbnail_path: Path) -> None:
    source_path = background_path
    extracted_path = None

    if _is_video_asset(str(background_path)):
        ffmpeg_executable = get_ffmpeg_executable()

        if not ffmpeg_executable:
            raise RuntimeError("FFmpeg is required to generate video template thumbnails")

        extracted_path = background_path.parent / "_thumbnail_source.jpg"
        subprocess.run(
            [
                ffmpeg_executable,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(background_path),
                "-frames:v",
                "1",
                str(extracted_path),
            ],
            check=True,
        )
        source_path = extracted_path

    try:
        with Image.open(source_path) as image:
            thumbnail = ImageOps.fit(image.convert("RGB"), (270, 480), Image.Resampling.LANCZOS)
            thumbnail.save(thumbnail_path, "JPEG", quality=88, optimize=True)
    finally:
        if extracted_path and extracted_path.exists():
            extracted_path.unlink()


def _normalize_video_transform(zoom, offset_x, offset_y) -> Dict:
    try:
        normalized_zoom = float(zoom)
    except (TypeError, ValueError):
        normalized_zoom = 1.0

    normalized_zoom = max(0.5, min(3.0, normalized_zoom))

    return {
        "zoom": round(normalized_zoom, 3),
        "offset_x": int(offset_x or 0),
        "offset_y": int(offset_y or 0),
    }


def _normalize_foreground_transform(scale, offset_x, offset_y, rotation) -> Dict:
    try:
        normalized_scale = float(scale)
    except (TypeError, ValueError):
        normalized_scale = 1.0

    try:
        normalized_rotation = float(rotation)
    except (TypeError, ValueError):
        normalized_rotation = 0.0

    normalized_scale = max(0.05, min(6.0, normalized_scale))
    normalized_rotation = max(-180.0, min(180.0, normalized_rotation))

    return {
        "scale": round(normalized_scale, 3),
        "offset_x": int(offset_x or 0),
        "offset_y": int(offset_y or 0),
        "rotation": round(normalized_rotation, 2),
    }


def _parse_foregrounds_config(value) -> List[Dict]:
    if not value:
        return []

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            raise ValueError("foregrounds_config must be valid JSON")
    else:
        parsed = value

    if not isinstance(parsed, list):
        raise ValueError("foregrounds_config must be a list")

    return [item for item in parsed if isinstance(item, dict)]


def _foreground_asset_name(index: int, filename: str) -> str:
    extension = _validate_asset_extension(
        filename,
        ALLOWED_FOREGROUND_EXTENSIONS,
        "Foreground",
    )
    return f"foreground_{index}_{uuid.uuid4().hex[:8]}{extension}"


def _voice_intro_asset_name(filename: str) -> str:
    extension = _validate_asset_extension(
        filename,
        ALLOWED_VOICE_INTRO_EXTENSIONS,
        "Voice intro",
    )
    return f"voice_intro{extension}"


def _background_sound_asset_name(index: int, filename: str) -> str:
    extension = _validate_asset_extension(
        filename,
        ALLOWED_BACKGROUND_SOUND_EXTENSIONS,
        "Background sound",
    )
    return f"sound_{index}_{uuid.uuid4().hex[:8]}{extension}"


def _outro_asset_name(filename: str) -> str:
    extension = _validate_asset_extension(filename, ALLOWED_OUTRO_EXTENSIONS, "Outro")
    return f"outro{extension}"


def _save_template_media_file(
    template_dir: Path,
    filename: Optional[str],
    data: Optional[bytes],
    asset_name: Optional[str],
    label: str,
    existing_asset: Optional[str] = None,
) -> Optional[str]:
    if not filename or not data or not asset_name:
        return existing_asset

    asset_path = template_dir / asset_name
    asset_path.write_bytes(data)

    if not asset_path.is_file() or asset_path.stat().st_size <= 0:
        raise ValueError(f"{label} is empty or unreadable")

    if existing_asset and existing_asset != asset_name:
        existing_path = _safe_asset_path(template_dir, existing_asset)
        if existing_path and existing_path.is_file():
            existing_path.unlink()

    return asset_name


def _save_background_sound_files(
    template_dir: Path,
    sound_files: Optional[List[Dict]],
    existing_assets: Optional[List[str]] = None,
) -> Optional[List[str]]:
    files = sound_files or []

    if not files:
        return existing_assets

    next_assets: List[str] = []

    for index, file_payload in enumerate(files):
        asset_name = _background_sound_asset_name(index, file_payload.get("filename") or "")
        asset_path = template_dir / asset_name
        asset_path.write_bytes(file_payload.get("bytes") or b"")

        if not asset_path.is_file() or asset_path.stat().st_size <= 0:
            raise ValueError("Background sound is empty or unreadable")

        next_assets.append(asset_name)

    for old_asset in existing_assets or []:
        if old_asset in next_assets:
            continue

        old_path = _safe_asset_path(template_dir, old_asset)
        if old_path and old_path.is_file():
            old_path.unlink()

    return next_assets


def _foreground_item_from_config(item: Dict, legacy_index: int = 0) -> Dict:
    transform = dict(item.get("transform") or {})
    try:
        order = int(item.get("order", legacy_index))
    except (TypeError, ValueError):
        order = legacy_index

    return {
        "id": str(item.get("id") or f"fg_{legacy_index}_{uuid.uuid4().hex[:8]}"),
        "asset": str(item.get("asset") or ""),
        "order": order,
        "transform": _normalize_foreground_transform(
            transform.get("scale", 1.0),
            transform.get("offset_x", 0),
            transform.get("offset_y", 0),
            transform.get("rotation", 0.0),
        ),
    }


def _foreground_items_from_config(config: Dict) -> List[Dict]:
    foregrounds = config.get("foregrounds")

    if isinstance(foregrounds, list) and foregrounds:
        items = [
            _foreground_item_from_config(item, index)
            for index, item in enumerate(foregrounds)
            if isinstance(item, dict) and item.get("asset")
        ]
        return sorted(items, key=lambda item: item.get("order", 0))

    legacy_asset = config.get("foreground")
    if legacy_asset:
        legacy_transform = dict(config.get("foreground_transform") or {})
        return [
            {
                "id": "foreground_0",
                "asset": str(legacy_asset),
                "order": 0,
                "transform": _normalize_foreground_transform(
                    legacy_transform.get("scale", 1.0),
                    legacy_transform.get("offset_x", 0),
                    legacy_transform.get("offset_y", 0),
                    legacy_transform.get("rotation", 0.0),
                ),
            }
        ]

    return []


def _save_foreground_files(
    template_dir: Path,
    foreground_files: Optional[List[Dict]],
    foregrounds_config=None,
    existing_items: Optional[List[Dict]] = None,
) -> List[Dict]:
    config_items = _parse_foregrounds_config(foregrounds_config)
    files = foreground_files or []
    existing_by_id = {item["id"]: item for item in existing_items or []}
    next_items: List[Dict] = []
    used_assets = set()

    if config_items:
        for index, item in enumerate(config_items):
            transform = dict(item.get("transform") or {})
            normalized_transform = _normalize_foreground_transform(
                transform.get("scale", 1.0),
                transform.get("offset_x", 0),
                transform.get("offset_y", 0),
                transform.get("rotation", 0.0),
            )
            upload_index = item.get("upload_index")
            foreground_id = str(item.get("id") or f"fg_{uuid.uuid4().hex[:8]}")
            try:
                order = int(item.get("order", index))
            except (TypeError, ValueError):
                order = index

            if upload_index is not None:
                try:
                    file_payload = files[int(upload_index)]
                except (IndexError, TypeError, ValueError):
                    raise ValueError("Foreground upload index is invalid")

                asset_name = _foreground_asset_name(index, file_payload.get("filename") or "")
                asset_path = template_dir / asset_name
                asset_path.write_bytes(file_payload.get("bytes") or b"")
                _validate_readable_asset(asset_path, "Foreground")
            elif foreground_id in existing_by_id:
                asset_name = existing_by_id[foreground_id]["asset"]
            elif item.get("asset"):
                asset_name = str(item.get("asset"))
                asset_path = _safe_asset_path(template_dir, asset_name)
                if not asset_path or not asset_path.is_file():
                    raise FileNotFoundError(f"Missing frame template foreground: {asset_name}")
            else:
                continue

            used_assets.add(asset_name)
            next_items.append(
                {
                    "id": foreground_id,
                    "asset": asset_name,
                    "order": order,
                    "transform": normalized_transform,
                }
            )
    else:
        for index, file_payload in enumerate(files):
            asset_name = _foreground_asset_name(index, file_payload.get("filename") or "")
            asset_path = template_dir / asset_name
            asset_path.write_bytes(file_payload.get("bytes") or b"")
            _validate_readable_asset(asset_path, "Foreground")
            used_assets.add(asset_name)
            next_items.append(
                {
                    "id": f"fg_{uuid.uuid4().hex[:8]}",
                    "asset": asset_name,
                    "order": index,
                    "transform": _normalize_foreground_transform(1.0, 0, 0, 0.0),
                }
            )

    for old_item in existing_items or []:
        asset_name = old_item.get("asset")
        if not asset_name or asset_name in used_assets:
            continue

        old_path = _safe_asset_path(template_dir, asset_name)
        if old_path and old_path.is_file():
            old_path.unlink()

    ordered_items = sorted(next_items, key=lambda item: item.get("order", 0))
    for index, item in enumerate(ordered_items):
        item["order"] = index

    return ordered_items


def create_frame_template(
    name: str,
    background_filename: str,
    background_bytes: bytes,
    slot_x: int,
    slot_y: int,
    slot_width: int,
    slot_height: int,
    transform_zoom: float = 1.0,
    transform_offset_x: int = 0,
    transform_offset_y: int = 0,
    foreground_scale: float = 1.0,
    foreground_offset_x: int = 0,
    foreground_offset_y: int = 0,
    foreground_rotation: float = 0.0,
    fit: str = "cover",
    description: str = "",
    foreground_filename: Optional[str] = None,
    foreground_bytes: Optional[bytes] = None,
    foreground_files: Optional[List[Dict]] = None,
    foregrounds_config=None,
    thumbnail_filename: Optional[str] = None,
    thumbnail_bytes: Optional[bytes] = None,
    voice_intro_filename: Optional[str] = None,
    voice_intro_bytes: Optional[bytes] = None,
    background_sound_files: Optional[List[Dict]] = None,
    outro_filename: Optional[str] = None,
    outro_bytes: Optional[bytes] = None,
) -> Dict:
    template_id = _slugify_template_id(name)
    template_dir = _safe_template_dir(template_id)
    fit = str(fit or "cover").lower()

    if template_dir.exists():
        raise FileExistsError(f"Frame template already exists: {template_id}")

    if fit not in {"cover", "contain"}:
        raise ValueError(f"Unsupported editor frame fit: {fit}")

    slot = {
        "x": int(slot_x),
        "y": int(slot_y),
        "width": _positive_int(slot_width, "video_slot.width"),
        "height": _positive_int(slot_height, "video_slot.height"),
        "fit": fit,
    }

    if slot["x"] < 0 or slot["y"] < 0:
        raise ValueError("Frame template slot position cannot be negative")

    if slot["x"] + slot["width"] > FRAME_CANVAS_WIDTH or slot["y"] + slot["height"] > FRAME_CANVAS_HEIGHT:
        raise ValueError("Frame template slot must stay inside the 9:16 canvas")

    transform = _normalize_video_transform(
        transform_zoom,
        transform_offset_x,
        transform_offset_y,
    )
    background_extension = _validate_asset_extension(
        background_filename,
        ALLOWED_BACKGROUND_EXTENSIONS,
        "Background",
    )
    thumbnail_extension = (
        _validate_asset_extension(
            thumbnail_filename or "",
            ALLOWED_THUMBNAIL_EXTENSIONS,
            "Thumbnail",
        )
        if thumbnail_filename and thumbnail_bytes
        else ""
    )
    FRAME_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    temp_dir = FRAME_TEMPLATES_DIR / f".tmp_{template_id}_{uuid.uuid4().hex}"

    try:
        temp_dir.mkdir(parents=True, exist_ok=False)
        background_name = f"background{background_extension}"
        background_path = temp_dir / background_name
        background_path.write_bytes(background_bytes)
        _validate_portrait_asset(background_path, "Background")
        normalized_foreground_files = list(foreground_files or [])

        if foreground_filename and foreground_bytes:
            normalized_foreground_files.append(
                {
                    "filename": foreground_filename,
                    "bytes": foreground_bytes,
                }
            )

        if normalized_foreground_files and not foregrounds_config and foreground_filename:
            foregrounds_config = [
                {
                    "upload_index": 0,
                    "transform": _normalize_foreground_transform(
                        foreground_scale,
                        foreground_offset_x,
                        foreground_offset_y,
                        foreground_rotation,
                    ),
                }
            ]

        foreground_items = _save_foreground_files(
            temp_dir,
            normalized_foreground_files,
            foregrounds_config,
        )

        thumbnail_name = "thumbnail.jpg"
        thumbnail_path = temp_dir / thumbnail_name

        if thumbnail_extension:
            uploaded_thumbnail = temp_dir / f"_uploaded_thumbnail{thumbnail_extension}"
            uploaded_thumbnail.write_bytes(thumbnail_bytes or b"")
            with Image.open(uploaded_thumbnail) as image:
                thumbnail = ImageOps.fit(image.convert("RGB"), (270, 480), Image.Resampling.LANCZOS)
                thumbnail.save(thumbnail_path, "JPEG", quality=88, optimize=True)
            uploaded_thumbnail.unlink()
        else:
            _generate_thumbnail(background_path, thumbnail_path)

        config = {
            "id": template_id,
            "name": str(name).strip(),
            "description": str(description or "").strip(),
            "canvas": {
                "width": FRAME_CANVAS_WIDTH,
                "height": FRAME_CANVAS_HEIGHT,
            },
            "video_slot": slot,
            "video_transform": transform,
            "background": background_name,
            "thumbnail": thumbnail_name,
        }

        if foreground_items:
            config["foregrounds"] = foreground_items

        voice_intro_name = _save_template_media_file(
            temp_dir,
            voice_intro_filename,
            voice_intro_bytes,
            _voice_intro_asset_name(voice_intro_filename or "") if voice_intro_filename and voice_intro_bytes else None,
            "Voice intro",
        )
        background_sound_names = _save_background_sound_files(temp_dir, background_sound_files)
        outro_name = _save_template_media_file(
            temp_dir,
            outro_filename,
            outro_bytes,
            _outro_asset_name(outro_filename or "") if outro_filename and outro_bytes else None,
            "Outro",
        )

        if voice_intro_name:
            config["voice_intro"] = voice_intro_name

        if background_sound_names:
            config["background_sounds"] = background_sound_names

        if outro_name:
            config["outro"] = outro_name

        with (temp_dir / "template.json").open("w", encoding="utf-8") as file:
            json.dump(config, file, ensure_ascii=True, indent=2)

        shutil.move(str(temp_dir), str(template_dir))
        return load_frame_template(template_id)
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


def update_frame_template(
    template_id: str,
    name: str,
    slot_x: int,
    slot_y: int,
    slot_width: int,
    slot_height: int,
    transform_zoom: float = 1.0,
    transform_offset_x: int = 0,
    transform_offset_y: int = 0,
    foreground_scale: float = 1.0,
    foreground_offset_x: int = 0,
    foreground_offset_y: int = 0,
    foreground_rotation: float = 0.0,
    fit: str = "cover",
    description: str = "",
    background_filename: Optional[str] = None,
    background_bytes: Optional[bytes] = None,
    foreground_filename: Optional[str] = None,
    foreground_bytes: Optional[bytes] = None,
    foreground_files: Optional[List[Dict]] = None,
    foregrounds_config=None,
    thumbnail_filename: Optional[str] = None,
    thumbnail_bytes: Optional[bytes] = None,
    voice_intro_filename: Optional[str] = None,
    voice_intro_bytes: Optional[bytes] = None,
    background_sound_files: Optional[List[Dict]] = None,
    outro_filename: Optional[str] = None,
    outro_bytes: Optional[bytes] = None,
) -> Dict:
    template_dir = _safe_template_dir(template_id)
    config_path = template_dir / "template.json"

    if not config_path.is_file():
        raise FileNotFoundError(f"Frame template does not exist: {template_id}")

    fit = str(fit or "cover").lower()

    if fit not in {"cover", "contain"}:
        raise ValueError(f"Unsupported editor frame fit: {fit}")

    slot = {
        "x": int(slot_x),
        "y": int(slot_y),
        "width": _positive_int(slot_width, "video_slot.width"),
        "height": _positive_int(slot_height, "video_slot.height"),
        "fit": fit,
    }

    if slot["x"] < 0 or slot["y"] < 0:
        raise ValueError("Frame template slot position cannot be negative")

    if slot["x"] + slot["width"] > FRAME_CANVAS_WIDTH or slot["y"] + slot["height"] > FRAME_CANVAS_HEIGHT:
        raise ValueError("Frame template slot must stay inside the 9:16 canvas")

    transform = _normalize_video_transform(
        transform_zoom,
        transform_offset_x,
        transform_offset_y,
    )
    with config_path.open("r", encoding="utf-8") as file:
        config = json.load(file)
    existing_foregrounds = _foreground_items_from_config(config)

    config["id"] = str(config.get("id") or template_id)
    config["name"] = str(name or config.get("name") or template_id).strip()
    config["description"] = str(description or "").strip()
    config["canvas"] = {
        "width": FRAME_CANVAS_WIDTH,
        "height": FRAME_CANVAS_HEIGHT,
    }
    config["video_slot"] = slot
    config["video_transform"] = transform
    background_changed = False

    if background_filename and background_bytes:
        background_extension = _validate_asset_extension(
            background_filename,
            ALLOWED_BACKGROUND_EXTENSIONS,
            "Background",
        )
        background_name = f"background{background_extension}"
        background_path = template_dir / background_name
        background_path.write_bytes(background_bytes)
        _validate_portrait_asset(background_path, "Background")

        old_background = config.get("background")
        if old_background and old_background != background_name:
            old_background_path = _safe_asset_path(template_dir, old_background)
            if old_background_path and old_background_path.is_file():
                old_background_path.unlink()

        config["background"] = background_name
        background_changed = True

    normalized_foreground_files = list(foreground_files or [])

    if foreground_filename and foreground_bytes:
        normalized_foreground_files.append(
            {
                "filename": foreground_filename,
                "bytes": foreground_bytes,
            }
        )

    if normalized_foreground_files or foregrounds_config:
        if normalized_foreground_files and not foregrounds_config and foreground_filename:
            foregrounds_config = [
                {
                    "upload_index": 0,
                    "transform": _normalize_foreground_transform(
                        foreground_scale,
                        foreground_offset_x,
                        foreground_offset_y,
                        foreground_rotation,
                    ),
                }
            ]

        foreground_items = _save_foreground_files(
            template_dir,
            normalized_foreground_files,
            foregrounds_config,
            existing_foregrounds,
        )
        config["foregrounds"] = foreground_items
        config.pop("foreground", None)
        config.pop("foreground_transform", None)

    if thumbnail_filename and thumbnail_bytes:
        thumbnail_extension = _validate_asset_extension(
            thumbnail_filename,
            ALLOWED_THUMBNAIL_EXTENSIONS,
            "Thumbnail",
        )
        uploaded_thumbnail = template_dir / f"_uploaded_thumbnail{thumbnail_extension}"
        thumbnail_path = template_dir / "thumbnail.jpg"
        uploaded_thumbnail.write_bytes(thumbnail_bytes)

        try:
            with Image.open(uploaded_thumbnail) as image:
                thumbnail = ImageOps.fit(image.convert("RGB"), (270, 480), Image.Resampling.LANCZOS)
                thumbnail.save(thumbnail_path, "JPEG", quality=88, optimize=True)
        finally:
            if uploaded_thumbnail.exists():
                uploaded_thumbnail.unlink()

        config["thumbnail"] = "thumbnail.jpg"
    elif background_changed:
        _generate_thumbnail(
            _safe_asset_path(template_dir, config.get("background") or "background.png"),
            template_dir / "thumbnail.jpg",
        )
        config["thumbnail"] = "thumbnail.jpg"

    voice_intro_name = _save_template_media_file(
        template_dir,
        voice_intro_filename,
        voice_intro_bytes,
        _voice_intro_asset_name(voice_intro_filename or "") if voice_intro_filename and voice_intro_bytes else None,
        "Voice intro",
        existing_asset=config.get("voice_intro"),
    )
    background_sound_names = _save_background_sound_files(
        template_dir,
        background_sound_files,
        existing_assets=config.get("background_sounds") or [],
    )
    outro_name = _save_template_media_file(
        template_dir,
        outro_filename,
        outro_bytes,
        _outro_asset_name(outro_filename or "") if outro_filename and outro_bytes else None,
        "Outro",
        existing_asset=config.get("outro"),
    )

    if voice_intro_name:
        config["voice_intro"] = voice_intro_name

    if background_sound_names:
        config["background_sounds"] = background_sound_names

    if outro_name:
        config["outro"] = outro_name

    with config_path.open("w", encoding="utf-8") as file:
        json.dump(config, file, ensure_ascii=True, indent=2)

    return load_frame_template(template_id)


def delete_frame_template(template_id: str) -> None:
    template_dir = _safe_template_dir(template_id)

    if not template_dir.is_dir():
        raise FileNotFoundError(f"Frame template does not exist: {template_id}")

    shutil.rmtree(template_dir)


def load_frame_template(template_id: str) -> Dict:
    template_dir = _safe_template_dir(template_id)
    config_path = template_dir / "template.json"

    if not config_path.is_file():
        raise FileNotFoundError(f"Missing frame template config: {config_path}")

    with config_path.open("r", encoding="utf-8") as file:
        config = json.load(file)

    canvas = dict(config.get("canvas") or {})
    video_slot = dict(config.get("video_slot") or {})
    video_transform = dict(config.get("video_transform") or {})
    canvas_width = _positive_int(canvas.get("width"), "canvas.width")
    canvas_height = _positive_int(canvas.get("height"), "canvas.height")
    slot_x = int(video_slot.get("x") or 0)
    slot_y = int(video_slot.get("y") or 0)
    slot_width = _positive_int(video_slot.get("width"), "video_slot.width")
    slot_height = _positive_int(video_slot.get("height"), "video_slot.height")
    fit = str(video_slot.get("fit") or "cover").lower()
    transform = _normalize_video_transform(
        video_transform.get("zoom", 1.0),
        video_transform.get("offset_x", 0),
        video_transform.get("offset_y", 0),
    )
    if fit not in ALLOWED_FITS:
        raise ValueError(f"Unsupported frame template fit: {fit}")

    if slot_x < 0 or slot_y < 0:
        raise ValueError("Frame template slot position cannot be negative")

    if slot_x + slot_width > canvas_width or slot_y + slot_height > canvas_height:
        raise ValueError("Frame template slot must stay inside canvas")

    background_path = _safe_asset_path(
        template_dir,
        config.get("background") or "background.png",
    )
    thumbnail_path = _safe_asset_path(
        template_dir,
        config.get("thumbnail") or "thumbnail.jpg",
    )

    if not background_path or not background_path.is_file():
        raise FileNotFoundError(f"Missing frame template background: {background_path}")

    if thumbnail_path and not thumbnail_path.is_file():
        thumbnail_path = background_path

    voice_intro_path = _safe_asset_path(template_dir, config.get("voice_intro"))
    if voice_intro_path and not voice_intro_path.is_file():
        voice_intro_path = None

    background_sound_paths = []
    for sound_asset in config.get("background_sounds") or []:
        sound_path = _safe_asset_path(template_dir, sound_asset)
        if sound_path and sound_path.is_file():
            background_sound_paths.append(str(sound_path))

    outro_path = _safe_asset_path(template_dir, config.get("outro"))
    if outro_path and not outro_path.is_file():
        outro_path = None

    foregrounds = []

    for foreground_item in _foreground_items_from_config(config):
        foreground_path = _safe_asset_path(template_dir, foreground_item.get("asset"))

        if not foreground_path or not foreground_path.is_file():
            raise FileNotFoundError(f"Missing frame template foreground: {foreground_path}")

        foreground_width, foreground_height = _validate_readable_asset(foreground_path, "Foreground")
        foregrounds.append(
            {
                "id": foreground_item["id"],
                "asset": foreground_item["asset"],
                "order": foreground_item.get("order", len(foregrounds)),
                "transform": foreground_item["transform"],
                "size": {
                    "width": foreground_width,
                    "height": foreground_height,
                },
                "path": str(foreground_path),
            }
        )

    first_foreground = foregrounds[0] if foregrounds else None

    return {
        "id": str(config.get("id") or template_id),
        "name": str(config.get("name") or template_id),
        "description": str(config.get("description") or ""),
        "template_dir": str(template_dir),
        "canvas": {
            "width": canvas_width,
            "height": canvas_height,
        },
        "video_slot": {
            "x": slot_x,
            "y": slot_y,
            "width": slot_width,
            "height": slot_height,
            "fit": fit,
        },
        "video_transform": transform,
        "foregrounds": foregrounds,
        "foreground_transform": first_foreground["transform"] if first_foreground else _normalize_foreground_transform(1.0, 0, 0, 0.0),
        "foreground_size": first_foreground["size"] if first_foreground else {"width": 0, "height": 0},
        "background_path": str(background_path),
        "foreground_path": first_foreground["path"] if first_foreground else "",
        "thumbnail_path": str(thumbnail_path) if thumbnail_path else "",
        "voice_intro": str(config.get("voice_intro") or ""),
        "voice_intro_path": str(voice_intro_path) if voice_intro_path else "",
        "background_sounds": list(config.get("background_sounds") or []),
        "background_sound_paths": background_sound_paths,
        "outro": str(config.get("outro") or ""),
        "outro_path": str(outro_path) if outro_path else "",
    }


def list_frame_templates() -> List[Dict]:
    if not FRAME_TEMPLATES_DIR.is_dir():
        return []

    templates = []

    for template_dir in sorted(FRAME_TEMPLATES_DIR.iterdir()):
        if not template_dir.is_dir():
            continue

        try:
            template = load_frame_template(template_dir.name)
        except Exception:
            continue

        templates.append(
            {
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
                "has_foreground": bool(template["foreground_path"]),
                "foreground_url": f"/frame-templates/{template['id']}/foreground" if template["foreground_path"] else "",
                "thumbnail_url": f"/frame-templates/{template['id']}/thumbnail",
                "voice_intro": template["voice_intro"],
                "background_sounds": template["background_sounds"],
                "outro": template["outro"],
            }
        )

    return templates


def get_frame_template_thumbnail_path(template_id: str) -> str:
    template = load_frame_template(template_id)
    return template["thumbnail_path"]


def get_frame_template_foreground_path(template_id: str, foreground_id: Optional[str] = None) -> str:
    template = load_frame_template(template_id)

    if foreground_id:
        for foreground in template["foregrounds"]:
            if foreground["id"] == foreground_id:
                return foreground["path"]

        raise FileNotFoundError(f"Frame template foreground does not exist: {foreground_id}")

    if not template["foreground_path"]:
        raise FileNotFoundError(f"Frame template has no foreground: {template_id}")

    return template["foreground_path"]


def _is_video_asset(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in {".mp4", ".mov", ".mkv", ".webm", ".gif"}


def _ffprobe_executable(ffmpeg_executable: str) -> str:
    ffmpeg_path = Path(ffmpeg_executable)
    candidate = ffmpeg_path.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")

    if candidate.is_file():
        return str(candidate)

    return "ffprobe"


def _probe_duration(path: str, ffmpeg_executable: str) -> float:
    ffprobe = _ffprobe_executable(ffmpeg_executable)
    process = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    if process.returncode != 0:
        return 0.0

    try:
        return float(process.stdout.strip() or 0)
    except ValueError:
        return 0.0


def _has_audio_stream(path: str, ffmpeg_executable: str) -> bool:
    ffprobe = _ffprobe_executable(ffmpeg_executable)
    process = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return process.returncode == 0 and bool(process.stdout.strip())


def _run_ffmpeg(cmd: List[str], error_message: str) -> None:
    process = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    if process.returncode != 0:
        raise RuntimeError((process.stderr or "").strip() or error_message)


def _background_video_input_args(background_path: str) -> List[str]:
    if _is_video_asset(background_path):
        return ["-stream_loop", "-1", "-i", background_path]

    return ["-loop", "1", "-framerate", "30", "-i", background_path]


def _write_concat_file(path: str, files: List[str]) -> None:
    with open(path, "w", encoding="utf-8") as file:
        for item in files:
            normalized = os.path.abspath(item).replace("\\", "/").replace("'", "'\\''")
            file.write(f"file '{normalized}'\n")


def _make_intro_clip(
    ffmpeg_executable: str,
    background_path: str,
    voice_intro_path: str,
    output_path: str,
    canvas: Dict,
) -> float:
    duration = _probe_duration(voice_intro_path, ffmpeg_executable)

    if duration <= 0:
        raise RuntimeError("Cannot detect voice intro duration")

    cmd = [
        ffmpeg_executable,
        "-y",
        "-loglevel",
        "error",
        *_background_video_input_args(background_path),
        "-i",
        voice_intro_path,
        "-filter_complex",
        (
            f"[0:v]scale={canvas['width']}:{canvas['height']}:force_original_aspect_ratio=decrease,"
            f"pad={canvas['width']}:{canvas['height']}:(ow-iw)/2:(oh-ih)/2:color=black,"
            "format=yuv420p[v]"
        ),
        "-map",
        "[v]",
        "-map",
        "1:a:0",
        "-t",
        f"{duration:.6f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        output_path,
    ]
    _run_ffmpeg(cmd, "FFmpeg voice intro render failed")
    return duration


def _normalize_clip(
    ffmpeg_executable: str,
    input_path: str,
    output_path: str,
    canvas: Dict,
    duration: Optional[float] = None,
) -> float:
    clip_duration = duration or _probe_duration(input_path, ffmpeg_executable)

    if clip_duration <= 0:
        raise RuntimeError(f"Cannot detect clip duration: {input_path}")

    has_audio = _has_audio_stream(input_path, ffmpeg_executable)
    cmd = [ffmpeg_executable, "-y", "-loglevel", "error", "-i", input_path]

    if not has_audio:
        cmd.extend(["-f", "lavfi", "-t", f"{clip_duration:.6f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"])

    cmd.extend(
        [
            "-filter_complex",
            (
                f"[0:v]scale={canvas['width']}:{canvas['height']}:force_original_aspect_ratio=decrease,"
                f"pad={canvas['width']}:{canvas['height']}:(ow-iw)/2:(oh-ih)/2:color=black,"
                "format=yuv420p[v]"
            ),
            "-map",
            "[v]",
            "-map",
            "0:a:0" if has_audio else "1:a:0",
            "-t",
            f"{clip_duration:.6f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            output_path,
        ]
    )
    _run_ffmpeg(cmd, "FFmpeg clip normalize failed")
    return clip_duration


def _concat_clips(ffmpeg_executable: str, clips: List[str], output_path: str) -> None:
    if len(clips) == 1:
        shutil.copyfile(clips[0], output_path)
        return

    concat_path = os.path.join(os.path.dirname(output_path), f"concat_{uuid.uuid4().hex}.txt")

    try:
        _write_concat_file(concat_path, clips)
        _run_ffmpeg(
            [
                ffmpeg_executable,
                "-y",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_path,
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                output_path,
            ],
            "FFmpeg clip concat failed",
        )
    finally:
        if os.path.isfile(concat_path):
            os.remove(concat_path)


def _build_random_background_audio(
    ffmpeg_executable: str,
    sound_paths: List[str],
    duration: float,
    output_path: str,
) -> bool:
    if not sound_paths or duration <= 0:
        return False

    playlist: List[str] = []
    elapsed = 0.0
    guard = 0

    while elapsed < duration and guard < 500:
        sound_path = random.choice(sound_paths)
        sound_duration = _probe_duration(sound_path, ffmpeg_executable)

        if sound_duration <= 0:
            guard += 1
            continue

        playlist.append(sound_path)
        elapsed += sound_duration
        guard += 1

    if not playlist:
        return False

    concat_path = os.path.join(os.path.dirname(output_path), f"sounds_{uuid.uuid4().hex}.txt")

    try:
        _write_concat_file(concat_path, playlist)
        _run_ffmpeg(
            [
                ffmpeg_executable,
                "-y",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_path,
                "-t",
                f"{duration:.6f}",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                output_path,
            ],
            "FFmpeg random background audio render failed",
        )
        return os.path.isfile(output_path)
    finally:
        if os.path.isfile(concat_path):
            os.remove(concat_path)


def _mix_background_audio(
    ffmpeg_executable: str,
    input_video_path: str,
    background_audio_path: str,
    output_path: str,
) -> None:
    _run_ffmpeg(
        [
            ffmpeg_executable,
            "-y",
            "-loglevel",
            "error",
            "-i",
            input_video_path,
            "-i",
            background_audio_path,
            "-filter_complex",
            "[1:a]volume=0.22[bg];[0:a:0][bg]amix=inputs=2:duration=first:dropout_transition=0[aout]",
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            output_path,
        ],
        "FFmpeg background audio mix failed",
    )


def _finalize_frame_template_media(
    ffmpeg_executable: str,
    main_video_path: str,
    output_path: str,
    template: Dict,
    canvas: Dict,
    main_duration: float,
    work_dir: str,
) -> None:
    clips: List[str] = []
    voice_intro_path = template.get("voice_intro_path") or ""
    background_sound_paths = template.get("background_sound_paths") or []
    outro_path = template.get("outro_path") or ""

    if voice_intro_path:
        intro_clip = os.path.join(work_dir, "intro.mp4")
        _make_intro_clip(
            ffmpeg_executable,
            template["background_path"],
            voice_intro_path,
            intro_clip,
            canvas,
        )
        clips.append(intro_clip)

    normalized_main = os.path.join(work_dir, "main_normalized.mp4")
    _normalize_clip(ffmpeg_executable, main_video_path, normalized_main, canvas, duration=main_duration)
    clips.append(normalized_main)

    if outro_path:
        outro_clip = os.path.join(work_dir, "outro.mp4")
        _normalize_clip(ffmpeg_executable, outro_path, outro_clip, canvas)
        clips.append(outro_clip)

    sequence_path = os.path.join(work_dir, "sequence.mp4")
    _concat_clips(ffmpeg_executable, clips, sequence_path)

    sequence_duration = _probe_duration(sequence_path, ffmpeg_executable)
    background_audio_path = os.path.join(work_dir, "background_sound.m4a")

    if _build_random_background_audio(
        ffmpeg_executable,
        background_sound_paths,
        sequence_duration,
        background_audio_path,
    ):
        _mix_background_audio(ffmpeg_executable, sequence_path, background_audio_path, output_path)
    else:
        shutil.copyfile(sequence_path, output_path)


def _slot_filter(slot: Dict, fit: str, transform: Optional[Dict] = None) -> str:
    width = slot["width"]
    height = slot["height"]
    transform = _normalize_video_transform(
        (transform or {}).get("zoom", 1.0),
        (transform or {}).get("offset_x", 0),
        (transform or {}).get("offset_y", 0),
    )
    zoom = transform["zoom"]
    offset_x = transform["offset_x"]
    offset_y = transform["offset_y"]
    zoom_filter = f"scale=trunc(iw*{zoom}/2)*2:trunc(ih*{zoom}/2)*2"
    crop_x = (
        f"if(gte(iw,{width}),"
        f"min(max((iw-{width})/2-({offset_x}),0),iw-{width}),0)"
    )
    crop_y = (
        f"if(gte(ih,{height}),"
        f"min(max((ih-{height})/2-({offset_y}),0),ih-{height}),0)"
    )
    pad_x = (
        f"if(lt(iw,{width}),"
        f"min(max(({width}-iw)/2+({offset_x}),0),{width}-iw),0)"
    )
    pad_y = (
        f"if(lt(ih,{height}),"
        f"min(max(({height}-ih)/2+({offset_y}),0),{height}-ih),0)"
    )
    frame_filter = (
        f"{zoom_filter},"
        f"crop=w='min(iw,{width})':h='min(ih,{height})':x='{crop_x}':y='{crop_y}',"
        f"pad={width}:{height}:x='{pad_x}':y='{pad_y}':color=black"
    )

    if fit == "cover":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"{frame_filter}"
        )

    if fit == "contain":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"{frame_filter}"
        )

    return f"scale={width}:{height},{frame_filter}"


def render_video_with_frame_template(
    input_video_path: str,
    output_path: str,
    template_id: str,
    fit_override: Optional[str] = None,
    progress_callback=None,
) -> Dict:
    if not os.path.isfile(input_video_path):
        raise FileNotFoundError(f"Input video does not exist: {input_video_path}")

    ffmpeg_executable = get_ffmpeg_executable()

    if not ffmpeg_executable:
        raise RuntimeError("FFmpeg is required to apply a frame template")

    template = load_frame_template(template_id)
    canvas = template["canvas"]
    slot = template["video_slot"]
    transform = template["video_transform"]
    fit = str(fit_override or slot["fit"]).lower()

    if fit not in ALLOWED_FITS:
        raise ValueError(f"Unsupported frame fit: {fit}")

    video_info = get_video_capture_info(input_video_path)
    duration = float(video_info.get("duration") or 0.0)

    if duration <= 0:
        raise RuntimeError(f"Cannot detect video duration: {input_video_path}")

    output_dir = os.path.dirname(output_path)

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    background_path = template["background_path"]
    foregrounds = template["foregrounds"]
    render_foregrounds = list(reversed(foregrounds))
    has_template_media = bool(
        template.get("voice_intro_path")
        or template.get("background_sound_paths")
        or template.get("outro_path")
    )
    work_dir = tempfile.mkdtemp(prefix="frame_template_") if has_template_media else ""
    render_output_path = os.path.join(work_dir, "main_framed.mp4") if has_template_media else output_path
    cmd = [ffmpeg_executable, "-y", "-loglevel", "error"]

    if _is_video_asset(background_path):
        cmd.extend(["-stream_loop", "-1", "-i", background_path])
    else:
        cmd.extend(["-loop", "1", "-framerate", "30", "-i", background_path])

    cmd.extend(["-i", input_video_path])

    for foreground in render_foregrounds:
        foreground_path = foreground["path"]
        if _is_video_asset(foreground_path):
            cmd.extend(["-stream_loop", "-1", "-i", foreground_path])
        else:
            cmd.extend(["-loop", "1", "-framerate", "30", "-i", foreground_path])

    filter_parts = [
        (
            f"[0:v]scale={canvas['width']}:{canvas['height']}:"
            "force_original_aspect_ratio=decrease,"
            f"pad={canvas['width']}:{canvas['height']}:(ow-iw)/2:(oh-ih)/2:"
            "color=black[frame_bg]"
        ),
        f"[1:v]{_slot_filter(slot, fit, transform)}[slot_video]",
        f"[frame_bg][slot_video]overlay={slot['x']}:{slot['y']}:shortest=1[composite]",
    ]
    output_label = "composite"

    for foreground_index, foreground in enumerate(render_foregrounds):
        input_index = foreground_index + 2
        foreground_transform = foreground["transform"]
        foreground_scale = foreground_transform["scale"]
        foreground_rotation = math.radians(foreground_transform["rotation"])
        foreground_offset_x = foreground_transform["offset_x"]
        foreground_offset_y = foreground_transform["offset_y"]
        foreground_label = f"frame_fg_{foreground_index}"
        next_output_label = f"framed_{foreground_index}"

        filter_parts.append(
            f"[{input_index}:v]format=rgba,"
            f"scale=trunc(iw*{foreground_scale}/2)*2:trunc(ih*{foreground_scale}/2)*2,"
            f"rotate={foreground_rotation:.8f}:c=none:"
            f"ow=rotw({foreground_rotation:.8f}):oh=roth({foreground_rotation:.8f})"
            f"[{foreground_label}]"
        )
        filter_parts.append(
            f"[{output_label}][{foreground_label}]"
            f"overlay=(main_w-overlay_w)/2+({foreground_offset_x}):"
            f"(main_h-overlay_h)/2+({foreground_offset_y}):shortest=1[{next_output_label}]"
        )
        output_label = next_output_label

    cmd.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            f"[{output_label}]",
            "-map",
            "1:a?",
            "-t",
            f"{duration:.6f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            "-nostats",
            render_output_path,
        ]
    )

    _emit_progress(progress_callback, 0.0, template_id=template_id, fit=fit)
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stderr = ""

    try:
        for line in process.stdout or []:
            key, separator, value = line.strip().partition("=")

            if not separator:
                continue

            if key == "out_time_ms":
                try:
                    rendered_seconds = int(value) / 1_000_000
                except ValueError:
                    continue

                _emit_progress(
                    progress_callback,
                    rendered_seconds / duration,
                    template_id=template_id,
                    fit=fit,
                )

        stderr = (process.stderr.read() if process.stderr else "").strip()
        return_code = process.wait()
    finally:
        if process.poll() is None:
            process.kill()

    if return_code != 0:
        if work_dir and os.path.isdir(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
        raise RuntimeError(stderr or "FFmpeg frame template render failed")

    if not os.path.isfile(render_output_path):
        if work_dir and os.path.isdir(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
        raise RuntimeError("Frame template render did not produce an output file")

    try:
        if has_template_media:
            _emit_progress(progress_callback, 0.98, template_id=template_id, fit=fit)
            _finalize_frame_template_media(
                ffmpeg_executable,
                render_output_path,
                output_path,
                template,
                canvas,
                duration,
                work_dir,
            )

        if not os.path.isfile(output_path):
            raise RuntimeError("Frame template render did not produce an output file")
    finally:
        if work_dir and os.path.isdir(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)

    _emit_progress(progress_callback, 1.0, template_id=template_id, fit=fit)

    return {
        "status": "ok",
        "stage": "apply_frame",
        "template_id": template_id,
        "template_name": template["name"],
        "fit": fit,
        "input_video_path": input_video_path,
        "output_path": output_path,
        "duration": duration,
        "canvas": canvas,
        "video_slot": slot,
        "video_transform": transform,
        "voice_intro": template.get("voice_intro") or "",
        "background_sounds": template.get("background_sounds") or [],
        "outro": template.get("outro") or "",
        "foregrounds": [
            {
                "id": foreground["id"],
                "transform": foreground["transform"],
                "size": foreground["size"],
            }
            for foreground in foregrounds
        ],
        "foreground_transform": template["foreground_transform"],
    }
