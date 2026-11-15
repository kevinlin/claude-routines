# Routines

This repo is the `routine` skill for Claude Code: recurring jobs, kept as files. A routine says when a job runs, on whose data, and where you want to be asked first. It calls skills for the actual know-how.

There is no app here. Claude Desktop's local scheduled tasks do the scheduling, the `routine` skill holds the rules every run follows, and a small script checks that nothing failed quietly. The routines themselves are files in your routines home.

## Install

```
npx skills add kevinlin/claude-routines -g -a claude-code
```

You need Claude Desktop on macOS for the scheduled tasks, and `python3` for the health check.

For development:

```
git clone https://github.com/kevinlin/claude-routines
ln -s "$PWD/claude-routines/skills/routine" ~/.claude/skills/routine
```

## Where routines live

Routines live in `~/.routines/`, or in `$ROUTINES_HOME` when you set it. The folder is created on your first `/routine new`. It is not part of this repo.

```
~/.routines/             or $ROUTINES_HOME
  <name>/ROUTINE.md      what the routine does; edit this to change it
  <name>/notes.md        what it has learned about your preferences
  <name>/runs/           one record per run: running, needs-you, done or failed
```

## Using it

| I want to | Do this |
|---|---|
| Run one now | `/routine run <name>` in any Claude Code session |
| See what needs me | `/routine status`, or `python3 ~/.claude/skills/routine/scripts/status.py` |
| Make a job repeat | do it once by hand in a session, then `/routine save <name>` |
| Start from a description | `/routine new <name>` |
| Change a routine | edit its `ROUTINE.md`; the next run uses it |
| Change when it runs | edit the task in Claude Desktop (the schedule is not in the file) |
| Switch one off | set `paused: true` and pause the Desktop task |

## First: the Desktop spike

The design assumes four things about Claude Desktop that have not been tried yet. Check them with a throwaway local task before scheduling the real routines, and write down what happened.

1. A task whose prompt is `/routine status` loads the `routine` skill from `~/.claude/skills`.
   - Result:
2. A run that asks a question shows as needing input, sends a notification, and continues when answered, both from the desktop and from the phone.
   - Result:
3. While a run is waiting on an answer, what does the next scheduled fire do? Expected: skipped, with "previous run still in progress" in the history.
   - Result:
4. Can Claude, inside a Desktop session, create or change a local scheduled task when asked?
   - Result:

If 2 fails, nothing is lost: an unanswered question stays in the run record as `needs-you`, the watchdog flags it, and the next run asks it again before doing anything else.

## Turning a routine on

1. In Claude Desktop: Scheduled > New > Local. Name it after the routine, set the prompt to `/routine run <name>`, the folder to `~/.routines/<name>`, and the schedule from the routine's `schedule` line.
2. Press Run now and watch it. Answer its first-run questions. Choose "always allow" for read-only tools; leave anything that writes on ask.
3. Remove `paused: true` from its `ROUTINE.md`.

## The watchdog

`status.py` flags a routine when its latest run is `failed`, is waiting on you, has been `running` for more than two hours, or is older than its `cadence_hours` allows. launchd runs it at 09:30 and 17:00 and posts one macOS notification listing what is flagged. It does not need Claude to be open.

```
# install
cp ~/.claude/skills/routine/launchd/dev.routines.status.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/dev.routines.status.plist

# remove
launchctl bootout gui/$(id -u)/dev.routines.status
rm ~/Library/LaunchAgents/dev.routines.status.plist
```

The plist expects the skill at `~/.claude/skills/routine`. Output goes to `~/Library/Logs/routines-status.log`.

## Limits

- Routines run only while Claude Desktop is open and the Mac is awake. After sleep, Desktop starts one catch-up run for the most recent missed time.
- The schedule lives in the Desktop app. The `schedule` line in a `ROUTINE.md` is a note, and nothing checks that the two agree.
- Tools that insist on asking every time will stall an unattended run until answered.

## This repo

```
skills/routine/SKILL.md                            the skill
skills/routine/references/ROUTINE.template.md      the template for new routines
skills/routine/scripts/status.py                   the health check
skills/routine/scripts/test_status.py              its tests
skills/routine/launchd/dev.routines.status.plist   the twice-daily watchdog
docs/specs/                                        design and implementation
docs/product/                                      the decision that retired Flow Fabric
```

`docs/product/` is a copy from the archived [kevinlin/flow-fabric](https://github.com/kevinlin/flow-fabric), the project this replaced, and its relative links point into that repo.

## Development

Run the tests:

```
cd skills/routine/scripts && python3 -m unittest
```

CI runs them on macOS with the system Python 3.9.

## License

MIT, see [LICENSE](LICENSE).
