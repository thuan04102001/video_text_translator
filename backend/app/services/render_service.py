import os
import re
import subprocess
import tempfile
from typing import Dict, List, Optional

from app.services.analyze_service import DEFAULT_TEMP_DIR, analyze_video_for_production
from app.services.frame_template_service import render_video_with_frame_template
from core.system.runtime_cleanup import cleanup_file, cleanup_sample_session_dir
from core.translation.meme_translation_memory import (
    get_approved_translation,
    load_memory,
    remember_pending_case,
    repair_ocr_text,
)
from core.translation.language_detector import (
    SUB_FAIL_TEXT,
    default_ocr_languages,
    find_non_english_adjacent_pair,
    is_english_caption,
)
from core.translation.meme_semantic_translator import (
    build_translation_context,
    rewrite_after_argos,
    semantic_translate_before_argos,
)
from core.translation.translator_router import translate_text
from core.video.audio_merge import copy_video_file, get_ffmpeg_executable, merge_audio_or_copy
from core.video.video_writer import get_video_capture_info, render_video_to_temp_without_audio


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
        stage_progress = source_event.pop("stage_progress", None)

        if stage_progress is None and source_stage == "render_video_without_audio":
            stage_progress = source_progress

        _emit_progress(
            progress_callback,
            stage,
            start + ((end - start) * max(0.0, min(1.0, source_progress))),
            source_stage=source_stage,
            detail_stage=detail_stage,
            stage_progress=stage_progress,
            **source_event,
        )

    return report


def make_done_output_path(
    video_path: str,
    output_dir: Optional[str] = None,
) -> str:
    input_dir = os.path.dirname(video_path)
    basename = os.path.basename(video_path)
    name, _ext = os.path.splitext(basename)

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        return os.path.join(output_dir, f"{name}-done.mp4")

    return os.path.join(input_dir, f"{name}-done.mp4")


def _normalize_trim_seconds(value: Optional[float]) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0

    return max(0.0, number)


def _run_ffmpeg_trim(
    input_path: str,
    output_path: str,
    start_seconds: float,
    duration_seconds: float,
    progress_callback=None,
) -> None:
    ffmpeg_executable = get_ffmpeg_executable()

    if not ffmpeg_executable:
        raise RuntimeError("FFmpeg not found. Cannot trim video.")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    cmd = [
        ffmpeg_executable,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start_seconds:.6f}",
        "-i",
        input_path,
        "-t",
        f"{duration_seconds:.6f}",
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
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
        output_path,
    ]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    stderr_lines: List[str] = []

    if process.stdout:
        for line in process.stdout:
            text = line.strip()
            if not text.startswith("out_time_ms="):
                continue

            try:
                rendered_seconds = int(text.split("=", 1)[1]) / 1_000_000
            except ValueError:
                continue

            _emit_progress(
                progress_callback,
                "trim_video",
                min(0.98, rendered_seconds / duration_seconds),
                stage_progress=min(0.98, rendered_seconds / duration_seconds),
            )

    if process.stderr:
        stderr_lines.append(process.stderr.read())

    return_code = process.wait()

    if return_code != 0:
        stderr = "\n".join(part for part in stderr_lines if part).strip()
        raise RuntimeError(stderr or "FFmpeg trim failed")

    if not os.path.isfile(output_path):
        raise RuntimeError("Trim did not produce an output file")

    _emit_progress(progress_callback, "trim_video", 1.0, stage_progress=1.0)


def _prepare_trimmed_input(
    video_path: str,
    output_path: str,
    trim_start_seconds: Optional[float] = 0,
    trim_end_seconds: Optional[float] = 0,
    progress_callback=None,
) -> Dict:
    trim_start = _normalize_trim_seconds(trim_start_seconds)
    trim_end = _normalize_trim_seconds(trim_end_seconds)

    if trim_start <= 0 and trim_end <= 0:
        return {
            "enabled": False,
            "input_path": video_path,
            "temp_path": None,
            "cleanup": False,
            "start_seconds": 0.0,
            "end_seconds": 0.0,
            "duration": None,
            "output_duration": None,
        }

    video_info = get_video_capture_info(video_path)
    duration = float(video_info.get("duration") or 0.0)
    output_duration = duration - trim_start - trim_end

    if duration <= 0:
        raise RuntimeError(f"Cannot detect video duration: {video_path}")

    if output_duration <= 0.05:
        raise ValueError(
            "TRIM FAIL: trim start/end is longer than the input video duration"
        )

    trim_dir = os.path.join(tempfile.gettempdir(), "video_text_translator_trim")
    os.makedirs(trim_dir, exist_ok=True)

    output_name = os.path.splitext(os.path.basename(output_path))[0]
    temp_path = os.path.join(
        trim_dir,
        f"{output_name}_trim_{os.getpid()}_{abs(hash((video_path, trim_start, trim_end))) & 0xffffffff:x}.mp4",
    )

    cleanup_file(temp_path)
    _emit_progress(progress_callback, "trim_video", 0.0, stage_progress=0.0)
    _run_ffmpeg_trim(
        input_path=video_path,
        output_path=temp_path,
        start_seconds=trim_start,
        duration_seconds=output_duration,
        progress_callback=progress_callback,
    )

    return {
        "enabled": True,
        "input_path": temp_path,
        "temp_path": temp_path,
        "cleanup": True,
        "start_seconds": trim_start,
        "end_seconds": trim_end,
        "duration": duration,
        "output_duration": output_duration,
    }


def build_selected_caption_preview(selected_timelines: List[Dict]) -> List[Dict]:
    previews = []

    for index, timeline in enumerate(selected_timelines, start=1):
        previews.append(
            {
                "index": index,
                "text": timeline.get("text"),
                "translated_text": timeline.get("translated_text"),
                "caption_role": timeline.get("caption_role"),
                "should_translate": timeline.get("should_translate"),
                "start": timeline.get("start"),
                "end": timeline.get("end"),
                "duration": timeline.get("duration"),
                "sample_count": timeline.get("sample_count"),
                "box": timeline.get("box") or timeline.get("average_box"),
            }
        )

    return previews


def attach_translations_to_timelines(
    selected_timelines: List[Dict],
    translated_texts: List[str],
) -> List[Dict]:
    translated_timelines = []

    translate_index = 0

    for timeline in selected_timelines:
        item = dict(timeline)

        if item.get("should_translate"):
            if translate_index < len(translated_texts):
                item["translated_text"] = translated_texts[translate_index]
            else:
                item["translated_text"] = ""

            translate_index += 1
        else:
            item["translated_text"] = ""

        translated_timelines.append(item)

    return translated_timelines


def count_words(text: str) -> int:
    return len(str(text or "").strip().split())


def is_pov_header_only(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())

    return normalized in {
        "pov",
        "pov:",
    }


def translation_lost_meaning(original_text: str, translated_text: str) -> bool:
    original = str(original_text or "").strip()
    translated = str(translated_text or "").strip()

    if not original:
        return False

    if not translated:
        return True

    if translated.strip().lower() in {
        "name",
        "none",
        "null",
    }:
        return True

    original_words = count_words(original)
    translated_words = count_words(translated)

    if original_words >= 4 and translated_words <= 1:
        return True

    if len(original) >= 18 and len(translated) <= 4:
        return True

    return False


def repair_known_meme_translation(original_text: str, translated_text: str) -> str:
    original = " ".join(str(original_text or "").strip().split())
    lowered = original.lower()
    translated = str(translated_text or "").strip()
    symbol_clean = original
    symbol_clean = re.sub(r"\b4[o0]ks\b", "40k$", symbol_clean, flags=re.IGNORECASE)
    symbol_clean = re.sub(r"\b3ks\b", "3k$", symbol_clean, flags=re.IGNORECASE)
    symbol_clean = re.sub(r"\b15ks\b", "15k$", symbol_clean, flags=re.IGNORECASE)
    symbol_clean = re.sub(r"0\s*,\s*1s[o0c]\b", "0,1$", symbol_clean, flags=re.IGNORECASE)
    symbol_clean = re.sub(r"greece[=el]*\b", "Greece", symbol_clean, flags=re.IGNORECASE)
    lowered_clean = symbol_clean.lower()

    if (
        "dad filled up the car" in lowered
        and "every note of that smell" in lowered
    ):
        return "Bố vừa đổ đầy xăng và bạn đã cảm nhận trọn từng nốt hương của mùi đó:"

    if lowered_clean.startswith("business plan in greece"):
        return "Kế hoạch kinh doanh ở Hy Lạp"

    if lowered_clean.startswith("car for "):
        return symbol_clean.replace("Car for", "Xe").strip()

    if lowered_clean.startswith("pc for "):
        return symbol_clean.replace("PC for", "PC").strip()

    if lowered_clean.startswith("phone for "):
        return symbol_clean.replace("Phone for", "Điện thoại").strip()

    if lowered_clean.startswith("gas went up"):
        value = symbol_clean.split("up", 1)[-1].strip()
        return f"Giá xăng tăng {value}".strip()

    if lowered in {"inreality:", "in reality:"}:
        return "Trong thực tế:"

    if lowered in {"inthe movies3", "inthe movies?", "in the movies:"}:
        return "Trong phim:"

    if lowered in {"inthe film3", "in the film:"}:
        return "Trong phim:"

    if lowered.startswith("reaccion a una arana") or lowered.startswith("reacción a una araña"):
        region = ""

        if "europa" in lowered:
            region = "châu Âu"
        elif "asia" in lowered:
            region = "châu Á"
        elif "australia" in lowered:
            region = "Úc"

        if region:
            return f"Phản ứng với một con nhện ở {region}"

    phase_labels = {
        "girls:": "Các cô gái:",
        "boys:": "Các cậu con trai:",
        "teacher:": "Giáo viên:",
    }

    for source_label, target_label in phase_labels.items():
        if not lowered.startswith(source_label):
            continue

        if translated.lower().startswith(target_label.lower()):
            return translated

        remainder = original[len(source_label):].strip()

        if not remainder:
            return target_label

        if translated and translated.lower() != source_label.rstrip(":"):
            return f"{target_label} {translated}".strip()

        return f"{target_label} {remainder}".strip()

    return translated


def repair_pov_translation_if_needed(
    original_text: str,
    translated_text: str,
    source_lang: str,
    target_lang: str,
    translation_engine: str,
) -> str:
    original = str(original_text or "").strip()
    translated = str(translated_text or "").strip()

    if not original.lower().startswith("pov:"):
        return translated

    if not is_pov_header_only(translated):
        return translated

    remainder = original[4:].strip()

    if not remainder:
        return translated

    try:
        translated_remainder = translate_text(
            text=remainder,
            source_lang=source_lang,
            target_lang=target_lang,
            engine_name=translation_engine,
        ).strip()
    except Exception:
        translated_remainder = ""

    if not translated_remainder or is_pov_header_only(translated_remainder):
        translated_remainder = remainder

    return f"POV: {translated_remainder}".strip()


def repair_translations(
    original_texts: List[str],
    translated_texts: List[str],
    source_lang: str,
    target_lang: str,
    translation_engine: str,
) -> List[str]:
    repaired = []

    for index, original_text in enumerate(original_texts):
        translated_text = (
            translated_texts[index]
            if index < len(translated_texts)
            else ""
        )

        repaired_text = repair_pov_translation_if_needed(
            original_text=original_text,
            translated_text=translated_text,
            source_lang=source_lang,
            target_lang=target_lang,
            translation_engine=translation_engine,
        )

        repaired_text = repair_known_meme_translation(
            original_text=original_text,
            translated_text=repaired_text,
        )

        if translation_lost_meaning(
            original_text=original_text,
            translated_text=repaired_text,
        ):
            repaired_text = str(original_text or "").strip()

        repaired.append(repaired_text)

    return repaired


def translate_selected_timelines(
    selected_timelines: List[Dict],
    source_lang: str = "en",
    target_lang: str = "vi",
    translation_engine: str = "argos",
) -> List[Dict]:
    texts_to_translate = []
    translate_slots = []
    final_texts_by_slot = {}
    memory = load_memory()

    for slot_index, timeline in enumerate(selected_timelines):
        if not timeline.get("should_translate"):
            continue

        text = str(timeline.get("text") or "").strip()

        if not text:
            continue

        normalized_text = repair_ocr_text(
            text=text,
            memory=memory,
        )

        if not is_english_caption(normalized_text, fallback="en"):
            final_texts_by_slot[slot_index] = SUB_FAIL_TEXT
            continue

        approved_translation = get_approved_translation(
            text=normalized_text,
            memory=memory,
        )

        if approved_translation:
            final_texts_by_slot[slot_index] = approved_translation
            continue

        context = build_translation_context(
            timelines=selected_timelines,
            slot_index=slot_index,
        )
        semantic_translation = semantic_translate_before_argos(
            text=normalized_text,
            caption_role=timeline.get("caption_role") or "",
            context=context,
        )

        if semantic_translation:
            final_texts_by_slot[slot_index] = semantic_translation
            continue

        translate_slots.append(
            {
                "slot_index": slot_index,
                "original_text": text,
                "normalized_text": normalized_text,
                "caption_role": timeline.get("caption_role") or "",
                "context": context,
            }
        )
        texts_to_translate.append(normalized_text)

    if not texts_to_translate:
        translated_timelines = []

        for slot_index, timeline in enumerate(selected_timelines):
            item = dict(timeline)

            if slot_index in final_texts_by_slot:
                item["translated_text"] = final_texts_by_slot[slot_index]

            translated_timelines.append(item)

        return translated_timelines

    for slot in translate_slots:
        slot_index = slot["slot_index"]
        detected_source_lang = "en"

        try:
            translated_text = translate_text(
                text=slot["normalized_text"],
                source_lang=detected_source_lang,
                target_lang=target_lang,
                engine_name=translation_engine,
                options={"auto_install": False},
            )
        except Exception:
            translated_text = SUB_FAIL_TEXT

        repaired_batch = repair_translations(
            original_texts=[slot["normalized_text"]],
            translated_texts=[translated_text],
            source_lang=detected_source_lang,
            target_lang=target_lang,
            translation_engine=translation_engine,
        )
        translated_text = repaired_batch[0] if repaired_batch else translated_text

        final_text = rewrite_after_argos(
            original_text=slot["original_text"],
            normalized_text=slot["normalized_text"],
            translated_text=translated_text,
            caption_role=slot["caption_role"],
            context=slot.get("context") or {},
        )
        final_texts_by_slot[slot_index] = final_text

        remember_pending_case(
            original_text=slot["original_text"],
            normalized_text=slot["normalized_text"],
            translated_text=final_text,
            source_lang=detected_source_lang,
            target_lang=target_lang,
            engine=translation_engine,
            caption_role=slot["caption_role"],
        )

    translated_timelines = []

    for slot_index, timeline in enumerate(selected_timelines):
        item = dict(timeline)

        if item.get("should_translate"):
            item["translated_text"] = final_texts_by_slot.get(slot_index, "")

        translated_timelines.append(item)

    return translated_timelines


def find_non_english_caption(
    selected_timelines: List[Dict],
    raw_timelines: Optional[List[Dict]] = None,
) -> Optional[Dict]:
    memory = load_memory()
    selected_translate_timelines = [
        timeline
        for timeline in selected_timelines
        if timeline.get("should_translate")
    ]
    raw_check_timelines = list(raw_timelines or [])
    timelines_to_check = []
    seen_texts = set()

    for timeline in selected_translate_timelines + raw_check_timelines:
        text_key = " ".join(str(timeline.get("text") or "").lower().split())

        if not text_key or text_key in seen_texts:
            continue

        seen_texts.add(text_key)
        timelines_to_check.append(timeline)

    for timeline in timelines_to_check:
        text = str(timeline.get("text") or "").strip()

        if not text:
            continue

        if is_language_gate_ignorable_text(text):
            continue

        normalized_text = repair_ocr_text(
            text=text,
            memory=memory,
        )

        if is_language_gate_ignorable_text(normalized_text):
            continue

        failed_pair = find_non_english_adjacent_pair(normalized_text)

        if failed_pair or not is_english_caption(normalized_text, fallback="en"):
            return {
                "text": text,
                "normalized_text": normalized_text,
                "failed_pair": failed_pair or normalized_text,
                "caption_role": timeline.get("caption_role") or "",
                "start": timeline.get("start"),
                "end": timeline.get("end"),
            }

    return None


def is_language_gate_ignorable_text(text: str) -> bool:
    value = str(text or "").strip().lower()

    if not value:
        return True

    tokens = re.findall(r"[a-z\u00c0-\u024f]+|\d+", value)

    if not tokens:
        return True

    label_tokens = {
        "baby",
        "bro",
        "dad",
        "daddy",
        "girl",
        "girls",
        "hermano",
        "kid",
        "mama",
        "mam\u00e1",
        "me",
        "mom",
        "mommy",
        "papa",
        "pap\u00e1",
        "profesor",
        "profesora",
        "radiologo",
        "radi\u00f3logo",
        "son",
        "teacher",
        "yo",
    }
    unit_tokens = {"cm", "kg", "km", "h", "mph"}
    non_numeric_tokens = [token for token in tokens if not token.isdigit()]

    if not non_numeric_tokens:
        return True

    if len(non_numeric_tokens) <= 2 and all(
        token in label_tokens or token in unit_tokens
        for token in non_numeric_tokens
    ):
        return True

    return False


def find_sub_fail_translation(translated_timelines: List[Dict]) -> Optional[Dict]:
    for timeline in translated_timelines:
        if not timeline.get("should_translate"):
            continue

        translated_text = str(timeline.get("translated_text") or "").strip()

        if translated_text == SUB_FAIL_TEXT:
            return {
                "text": timeline.get("text") or "",
                "translated_text": translated_text,
                "caption_role": timeline.get("caption_role") or "",
                "start": timeline.get("start"),
                "end": timeline.get("end"),
            }

    return None


def _render_subtitle_video(
    video_path: str,
    output_dir: Optional[str] = None,
    final_output_path: Optional[str] = None,
    target_lang: str = "vi",
    source_lang: str = "en",
    languages: Optional[List[str]] = None,
    gpu=None,
    translation_engine: str = "argos",
    translate: bool = True,
    render_video: bool = True,
    cleanup_temp: bool = True,
    progress_callback=None,
) -> Dict:
    """
    Production render entrypoint.

    Layer flow:
    1. Analyze video bằng production analyzer
    2. Select final captions bằng final_caption_selector
    3. Translate selected timelines nếu translate=True
    4. Render translated text vào video tạm không audio nếu render_video=True
    5. Merge audio gốc vào output cuối

    Layer responsibility:
    - render_service chỉ điều phối flow
    - analyze_service xử lý OCR/timeline/selector
    - translator_router xử lý translation
    - video_writer xử lý render frame
    - audio_merge xử lý audio
    """

    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video file không tồn tại: {video_path}")

    output_path = make_done_output_path(
        video_path=video_path,
        output_dir=output_dir,
    )

    _emit_progress(progress_callback, "analyze", 0.0)

    analyze_result = analyze_video_for_production(
        video_path=video_path,
        languages=default_ocr_languages(languages or [source_lang]),
        gpu=gpu,
        progress_callback=_scaled_progress_callback(
            progress_callback,
            "analyze",
            0.0,
            0.62,
        ),
    )

    sample_output_dir = analyze_result.pop("_temp_sample_output_dir", "")

    if cleanup_temp:
        cleanup_sample_session_dir(
            session_dir=sample_output_dir,
            temp_dir=DEFAULT_TEMP_DIR,
        )

    selected_timelines = analyze_result.get("selected_timelines", [])

    translated_timelines = selected_timelines

    non_english_caption = (
        find_non_english_caption(
            selected_timelines=selected_timelines,
            raw_timelines=analyze_result.get("raw_timelines", []),
        )
        if translate and target_lang == "vi"
        else None
    )

    _emit_progress(progress_callback, "language_gate", 0.64)

    if non_english_caption:
        return {
            "status": "error",
            "stage": "translation_language_gate",
            "message": SUB_FAIL_TEXT,
            "error": SUB_FAIL_TEXT,
            "reason": "non_english_caption",
            "video_path": video_path,
            "output_path": output_path,
            "target_lang": target_lang,
            "source_lang": source_lang,
            "translation": {
                "enabled": translate,
                "engine": translation_engine,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "status": "error",
                "error": SUB_FAIL_TEXT,
                "failed_caption": non_english_caption,
            },
            "render": {
                "enabled": render_video,
                "status": "error",
                "temp_video_path": None,
                "output_path": output_path,
                "error": SUB_FAIL_TEXT,
                "video_writer": None,
                "audio_merge": None,
            },
            "video_info": analyze_result.get("video_info", {}),
            "settings": analyze_result.get("settings", {}),
            "summary": analyze_result.get("summary", {}),
            "selected_timeline_count": len(selected_timelines),
            "selected_timelines": build_selected_caption_preview(
                selected_timelines
            ),
            "final_caption_selection": analyze_result.get(
                "final_caption_selection",
                {},
            ),
        }

    translation_status = {
        "enabled": translate,
        "engine": translation_engine,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "status": "skipped",
        "error": None,
    }

    if translate:
        _emit_progress(progress_callback, "translate", 0.66)
        try:
            translated_timelines = translate_selected_timelines(
                selected_timelines=selected_timelines,
                source_lang=source_lang,
                target_lang=target_lang,
                translation_engine=translation_engine,
            )

            translation_status["status"] = "ok"

        except Exception as error:
            translation_status["status"] = "error"
            translation_status["error"] = str(error)

            translated_timelines = selected_timelines

    sub_fail_translation = (
        find_sub_fail_translation(translated_timelines)
        if translate and target_lang == "vi"
        else None
    )

    if sub_fail_translation:
        return {
            "status": "error",
            "stage": "translation_sub_fail",
            "message": SUB_FAIL_TEXT,
            "error": SUB_FAIL_TEXT,
            "reason": "sub_fail_translation",
            "video_path": video_path,
            "output_path": output_path,
            "target_lang": target_lang,
            "source_lang": source_lang,
            "translation": {
                **translation_status,
                "status": "error",
                "error": SUB_FAIL_TEXT,
                "failed_caption": sub_fail_translation,
            },
            "render": {
                "enabled": render_video,
                "status": "error",
                "temp_video_path": None,
                "output_path": output_path,
                "error": SUB_FAIL_TEXT,
                "video_writer": None,
                "audio_merge": None,
            },
            "video_info": analyze_result.get("video_info", {}),
            "settings": analyze_result.get("settings", {}),
            "summary": analyze_result.get("summary", {}),
            "selected_timeline_count": len(selected_timelines),
            "selected_timelines": build_selected_caption_preview(
                translated_timelines
            ),
            "final_caption_selection": analyze_result.get(
                "final_caption_selection",
                {},
            ),
        }

    render_status = {
        "enabled": render_video,
        "status": "skipped",
        "temp_video_path": None,
        "output_path": output_path,
        "error": None,
        "video_writer": None,
        "audio_merge": None,
    }

    if render_video:
        temp_video_path = None

        try:
            _emit_progress(progress_callback, "render_frames", 0.72)

            temp_render_result = render_video_to_temp_without_audio(
                video_path=video_path,
                final_output_path=output_path,
                translated_timelines=translated_timelines,
                progress_callback=_scaled_progress_callback(
                    progress_callback,
                    "render_frames",
                    0.72,
                    0.95,
                ),
            )

            temp_video_path = temp_render_result.get("output_path")

            render_status["temp_video_path"] = temp_video_path
            render_status["video_writer"] = temp_render_result

            _emit_progress(progress_callback, "merge_audio", 0.97)

            audio_merge_result = merge_audio_or_copy(
                original_video_path=video_path,
                rendered_video_path=temp_video_path,
                output_path=output_path,
                cleanup_rendered_video=cleanup_temp,
            )

            render_status["audio_merge"] = audio_merge_result
            render_status["status"] = "ok"
            _emit_progress(progress_callback, "complete", 1.0)

        except Exception as error:
            render_status["status"] = "error"
            render_status["error"] = str(error)

        finally:
            if cleanup_temp and temp_video_path:
                cleanup_file(temp_video_path)

    return {
        "status": "ok",
        "stage": "render_complete" if render_video else "render_prepare_translation",
        "message": (
            "Render production hoàn tất."
            if render_status.get("status") == "ok"
            else "Analyze/translation hoàn tất. Render video chưa hoàn tất hoặc bị bỏ qua."
        ),
        "video_path": video_path,
        "output_path": output_path,
        "target_lang": target_lang,
        "source_lang": source_lang,
        "translation": translation_status,
        "render": render_status,
        "video_info": analyze_result.get("video_info", {}),
        "settings": analyze_result.get("settings", {}),
        "summary": analyze_result.get("summary", {}),
        "selected_timeline_count": len(translated_timelines),
        "selected_timelines": build_selected_caption_preview(
            translated_timelines
        ),
        "final_caption_selection": analyze_result.get(
            "final_caption_selection",
            {},
        ),
    }


def render_single_video(
    video_path: str,
    output_dir: Optional[str] = None,
    target_lang: str = "vi",
    source_lang: str = "en",
    languages: Optional[List[str]] = None,
    gpu=None,
    translation_engine: str = "argos",
    translate: bool = True,
    render_video: bool = True,
    cleanup_temp: bool = True,
    apply_frame: bool = False,
    frame_template_id: Optional[str] = None,
    frame_fit: Optional[str] = None,
    trim_start_seconds: Optional[float] = 0,
    trim_end_seconds: Optional[float] = 0,
    progress_callback=None,
) -> Dict:
    """
    Production orchestration wrapper.

    Optional trim is a pre-process step only. It prepares a temporary input,
    then the existing subtitle/frame branches continue unchanged.
    """

    output_path = make_done_output_path(
        video_path=video_path,
        output_dir=output_dir,
    )
    trim_start = _normalize_trim_seconds(trim_start_seconds)
    trim_end = _normalize_trim_seconds(trim_end_seconds)
    trim_enabled = trim_start > 0 or trim_end > 0
    trim_info = {
        "enabled": False,
        "input_path": video_path,
        "temp_path": None,
        "cleanup": False,
        "start_seconds": trim_start,
        "end_seconds": trim_end,
        "duration": None,
        "output_duration": None,
    }
    downstream_progress = progress_callback
    frame_temp_path = None

    if trim_enabled:
        trim_info = _prepare_trimmed_input(
            video_path=video_path,
            output_path=output_path,
            trim_start_seconds=trim_start,
            trim_end_seconds=trim_end,
            progress_callback=_scaled_progress_callback(
                progress_callback,
                "trim_video",
                0.0,
                0.12,
            ),
        )
        video_path = trim_info["input_path"]
        downstream_progress = _scaled_progress_callback(
            progress_callback,
            "post_trim_pipeline",
            0.12,
            1.0,
        )

    try:
        if not translate and not apply_frame:
            if not trim_enabled:
                raise ValueError("Enable Translate Caption, Apply Frame, or Trim before rendering")

            copy_result = copy_video_file(
                input_video_path=video_path,
                output_path=output_path,
            )
            _emit_progress(progress_callback, "complete", 1.0)

            return {
                "status": "ok",
                "stage": "trim_complete",
                "message": "Trim video complete.",
                "video_path": video_path,
                "output_path": output_path,
                "target_lang": target_lang,
                "source_lang": source_lang,
                "trim": trim_info,
                "translation": {
                    "enabled": False,
                    "engine": translation_engine,
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                    "status": "skipped",
                    "error": None,
                },
                "render": {
                    "enabled": True,
                    "status": "ok",
                    "temp_video_path": None,
                    "output_path": output_path,
                    "error": None,
                    "video_writer": None,
                    "audio_merge": copy_result,
                },
                "video_info": {},
                "settings": {},
                "summary": {},
                "selected_timeline_count": 0,
                "selected_timelines": [],
                "final_caption_selection": {},
            }

        if not apply_frame:
            result = _render_subtitle_video(
                video_path=video_path,
                output_dir=output_dir,
                final_output_path=output_path,
                target_lang=target_lang,
                source_lang=source_lang,
                languages=languages,
                gpu=gpu,
                translation_engine=translation_engine,
                translate=translate,
                render_video=render_video,
                cleanup_temp=cleanup_temp,
                progress_callback=downstream_progress,
            )
            result["trim"] = trim_info
            return result

        if not render_video:
            raise ValueError("Apply Frame requires render_video=True")

        if not frame_template_id:
            raise ValueError("Select a frame template before rendering")

        frame_input_path = video_path
        frame_temp_path = f"{os.path.splitext(output_path)[0]}_frame_composite.mp4"

        if translate:
            result = _render_subtitle_video(
                video_path=video_path,
                output_dir=output_dir,
                final_output_path=output_path,
                target_lang=target_lang,
                source_lang=source_lang,
                languages=languages,
                gpu=gpu,
                translation_engine=translation_engine,
                translate=True,
                render_video=True,
                cleanup_temp=cleanup_temp,
                progress_callback=_scaled_progress_callback(
                    downstream_progress,
                    "subtitle_pipeline",
                    0.0,
                    0.82,
                ),
            )
            result["trim"] = trim_info

            if (result.get("render") or {}).get("status") != "ok":
                return result

            frame_input_path = result.get("output_path") or output_path
        else:
            result = {
                "status": "ok",
                "stage": "frame_prepare",
                "message": "Frame-only render prepared.",
                "video_path": video_path,
                "output_path": output_path,
                "target_lang": target_lang,
                "source_lang": source_lang,
                "trim": trim_info,
                "translation": {
                    "enabled": False,
                    "engine": translation_engine,
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                    "status": "skipped",
                    "error": None,
                },
                "render": {
                    "enabled": True,
                    "status": "pending",
                    "temp_video_path": None,
                    "output_path": output_path,
                    "error": None,
                    "video_writer": None,
                    "audio_merge": None,
                },
                "video_info": {},
                "settings": {},
                "summary": {},
                "selected_timeline_count": 0,
                "selected_timelines": [],
                "final_caption_selection": {},
            }

        cleanup_file(frame_temp_path)
        frame_result = render_video_with_frame_template(
            input_video_path=frame_input_path,
            output_path=frame_temp_path,
            template_id=frame_template_id,
            fit_override=frame_fit,
            progress_callback=_scaled_progress_callback(
                downstream_progress,
                "apply_frame",
                0.82 if translate else 0.0,
                1.0,
            ),
        )
        os.replace(frame_temp_path, output_path)

        result["status"] = "ok"
        result["stage"] = "frame_complete"
        result["message"] = "Frame template render complete."
        result["output_path"] = output_path
        result["frame"] = {
            **frame_result,
            "enabled": True,
            "output_path": output_path,
        }
        result["render"] = {
            **(result.get("render") or {}),
            "enabled": True,
            "status": "ok",
            "output_path": output_path,
            "error": None,
            "frame_template": result["frame"],
        }
        _emit_progress(progress_callback, "complete", 1.0)
        return result

    except Exception as error:
        if apply_frame and "result" in locals() and result is not None:
            result["status"] = "error"
            result["stage"] = "frame_template_render"
            result["message"] = "Frame template render failed."
            result["error"] = str(error)
            result["trim"] = trim_info
            result["frame"] = {
                "enabled": True,
                "status": "error",
                "template_id": frame_template_id,
                "fit": frame_fit,
                "error": str(error),
            }
            result["render"] = {
                **(result.get("render") or {}),
                "enabled": True,
                "status": "error",
                "output_path": output_path,
                "error": str(error),
                "frame_template": result["frame"],
            }
            return result

        raise

    finally:
        if cleanup_temp and frame_temp_path:
            cleanup_file(frame_temp_path)
        if cleanup_temp and trim_info.get("cleanup"):
            cleanup_file(str(trim_info.get("temp_path") or ""))
