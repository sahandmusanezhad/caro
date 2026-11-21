#!/usr/bin/env python3
"""The open issues of Tecso-Dev/caro, made again in this repository from a copy.

The owner chose on 2026-11-21 that caro is on the owner's account alone and
that Tecso-Dev/caro is deleted, its open issues moved here first
(docs/LEAVING_TECSO.md). This reads the copy that document's step 2 writes --
`gh issue list -R Tecso-Dev/caro --state all --json ...` into issues.json --
and makes each open issue again here with `gh issue create`, signed in as the
owner on the owner's machine:

    python3 scripts/move_issues.py ~/caro-tecso-backup/issues.json --dry-run
    python3 scripts/move_issues.py ~/caro-tecso-backup/issues.json

The first prints what would be made and makes nothing; the second makes it.
`--repo OWNER/NAME` names another target; none in Tecso-Dev is taken.

Each issue keeps its title. Its body says where it came from, who opened it
and when, and its labels there, then holds its body and every comment, in
order, each with who wrote it and when. A mention is written as code, so that
no one is notified again; a number like #4 is left as it was written, and the
first line says it is Tecso-Dev/caro's. Closed issues are not made again:
the copy keeps them.

What is made is written to moved.tsv beside the copy, a line as each issue is
made, its number there and its address here. Run again, it makes only what
moved.tsv does not hold, so nothing is made twice, and a run that stopped
goes on from where it stopped.

It reads no token and prints none: gh holds the owner's sign-in.

Exit status: 0 when every open issue of the copy is here; 1 when gh failed
on one, those before it made and written down; 2 when it refuses to start --
no such copy, a copy that is not gh's list, a target in Tecso-Dev, or Issues
off in the target.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SOURCE = "Tecso-Dev/caro"
TARGET = "sahandmusanezhad/caro"
# GitHub's limit on an issue's body is 65,536 characters; this leaves room.
LIMIT = 60000
# A login: letters, digits and single hyphens, neither first nor last, up to
# 39 characters; not right after a letter or a digit, as in an address.
_MENTION = re.compile(r"(?<![\w`])@([A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38})")


def quiet(text: str) -> str:
    """The text with each mention written as code, outside code already."""
    out, fence = [], False
    for line in (text or "").split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
            out.append(line)
            continue
        if fence:
            out.append(line)
            continue
        parts = line.split("`")
        for i in range(0, len(parts), 2):
            parts[i] = _MENTION.sub(r"`@\1`", parts[i])
        out.append("`".join(parts))
    return "\n".join(out)


def _who(item: dict) -> str:
    return (item.get("author") or {}).get("login") or "someone"


def body(issue: dict) -> str:
    """The body an issue is made with here."""
    labels = ", ".join(lb.get("name", "") for lb in issue.get("labels") or []) or "none"
    head = (f"Moved from {SOURCE}#{issue['number']}, which the owner chose on 2026-11-21 to delete, "
            f"so that caro is on the owner's account alone. Opened there by {_who(issue)} on "
            f"{str(issue.get('createdAt', ''))[:10]}; its labels there: {labels}. A mention below is "
            f"written as code, so that no one is notified again, and a number like #4 is {SOURCE}'s.")
    first = [head, quiet(issue.get("body") or "_(no description)_")]
    comments = [f"**{_who(c)}, {str(c.get('createdAt', ''))[:10]}:**\n\n{quiet(c.get('body') or '')}"
                for c in issue.get("comments") or []]
    kept = list(comments)
    while kept and len("\n\n---\n\n".join(first + kept)) > LIMIT:
        kept.pop()
    text = "\n\n---\n\n".join(first + kept)
    if len(kept) < len(comments):
        text += (f"\n\n---\n\n_{len(comments) - len(kept)} later comments did not fit in one issue; "
                 f"they are in the copy, issues.json._")
    return text + "\n"


def gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def _read_copy(copy: Path) -> list[dict] | str:
    try:
        issues = json.loads(copy.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return f"no copy at {copy}: run docs/LEAVING_TECSO.md's step 2 first"
    except (OSError, ValueError) as e:
        return f"{copy} is not gh's list of issues: {e}"
    if not isinstance(issues, list) or not all(
            isinstance(i, dict) and isinstance(i.get("number"), int) and isinstance(i.get("title"), str)
            and i.get("state") in ("OPEN", "CLOSED") for i in issues):
        return f"{copy} is not gh's list of issues: each needs a number, a title and a state"
    return issues


def _read_moved(path: Path) -> dict[int, str]:
    moved: dict[int, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                number, url = line.split("\t", 1)
                moved[int(number)] = url
    return moved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Tecso-Dev/caro's open issues, made again here from a copy.")
    ap.add_argument("copy", help="issues.json, written by docs/LEAVING_TECSO.md's step 2")
    ap.add_argument("--repo", default=TARGET, help=f"where they are made (default {TARGET})")
    ap.add_argument("--dry-run", action="store_true", help="print what would be made, and make nothing")
    a = ap.parse_args(argv)

    if a.repo.split("/")[0].lower() == "tecso-dev":
        print(f"refused: nothing is written to Tecso-Dev ({a.repo}); docs/WORKING_AGREEMENT.md", file=sys.stderr)
        return 2
    copy = Path(a.copy).expanduser()
    issues = _read_copy(copy)
    if isinstance(issues, str):
        print(f"refused: {issues}", file=sys.stderr)
        return 2
    moved_path = copy.with_name("moved.tsv")
    moved = _read_moved(moved_path)
    open_ = sorted((i for i in issues if i["state"] == "OPEN"), key=lambda i: i["number"])
    todo = [i for i in open_ if i["number"] not in moved]
    print(f"{len(issues)} issues in the copy, {len(open_)} open; {len(open_) - len(todo)} made here "
          f"already; {len(todo)} to make in {a.repo}")
    if a.dry_run:
        for i in todo:
            print(f"would make {SOURCE}#{i['number']}: {i['title']}")
        return 0
    if todo:
        on = gh("repo", "view", a.repo, "--json", "hasIssuesEnabled", "-q", ".hasIssuesEnabled")
        if on.returncode != 0 or on.stdout.strip() != "true":
            print(f"refused: Issues is not on in {a.repo}; turn it on under Settings -> General -> "
                  f"Features -> Issues, then run this again. {on.stderr.strip()}", file=sys.stderr)
            return 2
    for i in todo:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(body(i))
        try:
            p = gh("issue", "create", "-R", a.repo, "--title", i["title"], "--body-file", f.name)
        finally:
            os.unlink(f.name)
        lines = p.stdout.strip().splitlines()
        url = lines[-1].strip() if lines else ""
        if p.returncode != 0 or not url.startswith("https://"):
            print(f"gh failed on {SOURCE}#{i['number']}, and nothing after it was made: "
                  f"{p.stderr.strip() or p.stdout.strip()}", file=sys.stderr)
            return 1
        with moved_path.open("a", encoding="utf-8") as m:
            m.write(f"{i['number']}\t{url}\n")
        moved[i["number"]] = url
        print(f"{SOURCE}#{i['number']} -> {url}")
    print(f"{moved_path}: {len(moved)} lines")
    for number in sorted(moved):
        print(f"{SOURCE}#{number}\t{moved[number]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
