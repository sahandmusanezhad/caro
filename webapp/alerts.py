"""The collection's alerts, said from the server (docs/REARCHITECTURE.md,
phase 3).

    python -m webapp.role alerts            every five minutes, until stopped
    python -m webapp.role alerts --once     one look
    python -m webapp.role alerts --test     one test message, and nothing else

Reads the runs the worker reported (caro/runs.py) and says each alert they
raise once: a run that did not arrive by its time, a run that stopped, a
robots.txt that changed, a count far from the runs before it. They are said
from the server, because a worker that stopped cannot say so, and because
Telegram, where the owner's alerts go (phase 0), is not reached from Iran.

    CARO_OPS_URL                 the runs' database
    CARO_ALERT_EXPECT            the runs expected each day, source@HH:MM Tehran: khodro45@05:00
    CARO_ALERT_TELEGRAM_TOKEN    a Telegram bot's token
    CARO_ALERT_TELEGRAM_CHAT     the chat it writes to

Without the bot, an alert is written to the log alone and kept as said, so
that the bot, once set, does not send a backlog. A message holds the
source, the run, and the numbers; nothing personal is in a record to say.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from caro import runs as runs_mod

EVERY = 300


@dataclass
class Telegram:
    token: str
    chat: str
    opener: Callable = urllib.request.urlopen

    def send(self, text: str) -> bool:
        """True when Telegram took the message. Its address holds the token,
        so a failure is said by its kind alone."""
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{self.token}/sendMessage", method="POST",
            data=urllib.parse.urlencode({"chat_id": self.chat, "text": text,
                                         "disable_web_page_preview": "true"}).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with self.opener(req, timeout=15) as r:
                return r.status == 200
        except Exception as e:      # noqa: BLE001
            print(f"alerts: Telegram did not take the message ({type(e).__name__})", file=sys.stderr)
            return False


def notifier(env=None) -> Telegram | None:
    env = os.environ if env is None else env
    token = (env.get("CARO_ALERT_TELEGRAM_TOKEN") or "").strip()
    chat = (env.get("CARO_ALERT_TELEGRAM_CHAT") or "").strip()
    if bool(token) != bool(chat):
        raise SystemExit("alerts: CARO_ALERT_TELEGRAM_TOKEN and CARO_ALERT_TELEGRAM_CHAT go together")
    return Telegram(token, chat) if token else None


def look(db: runs_mod.Runs, expect: list[runs_mod.Expected], bot: Telegram | None,
         now: float, out: Callable[[str], None] = print) -> list[str]:
    """Says every alert not said before; gives the keys said now. An alert
    the bot did not take is not kept as said, and is tried on the next look."""
    said = []
    for a in runs_mod.alerts(db.runs(limit=500), expect, now):
        if db.said(a.key):
            continue
        text = "CARO: " + a.text
        if bot is not None and not bot.send(text):
            continue
        db.say(a.key, a.text, now=int(now))
        out(f"alert{'' if bot else ' (log only: no Telegram bot is set)'}: {a.text}")
        said.append(a.key)
    return said


def main(argv: list[str] | None = None, clock: Callable[[], float] = time.time) -> int:
    ap = argparse.ArgumentParser(prog="alerts", description="the collection's alerts")
    ap.add_argument("--once", action="store_true", help="one look, then stop")
    ap.add_argument("--test", action="store_true", help="send one test message, and nothing else")
    a = ap.parse_args(argv)
    bot = notifier()
    if a.test:
        if bot is None:
            print("alerts: no Telegram bot is set, so nothing was sent", file=sys.stderr)
            return 1
        ok = bot.send("CARO: a test alert, sent by the operator. Nothing is wrong.")
        print("alerts: the test message was sent" if ok else "alerts: the test message was not sent")
        return 0 if ok else 1
    try:
        expect = runs_mod.expected(os.environ.get("CARO_ALERT_EXPECT", ""))
        db = runs_mod.open_runs(os.environ.get(runs_mod.OPS_ENV, ""))
    except (ValueError, runs_mod.RunsError) as e:
        print(f"alerts: {e}", file=sys.stderr)
        return 2
    stop = {"now": False}

    def _stop(*_):
        stop["now"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    print(f"alerts: {'Telegram' if bot else 'the log alone'}; expecting "
          + (", ".join(f"{e.source} by {e.by}" for e in expect) or "no daily run"), flush=True)
    while not stop["now"]:
        look(db, expect, bot, clock())
        if a.once:
            break
        for _ in range(EVERY):
            if stop["now"]:
                break
            time.sleep(1)
    db.close()
    return 0
