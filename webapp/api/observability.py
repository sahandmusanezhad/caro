"""Error reports from the API, and nothing in them a person could be found by.

Phase 0 of the accepted plan (docs/REARCHITECTURE.md): Sentry on the API, so
that a fault in production reaches the owner instead of a log nobody reads.
It is off unless `SENTRY_DSN` is set: with no DSN nothing is imported,
nothing leaves the process and nothing behaves differently, which is how the
suites run.

What leaves the process when it is on is an exception's type, its message
and its frames -- file, function, line -- and the plan's sixth security
measure says what does not:

- `send_default_pii`, `include_local_variables` and `include_source_context`
  are off, so the SDK attaches no cookie, no user, no address, no frame's
  variables, where a secret or a seller's number could sit, and none of the
  source lines around a frame -- found when the first real event sent by
  the suite carried the numbers written in the lines around the raise;
- `scrub`, both `before_send` and `before_breadcrumb`, takes out what an
  event can still carry: the request's cookies, body, query string and
  environment, every header but four that hold neither a credential nor an
  address, the user, the query in a URL, and every Iranian mobile number
  written anywhere in a string, in Persian or Arabic-Indic digits too, in
  the shapes `store.phone_09` reads. A ten-digit number that starts with 9
  is one of them -- a mobile written without its 0 -- and is taken out even
  where it was a price: a report short of a price is a smaller loss than a
  report that carries a number.
"""

from __future__ import annotations

import importlib
import os
import re
import sys
from typing import Any, Callable, Mapping

from fastapi import APIRouter, Header, Request

from webapp.api.store import phone_09

DSN_ENV = "SENTRY_DSN"
REDACTED = "[a number]"
# The headers an event keeps. Everything else -- Authorization, Cookie,
# X-Admin-Token, X-Admin-Code, X-Forwarded-For and whatever a proxy adds --
# is dropped: a list of what may stay cannot miss a header nobody thought of.
KEEP_HEADERS = frozenset({"content-type", "content-length", "accept", "host"})
# Taken out wherever they appear in an event.
DROP_KEYS = frozenset({"cookies", "data", "query_string", "env", "user", "vars", "ip_address"})

_DIGIT = "0-9۰-۹٠-٩"
_GROUP = re.compile(f"[{_DIGIT}]+")
_JOIN = re.compile(r"[\s\-.()\u200c]{0,3}")     # \u200c: the zero-width non-joiner


def redact_numbers(text: str) -> str:
    """`text` with every mobile number in it replaced by REDACTED. A number
    is found as runs of digits joined by at most three of the separators
    people write between them, and kept only if `phone_09` reads the whole
    as one number -- so two unrelated numbers side by side are not joined
    into one, and a price beside a number does not hide it."""
    groups = [(m.start(), m.end()) for m in _GROUP.finditer(text)]
    spans, i = [], 0
    while i < len(groups):
        found = None
        for j in range(i, min(i + 5, len(groups))):
            if j > i and not _JOIN.fullmatch(text[groups[j - 1][1]:groups[j][0]]):
                break
            start = groups[i][0] - (1 if groups[i][0] > 0 and text[groups[i][0] - 1] == "+" else 0)
            if phone_09(text[start:groups[j][1]]):
                found = (start, groups[j][1], j)
                break
        if found:
            spans.append(found[:2])
            i = found[2] + 1
        else:
            i += 1
    for start, end in reversed(spans):
        text = text[:start] + REDACTED + text[end:]
    return text


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return redact_numbers(value)
    if isinstance(value, Mapping):
        return {k: _clean(v) for k, v in value.items() if k not in DROP_KEYS}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def scrub(event: dict, hint: Any = None) -> dict:
    """An event as it may leave the process: see the module's docstring."""
    request = event.get("request")
    if isinstance(request, Mapping):
        request = dict(request)
        headers = request.get("headers")
        if isinstance(headers, Mapping):
            request["headers"] = {k: v for k, v in headers.items() if str(k).lower() in KEEP_HEADERS}
        if isinstance(request.get("url"), str):
            request["url"] = request["url"].split("?", 1)[0].split("#", 1)[0]
        event = {**event, "request": request}
    return _clean(event)


def scrub_breadcrumb(crumb: dict, hint: Any = None) -> dict:
    return _clean(crumb)


# Whether init_sentry started the SDK in this process.
_ON = False
TEST_MESSAGE = "a test report, sent by the operator from /api/admin/report-test"


def init_sentry(env: Mapping[str, str] | None = None, *,
                importer: Callable[[str], Any] = importlib.import_module) -> bool:
    """Starts error reports when SENTRY_DSN is set; True when they are on.
    Never raises: a report that cannot be sent is no reason for the API not
    to start."""
    env = os.environ if env is None else env
    dsn = (env.get(DSN_ENV) or "").strip()
    if not dsn:
        return False
    try:
        sdk = importer("sentry_sdk")
    except ImportError:
        print(f"{DSN_ENV} is set and sentry-sdk is not installed: error reports are off",
              file=sys.stderr)
        return False
    try:
        rate = float(env.get("SENTRY_TRACES_SAMPLE_RATE") or 0)
    except ValueError:
        rate = 0.0
    try:
        sdk.init(dsn=dsn, send_default_pii=False, include_local_variables=False,
                 include_source_context=False,
                 before_send=scrub, before_breadcrumb=scrub_breadcrumb,
                 environment=(env.get("SENTRY_ENVIRONMENT") or "production").strip(),
                 release=(env.get("SENTRY_RELEASE") or "").strip() or None,
                 traces_sample_rate=rate)
    except Exception as e:                      # noqa: BLE001 — see the docstring
        print(f"error reports are off: Sentry would not start ({type(e).__name__})", file=sys.stderr)
        return False
    global _ON
    _ON = True
    return True


router = APIRouter()


@router.post("/api/admin/report-test")
def report_test(request: Request, x_admin_token: str | None = Header(default=None),
                x_admin_code: str | None = Header(default=None)) -> dict:
    """The operator's way to see an error report arrive: one message, sent
    through the same scrubbers as any event, and its id to find it by. It
    says "off" where SENTRY_DSN is not set -- which is how to tell that from
    reports that are on and not arriving. The operator's check is the
    inbox's, so it is refused, and slowed, as every operator's endpoint is."""
    from webapp.api.contact import require_operator          # noqa: PLC0415
    require_operator(request, x_admin_token, x_admin_code)
    if not _ON:
        return {"reports": "off"}
    sdk = importlib.import_module("sentry_sdk")
    event_id = sdk.capture_message(TEST_MESSAGE, level="info")
    sdk.flush(timeout=5)
    return {"reports": "on", "event_id": event_id}
