#!/usr/bin/env python3
"""Health check for personal routines.

Reads each routine's ROUTINE.md and its newest run record and flags what needs
attention. Deliberately no LLM and no third-party imports, so it can run from
launchd even when Claude was never opened. Python 3.9 compatible.
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

STALL_HOURS = 2  # a run still "running" after this long has crashed or hung


def frontmatter(path):
    # shortcut: flat `key: value` lines only, no nested YAML; switch to a YAML
    # parser if routine files ever need lists or nesting in their frontmatter.
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if sep:
            out[key.strip()] = value.strip().strip("\"'")
    return out


def parse_time(text):
    try:
        t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.astimezone().replace(tzinfo=None) if t.tzinfo else t


def elapsed_hours(start, end, weekdays_only):
    if not weekdays_only:
        return (end - start).total_seconds() / 3600
    hours, cur = 0.0, start
    while cur < end:
        midnight = (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        nxt = min(end, midnight)
        if cur.weekday() < 5:
            hours += (nxt - cur).total_seconds() / 3600
        cur = nxt
    return hours


def is_true(meta, key):
    return meta.get(key, "").lower() == "true"


def check(folder, now):
    meta = frontmatter(folder / "ROUTINE.md")
    row = {"name": meta.get("name", folder.name), "status": "-", "last": "", "flag": "", "summary": ""}
    if is_true(meta, "paused"):
        row["status"] = "paused"
        return row
    records = sorted((folder / "runs").glob("*.md"))
    if not records:
        row["flag"] = "NEVER RUN"
        return row

    latest = records[-1]
    rec = frontmatter(latest)
    started = parse_time(rec.get("started", "")) or datetime.fromtimestamp(latest.stat().st_mtime)
    status = rec.get("status", "unknown")
    row.update(status=status, last=started.strftime("%Y-%m-%d %H:%M"), summary=rec.get("summary", ""))

    if status == "needs-you":
        row["flag"] = "NEEDS-YOU"
    elif status == "running":
        if now - started > timedelta(hours=STALL_HOURS):
            row["flag"] = "STALLED"
    elif status != "done":
        row["flag"] = "FAILED"  # includes records with a missing or unknown status
    else:
        try:
            cadence = float(meta.get("cadence_hours") or 0)
        except ValueError:
            cadence = 0
        grace = max(2, cadence * 0.25)
        if cadence and elapsed_hours(started, now, is_true(meta, "weekdays_only")) > cadence + grace:
            row["flag"] = "OVERDUE"
    return row


def report(home, now):
    root = Path(home).expanduser()
    if not root.is_dir():
        return []  # fresh install: nothing created yet
    folders = sorted(p for p in root.iterdir() if p.is_dir())
    return [
        check(p, now)
        for p in folders
        if not p.name.startswith(("_", ".")) and (p / "ROUTINE.md").is_file()
    ]


def notify(message):
    text = message.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(["osascript", "-e", f'display notification "{text}" with title "Routines"'], check=False)


def main(argv=None, now=None, notifier=notify):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--home", default=os.environ.get("ROUTINES_HOME", "~/.routines"))
    parser.add_argument("--notify", action="store_true", help="post a macOS notification if anything is flagged")
    args = parser.parse_args(argv)

    rows = report(args.home, now or datetime.now())
    columns = [("ROUTINE", "name"), ("STATUS", "status"), ("LAST RUN", "last"), ("FLAG", "flag"), ("SUMMARY", "summary")]
    widths = [max(len(title), *(len(r[key]) for r in rows)) if rows else len(title) for title, key in columns]
    for cells in [[title for title, _ in columns]] + [[r[key] for _, key in columns] for r in rows]:
        print("  ".join(cell.ljust(width) for cell, width in zip(cells, widths)).rstrip())

    flagged = [r for r in rows if r["flag"]]
    if flagged and args.notify:
        notifier(", ".join(f"{r['name']}: {r['flag']}" for r in flagged))
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
