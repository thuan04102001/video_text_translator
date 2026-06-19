import os
from typing import Dict, List, Optional

import cv2

from core.render.text_box_renderer import render_translated_timelines_on_frame


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def get_video_capture_info(video_path: str) -> Dict:
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video file không tồn tại: {video_path}")

    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        raise RuntimeError(f"Không thể mở video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    if fps <= 0:
        fps = 30

    duration = 0.0

    if frame_count > 0 and fps > 0:
        duration = frame_count / fps

    cap.release()

    return {
        "video_path": video_path,
        "fps": fps,
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "duration": duration,
    }


def make_temp_video_path(
    output_path: str,
    suffix: str = "_no_audio",
) -> str:
    output_dir = os.path.dirname(output_path)

    if output_dir:
        ensure_dir(output_dir)

    name, _ext = os.path.splitext(output_path)

    return f"{name}{suffix}.mp4"


def create_video_writer(
    output_path: str,
    fps: float,
    width: int,
    height: int,
):
    output_dir = os.path.dirname(output_path)

    if output_dir:
        ensure_dir(output_dir)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")

    writer = cv2.VideoWriter(
        output_path,
        fourcc,
        fps,
        (width, height),
    )

    if not writer.isOpened():
        raise RuntimeError(f"Không thể tạo video writer: {output_path}")

    return writer


def render_video_without_audio(
    video_path: str,
    output_path: str,
    translated_timelines: List[Dict],
    progress_callback=None,
) -> Dict:
    """
    Render translated timelines into video frames.

    Layer responsibility:
    - chỉ đọc video
    - render text vào frame
    - ghi video không audio

    Không làm:
    - OCR
    - selector
    - translate
    - merge audio
    """

    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video file không tồn tại: {video_path}")

    video_info = get_video_capture_info(video_path)

    fps = float(video_info["fps"])
    frame_count = int(video_info["frame_count"])
    width = int(video_info["width"])
    height = int(video_info["height"])

    if width <= 0 or height <= 0:
        raise RuntimeError(f"Video width/height không hợp lệ: {video_path}")

    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        raise RuntimeError(f"Không thể mở video: {video_path}")

    writer = create_video_writer(
        output_path=output_path,
        fps=fps,
        width=width,
        height=height,
    )

    rendered_frames = 0

    try:
        while True:
            ok, frame = cap.read()

            if not ok:
                break

            current_time = rendered_frames / fps

            output_frame = render_translated_timelines_on_frame(
                frame=frame,
                timelines=translated_timelines,
                current_time=current_time,
            )

            writer.write(output_frame)

            rendered_frames += 1

            if progress_callback is not None:
                progress_callback(
                    {
                        "stage": "render_video_without_audio",
                        "frame_index": rendered_frames,
                        "frame_count": frame_count,
                        "progress": (
                            rendered_frames / frame_count
                            if frame_count > 0
                            else 0
                        ),
                    }
                )

    finally:
        cap.release()
        writer.release()

    return {
        "status": "ok",
        "stage": "render_video_without_audio",
        "video_path": video_path,
        "output_path": output_path,
        "fps": fps,
        "frame_count": frame_count,
        "rendered_frames": rendered_frames,
        "width": width,
        "height": height,
        "has_audio": False,
    }


def render_video_to_temp_without_audio(
    video_path: str,
    final_output_path: str,
    translated_timelines: List[Dict],
    temp_output_path: Optional[str] = None,
    progress_callback=None,
) -> Dict:
    if temp_output_path is None:
        temp_output_path = make_temp_video_path(
            output_path=final_output_path,
            suffix="_no_audio",
        )

    return render_video_without_audio(
        video_path=video_path,
        output_path=temp_output_path,
        translated_timelines=translated_timelines,
        progress_callback=progress_callback,
    )