# AI Context - Current Task

Last requested direction:

- Check whether unfinished processes were still running after credit limit/power interruption.
- If clean, apply AI handoff documentation to this project so another ChatGPT/Codex account can continue without re-analyzing everything from scratch.

Process check result:

- No active `python`, `uvicorn`, `ffmpeg`, `npm`, `vite`, or project `node` process was found.
- Only Codex internal `node_repl` was visible.

Current implementation task:

- Auto Reup is being implemented step by step, one completed process at a time.
- Process 1 is now implemented: Meta/Facebook fanpage connection and import.
- The UI can paste a Meta user access token and import available fanpages.
- Backend stores page access tokens locally in SQLite and only exposes `has_page_access_token` to the frontend.
- Meta import compatibility note:
  - `/me/accounts` request must use `id,name,access_token,tasks,category`.
  - Do not request `perms`; Graph API newer versions can reject it with `(#100) Tried accessing nonexisting field (perms)`.
- New ongoing rule: every future code/update task must sync relevant notes back into `AI_CONTEXT` before finishing.
- Repository is being initialized and published to GitHub with commit message `Initial commit`.
- Local runtime state such as SQLite page tokens, uploads, outputs, temp frames, logs, dependencies and backups must remain untracked.

Current boundary:

- Auto Reup source scan, preparation worker, scheduler and real Page publishing
  have now been connected.
- Future fixes must preserve the shared video pipeline and the Page credential
  ownership rules.
- Current Action card Page insights focus on total metrics only. Period tabs were
  removed because Meta's available API returns lifetime video/post totals rather
  than reliable daily deltas. Trend display is `% vs hôm qua` when a historical
  total snapshot from roughly yesterday exists; otherwise the UI shows a missing
  baseline state.

Current Meta page investigation:

- Local SQLite contains 93 fanpages; 92 have Meta page tokens from one import at `2026-06-19T01:16:23Z`.
- The compact dashboard list only displays six because the frontend uses `pages.slice(0, 6)`.
- A current `/me/accounts` response with six items reflects the current user token scope, not the complete local SQLite history.
- Before changing import behavior, decide whether synchronization should:
  - keep historical pages but mark missing pages stale/disconnected, or
  - mirror the current token exactly and remove/deactivate pages absent from the latest import.

Implemented Meta page synchronization:

- Inventory combines direct Pages, Business-owned Pages and Business client Pages.
- Import is conservative: missing historical Pages become stale only after a complete scan without Meta edge errors.
- UI exposes the complete local Page list with search and connection status instead of truncating to five/six records.
- The next real validation requires importing with the user's full token and reviewing returned `source_counts`, `businesses` and `warnings`.

Implemented Meta token lifecycle:

- Multiple Meta credentials can be stored and selected independently.
- Credential types are `system_user`, `user_oauth` and `test_token`.
- System User credentials require explicit Business IDs and are the production
  path for unattended 24/24 operation.
- Tokens are encrypted locally; frontend only receives masked metadata/status.
- Manual per-token sync and sync-all are available.
- Per-token auto sync is persisted and checked by a backend monitor.
- Sync validates the User token, refreshes direct/BM inventory and reacquires Page tokens.
- Expired/revoked tokens are marked for re-auth; jobs must not silently continue with dead credentials.
- Page visibility can be many-to-many, but Page operation is one-to-one through
  `fanpages.credential_id`.
- Long-lived exchange requires `.env` values `META_APP_ID` and `META_APP_SECRET`;
  otherwise the supplied token is managed as-is and may still expire quickly.
- Token removal now cascades to Pages exclusively imported by that token.
- Shared/overlapping Page records never switch to another credential automatically;
  manual Pages remain untouched.
- The Page inventory UI groups records by Meta User token and exposes shared ownership without exposing secrets.
- Multi-token accounts are independent asset controllers, not a backup pool.
- User-token expiry now validates its own linked Page tokens independently:
  valid Page tokens remain usable in `degraded/REAUTH`; invalid Page tokens are disabled.
- Transient Meta/network errors preserve the last known-good Page state.
- Page-token observability is implemented:
  - each User-token/Page link has an independent Page-token status and check time;
  - the dashboard can manually validate a Page token against Meta;
  - the latest Meta validation error is persisted and shown without exposing secrets.

Current credential ownership rule:

- Account A managing A1-A10 and account B managing G1-G20 are two independent
  operational groups.
- Multiple accounts are not a failover pool for the same expired session.
- Sync, validation, removal and publishing readiness use only the Page's assigned
  operational credential.
- Removing credential A deletes A's operational Page records. Expiring credential A
  disables A Pages. Neither case may make credential B take over A Pages.
- System User inventory must use `/{system-user-id}/assigned_pages`.
  `/{business-id}/owned_pages` is broader than System User assignment and must not
  be used as the operational Page list.
- Verification on 2026-06-20:
  - Business Settings displayed 29 assigned business assets because the total
    includes 28 Facebook Pages plus the assigned Meta App.
  - Graph `/{system-user-id}/assigned_pages` returned 28 Pages.
  - After sync, local state is 28 total / 28 valid / 0 invalid.

Current Auto Reup Action state:

- Destination Page is step 1 and only valid imported Meta Pages are selectable.
- Action name is automatically the selected Page name on frontend and backend.
- Manual quick Page creation was removed from the Action modal.
- Frame Template list is loaded from the same `/frame-templates` catalog used by
  AI Video Text Translator.
- Creative Frame cannot be saved without a valid template.
- Schedule stores a random posting gap range, default 180-250 minutes.
- Backend exposes a real shared-pipeline bridge:
  `POST /auto-reup/actions/{action_id}/render`.
- The bridge calls the existing `render_single_video()` with the Action's
  Translate Caption and Creative Frame settings.
- Source crawling/indexing is operational:
  - Action `Vip12` scanned `https://www.facebook.com/oceandailyvn`.
  - It discovered reel `1490497985895962`.
  - Runtime state is `1 total / 1 scanned / 1 queued`.
  - Repeated scans do not duplicate the same Action/source video job.
- Queue worker is implemented:
  download source -> optional clean content -> shared render pipeline -> ready.
- Persistent scheduler is implemented with daily limit, active time window and
  persisted random min/max gaps.
- Real Facebook Page publishing is implemented through the Page's own token and
  Graph API video endpoint.
- Job state/progress is persisted and visible in the recent queue UI.
- Existing queued jobs will begin processing after the backend is restarted with
  the new code.
- Action runtime observability is implemented:
  - double-click an Action or click its Detail icon;
  - view live scan/download/render/wait/publish state;
  - view real next-scan and next-publish countdowns;
  - inspect persistent event history and per-job progress.
- Action scheduling has been upgraded:
  - `random_interval` keeps the previous random gap behavior;
  - `manual_times` uses fixed daily posting slots, one per configured post/day;
  - `smart_daily` automatically distributes posts inside the active window;
  - smart mode can target VN or US golden-hour profiles for Vietnamese or foreign-view pages.
- Source scanning/runtime has been upgraded:
  - discovered source videos are stored in `source_video_inventory`;
  - only a small active job buffer is created from inventory for upcoming posts;
  - `posted_source_history` prevents reposting the same source video to the same
    destination Page even after deleting/recreating an Action;
  - existing posted jobs are migrated into posted-source history at startup;
  - Facebook scans run hidden/offscreen by default, stop incremental scans after
    known reels, and report `login_required` instead of opening visible Chrome
    automatically;
  - UI exposes a manual Facebook login-browser button when a scan requires login.
- Facebook login detection was hardened on 2026-06-22:
  - no broad raw-HTML search for `checkpoint`, `log in` or login form strings;
  - use final auth URL, `c_user`/`xs` cookies, visible login/checkpoint controls
    and positive logged-in UI selectors instead;
  - this avoids false checkpoint/login errors on pages that are visibly logged in.
- Action cards now expose cached destination Page insight mini stats:
  - `page_insight_snapshots` stores Today/7d/28d views, engagements, followers
    and optional earnings when Meta returns them;
  - runtime refreshes active Action destination insights on a best-effort interval;
  - missing/unsupported Meta metrics are shown as fallback and do not break posting.
- Creative Frame has replaced Apply Frame as the official frame pipeline:
  - Single video and batch folder payloads can send `apply_creative_frame`.
  - Legacy `apply_frame` payloads are mapped into Creative Frame internally.
  - Creative Frame reuses the selected Frame Template, prepares a normalized source
    clip first, then calls the existing template renderer.
  - Options: remove source audio, visual repack variant, optional seed.
  - Smart Audio Layer can synthesize clean background audio by profile
    auto/nature/story/game/funny/action/calm and mix it into the beta output.
  - Smart Audio is intended as a first safe baseline until a curated clean audio
    library exists.
  - Default Smart Audio volume is now `1.0` with max `2.0`; earlier `0.18/0.35`
    was technically present but too quiet in browser preview.
  - Custom Smart Audio is supported:
    - frontend uploads a selected MP3/audio/video file through `/analyze/upload-audio`;
    - single and batch pass the uploaded server path to Creative Frame;
    - backend loops/trims/fades that custom audio to the rendered video duration.
  - Audio Profile selection has been removed from the frontend; custom audio is
    now the intended user-facing Smart Audio path.
- Creative Frame is now official:
  - AI Video Text Translator no longer exposes Apply Frame as a separate option.
  - Legacy `apply_frame` payloads are mapped into Creative Frame internally.
  - Auto Reup still stores the historical `apply_frame` DB flag, but it now means
    "Creative Frame enabled" in UI and render behavior.
  - Auto Reup action settings include Creative Frame audio/repack controls.

Current handoff note:

- 2026-06-22: User requested Codex to read AI_CONTEXT once before the next single task.
- No concrete task was provided after the "Sau đó chỉ làm 1 việc:" line, so no code changes were made for a new feature/fix.
- Await the user's exact next task before editing code.

Git handoff note:

- 2026-06-22: User requested deleting backup files and pushing the current work to Git.
- Local `backups/` directory was removed before staging.
- Commit/push should include the accumulated Auto Reup, Creative Frame, Frame Template Manager, and documentation updates currently in the working tree.
