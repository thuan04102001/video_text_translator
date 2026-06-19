import os
import shutil
import subprocess
from typing import Dict, Optional


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def get_ffmpeg_executable() -> Optional[str]:
    system_ffmpeg = shutil.which("ffmpeg")

    if system_ffmpeg:
        return system_ffmpeg

    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def get_ffprobe_executable() -> Optional[str]:
    system_ffprobe = shutil.which("ffprobe")

    if system_ffprobe:
        return system_ffprobe

    ffmpeg_executable = get_ffmpeg_executable()

    if not ffmpeg_executable:
        return None

    ffmpeg_dir = os.path.dirname(ffmpeg_executable)

    for name in ["ffprobe.exe", "ffprobe"]:
        candidate = os.path.join(ffmpeg_dir, name)

        if os.path.isfile(candidate):
            return candidate

    return None


def ffmpeg_exists() -> bool:
    return get_ffmpeg_executable() is not None


def has_audio_stream(video_path: str) -> bool:
    """
    Check video co audio stream hay khong.

    Neu ffprobe khong co, fallback an toan:
    - tra True de ffmpeg merge thu
    - neu that su khong co audio, merge_audio_from_original se fallback copy/transcode video.
    """

    if not os.path.isfile(video_path):
        return False

    ffprobe_executable = get_ffprobe_executable()

    if ffprobe_executable is None:
        return True

    cmd = [
        ffprobe_executable,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "csv=p=0",
        video_path,
    ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        return "audio" in (result.stdout or "").lower()

    except Exception:
        return True


def copy_video_file(
    input_video_path: str,
    output_path: str,
) -> Dict:
    output_dir = os.path.dirname(output_path)

    if output_dir:
        ensure_dir(output_dir)

    shutil.copy2(input_video_path, output_path)

    return {
        "status": "ok",
        "stage": "copy_video_no_audio_merge",
        "input_video_path": input_video_path,
        "output_path": output_path,
        "reason": "Audio merge skipped or unavailable.",
    }


def transcode_video_file(
    input_video_path: str,
    output_path: str,
    reason: str,
) -> Dict:
    ffmpeg_executable = get_ffmpeg_executable()

    if not ffmpeg_executable:
        result = copy_video_file(
            input_video_path=input_video_path,
            output_path=output_path,
        )

        result["warning"] = (
            "ffmpeg not found. Output was copied directly and may not play "
            "well in browser preview."
        )

        return result

    output_dir = os.path.dirname(output_path)

    if output_dir:
        ensure_dir(output_dir)

    cmd = [
        ffmpeg_executable,
        "-y",
        "-i",
        input_video_path,
        "-map",
        "0:v:0",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-an",
        output_path,
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        fallback = copy_video_file(
            input_video_path=input_video_path,
            output_path=output_path,
        )

        fallback["warning"] = (
            "H.264 transcode failed. Output fallback was copied directly."
        )
        fallback["ffmpeg_error"] = result.stderr

        return fallback

    return {
        "status": "ok",
        "stage": "transcode_video_h264_no_audio",
        "input_video_path": input_video_path,
        "output_path": output_path,
        "has_audio": False,
        "reason": reason,
        "ffmpeg_stdout": result.stdout,
        "ffmpeg_stderr": result.stderr,
    }


def merge_audio_from_original(
    original_video_path: str,
    rendered_video_path: str,
    output_path: str,
    cleanup_rendered_video: bool = False,
) -> Dict:
    """
    Merge original audio into rendered video.

    Layer responsibility:
    - chi merge audio
    - khong OCR
    - khong translate
    - khong render text

    Behavior:
    - neu ffmpeg khong co: copy rendered video ra output
    - neu video goc khong co audio: transcode H.264 output khong audio
    - neu merge loi: transcode H.264 fallback khong audio
    """

    if not os.path.isfile(original_video_path):
        raise FileNotFoundError(
            f"Video goc khong ton tai: {original_video_path}"
        )

    if not os.path.isfile(rendered_video_path):
        raise FileNotFoundError(
            f"Rendered video khong ton tai: {rendered_video_path}"
        )

    output_dir = os.path.dirname(output_path)

    if output_dir:
        ensure_dir(output_dir)

    ffmpeg_executable = get_ffmpeg_executable()

    if not ffmpeg_executable:
        result = copy_video_file(
            input_video_path=rendered_video_path,
            output_path=output_path,
        )

        result["warning"] = (
            "Khong tim thay ffmpeg. Output duoc tao khong kem audio goc."
        )

        return result

    if not has_audio_stream(original_video_path):
        result = transcode_video_file(
            input_video_path=rendered_video_path,
            output_path=output_path,
            reason="Original video has no audio stream.",
        )

        result["warning"] = (
            "Video goc khong co audio stream. Output duoc tao khong kem audio."
        )

        return result

    cmd = [
        ffmpeg_executable,
        "-y",
        "-i",
        rendered_video_path,
        "-i",
        original_video_path,
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-shortest",
        output_path,
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        fallback = transcode_video_file(
            input_video_path=rendered_video_path,
            output_path=output_path,
            reason="Audio merge with original video failed.",
        )

        fallback["warning"] = (
            "Merge audio bang ffmpeg that bai. "
            "Output fallback khong kem audio goc."
        )

        fallback["ffmpeg_error"] = result.stderr

        return fallback

    if cleanup_rendered_video:
        try:
            if os.path.abspath(rendered_video_path) != os.path.abspath(output_path):
                os.remove(rendered_video_path)
        except Exception:
            pass

    return {
        "status": "ok",
        "stage": "merge_audio_from_original",
        "original_video_path": original_video_path,
        "rendered_video_path": rendered_video_path,
        "output_path": output_path,
        "has_audio": True,
        "ffmpeg_stdout": result.stdout,
        "ffmpeg_stderr": result.stderr,
    }


def merge_audio_or_copy(
    original_video_path: str,
    rendered_video_path: str,
    output_path: str,
    cleanup_rendered_video: bool = False,
) -> Dict:
    """
    Public wrapper dung cho render_service.
    """

    return merge_audio_from_original(
        original_video_path=original_video_path,
        rendered_video_path=rendered_video_path,
        output_path=output_path,
        cleanup_rendered_video=cleanup_rendered_video,
    )
