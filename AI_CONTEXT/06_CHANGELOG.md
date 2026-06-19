# Changelog

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

## Luu y

Day khong phai changelog release chinh thuc theo version. Day la snapshot de agent moi nam lich su nhanh.
