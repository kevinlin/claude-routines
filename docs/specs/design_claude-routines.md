# Design: Claude Routines

| | |
|---|---|
| Status | Approved 2026-11-15. Skill built and published; the first routines are paused drafts that have not run yet. |
| Owner | Kevin Lin |
| Replaces | Flow Fabric, see [decision_retire-flow-fabric.md](../product/decision_retire-flow-fabric.md) |
| Implementation | [impl_claude-routines.md](impl_claude-routines.md) |

## Intent

- Automate my own recurring work: jobs that depend on my data, my timing and my decisions.
- Skills hold common know-how, such as reviewing a Vertec month or recapping a meeting. A routine says when to use which skills, on whose data, and where I must be asked first. Routines call skills and never copy them.
- No app code. Claude Desktop scheduled tasks do the scheduling. This repo holds one skill (markdown plus one script), and the routines are files in the routines home.

## Goals

- **Ask me, then continue.** A run stops before any change made in my name and continues after my yes.
- **Never fail silently.** Every run ends as `done`, `needs-you` or `failed`. A check outside Claude flags anything else.
- **Remember across runs.** Preferences and corrections persist in files, not in a conversation.
- **Save a session as a routine.** A job done once by hand becomes a routine.
- **Everything is a file.** I can read and edit every routine, note and run record.

## Non-goals

- No daemon, database, web UI, BPMN, queue or telemetry export.
- No engine-owned control flow. Inside a run the agent picks the order of steps; only the ask-before stops and the run record are fixed.
- No resume from the failed step. A crashed run is flagged and run again.
- No sync between the `schedule` line in a file and the schedule in Desktop.
- No Stop-hook enforcement. Add one only if runs are seen ending without a final status.

## Anti-goals

These count as failures even when the routine otherwise works:

- A routine that writes, sends, books or approves without my yes for that item.
- Bypass-permissions mode used to keep runs unattended.
- A `done` that hides a failed or skipped step.
- Notifications for clean runs. They teach me to ignore notifications.

## Approaches considered

| Approach | Trade-off | Outcome |
|---|---|---|
| Routines on the Flow Fabric engine | Keeps BPMN authoring and a daemon to run and maintain | Rejected |
| Extend cowork-z automations | Real build work in Rust and the OpenCode sidecar | Rejected |
| Claude scheduled tasks + skills | No app code. Needs Desktop open and the Mac awake; the schedule lives in the app | Chosen |

## Platform this relies on

Stated in the Claude Code docs:

- A Desktop local scheduled task keeps its prompt at `~/.claude/scheduled-tasks/<name>/SKILL.md`, plus its own working folder, permission mode and run history (skipped runs included).
- After the Mac sleeps through a slot, Desktop starts one catch-up run for the most recent missed time, up to seven days back.
- A run that stops on a prompt is answered in that run's session. With Remote Control on, the answer can come from the phone.
- Cloud scheduled tasks add API and GitHub triggers but see only repos and connectors, not local files or CLIs.
- `CronCreate` is session-only and expires after seven days, so it cannot carry routines.

Assumed and not yet tried (impl task 1, the Desktop spike):

- A task prompt `/routine ...` loads a personal skill from `~/.claude/skills`.
- A run that asks a question sends a notification, shows as needing input, and continues when answered from the desktop or the phone.
- While a run waits for an answer, the next scheduled fire is skipped.
- Claude inside a Desktop session can create or change a local scheduled task.

If the second assumption fails, the carry-over rule (run protocol step 3) becomes the main way questions get answered.

## Layout

The repo:

```
skills/routine/SKILL.md                            the skill
skills/routine/references/ROUTINE.template.md      the template for new routines
skills/routine/scripts/status.py                   the health check
skills/routine/scripts/test_status.py              its tests
skills/routine/launchd/dev.routines.status.plist   the twice-daily watchdog
docs/specs/                                        design and implementation
docs/product/                                      the decision that retired Flow Fabric
```

The routines home, `~/.routines/` or `$ROUTINES_HOME`:

```
~/.routines/
  <name>/ROUTINE.md                   instructions, the source of truth
  <name>/notes.md                     memory
  <name>/runs/YYYY-MM-DD-HHMM.md      one record per run
```

- The skill is installed with `npx skills add kevinlin/claude-routines -g -a claude-code`, or for development as a symlink `~/.claude/skills/routine` -> `<repo>/skills/routine`.
- A folder is a routine when it holds a `ROUTINE.md` and its name does not start with `_` or `.`.
- The routines home is `$ROUTINES_HOME` when set, otherwise `~/.routines`. It is not in git. `status.py` lists nothing when it does not exist yet.

## ROUTINE.md

Frontmatter is flat `key: value` lines, because the health check parses nothing else.

| Field | Meaning |
|---|---|
| `name` | Folder name |
| `purpose` | One sentence, in my words |
| `schedule` | Human-readable, such as "Fridays 16:00". A record only; Desktop holds the real schedule |
| `cadence_hours` | Longest normal gap between runs: 24 daily, 168 weekly, 744 monthly |
| `weekdays_only` | `true` if the routine never runs on weekends, so Monday morning is not flagged overdue |
| `paused` | `true` while a draft or switched off. The health check leaves it alone |
| `runs_on` | `desktop-local` or `cloud` |

Body sections:

- **Goal**: what is true after a good run.
- **Steps**: outcomes plus the skill to use. No shell transcripts; the skill knows the commands and stays current when they change.
- **Ask before**: each action that needs my yes.
- **Done when**: the condition that can be checked.
- **Report**: what the summary line holds, and whether a clean run notifies.
- **Settle on the first run** (drafts only): questions the first supervised run asks me. The answers go to `notes.md` and the section is deleted.

## notes.md

- My standing preferences, corrections, and facts that stay true between runs.
- Short and dated. A newer note replaces one it contradicts.

## Run record

- File name is the start time, `runs/YYYY-MM-DD-HHMM.md`. The newest by name is the latest run.
- Frontmatter: `status` (`running`, `needs-you`, `done`, `failed`), `started`, `ended`, `summary`.
- Body: `## Done` (what was done, with numbers), `## Open question` (only for `needs-you`: the question, the options, the prepared work), `## Error` (only for `failed`: message and how far the run got).

## Run protocol

Kept once, in the `routine` skill, so every routine follows the same rules.

1. Read `ROUTINE.md`, `notes.md` and the newest run record.
2. Write the new record with `status: running` before any work, using the time from `date`. A run that dies after this is reported as stalled; a run that dies before it leaves no trace.
3. If the previous record is an unanswered `needs-you`, ask that question first with the work already prepared. Do not redo the work or pick an answer.
4. Do the Steps with the named skills, applying everything in `notes.md`.
5. Stop at every ask-before item (see Asking).
6. Close the record: `done` with a one-line summary, or `failed` with the reason. Any failed or skipped step means not `done`.
7. Add new preferences and corrections to `notes.md`.
8. Notify only for `needs-you`, `failed`, or when Report asks for a notification on success.

Notifications go through a push-notification tool when the run has one, otherwise `osascript`.

## Asking

- Applies to every ask-before item, and to any change outside the routine's folder that the routine does not explicitly allow: sending, booking, approving, merging, deleting.
- Finish the read-only preparation first, so one answer settles the question.
- Set the record to `needs-you`, write the question under `## Open question`, ask in the session, notify.
- On the answer, set the record back to `running` and continue. One yes covers one item.
- No answer: leave `needs-you` and stop. The next run asks again (protocol step 3).
- A skill's own confirmation rule, such as Vertec's preview-then-confirm, applies as well. It does not replace this one.

## Commands

| Prompt | Does |
|---|---|
| `/routine run <name> [args]` | Runs the routine by the protocol above |
| `/routine new <name>` | Short interview, then writes the folder from the template |
| `/routine save <name>` | Builds a routine from the session just done by hand: steps actually taken, each decision point becomes an ask-before item, each correction goes to `notes.md`. Shows the draft before writing |
| `/routine status` | Runs `status.py` and relays the table, flagged rows first |

## Health check

`status.py` reads each routine's frontmatter and its newest run record. Stdlib only, Python 3.9 or later, no model call.

| Flag | When |
|---|---|
| `NEVER RUN` | Not paused and no run record |
| `NEEDS-YOU` | Latest record is `needs-you` |
| `STALLED` | Latest record is `running` and started more than 2 hours ago |
| `FAILED` | Latest status is anything other than `done`, `running` or `needs-you`, including missing or unknown |
| `OVERDUE` | Latest record is `done` and the time since it started is more than `cadence_hours` plus a grace of 2 hours or 25 % of the cadence, whichever is larger. Weekend hours are not counted when `weekdays_only` is set |

- Paused routines are listed and never flagged.
- If a record has no readable `started`, the file's modification time is used.
- Prints a table (routine, status, last run, flag, summary). Exit code 1 when anything is flagged.
- `--notify` posts one macOS notification listing the flagged routines.

The watchdog is the launchd agent `dev.routines.status`. It runs `status.py --notify` at 09:30 and 17:00 and logs to `~/Library/Logs/routines-status.log`. The plist expects the skill at `~/.claude/skills/routine`. It works when Claude was never opened that day.

## Scheduling and permissions

- One Desktop local task per routine. Name: the routine's name. Prompt: `/routine run <name>`. Folder: the routine's folder. Schedule: from the routine's `schedule` line.
- Editing `ROUTINE.md` takes effect on the next run, with nothing to sync.
- The first run is supervised. Press Run now, choose "always allow" for read-only tools, leave every writing tool on ask, then remove `paused: true`.
- Never bypass permissions. The stops are how I stay in charge of what is done in my name.

## The routines

Personal routines live in the routines home, not in this repo.

A routine that follows a change through review and CI/CD to production is the multi-day, gated case Flow Fabric was built for, done here as a state file plus an hourly poll. Gates: review, CI, merged, deploy pipeline, live. It notifies on a gate change or a gate stuck past its limit, and asks before re-running, merging, commenting or deploying.

## Known limits

- Runs happen only while Claude Desktop is open and the Mac is awake.
- Nothing checks that a file's `schedule` matches the Desktop task.
- A run that waits on my answer probably blocks that routine's next fire (spike will confirm).
- MCP tools that require user interaction prompt on every run and stall an unattended run.
- A run that dies before writing its record is invisible until it shows up as `OVERDUE`.
- The watchdog's notification has been seen from a shell, not yet from launchd.

## Open

- Spike results (impl task 1) and any design change they force.
