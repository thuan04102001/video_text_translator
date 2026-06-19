# Project Context

## Muc tieu

Du an nay la tool xu ly video meme/caption local:

1. Nhan dien caption goc trong video.
2. Dich caption tieng Anh sang tieng Viet.
3. Render caption moi de che caption goc dep, dung timeline.
4. Xu ly hang loat folder video.
5. Co tuy chon ap dung frame template 9:16.
6. Co Video Crawler va Auto Reup Dashboard lam module rieng.

## Stack chinh

- Backend: FastAPI, Python, OpenCV, EasyOCR, FFmpeg, Argos Translate, optional OpenAI/Gemini/OpenRouter.
- Frontend: React + Vite, CSS inline trong page/component hien tai.
- Runtime: Windows, FFmpeg/ffprobe trong PATH, Python venv tai `backend/venv`, Node/npm cho frontend.

## Module hien co

- `Video Text Translator`: module chinh cho single video va batch folder.
- `Video Crawler`: module crawler/download video, tach UI rieng.
- `Auto Reup`: dashboard moi cho quan ly action reup/dang bai, hien co UI + API CRUD noi bo, chua nen xem la da dang Facebook that.

## Trang thai xu ly video

Nhung logic da duoc tinh chinh nhieu va can giu on dinh:

- Caption detection/timeline.
- Box fit/cover caption goc.
- Language gate: chi dich video co main caption tieng Anh; non-English phai SUB FAIL va khong render pass.
- Batch progress theo tung video.
- Error input prefix `error-`.
- Output name rule: `nameinput-done.mp4`.
- Frame template 9:16, video slot, foreground layers, intro/sound/outro.
- Trim dau/cuoi video phai chay truoc sub/template.

## Nguyen tac khi tiep tuc

- Doc `04_WORKFLOW_RULES.md` truoc khi sua code.
- Neu task lien quan UI, han che sua backend logic.
- Neu task lien quan Auto Reup, khong dung vao OCR/sub/render neu khong can.
- Moi thay doi lon can build/test nhe truoc khi ket luan.

## User preference

- Khi user da confirm `ok`, uu tien trien khai truc tiep.
- Giao dien can gon, dep, chuyen nghiep, khong lang phi dien tich.
- Neu loi video/chat luong sub, can phan tich nguyen nhan truoc khi sua.
- Tranh sua case A lam hong case B; moi thay doi logic video phai rat can trong.
