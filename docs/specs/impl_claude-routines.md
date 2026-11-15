# Implementation: Claude Routines

Design: [design_claude-routines.md](design_claude-routines.md). Status as of 2026-11-15.

| # | Task | Status |
|---|---|---|
| 1 | Desktop spike | Not started, needs the owner in Claude Desktop |
| 2 | Repo and kit | Done, with gaps |
| 3 | `status.py` with tests | Done |
| 4 | First routine | Personal, tracked in `~/.routines/README.md` |
| 5 | Watchdog | Reinstalled in task 10; two checks open |
| 6 | Remaining routines | Personal, tracked in `~/.routines/README.md` |
| 7 | Retire Flow Fabric | Done |
| 8 | One-week acceptance | Not started |
| 9 | Re-point paths after the move | Done |
| 10 | Skill repo and publish | Done |

## 1. Desktop spike

- Create a throwaway local task and check the four assumptions in the design's "Platform this relies on".
- Verify: each result written to the "First: the Desktop spike" section of [README.md](../../README.md).
- If answering inside the session fails, the carry-over rule becomes the main path. Note that in the design.

## 2. Repo and kit

- Done: repo initialised, `routine` skill (`run`, `new`, `save`, `status`), `ROUTINE.template.md`, README.
- Verified 2026-11-15 in fresh `claude -p` sessions: `/routine status` relays the table, and `/routine run demo` on a throwaway unpaused routine wrote its record first, did the step, and closed it `done`.
- Not done: the skill-creator eval loop, and `/routine new demo` as a skill call.
- Verify: `/routine status` in a fresh session prints the table; `/routine new demo` writes a valid folder that `status.py` lists.

## 3. `status.py` with tests

- Done: 16 `unittest` cases over temp-dir fixtures, one per flag plus paused, weekdays-only, timezone, kit-folder skipping, missing home, exit code and notify. The notifier is injected, so tests post nothing.
- Verified: green on `/usr/bin/python3` 3.9.6 and Homebrew Python 3.13.
- Rerun: `cd skills/routine/scripts && python3 -m unittest`.

## 4. First routine

- Personal; tracked in `~/.routines/README.md`.

## 5. Watchdog

- Done: `dev.routines.status` loaded in launchd; one manual kick exited 0 and wrote the log. The notify path was tested from a shell with a throwaway failed routine.
- Not done: kill a run mid-way and see `STALLED` at the next check; see a notification posted by launchd itself.
- Reinstalled with the user-independent plist in task 10.

## 6. Remaining routines

- Personal; tracked in `~/.routines/README.md`.

## 7. Retire Flow Fabric

- Done: decision record, cancelled milestones in the spec index, and a notice in `CLAUDE.md`, pushed to `kevinlin/flow-fabric` main (`17dd16c`). The repo was archived on 2026-11-15. Issue #1 had already been deleted.
- A copy of the decision record is in [docs/product](../product/decision_retire-flow-fabric.md).

## 8. One-week acceptance

- The first routines live for one week.
- Checks:
  - Ask and continue: a routine that writes stops before a write, and an answer from the phone continues the same run.
  - Memory: a correction given in one run is followed by the next run from `notes.md`.
  - Crash: a killed run is reported `STALLED`.
  - Sleep: after a missed slot, the catch-up run writes a normal record.
  - Save: `/routine save` on a session done by hand gives a `ROUTINE.md` that runs unedited or with small edits.
  - Every run has a final status or a flag, and no failure went unnoticed.

## 9. Re-point paths after the move

Done 2026-11-15 in task 10. The routines home moved to `~/.routines` instead of defaulting to the repo, so the `parents[3]` proposal was dropped.

The repo moved out of `~/routines` into a normal checkout. These still point at the old place:

- `~/.claude/skills/routine` is gone. Recreate it as a symlink to `_kit/routine`.
- The installed launchd plist runs `~/routines/_kit/routine/scripts/status.py`. Until it is fixed, the 09:30 and 17:00 checks fail into the log and post no notification.
- `status.py` defaults `--home` to `~/routines`. Proposed: default to the repo that holds the script (`Path(__file__).resolve().parents[3]`), so a later move needs no edit. `$ROUTINES_HOME` still wins.
- `_kit/routine/SKILL.md` (description and layout block) and the README's "Turning a routine on" step name `~/routines`.
- Leave the decision record alone; it is a dated record.
- Verify: `python3 _kit/routine/scripts/status.py` with no arguments lists the five routines; after reinstalling the plist, `launchctl kickstart` exits 0 and the log shows the table; `/routine status` works in a fresh session.

## 10. Skill repo and publish

- Done: the old kit folder renamed to `skills/`, and the launchd plist moved into the skill with no user-specific paths (it runs through `/bin/sh` so `$HOME` expands).
- Done: the routines home moved to `~/.routines`, and `status.py` lists nothing when it is missing.
- Done: LICENSE (MIT), CHANGELOG, a macOS CI workflow. Published at github.com/kevinlin/claude-routines.
- Verify:
  - unit tests on `/usr/bin/python3` and python3.13
  - `status.py` with no arguments lists the routines in `~/.routines`
  - `launchctl kickstart` exits 0 and the log shows the table
  - `/routine status` works in a fresh session
  - `npx skills add kevinlin/claude-routines --list` finds `routine`
