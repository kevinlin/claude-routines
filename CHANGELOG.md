# Changelog

## 0.2.0 - 2026-11-17

A console for seeing every routine on one page.

- The console snapshot. `/routine console` writes `~/.routines/console.html`: a status table with the flagged routines first, then each routine's settings, instructions, notes and newest run records. It has no forms and changes nothing.
- The edit server. `/routine console edit` serves the same page on 127.0.0.1 only, with a token that is new on every start, and stops after 30 minutes without a request. It can change six frontmatter fields: `purpose`, `schedule`, `cadence_hours`, `weekdays_only`, `paused` and `runs_on`.
- The watchdog refreshes the snapshot before each check. Remove and install the plist again to get it.
- Acceptance tests in CI, on the system Python and on Python 3.13.

## 0.1.0 - 2026-11-15

First public release.

- The `routine` skill with four commands: `run`, `new`, `save` and `status`.
- The `status.py` health check. It flags failed, stalled, overdue and waiting routines, with no model call.
- A launchd watchdog inside the skill that runs the check at 09:30 and 17:00.
- Routines are kept in `~/.routines`, outside the repo, so your own routines never end up in a commit.
- Install with `npx skills add kevinlin/claude-routines`.
