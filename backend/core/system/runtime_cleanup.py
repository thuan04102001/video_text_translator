import os
import shutil
from pathlib import Path
from typing import Dict, Iterable


BACKEND_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = BACKEND_ROOT.parent

RUNTIME_TEMP_DIRS = (
    BACKEND_ROOT / "temp" / "analyze_frame_samples",
    BACKEND_ROOT / "temp" / "frame_samples",
    WORKSPACE_ROOT / "temp" / "analyze_frame_samples",
    WORKSPACE_ROOT / "temp" / "frame_samples",
)

STARTUP_TEMP_DIRS = RUNTIME_TEMP_DIRS + (
    BACKEND_ROOT / "temp" / "regression_frame_samples",
    WORKSPACE_ROOT / "temp" / "regression_frame_samples",
)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _remove_entry(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def clear_directory_contents(directory: Path) -> Dict:
    resolved_dir = directory.resolve()
    removed_count = 0
    errors = []

    resolved_dir.mkdir(parents=True, exist_ok=True)

    for entry in resolved_dir.iterdir():
        if not _is_within(entry, resolved_dir):
            errors.append(
                {
                    "path": str(entry),
                    "error": "Refused to remove path outside the runtime directory.",
                }
            )
            continue

        try:
            _remove_entry(entry)
            removed_count += 1
        except Exception as error:
            errors.append(
                {
                    "path": str(entry),
                    "error": str(error),
                }
            )

    return {
        "path": str(resolved_dir),
        "removed_count": removed_count,
        "errors": errors,
    }


def clear_runtime_temp_dirs(
    directories: Iterable[Path] = STARTUP_TEMP_DIRS,
) -> Dict:
    results = [
        clear_directory_contents(directory)
        for directory in directories
    ]

    errors = [
        error
        for result in results
        for error in result["errors"]
    ]

    return {
        "success": len(errors) == 0,
        "removed_count": sum(result["removed_count"] for result in results),
        "directories": results,
        "errors": errors,
    }


def cleanup_sample_session_dir(session_dir: str, temp_dir: str) -> bool:
    if not session_dir:
        return False

    allowed_root = (Path(temp_dir).resolve() / "frame_samples").resolve()
    resolved_session = Path(session_dir).resolve()

    if resolved_session == allowed_root or not _is_within(resolved_session, allowed_root):
        return False

    if not resolved_session.exists():
        return False

    try:
        _remove_entry(resolved_session)
        return True
    except OSError:
        return False


def cleanup_file(path: str) -> bool:
    if not path or not os.path.isfile(path):
        return False

    try:
        os.remove(path)
        return True
    except OSError:
        return False
