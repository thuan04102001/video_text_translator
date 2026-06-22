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
12. Truoc moi task phai dung Git lam moc kiem tra:
    - chay `git status --short --branch`
    - xem `git log --oneline -5`
    - dung `git diff`/`git show` tren dung file lien quan truoc khi quet lai toan bo du an.
13. Khi dieu tra regression, uu tien so sanh voi commit gan nhat dang hoat dong tot; khong suy doan tu code hien tai neu lich su Git co the chi ro thay doi.
14. Khong `reset`, `checkout`, revert, commit hoac push ngam. Chi commit/push khi user yeu cau; khong duoc lam mat thay doi chua commit cua user.
15. Neu task bi gian doan vi het credit/limit/thoi gian hoac context compaction:
    - Khi duoc tiep tuc, phai resume dung cong viec dang lam do.
    - Khong khoi dong lai tu dau, khong lap lai phan tich neu context da co.
    - Doc summary/context hien co, kiem tra nhanh file dang sua va tiep tuc tu buoc
      tiep theo hop ly.
    - Neu user bao "tiep tuc" hoac thread duoc hoi lai, mac dinh tiep tuc task
      dang do truoc do tru khi user doi huong ro rang.
16. Meta token rule:
    - Khong tra User/Page access token ve frontend hoac ghi token vao log.
    - User token phai ma hoa khi luu local.
    - "Auto refresh" nghia la validate + sync lai Page token; khong duoc gia vo Meta co OAuth refresh token.
    - Moi Meta credential la mot nhom tai san rieng, khong coi credential khac la backup.
    - Vi du: credential A quan ly A1-A10; credential B quan ly G1-G20.
      Khong duoc tu dong dung B de thay A hoac nguoc lai.
    - Moi Page chi co mot operational credential qua `fanpages.credential_id`.
    - Link khac trong `meta_token_page_links` chi the hien quan he nhin thay/quan ly;
      khong co quyen tu dong tiep quan Page.
    - System User + Business ID la huong production 24/24.
    - System User chi import `/{system-user-id}/assigned_pages`.
      Khong dung toan bo `/{business-id}/owned_pages` lam danh sach van hanh,
      vi edge do gom ca Page chua gan cho System User.
    - User OAuth danh cho tai san ca nhan/direct Page.
    - Explorer/Test token chi dung test, khong dung lam credential production.
    - User token het han phai validate tung Page token cua chinh User do.
    - Khong suy dien Page token song/chet tu trang thai User token. Phai check dung
      Page token cua lien ket User token -> Page va luu ket qua rieng.
    - Page token con hop le duoc giu chay o trang thai `degraded/REAUTH`; Page token chet moi bi disable.
    - Loi mang/API tam thoi khong duoc xoa Page token hoac tat Page dang hoat dong.
    - Khong tu dong chuyen Page sang User token tai khoan khac khi User token het han.
    - Remove credential phai xoa toan bo Page dang operationally assigned cho
      credential do. Khong duoc tu dong chuyen Page sang credential con lai.
    - Page tao thu cong khong co Meta token owner khong duoc xoa theo lifecycle User token.
17. Auto Reup Action rule:
    - Ten Action phai lay tu ten fanpage dich, khong tin vao ten nhap tu frontend.
    - Fanpage dich phai co Page token hop le khi tao/bat Action.
    - Creative Frame bat buoc co template ton tai trong catalog Frame Template chung.
    - Translate Caption va Creative Frame phai goi `render_single_video()` hien co;
      khong copy hoac viet lai pipeline video rieng cho Auto Reup.
    - Lich dang luu theo khoang random min/max, khong dung mot moc delay co dinh.
    - UI Action khong tao fanpage thu cong; fanpage chi den tu Meta Credential Manager.
    - Source scan chi duoc lap chi muc va tao queue; khong sua OCR, sub, frame
      template hoac render logic.
    - Quet lai cung Action/source video khong duoc tao job trung.
    - Queue runtime phai theo state machine:
      `queued -> processing -> ready -> publishing -> posted/error`.
    - Worker Auto Reup bat buoc goi shared `render_action_video()` /
      `render_single_video()`; khong tao pipeline render rieng.
    - Scheduler phai ton trong `daily_limit`, khung gio Action va khoang random
      min/max da luu. Thoi gian duoc hieu theo `AUTO_REUP_TIMEZONE`.
    - Chi status `posted` khi Meta API tra upload thanh cong va co publish ID.
      Loi download/render/publish phai vao `error`, khong duoc pass am tham.
    - Moi Page chi publish bang operational credential cua chinh Page do;
      khong fallback cheo sang credential khac.
    - Action runtime detail phai lay stage/progress/schedule tu SQLite/backend
      runtime that. Khong dung timer gia de tang progress.
    - Event stream chi ghi thay doi stage/status/schedule quan trong; khong ghi
      moi tick progress de tranh lam phinh database.

## Cach lam viec

- Tim file bang `rg`/`rg --files`.
- Doc code hien co truoc khi sua.
- Dung `git diff -- <file>` va `git log -p -- <file>` de thu hep pham vi dieu tra, tranh doc lai du lieu khong lien quan.
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
