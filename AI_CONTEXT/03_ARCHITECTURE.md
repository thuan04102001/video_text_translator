# Architecture

## Tong quan

```text
video_text_translator/
  backend/
    app/
      api/                 FastAPI routes
      services/            Application services
      main.py              FastAPI app entry
    core/
      ocr/                 EasyOCR wrapper + OCR cleaner
      render/              Text box/render utilities
      translation/         Argos/OpenAI/Gemini/OpenRouter routing
      video/               Frame sampler, writer, audio merge
      crawler/             Video crawler runtime
      system/              Runtime cleanup, hardware checker
    engines/
      meme_caption/        Caption scoring, selection, timeline
    frame_templates/       Template folders and assets
    tests/regression/      Regression runner and reports
  frontend/
    src/
      App.jsx              Module switcher
      pages/
        Home.jsx           Translator UI + frame template manager
        CrawlerPanel.jsx   Video crawler UI
        AutoReupDashboard.jsx
  uploads/
  outputs/
  temp/
```

## Backend routes

- `single_routes.py`: single analyze/render.
- `batch_routes.py`: batch scan/start/status/pause/resume/cancel/reset.
- `analyze_routes.py`: upload/sample frame/OCR debug endpoints.
- `crawler_routes.py`: crawler tasks.
- `frame_template_routes.py`: template catalog/create/update/delete/assets.
- `auto_reup_routes.py`: Auto Reup dashboard API, including Meta fanpage import endpoints.
- `utility_routes.py`: upload cleanup/select folder helpers.

## Backend services

- `render_service.py`: orchestrates trim -> translate/render -> frame template.
- `batch_service.py`: folder scan, workers, progress, error handling.
- `frame_template_service.py`: template CRUD and FFmpeg frame rendering.
- `analyze_service.py`: analyze video into caption timelines.
- `auto_reup_service.py`: local SQLite-backed dashboard/action data plus Meta fanpage import/page-token storage.
- `config_service.py`, `ai_key_service.py`: settings/key support.

## Auto Reup process status

Current completed process:

- Process 1: Meta/Facebook fanpage connection.
  - UI accepts a Meta user access token.
  - Backend calls Graph API `/me/accounts`.
  - Fanpages are imported/upserted into local SQLite.
  - Page access tokens are stored locally but never returned to the frontend.
  - Frontend only receives `has_page_access_token` for readiness display.

Not yet implemented:

- Source crawling/indexing.
- Duplicate detection from source posts/videos.
- Scheduler.
- Real Facebook publishing.

## Frontend modules

`frontend/src/App.jsx` switches between:

- `Home.jsx`: Video Text Translator.
- `CrawlerPanel.jsx`: Video Crawler.
- `AutoReupDashboard.jsx`: Auto Reup Dashboard.

## Runtime cleanup

Backend startup in `backend/app/main.py` calls:

- `clear_uploads_dir()`
- `clear_runtime_temp_dirs()`
- `reset_batch_render()`

This is intentional to avoid stale upload/temp/batch state after crash/F5/power off.
