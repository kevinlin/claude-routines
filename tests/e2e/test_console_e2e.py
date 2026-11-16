"""Acceptance gate for skills/routine/scripts/console.py.

One test method per scenario in console.feature, named after the scenario ID
(@CON-07 -> test_con_07_...). Launch scaffolding lives in support.py.

Run from the repo root:  python3 -m unittest discover -s tests/e2e -v
"""
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import support as S

LINE_SEPARATORS = ["\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"]
HOSTILE_TEXT = [
    "XSS-NAME " + S.HOSTILE,
    'XSS-FM ' + S.HOSTILE + ' "><img src=x onerror=alert(1)> end',
    "XSS-SCHED &lt;b&gt;already-escaped &amp; done " + S.HOSTILE,
    "XSS-NOTES " + S.HOSTILE + " <img src=x onerror=alert(1)>",
    "XSS-SUMMARY " + S.HOSTILE,
    "XSS-RUNBODY " + S.HOSTILE,
    "XSS-BODY " + S.HOSTILE,
]
RESPONSE_HEADERS = {
    "content-security-policy": S.CSP,
    "referrer-policy": "no-referrer",
    "cache-control": "no-store",
}
_TIMESTAMP = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?\s?(Z|UTC|[+-]\d{2}:?\d{2})?")


def local_times(text):
    """Every date-time in the text as a naive local datetime (offsets and Z are converted)."""
    found = []
    for m in _TIMESTAMP.finditer(text):
        y, mo, d, h, mi, s, tz = m.groups()
        try:
            moment = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0))
        except ValueError:
            continue
        if tz:
            if tz in ("Z", "UTC"):
                offset = timedelta(0)
            else:
                digits = tz[1:].replace(":", "")
                offset = timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
                offset = -offset if tz[0] == "-" else offset
            moment = (moment - offset).replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        found.append(moment)
    return found


class ConsoleGate(S.ConsoleCase):
    # ----------------------------------------------------------------- checks
    def _pairs(self, home, page):
        """Pair every status.py row with a distinct row of the page's status table."""
        _, expected = self.run_status(home.path)
        rows = page.status_rows()
        remaining = list(rows)
        pairs = []
        for e in expected:
            hit = next((r for r in remaining if e["name"] in r["name"]
                        and r["status"] == e["status"] and r["flag"] == e["flag"]), None)
            self.assertIsNotNone(hit, "status.py row %r has no row in the page table %r" % (e, rows))
            remaining.remove(hit)
            pairs.append((e, hit))
        self.assertEqual(remaining, [], "the page lists routines status.py does not")
        return pairs

    def _section(self, page, home, rid):
        return page.section(str(home.md(rid)), "BODY-MARK-" + rid)

    def _scoped(self, home, rid, text):
        """True when the section really is this routine's own (holds no other body marker)."""
        return all("BODY-MARK-" + other not in text for other in home.ids if other != rid)

    def _check_table(self, home, page):
        pairs = self._pairs(home, page)
        flags = [bool(r["flag"]) for r in page.status_rows()]
        self.assertEqual(flags, sorted(flags, reverse=True), "flagged routines must come first")
        for e, row in pairs:
            if e["last"]:
                self.assertIn(e["last"][:10], row["last"], "last run of %s" % e["name"])
            if e["summary"]:
                self.assertIn(e["summary"], row["summary"], "summary of %s" % e["name"])

    def _check_fields(self, home, page, strict):
        for rid in home.ids:
            section = self._section(page, home, rid)
            text = section.corpus()
            front = home.front(rid)
            for key in S.FIELDS:
                self.assertIn(front[key], text, "%s: value of %s" % (rid, key))
            visible = S.norm(section.text())
            if strict and self._scoped(home, rid, visible):
                tokens = set(re.split(r"[^\w.-]+", visible))
                wants_true = front["weekdays_only"] == "true" or front["paused"] == "true"
                self.assertEqual("true" in tokens, wants_true, "%s: true/false values" % rid)
                self.assertIn(front["runs_on"], tokens)

    def _check_bodies(self, home, page):
        for rid in home.ids:
            text = S.norm(self._section(page, home, rid).corpus())
            self.assertIn("BODY-MARK-%s first line of the body" % rid, text)
            self.assertIn("BODY-STEP-%s second paragraph" % rid, text)

    def _check_notes(self, home, page):
        text = S.norm(self._section(page, home, "rich").corpus())
        self.assertIn("NOTES-MARK-rich keep it under ten lines", text)
        self.assertIn("NOTES-LATER-rich second note", text)
        for rid in home.ids:
            other = S.norm(self._section(page, home, rid).corpus())
            if rid != "rich" and self._scoped(home, rid, other):
                self.assertNotIn("NOTES-MARK-rich", other, "notes of rich shown under " + rid)

    def _check_records(self, home, page):
        records = list(reversed(home.specs["rich"]["records"]))  # newest first
        text = S.norm(self._section(page, home, "rich").corpus())
        positions = []
        for started, _status, summary, body in records[:5]:
            for needle in (body, summary, S.iso(started), S.iso(started + timedelta(minutes=5))):
                self.assertIn(needle, text, "newest five records must show %r" % needle)
            positions.append(text.index(body))
        self.assertEqual(positions, sorted(set(positions)), "records are not newest first")
        everything = page.corpus()
        for started, _status, summary, body in records[5:]:
            for needle in (body, summary, S.iso(started)):
                self.assertNotIn(needle, everything, "older record is on the page: %r" % needle)
        short = S.norm(self._section(page, home, "done-clean").corpus())
        self.assertIn("DONECLEAN-BODY", short)
        self.assertIn("DONECLEAN-OLD-BODY", short)
        self.assertLess(short.index("DONECLEAN-BODY"), short.index("DONECLEAN-OLD-BODY"))

    def _check_paths_and_time(self, home, page, started, finished):
        text = page.text()
        for rid in home.ids:
            self.assertIn(str(home.md(rid)), text, "ROUTINE.md path of " + rid)
        pad = timedelta(seconds=70)
        utc_offset = datetime.now(timezone.utc).replace(tzinfo=None) - datetime.now()
        shown = local_times(page.corpus())  # text and attributes, so <time datetime=...> counts
        self.assertTrue(
            any(started - pad <= t <= finished + pad or started - pad <= t - utc_offset <= finished + pad
                for t in shown),
            "no generation time near %s (local or UTC) in the page; date-times seen: %s" % (finished, shown[:6]))

    def _check_sentences(self, home, page):
        text = page.text()
        self.assertGreaterEqual(text.count(S.PAUSED_SENTENCE), len(home.ids))
        holders = [e for e in page.elements() if any(S.PAUSED_SENTENCE in t for t in e.own_texts())]
        self.assertTrue(holders, "the paused sentence must be one run of text")
        for e in holders:
            near = " ".join(S.norm(a.text()).lower() for a in e.ancestors()[:4])
            self.assertIn("paused", near, "the sentence is not next to the paused field")
        self.assertEqual(text.count(S.NEEDS_YOU_SENTENCE), 1)
        waiting = S.norm(self._section(page, home, "needs-you").text())
        self.assertIn(S.NEEDS_YOU_SENTENCE, waiting)
        for rid in home.ids:
            own = S.norm(self._section(page, home, rid).text())
            self.assertIn(S.PAUSED_SENTENCE, own, "paused sentence missing for " + rid)
            if rid != "needs-you" and self._scoped(home, rid, own):
                self.assertNotIn(S.NEEDS_YOU_SENTENCE, own, "needs-you sentence under " + rid)

    def _check_names_and_ids(self, home, page):
        text = page.text()
        cleaned = " ".join(w for w in text.split() if "/" not in w)
        for rid in ("folder-mismatch", "twin-a", "twin-b", "hostile"):
            self.assertIn(S.norm(home.display[rid]), text, "display name of " + rid)
            alone = r"(?<![\w/.-])%s(?![\w/.-])" % re.escape(rid)
            self.assertTrue(re.search(alone, cleaned), "id %s is not shown apart from paths" % rid)

    def _check_escaped(self, page, visible_only):
        low = page.html.lower()
        for raw in ("<script", "</script", "<img", "<iframe"):
            self.assertNotIn(raw, low, "unescaped %s in the page source" % raw)
        for tag in ("script", "img", "iframe"):
            self.assertNotIn(tag, page.start_tags)
        for e in page.elements():
            self.assertFalse([a for a in e.attrs if a.startswith("on")], "event handler on <%s>" % e.tag)
        shown = page.text() if visible_only else page.corpus()
        for needle in HOSTILE_TEXT:
            self.assertIn(needle, shown, "hostile text is not shown as plain text: %r" % needle)

    def _form_for(self, page, rid):
        for form in page.forms():
            if urlsplit(form.action).path == "/routine/" + rid:
                return form
        self.fail("no form posts to /routine/%s" % rid)

    def _ok(self, server, rid, fields, **kw):
        resp = server.post(rid, fields, **kw)
        self.assertEqual(resp.status, 303, resp)
        self.assertEqual(resp.header("location"), server.target)
        return resp

    def _headers_ok(self, resp, label):
        for name, value in RESPONSE_HEADERS.items():
            self.assertEqual(resp.header(name), value, "%s: %s on %s" % (label, name, resp.status))

    # --------------------------------------------------------------- snapshot
    def test_con_01_snapshot_is_written_where_promised_and_changes_nothing_else(self):
        home = self.make_home()
        before = home.tree()
        proc = self.run_console(home.path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        lines = proc.stdout.splitlines()
        self.assertEqual(len(lines), 1, "stdout must be one line: %r" % proc.stdout)
        self.assertTrue(os.path.isabs(lines[0]), lines[0])
        self.assertTrue(os.path.samefile(lines[0], str(home.snapshot)), lines[0])
        after = home.tree()
        self.assertEqual(set(after) - set(before), {os.path.relpath(str(home.snapshot), str(home.root))})
        for key, value in before.items():
            self.assertEqual(after[key], value, "console.py changed " + key)
        page = S.Page(home.snapshot.read_text(encoding="utf-8"))
        self.assertTrue(page.elements("table"))
        self.assertEqual(self.opened(), [], "--no-open must not launch a browser")

    def test_con_02_snapshot_lists_the_same_routines_statuses_and_flags_as_status_py(self):
        home = self.make_home()
        page = self.snapshot(home)
        pairs = self._pairs(home, page)
        self.assertEqual(len(pairs), len(home.ids))

    def test_con_03_each_flag_is_shown_as_its_text_label(self):
        home = self.make_home()
        _, built = self.run_status(home.path)
        self.assertEqual(sorted((r["name"], r["flag"]) for r in built),
                         sorted((home.display[i], home.flag[i]) for i in home.ids),
                         "fixture drifted from the flags it was built for")
        rows = self.snapshot(home).status_rows()
        for rid in home.ids:
            matches = [r for r in rows if home.display[rid] in r["name"] and r["flag"] == home.flag[rid]]
            self.assertTrue(matches, "%s should show flag %r; rows: %r" % (rid, home.flag[rid], rows))
        shown = sorted(r["flag"] for r in rows if r["flag"])
        self.assertEqual(shown, sorted(["NEVER RUN", "NEEDS-YOU", "STALLED", "FAILED", "OVERDUE"]))

    def test_con_04_flagged_routines_come_before_unflagged_ones(self):
        home = self.make_home()
        rows = self.snapshot(home).status_rows()
        flags = [bool(r["flag"]) for r in rows]
        self.assertEqual(sum(flags), 5)
        self.assertEqual(flags, sorted(flags, reverse=True), [(r["name"], r["flag"]) for r in rows])

    def test_con_05_each_row_shows_last_run_and_summary(self):
        home = self.make_home()
        pairs = self._pairs(home, self.snapshot(home))
        checked = 0
        for e, row in pairs:
            if e["last"]:
                self.assertIn(e["last"][:10], row["last"], e["name"])
                checked += 1
            if e["summary"]:
                self.assertIn(e["summary"], row["summary"], e["name"])
        self.assertGreaterEqual(checked, 8)

    def test_con_06_missing_home_creates_nothing_and_exits_zero(self):
        missing = self.sandbox / "no-such-home"
        before = sorted(os.listdir(str(self.sandbox)))
        proc = self.run_console(missing)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(len((proc.stdout + proc.stderr).splitlines()), 1,
                         "expected a one-line message: %r %r" % (proc.stdout, proc.stderr))
        self.assertFalse(missing.exists(), "a missing home must not be created")
        self.assertEqual(sorted(os.listdir(str(self.sandbox))), before)
        self.assertEqual(self.opened(), [])

    def test_con_07_status_py_lists_the_same_routines_after_console_html_exists(self):
        home = self.make_home()
        before, rows_before = self.run_status(home.path)
        self.snapshot(home)
        self.snapshot(home)  # the second run overwrites an existing console.html
        after, rows_after = self.run_status(home.path)
        self.assertTrue(home.snapshot.is_file())
        self.assertEqual(after, before)
        self.assertEqual(len(rows_after), len(home.ids))
        self.assertNotIn("console", after)

    def test_con_08_folders_that_are_not_routines_are_not_listed(self):
        home = self.make_home()
        page = self.snapshot(home)
        for marker in ("KIT-BODY-MARK", "HIDDEN-BODY-MARK", "DOCS-MARK", "STRAY-MARK", "_kit", ".hidden"):
            self.assertNotIn(marker, page.html)
        self.assertEqual(len(page.status_rows()), len(home.ids))

    def test_con_09_snapshot_opens_in_the_browser_unless_no_open(self):
        home = self.make_home()
        proc = self.run_console(home.path, no_open=False)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(
            self.wait_opened(str(home.snapshot)) or self.wait_opened(home.snapshot.as_uri()),
            "no browser launch for console.html; launches seen: %r" % self.opened())

    def test_con_10_routines_with_unsafe_frontmatter_are_still_listed(self):
        home = self.make_home(["symlinked", "no-close", "no-open", "dupe"])
        page = self.snapshot(home)
        self._pairs(home, page)
        text = page.text()
        for rid in ("symlinked", "no-close", "no-open", "dupe"):
            self.assertIn(str(home.md(rid)), text)

    # ---------------------------------------------------------------- content
    def test_con_11_each_routine_shows_its_six_field_values(self):
        home = self.make_home()
        self._check_fields(home, self.snapshot(home), strict=True)

    def test_con_12_each_routine_shows_its_routine_md_body(self):
        home = self.make_home()
        self._check_bodies(home, self.snapshot(home))

    def test_con_13_notes_are_shown(self):
        home = self.make_home()
        self._check_notes(home, self.snapshot(home))

    def test_con_14_newest_five_run_records_are_shown_newest_first(self):
        home = self.make_home()
        self._check_records(home, self.snapshot(home))

    def test_con_15_generation_time_and_routine_md_paths_are_shown(self):
        home = self.make_home()
        started = datetime.now()
        page = self.snapshot(home)
        self._check_paths_and_time(home, page, started, datetime.now())

    def test_con_16_paused_sentence_is_next_to_the_paused_field(self):
        home = self.make_home()
        page = self.snapshot(home)
        self.assertGreaterEqual(page.text().count(S.PAUSED_SENTENCE), len(home.ids))
        holders = [e for e in page.elements() if any(S.PAUSED_SENTENCE in t for t in e.own_texts())]
        self.assertTrue(holders, "the sentence must be one run of text, word for word")
        for e in holders:
            near = " ".join(S.norm(a.text()).lower() for a in e.ancestors()[:4])
            self.assertIn("paused", near)
        for rid in home.ids:
            self.assertIn(S.PAUSED_SENTENCE, S.norm(self._section(page, home, rid).text()), rid)

    def test_con_17_needs_you_sentence_is_shown_only_for_a_waiting_routine(self):
        home = self.make_home()
        page = self.snapshot(home)
        self.assertEqual(page.text().count(S.NEEDS_YOU_SENTENCE), 1,
                         "exactly one routine (needs-you) has a needs-you latest record")
        self.assertIn(S.NEEDS_YOU_SENTENCE, S.norm(self._section(page, home, "needs-you").text()))
        for rid in ("done-clean", "rich", "paused", "failed"):  # older needs-you records do not count
            own = S.norm(self._section(page, home, rid).text())
            if self._scoped(home, rid, own):
                self.assertNotIn(S.NEEDS_YOU_SENTENCE, own, rid)

    def test_con_18_display_name_and_id_are_both_shown_when_they_differ(self):
        home = self.make_home()
        self._check_names_and_ids(home, self.snapshot(home))

    def test_con_19_served_page_has_the_same_content_as_the_snapshot(self):
        home = self.make_home()
        server = self.serve(home)
        started = datetime.now()
        page = self.served_page(server)
        finished = datetime.now()
        self._check_table(home, page)
        self._check_fields(home, page, strict=False)
        self._check_bodies(home, page)
        self._check_notes(home, page)
        self._check_records(home, page)
        self._check_paths_and_time(home, page, started, finished)
        self._check_sentences(home, page)
        self._check_names_and_ids(home, page)

    # --------------------------------------------------------------- escaping
    def test_con_20_hostile_text_is_escaped_in_the_snapshot(self):
        home = self.make_home()
        self._check_escaped(self.snapshot(home), visible_only=True)

    def test_con_21_hostile_text_is_escaped_in_the_served_page(self):
        home = self.make_home()
        server = self.serve(home)
        self._check_escaped(self.served_page(server), visible_only=False)

    def test_con_22_page_contains_no_javascript(self):
        home = self.make_home()
        server = self.serve(home)
        for label, page in (("snapshot", self.snapshot(home)), ("served", self.served_page(server))):
            low = page.html.lower()
            for raw in ("<script", "javascript:", "<iframe", "<object", "<embed"):
                self.assertNotIn(raw, low, "%s page contains %s" % (label, raw))
            for e in page.elements():
                self.assertFalse([a for a in e.attrs if a.startswith("on")], "%s: handler on <%s>" % (label, e.tag))

    # ------------------------------------------------------------------ forms
    def test_con_23_snapshot_has_no_form(self):
        home = self.make_home()
        page = self.snapshot(home)
        self.assertNotIn("<form", page.html.lower())
        self.assertEqual(page.forms(), [])

    def test_con_24_served_page_has_one_form_per_routine(self):
        home = self.make_home()
        server = self.serve(home)
        forms = self.served_page(server).forms()
        self.assertEqual(len(forms), len(home.ids))
        seen = {}
        allowed = set(S.FIELDS) | {"sha"}
        for form in forms:
            parts = urlsplit(form.action)
            self.assertEqual(form.method, "post")
            self.assertTrue(parts.path.startswith("/routine/"), form.action)
            rid = parts.path[len("/routine/"):]
            self.assertEqual(parse_qs(parts.query), {"t": [server.token]}, form.action)
            self.assertNotIn(rid, seen, "two forms post to " + rid)
            seen[rid] = form
            self.assertEqual(form.names(), allowed, "controls of the form for " + rid)
            self.assertEqual(form.value_of("sha"), home.sha(rid), "sha of " + rid)
        self.assertEqual(sorted(seen), sorted(home.ids))

    def test_con_25_submitting_a_served_form_unchanged_is_accepted_and_changes_nothing(self):
        home = self.make_home()
        server = self.serve(home)
        page = self.served_page(server)
        for rid in home.ids:
            with self.subTest(rid):
                form = self._form_for(page, rid)
                pairs = form.submission()
                effective = dict(pairs)  # the last value of a repeated field wins
                for key in S.FIELDS:
                    self.assertEqual(effective[key].strip(), home.front(rid)[key], "form value of %s.%s" % (rid, key))
                before = home.read(rid)
                parts = urlsplit(form.action)
                resp = S.http_request(server.port, "POST", parts.path + "?" + parts.query, body=S.urlencode(pairs).encode(),
                                      headers={"Content-Type": S.FORM_TYPE,
                                               "Content-Length": str(len(S.urlencode(pairs).encode()))})
                self.assertEqual(resp.status, 303, resp)
                self.assertEqual(resp.header("location"), server.target)
                self.assertEqual(home.read(rid), before)

    # ------------------------------------------------------------------ serve
    def test_con_26_serve_prints_the_url_line_and_writes_the_snapshot_first(self):
        home = self.make_home()
        first = self.serve(home)
        self.assertGreaterEqual(len(first.lines), 2, first.lines)
        self.assertEqual(first.lines[-1], first.url)
        self.assertTrue(any(os.path.isabs(l) and os.path.exists(l) and os.path.samefile(l, str(home.snapshot))
                            for l in first.lines[:-1]), "path line missing: %r" % first.lines)
        self.assertTrue(home.snapshot.is_file(), "console.html must exist when the URL is printed")
        self.assertGreater(first.port, 0)
        self.assertRegex(first.token, r"^[A-Za-z0-9_-]{43}$", "secrets.token_urlsafe(32) is 43 characters")
        self.assertEqual(first.get().status, 200)
        second = self.serve(home)
        self.assertNotEqual(first.token, second.token)
        self.assertNotEqual(first.port, second.port)
        time.sleep(0.3)
        self.assertEqual(self.opened(), [], "--no-open must not launch a browser")

    def test_con_27_serve_honours_the_port_option(self):
        home = self.make_home()
        port = S.free_port()
        server = self.serve(home, "--port", str(port))
        self.assertEqual(server.port, port)
        self.assertEqual(server.get().status, 200)

    def test_con_28_server_listens_on_loopback_only(self):
        home = self.make_home()
        server = self.serve(home)
        self.assertTrue(S.connects("127.0.0.1", server.port))
        for host in S.non_loopback_addresses() + ["127.0.0.2", "::1"]:
            self.assertFalse(S.connects(host, server.port), "server answers on %s" % host)
        if shutil.which("lsof"):
            out = subprocess.run(["lsof", "-nP", "-a", "-p", str(server.proc.pid), "-iTCP", "-sTCP:LISTEN"],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 universal_newlines=True).stdout
            if ":%d" % server.port in out:
                self.assertIn("127.0.0.1:%d" % server.port, out)
                self.assertNotIn("*:%d" % server.port, out)

    def test_con_29_serve_opens_the_url_unless_no_open(self):
        home = self.make_home()
        server = self.serve(home, no_open=False)
        self.assertTrue(self.wait_opened(server.url), "no browser launch for the URL: %r" % self.opened())

    # ------------------------------------------------------------------- auth
    def test_con_30_get_without_or_with_a_wrong_token_is_403(self):
        home = self.make_home()
        a = self.serve(home)
        b = self.serve(home)
        before = home.routine_files()
        for target in ("/", "/?t=", "/?t=wrong", "/?t=" + b.token, "/?t=" + a.token + "x",
                       "/?t=" + a.token[:-1], "/?T=" + a.token, "/?token=" + a.token):
            with self.subTest(target[:40]):
                resp = a.get(target)
                self.assertEqual(resp.status, 403, resp)
                self.assertNotIn("BODY-MARK", resp.text)
        self.assertEqual(home.routine_files(), before)
        self.assertEqual(a.get().status, 200)

    def test_con_31_post_without_or_with_a_wrong_token_is_403(self):
        home = self.make_home(["edit-lf"])
        a = self.serve(home)
        b = self.serve(home)
        fields = [("sha", home.sha("edit-lf")), ("paused", "true")]
        for query in ("", "t=", "t=wrong", "t=" + b.token, "t=" + a.token + "x", "t=" + a.token[:-1]):
            with self.subTest(query[:20]):
                self.assert_refused(a, home, "edit-lf", fields, 403, query=query)
        self.assert_refused(b, home, "edit-lf", fields, 403, query="t=" + a.token)

    def test_con_32_token_is_only_read_from_the_query_parameter_t(self):
        home = self.make_home(["edit-lf"])
        server = self.serve(home)
        sha = home.sha("edit-lf")
        tok = server.token
        self.assert_refused(server, home, "edit-lf", [("sha", sha), ("paused", "true"), ("t", tok)], 403, query="")
        for name, value in (("Authorization", "Bearer " + tok), ("X-Token", tok), ("Cookie", "t=" + tok)):
            with self.subTest(name):
                self.assert_refused(server, home, "edit-lf", [("sha", sha), ("paused", "true")], 403,
                                    query="", headers={name: value})
                self.assertEqual(server.get("/", headers={name: value}).status, 403)

    def test_con_33_foreign_host_is_403_and_local_hosts_are_accepted(self):
        home = self.make_home(["edit-lf"])
        server = self.serve(home)
        port = server.port
        before = home.routine_files()
        for host in ("evil.example", "evil.example:%d" % port, "127.0.0.1", "127.0.0.1:%d" % (port + 1),
                     "localhost", "localhost:%d" % (port + 1), "127.0.0.1.evil.example:%d" % port,
                     "[::1]:%d" % port):
            with self.subTest(host):
                self.assertEqual(server.get(host=host).status, 403)
                self.assert_refused(server, home, "edit-lf",
                                    [("sha", home.sha("edit-lf")), ("paused", "true")], 403, host=host)
        resp = S.raw_exchange(port, ("GET %s HTTP/1.0\r\n\r\n" % server.target).encode())
        self.assertEqual(resp.status, 403, "a request without Host must be refused")
        self.assertEqual(home.routine_files(), before)
        for host in ("127.0.0.1:%d" % port, "localhost:%d" % port):
            self.assertEqual(server.get(host=host).status, 200, host)

    def test_con_34_other_get_paths_are_404(self):
        home = self.make_home()
        server = self.serve(home)
        before = home.routine_files()
        for path in ("/index.html", "/console.html", "/routine/done-clean", "/favicon.ico", "/%2e%2e/etc/passwd",
                     "/routine/"):
            with self.subTest(path):
                self.assertEqual(server.get(path + "?t=" + server.token).status, 404)
        self.assertEqual(home.routine_files(), before)

    # ------------------------------------------------------------------- edit
    def test_con_35_paused_round_trip_changes_only_that_line(self):
        home = self.make_home(["edit-lf"])
        server = self.serve(home)
        before_tree, before = home.tree(), home.read("edit-lf")
        self._ok(server, "edit-lf", [("sha", S.sha256(before)), ("paused", "true")])
        after = home.read("edit-lf")
        self.assertEqual(after, S.oracle_set(before, {"paused": "true"}))
        self.assertNotEqual(after, before)
        after_tree = home.tree()
        changed = {k for k in set(before_tree) | set(after_tree) if before_tree.get(k) != after_tree.get(k)}
        self.assertEqual(changed, {"home/edit-lf/ROUTINE.md", "home/console.html"})
        snap = S.Page(home.snapshot.read_text(encoding="utf-8"))
        self.assertEqual(snap.forms(), [], "the refreshed snapshot must still have no form")
        row = next(r for r in snap.status_rows() if "edit-lf" in r["name"])
        self.assertEqual((row["status"], row["flag"]), ("paused", ""))
        self.assertEqual(len(snap.status_rows()), len(home.ids) + 1)
        page = self.served_page(server)
        row = next(r for r in page.status_rows() if "edit-lf" in r["name"])
        self.assertEqual(row["status"], "paused")
        self.assertEqual(self._form_for(page, "edit-lf").value_of("sha"), home.sha("edit-lf"))

    def test_con_36_crlf_and_mixed_line_endings_are_kept(self):
        home = self.make_home(["edit-crlf", "edit-mixed"])
        server = self.serve(home)
        cases = (("edit-crlf", {"purpose": "New purpose", "paused": "true"}),
                 ("edit-mixed", {"purpose": "New purpose", "weekdays_only": "true", "paused": "true"}))
        for rid, changes in cases:
            with self.subTest(rid):
                before = home.read(rid)
                self._ok(server, rid, [("sha", S.sha256(before))] + sorted(changes.items()))
                after = home.read(rid)
                self.assertEqual(after, S.oracle_set(before, changes))
                self.assertEqual(after.count(b"\r\n"), before.count(b"\r\n"))
                self.assertEqual(after.count(b"\n"), before.count(b"\n"))

    def test_con_37_permission_bits_are_kept(self):
        home = self.make_home(["edit-lf", "edit-crlf"])
        server = self.serve(home)
        for rid, mode in (("edit-lf", 0o640), ("edit-crlf", 0o600)):
            with self.subTest(rid):
                os.chmod(str(home.md(rid)), mode)
                self._ok(server, rid, [("sha", home.sha(rid)), ("paused", "true")])
                self.assertEqual(stat.S_IMODE(os.stat(str(home.md(rid))).st_mode), mode)

    def test_con_38_file_is_replaced_atomically(self):
        home = self.make_home(["edit-lf"])
        server = self.serve(home)
        md = home.md("edit-lf")
        before = home.read("edit-lf")
        old_inode = os.stat(str(md)).st_ino
        keeper = self.sandbox / "old-inode.md"
        os.link(str(md), str(keeper))
        names = sorted(os.listdir(str(md.parent)))
        self._ok(server, "edit-lf", [("sha", S.sha256(before)), ("paused", "true")])
        self.assertNotEqual(md.read_bytes(), before)
        self.assertEqual(keeper.read_bytes(), before, "the old file was rewritten in place, not replaced")
        self.assertNotEqual(os.stat(str(md)).st_ino, old_inode)
        self.assertEqual(sorted(os.listdir(str(md.parent))), names, "temp file left behind")
        self.assert_refused(server, home, "edit-lf", [("sha", "0" * 64), ("paused", "false")], 409)
        self.assertEqual(sorted(os.listdir(str(md.parent))), names, "temp file left behind after a refusal")

    def test_con_39_each_of_the_six_fields_can_be_changed(self):
        new = {"purpose": "Wöchentlicher Bericht — 週報", "schedule": "Mondays 09:00 sharp",
               "cadence_hours": "36.50", "weekdays_only": "true", "paused": "true", "runs_on": "cloud"}
        home = self.make_home(["edit-lf", "edit-crlf"])
        server = self.serve(home)
        for key in S.FIELDS:
            with self.subTest(key):
                before = home.read("edit-lf")
                self._ok(server, "edit-lf", [("sha", S.sha256(before)), (key, new[key])])
                self.assertEqual(home.read("edit-lf"), S.oracle_set(before, {key: new[key]}))
        with self.subTest("all six in one request"):
            before = home.read("edit-crlf")
            self._ok(server, "edit-crlf", [("sha", S.sha256(before))] + [(k, new[k]) for k in S.FIELDS])
            self.assertEqual(home.read("edit-crlf"), S.oracle_set(before, new))

    def test_con_40_values_are_stripped_and_the_last_duplicate_wins(self):
        home = self.make_home(["edit-lf"])
        server = self.serve(home)
        before = home.read("edit-lf")
        self._ok(server, "edit-lf", [("sha", S.sha256(before)), ("purpose", "first"),
                                     ("purpose", "   last wins  "), ("schedule", "   padded  ")])
        after = home.read("edit-lf")
        self.assertEqual(after, S.oracle_set(before, {"purpose": "last wins", "schedule": "padded"}))
        self._ok(server, "edit-lf", [("sha", S.sha256(after)), ("paused", "maybe"), ("paused", "true")])
        final = home.read("edit-lf")
        self.assertEqual(final, S.oracle_set(after, {"paused": "true"}), "only the last value counts")
        self.assert_refused(server, home, "edit-lf",
                            [("sha", S.sha256(final)), ("paused", "false"), ("paused", "maybe")], 400)

    def test_con_41_quotes_inside_a_value_are_kept(self):
        home = self.make_home(["edit-lf"])
        server = self.serve(home)
        before = home.read("edit-lf")
        changes = {"purpose": "it's a \"fine\" day", "schedule": "Mondays 09:00 # not a comment: ok"}
        self._ok(server, "edit-lf", [("sha", S.sha256(before))] + sorted(changes.items()))
        self.assertEqual(home.read("edit-lf"), S.oracle_set(before, changes))

    def test_con_42_missing_key_is_added_before_the_closing_marker(self):
        home = self.make_home(["sparse", "sparse-crlf"])
        server = self.serve(home)
        before = home.read("sparse")
        self._ok(server, "sparse", [("sha", S.sha256(before)), ("paused", "true")])
        once = home.read("sparse")
        self.assertEqual(once, S.oracle_add(before, ["paused: true"]))
        self._ok(server, "sparse", [("sha", S.sha256(once)), ("runs_on", "cloud"), ("cadence_hours", "12")])
        twice = home.read("sparse").splitlines(keepends=True)
        closing = twice.index(b"---\n", 1)
        self.assertEqual(sorted(twice[closing - 2:closing]), [b"cadence_hours: 12\n", b"runs_on: cloud\n"])
        self.assertEqual(b"".join(twice[:closing - 2] + twice[closing:]), once)
        crlf = home.read("sparse-crlf")
        self._ok(server, "sparse-crlf", [("sha", S.sha256(crlf)), ("paused", "true")])
        self.assertEqual(home.read("sparse-crlf"), S.oracle_add(crlf, ["paused: true"]))

    def test_con_43_same_display_name_posts_change_only_the_addressed_folder(self):
        home = self.make_home()
        server = self.serve(home)
        self.assertEqual(home.front("twin-a")["name"], home.front("twin-b")["name"])
        a_before, b_before = home.read("twin-a"), home.read("twin-b")
        self._ok(server, "twin-b", [("sha", S.sha256(b_before)), ("purpose", "Only twin b changed")])
        self.assertEqual(home.read("twin-a"), a_before)
        self.assertEqual(home.read("twin-b"), S.oracle_set(b_before, {"purpose": "Only twin b changed"}))
        self.assert_refused(server, home, "twin-a", [("sha", home.sha("twin-b")), ("purpose", "x")], 409)
        b_mid = home.read("twin-b")
        self._ok(server, "twin-a", [("sha", S.sha256(a_before)), ("paused", "true")])
        self.assertEqual(home.read("twin-b"), b_mid)
        self.assertEqual(home.read("twin-a"), S.oracle_set(a_before, {"paused": "true"}))

    def test_con_44_body_of_exactly_the_size_limit_is_accepted(self):
        home = self.make_home(["edit-lf"])
        server = self.serve(home)
        before = home.read("edit-lf")
        base = len(S.urlencode([("sha", S.sha256(before)), ("purpose", "")]))
        value = "x" * (16384 - base)
        body = S.urlencode([("sha", S.sha256(before)), ("purpose", value)]).encode()
        self.assertEqual(len(body), 16384)
        self._ok(server, "edit-lf", None, body=body)
        self.assertEqual(home.read("edit-lf"), S.oracle_set(before, {"purpose": value}))

    # --------------------------------------------------------------- refusals
    def test_con_45_stale_sha_is_409(self):
        home = self.make_home(["edit-lf"])
        server = self.serve(home)
        stale = home.sha("edit-lf")
        with open(str(home.md("edit-lf")), "ab") as fh:
            fh.write(b"\nadded behind the console's back\n")
        self.assert_refused(server, home, "edit-lf", [("sha", stale), ("paused", "true")], 409)
        self.assert_refused(server, home, "edit-lf", [("sha", "0" * 64), ("paused", "true")], 409)
        self.assert_refused(server, home, "edit-lf", [("sha", "not-a-sha"), ("paused", "true")], 409)
        before = home.read("edit-lf")
        self._ok(server, "edit-lf", [("sha", home.sha("edit-lf")), ("paused", "true")])
        self.assertEqual(home.read("edit-lf"), S.oracle_set(before, {"paused": "true"}))

    def test_con_46_line_separators_in_a_value_are_400(self):
        home = self.make_home(["edit-lf"])
        server = self.serve(home)
        sha = home.sha("edit-lf")
        for field in ("purpose", "schedule"):
            for sep in LINE_SEPARATORS:
                with self.subTest("%s %r" % (field, sep)):
                    self.assert_refused(server, home, "edit-lf", [("sha", sha), (field, "a%sb" % sep)], 400)

    def test_con_47_quote_at_either_end_of_a_value_is_400(self):
        home = self.make_home(["edit-lf"])
        server = self.serve(home)
        sha = home.sha("edit-lf")
        values = ['"quoted"', "'quoted'", '"start', 'end"', "'start", "end'", '  "padded"  ', "  'padded'  "]
        for field in ("purpose", "schedule"):
            for value in values:
                with self.subTest("%s %r" % (field, value)):
                    self.assert_refused(server, home, "edit-lf", [("sha", sha), (field, value)], 400)

    def test_con_48_bad_cadence_hours_is_400(self):
        home = self.make_home(["edit-lf"])
        server = self.serve(home)
        sha = home.sha("edit-lf")
        for value in ("0", "0.0", "-1", "-0.5", "inf", "-inf", "+inf", "nan", "NaN", "Infinity", "abc", "",
                      "1e999", "12h"):
            with self.subTest(repr(value)):
                self.assert_refused(server, home, "edit-lf", [("sha", sha), ("cadence_hours", value)], 400)

    def test_con_49_bad_paused_weekdays_only_and_runs_on_are_400(self):
        home = self.make_home(["edit-lf"])
        server = self.serve(home)
        sha = home.sha("edit-lf")
        flags = ("True", "TRUE", "False", "yes", "no", "1", "0", "on", "")
        for field in ("paused", "weekdays_only"):
            for value in flags:
                with self.subTest("%s %r" % (field, value)):
                    self.assert_refused(server, home, "edit-lf", [("sha", sha), (field, value)], 400)
        for value in ("Cloud", "CLOUD", "local", "desktop", "desktop_local", "laptop", ""):
            with self.subTest("runs_on %r" % value):
                self.assert_refused(server, home, "edit-lf", [("sha", sha), ("runs_on", value)], 400)

    def test_con_50_unknown_field_is_400(self):
        home = self.make_home(["edit-lf"])
        server = self.serve(home)
        sha = home.sha("edit-lf")
        for extra in ([("bogus", "1")], [("name", "Other")], [("Paused", "true")], [("paused_until", "x")],
                      [("paused", "true"), ("extra", "x")]):
            with self.subTest(extra):
                self.assert_refused(server, home, "edit-lf", [("sha", sha)] + extra, 400)

    def test_con_51_missing_sha_is_400(self):
        home = self.make_home(["edit-lf"])
        server = self.serve(home)
        self.assert_refused(server, home, "edit-lf", [("paused", "true")], 400)
        self.assert_refused(server, home, "edit-lf", [], 400)

    def test_con_52_one_bad_field_refuses_the_whole_request(self):
        home = self.make_home(["edit-lf"])
        server = self.serve(home)
        fields = [("sha", home.sha("edit-lf")), ("purpose", "fine value"), ("schedule", "Daily"),
                  ("paused", "maybe")]
        self.assert_refused(server, home, "edit-lf", fields, 400)

    def test_con_53_symlinked_routine_md_is_422(self):
        home = self.make_home(["symlinked"])
        server = self.serve(home)
        link = str(home.md("symlinked"))
        self.assertTrue(os.path.islink(link))
        self.assert_refused(server, home, "symlinked", [("sha", home.sha("symlinked")), ("paused", "true")], 422)
        self.assertTrue(os.path.islink(link), "the symlink was replaced by a regular file")

    def test_con_54_missing_frontmatter_markers_are_422(self):
        home = self.make_home(["no-close", "no-open"])
        server = self.serve(home)
        for rid in ("no-close", "no-open"):
            with self.subTest(rid):
                self.assert_refused(server, home, rid, [("sha", home.sha(rid)), ("paused", "true")], 422)

    def test_con_55_duplicated_key_is_422(self):
        home = self.make_home(["dupe"])
        server = self.serve(home)
        sha = home.sha("dupe")
        self.assert_refused(server, home, "dupe", [("sha", sha), ("schedule", "Hourly")], 422)
        self.assert_refused(server, home, "dupe", [("sha", sha), ("paused", "true")], 422)

    def test_con_56_unknown_id_is_404(self):
        home = self.make_home()
        server = self.serve(home)
        for rid in ("does-not-exist", "Done-Clean", "done-clea"):
            with self.subTest(rid):
                self.assert_refused(server, home, rid, [("sha", "0" * 64), ("paused", "true")], 404)

    def test_con_57_id_with_dot_dot_slash_is_404(self):
        home = self.make_home()
        server = self.serve(home)
        outside = (home.root / "outside" / "ROUTINE.md")
        sha = S.sha256(outside.read_bytes())
        for raw in ("../outside", "..%2Foutside", "%2e%2e%2Foutside", "%2E%2E/outside", "..", "done-clean/../done-clean",
                    "done-clean%2F..%2Fdone-clean", "../outside/ROUTINE.md"):
            with self.subTest(raw):
                self.assert_refused(server, home, "x", [("sha", sha), ("paused", "true")], 404, raw_id=raw)

    def test_con_58_unlisted_folders_are_404(self):
        home = self.make_home()
        server = self.serve(home)
        for rid in ("_kit", ".hidden", "docs", "console.html", "stray.md", "runs"):
            with self.subTest(rid):
                sha = S.sha256((home.path / rid / "ROUTINE.md").read_bytes()) if rid in ("_kit", ".hidden") else "0" * 64
                self.assert_refused(server, home, rid, [("sha", sha), ("paused", "true")], 404)

    def test_con_59_non_form_content_type_is_415(self):
        home = self.make_home(["edit-lf"])
        server = self.serve(home)
        fields = [("sha", home.sha("edit-lf")), ("paused", "true")]
        for ctype in ("application/json", "text/plain", "multipart/form-data; boundary=x", "text/html", None):
            with self.subTest(ctype):
                self.assert_refused(server, home, "edit-lf", fields, 415, content_type=ctype)

    def test_con_60_missing_or_non_numeric_content_length_is_411(self):
        home = self.make_home(["edit-lf"])
        server = self.serve(home)
        for label, kw in (("missing", dict(content_length=None)),
                          ("abc", dict(content_length="abc")),
                          ("12x", dict(content_length="12x")),
                          ("chunked", dict(content_length=None, headers={"Transfer-Encoding": "chunked"}))):
            with self.subTest(label):
                self.assert_refused(server, home, "edit-lf", [], 411, body=b"", timeout=5, **kw)

    def test_con_61_oversize_content_length_is_413_before_the_body_is_read(self):
        home = self.make_home(["edit-lf"])
        server = self.serve(home)
        for length in (16385, 100000, 10 ** 12):
            with self.subTest(length):
                try:
                    self.assert_refused(server, home, "edit-lf", [], 413, body=b"", content_length=length,
                                        timeout=5)
                except socket.timeout:
                    self.fail("413 was not sent until the body arrived; it must be decided from the header")

    def test_con_62_post_checks_run_in_the_documented_order(self):
        home = self.make_home(["edit-lf", "symlinked", "dupe", "no-close"])
        server = self.serve(home)
        good, stale = home.sha("edit-lf"), "0" * 64
        bad = ("paused", "maybe")
        cases = [
            ("token before content type, id and fields", 403, "nope", [("zzz", "1")],
             dict(query="t=wrong", content_type="application/json")),
            ("host before content type", 403, "edit-lf", [("sha", good)],
             dict(host="evil.example", content_type="application/json")),
            ("content type before content length", 415, "edit-lf", [],
             dict(content_type="application/json", content_length=None, body=b"")),
            ("content type before id", 415, "nope", [("sha", good)], dict(content_type="application/json")),
            ("content type before size", 415, "edit-lf", [],
             dict(content_type="application/json", content_length=99999, body=b"", timeout=5)),
            ("content length before id", 411, "nope", [], dict(content_length=None, body=b"", timeout=5)),
            ("size before id", 413, "nope", [], dict(content_length=99999, body=b"", timeout=5)),
            ("id before fields", 404, "nope", [("zzz", "1")], {}),
            ("unknown field before the file state", 400, "symlinked", [("sha", good), ("zzz", "1")], {}),
            ("missing sha before the file state", 400, "symlinked", [("paused", "true")], {}),
            ("missing sha before duplicate key", 400, "dupe", [("paused", "true")], {}),
            ("bad value before the file state", 400, "symlinked", [("sha", home.sha("symlinked")), bad], {}),
            ("bad value before the closing marker", 400, "no-close", [("sha", home.sha("no-close")), bad], {}),
            ("bad value before the sha check", 400, "edit-lf", [("sha", stale), bad], {}),
            ("file state before the sha check (symlink)", 422, "symlinked", [("sha", stale), ("paused", "true")], {}),
            ("file state before the sha check (duplicate)", 422, "dupe", [("sha", stale), ("paused", "true")], {}),
            ("sha check last", 409, "edit-lf", [("sha", stale), ("paused", "true")], {}),
        ]
        for label, status, rid, fields, kw in cases:
            with self.subTest(label):
                self.assert_refused(server, home, rid, fields, status, **kw)

    # ---------------------------------------------------------------- headers
    def test_con_63_headers_on_success_responses(self):
        home = self.make_home(["edit-lf"])
        server = self.serve(home)
        ok = server.get()
        self.assertEqual(ok.status, 200)
        self._headers_ok(ok, "GET page")
        done = self._ok(server, "edit-lf", [("sha", home.sha("edit-lf")), ("paused", "true")])
        self._headers_ok(done, "POST edit")

    def test_con_64_headers_on_refusals(self):
        home = self.make_home(["edit-lf", "symlinked"])
        server = self.serve(home)
        good = [("sha", home.sha("edit-lf")), ("paused", "true")]
        before = home.routine_files()
        tries = [
            ("GET without token", server.get("/")),
            ("GET other path", server.get("/nope?t=" + server.token)),
            ("GET foreign host", server.get(host="evil.example")),
            ("POST wrong token", server.post("edit-lf", good, query="t=wrong")),
            ("POST unknown id", server.post("nope", good)),
            ("POST unknown field", server.post("edit-lf", [("sha", good[0][1]), ("zzz", "1")])),
            ("POST bad value", server.post("edit-lf", [("sha", good[0][1]), ("paused", "maybe")])),
            ("POST stale sha", server.post("edit-lf", [("sha", "0" * 64), ("paused", "true")])),
            ("POST symlink", server.post("symlinked", [("sha", home.sha("symlinked")), ("paused", "true")])),
            ("POST content type", server.post("edit-lf", good, content_type="text/plain")),
            ("POST no length", server.post("edit-lf", [], body=b"", content_length=None, timeout=5)),
            ("POST too long", server.post("edit-lf", [], body=b"", content_length=99999, timeout=5)),
        ]
        for label, resp in tries:
            with self.subTest(label):
                self.assertGreaterEqual(resp.status, 400, resp)
                self._headers_ok(resp, label)
        self.assertEqual(home.routine_files(), before, "a refusal changed a ROUTINE.md")

    def test_con_65_snapshot_carries_the_csp_meta_tag(self):
        home = self.make_home()
        page = self.snapshot(home)
        policies = [m.get("content") for m in page.metas()
                    if m.get("http-equiv", "").lower() == "content-security-policy"]
        self.assertEqual(policies, [S.CSP])

    # -------------------------------------------------------------- lifecycle
    def test_con_66_server_exits_zero_after_idle_seconds(self):
        home = self.make_home()
        server = self.serve(home, "--idle-seconds", "2")
        started = time.monotonic()
        self.assertIsNone(server.proc.poll(), "the server must not exit at once")
        code = server.proc.wait(timeout=20)
        self.assertEqual(code, 0, server.stderr_text())
        self.assertGreaterEqual(time.monotonic() - started, 1.0, "exited long before --idle-seconds")
        self.assertFalse(S.connects("127.0.0.1", server.port), "the port is still open after exit")

    def test_con_67_a_request_resets_the_idle_timer(self):
        home = self.make_home()
        server = self.serve(home, "--idle-seconds", "5")
        time.sleep(3)
        self.assertEqual(server.get().status, 200)
        time.sleep(3.5)
        self.assertIsNone(server.proc.poll(), "idle timer was not reset by a request")
        self.assertEqual(server.proc.wait(timeout=20), 0, server.stderr_text())

    def test_con_68_ctrl_c_exits_zero(self):
        home = self.make_home()
        server = self.serve(home, wrapped=True)
        self.assertEqual(server.get().status, 200)
        server.proc.send_signal(signal.SIGINT)
        self.assertEqual(server.proc.wait(timeout=10), 0, server.stderr_text())

    def test_con_69_stalled_request_is_dropped_and_requests_are_handled_one_at_a_time(self):
        home = self.make_home()
        server = self.serve(home)
        stalled = socket.create_connection(("127.0.0.1", server.port), 5)
        opened = time.monotonic()
        try:
            time.sleep(0.5)
            second = socket.create_connection(("127.0.0.1", server.port), 5)
            try:
                second.sendall(("GET %s HTTP/1.0\r\nHost: 127.0.0.1:%d\r\n\r\n" % (server.target, server.port)).encode())
                second.settimeout(3)
                try:
                    early = second.recv(1)
                except socket.timeout:
                    early = None
                self.assertIsNone(early, "a second request was served while the first connection was open")
                stalled.settimeout(15)
                try:
                    data = stalled.recv(1)
                except ConnectionError:
                    data = b""
                waited = time.monotonic() - opened
                self.assertEqual(data, b"", "the stalled connection got data instead of being dropped")
                self.assertGreaterEqual(waited, 8.0, "dropped after %.1fs; the limit is 10s" % waited)
                self.assertLessEqual(waited, 14.0, "not dropped after %.1fs; the limit is 10s" % waited)
                second.settimeout(10)
                reply = b""
                while True:
                    chunk = second.recv(65536)
                    if not chunk:
                        break
                    reply += chunk
                self.assertTrue(reply.startswith(b"HTTP/1."), reply[:80])
                self.assertIn(b" 200 ", reply.split(b"\r\n", 1)[0])
            finally:
                second.close()
        finally:
            stalled.close()


if __name__ == "__main__":
    import unittest
    unittest.main()
