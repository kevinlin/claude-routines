"""Launch scaffolding for the routines console acceptance gate.

Stdlib only, Python 3.9 compatible. Nothing in here imports console.py: the
gate drives the real CLI as a subprocess, so a missing console.py makes each
test fail on its own instead of breaking collection.

Contents
  fixture      build_home(): the mixed routines home every scenario starts from
  process      ConsoleCase / Server: run the CLI, start --serve, stop it again
  http         http_request / raw_exchange: talk to the server, one connection each
  page model   Page: a small HTML tree with tables, forms and sections
  oracle       byte-level helpers that say what a correct edit looks like

Also runnable by hand for tests/e2e/QA.md:
  python3 tests/e2e/support.py make-fixture DIR [--extras all|name,name]
"""
import hashlib
import http.client
import os
import queue
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "skills" / "routine" / "scripts"
CONSOLE = SCRIPTS / "console.py"
STATUS = SCRIPTS / "status.py"

FIELDS = ("purpose", "schedule", "cadence_hours", "weekdays_only", "paused", "runs_on")
CSP = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'"
FORM_TYPE = "application/x-www-form-urlencoded"
PAUSED_SENTENCE = "Pausing here does not pause the task in Claude Desktop."
NEEDS_YOU_SENTENCE = "Answer this in the Claude session, not here."
HOSTILE = "<script>alert(1)</script>"
URL_LINE = re.compile(r"http://127\.0\.0\.1:(\d+)/\?t=([A-Za-z0-9_-]+)")

# Wraps the real script so SIGINT behaves like Ctrl-C even when the test run
# itself was started with SIGINT ignored (background job, some CI shells).
# `python -c` leaves the script's folder off sys.path, but a plain
# `python console.py` puts it first, and console.py imports its sibling
# status.py. So the wrapper puts the folder at sys.path[0] before run_path.
_SIGINT_WRAPPER = (
    "import os, runpy, signal, sys; "
    "signal.signal(signal.SIGINT, signal.default_int_handler); "
    "sys.argv = sys.argv[1:]; "
    "sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[0]))); "
    "runpy.run_path(sys.argv[0], run_name='__main__')"
)


def norm(text):
    return " ".join(text.split())


def sha256(data):
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# Fixture
# --------------------------------------------------------------------------

def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _stamp(dt):
    return dt.strftime("%Y-%m-%d-%H%M")


def routine_text(spec):
    return (
        "---\n"
        "name: {name}\npurpose: {purpose}\nschedule: {schedule}\ncadence_hours: {cadence}\n"
        "weekdays_only: {weekdays}\npaused: {paused}\nruns_on: {runs_on}\n"
        "---\n\n## Goal\n{body}\n"
    ).format(**spec)


def run_text(started, status, summary, body):
    return (
        "---\nstatus: {s}\nstarted: {a}\nended: {e}\nsummary: {m}\n---\n\n## Done\n- {b}\n"
    ).format(s=status, a=iso(started), e=iso(started + timedelta(minutes=5)), m=summary, b=body)


def _spec(rid, now, *, name=None, purpose=None, schedule="Daily 09:00", cadence="24",
          weekdays="false", paused="false", runs_on="desktop-local", flag="",
          records=(), notes=None, body_extra=""):
    """records: [(age in minutes, status, summary, body)], oldest first."""
    body = "BODY-MARK-{0} first line of the body\n\nBODY-STEP-{0} second paragraph".format(rid)
    if body_extra:
        body += "\n\n" + body_extra
    return {
        "id": rid, "name": name or rid, "purpose": purpose or "Purpose of " + rid.upper(),
        "schedule": schedule, "cadence": cadence, "weekdays": weekdays, "paused": paused,
        "runs_on": runs_on, "flag": flag, "body": body, "notes": notes,
        "records": [(now - timedelta(minutes=age), st, sm, bd) for age, st, sm, bd in records],
    }


def _specs(now):
    rich_records = []
    for k in range(1, 8):  # k=7 is the newest, 35 minutes old; one hour apart
        status = ["done", "failed", "done", "needs-you", "done", "failed", "done"][k - 1]
        rich_records.append((35 + 60 * (7 - k), status,
                             "RUNMARK-%d-SUMMARY" % k, "RUNMARK-%d-BODY did the work" % k))
    hostile = _spec(
        "hostile", now,
        name="XSS-NAME " + HOSTILE,
        purpose='XSS-FM %s "><img src=x onerror=alert(1)> end' % HOSTILE,
        schedule="XSS-SCHED &lt;b&gt;already-escaped &amp; done " + HOSTILE,
        notes="XSS-NOTES %s <img src=x onerror=alert(1)>\n" % HOSTILE,
        body_extra="XSS-BODY " + HOSTILE,
        records=[(40, "done", "XSS-SUMMARY " + HOSTILE, "XSS-RUNBODY " + HOSTILE)],
    )
    return [
        _spec("never-run", now, flag="NEVER RUN"),
        _spec("needs-you", now, flag="NEEDS-YOU",
              records=[(180, "needs-you", "NEEDSYOU-SUMMARY which invoice?", "NEEDSYOU-BODY waiting")]),
        _spec("stalled", now, flag="STALLED",
              records=[(300, "running", "STALLED-SUMMARY started and never ended", "STALLED-BODY begun")]),
        _spec("failed", now, flag="FAILED",
              records=[(60, "failed", "FAILED-SUMMARY could not log in", "FAILED-BODY error")]),
        _spec("overdue", now, flag="OVERDUE",
              records=[(3 * 24 * 60, "done", "OVERDUE-SUMMARY last ran Friday", "OVERDUE-BODY ok")]),
        _spec("done-clean", now, records=[
            (2 * 24 * 60, "needs-you", "DONECLEAN-OLD-SUMMARY question", "DONECLEAN-OLD-BODY asked"),
            (45, "done", "DONECLEAN-SUMMARY all good", "DONECLEAN-BODY finished")]),
        _spec("paused", now, paused="true",
              records=[(120, "failed", "PAUSED-SUMMARY broke while paused", "PAUSED-BODY error")]),
        _spec("rich", now, purpose="RICH-PURPOSE-QWERTY", schedule="Weekdays 07:45 RICH-SCHEDULE",
              cadence="36.5", weekdays="true", runs_on="cloud", records=rich_records,
              notes="NOTES-MARK-rich keep it under ten lines\nNOTES-LATER-rich second note\n"),
        _spec("twin-a", now, name="Shared Name",
              records=[(50, "done", "TWINA-SUMMARY fine", "TWINA-BODY ok")]),
        _spec("twin-b", now, name="Shared Name",
              records=[(55, "done", "TWINB-SUMMARY fine", "TWINB-BODY ok")]),
        _spec("folder-mismatch", now, name="Display Differs",
              records=[(70, "done", "MISMATCH-SUMMARY fine", "MISMATCH-BODY ok")]),
        hostile,
    ]


# Hand-written files for the edit and refusal scenarios. Each is added by name.
EDIT_LF = (
    b"---\n"
    b"name: edit-lf\n"
    b"# paused: true (old value, kept for reference)\n"
    b"owner: kevin\n"
    b"purpose: Weekly check\n"
    b"paused_until: never\n"
    b"schedule: Fridays 16:00\n"
    b"cadence_hours: 168\n"
    b"weekdays_only: false\n"
    b"paused: false\n"
    b"runs_on: desktop-local\n"
    b"note: has: colons and  two  spaces\n"
    b"---\n"
    b"\n"
    b"## Goal\n"
    b"BODY-MARK-edit-lf first line of the body\n"
    b"purpose: body text, not frontmatter\n"
    b"paused: true\n"
    b"\n"
    b"---\n"
    b"\n"
    b"more text after a rule, with no newline at the end"
)
EDIT_CRLF = EDIT_LF.replace(b"edit-lf", b"edit-crlf").replace(b"\n", b"\r\n") + b"\r\n"
EDIT_MIXED = (
    b"---\r\n"
    b"name: edit-mixed\r\n"
    b"purpose: Old purpose\n"
    b"schedule: Fridays 16:00\r\n"
    b"cadence_hours: 24\r\n"
    b"weekdays_only: false\n"
    b"paused: false\r\n"
    b"runs_on: desktop-local\r\n"
    b"---\r\n"
    b"\n"
    b"## Goal\n"
    b"BODY-MARK-edit-mixed first line\r\n"
    b"last line without a newline"
)
SPARSE = (
    b"---\nname: sparse\npurpose: Only purpose\n# trailing comment before the end\n---\n"
    b"BODY-MARK-sparse first line\n"
)
SPARSE_CRLF = SPARSE.replace(b"sparse", b"sparse-crlf").replace(b"\n", b"\r\n")
NO_CLOSE = b"---\nname: no-close\npurpose: Never closed\npaused: false\nBODY-MARK-no-close\n"
NO_OPEN = b"\n---\nname: no-open\npurpose: Starts with a blank line\npaused: false\n---\nBODY-MARK-no-open\n"
DUPE = (b"---\nname: dupe\npurpose: First\nschedule: Daily\nschedule: Twice\npaused: false\n---\n"
        b"BODY-MARK-dupe\n")
SYMLINK_TARGET = (b"---\nname: symlinked\npurpose: Real file behind a link\npaused: false\n---\n"
                  b"BODY-MARK-symlinked\n")

EXTRAS = {
    "edit-lf": EDIT_LF, "edit-crlf": EDIT_CRLF, "edit-mixed": EDIT_MIXED, "sparse": SPARSE,
    "sparse-crlf": SPARSE_CRLF, "no-close": NO_CLOSE, "no-open": NO_OPEN, "dupe": DUPE,
}
ALL_EXTRAS = tuple(EXTRAS) + ("symlinked",)


class Home:
    """A built fixture. root holds home/ (the routines home), outside/ and elsewhere/."""

    def __init__(self, root, specs):
        self.root = Path(root)
        self.path = self.root / "home"
        self.specs = {s["id"]: s for s in specs}
        self.ids = [s["id"] for s in specs]
        self.display = {s["id"]: s["name"] for s in specs}
        self.flag = {s["id"]: s["flag"] for s in specs}
        self.extras = []

    @property
    def snapshot(self):
        return self.path / "console.html"

    def md(self, rid):
        return self.path / rid / "ROUTINE.md"

    def read(self, rid):
        return self.md(rid).read_bytes()

    def sha(self, rid):
        return sha256(self.read(rid))

    def front(self, rid):
        return read_front(self.read(rid))

    def tree(self):
        """Everything under the fixture root, so any stray write shows up."""
        return tree_state(self.root)

    def routine_files(self):
        """Every ROUTINE.md under the fixture root (listed or not), by relative path."""
        return {k: v for k, v in self.tree().items() if k.endswith("ROUTINE.md")}


def build_home(root, extras=()):
    root = Path(root)
    home = root / "home"
    home.mkdir(parents=True)
    now = datetime.now().replace(second=0, microsecond=0)
    specs = _specs(now)
    for spec in specs:
        folder = home / spec["id"]
        (folder / "runs").mkdir(parents=True)
        (folder / "ROUTINE.md").write_bytes(routine_text(spec).encode("utf-8"))
        if spec["notes"]:
            (folder / "notes.md").write_bytes(spec["notes"].encode("utf-8"))
        for started, status, summary, body in spec["records"]:
            (folder / "runs" / (_stamp(started) + ".md")).write_bytes(
                run_text(started, status, summary, body).encode("utf-8"))
    for name, text in (("_kit", "KIT-BODY-MARK"), (".hidden", "HIDDEN-BODY-MARK")):
        (home / name).mkdir()
        (home / name / "ROUTINE.md").write_bytes(
            routine_text(_spec(name, now, body_extra=text)).encode("utf-8"))
    (home / "docs").mkdir()
    (home / "docs" / "README.md").write_text("DOCS-MARK not a routine\n")
    (home / "stray.md").write_text("STRAY-MARK a file, not a folder\n")
    (root / "outside").mkdir()
    (root / "outside" / "ROUTINE.md").write_bytes(EDIT_LF.replace(b"edit-lf", b"outside"))
    meta = Home(root, specs)
    for name in extras:
        add_extra(meta, name)
    return meta


def add_extra(home, name):
    if name == "symlinked":
        (home.root / "elsewhere").mkdir(exist_ok=True)
        target = home.root / "elsewhere" / "real-routine.md"
        target.write_bytes(SYMLINK_TARGET)
        (home.path / "symlinked").mkdir()
        os.symlink(str(target), str(home.path / "symlinked" / "ROUTINE.md"))
    else:
        (home.path / name).mkdir()
        (home.path / name / "ROUTINE.md").write_bytes(EXTRAS[name])
    home.extras.append(name)


def read_front(data):
    """{key: raw value} for the frontmatter lines, the same simple reading status.py does."""
    out = {}
    lines = data.decode("utf-8").splitlines()
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if sep:
            out[key.strip()] = value.strip()
    return out


def tree_state(path):
    out = {}
    for dirpath, dirnames, filenames in os.walk(str(path), followlinks=False):
        for name in dirnames + filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, str(path))
            st = os.lstat(full)
            if stat.S_ISLNK(st.st_mode):
                out[rel] = ("link", os.readlink(full))
            elif stat.S_ISDIR(st.st_mode):
                out[rel] = ("dir",)
            else:
                with open(full, "rb") as fh:
                    out[rel] = ("file", stat.S_IMODE(st.st_mode), fh.read())
    return out


# --------------------------------------------------------------------------
# Oracle: what a correct edit does to the bytes
# --------------------------------------------------------------------------

def _split(data):
    """Lines with their endings; the closing marker index is the first '---' after line 1."""
    lines = data.splitlines(keepends=True)
    close = next(i for i, line in enumerate(lines[1:], 1) if line.rstrip(b"\r\n").strip() == b"---")
    return lines, close


def oracle_set(data, changes):
    """Rewrite existing `key: value` frontmatter lines, keeping each line's own ending."""
    lines, close = _split(data)
    for i in range(1, close):
        body = lines[i].rstrip(b"\r\n")
        end = lines[i][len(body):]
        key = body.split(b":", 1)[0].strip().decode("utf-8")
        if b":" in body and key in changes:
            lines[i] = ("%s: %s" % (key, changes[key])).encode("utf-8") + end
    return b"".join(lines)


def oracle_add(data, new_lines):
    """Insert `key: value` lines directly before the closing marker, in the closing marker's ending."""
    lines, close = _split(data)
    closing = lines[close]
    end = closing[len(closing.rstrip(b"\r\n")):] or b"\n"
    added = [line.encode("utf-8") + end for line in new_lines]
    return b"".join(lines[:close] + added + lines[close:])


# --------------------------------------------------------------------------
# Page model
# --------------------------------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
         "source", "track", "wbr"}
_BLOCK = {"div", "p", "tr", "td", "th", "li", "ul", "ol", "dl", "dt", "dd", "h1", "h2", "h3", "h4",
          "h5", "h6", "section", "article", "table", "thead", "tbody", "tfoot", "br", "details",
          "summary", "pre", "form", "label", "option", "select", "header", "footer", "main", "nav",
          "fieldset", "legend", "body", "html", "aside", "textarea", "blockquote", "hr", "caption",
          "title"}
_IMPLIED_CLOSE = {"td": ("td", "th"), "th": ("td", "th"), "tr": ("td", "th", "tr"), "li": ("li",),
                  "option": ("option",), "p": ("p",), "dt": ("dt", "dd"), "dd": ("dt", "dd")}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children = []
        self.parent = parent

    def elements(self, tag=None):
        stack = [self]
        while stack:
            node = stack.pop()
            if tag is None or node.tag == tag:
                yield node
            stack.extend(reversed([c for c in node.children if isinstance(c, Node)]))

    def own_texts(self):
        return [c for c in self.children if isinstance(c, str)]

    def ancestors(self):
        node, out = self, []
        while node is not None:
            out.append(node)
            node = node.parent
        return out

    def corpus(self):
        """Visible text plus every attribute value below this node, whitespace collapsed."""
        values = [self.text()]
        for e in self.elements():
            values.extend(v for v in e.attrs.values() if v)
        return norm("\n".join(values))

    def text(self):
        out = []

        def walk(node):
            if node.tag in ("style", "script"):
                return
            block = node.tag in _BLOCK
            if block:
                out.append("\n")
            for child in node.children:
                if isinstance(child, str):
                    out.append(child)
                else:
                    walk(child)
            if block:
                out.append("\n")

        walk(self)
        return "".join(out)


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.cur = self.root
        self.start_tags = []

    def handle_starttag(self, tag, attrs):
        closing = _IMPLIED_CLOSE.get(tag, ())
        while self.cur.tag in closing:
            self.cur = self.cur.parent
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.children.append(node)
        self.start_tags.append(tag)
        if tag not in _VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.tag != "#root":
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


class Form:
    def __init__(self, node):
        self.node = node
        self.action = node.attrs.get("action", "")
        self.method = node.attrs.get("method", "get").lower()

    def named_controls(self):
        return [e for e in self.node.elements()
                if e.tag in ("input", "select", "textarea", "button") and e.attrs.get("name")]

    def names(self):
        return {e.attrs["name"] for e in self.named_controls()}

    def value_of(self, name):
        for e in self.named_controls():
            if e.attrs["name"] == name:
                return e.attrs.get("value", "")
        return None

    def submission(self):
        """The (name, value) pairs a browser would send for this form, in document order."""
        pairs = []
        for e in self.node.elements():
            name = e.attrs.get("name")
            if not name or "disabled" in e.attrs:
                continue
            if e.tag == "input":
                kind = e.attrs.get("type", "text").lower()
                if kind in ("checkbox", "radio"):
                    if "checked" in e.attrs:
                        pairs.append((name, e.attrs.get("value", "on")))
                elif kind not in ("submit", "button", "image", "reset", "file"):
                    pairs.append((name, e.attrs.get("value", "")))
            elif e.tag == "select":
                options = list(e.elements("option"))
                chosen = [o for o in options if "selected" in o.attrs] or options[:1]
                for o in chosen:
                    pairs.append((name, o.attrs["value"] if "value" in o.attrs else norm(o.text())))
            elif e.tag == "textarea":
                pairs.append((name, "".join(e.own_texts()).lstrip("\n")))
        return pairs


class Page:
    def __init__(self, html):
        builder = _Builder()
        builder.feed(html)
        builder.close()
        self.html = html
        self.root = builder.root
        self.start_tags = builder.start_tags

    def elements(self, tag=None):
        return list(self.root.elements(tag))

    def text(self):
        return norm(self.root.text())

    def corpus(self):
        return self.root.corpus()

    def forms(self):
        return [Form(n) for n in self.root.elements("form")]

    def metas(self):
        return [n.attrs for n in self.root.elements("meta")]

    def status_rows(self):
        """Rows of the status table as dicts name/status/last/flag/summary (cell text)."""
        for table in self.root.elements("table"):
            rows = []
            for tr in table.elements("tr"):
                rows.append([norm(c.text()) for c in tr.children
                             if isinstance(c, Node) and c.tag in ("td", "th")])
            for h, header in enumerate(rows):
                low = [c.lower() for c in header]
                if "status" in low and any("flag" in c for c in low):
                    return self._rows_by_header(low, rows[h + 1:])
        raise AssertionError("no table with Status and Flag columns found in the page")

    @staticmethod
    def _rows_by_header(low, body):
        def find(test, default):
            return next((i for i, c in enumerate(low) if test(c)), default)

        index = {
            "name": find(lambda c: "routine" in c or "name" in c, 0),
            "status": find(lambda c: c == "status", 1),
            "last": find(lambda c: "last" in c, 2),
            "flag": find(lambda c: "flag" in c, 3),
            "summary": find(lambda c: "summary" in c, 4),
        }
        need = max(index.values()) + 1
        return [{k: row[i] for k, i in index.items()} for row in body if len(row) >= need]

    def section(self, path, marker):
        """The smallest element that holds both the routine's ROUTINE.md path and its body marker."""
        path_nodes = [e for e in self.root.elements() if any(path in t for t in e.own_texts())]
        mark_nodes = [e for e in self.root.elements() if any(marker in t for t in e.own_texts())]
        if not path_nodes:
            raise AssertionError("path %s is not shown as text in the page" % path)
        if not mark_nodes:
            raise AssertionError("body marker %s is not shown in the page" % marker)
        best, best_size = None, None
        for a in path_nodes:
            ancestors = a.ancestors()
            for b in mark_nodes:
                node = b
                while all(node is not x for x in ancestors):
                    node = node.parent
                size = sum(1 for _ in node.elements())
                if best is None or size < best_size:
                    best, best_size = node, size
        return best


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

class Response:
    def __init__(self, status, reason, headers, body):
        self.status = status
        self.reason = reason
        self.headers = headers
        self.body = body

    @property
    def text(self):
        return self.body.decode("utf-8", "replace")

    @property
    def page(self):
        return Page(self.text)

    def header(self, name):
        return self.headers.get(name.lower())

    def __repr__(self):
        return "<Response %s %s %r>" % (self.status, self.reason, self.text[:120])


def _response(resp):
    data = resp.read()
    headers = {}
    for key, value in resp.getheaders():
        key = key.lower()
        headers[key] = headers[key] + ", " + value if key in headers else value
    return Response(resp.status, resp.reason, headers, data)


def http_request(port, method, target, *, headers=(), host="default", body=None, timeout=15):
    """One request on its own connection. headers are sent verbatim, nothing is added but Host."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.putrequest(method, target, skip_host=True, skip_accept_encoding=True)
        if host == "default":
            conn.putheader("Host", "127.0.0.1:%d" % port)
        elif host is not None:
            conn.putheader("Host", host)
        for key, value in (headers.items() if isinstance(headers, dict) else headers):
            conn.putheader(key, value)
        conn.putheader("Connection", "close")
        conn.endheaders(body)
        return _response(conn.getresponse())
    finally:
        conn.close()


def raw_exchange(port, payload, timeout=10):
    """Send raw bytes, parse whatever comes back."""
    sock = socket.create_connection(("127.0.0.1", port), timeout)
    try:
        sock.sendall(payload)
        resp = http.client.HTTPResponse(sock)
        resp.begin()
        return _response(resp)
    finally:
        sock.close()


def post_short(port, target, body, *, short_by=20, host="default", content_type=FORM_TYPE, timeout=10):
    """POST over a raw socket that declares len(body) but stops short_by bytes early.

    The client then half-closes (SHUT_WR) so the server sees end-of-stream mid-body,
    and reads the answer. short_by=0 sends the whole body and is the control case.
    """
    head = "POST %s HTTP/1.0\r\nHost: %s\r\n" % (target, "127.0.0.1:%d" % port if host == "default" else host)
    if content_type is not None:
        head += "Content-Type: %s\r\n" % content_type
    head += "Content-Length: %d\r\n\r\n" % len(body)
    sock = socket.create_connection(("127.0.0.1", port), timeout)
    try:
        sock.sendall(head.encode("ascii") + body[:len(body) - short_by])
        sock.shutdown(socket.SHUT_WR)
        resp = http.client.HTTPResponse(sock)
        resp.begin()
        return _response(resp)
    finally:
        sock.close()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def connects(host, port, timeout=2):
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((host, port))
            return True
    except OSError:
        return False


def non_loopback_addresses():
    found = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # no packet is sent; this only picks a route
            found.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        found.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    return sorted(a for a in found if not a.startswith("127.") and a != "0.0.0.0")


# --------------------------------------------------------------------------
# Processes
# --------------------------------------------------------------------------

class Server:
    """A started `console.py --serve`. Stdout is drained by a thread so it never blocks."""

    def __init__(self, home_path, env, extra=(), wrapped=False, no_open=True):
        argv = [sys.executable]
        if wrapped:
            argv += ["-c", _SIGINT_WRAPPER]
        argv += [str(CONSOLE), "--serve", "--home", str(home_path)]
        if no_open:
            argv.append("--no-open")
        argv += list(extra)
        self.argv = argv
        self._err = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=self._err, env=env, universal_newlines=True,
                                     encoding="utf-8", bufsize=1)
        self.lines = []
        self._queue = queue.Queue()
        self._pump = threading.Thread(target=self._read, daemon=True)
        self._pump.start()
        self.port = None
        self.token = None
        self.url = None

    def _read(self):
        try:
            for line in self.proc.stdout:
                self._queue.put(line.rstrip("\n"))
        finally:
            self._queue.put(None)

    def stderr_text(self):
        self._err.flush()
        self._err.seek(0)
        return self._err.read().decode("utf-8", "replace")

    def wait_url(self, timeout=20):
        deadline = time.monotonic() + timeout
        while True:
            try:
                line = self._queue.get(timeout=max(0.05, deadline - time.monotonic()))
            except queue.Empty:
                line = False
            if line is None:
                rc = self.proc.wait(10)
                raise AssertionError("console.py --serve exited with %s before printing its URL.\n"
                                     "stdout: %r\nstderr: %s" % (rc, self.lines, self.stderr_text()[-1500:]))
            if line is False or time.monotonic() > deadline:
                raise AssertionError("no URL line within %ss. stdout so far: %r\nstderr: %s"
                                     % (timeout, self.lines, self.stderr_text()[-1500:]))
            self.lines.append(line)
            match = URL_LINE.fullmatch(line)
            if match:
                self.port, self.token, self.url = int(match.group(1)), match.group(2), line
                return self

    @property
    def target(self):
        return "/?t=" + self.token

    def get(self, target=None, **kw):
        return http_request(self.port, "GET", self.target if target is None else target, **kw)

    def post(self, rid, fields, *, raw_id=None, query=None, body=None, content_type=FORM_TYPE,
             content_length="auto", headers=(), host="default", timeout=15):
        """POST to /routine/<id>?t=<token>. fields: list of pairs, urlencoded unless body is given."""
        if body is None:
            body = urlencode(list(fields)).encode("utf-8")
        target = "/routine/%s?%s" % (rid if raw_id is None else raw_id,
                                     "t=" + self.token if query is None else query)
        hdrs = list(headers.items() if isinstance(headers, dict) else headers)
        if content_type is not None:
            hdrs.append(("Content-Type", content_type))
        if content_length == "auto":
            hdrs.append(("Content-Length", str(len(body))))
        elif content_length is not None:
            hdrs.append(("Content-Length", str(content_length)))
        return http_request(self.port, "POST", target, headers=hdrs, host=host, body=body, timeout=timeout)

    def post_short(self, rid, fields, *, short_by=20, raw_id=None, query=None, **kw):
        """Like post(), but the body stops short_by bytes before the declared Content-Length."""
        body = urlencode(list(fields)).encode("utf-8")
        target = "/routine/%s?%s" % (rid if raw_id is None else raw_id,
                                     "t=" + self.token if query is None else query)
        return post_short(self.port, target, body, short_by=short_by, **kw)

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(5)
        try:
            self.proc.stdout.close()
        except OSError:
            pass
        self._pump.join(2)
        self._err.close()


class ConsoleCase(unittest.TestCase):
    """Sandbox per test: a temp root, a fake HOME, and browser launchers that only record."""

    def setUp(self):
        self.sandbox = Path(os.path.realpath(tempfile.mkdtemp(prefix="console-e2e-")))
        self.addCleanup(shutil.rmtree, str(self.sandbox), True)
        bin_dir = self.sandbox / "bin"
        bin_dir.mkdir()
        (self.sandbox / "fakehome").mkdir()
        for name in ("open", "xdg-open", "gnome-open", "kde-open", "x-www-browser", "www-browser",
                     "sensible-browser", "wslview"):
            shim = bin_dir / name
            shim.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$OPEN_LOG\"\n")
            shim.chmod(0o755)
        env = dict(os.environ)
        env.pop("ROUTINES_HOME", None)
        env.update(HOME=str(self.sandbox / "fakehome"),
                   PATH=str(bin_dir) + os.pathsep + env.get("PATH", ""),
                   BROWSER=str(bin_dir / "open"), OPEN_LOG=str(self.sandbox / "open.log"),
                   PYTHONDONTWRITEBYTECODE="1")
        self.env = env

    # fixture ---------------------------------------------------------------
    def make_home(self, extras=()):
        return build_home(self.sandbox / "fx", extras)

    # one-shot runs ---------------------------------------------------------
    def run_console(self, home_path, *extra, no_open=True, timeout=60):
        argv = [sys.executable, str(CONSOLE), "--home", str(home_path)]
        if no_open:
            argv.append("--no-open")
        argv += list(extra)
        return subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=self.env, timeout=timeout,
                              universal_newlines=True, encoding="utf-8")

    def run_status(self, home_path):
        """(stdout, rows) of status.py --home. Rows are parsed from the header's column offsets."""
        proc = subprocess.run([sys.executable, str(STATUS), "--home", str(home_path)],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=self.env, timeout=60, universal_newlines=True, encoding="utf-8")
        self.assertIn(proc.returncode, (0, 1), proc.stderr)
        return proc.stdout, parse_status_table(proc.stdout)

    def snapshot(self, home):
        """Run the snapshot mode, return the parsed console.html."""
        proc = self.run_console(home.path)
        self.assertEqual(proc.returncode, 0, "console.py failed:\n%s\n%s" % (proc.stdout, proc.stderr))
        self.assertTrue(home.snapshot.is_file(), "console.html was not written\n" + proc.stdout)
        return Page(home.snapshot.read_text(encoding="utf-8"))

    # servers ---------------------------------------------------------------
    def serve(self, home, *extra, wrapped=False, no_open=True):
        path = home.path if isinstance(home, Home) else home
        server = Server(path, self.env, extra, wrapped=wrapped, no_open=no_open)
        self.addCleanup(server.stop)
        return server.wait_url()

    def served_page(self, server):
        resp = server.get()
        self.assertEqual(resp.status, 200, resp)
        return resp.page

    # browser launcher log --------------------------------------------------
    def opened(self):
        log = self.sandbox / "open.log"
        return log.read_text().splitlines() if log.exists() else []

    def wait_opened(self, needle, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if any(needle in line for line in self.opened()):
                return True
            time.sleep(0.1)
        return False

    # refusals --------------------------------------------------------------
    def assert_refused(self, server, home, rid, fields, status, **kw):
        """POST that must fail with `status` and leave every file under the fixture untouched."""
        before = home.tree()
        resp = server.post(rid, fields, **kw)
        self.assertEqual(resp.status, status, "expected %s, got %r for %r" % (status, resp, fields))
        self.assertEqual(home.tree(), before, "a refused request changed files (%s)" % status)
        return resp


def parse_status_table(text):
    lines = text.splitlines()
    header = lines[0]
    cuts = [header.index(t) for t in ("STATUS", "LAST RUN", "FLAG", "SUMMARY")]
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        cells = [line[:cuts[0]], line[cuts[0]:cuts[1]], line[cuts[1]:cuts[2]],
                 line[cuts[2]:cuts[3]], line[cuts[3]:]]
        rows.append(dict(zip(("name", "status", "last", "flag", "summary"), (c.strip() for c in cells))))
    return rows


# --------------------------------------------------------------------------
# By hand, for QA.md
# --------------------------------------------------------------------------

def _main(argv):
    if len(argv) >= 3 and argv[1] == "make-fixture":
        extras = ()
        if "--extras" in argv:
            value = argv[argv.index("--extras") + 1]
            extras = ALL_EXTRAS if value == "all" else tuple(v for v in value.split(",") if v)
        home = build_home(Path(argv[2]).resolve(), extras)
        print(home.path)
        return 0
    print(__doc__.split("Also runnable by hand for tests/e2e/QA.md:")[1].strip())
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
