# AI Video Text Translator

Tool local tren Windows de xu ly video meme/caption theo batch:

- Video Text Translator: OCR caption, dich sang tieng Viet, render lai caption, ap dung frame template, cat dau/cuoi video.
- Video Crawler: crawl/download video tu nguon da cau hinh.
- Auto Reup Dashboard: dashboard quan ly action reup/dang bai, hien dang o muc scaffold UI + API CRUD noi bo.

## Chay nhanh

Lan dau:

```bat
setup.bat
```

Moi lan chay tool:

```bat
start.bat
```

URL mac dinh:

- Frontend: http://127.0.0.1:5173
- Backend API: http://127.0.0.1:8000

## Tai lieu AI context

Neu doi tai khoan ChatGPT/Codex hoac tiep tuc o may/agent khac, hay bat dau tu:

```text
AI_CONTEXT/00_README.md
```

Toan bo context/architecture/rules/changelog/todo da duoc gom trong `AI_CONTEXT/` theo thu tu doc ro rang de root du an gon hon.

Rule quan trong nhat: logic OCR/sub/render video dang on dinh, khong duoc tu y sua khi chi lam UI hoac module moi.
