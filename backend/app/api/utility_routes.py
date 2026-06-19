import os
import shutil

from fastapi import APIRouter
from pydantic import BaseModel
from tkinter import Tk, filedialog

router = APIRouter(prefix="/utility", tags=["Utility"])

UPLOAD_DIR = "uploads"


class SaveRenderedVideoRequest(BaseModel):
    source_path: str
    suggested_name: str | None = None


def clear_uploads_dir() -> dict:
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    removed = []
    errors = []

    for name in os.listdir(UPLOAD_DIR):
        path = os.path.join(UPLOAD_DIR, name)

        try:
            if os.path.isfile(path) or os.path.islink(path):
                os.remove(path)
            elif os.path.isdir(path):
                shutil.rmtree(path)

            removed.append(name)
        except Exception as error:
            errors.append(
                {
                    "name": name,
                    "error": str(error),
                }
            )

    return {
        "success": len(errors) == 0,
        "removed_count": len(removed),
        "removed": removed,
        "errors": errors,
    }


@router.post("/clear-uploads")
def clear_uploads():
    return clear_uploads_dir()


@router.get("/select-folder")
def select_folder():
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    folder_path = filedialog.askdirectory(title="Select folder")

    root.destroy()

    return {
        "folder_path": folder_path
    }


@router.post("/save-rendered-video")
def save_rendered_video(payload: SaveRenderedVideoRequest):
    source_path = payload.source_path

    if not source_path or not os.path.isfile(source_path):
        return {
            "success": False,
            "message": f"Rendered video không tồn tại: {source_path}",
            "saved_path": "",
        }

    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    default_name = payload.suggested_name or os.path.basename(source_path)

    save_path = filedialog.asksaveasfilename(
        title="Save rendered video",
        defaultextension=".mp4",
        initialfile=default_name,
        filetypes=[("MP4 video", "*.mp4"), ("All files", "*.*")],
    )

    root.destroy()

    if not save_path:
        return {
            "success": False,
            "cancelled": True,
            "message": "User cancelled save.",
            "saved_path": "",
        }

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    shutil.copy2(source_path, save_path)

    return {
        "success": True,
        "cancelled": False,
        "message": "Saved rendered video.",
        "source_path": source_path,
        "saved_path": save_path,
    }
