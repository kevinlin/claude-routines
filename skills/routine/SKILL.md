---
name: routine
description: Run, create, save and check personal routines, the recurring jobs kept as markdown in ~/.routines (timesheet checks, morning briefings, weekly reviews, following a change to production). Use this skill whenever a prompt says "/routine ...", whenever a scheduled task's prompt is "/routine run <name>", when the user asks to turn the session they just did into something that repeats ("save this as a routine", "do this every Friday"), asks for a new recurring job, or asks whether their routines ran, which failed, or what is waiting on them. Use it even if they say "automation" or "scheduled task" instead of "routine".
metadata:
  version: 0.2.0
---

# Routine

A routine is a personal, recurring job: one person's data, timing and decisions. It is different from a skill. A skill is a reusable capability (how to review a Vertec month); a routine says when to use capabilities, on whose data, and where that person wants to be asked first. Routines call skills. They don't duplicate them.

Routines live as plain files so the owner can read and change every one of them:

```
~/.routines/               (or $ROUTINES_HOME)
  console.html             generated snapshot of every routine (safe to delete)
  <name>/
    ROUTINE.md             the instructions; the source of truth
    notes.md               memory: preferences, corrections, facts from earlier runs
    runs/YYYY-MM-DD-HHMM.md   one record per run
```

A scheduler (normally a Claude Desktop local scheduled task) only holds the pointer prompt `/routine run <name>`. Everything else is in the folder, so an edit to `ROUTINE.md` applies on the next run.

## Commands

| Prompt | What to do |
|---|---|
| `/routine run <name> [args]` | Execute the routine, following "Running a routine" |
| `/routine new <name>` | Interview the user briefly, then write the folder ("Creating a routine") |
| `/routine save <name>` | Turn the work just done in this session into a routine ("Saving a session") |
| `/routine status` | Run `python3 <this skill>/scripts/status.py` and relay the table, flagged rows first |
| `/routine console` | Run `python3 <this skill>/scripts/console.py` and relay the path it prints |
| `/routine console edit` | Run `python3 <this skill>/scripts/console.py --serve` in the background, because it keeps running. Relay the URL line it prints, and say it stops by itself after 30 minutes without a request |

If the name is missing or unknown, list the folders in the routines home and ask which one.

## Running a routine

The run may be unattended: nobody is watching, and the owner will only know what happened from the files you leave. That is why the record comes first and the status is never left vague.

1. **Read** `ROUTINE.md`, `notes.md`, and the newest file in `runs/`.
2. **Write the run record before doing any work.** Get the time from `date +%Y-%m-%dT%H:%M:%S` (do not guess it) and create `runs/<YYYY-MM-DD-HHMM>.md` with `status: running`. A health check outside Claude reads these records; a run that dies after this point is then reported as stalled, while a run that dies before leaving any record goes unnoticed.
3. **Carry over an open question.** If the newest earlier record is `needs-you` and its question was never answered, start with that question and the work already prepared. Do not redo the work or silently pick an answer.
4. **Do the Steps** in `ROUTINE.md`, using the skills it names. Apply everything in `notes.md`; those are the owner's standing preferences and corrections.
5. **Stop at every "Ask before" item.** See "Asking" below.
6. **Close the record.** Set `status: done` with a one-line `summary`, or `status: failed` with what went wrong and how far you got. If any step failed or was skipped, the run is not `done`; say so. A wrong `done` is worse than a `failed`, because nobody looks at a `done`.
7. **Update `notes.md`** with anything the owner told you that should hold next time (a preference, a correction, a fact that will still be true). Keep it short and dated; remove a note that a newer one contradicts.
8. **Notify** only when the status is `needs-you` or `failed`, or when the routine's Report section asks for a notification on success. A notification for a clean run teaches the owner to ignore them.

To notify, use a push-notification tool if you have one; otherwise run
`osascript -e 'display notification "<one line>" with title "Routine: <name>"'`.
Lead with what the owner has to act on.

### Run record format

```markdown
---
status: running            # running | needs-you | done | failed
started: 2026-11-20T16:00:12
ended:
summary:
---

## Done
- what was actually done, with numbers where they exist

## Open question
(only when needs-you: the question, the options, and what is already prepared)

## Error
(only when failed: what failed, the message, how far the run got)
```

Keep the frontmatter flat (`key: value`); the health check parses only that.

### Asking

Anything listed under "Ask before" in `ROUTINE.md`, and anything that changes something outside the routine's own folder that the routine doesn't explicitly allow (sending a message, booking time, approving, merging, deleting), needs the owner's yes for that specific item.

1. Finish all the read-only preparation first, so the question can be answered in one go.
2. Set the record to `status: needs-you` and write the question, the options and the prepared work under "Open question".
3. Ask in the session (use a question tool if you have one) and send a notification.
4. When the answer arrives, set the record back to `running` and continue. One yes covers one item; a yes to Monday's booking is not a yes to Tuesday's.
5. If no answer comes, leave the record as `needs-you` and stop. The next run picks it up through step 3 of "Running a routine".

If a skill the routine uses has its own confirmation rule (for example a preview-then-confirm flow), follow that rule as well; it does not replace this one.

## ROUTINE.md format

Start from `references/ROUTINE.template.md`. Frontmatter fields:

- `name`: folder name.
- `purpose`: one sentence, in the owner's words.
- `schedule`: human-readable ("Fridays 16:00"). A record only; the scheduler holds the real schedule.
- `cadence_hours`: the longest normal gap between runs (24 for daily, 168 for weekly, 744 for monthly). The health check flags the routine as overdue after this plus a grace period.
- `weekdays_only`: `true` if it never runs on weekends, so Monday morning isn't flagged.
- `paused`: `true` while a routine is a draft or switched off; the health check then leaves it alone.
- `runs_on`: `desktop-local` or `cloud`.

Body sections: **Goal**, **Steps**, **Ask before**, **Done when**, **Report**. Write steps as outcomes plus the skill to use, not as shell transcripts; the skill already knows the commands and will stay current when they change.

## Creating a routine (`new`)

Ask only what you cannot infer, one or two questions at a time: what the job is for, when it should run, what it reads and what it may change, where the owner wants to be asked first, and how they will know it went well. Then write the folder under the routines home (create the home first if it does not exist): `ROUTINE.md`, an empty `notes.md` and an empty `runs/` folder (add a `.gitkeep`). Show the file, and register the schedule ("Scheduling").

Suggest doing the job once by hand first and using `save` instead. A routine written from a real run is usually better than one written from a description.

## Saving a session (`save`)

The user has just done the job by hand in this session and wants it to repeat. Build the routine from what happened, not from what a tidy version would look like:

- **Steps**: the steps that were actually needed, in order, naming each skill or tool used. Leave out dead ends.
- **Ask before**: every point where the user made a decision or approved something.
- **notes.md**: every correction or preference they voiced ("don't book on that project", "keep it under ten lines").
- **Done when** and **Report**: what the session ended with that the user was satisfied by.

Show the draft and ask what is wrong or missing before writing it. Then register the schedule.

## Scheduling

Routines normally run as Claude Desktop local scheduled tasks, because they need local files, CLIs and logins.

- If you have a tool that creates or updates local scheduled tasks, create one named after the routine with prompt `/routine run <name>`, the routine folder as working folder, and the schedule from the frontmatter.
- If you don't, give the user these values to enter under Desktop > Scheduled > New > Local: name, prompt `/routine run <name>`, folder, schedule.
- Either way, ask the user to press **Run now** once and watch it: approve the read-only tools with "always allow" so later runs don't stall on permission prompts, and leave anything that writes on ask. Then remove `paused: true`.

Do not set a routine to bypass permissions to make it run unattended. The stops are how the owner stays in charge of what gets changed in their name.

## Console

`/routine console` writes `console.html` in the routines home and prints its path. The page is a snapshot of every routine: a status table with the flagged routines first, then for each routine its six frontmatter fields, the `ROUTINE.md` body, `notes.md` and the newest five run records. It also shows when it was generated and where each `ROUTINE.md` is. It has no forms and changes nothing.

`/routine console edit` writes the same page, then serves it on 127.0.0.1 with a form for each routine. The URL it prints holds a token that is new each time the server starts. The server can change six frontmatter fields: `purpose`, `schedule`, `cadence_hours`, `weekdays_only`, `paused` and `runs_on`. Everything else is edited as a file.

Pausing a routine in the console sets `paused: true` in its `ROUTINE.md`. It does not pause the task in Claude Desktop. A `needs-you` question is answered in the Claude session, not in the console.

## Watchdog

On macOS, a launchd job can check the routines even when Claude was never opened. At 09:30 and 17:00 it refreshes the console snapshot with `console.py --no-open`, then runs `status.py --notify` without Claude and posts one notification listing the flagged routines. The check runs even when the refresh fails. It logs to `~/Library/Logs/routines-status.log`. It expects this skill at `~/.claude/skills/routine`.

Install it only when the user asks.

```
# install
cp ~/.claude/skills/routine/launchd/dev.routines.status.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/dev.routines.status.plist

# remove
launchctl bootout gui/$(id -u)/dev.routines.status
rm ~/Library/LaunchAgents/dev.routines.status.plist
```

## Things that go wrong

- **The run started late.** Desktop runs one catch-up run after sleep, so a 09:00 routine can start at 23:00. Check the time before doing anything date-sensitive and say in the record that it was a catch-up.
- **A tool or login is unavailable.** Record `failed` with the exact message. Do not substitute another data source and report as if nothing changed.
- **Nothing to do.** That is `done` with a summary such as "week complete, nothing missing". Still write the record.
