# Changelog

## 0.1.0 - 2026-11-15

First public release.

- The `routine` skill with four commands: `run`, `new`, `save` and `status`.
- The `status.py` health check. It flags failed, stalled, overdue and waiting routines, with no model call.
- A launchd watchdog inside the skill that runs the check at 09:30 and 17:00.
- Routines are kept in `~/.routines`, outside the repo, so your own routines never end up in a commit.
- Install with `npx skills add kevinlin/claude-routines`.
