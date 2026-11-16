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
- No app to keep running. Claude Desktop scheduled tasks do the scheduling. This repo holds one skill (markdown, a health check and a console script), and the routines are files in the routines home.

## Goals

- **Ask me, then continue.** A run stops before any change made in my name and continues after my yes.
- **Never fail silently.** Every run ends as `done`, `needs-you` or `failed`. A check outside Claude flags anything else.
- **Remember across runs.** Preferences and corrections persist in files, not in a conversation.
- **Save a session as a routine.** A job done once by hand becomes a routine.
- **Everything is a file.** I can read and edit every routine, note and run record.

## Non-goals

- No daemon, database, always-on web UI, BPMN, queue or telemetry export. The console (see Console) is a generated file plus a server that runs only while I have it open. It holds no state.
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
skills/routine/scripts/console.py                  the console: snapshot page and edit server
skills/routine/scripts/test_console.py             its tests
skills/routine/launchd/dev.routines.status.plist   the twice-daily watchdog
tests/e2e/                                         acceptance tests for the console
docs/specs/                                        design and implementation
docs/product/                                      the decision that retired Flow Fabric
```

The routines home, `~/.routines/` or `$ROUTINES_HOME`:

```
~/.routines/
  <name>/ROUTINE.md                   instructions, the source of truth
  <name>/notes.md                     memory
  <name>/runs/YYYY-MM-DD-HHMM.md      one record per run
  console.html                        generated snapshot, safe to delete
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
| `/routine console` | Runs `console.py`, which writes `console.html` and opens it |
| `/routine console edit` | Runs `console.py --serve` in the background and relays the URL |

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

The watchdog is the launchd agent `dev.routines.status`. At 09:30 and 17:00 it refreshes the console snapshot (`console.py --no-open`), then runs `status.py --notify`. It logs to `~/Library/Logs/routines-status.log`. The plist expects the skill at `~/.claude/skills/routine`. It works when Claude was never opened that day.

## Console

One place to see every routine's status, config, notes, open question and recent runs, and to change a frontmatter field without opening the file. Added in 0.2.0.

Options considered:

| Option | Fresh | Edits | Process | Main risk | Outcome |
|---|---|---|---|---|---|
| Plain `STATUS.md` in the routines home | At generation | In the file | None | Thin: no flag colour, long history is unreadable | Rejected |
| On-demand server only | Live | Frontmatter forms | While open | Nothing to look at when the server is down | Rejected |
| Generated `console.html`, no server | At generation | In the file | None | Read-only | Kept as the read half |
| Snapshot plus on-demand server | Snapshot always there, live while serving | Frontmatter forms | Only while serving | A local write endpoint to secure; a write can race a run | Chosen |

`console.py` is stdlib only, runs on Python 3.9, and reuses `status.py` for the folder listing, the flags and the frontmatter reading. The page has no JavaScript.

```
console.py [--home DIR] [--no-open]
    write <home>/console.html, print its path, open it. Exit 0.
    Missing home: print a one-line message, create nothing, exit 0.
console.py --serve [--home DIR] [--no-open] [--port N] [--idle-seconds N]
    also serve the live page with edit forms on http://127.0.0.1:<port>/?t=<token>,
    print that URL, exit on Ctrl-C or after --idle-seconds (default 1800)
    without a request.
```

What the page shows:

- The status table, flagged routines first. A flag is a text label, never colour alone.
- Per routine: the frontmatter fields, the `ROUTINE.md` body, `notes.md`, and the newest five run records. The open question of a `needs-you` run is in its record.
- The snapshot says when it was generated and gives each `ROUTINE.md` path. It is refreshed by `/routine console`, by the watchdog, and after every edit made through the server.

What the server may write:

- Six frontmatter fields of a `ROUTINE.md`: `purpose`, `schedule`, `cadence_hours`, `weekdays_only`, `paused`, `runs_on`.
- Nothing else. `name`, the body, `notes.md` and run records are edited as files.
- It cannot change the Desktop schedule or answer a `needs-you` question. The page says so next to `paused` and next to an open question.

How it writes:

- The writer works on the file's raw lines and never rebuilds the frontmatter from the parsed values. Only the named `key: value` lines change. Field order, unknown keys, comment lines, line endings, the body and the file mode are kept. A key that is not in the file yet is added before the closing `---`.
- It refuses a file it cannot edit safely and writes nothing: a `ROUTINE.md` that is a symlink, frontmatter without an opening or a closing `---`, or one of the six keys appearing twice.
- The file is replaced atomically: a temp file in the same folder, then a rename.
- Each form carries the sha256 of the `ROUTINE.md` it was rendered from. The server compares it when the request arrives and compares the file again right before the rename. If the file changed, it answers 409 and writes nothing. This covers a run or an editor changing the file while the page was open.
- The server handles one request at a time, so its own writes never overlap.

Rules the server holds:

- It binds `127.0.0.1` only. Every request carries the per-run token in the query string, or gets 403. The token comes from `secrets`, and a token from an earlier server run is worthless.
- The `Host` header must be `127.0.0.1:<port>` or `localhost:<port>`, or the request gets 403. This blocks DNS rebinding.
- A POST is form-encoded, declares its length and is at most 16 KB. The size is checked from the header before the body is read, and a request that stalls is dropped after 10 seconds.
- The edit id is the routine's folder name, never the `name` in the frontmatter, which nothing keeps unique. The id is looked up among the listed folders and never joined into a path. An unknown id gets 404.
- Values: no line separator of any kind that `str.splitlines` knows; no quote at the start or end, because the reader would strip it; `cadence_hours` is a finite positive number; the two booleans are `true` or `false`; `runs_on` is `desktop-local` or `cloud`. Any other field is refused.
- All file content is HTML-escaped, and the page is served with a content security policy that allows no scripts. Notes and run records can hold text a run copied from outside.
- A failed snapshot never stops the health check. The watchdog runs the two commands one after the other and does not chain them.

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
- `console.html` is a snapshot. Between refreshes it can be up to a watchdog interval old.
- Setting `paused` in the console does not pause the Desktop task. The task still fires.
- An editor or a run that writes `ROUTINE.md` in the instant between the console's last check and its rename loses that change. Nothing locks the file, because the other writers would not take the lock.
- The console does not check config. A missing `cadence_hours` still switches off `OVERDUE` without a warning.

## Open

- Spike results (impl task 1) and any design change they force.
