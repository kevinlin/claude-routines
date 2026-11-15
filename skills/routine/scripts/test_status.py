import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import status

NOW = datetime(2026, 11, 18, 9, 30)  # a Wednesday


def make(home, name, meta="", runs=()):
    """Create a routine folder; runs = [(filename, status, started_iso)]."""
    folder = Path(home) / name
    (folder / "runs").mkdir(parents=True)
    (folder / "ROUTINE.md").write_text(f"---\nname: {name}\n{meta}\n---\n\n## Goal\n")
    for filename, run_status, started in runs:
        (folder / "runs" / filename).write_text(
            f"---\nstatus: {run_status}\nstarted: {started}\nsummary: did things\n---\n"
        )
    return folder


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def flag(self, name):
        return {r["name"]: r["flag"] for r in status.report(self.home, NOW)}[name]

    def test_never_run(self):
        make(self.home, "a")
        self.assertEqual(self.flag("a"), "NEVER RUN")

    def test_fresh_done_is_clean(self):
        make(self.home, "a", "cadence_hours: 24", [("2026-11-18-0830.md", "done", "2026-11-18T08:30:00")])
        self.assertEqual(self.flag("a"), "")

    def test_failed(self):
        make(self.home, "a", runs=[("2026-11-18-0830.md", "failed", "2026-11-18T08:30:00")])
        self.assertEqual(self.flag("a"), "FAILED")

    def test_unreadable_status_counts_as_failed(self):
        make(self.home, "a", runs=[("2026-11-18-0830.md", "finished-ish", "2026-11-18T08:30:00")])
        self.assertEqual(self.flag("a"), "FAILED")

    def test_needs_you(self):
        make(self.home, "a", runs=[("2026-11-17-1600.md", "needs-you", "2026-11-17T16:00:00")])
        self.assertEqual(self.flag("a"), "NEEDS-YOU")

    def test_running_recently_is_clean(self):
        make(self.home, "a", runs=[("2026-11-18-0900.md", "running", "2026-11-18T09:00:00")])
        self.assertEqual(self.flag("a"), "")

    def test_running_too_long_is_stalled(self):
        make(self.home, "a", runs=[("2026-11-18-0600.md", "running", "2026-11-18T06:00:00")])
        self.assertEqual(self.flag("a"), "STALLED")

    def test_overdue(self):
        make(self.home, "a", "cadence_hours: 24", [("2026-11-16-0830.md", "done", "2026-11-16T08:30:00")])
        self.assertEqual(self.flag("a"), "OVERDUE")

    def test_latest_record_wins(self):
        make(self.home, "a", "cadence_hours: 24", [
            ("2026-11-17-0830.md", "failed", "2026-11-17T08:30:00"),
            ("2026-11-18-0830.md", "done", "2026-11-18T08:30:00"),
        ])
        self.assertEqual(self.flag("a"), "")

    def test_weekdays_only_skips_the_weekend(self):
        monday = datetime(2026, 11, 16, 9, 30)
        friday_run = [("2026-11-13-0830.md", "done", "2026-11-13T08:30:00")]
        make(self.home, "wd", "cadence_hours: 24\nweekdays_only: true", friday_run)
        make(self.home, "all", "cadence_hours: 24", friday_run)
        flags = {r["name"]: r["flag"] for r in status.report(self.home, monday)}
        self.assertEqual(flags, {"wd": "", "all": "OVERDUE"})

    def test_paused_routine_is_never_flagged(self):
        make(self.home, "a", "paused: true")
        self.assertEqual(self.flag("a"), "")

    def test_timezone_aware_start_is_understood(self):
        make(self.home, "a", runs=[("2026-11-18-0600.md", "running", "2026-11-18T06:00:00+00:00")])
        self.assertIn(self.flag("a"), ("", "STALLED"))  # parsed, not crashed; value depends on local zone

    def test_kit_and_plain_folders_are_ignored(self):
        make(self.home, "_kit")
        (Path(self.home) / "docs").mkdir()
        self.assertEqual(status.report(self.home, NOW), [])

    def test_missing_home_is_an_empty_report(self):
        missing = str(Path(self.home) / "does-not-exist")
        self.assertEqual(status.report(missing, NOW), [])
        self.assertEqual(status.main(["--home", missing], NOW), 0)

    def test_exit_code_and_notify_only_for_flagged(self):
        make(self.home, "good", runs=[("2026-11-18-0830.md", "done", "2026-11-18T08:30:00")])
        sent = []
        self.assertEqual(status.main(["--home", self.home, "--notify"], NOW, sent.append), 0)
        self.assertEqual(sent, [])

        make(self.home, "bad", runs=[("2026-11-18-0830.md", "failed", "2026-11-18T08:30:00")])
        self.assertEqual(status.main(["--home", self.home, "--notify"], NOW, sent.append), 1)
        self.assertEqual(len(sent), 1)
        self.assertIn("bad", sent[0])
        self.assertNotIn("good", sent[0])

    def test_no_notify_without_the_flag(self):
        make(self.home, "bad", runs=[("2026-11-18-0830.md", "failed", "2026-11-18T08:30:00")])
        sent = []
        status.main(["--home", self.home], NOW, sent.append)
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
