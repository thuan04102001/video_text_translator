import os
import uuid
from typing import Dict, List, Optional

import cv2


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def get_video_basic_info(video_path: str) -> Dict:
    if not video_path:
        raise ValueError("video_path is empty")

    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video không tồn tại: {video_path}")

    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        raise RuntimeError(f"Không thể mở video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    cap.release()

    if not fps or fps <= 0:
        fps = 30.0

    duration = frame_count / fps if frame_count > 0 else 0

    return {
        "video_path": video_path,
        "fps": fps,
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "duration": duration,
    }


def make_sample_session_dir(temp_dir: str, video_path: str) -> str:
    ensure_dir(temp_dir)

    base_name = os.path.splitext(os.path.basename(video_path))[0]
    session_id = uuid.uuid4().hex[:8]

    session_dir = os.path.join(
        temp_dir,
        "frame_samples",
        f"{base_name}_{session_id}",
    )

    ensure_dir(session_dir)

    return session_dir


def sample_video_frames(
    video_path: str,
    output_dir: str,
    interval_sec: float = 0.25,
    max_frames: Optional[int] = None,
    image_ext: str = ".jpg",
    progress_callback=None,
) -> Dict:
    """
    Analyze bắt buộc dùng hàm này để lấy frame sample dày.

    Rule:
    - chỉ sample frame
    - không OCR
    - không detect
    - không build timeline
    - không render

    interval_sec mặc định 0.25s, nằm trong yêu cầu 0.2~0.3s.
    """

    if interval_sec <= 0:
        raise ValueError("interval_sec must be > 0")

    if image_ext not in [".jpg", ".jpeg", ".png"]:
        raise ValueError("image_ext must be .jpg, .jpeg, or .png")

    info = get_video_basic_info(video_path)

    ensure_dir(output_dir)

    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        raise RuntimeError(f"Không thể mở video: {video_path}")

    fps = info["fps"]
    duration = info["duration"]

    samples: List[Dict] = []

    current_time = 0.0
    sample_index = 0
    expected_samples = max(1, int(duration / interval_sec) + 1)

    if max_frames is not None:
        expected_samples = min(expected_samples, max_frames)

    while current_time <= duration:
        if max_frames is not None and len(samples) >= max_frames:
            break

        frame_index = int(round(current_time * fps))

        if frame_index >= info["frame_count"]:
            break

        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)

        ok, frame = cap.read()

        if not ok or frame is None:
            current_time += interval_sec
            continue

        filename = f"frame_{sample_index:06d}_{current_time:.2f}s{image_ext}"
        image_path = os.path.join(output_dir, filename)

        if image_ext in [".jpg", ".jpeg"]:
            cv2.imwrite(image_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        else:
            cv2.imwrite(image_path, frame)

        samples.append(
            {
                "sample_index": sample_index,
                "time": round(current_time, 3),
                "frame_index": frame_index,
                "image_path": image_path,
            }
        )

        sample_index += 1

        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "frame_sampling",
                    "sample_index": sample_index,
                    "sample_count": expected_samples,
                    "progress": min(1.0, sample_index / expected_samples),
                }
            )

        current_time += interval_sec

    cap.release()

    return {
        "video_info": info,
        "interval_sec": interval_sec,
        "sample_count": len(samples),
        "output_dir": output_dir,
        "samples": samples,
    }


def analyze_sample_video(
    video_path: str,
    temp_dir: str = "temp",
    interval_sec: float = 0.25,
    max_frames: Optional[int] = None,
    progress_callback=None,
) -> Dict:
    """
    Wrapper analyze bước đầu.

    Đây chưa phải analyze OCR/detect hoàn chỉnh.
    Phase này chỉ xác nhận:
    - mở được video
    - lấy được metadata
    - sample frame đúng 0.2~0.3s
    - lưu ảnh frame vào temp
    """

    session_dir = make_sample_session_dir(temp_dir, video_path)

    result = sample_video_frames(
        video_path=video_path,
        output_dir=session_dir,
        interval_sec=interval_sec,
        max_frames=max_frames,
        image_ext=".jpg",
        progress_callback=progress_callback,
    )

    return {
        "status": "ok",
        "stage": "frame_sampling",
        "result": result,
    }
