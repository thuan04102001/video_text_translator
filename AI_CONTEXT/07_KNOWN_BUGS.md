# AI Context - Known Bugs And Risk Areas

## Risk areas

- Language classification has historically been fragile: fixing one case can break English pass cases or Spanish fail cases.
- Caption grouping/merging is sensitive: separated captions and stacked main captions need different handling.
- Box fit has been heavily tuned: small changes can cause exposed original caption edges or oversized boxes.
- Foreground layer z-order must remain synchronized between UI preview and saved/rendered template.
- Batch progress must reflect real item progress, not fixed timer estimates.

## Current operational note

On 2026-06-18 quick process check showed no active backend/frontend/ffmpeg render process except Codex internal `node_repl`.
