# AI Context - Next Task

Likely next steps depend on user direction:

1. Continue Auto Reup Dashboard:
   - run an end-to-end live validation with one Page and one source video
   - inspect any platform-specific yt-dlp authentication/download failure
   - add explicit retry controls and richer publish history if requested
   - add scheduler observability for next-post time if requested

2. Continue Frame Template:
   - add more templates
   - improve import/export
   - test intro/random sound/outro with batch

3. Stabilize video processing:
   - only if user provides failing samples
   - inspect before editing
   - avoid broad heuristic rewrites

4. Packaging/cleanup:
   - keep temp/frame sample cleanup strong
   - avoid zipping runtime/cache/venv/node_modules unless explicitly needed
