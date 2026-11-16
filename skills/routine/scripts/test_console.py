import ast
import contextlib
import hashlib
import html
import http.client
import io
import os
import re
import secrets
import signal
import socket
import stat
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock
from urllib.parse import quote, urlencode

import console
import status
from test_status import NOW, make

FORM = "application/x-www-form-urlencoded"
POLICY = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'"
PAUSE_SENTENCE = "Pausing here does not pause the task in Claude Desktop."
ASK_SENTENCE = "Answer this in the Claude session, not here."
HOSTILE = "<script>alert(1)</script>"
BREAKOUT = '"><img src=x onerror=alert(1)>'
ATTRIBUTE = 'x" autofocus onfocus="alert(1)'  # no angle brackets: only quote escaping stops this one

OLD = {
    "purpose": "Weekly review",
    "schedule": "Fridays 16:00",
    "cadence_hours": "168",
    "weekdays_only": "false",
    "paused": "false",
    "runs_on": "desktop-local",
}
NEW = {
    "purpose": "Daily review: now",
    "schedule": "Mondays 09:00",
    "cadence_hours": "24",
    "weekdays_only": "true",
    "paused": "true",
    "runs_on": "cloud",
}
RAW = (
    "---\n"
    "name: alpha\n"
    "# keep this comment\n"
    "owner: kevin\n"
    + "".join(f"{key}: {value}\n" for key, value in OLD.items())
    + "---\n"
    "\n## Goal\nKeep it short.\n"
).encode()


def routine_file(home, name, raw):
    """A routine folder whose ROUTINE.md holds exactly these bytes."""
    folder = Path(home) / name
    (folder / "runs").mkdir(parents=True, exist_ok=True)
    path = folder / "ROUTINE.md"
    path.write_bytes(raw)
    return path


def sha_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def runs_named(count, status_word="done"):
    return [
        (f"2026-11-{day:02d}-0830.md", status_word, f"2026-11-{day:02d}T08:30:00")
        for day in range(1, count + 1)
    ]


class TempHome(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.outside = Path(tmp.name) / "outside"  # a sibling of the home: nothing here may ever change
        self.outside.mkdir()
        self.home = Path(tmp.name) / "home"
        self.home.mkdir()

    def page(self, token=None):
        return console.render(console.collect(self.home, NOW), NOW, token)


class StatusFoldersTest(TempHome):
    def test_folders_lists_what_report_lists_and_nothing_else(self):
        make(self.home, "b")
        make(self.home, "a")
        make(self.home, "_kit")
        make(self.home, ".hidden")
        (self.home / "docs").mkdir()
        (self.home / "loose.md").write_text("x")
        self.assertEqual([p.name for p in status.folders(self.home)], ["a", "b"])
        self.assertEqual([r["name"] for r in status.report(self.home, NOW)], ["a", "b"])

    def test_folders_of_a_missing_home_is_empty(self):
        self.assertEqual(status.folders(self.home / "nope"), [])

    def test_report_still_lists_the_same_routines_after_console_html_exists(self):
        make(self.home, "a")
        make(self.home, "b")
        before = status.report(self.home, NOW)
        console.write_static(self.home, NOW)
        self.assertTrue((self.home / "console.html").is_file())
        self.assertEqual(status.report(self.home, NOW), before)
        self.assertEqual([p.name for p in status.folders(self.home)], ["a", "b"])


class WriterTest(TempHome):
    def setUp(self):
        super().setUp()
        self.path = routine_file(self.home, "alpha", RAW)

    def write(self, changes, path=None):
        path = path or self.path
        console.set_fields(path, changes, sha_of(path))

    def expected(self, changes):
        text = RAW.decode()
        for key, value in changes.items():
            text = text.replace(f"{key}: {OLD[key]}\n", f"{key}: {value}\n")
        return text.encode()

    def test_each_field_changes_alone(self):
        for key, value in NEW.items():
            with self.subTest(key=key):
                self.path.write_bytes(RAW)
                self.write({key: value})
                self.assertEqual(self.path.read_bytes(), self.expected({key: value}))

    def test_all_fields_change_together(self):
        self.write(NEW)
        self.assertEqual(self.path.read_bytes(), self.expected(NEW))

    def test_unchanged_lines_comments_body_and_permission_bits_stay(self):
        os.chmod(self.path, 0o640)
        body = "\n## Goal\n---\nnaïve  \u2028 tail \x0b\r\nno newline at the end".encode()
        raw = RAW.split(b"---\n\n## Goal")[0] + b"---\n" + body
        self.path.write_bytes(raw)
        self.write({"paused": "true"})
        out = self.path.read_bytes()
        self.assertEqual(out, raw.replace(b"paused: false\n", b"paused: true\n"))
        self.assertTrue(out.endswith(body))
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)

    def test_each_lines_own_ending_is_kept(self):
        raw = b"---\r\nname: c\r\npurpose: old\nschedule: s\r\npaused: false\r\n---\r\nbody\r\n"
        self.path.write_bytes(raw)
        self.write({"purpose": "new", "schedule": "t", "paused": "true"})
        self.assertEqual(
            self.path.read_bytes(),
            b"---\r\nname: c\r\npurpose: new\nschedule: t\r\npaused: true\r\n---\r\nbody\r\n",
        )

    def test_a_missing_key_lands_directly_before_the_closing_marker(self):
        self.path.write_bytes(b"---\nname: m\npurpose: p\n---\nbody\n")
        self.write({"runs_on": "cloud", "paused": "true"})
        self.assertEqual(
            self.path.read_bytes(),
            b"---\nname: m\npurpose: p\npaused: true\nruns_on: cloud\n---\nbody\n",
        )

    def test_a_missing_key_takes_the_files_line_ending(self):
        self.path.write_bytes(b"---\r\nname: m\r\n---\r\nbody\r\n")
        self.write({"paused": "true"})
        self.assertEqual(self.path.read_bytes(), b"---\r\nname: m\r\npaused: true\r\n---\r\nbody\r\n")

    def test_a_missing_key_with_the_closing_marker_on_the_last_line(self):
        self.path.write_bytes(b"---\nname: m\n---")
        self.write({"paused": "true"})
        self.assertEqual(self.path.read_bytes(), b"---\nname: m\npaused: true\n---")

    def test_a_written_value_reads_back_equal_through_status_frontmatter(self):
        tricky = {
            "purpose": 'say "hi": a # b',
            "schedule": "x:y:z",
            "cadence_hours": "1e2",
            "weekdays_only": "true",
            "paused": "false",
            "runs_on": "cloud",
        }
        self.write(tricky)
        meta = status.frontmatter(self.path)
        for key, value in tricky.items():
            self.assertEqual(meta[key], value, key)
        self.assertEqual(meta["owner"], "kevin")
        self.assertEqual(meta["name"], "alpha")

    def test_no_change_is_the_identity(self):
        self.assertEqual(console.rewrite(RAW, {}), RAW)

    def test_writing_the_same_bytes_does_not_replace_the_file(self):
        before = self.path.stat().st_ino
        self.write({"paused": "false"})
        self.assertEqual(self.path.stat().st_ino, before)
        self.assertEqual(self.path.read_bytes(), RAW)

    def test_the_writer_refuses_a_bad_value_itself(self):
        for changes in ({"purpose": "a\nb"}, {"cadence_hours": "nan"}, {"name": "x"}):
            with self.subTest(changes=changes):
                with self.assertRaises(console.Refused) as caught:
                    self.write(changes)
                self.assertEqual(caught.exception.code, 400)
                self.assertEqual(self.path.read_bytes(), RAW)

    def test_a_change_made_while_saving_is_not_overwritten(self):
        outside = RAW.replace(b"Keep it short.", b"Edited elsewhere.")
        real = console.rewrite

        def rewrite_then_edit(raw, changes):
            built = real(raw, changes)
            self.path.write_bytes(outside)  # lands after the sha check, before the replace
            return built

        with mock.patch.object(console, "rewrite", rewrite_then_edit):
            with self.assertRaises(console.Refused) as caught:
                self.write({"paused": "true"})
        self.assertEqual(caught.exception.code, 409)
        self.assertEqual(self.path.read_bytes(), outside)

    def test_no_temp_file_is_left_behind(self):
        self.write({"paused": "true"})
        with self.assertRaises(console.Refused):
            console.set_fields(self.path, {"paused": "false"}, "0" * 64)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ["ROUTINE.md", "runs"])


class PageTest(TempHome):
    def test_hostile_text_is_escaped_everywhere(self):
        for payload in (HOSTILE, BREAKOUT, ATTRIBUTE):
            with self.subTest(payload=payload):
                raw = f"---\nname: {payload}\npurpose: {payload}\nowner: {payload}\n---\n\n{payload}\n".encode()
                path = routine_file(self.home, "evil", raw)
                (path.parent / "notes.md").write_text(f"- {payload}\n")
                (path.parent / "runs" / "2026-11-17-1600.md").write_text(
                    f"---\nstatus: needs-you\nstarted: 2026-11-17T16:00:00\nsummary: {payload}\nx: {payload}\n---\n\n{payload}\n"
                )
                for page in (self.page(), self.page("tok")):
                    self.assertNotIn("<script", page.lower())
                    self.assertNotIn("<img", page.lower())
                    self.assertNotIn('onerror=alert(1)>', page)
                    self.assertNotIn('" autofocus', page)
                    self.assertIn(html.escape(payload.strip('"')), page)  # frontmatter readers drop edge quotes

    def test_a_folder_name_cannot_break_out_of_the_form_action(self):
        folder = 'q"u&o<t>e'
        make(self.home, folder)
        page = self.page("tok")
        self.assertIn(f"/routine/{quote(folder, safe='')}?t=tok", page)
        self.assertNotIn(folder, page)

    def test_no_javascript_and_the_policy_is_in_the_file(self):
        make(self.home, "a")
        for page in (self.page(), self.page("tok")):
            self.assertNotIn("<script", page.lower())
            self.assertIsNone(re.search(r"\son\w+\s*=", page))
            self.assertIn(f'<meta http-equiv="Content-Security-Policy" content="{POLICY}">', page)

    def test_the_snapshot_has_no_form_and_the_served_page_has_one_per_editable_routine(self):
        make(self.home, "a")
        make(self.home, "b")
        target = self.outside / "real.md"
        target.write_bytes(RAW)
        (self.home / "linked").mkdir()
        (self.home / "linked" / "ROUTINE.md").symlink_to(target)
        self.assertNotIn("<form", self.page())
        live = self.page("tok")
        self.assertEqual(live.count("<form"), 2)
        self.assertIn('action="/routine/a?t=tok"', live)
        self.assertIn('action="/routine/b?t=tok"', live)
        self.assertNotIn("/routine/linked", live)
        self.assertIn("symlink", live)

    def test_the_file_written_to_disk_has_no_form(self):
        make(self.home, "a")
        path = console.write_static(self.home, NOW)
        self.assertEqual(path, self.home / "console.html")
        self.assertNotIn("<form", path.read_text())

    def test_every_input_has_a_label_and_headers_have_scope(self):
        make(self.home, "a", "purpose: p\nschedule: s\ncadence_hours: 24\nweekdays_only: true\npaused: false\nruns_on: cloud")
        make(self.home, "b")
        page = self.page("tok")
        ids = re.findall(r'<(?:input|select)\b(?![^>]*type="hidden")[^>]*\bid="([^"]+)"', page)
        self.assertEqual(len(ids), 12)
        for ident in ids:
            self.assertIn(f'<label for="{ident}">', page)
        self.assertEqual(len(re.findall(r'<th scope="col">', page)), 5)

    def test_flagged_routines_come_first_with_their_text_label(self):
        make(self.home, "aaa-clean", runs=[("2026-11-18-0830.md", "done", "2026-11-18T08:30:00")])
        make(self.home, "bbb-failed", runs=[("2026-11-18-0830.md", "failed", "2026-11-18T08:30:00")])
        make(self.home, "ccc-never")
        make(self.home, "ddd-ask", runs=[("2026-11-18-0830.md", "needs-you", "2026-11-18T08:30:00")])
        make(self.home, "eee-stalled", runs=[("2026-11-18-0100.md", "running", "2026-11-18T01:00:00")])
        make(self.home, "fff-overdue", "cadence_hours: 24", [("2026-11-15-0830.md", "done", "2026-11-15T08:30:00")])
        table = self.page().split("<h2>Routines</h2>")[0]
        order = [name for name in re.findall(r'<a href="#r-\d+">([^<]+)</a>', table)]
        self.assertEqual(
            order,
            ["bbb-failed", "ccc-never", "ddd-ask", "eee-stalled", "fff-overdue", "aaa-clean"],
        )
        for label in ("NEEDS-YOU", "STALLED", "FAILED", "OVERDUE", "NEVER RUN"):
            self.assertIn(f">{label}</span>", table)

    def test_the_table_columns_and_values(self):
        make(self.home, "a", runs=[("2026-11-18-0830.md", "done", "2026-11-18T08:30:00")])
        table = self.page().split("<h2>Routines</h2>")[0]
        for head in ("Routine", "Status", "Last run", "Flag", "Summary"):
            self.assertIn(f'<th scope="col">{head}</th>', table)
        for cell in ("done", "2026-11-18 08:30", "did things"):
            self.assertIn(f"<td>{cell}</td>", table)

    def test_only_the_newest_five_run_records_are_shown_newest_first(self):
        folder = make(self.home, "a", runs=runs_named(7))
        for number in range(1, 8):
            record = folder / "runs" / f"2026-11-{number:02d}-0830.md"
            record.write_text(record.read_text() + f"\nmarker-{number}\n")
        page = self.page()
        for number in (3, 4, 5, 6, 7):
            self.assertIn(f"marker-{number}\n", page)
        for number in (1, 2):
            self.assertNotIn(f"marker-{number}\n", page)
        self.assertLess(page.index("marker-7"), page.index("marker-6"))
        self.assertLess(page.index("marker-4"), page.index("marker-3"))

    def test_run_frontmatter_and_body_are_both_shown(self):
        folder = make(self.home, "a", runs=[("2026-11-18-0830.md", "done", "2026-11-18T08:30:00")])
        (folder / "runs" / "2026-11-18-0830.md").write_text(
            "---\nstatus: done\nstarted: 2026-11-18T08:30:00\nsummary: s\n---\n\n## Done\n- thing\n"
        )
        page = self.page()
        self.assertIn("started: 2026-11-18T08:30:00", page)
        self.assertIn("## Done\n- thing", page)

    def test_config_notes_body_path_and_time_are_shown(self):
        path = routine_file(self.home, "alpha", RAW)
        (path.parent / "notes.md").write_text("- prefer short summaries\n")
        page = self.page()
        for key, value in OLD.items():
            self.assertIn(f"<dt>{key}</dt>", page)
            self.assertIn(value, page)
        self.assertIn("## Goal\nKeep it short.", page)
        self.assertNotIn("keep this comment", page)  # frontmatter is not repeated in the body
        self.assertIn("- prefer short summaries", page)
        self.assertIn(os.path.abspath(path), page)
        self.assertIn("2026-11-18 09:30:00", page)

    def test_both_names_are_shown_when_display_name_and_folder_differ(self):
        routine_file(self.home, "folder-x", b"---\nname: Shown Name\n---\n")
        routine_file(self.home, "same", b"---\nname: same\n---\n")
        page = self.page()
        self.assertIn("Shown Name", page)
        self.assertIn("folder: folder-x", page)
        self.assertNotIn("folder: same", page)

    def test_the_pause_sentence_is_next_to_paused_in_both_pages(self):
        make(self.home, "a", "paused: false")
        for page in (self.page(), self.page("tok")):
            self.assertEqual(page.count(PAUSE_SENTENCE), 1)
            self.assertLess(page.index(">paused<"), page.index(PAUSE_SENTENCE))
            self.assertLess(page.index(PAUSE_SENTENCE) - page.index(">paused<"), 400)

    def test_the_ask_sentence_only_shows_for_a_latest_needs_you_record(self):
        make(self.home, "asks", runs=[("2026-11-17-1600.md", "done", "2026-11-17T16:00:00"),
                                      ("2026-11-18-0830.md", "needs-you", "2026-11-18T08:30:00")])
        make(self.home, "answered", runs=[("2026-11-17-1600.md", "needs-you", "2026-11-17T16:00:00"),
                                          ("2026-11-18-0830.md", "done", "2026-11-18T08:30:00")])
        for page in (self.page(), self.page("tok")):
            self.assertEqual(page.count(ASK_SENTENCE), 1)
        make(self.home, "paused-asks", "paused: true", [("2026-11-18-0830.md", "needs-you", "2026-11-18T08:30:00")])
        self.assertEqual(self.page().count(ASK_SENTENCE), 2)  # the record decides, even when the routine is paused

    def test_an_empty_home_still_renders(self):
        page = self.page("tok")
        self.assertIn("<table", page)
        self.assertNotIn("<form", page)

    def test_the_stylesheet_follows_the_design_tokens(self):
        make(self.home, "a")
        page = self.page()
        self.assertEqual(page.count("<style>"), 1)
        for token in ("color-scheme: light dark", "light-dark(", "--st-needs", "--st-stalled", "--st-overdue",
                      "--st-failed", "--st-never", "#0e7490", ":focus-visible"):
            self.assertIn(token, page)
        self.assertNotIn("http://", page.split("</style>")[0].split("<style>")[1])
        self.assertNotIn("https://", page)


class LiveServer(TempHome):
    """A real server on a free port, in a thread, over a temp home."""

    def setUp(self):
        super().setUp()
        self.server, self.token = self.start()
        self.port = self.server.server_address[1]

    def start(self):
        token = secrets.token_urlsafe(32)
        server = console.make_server(self.home, token, 0, clock=lambda: NOW)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        self.addCleanup(self.stop, server, thread)
        return server, token

    @staticmethod
    def stop(server, thread):
        server.shutdown()
        server.server_close()
        thread.join()

    def request(self, method, target, body=b"", headers=None, host=None, server=None):
        port = (server or self.server).server_address[1]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.putrequest(method, target, skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", host if host is not None else f"127.0.0.1:{port}")
            for name, value in (headers or {}).items():
                conn.putheader(name, value)
            conn.endheaders(body)
            response = conn.getresponse()
            data = response.read()
            return response.status, response, data
        finally:
            conn.close()

    def get(self, target=None, **kw):
        return self.request("GET", target if target is not None else f"/?t={self.token}", **kw)

    def post(self, target, body, headers=None, **kw):
        if isinstance(body, dict):
            body = urlencode(body).encode()
        if headers is None:
            headers = {"Content-Type": FORM, "Content-Length": str(len(body))}
        return self.request("POST", target, body, headers, **kw)

    def at(self, name):
        return f"/routine/{quote(name, safe='')}?t={self.token}"


class ServerTest(LiveServer):
    def test_it_binds_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_the_request_timeout_is_ten_seconds(self):
        self.assertIs(self.server.RequestHandlerClass, console.Handler)
        self.assertEqual(console.Handler.timeout, 10)

    def test_get_the_page_and_nothing_else(self):
        make(self.home, "alpha")
        code, response, body = self.get()
        self.assertEqual(code, 200)
        self.assertIn("text/html", response.getheader("Content-Type"))
        self.assertIn("<form", body.decode())
        for target in (f"/other?t={self.token}", f"/index.html?t={self.token}", f"/routine/alpha?t={self.token}"):
            self.assertEqual(self.get(target)[0], 404, target)
        self.assertEqual(self.get(f"/?t={self.token}&x=1")[0], 200)
        self.assertEqual(self.get(f"/?x=1&t={self.token}")[0], 200)

    def test_every_response_carries_the_three_headers(self):
        make(self.home, "alpha")
        results = [
            self.get(),
            self.get("/?t=wrong"),
            self.get(f"/nope?t={self.token}"),
            self.post(self.at("alpha"), {"sha": sha_of(self.home / "alpha" / "ROUTINE.md"), "paused": "true"}),
            self.post(self.at("alpha"), {"sha": "x", "paused": "maybe"}),
            self.post(self.at("nope"), {"sha": "x"}),
            self.request("PUT", f"/?t={self.token}"),
        ]
        self.assertEqual([r[0] for r in results], [200, 403, 404, 303, 400, 404, 501])
        for code, response, _ in results:
            with self.subTest(code=code):
                self.assertEqual(response.getheader("Content-Security-Policy"), POLICY)
                self.assertEqual(response.getheader("Referrer-Policy"), "no-referrer")
                self.assertEqual(response.getheader("Cache-Control"), "no-store")

    def test_the_served_page_is_the_live_state_not_a_cache(self):
        path = routine_file(self.home, "alpha", RAW)
        self.assertIn("Weekly review", self.get()[2].decode())
        path.write_bytes(RAW.replace(b"Weekly review", b"Changed by hand"))
        self.assertIn("Changed by hand", self.get()[2].decode())

    def test_the_form_in_the_served_page_posts_to_its_own_routine_with_the_current_sha(self):
        path = routine_file(self.home, "alpha", RAW)
        page = self.get()[2].decode()
        self.assertIn(f'action="/routine/alpha?t={self.token}"', page)
        self.assertIn(f'name="sha" value="{sha_of(path)}"', page)

    def test_a_successful_post_changes_the_field_and_nothing_else(self):
        path = routine_file(self.home, "alpha", RAW)
        code, response, _ = self.post(self.at("alpha"), {"sha": sha_of(path), "paused": " true "})
        self.assertEqual(code, 303)
        self.assertEqual(response.getheader("Location"), f"/?t={self.token}")
        self.assertEqual(path.read_bytes(), RAW.replace(b"paused: false\n", b"paused: true\n"))

    def test_a_successful_post_refreshes_console_html(self):
        path = routine_file(self.home, "alpha", RAW)
        self.assertFalse((self.home / "console.html").exists())
        self.post(self.at("alpha"), {"sha": sha_of(path), "purpose": "Brand new purpose"})
        snapshot = (self.home / "console.html").read_text()
        self.assertIn("Brand new purpose", snapshot)
        self.assertNotIn("<form", snapshot)
        self.assertIn("2026-11-18 09:30:00", snapshot)

    def test_a_successful_post_adds_a_missing_key(self):
        path = routine_file(self.home, "alpha", b"---\nname: alpha\npurpose: p\n---\nbody\n")
        code, _, _ = self.post(self.at("alpha"), {"sha": sha_of(path), "runs_on": "cloud"})
        self.assertEqual(code, 303)
        self.assertEqual(path.read_bytes(), b"---\nname: alpha\npurpose: p\nruns_on: cloud\n---\nbody\n")

    def test_the_last_value_of_a_repeated_field_wins_and_absent_fields_stay(self):
        path = routine_file(self.home, "alpha", RAW)
        body = f"sha={sha_of(path)}&purpose=first&paused=true&purpose=second".encode()
        self.assertEqual(self.post(self.at("alpha"), body)[0], 303)
        self.assertEqual(
            path.read_bytes(),
            RAW.replace(b"Weekly review", b"second").replace(b"paused: false\n", b"paused: true\n"),
        )

    def test_a_post_with_only_a_sha_changes_nothing(self):
        path = routine_file(self.home, "alpha", RAW)
        self.assertEqual(self.post(self.at("alpha"), {"sha": sha_of(path)})[0], 303)
        self.assertEqual(path.read_bytes(), RAW)

    def test_a_body_of_exactly_the_limit_is_accepted(self):
        path = routine_file(self.home, "alpha", RAW)
        head = f"sha={sha_of(path)}&purpose=".encode()
        body = head + b"a" * (16384 - len(head))
        self.assertEqual(len(body), 16384)
        self.assertEqual(self.post(self.at("alpha"), body)[0], 303)

    def test_percent_encoded_ids_round_trip(self):
        folder = 'q"u&o<t>e s'
        path = routine_file(self.home, folder, RAW)
        self.assertEqual(self.post(self.at(folder), {"sha": sha_of(path), "paused": "true"})[0], 303)
        self.assertIn(b"paused: true", path.read_bytes())

    def test_two_routines_with_one_display_name_and_one_renamed_are_told_apart_by_folder(self):
        purposes = {"first": "one", "second": "two", "third": "three"}
        names = {"first": "dup", "second": "dup", "third": "renamed"}
        paths = {
            folder: routine_file(self.home, folder, f"---\nname: {names[folder]}\npurpose: {purpose}\n---\n".encode())
            for folder, purpose in purposes.items()
        }
        for folder in paths:
            before = {name: path.read_bytes() for name, path in paths.items()}
            code, _, _ = self.post(self.at(folder), {"sha": sha_of(paths[folder]), "purpose": f"changed-{folder}"})
            self.assertEqual(code, 303)
            for other, path in paths.items():
                if other == folder:
                    want = before[other].replace(f"purpose: {purposes[other]}".encode(), f"purpose: changed-{folder}".encode())
                    self.assertNotEqual(want, before[other])
                else:
                    want = before[other]
                self.assertEqual(path.read_bytes(), want, f"posting to {folder}, checking {other}")

    def test_the_page_shows_both_names_for_the_renamed_routine(self):
        routine_file(self.home, "third", b"---\nname: renamed\n---\n")
        page = self.get()[2].decode()
        self.assertIn("renamed", page)
        self.assertIn("folder: third", page)


class CheckOrderTest(LiveServer):
    """One test per numbered check of the contract; each asserts the file is untouched."""

    def setUp(self):
        super().setUp()
        self.path = routine_file(self.home, "alpha", RAW)
        self.sha = sha_of(self.path)

    def body(self, **fields):
        return urlencode({"sha": self.sha, **fields}).encode()

    def refused(self, code, *, target=None, body=None, headers=None, host=None):
        target = target or self.at("alpha")
        body = self.body(paused="true") if body is None else body
        got, response, _ = self.post(target, body, headers=headers, host=host)
        self.assertEqual(got, code)
        self.assertEqual(self.path.read_bytes(), RAW)
        return response

    def test_check1_a_foreign_host_header_is_403(self):
        for host in ("evil.example", "evil.example:%d" % self.port, "127.0.0.1", "127.0.0.1:1", "localhost",
                     "localhost:%d" % (self.port + 1), "127.0.0.1:%d.evil.example" % self.port, ""):
            with self.subTest(host=host, method="POST"):
                self.refused(403, host=host)
            with self.subTest(host=host, method="GET"):
                self.assertEqual(self.get(host=host)[0], 403)
        self.assertEqual(self.get(host=f"localhost:{self.port}")[0], 200)

    def test_check1_a_missing_host_header_is_403(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest("GET", f"/?t={self.token}", skip_host=True, skip_accept_encoding=True)
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 403)
        conn.close()

    def test_check1_comes_before_the_token(self):
        self.refused(403, target=self.at("alpha").replace(self.token, "wrong"), host="evil.example")

    def test_check2_a_missing_or_wrong_token_is_403_on_get_and_post(self):
        other_server, other_token = self.start()
        for label, query in (("missing", ""), ("empty", "?t="), ("wrong", "?t=wrong"), ("prefix", f"?t={self.token[:-1]}"),
                             ("longer", f"?t={self.token}x"), ("other instance", f"?t={other_token}"),
                             ("other name", f"?token={self.token}"), ("upper", f"?t={self.token.upper()}")):
            with self.subTest(label=label, method="GET"):
                self.assertEqual(self.get(f"/{query}")[0], 403)
            with self.subTest(label=label, method="POST"):
                self.refused(403, target=f"/routine/alpha{query}")
        with self.subTest("instance token works on its own server"):
            self.assertEqual(self.get(f"/?t={other_token}", server=other_server)[0], 200)
            self.assertEqual(self.get(f"/?t={self.token}", server=other_server)[0], 403)

    def test_check2_a_non_ascii_token_is_403_not_a_crash(self):
        self.assertEqual(self.get("/?t=%C3%A9%FF")[0], 403)
        self.refused(403, target="/routine/alpha?t=%C3%A9%FF")

    def test_check2_comes_before_routing_and_the_body_checks(self):
        self.assertEqual(self.get("/nope?t=wrong")[0], 403)
        self.refused(403, target="/routine/nope?t=wrong", headers={"Content-Type": "text/plain"})

    def test_check3_a_content_type_that_is_not_form_encoded_is_415(self):
        body = self.body(paused="true")
        for content_type in ("application/json", "text/plain", "multipart/form-data; boundary=x", None):
            with self.subTest(content_type=content_type):
                headers = {"Content-Length": str(len(body))}
                if content_type:
                    headers["Content-Type"] = content_type
                self.refused(415, headers=headers)

    def test_check3_a_form_content_type_with_parameters_is_accepted(self):
        body = self.body(paused="true")
        headers = {"Content-Type": FORM.upper() + "; charset=UTF-8", "Content-Length": str(len(body))}
        self.assertEqual(self.post(self.at("alpha"), body, headers=headers)[0], 303)

    def test_check3_a_missing_or_non_numeric_content_length_is_411(self):
        for length in (None, "abc", "", "-1", "1.5", "0x10", "\xb2", "1 2"):
            with self.subTest(length=length):
                headers = {"Content-Type": FORM}
                if length is not None:
                    headers["Content-Length"] = length
                self.refused(411, body=b"", headers=headers)

    def test_check3_an_oversize_body_is_413_decided_from_the_header_alone(self):
        for length in ("16385", "99999999", "1" + "0" * 30):
            with self.subTest(length=length):
                self.refused(413, body=b"", headers={"Content-Type": FORM, "Content-Length": length})

    def test_a_body_shorter_than_its_content_length_is_400_and_writes_nothing(self):
        body = urlencode({"sha": self.sha, "purpose": "Truncated halfway through this sentence"}).encode()
        for short in (20, 1, len(body)):  # cut inside the value, one byte short, nothing sent at all
            with self.subTest(short=short):
                head = (f"POST /routine/alpha?t={self.token} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n"
                        f"Content-Type: {FORM}\r\nContent-Length: {len(body)}\r\n\r\n").encode()
                with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
                    sock.sendall(head + body[:len(body) - short])
                    sock.shutdown(socket.SHUT_WR)  # the client gives up: the server sees EOF before the declared length
                    reply = b""
                    while chunk := sock.recv(4096):
                        reply += chunk
                self.assertIn(b" 400 ", reply.split(b"\r\n", 1)[0])
                self.assertEqual(self.path.read_bytes(), RAW)
        self.assertEqual(self.post(self.at("alpha"), body)[0], 303)  # the same body, complete, is accepted
        self.assertIn(b"purpose: Truncated halfway through this sentence\n", self.path.read_bytes())

    def test_check3_comes_before_the_id_lookup(self):
        self.refused(415, target=self.at("nope"), headers={"Content-Type": "text/plain", "Content-Length": "0"})
        self.refused(411, target=self.at("nope"), body=b"", headers={"Content-Type": FORM})
        self.refused(413, target=self.at("nope"), body=b"", headers={"Content-Type": FORM, "Content-Length": "16385"})

    def test_check4_an_id_that_is_not_a_listed_folder_is_404(self):
        make(self.home, "_kit")
        (self.home / "docs").mkdir()
        (self.home / ".hidden").mkdir()
        (self.home / ".hidden" / "ROUTINE.md").write_bytes(RAW)
        sibling = routine_file(self.outside, "elsewhere", RAW)
        for target in (
            "/routine/nope", "/routine/", "/routine", "/routine/alpha/", "/routine/alpha/ROUTINE.md",
            "/routine/..", "/routine/../outside/elsewhere", "/routine/..%2Foutside%2Felsewhere",
            "/routine/..%2f..%2fetc", "/routine/%2e%2e", "/routine/_kit", "/routine/docs", "/routine/.hidden",
            "/routine/Alpha", "/routine/alpha%00", "/routine/alpha%20", "/routine/%2Fetc%2Fpasswd",
            "/", "/other", "/routine/alpha/../alpha",
        ):
            with self.subTest(target=target):
                self.refused(404, target=f"{target}?t={self.token}")
        self.assertEqual(sibling.read_bytes(), RAW)
        self.assertEqual((self.home / ".hidden" / "ROUTINE.md").read_bytes(), RAW)

    def test_check4_comes_before_the_field_checks(self):
        self.refused(404, target=self.at("nope"), body=b"bogus=1&paused=maybe")

    def test_check5_a_field_name_that_is_not_editable_is_400(self):
        for extra in ("name", "owner", "Purpose", "purpose ", "x", "", "t", "sha2"):
            with self.subTest(field=extra):
                self.refused(400, body=urlencode({"sha": self.sha, "paused": "true", extra: "v"}).encode())

    def test_check5_a_missing_sha_is_400(self):
        self.refused(400, body=urlencode({"paused": "true"}).encode())
        self.refused(400, body=b"")
        self.refused(400, body=urlencode({"SHA": self.sha, "paused": "true"}).encode())

    def test_check5_a_body_that_is_not_valid_text_is_400(self):
        self.refused(400, body=b"sha=" + self.sha.encode() + b"&purpose=%ff%fe")
        self.refused(400, body=b"sha=" + self.sha.encode() + b"&purpose=\xff")

    def test_check5_comes_before_the_value_checks(self):
        self.refused(400, body=urlencode({"paused": "maybe"}).encode())

    def test_check6_a_bad_value_is_400(self):
        separators = ["\n", "\r", "\r\n", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"]
        bad = {
            "purpose": [f"a{s}b" for s in separators] + [f"a{s}" for s in separators[:3]]
                       + ["\u2028", '"quoted', "'quoted", 'quoted"', "quoted'", '"', "'", '"both"', "ok'"],
            "schedule": ["a\u2028paused: true", "x\ny", "'", "x'"],
            "cadence_hours": ["inf", "-inf", "nan", "NaN", "Infinity", "0", "0.0", "-0", "-1", "-0.5", "abc", "",
                              "1e999", "24h", "1,5", "24\n", "'24'"],
            "weekdays_only": ["True", "TRUE", "yes", "1", "", "true\n", "maybe", "false false"],
            "paused": ["True", "FALSE", "no", "0", "", "ture"],
            "runs_on": ["local", "Cloud", "desktop", "desktop-local\n", "", "other"],
        }
        for key, values in bad.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    self.refused(400, body=self.body(**{key: value}))
        # one bad field spoils the whole request: the good one beside it is not written either
        self.refused(400, body=self.body(paused="true", purpose="a\u2028b"))

    def test_check6_values_are_stripped_of_surrounding_spaces(self):
        self.assertEqual(self.post(self.at("alpha"), self.body(paused="  true  ", cadence_hours=" 12 "))[0], 303)
        meta = status.frontmatter(self.path)
        self.assertEqual((meta["paused"], meta["cadence_hours"]), ("true", "12"))

    def test_check6_a_space_wrapped_quote_is_still_a_quote(self):
        self.refused(400, body=self.body(purpose=' "x" '))
        self.refused(400, body=self.body(purpose=" '"))

    def test_check6_values_that_look_odd_but_are_fine_are_written(self):
        ok = {"purpose": "a: b # c 'd' \"e\" f", "schedule": "", "cadence_hours": "1e2", "runs_on": "cloud"}
        self.assertEqual(self.post(self.at("alpha"), self.body(**ok))[0], 303)
        meta = status.frontmatter(self.path)
        for key, value in ok.items():
            self.assertEqual(meta[key], value)

    def test_check6_comes_before_the_file_checks(self):
        target = self.outside / "real.md"
        target.write_bytes(RAW)
        link = self.home / "alpha" / "ROUTINE.md"
        link.unlink()
        link.symlink_to(target)
        got, _, _ = self.post(self.at("alpha"), self.body(paused="maybe"))
        self.assertEqual(got, 400)
        self.assertEqual(target.read_bytes(), RAW)

    def unsafe(self, make_file):
        make_file(self.path)
        before = self.path.read_bytes()
        got, _, _ = self.post(self.at("alpha"), {"sha": hashlib.sha256(before).hexdigest(), "paused": "true"})
        self.assertEqual(got, 422)
        self.assertEqual(self.path.read_bytes(), before)

    def test_check7_a_symlinked_routine_md_is_422(self):
        target = self.outside / "real.md"
        target.write_bytes(RAW)

        def link(path):
            path.unlink()
            path.symlink_to(target)

        self.unsafe(link)
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(target.read_bytes(), RAW)
        self.assertEqual(os.readlink(self.path), str(target))

    def test_check4_a_routine_md_that_is_a_dangling_symlink_is_not_listed(self):
        self.path.unlink()
        self.path.symlink_to(self.outside / "gone.md")
        got, _, _ = self.post(self.at("alpha"), {"sha": "x", "paused": "true"})
        self.assertEqual(got, 404)

    def test_check7_a_missing_opening_marker_is_422(self):
        for raw in (b"name: alpha\npaused: false\n---\nbody\n", b"\n---\nname: a\npaused: false\n---\n",
                    b"# title\n---\npaused: false\n---\n", b"\xef\xbb\xbf---\npaused: false\n---\n", b""):
            with self.subTest(raw=raw):
                self.unsafe(lambda path, raw=raw: path.write_bytes(raw))

    def test_check7_a_missing_closing_marker_is_422(self):
        for raw in (b"---\nname: alpha\npaused: false\nbody\n", b"---\n", b"---\npaused: false\n--\n"):
            with self.subTest(raw=raw):
                self.unsafe(lambda path, raw=raw: path.write_bytes(raw))

    def test_check7_a_duplicated_key_is_422(self):
        for raw in (RAW.replace(b"paused: false\n", b"paused: false\npaused: true\n"),
                    RAW.replace(b"purpose: Weekly review\n", b"purpose: a\npurpose: b\n"),
                    RAW.replace(b"runs_on: desktop-local\n", b"runs_on: cloud\n  runs_on : cloud\n")):
            with self.subTest(raw=raw):
                self.unsafe(lambda path, raw=raw: path.write_bytes(raw))

    def test_check7_a_key_that_is_not_in_the_request_but_is_duplicated_still_blocks_the_edit(self):
        raw = RAW.replace(b"paused: false\n", b"paused: false\npaused: true\n")
        self.path.write_bytes(raw)
        got, _, _ = self.post(self.at("alpha"), {"sha": sha_of(self.path), "purpose": "x"})
        self.assertEqual(got, 422)
        self.assertEqual(self.path.read_bytes(), raw)

    def test_check7_a_file_that_is_not_utf8_is_422(self):
        self.unsafe(lambda path: path.write_bytes(RAW + b"\xff\xfe"))

    def test_check7_a_repeat_after_the_closing_marker_is_not_a_duplicate(self):
        raw = RAW + b"paused: in the body\n"
        self.path.write_bytes(raw)
        got, _, _ = self.post(self.at("alpha"), {"sha": sha_of(self.path), "paused": "true"})
        self.assertEqual(got, 303)
        self.assertEqual(self.path.read_bytes(), raw.replace(b"paused: false\n", b"paused: true\n", 1))

    def test_check7_comes_before_the_sha(self):
        self.path.write_bytes(b"no frontmatter here\n")
        before = self.path.read_bytes()
        got, _, _ = self.post(self.at("alpha"), {"sha": "0" * 64, "paused": "true"})
        self.assertEqual(got, 422)
        self.assertEqual(self.path.read_bytes(), before)

    def test_check8_a_sha_that_does_not_match_the_file_now_is_409(self):
        for sha in ("0" * 64, "", "abc", self.sha.upper(), self.sha + "0", "x\ny"):
            with self.subTest(sha=sha):
                self.refused(409, body=urlencode({"sha": sha, "paused": "true"}).encode())

    def test_check8_a_file_edited_since_the_page_was_read_is_409(self):
        self.path.write_bytes(RAW + b"added by hand\n")
        edited = self.path.read_bytes()
        got, _, _ = self.post(self.at("alpha"), self.body(paused="true"))  # self.sha is the old one
        self.assertEqual(got, 409)
        self.assertEqual(self.path.read_bytes(), edited)

    def test_check8_a_change_made_between_the_sha_check_and_the_replace_is_409(self):
        outside = RAW.replace(b"Keep it short.", b"Edited elsewhere.")
        real = console.rewrite

        def rewrite_then_edit(raw, changes):
            built = real(raw, changes)
            self.path.write_bytes(outside)
            return built

        with mock.patch.object(console, "rewrite", rewrite_then_edit):
            got, _, _ = self.post(self.at("alpha"), self.body(paused="true"))
        self.assertEqual(got, 409)
        self.assertEqual(self.path.read_bytes(), outside)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ["ROUTINE.md", "runs"])

    def test_the_documented_order_holds_when_several_checks_would_fail(self):
        # Each request fails two or more checks; the earlier number must win.
        self.refused(403, host="evil.example", target="/routine/nope?t=wrong",
                     headers={"Content-Type": "text/plain"})
        self.refused(415, target=self.at("nope"), body=b"bogus=1", headers={"Content-Type": "text/plain"})
        self.refused(404, target=self.at("nope"), body=b"bogus=1&paused=maybe")
        self.refused(400, body=urlencode({"sha": "0" * 64, "paused": "true", "bogus": "1"}).encode())
        self.refused(400, body=urlencode({"sha": "0" * 64, "paused": "maybe"}).encode())


class MainTest(TempHome):
    def run_main(self, *argv, **kw):
        kw.setdefault("opener", lambda url: None)  # a test must never open a browser
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = console.main(list(argv), now=NOW, **kw)
        return code, out.getvalue()

    def test_snapshot_mode_writes_prints_the_path_and_opens_the_file(self):
        make(self.home, "a")
        opened = []
        code, out = self.run_main("--home", str(self.home), opener=opened.append)
        self.assertEqual(code, 0)
        path = os.path.abspath(self.home / "console.html")
        self.assertEqual(out, path + "\n")
        self.assertTrue(os.path.isabs(out.strip()))
        self.assertEqual(opened, [Path(path).as_uri()])
        self.assertIn("<table", Path(path).read_text())
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode) & 0o077, 0)  # private: it holds notes

    def test_no_open_opens_nothing(self):
        make(self.home, "a")
        opened = []
        self.assertEqual(self.run_main("--home", str(self.home), "--no-open", opener=opened.append)[0], 0)
        self.assertEqual(opened, [])

    def test_home_defaults_to_the_environment_variable(self):
        make(self.home, "a")
        with mock.patch.dict(os.environ, {"ROUTINES_HOME": str(self.home)}):
            code, out = self.run_main("--no-open")
        self.assertEqual(out.strip(), os.path.abspath(self.home / "console.html"))

    def test_a_missing_home_prints_one_line_creates_nothing_and_exits_0(self):
        missing = self.home / "does-not-exist"
        for extra in ([], ["--serve"]):
            opened = []
            code, out = self.run_main("--home", str(missing), *extra, opener=opened.append)
            self.assertEqual(code, 0)
            self.assertEqual(len(out.strip().splitlines()), 1)
            self.assertIn(str(missing), out)
            self.assertFalse(missing.exists())
            self.assertEqual(opened, [])
        self.assertEqual(os.listdir(self.home), [])

    def test_console_html_is_replaced_not_written_through_a_symlink(self):
        make(self.home, "a")
        target = self.outside / "precious.txt"
        target.write_text("keep")
        (self.home / "console.html").symlink_to(target)
        self.run_main("--home", str(self.home), "--no-open")
        self.assertEqual(target.read_text(), "keep")
        self.assertFalse((self.home / "console.html").is_symlink())

    def test_serve_prints_the_url_serves_it_and_exits_0_when_idle(self):
        make(self.home, "alpha")
        fetched, threads = [], []

        def opener(url):
            def fetch():
                try:
                    fetched.append(urllib.request.urlopen(url, timeout=5).read().decode())
                except Exception as error:  # reported by the assertion below
                    fetched.append(error)
            thread = threading.Thread(target=fetch)
            thread.start()
            threads.append(thread)

        started = time.monotonic()
        code, out = self.run_main("--serve", "--home", str(self.home), "--idle-seconds", "0.5", opener=opener)
        for thread in threads:
            thread.join()
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], os.path.abspath(self.home / "console.html"))
        self.assertRegex(lines[1], r"^http://127\.0\.0\.1:\d+/\?t=[A-Za-z0-9_-]{43}$")
        self.assertEqual(len(fetched), 1)
        self.assertIn("<form", fetched[0])
        self.assertIn("alpha", fetched[0])
        self.assertLess(time.monotonic() - started, 5)

    def test_serve_opens_the_url_unless_no_open(self):
        make(self.home, "a")
        opened = []
        code, out = self.run_main("--serve", "--home", str(self.home), "--idle-seconds", "0.1", opener=opened.append)
        self.assertEqual(opened, [out.splitlines()[1]])
        opened.clear()
        self.run_main("--serve", "--home", str(self.home), "--idle-seconds", "0.1", "--no-open", opener=opened.append)
        self.assertEqual(opened, [])

    def test_each_serve_run_gets_its_own_token(self):
        make(self.home, "a")
        urls = {self.run_main("--serve", "--home", str(self.home), "--no-open", "--idle-seconds", "0.05")[1]
                for _ in range(3)}
        self.assertEqual(len(urls), 3)

    def test_the_idle_exit_comes_after_the_given_seconds_without_a_request(self):
        make(self.home, "a")
        started = time.monotonic()
        code, _ = self.run_main("--serve", "--home", str(self.home), "--no-open", "--idle-seconds", "0.4")
        elapsed = time.monotonic() - started
        self.assertEqual(code, 0)
        self.assertGreaterEqual(elapsed, 0.35)
        self.assertLess(elapsed, 3)

    def test_a_request_restarts_the_idle_clock(self):
        make(self.home, "a")
        threads = []

        def opener(url):
            def fetch():
                time.sleep(0.5)
                urllib.request.urlopen(url, timeout=5).read()
            thread = threading.Thread(target=fetch)
            thread.start()
            threads.append(thread)

        started = time.monotonic()
        self.run_main("--serve", "--home", str(self.home), "--idle-seconds", "0.8", opener=opener)
        self.assertGreaterEqual(time.monotonic() - started, 1.25)  # 0.5 s to the request, then a full 0.8 s
        for thread in threads:
            thread.join()

    def test_ctrl_c_exits_0(self):
        make(self.home, "a")
        timer = threading.Timer(0.3, os.kill, (os.getpid(), signal.SIGINT))
        timer.start()
        try:
            code, _ = self.run_main("--serve", "--home", str(self.home), "--no-open", "--idle-seconds", "30")
        finally:
            timer.cancel()
        self.assertEqual(code, 0)

    def test_the_port_can_be_chosen(self):
        make(self.home, "a")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        code, out = self.run_main("--serve", "--home", str(self.home), "--no-open", "--idle-seconds", "0.05",
                                  "--port", str(port))
        self.assertTrue(out.splitlines()[1].startswith(f"http://127.0.0.1:{port}/?t="))


class ImportsTest(unittest.TestCase):
    @unittest.skipUnless(hasattr(sys, "stdlib_module_names"), "needs Python 3.10+ for the stdlib list")
    def test_console_imports_only_the_standard_library_and_status(self):
        tree = ast.parse((Path(__file__).parent / "console.py").read_text())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add(node.module.split(".")[0])
        self.assertEqual(names - set(sys.stdlib_module_names), {"status"})

    def test_console_source_has_no_script_tag(self):
        source = (Path(__file__).parent / "console.py").read_text()
        self.assertNotIn("<script", source.lower())


if __name__ == "__main__":
    unittest.main()
