# Workflow Rules

## Hard rules

1. Khong tu y sua logic OCR/sub/render/box/timeline/dich khi user chi yeu cau UI, Auto Reup, docs, setup, hoac frame template UX.
2. Neu bat buoc sua logic video, phai giai thich dung vung sua va giu case dang tot.
3. Output video phai giu rule `nameinput-done.mp4`.
4. Video non-English phai fail clean: doi ten input thanh `error-nameinput.mp4`, log Error/Miss `SUB FAIL`, khong render pass.
5. File input co prefix `error-` phai skip thang sang Error/Miss.
6. Trim dau/cuoi video la buoc preprocess dau tien, truoc sub va truoc frame template.
7. Frame Template la module doc lap, khong can thiep OCR/dich/box.
8. Template mac dinh theo canvas 9:16, thuong 1080 x 1920.
9. Foreground layer order trong list phai dong bo voi z-index preview va render.
10. Log batch phai clean: video dang xu ly on top, done day xuong duoi, fail chi nam Error/Miss.
11. Moi lan code hoac cap nhat logic/UI/setup/docs phai dong bo lai `AI_CONTEXT` lien quan truoc khi ket thuc task.

## Cach lam viec

- Tim file bang `rg`/`rg --files`.
- Doc code hien co truoc khi sua.
- Edit thu cong bang `apply_patch`.
- Khong xoa/revert thay doi cua user neu khong duoc yeu cau.
- Sau sua frontend: chay `npm run build` trong `frontend`.
- Sau sua Python: chay `python -m py_compile` voi file lien quan.
- Neu app dang mo o browser, verify UI bang in-app browser neu can.
- Ket thuc moi task phai cap nhat toi thieu mot trong cac file phu hop:
  `06_CHANGELOG.md`, `08_CURRENT_TASK.md`, `09_NEXT_TASK.md`, `10_TODO.md`,
  hoac file context/rule tuong ung neu co thay doi quy tac hay kien truc.

## Vung nhay cam

- `backend/engines/meme_caption/*`
- `backend/core/render/text_box_renderer.py`
- `backend/app/services/render_service.py`
- `backend/app/services/batch_service.py`
- `backend/core/translation/language_detector.py`

Chi sua cac file tren khi task thuc su yeu cau logic video.
