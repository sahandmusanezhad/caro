"""Cloudflare Turnstile, verified on the server (docs/REARCHITECTURE.md,
phase 4).

Two forms are worth a bot's while: the seller's code request, where every
message sent spends the SMS account's credit, and the contact form, which
writes to the inbox. With CARO_TURNSTILE_SECRET set, each of them asks for
the token the widget gave the browser, and Cloudflare is asked whether it
is good before anything else is done:

    POST https://challenges.cloudflare.com/turnstile/v0/siteverify
         secret, response (the token), remoteip (the client's address)

Good means Cloudflare's own `success: true`. A token missing, refused, or
not answered for within ten seconds is 403, TURNSTILE, and nothing is sent
or written. Unset, nothing is asked, as before. The site draws the widget
where NEXT_PUBLIC_TURNSTILE_SITE_KEY was set at build (components/Turnstile).
Nothing about a request is printed: the secret is in its body.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Callable

from fastapi import HTTPException, Request

from webapp.api.security import client_address

VERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
REFUSED_FA = "بررسی «ربات نیستم» انجام نشد. صفحه را تازه کن و دوباره امتحان کن."
# How Cloudflare is asked; the suites put an opener of their own here.
OPENER: Callable = urllib.request.urlopen


def secret() -> str:
    return os.environ.get("CARO_TURNSTILE_SECRET", "").strip()


def verify(token: str | None, remote: str, *, opener: Callable | None = None,
           timeout: float = 10) -> bool:
    """Whether Cloudflare says the token is good; False for anything else."""
    if not token:
        return False
    form = {"secret": secret(), "response": token}
    if remote and remote != "unknown":
        form["remoteip"] = remote
    req = urllib.request.Request(VERIFY, data=urllib.parse.urlencode(form).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with (opener or OPENER)(req, timeout=timeout) as r:
            answer = json.loads(r.read().decode("utf-8"))
    except Exception:          # noqa: BLE001 -- no answer, or not Cloudflare's: not good
        return False
    return isinstance(answer, dict) and answer.get("success") is True


def require(token: str | None, request: Request) -> None:
    """403 TURNSTILE where a secret is set and the token is not good."""
    if secret() and not verify(token, client_address(request)):
        raise HTTPException(403, {"code": "TURNSTILE", "fa": REFUSED_FA})
