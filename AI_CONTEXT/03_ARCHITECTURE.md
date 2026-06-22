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
  - UI manages multiple independent Meta credentials:
    `system_user`, `user_oauth` and `test_token`.
  - Credentials are encrypted at rest with a machine-local Fernet key.
  - `system_user` is the production path for 24/24 operation and is scoped by
    one or more explicit Meta Business IDs.
  - `user_oauth` is used for personal/direct Page assets that cannot be assigned
    to a Business System User.
  - `test_token` is only for development/Graph API Explorer checks.
  - Each account supports manual sync, automatic periodic sync, update and removal.
  - Automatic sync validates the exact credential and reacquires only the Page
    inventory belonging to that credential.
  - Multiple credentials represent separate administrator accounts and separate
    asset groups. Example: account A owns A1-A10 while account B owns G1-G20.
    They are not treated as an operational backup pool.
  - Page ownership is explicit through `meta_token_page_links`.
  - Every Page has one explicit operational credential in
    `fanpages.credential_id`.
  - A Page never auto-switches to another credential when its assigned credential
    expires, is revoked or is removed.
  - Removing a credential deletes every Page operationally assigned to it.
    A Page exposed by another credential is not silently transferred; it must be
    explicitly imported/assigned again under that credential if desired.
  - Manually-created Pages without a Meta owner are preserved.
  - Actions, sources and jobs that referenced a deleted Page are detached by
    setting `target_page_id` to `NULL`, preventing dangling references.
  - Expired/revoked User OAuth tokens become `expired`/`error` and expose re-auth status
    instead of allowing publishing jobs to fail silently.
  - When a User token expires, each Page token linked to that exact User account
    is validated independently:
    - valid Page token -> Page remains usable as `degraded` and UI shows `REAUTH`;
    - invalid Page token -> Page becomes `missing_page_token` and is disabled.
  - Each User-token/Page link persists an independent Page-token state:
    `unknown`, `valid`, `invalid` or `error`, together with its last check time
    and latest Meta error.
  - `POST /auto-reup/pages/{page_id}/check-token?token_id=...` validates one
    exact Page token against Meta without returning the secret to the frontend.
  - The Page inventory displays User-token state and Page-token state separately.
  - Temporary connection/API errors do not clear working Page tokens or disable Pages.
  - No automatic cross-account credential switching is performed.
  - Optional `META_APP_ID` and `META_APP_SECRET` environment values allow the
    backend to attempt short-lived -> long-lived User token exchange.
  - User OAuth inventory combines Graph API `/me/accounts`, `/me/businesses`,
    `/{business-id}/owned_pages` and `/{business-id}/client_pages`.
  - System User inventory uses `/{system-user-id}/assigned_pages`, so only Pages
    explicitly assigned to that System User are imported.
  - Business ID identifies the Business scope but does not cause the entire
    Business `owned_pages` inventory to be imported.
  - Every edge is paginated and results are deduplicated by Facebook Page ID.
  - Missing Page tokens are hydrated through direct Page detail requests when permitted.
  - Fanpages are imported/upserted into local SQLite.
  - Direct/BM source and Business identity are persisted with each Page.
  - Historical Meta Pages are marked `stale` only after a complete scan without edge errors.
  - Page access tokens are stored locally but never returned to the frontend.
  - Frontend only receives `has_page_access_token` for readiness display.
  - Frontend receives non-secret owner metadata and groups the Page inventory by
    Meta User token. Page states include `READY`, `REAUTH`, `STALE` and missing token.
  - Reup Action configuration is backed by `reup_actions` in SQLite.
  - Action name is derived server-side from the selected destination Page.
  - Frame templates are shared with Video Text Translator through the existing
    `/frame-templates` catalog; Creative Frame requires a valid template ID.
  - Posting cadence is stored as a random interval range
    `min_gap_minutes..max_gap_minutes`.
  - `render_action_video()` delegates Translate Caption and Creative Frame to the
    existing `render_single_video()` production orchestrator. Auto Reup must not
    duplicate OCR, translation, subtitle, frame or audio logic.
  - `POST /auto-reup/actions/{action_id}/render` is the backend bridge for a
    downloaded/local source video. It is ready for the future crawler/worker.
  - `POST /auto-reup/actions/{action_id}/next-gap` returns a real random interval
    inside the Action's configured range for scheduler use.

Completed Auto Reup source inventory process:

- Enabled Actions are monitored by a backend action scanner.
- A new Action is scanned immediately; later scans follow
  `scan_interval_minutes`.
- `POST /auto-reup/actions/{action_id}/scan` triggers a manual scan without
  blocking the HTTP request.
- Facebook source discovery reuses the existing Playwright Facebook crawler.
  The Chrome debug profile must already be logged in; background workers never
  wait forever for interactive login.
- TikTok source discovery uses the installed yt-dlp extractor.
- Discovered videos are stored in `reup_jobs` with an explicit `action_id`.
- Duplicate protection is scoped by Action and source post/video identity.
- Action scan state is observable as `idle`, `scanning`, `ready` or `error`.

Completed Auto Reup execution runtime:

- Discovered jobs now follow a persistent state machine:
  `queued -> processing -> ready -> publishing -> posted/error`.
- A background preparation worker downloads the exact source video with yt-dlp,
  extracts its source description/title when available, and applies the Action's
  content-cleaning rule.
- Preparation calls the shared `render_action_video()` bridge, which delegates
  to the existing `render_single_video()` pipeline. Auto Reup does not copy or
  rewrite OCR, translation, subtitle, frame, audio or trim logic.
- Prepared media is stored under `backend/data/auto_reup_jobs/<job_id>/` and is
  removed after a successful Meta upload.
- Job progress/stage/source/output/publish ID are persisted in SQLite. Interrupted
  `processing` and `publishing` jobs recover to `queued` or `ready` at startup.
- The scheduler interprets Action time windows in `AUTO_REUP_TIMEZONE`
  (default `Asia/Bangkok`), honors `daily_limit`, and persists one random
  `min_gap_minutes..max_gap_minutes` posting time per ready job.
- Editing an Action's destination or schedule clears pending ready schedules so
  the new configuration is applied.
- Due jobs upload the prepared MP4 through the destination Page's own operational
  Page token using the Graph API `/{page-id}/videos` endpoint.
- Publish failures move only that job to Error and increment Action errors; they
  are never reported as posted.
- Runtime tuning is available through:
  `AUTO_REUP_RUNTIME_INTERVAL_SECONDS` and `AUTO_REUP_PREPARE_WORKERS`.
- Each Action has a persistent event stream in `reup_action_events`.
- `GET /auto-reup/actions/{action_id}/runtime` returns the live phase, next scan,
  next publish time, per-job progress and recent event history.
- The Action Detail UI polls backend state every two seconds and calculates
  countdown clocks locally every second. It never invents job progress.

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
