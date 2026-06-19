import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from app.services.render_service import render_single_video
from core.translation.language_detector import DEFAULT_OCR_LANGUAGES, SUB_FAIL_TEXT

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
MAX_WORKERS = 10
MAX_LOGS = 1000


def make_done_name(filename: str) -> str:
    name, _ = os.path.splitext(filename)
    return f"{name}-done.mp4"


def is_error_input_name(filename: str) -> bool:
    return os.path.basename(filename).lower().startswith("error-")


def make_error_input_path(input_path: str) -> str:
    input_dir = os.path.dirname(input_path)
    filename = os.path.basename(input_path)

    if is_error_input_name(filename):
        return input_path

    return os.path.join(input_dir, f"error-{filename}")


def rename_input_as_error(input_path: str) -> str:
    target_path = make_error_input_path(input_path)

    if os.path.abspath(target_path) == os.path.abspath(input_path):
        return input_path

    if os.path.exists(target_path):
        name, ext = os.path.splitext(os.path.basename(input_path))
        target_path = os.path.join(
            os.path.dirname(input_path),
            f"error-{name}-{int(time.time())}{ext}",
        )

    os.replace(input_path, target_path)
    return target_path


def scan_batch_folder(input_dir: str, output_dir: str) -> Dict:
    if not input_dir or not os.path.isdir(input_dir):
        raise Exception(f"Input folder does not exist: {input_dir}")

    if not output_dir:
        raise Exception("Output folder is not selected")

    os.makedirs(output_dir, exist_ok=True)

    videos = []
    queued = []
    skipped = []
    input_errors = []

    for filename in sorted(os.listdir(input_dir)):
        ext = os.path.splitext(filename)[1].lower()

        if ext not in VIDEO_EXTS:
            continue

        input_path = os.path.join(input_dir, filename)

        if not os.path.isfile(input_path):
            continue

        output_name = make_done_name(filename)
        output_path = os.path.join(output_dir, output_name)

        item = {
            "filename": filename,
            "input_path": input_path,
            "output_name": output_name,
            "output_path": output_path,
            "exists": os.path.exists(output_path),
        }

        videos.append(item)

        if is_error_input_name(filename):
            input_errors.append(item)
            continue

        if item["exists"]:
            skipped.append(item)
        else:
            queued.append(item)

    return {
        "input_dir": input_dir,
        "output_dir": output_dir,
        "total": len(videos),
        "queued_count": len(queued),
        "skipped_count": len(skipped),
        "input_error_count": len(input_errors),
        "videos": videos,
        "queued": queued,
        "skipped": skipped,
        "input_errors": input_errors,
    }


class BatchManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset(clear_running=True)

    def reset(self, clear_running: bool = False) -> Dict:
        with self.lock:
            if getattr(self, "running", False) and not clear_running:
                self.cancel_requested = True
                self.paused = False
                return self.status()

            self.running = False
            self.paused = False
            self.cancel_requested = False
            self.total = 0
            self.done = 0
            self.skipped = 0
            self.errors = 0
            self.active = 0
            self.threads = 1
            self.translate = True
            self.apply_frame = False
            self.frame_template_id = ""
            self.frame_fit = ""
            self.trim_start_seconds = 0.0
            self.trim_end_seconds = 0.0
            self.input_dir = ""
            self.output_dir = ""
            self.pending: List[Dict] = []
            self.logs: List[str] = []
            self.item_progress: Dict[str, Dict] = {}
            self.started_at: Optional[float] = None
            self.finished_at: Optional[float] = None
            self.generation = getattr(self, "generation", 0) + 1
            return self.status()

    def _append_log_locked(self, message: str) -> None:
        self.logs.append(message)
        if len(self.logs) > MAX_LOGS:
            self.logs = self.logs[-MAX_LOGS:]

    def _elapsed_locked(self) -> int:
        if not self.started_at:
            return 0

        end_time = self.finished_at or time.time()
        return int(max(0, end_time - self.started_at))

    def _update_item_progress(self, generation: int, filename: str, event: Dict) -> None:
        stage = str((event or {}).get("stage") or "processing")
        percent = int(round(max(0.0, min(1.0, float((event or {}).get("progress", 0.0) or 0.0))) * 100))
        raw_stage_progress = (event or {}).get("stage_progress")
        stage_progress = (
            int(round(max(0.0, min(1.0, float(raw_stage_progress))) * 100))
            if raw_stage_progress is not None
            else None
        )
        source_stage = str((event or {}).get("detail_stage") or (event or {}).get("source_stage") or "")

        with self.lock:
            if generation != self.generation:
                return

            previous = self.item_progress.get(filename, {})

            if (
                previous.get("state") == "process"
                and previous.get("stage") == stage
                and previous.get("progress") == percent
                and previous.get("stage_progress") == stage_progress
            ):
                return

            self.item_progress[filename] = {
                "filename": filename,
                "state": "process",
                "stage": stage,
                "progress": percent,
                "stage_progress": stage_progress,
                "source_stage": source_stage,
            }

    def status(self) -> Dict:
        with self.lock:
            return {
                "running": self.running,
                "paused": self.paused,
                "cancel_requested": self.cancel_requested,
                "total": self.total,
                "done": self.done,
                "skipped": self.skipped,
                "errors": self.errors,
                "active": self.active,
                "queued": len(self.pending),
                "threads": self.threads,
                "translate": self.translate,
                "apply_frame": self.apply_frame,
                "frame_template_id": self.frame_template_id,
                "frame_fit": self.frame_fit,
                "trim_start_seconds": self.trim_start_seconds,
                "trim_end_seconds": self.trim_end_seconds,
                "elapsed_seconds": self._elapsed_locked(),
                "input_dir": self.input_dir,
                "output_dir": self.output_dir,
                "logs": list(self.logs),
                "item_progress": {
                    filename: dict(progress)
                    for filename, progress in self.item_progress.items()
                },
            }

    def start(
        self,
        input_dir: str,
        output_dir: str,
        threads: int = 1,
        translation_mode: str = "argos",
        translate: bool = True,
        apply_frame: bool = False,
        frame_template_id: Optional[str] = None,
        frame_fit: Optional[str] = None,
        trim_start_seconds: float = 0,
        trim_end_seconds: float = 0,
    ) -> Dict:
        safe_threads = max(1, min(MAX_WORKERS, int(threads or 1)))
        trim_start = max(0.0, float(trim_start_seconds or 0))
        trim_end = max(0.0, float(trim_end_seconds or 0))
        trim_enabled = trim_start > 0 or trim_end > 0

        if not translate and not apply_frame and not trim_enabled:
            raise Exception("Enable Translate Caption, Apply Frame, or Trim before rendering")

        if translate and translation_mode != "argos":
            raise Exception("Batch render currently supports Argos Offline only")

        if apply_frame and not frame_template_id:
            raise Exception("Select a frame template before rendering")

        scan = scan_batch_folder(input_dir=input_dir, output_dir=output_dir)

        with self.lock:
            if self.running:
                raise Exception("Batch is already running")

            self.reset(clear_running=True)
            self.running = True
            self.paused = False
            self.cancel_requested = False
            self.total = scan["total"]
            self.skipped = scan["skipped_count"]
            self.errors = scan["input_error_count"]
            self.pending = list(scan["queued"])
            self.threads = safe_threads
            self.translate = bool(translate)
            self.apply_frame = bool(apply_frame)
            self.frame_template_id = str(frame_template_id or "")
            self.frame_fit = str(frame_fit or "")
            self.trim_start_seconds = trim_start
            self.trim_end_seconds = trim_end
            self.input_dir = input_dir
            self.output_dir = output_dir
            self.started_at = time.time()
            self.finished_at = None
            self.generation += 1
            generation = self.generation

            for item in scan["input_errors"]:
                self._append_log_locked(
                    f"[ERROR] {item['filename']}: {SUB_FAIL_TEXT}"
                )

            if not self.pending:
                self.running = False
                self.finished_at = time.time()
                return self.status()

        controller = threading.Thread(
            target=self._run_controller,
            args=(generation, safe_threads, translation_mode),
            daemon=True,
        )
        controller.start()

        return self.status()

    def pause(self) -> Dict:
        with self.lock:
            if self.running:
                self.paused = True
            return self.status()

    def resume(self) -> Dict:
        with self.lock:
            if self.running:
                self.paused = False
            return self.status()

    def cancel(self) -> Dict:
        with self.lock:
            if self.running:
                self.cancel_requested = True
                self.paused = False
            return self.status()

    def _take_next(self, generation: int) -> Optional[Dict]:
        while True:
            with self.lock:
                if generation != self.generation or not self.running:
                    return None

                if self.cancel_requested:
                    return None

                if not self.paused and self.pending:
                    return self.pending.pop(0)

                if not self.pending:
                    return None

            time.sleep(0.25)

    def _run_controller(self, generation: int, workers: int, translation_mode: str) -> None:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(self._worker_loop, generation, translation_mode)
                for _ in range(workers)
            ]

            for future in futures:
                try:
                    future.result()
                except Exception as error:
                    with self.lock:
                        self.errors += 1
                        self._append_log_locked(f"[ERROR] Worker crashed: {error}")

        with self.lock:
            if generation != self.generation:
                return

            self.running = False
            self.paused = False
            self.finished_at = time.time()


    def _worker_loop(self, generation: int, translation_mode: str) -> None:
        while True:
            item = self._take_next(generation)

            if not item:
                return

            self._render_item(generation, item, translation_mode)

    def _render_item(self, generation: int, item: Dict, translation_mode: str) -> None:
        filename = item["filename"]

        with self.lock:
            if generation != self.generation:
                return

            self.active += 1
            self._append_log_locked(f"[PROCESS] {filename}")
            self.item_progress[filename] = {
                "filename": filename,
                "state": "process",
                "stage": "starting",
                "progress": 0,
            }

        try:
            result = render_single_video(
                video_path=item["input_path"],
                output_dir=self.output_dir,
                source_lang="en",
                target_lang="vi",
                languages=DEFAULT_OCR_LANGUAGES,
                translation_engine=translation_mode,
                translate=self.translate,
                render_video=True,
                cleanup_temp=True,
                apply_frame=self.apply_frame,
                frame_template_id=self.frame_template_id or None,
                frame_fit=self.frame_fit or None,
                trim_start_seconds=self.trim_start_seconds,
                trim_end_seconds=self.trim_end_seconds,
                progress_callback=lambda event: self._update_item_progress(
                    generation,
                    filename,
                    event,
                ),
            )

            render_status = (result.get("render") or {}).get("status")
            render_error = (result.get("render") or {}).get("error")
            output_path = result.get("output_path") or item["output_path"]
            log_filename = filename

            if render_error == SUB_FAIL_TEXT:
                renamed_path = rename_input_as_error(item["input_path"])
                log_filename = os.path.basename(renamed_path)

            with self.lock:
                if generation != self.generation:
                    return

                if render_status == "ok" and os.path.exists(output_path):
                    self.done += 1
                    self.item_progress[filename] = {
                        "filename": filename,
                        "state": "done",
                        "stage": "complete",
                        "progress": 100,
                    }
                    self._append_log_locked(f"[DONE] {filename}")
                else:
                    self.errors += 1
                    self.item_progress.pop(filename, None)
                    self._append_log_locked(
                        f"[ERROR] {log_filename}: {render_error or 'Render did not produce output'}"
                    )

        except Exception as error:
            error_text = str(error)
            log_filename = filename

            if error_text == SUB_FAIL_TEXT:
                try:
                    renamed_path = rename_input_as_error(item["input_path"])
                    log_filename = os.path.basename(renamed_path)
                except Exception as rename_error:
                    error_text = f"{SUB_FAIL_TEXT}; rename failed: {rename_error}"

            with self.lock:
                if generation == self.generation:
                    self.errors += 1
                    self.item_progress.pop(filename, None)
                    self._append_log_locked(f"[ERROR] {log_filename}: {error_text}")

        finally:
            with self.lock:
                if generation == self.generation:
                    self.active = max(0, self.active - 1)


batch_manager = BatchManager()


def start_batch_render(
    input_dir: str,
    output_dir: str,
    threads: int = 1,
    translation_mode: str = "argos",
    translate: bool = True,
    apply_frame: bool = False,
    frame_template_id: Optional[str] = None,
    frame_fit: Optional[str] = None,
    trim_start_seconds: float = 0,
    trim_end_seconds: float = 0,
) -> Dict:
    return batch_manager.start(
        input_dir=input_dir,
        output_dir=output_dir,
        threads=threads,
        translation_mode=translation_mode,
        translate=translate,
        apply_frame=apply_frame,
        frame_template_id=frame_template_id,
        frame_fit=frame_fit,
        trim_start_seconds=trim_start_seconds,
        trim_end_seconds=trim_end_seconds,
    )


def get_batch_status() -> Dict:
    return batch_manager.status()


def pause_batch_render() -> Dict:
    return batch_manager.pause()


def resume_batch_render() -> Dict:
    return batch_manager.resume()


def cancel_batch_render() -> Dict:
    return batch_manager.cancel()


def reset_batch_render() -> Dict:
    return batch_manager.reset(clear_running=False)
