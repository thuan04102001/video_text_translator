# AI Context - Decisions

## Video processing

- Keep Argos as primary offline translation path.
- Non-English main caption should fail instead of producing bad Vietnamese.
- Language gate must focus on main caption, not noisy secondary labels.
- Trim is preprocessing and must run before translate/frame.
- Frame template is isolated and must not change OCR/sub logic.

## UI

- The old Home layout was preferred by the user and became the visual base.
- UI should be dark, compact, polished, and not waste sidebar space.
- Logs should be clean and status-driven, not raw noisy backend messages.
- Frame Template Manager should open as a real screen/modal overlay, not trapped inside sidebar/card.

## Template design

- Template folders are data-driven through `template.json`.
- Canvas must stay 9:16.
- Background can be static/dynamic.
- Foreground is multi-layer, with list order controlling z-order.
- Thumbnail is only for template list preview, not render output.
- Preview helper video is only for template adjustment, not saved into template.

## Auto Reup

- The current Auto Reup work should be isolated from existing translator/crawler behavior.
- Config should be action-based: user clicks add action, then fills target page/source/content/pipeline/schedule.
