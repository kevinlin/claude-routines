# QA procedure for the routines console

The same 69 checks as `console.feature` and `test_console_e2e.py`, for a person with a
browser, a terminal and `curl`. Each heading is a scenario ID. Run all of them, or the
group you care about. "Unchanged" always means the checksum listing (`snap`, below) is
identical before and after.

Needs: `python3` (3.9 or newer), `curl`, `shasum`, `nc`, a browser. Nothing here touches
`~/.routines`: every command names a throwaway home.

## Setup (once)

Run from the repo root.

```sh
CON=skills/routine/scripts/console.py
STA=skills/routine/scripts/status.py
TMP=$(mktemp -d)
MAIN=$(python3 tests/e2e/support.py make-fixture "$TMP/main")                  # the mixed home
EDGE=$(python3 tests/e2e/support.py make-fixture "$TMP/edge" --extras all)     # mixed home + edit and refusal files
snap() { find "$TMP" -type f -exec shasum -a 256 {} + | sort; }                # every file under both fixtures
python3 $STA --home "$MAIN"                                                    # the reference table
```

The mixed home has twelve routines (dates are relative to the moment you built it):

| id | what it is | flag |
|---|---|---|
| `never-run` | no run record | NEVER RUN |
| `needs-you` | latest record `needs-you` | NEEDS-YOU |
| `stalled` | latest record `running`, 5 h old | STALLED |
| `failed` | latest record `failed` | FAILED |
| `overdue` | last `done` 3 days ago, cadence 24 | OVERDUE |
| `done-clean` | latest `done` 45 min ago; an older record was `needs-you` | none |
| `paused` | `paused: true`, latest record `failed` | none (status `paused`) |
| `rich` | notes, seven records `RUNMARK-1` (oldest) to `RUNMARK-7`, `weekdays_only: true`, `runs_on: cloud` | none |
| `twin-a`, `twin-b` | both `name: Shared Name` | none |
| `folder-mismatch` | `name: Display Differs` | none |
| `hostile` | markup (`<script>alert(1)</script>`, `"><img ...>`) in name, purpose, schedule, notes, body, summary and run body | none |

Plus `_kit/` and `.hidden/` (each with a `ROUTINE.md`), `docs/` (none), and a loose `stray.md`. The edge home adds
`edit-lf`, `edit-crlf`, `edit-mixed`, `sparse`, `sparse-crlf` (editable), and `symlinked`, `no-close`, `no-open`, `dupe`
(not safe to edit).

Start two servers for the later sections, each in its own terminal, and note the URL each prints:

```sh
python3 $CON --serve --home "$MAIN" --no-open     # terminal A
python3 $CON --serve --home "$EDGE" --no-open     # terminal B
```

Then in your working terminal (fill in the ports and tokens from the printed URLs
`http://127.0.0.1:<port>/?t=<token>`):

```sh
PA=...; TA=...      # server A (main home)
PB=...; TB=...      # server B (edge home)
BASE=http://127.0.0.1:$PB; T=$TB                       # most edit checks use B
sha() { shasum -a 256 "$EDGE/$1/ROUTINE.md" | cut -d' ' -f1; }
post() { id=$1; body=$2; shift 2; curl -s -i -X POST --data "$body" "$@" "$BASE/routine/$id?t=$T"; }
```

`post <id> '<urlencoded body>' [curl options]` prints the whole response; add `| head -1` for the status line only.

## Snapshot

**CON-01** `python3 $CON --home "$MAIN" --no-open; echo "exit $?"`. Expect one line, the absolute path
of `$MAIN/console.html`, and `exit 0`. `snap` before and after differs only by the new `console.html`. No browser opens.

**CON-02** Open `$MAIN/console.html`. The status table has one row per line of `python3 $STA --home "$MAIN"`
(twelve), with the same name, status and flag on each row. No extra routine.

**CON-03** The FLAG column reads exactly `NEVER RUN`, `NEEDS-YOU`, `STALLED`, `FAILED`, `OVERDUE` on
`never-run`, `needs-you`, `stalled`, `failed`, `overdue`. The other seven rows, `paused` included, have no flag.

**CON-04** In the table, the five flagged rows are the first five.

**CON-05** Each row that has a last run in `status.py` shows that date in LAST RUN; each non-empty summary in
`status.py` is in SUMMARY.

**CON-06** `ls "$TMP"` and note it; `python3 $CON --home "$TMP/nope" --no-open; echo "exit $?"`. Expect exactly one
line of output, `exit 0`, no `$TMP/nope`, and `ls "$TMP"` unchanged.

**CON-07** `python3 $STA --home "$MAIN" > /tmp/before.txt`; run `console.py` twice; again `> /tmp/after.txt`;
`diff /tmp/before.txt /tmp/after.txt` is empty and `console.html` is not a row.

**CON-08** In `console.html` search (Cmd/Ctrl-F) for `_kit`, `.hidden`, `KIT-BODY`, `HIDDEN-BODY`, `DOCS-MARK`, `STRAY`: no hits.

**CON-09** `python3 $CON --home "$MAIN"` (no `--no-open`). The default browser opens `console.html`.

**CON-10** `python3 $CON --home "$EDGE" --no-open` exits 0. The table matches `python3 $STA --home "$EDGE"` and each of
`symlinked`, `no-close`, `no-open`, `dupe` shows the absolute path of its `ROUTINE.md`.

## Content (open `$MAIN/console.html`, and again the served page of A for CON-19)

**CON-11** For each routine the six fields show the file's values (`cat "$MAIN/rich/ROUTINE.md"`): `rich` shows
`RICH-PURPOSE-QWERTY`, `Weekdays 07:45 RICH-SCHEDULE`, `36.5`, `true`, `false`, `cloud`; `paused` shows `paused true`;
a routine with both booleans false shows no `true` anywhere in its section.

**CON-12** Each section shows its `BODY-MARK-<id> first line of the body` and `BODY-STEP-<id> second paragraph`.

**CON-13** `rich` shows `NOTES-MARK-rich keep it under ten lines` and `NOTES-LATER-rich second note`; no other section does.

**CON-14** `rich` lists records 7, 6, 5, 4, 3 in that order, each with status, started, ended, summary and body.
Search the page for `RUNMARK-2` and `RUNMARK-1`: no hits (check `ls "$MAIN/rich/runs"` shows seven files).
`done-clean` shows `DONECLEAN-BODY` above `DONECLEAN-OLD-BODY`.

**CON-15** The page shows when it was generated, within a minute of `date`. Every routine shows its absolute `ROUTINE.md` path.

**CON-16** Every routine has next to its `paused` field exactly: `Pausing here does not pause the task in Claude Desktop.`

**CON-17** `Answer this in the Claude session, not here.` appears once, in the `needs-you` section. Not in `done-clean`
(older record was needs-you), `rich`, `paused` or `failed`. Search the page: one hit.

**CON-18** `folder-mismatch` shows `Display Differs` and `folder-mismatch`; `twin-a` and `twin-b` each show `Shared Name`
and their own folder name apart from the path; `hostile` shows its name and the id `hostile`.

**CON-19** Open `http://127.0.0.1:$PA/?t=$TA`. Repeat CON-02 to CON-05 and CON-11 to CON-18 on this page.

## Escaping

**CON-20** In the snapshot, the `hostile` section and table row show, as plain text, `XSS-NAME <script>alert(1)</script>`,
`XSS-FM ... "><img src=x onerror=alert(1)> end`, `XSS-SCHED &lt;b&gt;already-escaped &amp; done ...`, `XSS-NOTES ...`,
`XSS-SUMMARY ...`, `XSS-RUNBODY ...`, `XSS-BODY ...`. No alert dialog, no broken image. View source: `grep -ci '<script' "$MAIN/console.html"` is 0
and so is `grep -ci '<img' "$MAIN/console.html"`.

**CON-21** The same on the served page of A. `curl -s "http://127.0.0.1:$PA/?t=$TA" | grep -ciE '<script|<img|<iframe'` is 0.
In the `hostile` form the purpose box shows the full text including the `"><img ...>` part and no image appears.

**CON-22** `curl -s "http://127.0.0.1:$PA/?t=$TA" "file://$MAIN/console.html" | grep -ciE '<script|javascript:|<iframe|<object|<embed|<[a-z]+[^>]* on[a-z]+='` is 0.
With the browser console open, no script runs and no CSP violation is reported for the page.

## Forms

**CON-23** `grep -ci '<form' "$MAIN/console.html"` is 0.

**CON-24** `curl -s "http://127.0.0.1:$PA/?t=$TA" | grep -o '<form[^>]*>'` prints twelve forms, each `method="post"` and
`action="/routine/<id>?t=$TA"` with a different id. Each form holds exactly `sha`, `purpose`, `schedule`, `cadence_hours`,
`weekdays_only`, `paused`, `runs_on`; its `sha` equals `shasum -a 256 "$MAIN/<id>/ROUTINE.md"`.

**CON-25** In the browser, press Save on each form without changing anything. Each time the page reloads (303 to `/?t=...`)
and `snap` shows no `ROUTINE.md` changed.

## Serve

**CON-26** Start `python3 $CON --serve --home "$MAIN" --no-open` in a terminal. The line with the path of `console.html`
and then `http://127.0.0.1:<port>/?t=<43 characters>` appear at once (not on exit). Start a second one: another port and token.

**CON-27** `python3 $CON --serve --home "$MAIN" --no-open --port 8765` prints a URL with port 8765.

**CON-28** `lsof -nP -iTCP -sTCP:LISTEN | grep <port>` shows `127.0.0.1:<port>` and no `*:<port>`.
`curl --max-time 3 http://$(ipconfig getifaddr en0):<port>/` (or the machine's LAN address) and `curl --max-time 3 http://127.0.0.2:<port>/` fail.

**CON-29** `python3 $CON --serve --home "$MAIN"` without `--no-open` opens the printed URL in the browser.

## Auth (A = main home server, B = edge home server)

**CON-30** Every one of these is `403` with no routine content, and the last one is `200`:
```sh
for q in '' '?t=' '?t=wrong' "?t=$TB" "?t=${TA}x" "?t=${TA%?}" "?T=$TA" "?token=$TA" "?t=$TA"; do
  printf '%-30s' "/$q"; curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:$PA/$q"; done
```

**CON-31** `snap > /tmp/b.txt`, then for each of no query, `t=`, `t=wrong`, `t=$TA` (B's own token is the right one,
so A's is the foreign one), `t=${TB}x`, `t=${TB%?}`:
`curl -s -o /dev/null -w '%{http_code}\n' -X POST --data "sha=$(sha edit-lf)&paused=true" "$BASE/routine/edit-lf?<query>"` prints `403`;
`snap | diff /tmp/b.txt -` is empty.

**CON-32** The token only counts as the query parameter `t`. Each of these has no query and is `403`, and `snap` is unchanged:
`curl -s -o /dev/null -w '%{http_code}\n' -X POST --data "sha=$(sha edit-lf)&paused=true&t=$T" "$BASE/routine/edit-lf"` (token in the body), and the same
with `-H "Authorization: Bearer $T"`, `-H "X-Token: $T"` or `-H "Cookie: t=$T"` instead of `t=` in the body. Also `curl -s -o /dev/null -w '%{http_code}\n' -H "Cookie: t=$T" $BASE/` is `403`.

**CON-33** With the valid token: `curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: evil.example' "$BASE/?t=$T"` is `403`; the same for
`Host: 127.0.0.1`, `Host: localhost`, `Host: 127.0.0.1:$((PB+1))`, `Host: localhost:$((PB+1))`, `Host: 127.0.0.1.evil.example:$PB`, `Host: [::1]:$PB`,
and for a POST of a valid edit (nothing changes). `curl -si --http1.0 -H 'Host:' "$BASE/?t=$T"` is `403`.
`-H "Host: 127.0.0.1:$PB"` and `-H "Host: localhost:$PB"` are `200`.

**CON-34** `curl -s -o /dev/null -w '%{http_code}\n' "$BASE/<path>?t=$T"` is `404` for `index.html`, `console.html`, `routine/done-clean`, `favicon.ico`, `%2e%2e/etc/passwd`, `routine/`.

## Edit (edge home, server B)

Keep a copy: `cp "$EDGE/edit-lf/ROUTINE.md" /tmp/edit-lf.orig`.

**CON-35** `post edit-lf "sha=$(sha edit-lf)&paused=true" | head -4` shows `303` and `Location: /?t=$T`.
`diff /tmp/edit-lf.orig "$EDGE/edit-lf/ROUTINE.md"` shows one changed line, `paused: false` to `paused: true`. The body lines
`purpose: body text, not frontmatter` and `paused: true`, the comment `# paused: true (old value, kept for reference)`, the keys `owner`, `paused_until`,
`note`, and the missing final newline are untouched. `snap` differs only in that file and `console.html`.
`grep -ci '<form' "$EDGE/console.html"` is 0 and its `edit-lf` row says `paused` with no flag. Reload B's page: same, and the
`edit-lf` form's `sha` equals `sha edit-lf`.

**CON-36** `cp "$EDGE/edit-crlf/ROUTINE.md" /tmp/crlf.orig; post edit-crlf "sha=$(sha edit-crlf)&purpose=New+purpose&paused=true" | head -1`.
`diff /tmp/crlf.orig "$EDGE/edit-crlf/ROUTINE.md"` shows two lines, and `grep -c $'\r' ` is the same before and after (every line still ends in CRLF).
Repeat on `edit-mixed` with `purpose`, `weekdays_only=true`, `paused=true`: `purpose` and `weekdays_only` keep a bare LF, `paused` keeps CRLF, there is
still no final newline.

**CON-37** `chmod 640 "$EDGE/edit-lf/ROUTINE.md"`, post a `paused` change (use the current `sha`), `ls -l` still shows `-rw-r-----`.
Same with `chmod 600` on `edit-crlf`.

**CON-38** `ln "$EDGE/edit-lf/ROUTINE.md" "$TMP/keeper.md"; cp "$TMP/keeper.md" /tmp/keeper.orig`, post a `paused` change.
`cmp "$TMP/keeper.md" /tmp/keeper.orig` is identical (old inode untouched), `ls -i` shows different inode numbers, `ls -a "$EDGE/edit-lf"` shows only `ROUTINE.md`.
A refused post (`sha=000...`) leaves the folder listing the same.

**CON-39** One post per field, using the current `sha` each time, and `diff` shows exactly that line:
`purpose=W%C3%B6chentlicher+Bericht+%E2%80%94+%E9%80%B1%E5%A0%B1`, `schedule=Mondays+09%3A00+sharp`, `cadence_hours=36.50` (written as `36.50`, not `36.5`),
`weekdays_only=true`, `paused=true`, `runs_on=cloud`. Then on `edit-crlf` one post with all six.

**CON-40** `post edit-lf "sha=$(sha edit-lf)&purpose=first&purpose=%20%20last%20wins%20%20&schedule=+++padded+++"` writes `purpose: last wins`
and `schedule: padded`, and nothing else. Then `paused=maybe&paused=true` is `303` and writes `paused: true`;
`paused=false&paused=maybe` is `400`.

**CON-41** `purpose=it%27s+a+%22fine%22+day&schedule=Mondays+09%3A00+%23+not+a+comment%3A+ok` is `303`; the file holds
`purpose: it's a "fine" day` and `schedule: Mondays 09:00 # not a comment: ok`.

**CON-42** `post sparse "sha=$(sha sparse)&paused=true"`: `paused: true` is the line right before the closing `---`, after the comment.
Then `runs_on=cloud&cadence_hours=12`: both lines sit between `paused: true` and `---`. `post sparse-crlf ...&paused=true`: the new line ends in CRLF (`grep -c $'\r'` equals the line count).

**CON-43** `post twin-b "sha=$(sha twin-b)&purpose=Only+twin+b+changed"` changes only `twin-b/ROUTINE.md` (`snap` diff). `post twin-a "sha=$(sha twin-b)&purpose=x"` is `409`.
`post twin-a "sha=$(sha twin-a)&paused=true"` changes only `twin-a`.

**CON-44** Build a body of exactly 16384 bytes and post it:
```sh
S=$(sha edit-lf); n=$((16384 - ${#S} - 4 - 1 - 8)); body="sha=$S&purpose=$(head -c $n /dev/zero | tr '\0' x)"; echo ${#body}   # 16384
post edit-lf "$body" | head -1                                                          # 303
```

## Refusals (each: `snap > /tmp/b.txt` before, `snap | diff /tmp/b.txt -` empty after)

**CON-45** `S=$(sha edit-lf); echo extra >> "$EDGE/edit-lf/ROUTINE.md"; post edit-lf "sha=$S&paused=true" | head -1` is `409`.
Also `sha=0000000000000000000000000000000000000000000000000000000000000000` and `sha=not-a-sha`: `409`.
With `sha=$(sha edit-lf)` it is `303`.

**CON-46** For `purpose` and `schedule`, `post edit-lf "sha=$(sha edit-lf)&purpose=a%0Ab" | head -1` is `400`; repeat with `%0D %0B %0C %1C %1D %1E %C2%85 %E2%80%A8 %E2%80%A9` in place of `%0A`.

**CON-47** `400` for `purpose` (and `schedule`) = `%22quoted%22`, `%27quoted%27`, `%22start`, `end%22`, `%27start`, `end%27`, `++%22padded%22++`, `++%27padded%27++`.

**CON-48** `400` for `cadence_hours` = `0`, `0.0`, `-1`, `-0.5`, `inf`, `-inf`, `%2Binf`, `nan`, `NaN`, `Infinity`, `abc`, empty, `1e999`, `12h`.

**CON-49** `400` for `paused` and for `weekdays_only` = `True`, `TRUE`, `False`, `yes`, `no`, `1`, `0`, `on`, empty. `400` for `runs_on` = `Cloud`, `CLOUD`, `local`, `desktop`, `desktop_local`, `laptop`, empty.

**CON-50** `400` for `sha=..&bogus=1`, `&name=Other`, `&Paused=true`, `&paused_until=x`, and `&paused=true&extra=x` (and `paused` stays `false`).

**CON-51** `post edit-lf 'paused=true' | head -1` is `400`; `post edit-lf '' | head -1` is `400`.

**CON-52** `post edit-lf "sha=$(sha edit-lf)&purpose=fine&schedule=Daily&paused=maybe"` is `400` and `purpose` and `schedule` keep their old values.

**CON-53** `ls -l "$EDGE/symlinked/ROUTINE.md"` shows a symlink to `$TMP/edge/elsewhere/real-routine.md`. `post symlinked "sha=$(sha symlinked)&paused=true" | head -1` is `422`;
it is still a symlink and the target is unchanged.

**CON-54** `post no-close "sha=$(sha no-close)&paused=true" | head -1` and the same for `no-open`: `422`.

**CON-55** `post dupe "sha=$(sha dupe)&schedule=Hourly" | head -1` and `...&paused=true`: `422`.

**CON-56** `post does-not-exist 'sha=0&paused=true' | head -1`, `post Done-Clean ...`, `post done-clea ...`: `404`.

**CON-57** Send raw targets with `--path-as-is`; the folder beside the home is `$TMP/edge/outside` (`shasum` it before and after):
```sh
for id in ../outside ..%2Foutside %2e%2e%2Foutside %2E%2E/outside .. 'done-clean/../done-clean' 'done-clean%2F..%2Fdone-clean' ../outside/ROUTINE.md; do
  curl -s -o /dev/null -w "$id %{http_code}\n" --path-as-is -X POST --data "sha=0&paused=true" "$BASE/routine/$id?t=$T"; done
```
All `404`.

**CON-58** `404` for `_kit`, `.hidden`, `docs`, `console.html`, `stray.md`, `runs`; `_kit/ROUTINE.md` and `.hidden/ROUTINE.md` unchanged.

**CON-59** `curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'Content-Type: application/json' --data "sha=$(sha edit-lf)&paused=true" "$BASE/routine/edit-lf?t=$T"` is `415`;
same with `text/plain`, `multipart/form-data; boundary=x`, `text/html`, and with `-H 'Content-Type:'` (header removed).

**CON-60** Raw requests (curl would add the length):
```sh
for h in '' 'Content-Length: abc\r\n' 'Content-Length: 12x\r\n' 'Transfer-Encoding: chunked\r\n'; do
  printf "POST /routine/edit-lf?t=$T HTTP/1.0\r\nHost: 127.0.0.1:$PB\r\nContent-Type: application/x-www-form-urlencoded\r\n${h}\r\n" \
    | nc -w 3 127.0.0.1 $PB | head -1; done
```
Every line is `HTTP/1.0 411 ...`.

**CON-61** Same raw form with `Content-Length: 16385\r\n` (also `100000`, `1000000000000`) and no body: `HTTP/1.0 413 ...` arrives at once, not after a timeout.

**CON-62** Combine two defects and check the first-listed one wins. Raw examples (statuses in brackets):
wrong token with `Content-Type: application/json` and unknown id [403]; `Host: evil.example` with a wrong content type [403];
wrong content type with no length [415]; wrong content type with unknown id [415]; wrong content type with length 99999 [415];
no length with unknown id [411]; length 99999 with unknown id [413]; unknown id with unknown field [404];
`symlinked` with an unknown field [400]; `symlinked` without `sha` [400]; `dupe` without `sha` [400];
`symlinked` with `paused=maybe` [400]; `no-close` with `paused=maybe` [400]; `edit-lf` with `sha=000..0&paused=maybe` [400];
`symlinked` with `sha=000..0&paused=true` [422]; `dupe` with `sha=000..0&paused=true` [422]; `edit-lf` with `sha=000..0&paused=true` [409].

## Headers

**CON-63** `curl -si "$BASE/?t=$T" | sed -n '1,/^\r$/p'` and the headers of a successful `post` both contain, exactly:
`Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; form-action 'self'`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`.

**CON-64** The same three headers on a `403` (`curl -si "$BASE/"`), a `404` (`curl -si "$BASE/nope?t=$T"`), `400`, `409`, `415`, `422`, `411` and `413` responses from the sections above.

**CON-65** `grep -i 'http-equiv' "$MAIN/console.html"` shows one `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; form-action 'self'">`.

## Lifecycle

**CON-66** `time python3 $CON --serve --home "$MAIN" --no-open --idle-seconds 2`, send nothing. It prints the URL, still runs at first, exits about 2 s later,
`echo $?` is `0`, and the port no longer accepts connections.

**CON-67** `python3 $CON --serve ... --idle-seconds 5`. After 3 s `curl` the URL (200). It must still be running 3.5 s after that (past the original 5 s), then exit `0` about 5 s after the request.

**CON-68** Start `python3 $CON --serve --home "$MAIN" --no-open`, press Ctrl-C: it stops and `echo $?` is `0`.

**CON-69** Terminal 1: `sleep 30 | nc 127.0.0.1 $PA` (keeps the connection open and sends nothing). Terminal 2, right away:
`time curl -si --max-time 25 "http://127.0.0.1:$PA/?t=$TA" | head -1`.
The curl waits (no answer while terminal 1 holds the connection); about 10 s after `nc` was opened the server drops it, and curl then prints `HTTP/1.0 200 OK`
after roughly 10 s (`time` shows 8 to 14 s).

## Clean up

Stop both servers (Ctrl-C), then `rm -rf "$TMP"`.
