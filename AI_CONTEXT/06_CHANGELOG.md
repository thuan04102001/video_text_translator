# Changelog

## 2026-06-21 - Auto Reup Action runtime detail

- Added persistent `reup_action_events` history per Action.
- Added live runtime API with current phase, next scan, next publish countdown,
  active queue counts, per-job progress and event history.
- Added Action Detail modal opened by double-click or the Detail icon.
- Detail data refreshes every two seconds; countdown clocks refresh every second.
- Kept shared OCR/sub/frame/render pipeline unchanged.

## 2026-06-21 - Auto Reup smart schedule modes

- Added Action schedule modes: random interval, manual fixed times and smart daily plan.
- Manual mode stores one fixed time per daily post and repeats those slots each day.
- Smart mode distributes daily posts inside the active window and supports VN or US
  golden-hour profiles for different audience targets.
- Existing random interval scheduling remains available for old Actions.
- Kept shared video pipeline unchanged.

## 2026-06-21 - Auto Reup source inventory and hidden Facebook scan

- Added `source_video_inventory` as a source backlog separate from publish jobs.
- Added `posted_source_history` so a source video already posted to a destination
  Page is not posted again even if its Action is deleted and recreated.
- Migrates existing `posted` jobs into posted-source history on startup.
- Facebook scans now use known source IDs to stop incremental scans after several
  already-seen reels and keep initial/backfill scan bounded by config limits.
- Queue manager fills only a small active job buffer from inventory instead of
  rendering every discovered source video.
- Facebook Chrome scan opens hidden/offscreen by default and exposes a login
  repair route only when the session requires login/checkpoint handling.
- Kept shared video pipeline unchanged.

## 2026-06-22 - Facebook login detector hardening

- Replaced broad raw-HTML login/checkpoint text matching in the Facebook crawler.
- Auth detection now uses real auth URLs, Facebook session cookies, visible login
  or checkpoint form controls, and positive logged-in UI signals.
- Prevents false `LOGIN REQUIRED` / checkpoint errors when normal logged-in pages
  contain auth-related strings inside Facebook scripts or hidden markup.

## 2026-06-22 - Auto Reup Page insights mini stats

- Added cached `page_insight_snapshots` for destination Pages.
- Enabled background refresh of Page Insights for active Action destinations.
- Action cards now show compact Today stats for views, engagement, followers and
  optional estimated earnings with fallback when Meta does not return a metric.
- Insights refresh is best-effort and never blocks posting/runtime behavior.

## 2026-06-22 - Auto Reup Page insights period selector

- Action card insights now support `Tổng`, `Hôm nay`, `7 ngày` and `28 ngày`;
  the default selected period is `Tổng`.
- Backend snapshots include a `total` period and keep metric-source metadata so
  the UI can distinguish unavailable Meta metrics from real zero values.
- Page total followers are fetched from Page fields (`followers_count` /
  `fan_count`) while period views use Meta's newer `views` metric instead of
  legacy Page Insights view metrics that can report misleading zeros.
- The dashboard now refreshes missing/stale Page insight snapshots from Meta when
  Actions load, and exposes a manual refresh button on each Action card.
- Legacy cached view snapshots are ignored when they were produced by deprecated
  view metrics instead of the current `views` metric.
- Because the Page Insights `views` metric is not currently accepted by Meta for
  this Page/API version, Action stats now use the Page videos edge
  (`/{page_id}/videos?fields=views`) and published-post summaries for real
  reup video performance. Verified Vip12 returns 11 total views from Meta.
- Fixed follower period logic: `page_follows` is a lifetime total repeated per
  day, so period snapshots now use current `followers_count` / `fan_count`
  instead of summing the same lifetime value into 7/28 fake followers.
- Fixed the misleading Today views display: Meta's Page videos edge returns
  lifetime views per video, not daily view deltas, so Today views are now left
  empty (`--`) unless a real daily delta source is available.
- Fixed the same Today issue for engagement: published-post summaries expose
  current lifetime reactions/comments/shares, not engagement gained today, so
  Today engagement is left empty (`--`) without a real daily delta source.
- Normalized Action card progress display so it cannot show `0 total` while the
  same Action already has posted/error counts.
- Kept shared video pipeline unchanged.

## 2026-06-22 - Auto Reup total-only insights trend

- Removed the Action card period tabs from the active UI; Page insight display is
  now focused on total views, engagement, followers and earnings.
- Added `page_insight_history` to persist total snapshots over time.
- Total snapshots can now expose trend metadata comparing the current total with
  the nearest snapshot from roughly yesterday (20-36 hours earlier).
- The UI shows `% vs hôm qua` under each total metric, or `-- chưa có mốc` until
  enough history exists.
- Action progress ring now represents reup completion (`posted / target total`)
  instead of mixing scanned/error counts into the percent.
- The target total now comes from discovered source inventory / existing jobs
  (`reup_target_total`), not from the daily posting limit.
- Kept shared video pipeline unchanged.

## 2026-06-22 - Auto Reup default module

- Changed the app shell default module from AI Video Text Translator to Auto Reup.
- Moved the Auto Reup tab to the first position in the module switcher.

## 2026-06-22 - Meta credential setup guide

- Added an in-dashboard setup guide button to Meta Credential Manager.
- The guide explains how to find Business/BM ID, create a System User, generate
  a System User token, assign Page assets, and sync the credential in the tool.
- Moved the guide modal to the dashboard root so it opens as a proper centered
  overlay instead of being clipped inside the Meta panel.
- Improved guide modal scrolling so the final notes section has enough bottom
  padding and is not clipped at the viewport edge.

## Current snapshot

- UI chinh co 3 module: Video Text Translator, Video Crawler, Auto Reup.
- Translator UI da duoc thiet ke lai theo Home cu, toi uu layout/video preview/log.
- Single video va batch folder da noi backend.
- Batch co pause/continue/cancel/reset, log Error/Miss, per-video progress.
- Folder upload/temp runtime duoc cleanup khi start backend.
- FFmpeg/ffprobe duoc yeu cau trong `setup.bat` va `start.bat`.
- Language gate hien tai chi cho dich main caption tieng Anh.
- Frame Template Manager da co:
  - canvas 9:16
  - video slot
  - video transform/adjust
  - multi foreground layers
  - reorder foreground layers
  - voice intro MP3
  - random background sounds MP3
  - outro MP4
  - preview video tam de can template
- Trim dau/cuoi video da nam ngang hang pipeline option va chay truoc sub/template.
- Video Crawler da duoc tich hop vao app shell.
- Auto Reup Dashboard da co scaffold UI + API CRUD cho fanpage/source/action/content clean.
- Root da duoc don gon: tai lieu dai han chuyen vao `AI_CONTEXT/`, backup zip chuyen vao `backups/`.
- Them rule van hanh: moi lan code/cap nhat sau nay phai dong bo thay doi vao `AI_CONTEXT`.
- Auto Reup process 1 da duoc noi backend that:
  - Them Meta token import UI.
  - Them API `/auto-reup/meta/pages` va `/auto-reup/meta/import-pages`.
  - Backend goi Graph API `/me/accounts`.
  - Fanpage duoc import/upsert vao SQLite.
  - Page token duoc luu local va khong tra nguoc ra frontend.
- Fix Meta Graph API import fanpage:
  - Bo field `perms` khoi request `/me/accounts` vi Graph API moi bao `(#100) Tried accessing nonexisting field (perms)`.
  - Dung `tasks` lam field quyen page chinh.
- Chuan bi initial GitHub publish:
  - Bo sung `.gitignore` cho venv, node_modules, build, runtime media/temp/log, SQLite local va backup archives.
  - Source code, setup scripts, AI_CONTEXT, frame templates va regression fixtures duoc giu lai trong repository.
  - Repository dich: `thuan04102001/video_text_translator`.
- Dieu tra Fanpage Meta count:
  - Dashboard co 93 record local, 92 record duoc import cung luc vao `2026-06-19T01:16:23Z`.
  - UI `Page da ket noi` chi render 6 item do dang dung `pages.slice(0, 6)`, khong phai backend chi load 6.
  - `/me/accounts` cua token hien tai chi tra page nam trong pham vi quyen cua chinh token do; ket qua co the khac du lieu SQLite da import truoc.
- Them workflow rule dung Git status/log/diff lam baseline truoc khi dieu tra hoac sua code.
- Fix Meta fanpage inventory:
  - Thu thap Page tu `/me/accounts`, `/me/businesses`, `owned_pages` va `client_pages`.
  - Phan trang tung edge, gop trung theo `page_id`, luu nguon direct/BM va ten Business.
  - Thu hydrate Page Access Token rieng cho Page ma Business edge khong tra token.
  - Chi mark Page cu `stale` neu toan bo inventory thanh cong; scan mot phan khong vo hieu hoa du lieu cu.
  - UI bo gioi han `slice(0, 6)` va `slice(0, 5)`, hien du danh sach co search, scroll va status connected/stale/missing token.
- Them Meta multi-token manager:
  - Luu va quan ly nhieu User access token theo tung tai khoan quan tri.
  - User token duoc ma hoa bang machine-local key, khong tra token ve frontend.
  - Ho tro add/select/update/remove, manual Check & Sync va Refresh tat ca.
  - Backend monitor kiem tra dinh ky theo chu ky cua tung token.
  - Page co the duoc nhin thay boi nhieu credential, nhung chi co mot operational credential.
  - Ho tro doi long-lived token khi `.env` co `META_APP_ID` va `META_APP_SECRET`.
  - Bo sung `.env.example`, `cryptography` dependency va huong dan setup Meta.
- Fix lifecycle User token -> Fanpage:
  - Remove User token se xoa cac Page import chi thuoc token do.
  - Khong fallback sang Page token cua tai khoan khac.
  - Page tao thu cong duoc giu nguyen.
  - Action/source/job tham chieu Page bi xoa duoc detach an toan.
  - Danh sach Page tren UI duoc gom theo tung tai khoan User token; page shared hien them owner.
- Tach lifecycle User token va Page token:
  - Multi User token dung de control nhieu nhom tai san, khong phai backup cheo.
  - User token expired se trigger validate truc tiep tung Page token cua tai khoan do.
  - Page token con hop le tiep tuc usable voi status `degraded` va badge `REAUTH`.
  - Page token khong hop le moi bi clear/disable.
  - Loi ket noi Meta tam thoi khong lam mat trang thai Page dang tot.
  - Dashboard dem `connected + degraded` la usable va hien rieng so Page can re-auth.
- Them kiem tra Page token truc tiep:
  - Luu status `unknown/valid/invalid/error`, thoi diem check va loi gan nhat tren
    tung lien ket User token -> Page.
  - Them API va nut UI check Page token tren tung Page, khong expose secret.
  - Page shared duoc danh gia theo dung token owner dang hien thi.
- Nang cap Meta Credential Manager:
  - Them ba loai credential: `system_user`, `user_oauth`, `test_token`.
  - System User bat buoc khai bao Business ID va la flow production 24/24.
  - User OAuth giu flow direct/personal Page; Test token chi dung development.
  - Moi Page co `credential_id` chi ro credential van hanh duy nhat.
  - Nhieu credential dung de quan ly nhieu cum tai san doc lap, khong phai
    du phong cho cung mot Page hay cung mot phien het han.
  - Sync/import/check/remove chi tac dong credential duoc chon.
  - Remove credential xoa nhom Page duoc gan van hanh cho credential do;
    khong de Page mo coi va khong tu chuyen sang tai khoan khac.
  - Credential het han/bi xoa khong kich hoat fallback cheo.
  - UI gom Page theo operational credential va hien loai credential.
- Fix pham vi import System User:
  - Truoc day backend doc `Business/owned_pages`, nen 28 Page duoc gan bi tron
    voi 34 Page khac cua Business va tong local thanh 62.
  - System User nay Meta tra 28 Page qua `SystemUser/assigned_pages`.
  - Chuyen inventory sang `assigned_pages`; Page khong con duoc gan se bi xoa
    khoi nhom credential khi sync hoan tat.
  - Da verify voi credential PDT: Meta tra 28 assigned Page, local database sau
    sync con dung 28 Page VALID va 0 Page INVALID.
- Hoan thien cau hinh Auto Reup Action:
  - Dao Fanpage dich len buoc 1; bo hoan toan form tao nhanh fanpage thu cong.
  - Ten Action tu dong bang ten Page dich va duoc backend ep lai de tranh du lieu sai.
  - Load truc tiep catalog Frame Template cua AI Video Text Translator.
  - Apply Frame bat buoc chon template ton tai.
  - Lich dang doi tu delay co dinh sang khoang random min/max, mac dinh 180-250 phut.
  - Them backend bridge render Action vao `render_single_video()`, giu nguyen logic
    Translate Caption -> Apply Frame hien co.
  - Them bo chon interval ngau nhien that cho scheduler tuong lai.
- Hoan thien source inventory cho Auto Reup Action:
  - Them scanner nen va nut quet nguon ngay.
  - Facebook dung lai Playwright crawler hien co; TikTok dung yt-dlp.
  - Them `action_id` vao queue va chong tao trung job khi quet lai.
  - UI poll runtime va hien `SOURCE READY / SCANNING / SCAN ERROR`.
- Hoan thien Auto Reup execution runtime:
  - Them queue worker tai video nguon va lay description/title that.
  - Content cleaner duoc ap dung theo cau hinh Action.
  - Worker goi dung shared `render_action_video()` -> `render_single_video()`,
    khong sua/copy logic OCR, sub, dich hay Frame Template.
  - Them state/progress that:
    `queued -> processing -> ready -> publishing -> posted/error`.
  - Them scheduler theo timezone, daily limit, khung gio va random min/max.
  - Them upload MP4 that len Facebook Page qua Graph API Page token.
  - Job dang do duoc recovery sau restart; temp job duoc xoa sau publish thanh cong.
  - UI Hang doi hien ca processing/ready/publishing va progress tung job.
- Them Creative Frame Beta cho AI Video Text Translator:
  - Giu nguyen Apply Frame va Video Frame Template hien tai lam duong du phong.
  - Them nhanh `apply_creative_frame` cho single video va batch folder.
  - Beta dung chung catalog template, nhung co buoc chuan hoa source rieng truoc
    khi ghep frame.
  - Ho tro tuy chon remove source audio, visual repack variant va seed optional.
  - Them Smart Audio Layer: tao audio nen sach bang FFmpeg theo profile
    auto/nature/story/game/funny/action/calm va mix vao output.
  - Khi bo source audio, Smart Audio giup video khong bi cam tieng; khi giu source
    audio, Smart Audio duoc mix nhe lam nen.
  - Tang gain Smart Audio mac dinh tu muc qua nho len `1.0`, cho phep toi da `2.0`
    de browser preview nghe ro hon.
  - Them custom audio cho Creative Frame Beta:
    - `/analyze/upload-audio` nhan MP3/M4A/AAC/WAV/OGG hoac MP4/MOV/MKV/WEBM.
    - UI cho chon file audio/video rieng cho Smart Audio.
    - Neu co custom audio, backend loop/cat/fade/mix file do thay vi audio profile
      tong hop.
  - UI da bo dropdown Audio Profile; nguoi dung tap trung chon audio custom that.
  - Backend chan bat dong thoi Apply Frame va Creative Frame Beta.
- Chuyen Creative Frame thanh pipeline chinh thuc:
  - UI AI Video Text Translator da bo nut Apply Frame, chi con Creative Frame.
  - Backend map field cu `apply_frame` sang Creative Frame de giu tuong thich
    voi batch/action cu.
  - Auto Reup action dung `apply_frame` nhu co bat/tat Creative Frame trong DB
    de tranh migrate rut gon, nhung label/UI/render bridge da chuyen sang Creative.
  - Auto Reup action co cau hinh remove source audio, visual repack, custom audio
    va volume cho Creative Frame.

## Luu y

Day khong phai changelog release chinh thuc theo version. Day la snapshot de agent moi nam lich su nhanh.
