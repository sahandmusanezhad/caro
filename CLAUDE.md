# Working agreement for this repository

Standing instructions from the project owner. They apply to every session,
not just the one that recorded them.

## The review loop

**Every piece of work goes to ChatGPT for analysis.** Not a summary of the
work — the work, with its numbers and its reasoning, and an explicit request
for the strongest objection rather than approval. The loop continues until
the project is finished, not until the reviews stop being critical.

The conversation lives at `chatgpt.com` under the owner's account
(«طراحی پرامپت چندعاملی»). It is reached with the Chrome extension.

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

## Commits and pushes

- **Separate commits, one per change**, each with the reasoning in the
  message. The commit log is part of the design record here; the *why* lives
  there, not only in the code.
- **Push after committing.** The remote is
  `github.com/sahandmusanezhad/caro`, branch `main`, and `gh` is
  authenticated on the owner's machine.
- Pushing needs `mcp__remote-devices__device_bash`, which runs git on the
  owner's computer using credentials that already live there. **Never handle
  the owner's GitHub token**, and never push from the sandbox. If the bridge
  is down, commit anyway, write a fresh `git bundle --all` into
  `~/Projects/`, and say plainly that the push is pending.

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

Read `docs/DECISIONS.md` before changing anything. It is 48 entries and most
of them exist because something went wrong in a way that was invisible.
