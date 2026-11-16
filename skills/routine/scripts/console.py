#!/usr/bin/env python3
"""Console for personal routines: one page with every routine's status, config, notes and runs.

Writes <home>/console.html. With --serve it also serves the page on 127.0.0.1 so a few
frontmatter fields can be changed without opening the file. Stdlib only, no JavaScript in
the page, Python 3.9 compatible. The server writes files that unattended runs depend on and
shows text that runs copied from mail and tickets, so: every piece of file content is
escaped, every request needs the Host and the token, and ROUTINE.md is edited line by line
and replaced atomically only if it has not changed since it was read.
"""
import argparse
import contextlib
import hashlib
import hmac
import html
import math
import os
import secrets
import stat
import sys
import tempfile
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, quote, unquote

import status

FIELDS = ("purpose", "schedule", "cadence_hours", "weekdays_only", "paused", "runs_on")
CHOICES = {"weekdays_only": ("true", "false"), "paused": ("true", "false"), "runs_on": ("desktop-local", "cloud")}
CADENCE_PRESETS = ("24", "168", "744")  # daily, weekly, monthly: offered when the file has no usable cadence
FORM = "application/x-www-form-urlencoded"
MAX_BODY = 16384
RECENT = 5  # run records shown per routine
POLICY = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'"
PAUSE_NOTE = "Pausing here does not pause the task in Claude Desktop."
ASK_NOTE = "Answer this in the Claude session, not here."
FLAG_CLASS = {"NEEDS-YOU": "needs", "STALLED": "stalled", "FAILED": "failed", "OVERDUE": "overdue", "NEVER RUN": "never"}

CSS = """
:root {
  color-scheme: light dark;
  --font-body: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  --bg:        light-dark(#fbfaf7, #14161a);
  --surface:   light-dark(#ffffff, #1c1f25);
  --code-bg:   light-dark(#f2f0ea, #22262d);
  --text:      light-dark(#1d2027, #e6e4df);
  --muted:     light-dark(#565c66, #a3a7ae);
  --rule:      light-dark(#e4e1d9, #2e333b);
  --accent:    light-dark(#0e7490, #5ec8dd);
  --accent-bg: light-dark(rgba(14,116,144,.08), rgba(94,200,221,.10));
  --ring:      var(--accent);
  --st-needs:   light-dark(#1d4ed8, #93b4fd);
  --st-stalled: light-dark(#c2410c, #fdae74);
  --st-overdue: light-dark(#6d28d9, #c4b0fc);
  --st-failed:  light-dark(#be123c, #fb92a8);
  --st-never:   light-dark(#4b5563, #b4bac3);
  --radius: 12px;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 400 16px/1.55 var(--font-body); }
main { max-width: 68rem; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 28px; margin: 0 0 4px; }
h2 { font-size: 20px; margin: 32px 0 12px; }
h3 { font-size: 14px; margin: 20px 0 6px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
h4 { font: 500 13px/1.4 var(--font-mono); margin: 12px 0 4px; }
p { margin: 0 0 12px; }
.muted, .id, .hint { color: var(--muted); }
.id, .hint { font-size: 14px; }
.id { font-family: var(--font-mono); }
:focus-visible { outline: 2px solid var(--ring); outline-offset: 2px; border-radius: 4px; }
code { font: 400 .9em var(--font-mono); background: var(--code-bg); padding: 2px 6px; border-radius: 5px; }
.table-wrap, details { background: var(--surface); border-radius: var(--radius); outline: 1px solid var(--rule); outline-offset: -1px; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; vertical-align: top; padding: 10px 14px; border-bottom: 1px solid var(--rule); }
thead th { background: var(--code-bg); color: var(--muted); font-size: 13px; }
tbody tr:last-child > * { border-bottom: 0; }
td:nth-child(2), td:nth-child(3) { white-space: nowrap; }
a { color: var(--accent); text-underline-offset: 3px; }
.flag { display: inline-block; font: 500 12px/1 var(--font-mono); white-space: nowrap; padding: 5px 8px; border-radius: 6px;
        color: var(--c); box-shadow: inset 0 0 0 1px var(--c); }
.flag.needs { --c: var(--st-needs); } .flag.stalled { --c: var(--st-stalled); } .flag.failed { --c: var(--st-failed); }
.flag.overdue { --c: var(--st-overdue); } .flag.never { --c: var(--st-never); }
details { margin: 0 0 12px; }
summary { cursor: pointer; padding: 12px 16px; font-weight: 600; }
.inner { padding: 0 16px 16px; border-top: 1px solid var(--rule); }
pre { margin: 0 0 12px; padding: 12px 14px; background: var(--code-bg); border-radius: 8px;
      font: 400 13px/1.5 var(--font-mono); white-space: pre-wrap; overflow-wrap: anywhere; }
.callout { padding: 10px 14px; background: var(--accent-bg); border-left: 3px solid var(--accent); border-radius: 6px; }
.fields { display: grid; grid-template-columns: max-content 1fr; gap: 10px 16px; align-items: start; margin: 0 0 12px; }
.fields dt, .fields label { font: 500 13px/36px var(--font-mono); color: var(--muted); }
.fields dd { margin: 0; line-height: 36px; }
.fields .hint { display: block; margin: 2px 0 0; line-height: 1.4; }
.fields dd .hint { margin: -6px 0 6px; }
input, select { font: inherit; width: 100%; max-width: 32rem; min-height: 36px; padding: 4px 10px;
                background: var(--surface); color: var(--text); border: 1px solid var(--muted); border-radius: 8px; }
input:disabled { background: var(--code-bg); }
::placeholder { color: var(--muted); opacity: 1; }
button { font: inherit; font-weight: 600; min-height: 40px; padding: 8px 16px; border: 0; border-radius: 8px;
         background: var(--accent); color: var(--bg); cursor: pointer; }
@media (max-width: 560px) { .fields { grid-template-columns: 1fr; gap: 2px; } .fields dt, .fields label { line-height: 1.4; } }
"""


class Refused(Exception):
    """A request or edit that must not go ahead; code is the HTTP status."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# --- reading -------------------------------------------------------------

def read_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def frontmatter_end(lines):
    """Index of the closing --- line, or None without an opening --- on line 1 or without a closing one."""
    if not lines or lines[0].strip() != "---":  # the same rule status.frontmatter applies
        return None
    return next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)


def body_of(text):
    lines = text.splitlines(keepends=True)
    end = frontmatter_end(lines)
    return "".join(lines if end is None else lines[end + 1:]).strip()


def collect(home, now):
    """Everything the page shows. Frontmatter values come from status.frontmatter and are for display only."""
    routines = []
    for folder in status.folders(home):
        path = folder / "ROUTINE.md"
        raw = path.read_bytes()  # read before status.* so that a late change makes the sha stale, never fresh
        records = sorted((folder / "runs").glob("*.md"))[-RECENT:][::-1]
        routines.append({
            "id": folder.name,
            "path": os.path.abspath(path),
            "row": status.check(folder, now),
            "meta": status.frontmatter(path),
            "sha": hashlib.sha256(raw).hexdigest(),
            "problem": "ROUTINE.md is a symlink" if path.is_symlink() else problem_with(raw),
            "body": body_of(raw.decode("utf-8", "replace")),
            "notes": read_text(folder / "notes.md"),
            "runs": [{"name": p.name, "meta": status.frontmatter(p), "text": read_text(p)} for p in records],
        })
    return routines


def problem_with(raw):
    try:
        rewrite(raw, {})
    except Refused as refusal:
        return str(refusal)
    return None


# --- page ----------------------------------------------------------------

def esc(text):
    return html.escape(str(text))


def flag_html(flag):
    return f'<span class="flag {FLAG_CLASS.get(flag, "never")}">{esc(flag)}</span>' if flag else ""


def id_note(r):
    return "" if r["row"]["name"] == r["id"] else f' <span class="id">folder: {esc(r["id"])}</span>'


def block(text, empty):
    return f"<pre>{esc(text)}</pre>" if text and text.strip() else f'<p class="muted">{empty}</p>'


def table_row(i, r):
    row = r["row"]
    return (
        f'<tr><th scope="row"><a href="#r-{i}">{esc(row["name"])}</a>{id_note(r)}</th>'
        f'<td>{esc(row["status"])}</td><td>{esc(row["last"])}</td><td>{flag_html(row["flag"])}</td>'
        f'<td>{esc(row["summary"])}</td></tr>'
    )


def fields_html(r):
    cells = []
    for key in FIELDS:
        value = r["meta"].get(key)
        shown = '<span class="muted">not set</span>' if value is None else esc(value)
        note = f' <span class="hint">{PAUSE_NOTE}</span>' if key == "paused" else ""
        cells.append(f"<dt>{key}</dt><dd>{shown}{note}</dd>")
    return f'<dl class="fields">{"".join(cells)}</dl>'


def field_row(i, key, meta):
    cid, value = f"f{i}-{key}", meta.get(key)
    hint = f'<p class="hint" id="{cid}-hint">{PAUSE_NOTE}</p>' if key == "paused" else ""
    described = f' aria-describedby="{cid}-hint"' if hint else ""
    options = CHOICES.get(key)
    if key == "cadence_hours" and (value is None or bad_value(key, value)):
        options = CADENCE_PRESETS
    if options:
        # A selected, disabled option is not submitted, so a control nobody touched leaves the file alone.
        current = "" if value in options else f'<option value="" selected disabled>{esc(value) if value else "(not set)"}</option>'
        choices = "".join(f'<option{" selected" if o == value else ""}>{o}</option>' for o in options)
        control = f'<select id="{cid}" name="{key}"{described}>{current}{choices}</select>'
    elif value is None:  # purpose or schedule that the file does not have: shown, not submitted
        control = f'<input id="{cid}" name="{key}" placeholder="not set in the file" disabled>'
    else:
        control = f'<input id="{cid}" name="{key}" value="{esc(value)}"{described}>'
    return f'<label for="{cid}">{key}</label><div>{control}{hint}</div>'


def form_html(i, r, token):
    action = f'/routine/{quote(r["id"], safe="")}?t={quote(token, safe="")}'
    rows = "".join(field_row(i, key, r["meta"]) for key in FIELDS)
    return (
        f'<form method="post" action="{esc(action)}" enctype="{FORM}">'
        f'<input type="hidden" name="sha" value="{r["sha"]}">'
        f'<div class="fields">{rows}</div><p><button type="submit">Save changes</button></p></form>'
    )


def card(i, r, token):
    row = r["row"]
    asks = r["runs"] and r["runs"][0]["meta"].get("status") == "needs-you"
    parts = [
        f'<details id="r-{i}"{" open" if row["flag"] else ""}>',
        f'<summary>{esc(row["name"])}{id_note(r)} {flag_html(row["flag"])}</summary><div class="inner">',
        f'<p class="id">File: <code>{esc(r["path"])}</code></p>',
    ]
    if asks:
        parts.append(f'<p class="callout">{ASK_NOTE}</p>')
    parts.append("<h3>Settings</h3>")
    if token is not None and r["problem"]:
        parts.append(f'<p class="callout">Not editable here: {esc(r["problem"])}. Change the file by hand.</p>')
    parts.append(form_html(i, r, token) if token is not None and not r["problem"] else fields_html(r))
    parts.append(f'<h3>ROUTINE.md</h3>{block(r["body"], "Empty.")}')
    parts.append(f'<h3>notes.md</h3>{block(r["notes"], "No notes yet.")}')
    parts.append(f"<h3>Recent runs (newest {RECENT})</h3>")
    parts += [f'<h4>{esc(run["name"])}</h4>{block(run["text"], "Empty.")}' for run in r["runs"]]
    if not r["runs"]:
        parts.append('<p class="muted">No run records yet.</p>')
    return "".join(parts) + "</div></details>"


def render(routines, now, token=None):
    """The page. Without a token it is the read-only snapshot: no form."""
    ordered = sorted(routines, key=lambda r: not r["row"]["flag"])  # stable: flagged first, then folder order
    intro = "Saving writes the field into ROUTINE.md." if token is not None else "Read-only snapshot."
    heads = "".join(f'<th scope="col">{h}</th>' for h in ("Routine", "Status", "Last run", "Flag", "Summary"))
    rows = "".join(table_row(i, r) for i, r in enumerate(ordered))
    cards = "".join(card(i, r, token) for i, r in enumerate(ordered))
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{POLICY}">\n'
        '<meta name="referrer" content="no-referrer">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>Routines console</title>\n<style>{CSS}</style>\n</head>\n<body>\n<main>\n"
        f'<h1>Routines</h1>\n<p class="muted">Generated {now:%Y-%m-%d %H:%M:%S}. {intro}</p>\n'
        f'<h2>Status</h2>\n<div class="table-wrap"><table><thead><tr>{heads}</tr></thead><tbody>{rows}</tbody></table></div>\n'
        f"<h2>Routines</h2>\n{cards}\n</main>\n</body>\n</html>\n"
    )


# --- writing -------------------------------------------------------------

def write_atomic(path, data, mode, before_replace=lambda: None):
    """Temp file next to path, then os.replace. before_replace may raise to abandon the write."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        before_replace()
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def write_static(home, now):
    path = Path(os.path.abspath(Path(home).expanduser() / "console.html"))
    write_atomic(path, render(collect(home, now), now).encode("utf-8"), 0o600)  # 0600: it holds notes
    return path


def read_file(path):
    """(bytes, permission bits) of a regular file. A symlink is refused: its target is not ours to rewrite."""
    if path.is_symlink():
        raise Refused(422, f"{path.name} is a symlink")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as handle:
            return handle.read(), stat.S_IMODE(os.fstat(handle.fileno()).st_mode)
    except OSError as error:
        raise Refused(422, f"cannot read {path.name}: {error.strerror}")


def bad_value(key, value):
    """Why value cannot be written as `key: value`, or None. Mirrors what status.frontmatter reads back."""
    if len((value + ".").splitlines()) > 1:  # any line separator str.splitlines() knows, not just \n
        return "must be a single line"
    if value.startswith(("'", '"')) or value.endswith(("'", '"')):
        return "must not start or end with a quote"
    if key == "cadence_hours":
        try:
            number = float(value)
        except ValueError:
            number = 0
        if not (math.isfinite(number) and number > 0):
            return "must be a number above 0"
    elif key in CHOICES and value not in CHOICES[key]:
        return "must be " + " or ".join(CHOICES[key])
    return None


def line_ending(line):
    return line[len(line.splitlines()[0]):]


def rewrite(raw, changes):
    """raw with each changed `key: value` line replaced, or added before the closing ---. Raises Refused(422)."""
    try:
        lines = raw.decode("utf-8").splitlines(keepends=True)  # the line split status.frontmatter sees
    except UnicodeDecodeError:
        raise Refused(422, "ROUTINE.md is not valid UTF-8")
    end = frontmatter_end(lines)
    if end is None:
        raise Refused(422, "the frontmatter needs a --- on line 1 and a closing ---")
    where = {}
    for i in range(1, end):
        key, sep, _ = lines[i].partition(":")
        if sep and key.strip() in FIELDS:
            if key.strip() in where:
                raise Refused(422, f"{key.strip()} appears on more than one line")
            where[key.strip()] = i
    added = []
    for key in FIELDS:
        if key not in changes:
            continue
        if key in where:
            i = where[key]
            lines[i] = f"{key}: {changes[key]}{line_ending(lines[i])}"
        else:
            eol = "\r\n" if lines[end - 1].endswith("\r\n") else "\n"
            added.append(f"{key}: {changes[key]}{eol}")
    lines[end:end] = added
    return "".join(lines).encode("utf-8")


def set_fields(path, changes, expected_sha):
    """Change frontmatter fields of the ROUTINE.md at path. Raises Refused with 400, 409 or 422; writes nothing then."""
    for key, value in changes.items():
        why = "is not an editable field" if key not in FIELDS else bad_value(key, value)
        if why:
            raise Refused(400, f"{key} {why}")
    raw, mode = read_file(path)
    new = rewrite(raw, changes)
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise Refused(409, "ROUTINE.md changed since the page was loaded; reload and try again")
    if new == raw:
        return

    def unchanged_since_read():
        # shortcut: a check-then-replace still has a window of microseconds; a lock file would close it.
        if read_file(path)[0] != raw:
            raise Refused(409, "ROUTINE.md changed while saving; nothing was written")

    write_atomic(path, new, mode, unchanged_since_read)


# --- server --------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    timeout = 10  # a connection that sends nothing for this long is dropped

    def log_message(self, *args):
        pass  # the request line carries the token

    def send_error(self, code, message=None, explain=None):
        self.reply(code, f"{code} {message or self.responses.get(code, ('error',))[0]}\n")

    def reply(self, code, text, kind="text/plain", location=None):
        data = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", f"{kind}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Security-Policy", POLICY)
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        if location:
            self.send_header("Location", location)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_GET(self):
        self.answer(self.show)

    def do_POST(self):
        self.answer(self.save)

    def answer(self, action):
        try:
            self.guard()
            action()
        except Refused as refusal:
            self.reply(refusal.code, f"{refusal.code} {refusal}\n")

    def guard(self):
        """Checks 1 and 2, for every GET and POST."""
        port = self.server.server_address[1]
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            raise Refused(403, "unexpected Host")
        self.route, _, query = self.path.partition("?")  # not urlsplit: "//x" would read as a host
        given = (parse_qs(query).get("t") or [""])[0]
        if not hmac.compare_digest(given.encode("utf-8"), self.server.token.encode("utf-8")):
            raise Refused(403, "missing or wrong token")

    def show(self):
        if self.route != "/":
            raise Refused(404, "not found")
        now = self.server.clock()
        self.reply(200, render(collect(self.server.home, now), now, self.server.token), "text/html")

    def save(self):
        if self.headers.get_content_type() != FORM:
            raise Refused(415, f"send {FORM}")
        length = self.headers.get("Content-Length", "")
        if not (length.isascii() and length.isdigit()):
            raise Refused(411, "Content-Length is required")
        if int(length) > MAX_BODY:
            raise Refused(413, f"the body may be at most {MAX_BODY} bytes")  # decided before reading it
        prefix = "/routine/"
        folders = {p.name: p for p in status.folders(self.server.home)}  # the id is only ever a key here
        folder = folders.get(unquote(self.route[len(prefix):])) if self.route.startswith(prefix) else None
        if folder is None:
            raise Refused(404, "no such routine")
        body = self.rfile.read(int(length))
        if len(body) < int(length):  # the client went away mid-body: a cut-off value must never reach the file
            raise Refused(400, "the body is shorter than Content-Length")
        try:
            fields = dict(parse_qsl(body.decode("utf-8"), keep_blank_values=True, errors="strict"))  # last one wins
        except ValueError:
            raise Refused(400, "the body is not valid form data")
        if set(fields) - set(FIELDS) - {"sha"}:
            raise Refused(400, "unknown field")
        if "sha" not in fields:
            raise Refused(400, "sha is missing")
        changes = {key: value.strip(" ") for key, value in fields.items() if key != "sha"}
        set_fields(folder / "ROUTINE.md", changes, fields["sha"])
        try:
            write_static(self.server.home, self.server.clock())
        except OSError:
            pass  # the snapshot is a convenience; the edit has already succeeded
        self.reply(303, "", location=f"/?t={self.server.token}")


def make_server(home, token, port=0, clock=datetime.now):
    server = HTTPServer(("127.0.0.1", port), Handler)
    server.home, server.token, server.clock = Path(home), token, clock
    return server


def serve(server, idle_seconds):
    idle = []
    server.timeout = idle_seconds
    server.handle_timeout = lambda: idle.append(True)  # one request at a time; no request for idle_seconds ends it
    try:
        while not idle:
            server.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv=None, now=None, opener=webbrowser.open):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--home", default=os.environ.get("ROUTINES_HOME", "~/.routines"))
    parser.add_argument("--no-open", action="store_true", help="do not open the browser")
    parser.add_argument("--serve", action="store_true", help="also serve the live page on 127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="port for --serve (default: any free port)")
    parser.add_argument("--idle-seconds", type=float, default=1800, help="--serve stops after this long without a request")
    args = parser.parse_args(argv)

    root = Path(args.home).expanduser()
    if not root.is_dir():
        print(f"No routines home at {root}; nothing to show.")
        return 0
    path = write_static(root, now or datetime.now())
    print(path)
    if not args.serve:
        if not args.no_open:
            opener(path.as_uri())
        return 0

    token = secrets.token_urlsafe(32)
    server = make_server(root, token, args.port, (lambda: now) if now else datetime.now)
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={token}"
    print(url, flush=True)
    try:
        if not args.no_open:
            opener(url)
        serve(server, args.idle_seconds)
    except KeyboardInterrupt:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
