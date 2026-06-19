# AI Context - System Overview

## App shell

`frontend/src/App.jsx` switches modules:

- `translator`
- `crawler`
- `autoReup`

## Translator pipeline

1. Optional trim video.
2. Optional analyze/OCR/caption timeline.
3. Optional translate selected captions.
4. Optional render translated captions.
5. Optional apply frame template.
6. Merge/keep audio.
7. Output `*-done.mp4`.

If both Translate and Frame are enabled:

```text
input -> trim -> analyze/sub/render -> frame template -> audio -> output
```

If only Frame is enabled:

```text
input -> trim -> frame template -> audio -> output
```

## Batch

Batch scans input folder, skips existing output `*-done.mp4`, skips/error-logs `error-*` files, uses multiple worker threads, and exposes per-video progress.

## Auto Reup

Current Auto Reup is a dashboard/data scaffold. It supports action-style configuration, but real Facebook posting/crawler-to-post automation should be treated as future work unless already implemented later.
