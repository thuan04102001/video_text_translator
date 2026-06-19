# AI Context - Current Task

Last requested direction:

- Check whether unfinished processes were still running after credit limit/power interruption.
- If clean, apply AI handoff documentation to this project so another ChatGPT/Codex account can continue without re-analyzing everything from scratch.

Process check result:

- No active `python`, `uvicorn`, `ffmpeg`, `npm`, `vite`, or project `node` process was found.
- Only Codex internal `node_repl` was visible.

Current implementation task:

- Auto Reup is being implemented step by step, one completed process at a time.
- Process 1 is now implemented: Meta/Facebook fanpage connection and import.
- The UI can paste a Meta user access token and import available fanpages.
- Backend stores page access tokens locally in SQLite and only exposes `has_page_access_token` to the frontend.
- Meta import compatibility note:
  - `/me/accounts` request must use `id,name,access_token,tasks,category`.
  - Do not request `perms`; Graph API newer versions can reject it with `(#100) Tried accessing nonexisting field (perms)`.
- New ongoing rule: every future code/update task must sync relevant notes back into `AI_CONTEXT` before finishing.
- Repository is being initialized and published to GitHub with commit message `Initial commit`.
- Local runtime state such as SQLite page tokens, uploads, outputs, temp frames, logs, dependencies and backups must remain untracked.

Current boundary:

- Do not implement source crawling, scheduler, or publishing until the user confirms moving to the next process.
