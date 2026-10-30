# Working agreement for this repository

Standing instructions from the project owner. They apply to every session —
whoever runs it, on his machine or away from it — not just the one that
recorded them. Where a session's own defaults disagree with this file, this
file wins. Where the owner says otherwise in a session, he wins, and this file
is corrected in a commit of its own.

What is left to do, and in what order, is in [ROADMAP](ROADMAP.md).

## The round

Every change goes through the same steps, and none is skipped because the
change looks small.

1. **Predictions first.** Before anything is run or changed, write down what
   the measurement will show, in a file, with the sha256 of every input it
   reads. A prediction that turns out wrong is reported as wrong, with its
   number. It is never rewritten after the result is seen.
2. **The measurement.** Run on the code as it is, in a copy of the tree, with
   the network off where the system allows it (`unshare -n`). Inputs are
   phrasings or data written for the measurement and said to be so; no log of
   what buyers type exists, and none is invented. No synthetic fixture fills a
   gap in a measurement of real data.
3. **The owner decides,** on the measurement. Put the ways to go to him with
   their numbers, say which one you would take and why, and say plainly where
   you disagree with him. Nothing is built before he has chosen.
4. **The build.** One commit per change, each with its reasoning in the
   message. Before its tests are written, try the build by hand on phrasings
   outside the measurement's sets: twice a fault was found only that way
   (D84). Tests pin what is read and what is left, so that either changes on
   purpose. Mutate each change and run the tests against every mutant; say
   which survive and why, and do not add a row after the run just to catch
   one. Run every mutant with `python3 -B` and `PYTHONDONTWRITEBYTECODE=1`,
   and restore the file by moving the copy back: a mutant and the original of
   the same size, written in the same second, share the bytecode of the first
   (found 2026-10-26: a restored `first_run.py` still ran its mutant, `return
   1`, and a run of the suites failed for it). The earlier rounds' mutations
   were rerun that way and gave the same survivors. Every commit is green on its own: all sixteen suites, and the site's
   build when the site is touched. The published counts — the README's four
   numbers and `/about`'s — move in the commit that moves them, or
   `tests/run_all.py` fails.
5. **The push is the owner's.**
6. **After the push,** read CI on both repositories and the site from the
   outside, and only then write the D-entry, with his hashes and what was
   seen. No D-number is cited anywhere before its entry exists.

## Commits and pushes

- **Every commit is authored and committed as
  `sahandmusanezhad <sahand.mosanejad4488@gmail.com>`**, and under no other
  name or address.
- **No trailer of any kind** — no co-author line, no session link, no line
  that credits a tool with the work — and no tool or vendor name in any file,
  commit message or branch name of this repository.
- **Separate commits, one per change**, each with the reasoning in the
  message. The commit log is part of the design record here; the *why* lives
  there, not only in the code. Pushed history is never squashed or rewritten.
- **Add files by name**, never with `git add -A` or `git add .`; a build
  directory or a link to one (`webapp/web/node_modules`) is never committed.
- **A session on the owner's machine** commits in his checkout and stops
  before `git push`. **A session that cannot reach his checkout** hands him
  the commits as patches, with a script that applies them with `git am`,
  checks the state it starts from and refuses any other, and is rehearsed on a
  fresh clone before he gets it.
- **The owner pushes**, to `github.com/Tecso-Dev/caro`, branch `main`, and the
  same branch to his own copy, `github.com/sahandmusanezhad/caro`. Never
  handle his GitHub token or any other credential; the credentials live on his
  machine and stay there.
- **Prepare each commit so it is green on its own.** The working tree may
  hold several pending changes at once, so `run_all.py` before a commit
  reports the tree rather than the commit. When more than one commit is
  staged at a time, check each in isolation and say which number belongs to
  which.

## Data, sources and secrets

- **No live request to any source without the owner's explicit permission.**
  Each live run is his decision and runs on his machine; a session writes its
  plan and its predictions, and reads what comes back.
- **The phone number of a seller on a source is never stored or shown.**
  No evasion of a block, no CAPTCHA solving, no rotation of accounts, no OTP
  handling on a source's account; robots.txt is read in code and obeyed
  (D73); a seller is a dealer only where the source shows a business badge
  (D26).
- **A number a seller gives CARO is shown only as that seller chose.** The
  owner chose on 2026-10-30 to build listings that sellers post on CARO
  itself ([SELLER_LISTINGS](SELLER_LISTINGS.md)). Their number is the one
  they logged in with: kept apart from the corpus, never in a page's HTML,
  JSON or structured data, shown only where its seller ticked «نمایش شماره»
  and only when a visitor presses it, and deleted with the account. The
  code CARO sends its own users to log in is not a source's OTP.
- **Snapshots and observations stay on the owner's machine.** What is
  published is a promoted corpus under `data/corpora/`, under
  [DATA_CONTRACT](DATA_CONTRACT.md).
- **`CARO_SELLER_SALT` lives outside the repository, on the owner's
  machine.** It is never printed, logged or committed. A key for any service
  is entered by the owner on his machine: a session never asks for it to be
  pasted into a conversation, and never reads, prints, logs or commits it.

## Decisions that are the owner's

- **Technology and language**: a new dependency, a framework, a model, a
  storage service, a new major version of a CI action, the design of the
  login. Propose with the reasons; he decides.
- **Rules about Persian that are a choice and not a measurement** — which
  letters may stand beside a word is one. He chose on 2026-10-18 to leave the
  letter boundaries as they are (D84).
- **Scope, and what is sent where.**

## Talking to the owner

He reads in Persian: a session replies to him in Persian, and keeps code,
commands, commit messages and the prose of this repository in English, which
is his choice for the repository. Say what was measured with its numbers, say
plainly what went wrong — one's own errors first — and state a disagreement
instead of complying in silence.

## The review loop

**Every piece of work goes to a second reviewer for analysis.** Not a summary
of the work — the work, with its numbers and its reasoning, and an explicit
request for the strongest objection rather than approval. The session writes
it as a brief that stands on its own; the owner relays it himself and brings
the answer back. A session never drives a reviewer's account itself. The loop
continues until the project is finished, not until the reviews stop being
critical.

**What this loop is for, and what it is not.** Its value so far has been
adversarial, not generative: it caught the missing confidence interval on
Run 5's MAE comparison (D39) — a real defect that changed what the run was
allowed to claim, and one no test in this repository would ever have found.
It has also been wrong, and saying so mattered: it read D30's *conditional*
coverage as *prediction-interval* coverage and concluded D37 had not proven
a tension, when the two quantities are complements over one population by
definition.

So: take the objection seriously, verify it against the code or the data
before acting, and disagree in writing when it is wrong. A review that is
accepted without checking is not a review, and two models agreeing with each
other is not evidence of anything.

## What this project is about

CARO's differentiator is not its model. It is that the system refuses to let
a claim outrun its evidence, and the design record is where that is
enforced. Two rules follow, and both have been broken before:

- **D36** — a mechanism the design supports is not an observed fact about
  the Iranian market. Nine instances, `tests/test_claims.py` guards against
  their recurrence, and it explicitly does not catch new ones.
- **D35** — acquisition and estimator never change in the same run, and a
  gate is never edited after seeing its output. After a loss, changing the
  corpus and re-running is the most natural way to manufacture a win.

Read `docs/DECISIONS.md` before changing anything. Most of its entries exist
because something went wrong in a way that was invisible. It carries no count
here on purpose: `/about` states one and `tests/test_claims.py` recomputes it
from the file, and a second hand-kept copy in this document would be a second
thing to go stale — which is what the sentence this replaced had done.
