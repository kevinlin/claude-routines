Feature: The routines console
  Kevin can see every routine's status, config, notes and recent runs in one page,
  and change a frontmatter field without opening the file, and nothing but his own
  form can write to his routine files.

  Executable in tests/e2e/test_console_e2e.py: one test method per scenario,
  test_con_NN_* for @CON-NN. Fixture and launch code are in tests/e2e/support.py.

  Background:
    Given a routines home built by the fixture with these routines
      | id              | what it is                                                          |
      | never-run       | not paused, no run record                                           |
      | needs-you       | latest record needs-you                                             |
      | stalled         | latest record running, started 5 hours ago                          |
      | failed          | latest record failed                                                |
      | overdue         | latest record done 3 days ago, cadence_hours 24                     |
      | done-clean      | latest record done 45 minutes ago, an older record was needs-you    |
      | paused          | paused: true, latest record failed                                  |
      | rich            | notes.md, seven run records told apart by RUNMARK-1..7, weekdays_only true, runs_on cloud |
      | twin-a          | frontmatter name "Shared Name"                                      |
      | twin-b          | frontmatter name "Shared Name"                                      |
      | folder-mismatch | frontmatter name "Display Differs"                                  |
      | hostile         | markup in its name, purpose, schedule, notes, body, summary and run body |
    And the folders _kit and .hidden hold a ROUTINE.md, and docs holds none
    And every console.py process runs with --home pointing at a temp directory and with --no-open unless a scenario says otherwise

  # ------------------------------------------------------------------ snapshot

  @CON-01
  Scenario: The snapshot is written where promised and nothing else changes
    When I run console.py with that home
    Then it exits 0
    And stdout is one line, the absolute path of <home>/console.html
    And the home holds the same files as before plus console.html
    And no routine file changed
    And no browser was launched

  @CON-02
  Scenario: The snapshot lists the same routines, statuses and flags as status.py
    When I run console.py with that home
    And I run status.py --home with the same home
    Then the page's status table has one row for every row status.py prints
    And each row has the same display name, status and flag
    And the page lists no routine status.py does not

  @CON-03
  Scenario: Each flag is shown as its text label
    When I run console.py with that home
    Then the flag column reads NEVER RUN, NEEDS-YOU, STALLED, FAILED and OVERDUE for exactly the five routines built for them
    And the other seven routines, the paused one included, show no flag

  @CON-04
  Scenario: Flagged routines come before unflagged ones
    When I run console.py with that home
    Then every flagged row of the status table comes before every unflagged row

  @CON-05
  Scenario: Each row shows the last run and the summary
    When I run console.py with that home
    Then every routine with a last run in status.py shows that run's date in the last-run column
    And every routine with a summary in status.py shows it in the summary column

  @CON-06
  Scenario: A missing home creates nothing and exits 0
    Given a home path that does not exist
    When I run console.py with that path
    Then it exits 0
    And it prints a single line
    And neither the home nor anything beside it was created
    And no browser was launched

  @CON-07
  Scenario: status.py lists the same routines after console.html exists
    Given status.py has printed its table for the home
    When console.py has written console.html, twice
    Then status.py prints exactly the same table
    And console.html is not listed as a routine

  @CON-08
  Scenario: Folders that are not routines are not listed
    When I run console.py with that home
    Then nothing from _kit, .hidden, docs or the loose file in the home appears in the page
    And the status table has twelve rows

  @CON-09
  Scenario: The snapshot is opened in the browser unless --no-open
    When I run console.py with that home and without --no-open
    Then the browser is asked to open console.html

  @CON-10
  Scenario: Routines whose frontmatter cannot be edited safely are still listed
    Given the home also holds routines with a symlinked ROUTINE.md, no closing marker, no opening marker and a duplicated key
    When I run console.py with that home
    Then it exits 0
    And the table matches status.py
    And each of the four shows the absolute path of its ROUTINE.md

  # ------------------------------------------------------------------- content

  @CON-11
  Scenario: Each routine shows its six field values
    When I run console.py with that home
    Then each routine's section shows its purpose, schedule, cadence_hours, weekdays_only, paused and runs_on as written in the file
    And a routine whose weekdays_only and paused are both false shows no "true"

  @CON-12
  Scenario: Each routine shows its ROUTINE.md body
    When I run console.py with that home
    Then each routine's section shows the two body lines written for it

  @CON-13
  Scenario: Notes are shown
    When I run console.py with that home
    Then the section of rich shows both lines of its notes.md
    And no other routine's section shows them

  @CON-14
  Scenario: The newest five run records are shown, newest first
    When I run console.py with that home
    Then rich shows records 7, 6, 5, 4 and 3 in that order
    And each shows its started, ended and summary and its body
    And records 2 and 1 appear nowhere on the page
    And done-clean shows both of its records, newest first

  @CON-15
  Scenario: The generation time and each ROUTINE.md path are shown
    When I run console.py with that home
    Then the page shows a date-time within a minute of now
    And it shows the absolute path of every listed ROUTINE.md

  @CON-16
  Scenario: The paused sentence sits next to the paused field
    When I run console.py with that home
    Then "Pausing here does not pause the task in Claude Desktop." appears word for word in every routine's section
    And it is within three elements of the text "paused"

  @CON-17
  Scenario: The needs-you sentence is shown only for a waiting routine
    When I run console.py with that home
    Then "Answer this in the Claude session, not here." appears word for word exactly once, in the section of needs-you
    And it does not appear for done-clean, whose older record was needs-you, nor for rich, paused or failed

  @CON-18
  Scenario: Display name and id are both shown when they differ
    When I run console.py with that home
    Then for folder-mismatch, twin-a, twin-b and hostile the page shows the display name
    And it shows the folder name as text apart from any path

  @CON-19
  Scenario: The served page has the same content as the snapshot
    Given a running server
    When I fetch the page with the token
    Then it passes the table, field, body, notes, record, time, path, sentence and name checks of CON-02 to CON-18

  # ------------------------------------------------------------------ escaping

  @CON-20
  Scenario: Hostile text is escaped in the snapshot
    When I run console.py with that home
    Then the page source has no script, img or iframe tag and no on* attribute
    And the name, purpose, schedule, notes, body, summary and run body of hostile show as visible text, exactly as written

  @CON-21
  Scenario: Hostile text is escaped in the served page
    Given a running server
    When I fetch the page with the token
    Then the same holds, with attribute values counting as text, so a quote cannot break out of a form field

  @CON-22
  Scenario: The page contains no JavaScript
    Given a running server
    Then neither the snapshot nor the served page has a script tag, an on* attribute, a javascript: URL, an iframe, an object or an embed

  # --------------------------------------------------------------------- forms

  @CON-23
  Scenario: The snapshot has no form
    When I run console.py with that home
    Then console.html contains no form element

  @CON-24
  Scenario: The served page has one form per routine
    Given a running server
    When I fetch the page with the token
    Then there are twelve forms, one per folder name, each method post to /routine/<id>?t=<token>
    And each form's named controls are exactly sha, purpose, schedule, cadence_hours, weekdays_only, paused and runs_on
    And each form's sha is the sha256 of that routine's ROUTINE.md

  @CON-25
  Scenario: Submitting a served form unchanged is accepted and changes nothing
    Given a running server
    When I submit each form as a browser would, without editing it
    Then each form's values equal the file's six values
    And every answer is 303 with Location /?t=<token>
    And no ROUTINE.md changes

  # --------------------------------------------------------------------- serve

  @CON-26
  Scenario: --serve prints the URL line and writes the snapshot first
    When I start console.py --serve
    Then stdout has the path of console.html and then a line that is exactly http://127.0.0.1:<port>/?t=<token>
    And the line arrives without waiting for the process to exit
    And the token is 43 URL-safe characters
    And console.html exists by then
    And a second server gets another port and another token
    And no browser was launched

  @CON-27
  Scenario: --serve honours --port
    When I start console.py --serve --port N with a free port N
    Then the URL names port N

  @CON-28
  Scenario: The server listens on loopback only
    Given a running server
    Then 127.0.0.1 connects
    And no other address of this machine, 127.0.0.2 or ::1 connects to that port

  @CON-29
  Scenario: --serve opens the URL unless --no-open
    When I start console.py --serve without --no-open
    Then the browser is asked to open the printed URL

  # ---------------------------------------------------------------------- auth

  @CON-30
  Scenario Outline: A GET without or with a wrong token is 403
    Given two running servers A and B
    When I GET <target> from A
    Then the answer is 403 and the body holds no routine content
    And GET /?t=<A's token> from A is 200

    Examples:
      | target                  |
      | /                       |
      | /?t=                    |
      | /?t=wrong               |
      | /?t=<B's token>         |
      | /?t=<A's token>x        |
      | /?t=<A's token minus 1> |
      | /?T=<A's token>         |
      | /?token=<A's token>     |

  @CON-31
  Scenario Outline: A POST without or with a wrong token is 403 and writes nothing
    Given two running servers A and B
    When I POST a valid edit of edit-lf to A with the query <query>
    Then the answer is 403
    And nothing under the home changed

    Examples:
      | query           |
      | (none)          |
      | t=              |
      | t=wrong         |
      | t=<B's token>   |
      | t=<A's token>x  |
      | t=<A's token minus 1> |

  @CON-32
  Scenario: The token is only read from the query parameter t
    Given a running server
    When the token is sent in the form body, in Authorization, in X-Token or in a Cookie instead of the query
    Then POST is 403 and nothing changed
    And GET with the token in a header is 403

  @CON-33
  Scenario Outline: A foreign Host is 403 and local hosts are accepted
    Given a running server on port P
    When I send a request with the valid token and Host <host>
    Then GET and POST are 403 and nothing changed, for each foreign host
    And a request without any Host header is 403
    And Host 127.0.0.1:P and localhost:P get 200

    Examples:
      | host                           |
      | evil.example                   |
      | evil.example:P                 |
      | 127.0.0.1                      |
      | 127.0.0.1:P+1                  |
      | localhost                      |
      | localhost:P+1                  |
      | 127.0.0.1.evil.example:P       |
      | [::1]:P                        |

  @CON-34
  Scenario Outline: Any other GET path is 404
    Given a running server
    When I GET <path> with the valid token
    Then the answer is 404

    Examples:
      | path                  |
      | /index.html           |
      | /console.html         |
      | /routine/done-clean   |
      | /favicon.ico          |
      | /%2e%2e/etc/passwd    |
      | /routine/             |

  # ---------------------------------------------------------------------- edit

  @CON-35
  Scenario: A paused round trip changes that line only
    Given edit-lf has a comment "# paused: true (...)", the unknown keys owner, paused_until and note, and body lines "purpose: ..." and "paused: true" after the closing marker
    And a running server
    When I POST sha and paused=true to /routine/edit-lf?t=<token>
    Then the answer is 303 with Location /?t=<token>
    And only the line "paused: false" of ROUTINE.md became "paused: true"
    And of everything under the fixture only that file and console.html changed
    And the refreshed console.html has no form and shows edit-lf with status paused and no flag
    And the served page shows the same and the form's sha is the new sha256

  @CON-36
  Scenario: CRLF and mixed line endings are kept
    Given edit-crlf uses CRLF everywhere and edit-mixed mixes CRLF and LF and has no final newline
    And a running server
    When I change purpose and paused, and for edit-mixed also weekdays_only
    Then only those lines changed, each keeping its own ending
    And the count of CRLF and of LF in the file is unchanged

  @CON-37
  Scenario: Permission bits are kept
    Given ROUTINE.md files with mode 0640 and 0600
    And a running server
    When I change paused in each
    Then each file keeps its mode

  @CON-38
  Scenario: The file is replaced atomically
    Given a second hard link to ROUTINE.md outside the routine folder
    And a running server
    When I change paused
    Then ROUTINE.md has a new inode and the old link still holds the old bytes
    And the routine folder holds the same file names as before
    And a refused request leaves the same names too

  @CON-39
  Scenario Outline: Each of the six fields can be changed
    Given a running server
    When I POST sha and <field>=<value>
    Then the answer is 303 and only that line changed to "<field>: <value>"
    And all six fields in one request change all six lines

    Examples:
      | field         | value                          |
      | purpose       | Wöchentlicher Bericht — 週報     |
      | schedule      | Mondays 09:00 sharp            |
      | cadence_hours | 36.50                          |
      | weekdays_only | true                           |
      | paused        | true                           |
      | runs_on       | cloud                          |

  @CON-40
  Scenario: Values are stripped and the last duplicate wins
    Given a running server
    When I POST purpose=first and purpose="   last wins  " and schedule="   padded  "
    Then the lines read "purpose: last wins" and "schedule: padded"
    When I POST paused=maybe and then paused=true
    Then paused becomes true
    When I POST paused=false and then paused=maybe
    Then the answer is 400 and nothing changed

  @CON-41
  Scenario: Quotes inside a value are kept
    Given a running server
    When I POST purpose=`it's a "fine" day` and schedule=`Mondays 09:00 # not a comment: ok`
    Then both lines are written exactly so

  @CON-42
  Scenario: A missing key is added before the closing marker
    Given sparse has only name and purpose, and a comment just before the closing marker
    And a running server
    When I POST paused=true
    Then "paused: true" is the line directly before the closing marker
    When I then POST runs_on=cloud and cadence_hours=12
    Then both new lines are directly before the closing marker, in either order
    And in a CRLF file the added line ends in CRLF

  @CON-43
  Scenario: Same display name, only the addressed folder changes
    Given twin-a and twin-b share the display name "Shared Name"
    And a running server
    When I POST to /routine/twin-b
    Then only twin-b's ROUTINE.md changed
    And a POST to twin-a with twin-b's sha is 409
    And a POST to twin-a then leaves twin-b alone

  @CON-44
  Scenario: A body of exactly the size limit is accepted
    Given a running server
    When I POST a form body of exactly 16384 bytes with a long purpose
    Then the answer is 303 and the purpose line holds the whole value

  # ------------------------------------------------------------------ refusals
  # Every refusal below also leaves every file under the fixture, console.html included,
  # byte-identical.

  @CON-45
  Scenario: A stale sha is 409
    Given a running server
    And ROUTINE.md changed on disk after the page was read
    When I POST with the old sha, with 64 zeros, or with "not-a-sha"
    Then each answer is 409
    And a POST with the current sha is then accepted

  @CON-46
  Scenario Outline: A line separator inside a value is 400
    Given a running server
    When I POST purpose or schedule as "a<separator>b"
    Then the answer is 400

    Examples:
      | separator        |
      | \n               |
      | \r               |
      | \v               |
      | \f               |
      | \x1c             |
      | \x1d             |
      | \x1e             |
      | \x85             |
      | U+2028           |
      | U+2029           |

  @CON-47
  Scenario Outline: A quote at either end of a value is 400
    Given a running server
    When I POST purpose or schedule as <value>
    Then the answer is 400

    Examples:
      | value         |
      | "quoted"      |
      | 'quoted'      |
      | "start        |
      | end"          |
      | 'start        |
      | end'          |
      |   "padded"    |
      |   'padded'    |

  @CON-48
  Scenario Outline: A cadence_hours that is not a finite number above 0 is 400
    Given a running server
    When I POST cadence_hours=<value>
    Then the answer is 400

    Examples:
      | value                                        |
      | 0                                            |
      | 0.0                                          |
      | -1                                           |
      | -0.5                                         |
      | inf                                          |
      | -inf                                         |
      | +inf                                         |
      | nan                                          |
      | NaN                                          |
      | Infinity                                     |
      | abc                                          |
      | (empty)                                      |
      | 1e999                                        |
      | 12h                                          |

  @CON-49
  Scenario: paused, weekdays_only and runs_on accept only their exact values
    Given a running server
    When I POST paused or weekdays_only as True, TRUE, False, yes, no, 1, 0, on or empty
    Or runs_on as Cloud, CLOUD, local, desktop, desktop_local, laptop or empty
    Then every answer is 400

  @CON-50
  Scenario: An unknown field is 400
    Given a running server
    When I POST sha plus bogus, name, Paused, paused_until, or a valid field together with an extra one
    Then every answer is 400

  @CON-51
  Scenario: A missing sha is 400
    Given a running server
    When I POST valid fields without sha, and an empty body
    Then both answers are 400

  @CON-52
  Scenario: One bad field refuses the whole request
    Given a running server
    When I POST valid purpose and schedule together with paused=maybe
    Then the answer is 400 and purpose and schedule are unchanged

  @CON-53
  Scenario: A symlinked ROUTINE.md is 422
    Given symlinked/ROUTINE.md is a symlink to a file outside the home
    And a running server
    When I POST a valid edit with the target's sha
    Then the answer is 422
    And the symlink is still a symlink and its target is unchanged

  @CON-54
  Scenario Outline: Missing frontmatter markers are 422
    Given <routine> has <defect>
    And a running server
    When I POST a valid edit with the file's sha
    Then the answer is 422

    Examples:
      | routine  | defect                                       |
      | no-close | an opening --- on line 1 and no closing ---  |
      | no-open  | a blank line 1 and --- only on line 2        |

  @CON-55
  Scenario: A duplicated key is 422
    Given dupe has two schedule lines in its frontmatter
    And a running server
    When I POST a change to schedule, and a change to paused
    Then both answers are 422

  @CON-56
  Scenario: An unknown id is 404
    Given a running server
    When I POST to /routine/does-not-exist, /routine/Done-Clean and /routine/done-clea
    Then every answer is 404

  @CON-57
  Scenario Outline: An id with ../ is 404
    Given a ROUTINE.md in a folder beside the home
    And a running server
    When I POST to /routine/<id>
    Then the answer is 404
    And the folder beside the home is unchanged

    Examples:
      | id                           |
      | ../outside                   |
      | ..%2Foutside                 |
      | %2e%2e%2Foutside             |
      | %2E%2E/outside               |
      | ..                           |
      | done-clean/../done-clean     |
      | done-clean%2F..%2Fdone-clean |
      | ../outside/ROUTINE.md        |

  @CON-58
  Scenario Outline: A folder that is not listed is 404
    Given a running server
    When I POST to /routine/<id>
    Then the answer is 404
    And _kit/ROUTINE.md and .hidden/ROUTINE.md are unchanged

    Examples:
      | id           |
      | _kit         |
      | .hidden      |
      | docs         |
      | console.html |
      | stray.md     |
      | runs         |

  @CON-59
  Scenario Outline: A content type that is not form-encoded is 415
    Given a running server
    When I POST a valid body with Content-Type <type>
    Then the answer is 415

    Examples:
      | type                             |
      | application/json                 |
      | text/plain                       |
      | multipart/form-data; boundary=x  |
      | text/html                        |
      | (no Content-Type header)         |

  @CON-60
  Scenario Outline: A missing or non-numeric Content-Length is 411
    Given a running server
    When I POST with <length>
    Then the answer is 411

    Examples:
      | length                                    |
      | no Content-Length                         |
      | Content-Length: abc                       |
      | Content-Length: 12x                       |
      | Transfer-Encoding: chunked, no length     |

  @CON-61
  Scenario Outline: An oversize Content-Length is 413 before the body is read
    Given a running server
    When I send the headers of a POST with Content-Length <length> and then no body
    Then the answer is 413 within five seconds

    Examples:
      | length        |
      | 16385         |
      | 100000        |
      | 1000000000000 |

  @CON-62
  Scenario Outline: The checks run in the documented order
    Given a running server
    When I POST a request that fails both <first> and <second>
    Then the answer is <status>
    And nothing changed

    Examples:
      | first                | second                      | status |
      | token                | content type, id, field     | 403    |
      | host                 | content type                | 403    |
      | content type         | content length              | 415    |
      | content type         | id                          | 415    |
      | content type         | size                        | 415    |
      | content length       | id                          | 411    |
      | size                 | id                          | 413    |
      | id                   | field                       | 404    |
      | field                | file state                  | 400    |
      | sha missing          | file state                  | 400    |
      | sha missing          | duplicate key               | 400    |
      | bad value            | symlink                     | 400    |
      | bad value            | missing closing marker      | 400    |
      | bad value            | stale sha                   | 400    |
      | symlink              | stale sha                   | 422    |
      | duplicate key        | stale sha                   | 422    |
      | stale sha            | (nothing else)              | 409    |

  # ------------------------------------------------------------------- headers

  @CON-63
  Scenario: The three response headers are on success responses
    Given a running server
    When I GET the page and POST a valid edit
    Then the 200 and the 303 both carry
      | Content-Security-Policy | default-src 'none'; style-src 'unsafe-inline'; form-action 'self' |
      | Referrer-Policy         | no-referrer                                                          |
      | Cache-Control           | no-store                                                             |

  @CON-64
  Scenario: The three response headers are on refusals
    Given a running server
    When I trigger a 403 (no token, foreign host, wrong token), a 404 (path and id), 400, 409, 415, 422, 411 and 413
    Then each response carries the same three headers

  @CON-65
  Scenario: The snapshot carries the CSP in a meta tag
    When I run console.py with that home
    Then console.html has exactly one meta http-equiv="Content-Security-Policy" whose content is the same policy

  # ----------------------------------------------------------------- lifecycle

  @CON-66
  Scenario: The server exits by itself after --idle-seconds
    When I start console.py --serve --idle-seconds 2 and send no request
    Then it is still running right after the URL line
    And it exits with code 0 within 20 seconds and not before one second
    And its port no longer accepts connections

  @CON-67
  Scenario: A request resets the idle timer
    When I start console.py --serve --idle-seconds 5
    And I send a request after 3 seconds
    Then the process is still running 3.5 seconds after that request
    And it exits with code 0 later

  @CON-68
  Scenario: Ctrl-C exits 0
    Given a running server
    When I send SIGINT
    Then it exits with code 0 within 10 seconds

  @CON-69
  Scenario: A stalled request is dropped after 10 seconds and requests are handled one at a time
    Given a running server
    And a connection that has sent nothing
    When a second connection sends a valid GET
    Then it gets no answer while the first connection is open
    And the first connection is closed between 8 and 14 seconds after it opened
    And then the second connection gets its 200
