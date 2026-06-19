from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import StreamingResponse

from core.crawler.downloader import download_profile_videos
from core.crawler.task_control import (
    cancel_task,
    create_task,
    pause_task,
    remove_task,
    resume_task,
)


router = APIRouter(prefix="/crawler", tags=["Crawler"])


@router.post("/download")
def crawler_download(
    url: str = Form(...),
    folder: str = Form(...),
    task_id: str = Form(...),
    workers: int = Form(1),
):
    safe_workers = max(1, min(10, int(workers or 1)))

    if not url:
        raise HTTPException(status_code=400, detail="Missing URL")

    if not folder:
        raise HTTPException(status_code=400, detail="Missing save folder")

    if not task_id:
        raise HTTPException(status_code=400, detail="Missing task_id")

    create_task(task_id)

    def generate():
        try:
            for log in download_profile_videos(
                url=url,
                folder=folder,
                task_id=task_id,
                max_workers=safe_workers,
            ):
                yield f"data: {log}\n\n"
        except Exception as error:
            yield f"data: [ERROR] {error}\n\n"
            yield "data: [FINISHED]\n\n"
        finally:
            remove_task(task_id)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
    )


@router.post("/task-control")
def crawler_task_control(
    action: str = Form(...),
    task_id: str = Form(...),
):
    if not task_id:
        raise HTTPException(status_code=400, detail="Missing task_id")

    if action == "pause":
        pause_task(task_id)
        return {"status": "paused"}

    if action == "resume":
        resume_task(task_id)
        return {"status": "resumed"}

    if action == "cancel":
        cancel_task(task_id)
        return {"status": "cancelled"}

    raise HTTPException(status_code=400, detail="Unknown action")
