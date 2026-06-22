import os
import random
import subprocess
import tempfile
from typing import Dict, Optional

from app.services.frame_template_service import render_video_with_frame_template
from core.system.runtime_cleanup import cleanup_file
from core.video.audio_merge import get_ffmpeg_executable, has_audio_stream
from core.video.video_writer import get_video_capture_info


AUDIO_PROFILES = {
    "auto": {
        "color": "pink",
        "amplitude": 0.55,
        "filter": "lowpass=f=2200",
    },
    "nature": {
        "color": "brown",
        "amplitude": 0.62,
        "filter": "lowpass=f=1400",
    },
    "story": {
        "color": "pink",
        "amplitude": 0.48,
        "filter": "lowpass=f=1800",
    },
    "game": {
        "color": "white",
        "amplitude": 0.32,
        "filter": "highpass=f=180,lowpass=f=3600",
    },
    "funny": {
        "color": "pink",
        "amplitude": 0.5,
        "filter": "highpass=f=120,lowpass=f=3000",
    },
    "action": {
        "color": "white",
        "amplitude": 0.35,
        "filter": "highpass=f=220,lowpass=f=4200",
    },
    "calm": {
        "color": "brown",
        "amplitude": 0.45,
        "filter": "lowpass=f=1100",
    },
}


def _run_ffmpeg_quick(cmd, error_message: str) -> None:
    process = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if process.returncode != 0:
        raise RuntimeError((process.stderr or error_message).strip())


def _prepare_creative_source(
    input_video_path: str,
    output_path: str,
    remove_source_audio: bool,
    randomize_variant: bool,
    seed: Optional[int],
) -> Dict:
    ffmpeg_executable = get_ffmpeg_executable()

    if not ffmpeg_executable:
        raise RuntimeError("FFmpeg is required to prepare Creative Frame beta")

    rng = random.Random(seed if seed is not None else os.path.basename(input_video_path))
    brightness = rng.uniform(-0.012, 0.012) if randomize_variant else 0.0
    contrast = rng.uniform(1.012, 1.035) if randomize_variant else 1.0
    saturation = rng.uniform(1.015, 1.055) if randomize_variant else 1.0
    sharpen = "unsharp=3:3:0.18:3:3:0.0" if randomize_variant else "null"
    video_filter = (
        f"eq=brightness={brightness:.5f}:contrast={contrast:.5f}:saturation={saturation:.5f},"
        f"{sharpen},format=yuv420p"
    )

    cmd = [
        ffmpeg_executable,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        input_video_path,
        "-map",
        "0:v:0",
        "-vf",
        video_filter,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ]

    if remove_source_audio:
        cmd.append("-an")
    else:
        cmd.extend(["-map", "0:a?", "-c:a", "aac", "-b:a", "192k"])

    cmd.append(output_path)
    _run_ffmpeg_quick(cmd, "FFmpeg Creative Frame source prepare failed")

    return {
        "remove_source_audio": bool(remove_source_audio),
        "randomize_variant": bool(randomize_variant),
        "seed": seed,
        "visual_filter": video_filter,
    }


def _select_audio_profile(input_video_path: str, template_id: str, requested_profile: str) -> str:
    profile = str(requested_profile or "auto").lower()

    if profile in AUDIO_PROFILES and profile != "auto":
        return profile

    haystack = f"{os.path.basename(input_video_path)} {template_id}".lower()

    if any(keyword in haystack for keyword in ["ocean", "sea", "water", "nature", "animal"]):
        return "nature"

    if any(keyword in haystack for keyword in ["game", "gaming", "battle", "fight"]):
        return "game"

    if any(keyword in haystack for keyword in ["funny", "meme", "cute", "lol"]):
        return "funny"

    if any(keyword in haystack for keyword in ["action", "sport", "speed"]):
        return "action"

    if any(keyword in haystack for keyword in ["story", "fact", "news", "talk"]):
        return "story"

    return "calm"


def _build_smart_audio(
    ffmpeg_executable: str,
    output_path: str,
    duration: float,
    profile: str,
    volume: float,
) -> Dict:
    safe_duration = max(0.5, float(duration or 0.5))
    safe_volume = max(0.02, min(2.0, float(volume or 1.0)))
    settings = AUDIO_PROFILES.get(profile) or AUDIO_PROFILES["auto"]
    fade_out_start = max(0.0, safe_duration - 0.8)
    audio_filter = (
        f"{settings['filter']},"
        f"volume={safe_volume:.5f},"
        "afade=t=in:st=0:d=0.4,"
        f"afade=t=out:st={fade_out_start:.5f}:d=0.8,"
        "aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"
    )
    source = (
        f"anoisesrc=color={settings['color']}:"
        f"amplitude={settings['amplitude']}:sample_rate=44100"
    )

    _run_ffmpeg_quick(
        [
            ffmpeg_executable,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            source,
            "-t",
            f"{safe_duration:.6f}",
            "-af",
            audio_filter,
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            output_path,
        ],
        "FFmpeg Smart Audio generation failed",
    )

    return {
        "profile": profile,
        "source_type": "generated",
        "duration": safe_duration,
        "volume": safe_volume,
        "source": source,
        "filter": audio_filter,
    }


def _build_custom_audio(
    ffmpeg_executable: str,
    input_audio_path: str,
    output_path: str,
    duration: float,
    volume: float,
) -> Dict:
    if not input_audio_path or not os.path.isfile(input_audio_path):
        raise FileNotFoundError(f"Custom audio file does not exist: {input_audio_path}")

    safe_duration = max(0.5, float(duration or 0.5))
    safe_volume = max(0.02, min(2.0, float(volume or 1.0)))
    fade_out_start = max(0.0, safe_duration - 0.8)
    audio_filter = (
        f"volume={safe_volume:.5f},"
        "afade=t=in:st=0:d=0.4,"
        f"afade=t=out:st={fade_out_start:.5f}:d=0.8,"
        "aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"
    )

    _run_ffmpeg_quick(
        [
            ffmpeg_executable,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-stream_loop",
            "-1",
            "-i",
            input_audio_path,
            "-t",
            f"{safe_duration:.6f}",
            "-vn",
            "-af",
            audio_filter,
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            output_path,
        ],
        "FFmpeg custom audio prepare failed",
    )

    return {
        "profile": "custom",
        "source_type": "custom",
        "input_audio_path": input_audio_path,
        "duration": safe_duration,
        "volume": safe_volume,
        "filter": audio_filter,
    }


def _apply_smart_audio_layer(
    ffmpeg_executable: str,
    input_video_path: str,
    smart_audio_path: str,
    output_path: str,
    base_volume: float,
) -> Dict:
    input_has_audio = has_audio_stream(input_video_path)
    safe_base_volume = max(0.0, min(1.0, float(base_volume or 0.78)))

    cmd = [
        ffmpeg_executable,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        input_video_path,
        "-i",
        smart_audio_path,
        "-map",
        "0:v:0",
    ]

    if input_has_audio:
        cmd.extend(
            [
                "-filter_complex",
                (
                    f"[0:a:0]volume={safe_base_volume:.5f}[base];"
                    "[1:a:0]volume=1.0[smart];"
                    "[base][smart]amix=inputs=2:duration=first:dropout_transition=0[aout]"
                ),
                "-map",
                "[aout]",
            ]
        )
    else:
        cmd.extend(["-map", "1:a:0"])

    cmd.extend(
        [
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            output_path,
        ]
    )

    _run_ffmpeg_quick(cmd, "FFmpeg Smart Audio mix failed")

    return {
        "input_had_audio": input_has_audio,
        "base_volume": safe_base_volume if input_has_audio else 0.0,
    }


def render_video_with_creative_frame(
    input_video_path: str,
    output_path: str,
    template_id: str,
    fit_override: Optional[str] = None,
    remove_source_audio: bool = True,
    randomize_variant: bool = True,
    seed: Optional[int] = None,
    smart_audio_enabled: bool = True,
    smart_audio_profile: str = "auto",
    smart_audio_volume: float = 1.0,
    custom_audio_path: Optional[str] = None,
    progress_callback=None,
) -> Dict:
    if not os.path.isfile(input_video_path):
        raise FileNotFoundError(f"Input video does not exist: {input_video_path}")

    output_dir = os.path.dirname(output_path) or os.path.dirname(input_video_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    work_dir = tempfile.mkdtemp(prefix="creative_frame_", dir=output_dir or None)
    prepared_path = os.path.join(work_dir, "creative_source.mp4")
    framed_path = os.path.join(work_dir, "creative_framed.mp4")
    smart_audio_path = os.path.join(work_dir, "smart_audio.m4a")
    smart_output_path = os.path.join(work_dir, "creative_with_audio.mp4")

    try:
        ffmpeg_executable = get_ffmpeg_executable()

        if not ffmpeg_executable:
            raise RuntimeError("FFmpeg is required to render Creative Frame beta")

        prepare_result = _prepare_creative_source(
            input_video_path=input_video_path,
            output_path=prepared_path,
            remove_source_audio=remove_source_audio,
            randomize_variant=randomize_variant,
            seed=seed,
        )

        frame_result = render_video_with_frame_template(
            input_video_path=prepared_path,
            output_path=framed_path if smart_audio_enabled else output_path,
            template_id=template_id,
            fit_override=fit_override,
            progress_callback=progress_callback,
        )

        smart_audio_result = {
            "enabled": False,
            "status": "skipped",
            "reason": "Smart audio layer disabled.",
        }

        if smart_audio_enabled:
            video_info = get_video_capture_info(framed_path)
            duration = float(video_info.get("duration") or frame_result.get("duration") or 0.0)
            if custom_audio_path:
                generated_audio = _build_custom_audio(
                    ffmpeg_executable=ffmpeg_executable,
                    input_audio_path=custom_audio_path,
                    output_path=smart_audio_path,
                    duration=duration,
                    volume=smart_audio_volume,
                )
            else:
                selected_profile = _select_audio_profile(input_video_path, template_id, smart_audio_profile)
                generated_audio = _build_smart_audio(
                    ffmpeg_executable=ffmpeg_executable,
                    output_path=smart_audio_path,
                    duration=duration,
                    profile=selected_profile,
                    volume=smart_audio_volume,
                )
            mix_result = _apply_smart_audio_layer(
                ffmpeg_executable=ffmpeg_executable,
                input_video_path=framed_path,
                smart_audio_path=smart_audio_path,
                output_path=smart_output_path,
                base_volume=0.72 if not remove_source_audio else 0.55,
            )
            os.replace(smart_output_path, output_path)
            smart_audio_result = {
                "enabled": True,
                "status": "ok",
                **generated_audio,
                **mix_result,
            }

        return {
            **frame_result,
            "stage": "creative_frame",
            "mode": "creative_frame",
            "input_video_path": input_video_path,
            "prepared_video_path": prepared_path,
            "prepare": prepare_result,
            "smart_audio": smart_audio_result,
            "output_path": output_path,
        }
    finally:
        cleanup_file(prepared_path)
        cleanup_file(framed_path)
        cleanup_file(smart_audio_path)
        cleanup_file(smart_output_path)
        try:
            os.rmdir(work_dir)
        except OSError:
            pass
