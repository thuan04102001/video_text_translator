import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.single_routes import router as single_router
from app.api.batch_routes import router as batch_router
from app.api.analyze_routes import router as analyze_router
from app.api.crawler_routes import router as crawler_router
from app.api.frame_template_routes import router as frame_template_router
from app.api.auto_reup_routes import router as auto_reup_router
from app.services.batch_service import reset_batch_render
from app.services.auto_reup_service import (
    start_auto_reup_action_monitor,
    start_auto_reup_runtime_monitor,
    start_meta_token_monitor,
    stop_auto_reup_action_monitor,
    stop_auto_reup_runtime_monitor,
    stop_meta_token_monitor,
)
from app.api.utility_routes import clear_uploads_dir, router as utility_router
from core.system.runtime_cleanup import clear_runtime_temp_dirs

app = FastAPI(title="AI Video Text Translator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(single_router)
app.include_router(batch_router)
app.include_router(analyze_router)
app.include_router(utility_router)
app.include_router(crawler_router)
app.include_router(frame_template_router)
app.include_router(auto_reup_router)

for media_dir in ["uploads", "outputs"]:
    os.makedirs(media_dir, exist_ok=True)
    app.mount(f"/media/{media_dir}", StaticFiles(directory=media_dir), name=media_dir)


@app.get("/")
def root():
    return {
        "status": "ok",
        "project": "AI Video Text Translator",
    }


@app.on_event("startup")
def startup_runtime_services():
    clear_uploads_dir()
    clear_runtime_temp_dirs()
    reset_batch_render()
    start_meta_token_monitor()
    start_auto_reup_action_monitor()
    start_auto_reup_runtime_monitor()


@app.on_event("shutdown")
def shutdown_background_services():
    stop_auto_reup_runtime_monitor()
    stop_auto_reup_action_monitor()
    stop_meta_token_monitor()
