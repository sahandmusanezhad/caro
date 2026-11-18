#!/usr/bin/env python3
"""The owner's Cloudflare steps, done through Cloudflare's API with the
owner's own token (docs/PHASE1_SETUP.md, steps 3, 6 and 8;
docs/PHASE4_SETUP.md, steps 1 and 3).

    read -rs CLOUDFLARE_API_TOKEN && export CLOUDFLARE_API_TOKEN
    python3 scripts/cloudflare_setup.py <command> [--dry-run]

The first line reads the token without showing it or keeping it in the
shell's history: paste it, then Enter.

    status                  what the zone holds of the rest, read only, and
                            the zone's id (PHASE4, step 2)
    origin-cert             on the server, as root: a key made there, and
                            Cloudflare's origin certificate for both
                            hostnames, valid 15 years, in /etc/caro/tls
                            (--tls-dir to change it). Only the key's request
                            leaves the server, never the key (PHASE1, step 3)
    staging --ip ADDRESS    caro-staging.noxioai.com, an A record to the
                            server, proxied (PHASE1, step 6)
    cache                   the rule that lets the edge keep the API's three
                            answers, added after the rules the zone has, none
                            of which is changed (PHASE4, step 1)
    turnstile               the widget for both hostnames: its site key
                            printed, its secret written to
                            turnstile-secret.txt beside you, mode 600 (PHASE4,
                            step 3)
    switch [--ip ADDRESS]   caro.noxioai.com from what it is -- Vercel's
                            CNAME -- to an A record to the server, proxied:
                            to the address staging's record has, unless
                            another is given,
                            in one change that Cloudflare makes whole or not
                            at all; what it was is kept in
                            cloudflare-undo.json beside you, by the first
                            switch (PHASE1, step 8)
    undo-switch             caro.noxioai.com back to what the first switch
                            found, in one change, and the kept file removed

The token is read from the environment, sent to api.cloudflare.com and
nowhere else, and never printed. Make it in Cloudflare under My Profile ->
API Tokens -> Create Token -> Custom token. Its permissions, as the form
names them:
- Zone / Zone / Read, Zone / DNS / Edit, Zone / Cache Rules / Edit and
  Zone / SSL and Certificates / Edit, for the zone noxioai.com alone;
- Account / Turnstile / Edit.
A command the token is not allowed stops with Cloudflare's refusal and the
permission that command needs. Delete the token when the steps are done.

Every command reads before it writes, writes only what differs from what it
wants, and with --dry-run writes nothing. Run again, it finds its work done.
A refusal from Cloudflare stops it with Cloudflare's own message.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

API = "https://api.cloudflare.com/client/v4"
ZONE = "noxioai.com"
SITE = "caro.noxioai.com"
STAGING = "caro-staging.noxioai.com"
PHASE = "http_request_cache_settings"
RULE_NAME = "CARO: API answers that say they may be kept"
RULE = {
    "description": RULE_NAME,
    "expression": '(http.request.uri.path in {"/api/models" "/api/model" "/api/corpus"})',
    "action": "set_cache_settings",
    "action_parameters": {"cache": True, "edge_ttl": {"mode": "respect_origin"},
                          "browser_ttl": {"mode": "respect_origin"}},
    "enabled": True,
}
# The same rule made by hand, as PHASE4_SETUP's step 1 names it.
RULE_NAMES = (RULE_NAME, "API answers that say they may be kept")
WIDGET = "caro"
WIDGET_DOMAINS = [SITE, STAGING]
SECRET_FILE = "turnstile-secret.txt"
UNDO_FILE = "cloudflare-undo.json"
TLS_DIR = Path("/etc/caro/tls")
CERT_DAYS = 5475                 # fifteen years, the longest Cloudflare gives
# What each command needs of the token, said when Cloudflare refuses it.
NEEDS = {"status": "Zone / Zone / Read", "staging": "Zone / DNS / Edit", "switch": "Zone / DNS / Edit",
         "undo-switch": "Zone / DNS / Edit", "cache": "Zone / Cache Rules / Edit",
         "turnstile": "Account / Turnstile / Edit", "origin-cert": "Zone / SSL and Certificates / Edit"}
OPENER: Callable = urllib.request.urlopen
RUN: Callable = subprocess.run


class CloudflareError(RuntimeError):
    """Cloudflare refused, or did not answer as its API does. The message
    holds Cloudflare's words and never the token."""

    def __init__(self, message: str, status: int | None = None, codes: tuple = ()) -> None:
        super().__init__(message)
        self.status, self.codes = status, codes


class Client:
    def __init__(self, token: str, opener: Callable | None = None, dry: bool = False,
                 out: Callable[[str], None] = print) -> None:
        self._token, self._opener, self.dry, self.out = token, opener or OPENER, dry, out

    def call(self, method: str, path: str, body: dict | None = None, query: dict | None = None,
             missing_ok: bool = False):
        """The `result` of one call; None for a 404 where `missing_ok`."""
        url = API + path + ("?" + urllib.parse.urlencode(query) if query else "")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Authorization": f"Bearer {self._token}",
                                              "Content-Type": "application/json"})
        status = None
        try:
            with self._opener(req, timeout=30) as r:
                answer = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404 and missing_ok:
                return None
            status = e.code
            try:
                answer = json.loads(e.read().decode("utf-8"))
            except Exception:          # noqa: BLE001 -- not Cloudflare's JSON
                raise CloudflareError(f"{method} {path}: HTTP {e.code}", e.code) from None
        except Exception as e:         # noqa: BLE001 -- no answer at all
            raise CloudflareError(f"{method} {path}: no answer ({type(e).__name__})") from None
        if not isinstance(answer, dict) or answer.get("success") is not True:
            errors = [x for x in (answer.get("errors") if isinstance(answer, dict) else None) or []
                      if isinstance(x, dict)]
            words = "; ".join(str(x.get("message", x)) for x in errors) or "refused"
            raise CloudflareError(f"{method} {path}: {words}", status, tuple(x.get("code") for x in errors))
        return answer.get("result")

    def write(self, method: str, path: str, body: dict | None = None, what: str = ""):
        """A change: said and made, or with --dry-run only said."""
        if self.dry:
            self.out(f"would: {what}")
            return None
        result = self.call(method, path, body)
        self.out(what)
        return result


def zone_of(c: Client, name: str = ZONE) -> tuple[str, str]:
    zones = [z for z in c.call("GET", "/zones", query={"name": name}) or [] if z.get("name") == name]
    if not zones:
        raise CloudflareError(f"the token sees no zone {name}")
    return zones[0]["id"], zones[0]["account"]["id"]


def records(c: Client, zone: str, name: str) -> list[dict]:
    """The records at `name` and at no other: asked for by the exact name, and
    filtered again here, so that nothing this script changes or takes away can
    be another name's, whatever the filter did."""
    got = c.call("GET", f"/zones/{zone}/dns_records", query={"name.exact": name, "per_page": 100}) or []
    return [r for r in got if str(r.get("name", "")).lower() == name.lower()]


def ensure_a(c: Client, zone: str, name: str, ip: str) -> str:
    """An A record at `name` to `ip`, proxied: "unchanged", "created" or
    "changed". Another kind of record at the name is not touched here."""
    have = records(c, zone, name)
    other = [r for r in have if r["type"] not in ("A", "AAAA")]
    if other:
        raise CloudflareError(f"{name} is a {other[0]['type']} record; not changed here")
    a = [r for r in have if r["type"] == "A"]
    want = {"type": "A", "name": name, "content": ip, "proxied": True, "ttl": 1}
    if a and a[0]["content"] == ip and a[0].get("proxied") is True:
        c.out(f"{name}: an A record to {ip}, proxied, already")
        return "unchanged"
    if a:
        c.write("PATCH", f"/zones/{zone}/dns_records/{a[0]['id']}", want,
                f"{name}: the A record changed to {ip}, proxied")
        return "changed"
    c.write("POST", f"/zones/{zone}/dns_records", want, f"{name}: an A record to {ip}, proxied, made")
    return "created"


def _squeezed(expression) -> str:
    return "".join(str(expression or "").split())


def _is_ours(rule: dict) -> bool:
    """CARO's cache rule: by either of its names, or by what it matches."""
    return rule.get("description") in RULE_NAMES or _squeezed(rule.get("expression")) == _squeezed(RULE["expression"])


def cache_rules(c: Client, zone: str) -> tuple[dict | None, list[dict], int | None]:
    """The zone's cache rules' entry point, its rules, and where CARO's is."""
    entry = c.call("GET", f"/zones/{zone}/rulesets/phases/{PHASE}/entrypoint", missing_ok=True)
    rules = (entry or {}).get("rules") or []
    return entry, rules, next((i for i, r in enumerate(rules) if _is_ours(r)), None)


def _overridden(rules: list[dict], at: int) -> list[str]:
    """The rules after CARO's that switch the cache off: where two match, the
    later one's settings win."""
    return [str(r.get("description") or r.get("id")) for r in rules[at + 1:]
            if r.get("enabled", True) and (r.get("action_parameters") or {}).get("cache") is False]


def ensure_cache_rule(c: Client, zone: str) -> str:
    """The rule at the end of the zone's own, none of which is sent or changed."""
    entry, rules, at = cache_rules(c, zone)
    if at is not None:
        c.out("the cache rule: there already")
        for later in _overridden(rules, at):
            c.out(f"  but the rule «{later}» comes after it and switches the cache off: "
                  "in Caching -> Cache Rules, drag CARO's below it")
        return "unchanged"
    if entry and entry.get("id"):
        c.write("POST", f"/zones/{zone}/rulesets/{entry['id']}/rules", RULE,
                f"the cache rule: made, after the {len(rules)} rule(s) the zone had")
    else:
        c.write("PUT", f"/zones/{zone}/rulesets/phases/{PHASE}/entrypoint", {"rules": [RULE]},
                "the cache rule: made, the zone's first")
    return "created"


def ensure_widget(c: Client, account: str, secret_file: Path) -> str | None:
    """The widget's site key; its secret written to `secret_file`, mode 600."""
    widgets = c.call("GET", f"/accounts/{account}/challenges/widgets", query={"per_page": 50}) or []
    have = [w for w in widgets if w.get("name") == WIDGET]
    if have:
        widget = c.call("GET", f"/accounts/{account}/challenges/widgets/{have[0]['sitekey']}")
        domains = list(widget.get("domains") or [])
        missing = [d for d in WIDGET_DOMAINS if d not in domains]
        if missing:
            # A PUT is the whole widget: what it has of these is sent back as it is.
            kept = {k: widget[k] for k in ("bot_fight_mode", "clearance_level", "ephemeral_id", "offlabel")
                    if widget.get(k) is not None}
            changed = c.write("PUT", f"/accounts/{account}/challenges/widgets/{widget['sitekey']}",
                              {"name": widget.get("name") or WIDGET, "domains": domains + missing,
                               "mode": widget.get("mode") or "managed", **kept},
                              f"the Turnstile widget: {', '.join(missing)} added to it")
            widget = {**widget, **(changed or {})}
        else:
            c.out(f"the Turnstile widget: there already, for {', '.join(domains)}")
    else:
        widget = c.write("POST", f"/accounts/{account}/challenges/widgets",
                         {"name": WIDGET, "domains": WIDGET_DOMAINS, "mode": "managed"},
                         f"the Turnstile widget: made, for {', '.join(WIDGET_DOMAINS)}")
        if widget is None:              # --dry-run
            return None
    sitekey, secret = widget["sitekey"], widget.get("secret") or ""
    if secret and not c.dry:
        fd = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(secret + "\n")
        os.chmod(secret_file, 0o600)
        c.out(f"its secret is in {secret_file}, mode 600: CARO_TURNSTILE_SECRET in the server's env files")
    c.out(f"its site key, which is public: NEXT_PUBLIC_TURNSTILE_SITE_KEY={sitekey}")
    return sitekey


def _replace(c: Client, zone: str, have: list[dict], new: list[dict], what: str):
    """The records at a name replaced in one batch: Cloudflare takes the old
    away and makes the new in one transaction, or does neither -- the name is
    never left without a record by a change that failed half-way."""
    return c.write("POST", f"/zones/{zone}/dns_records/batch",
                   {"deletes": [{"id": r["id"]} for r in have], "posts": new}, what)


def staging_address(c: Client, zone: str) -> str:
    """The server's address, as staging's record has it (PHASE1, step 6)."""
    a = [r for r in records(c, zone, STAGING) if r["type"] == "A"]
    if len(a) != 1:
        raise CloudflareError(f"{STAGING} has {len(a)} A records, not one: give the switch --ip")
    try:
        ip = _ip(a[0]["content"])
    except argparse.ArgumentTypeError as e:
        raise CloudflareError(f"{STAGING}'s record: {e}") from None
    c.out(f"the server's address, as {STAGING}'s record has it: {ip}")
    return ip


def switch(c: Client, zone: str, ip: str, undo_file: Path) -> str:
    """caro.noxioai.com to the server. What the first switch found is kept in
    `undo_file`, and a later switch -- to a new address -- keeps it as it is."""
    have = records(c, zone, SITE)
    a = [r for r in have if r["type"] == "A"]
    if a and len(have) == 1 and a[0]["content"] == ip and a[0].get("proxied") is True:
        c.out(f"{SITE}: an A record to {ip}, proxied, already")
        return "unchanged"
    if undo_file.exists():
        c.out(f"{SITE}: {undo_file} kept as the first switch wrote it")
    elif have and not c.dry:
        old = [{k: r[k] for k in ("type", "name", "content", "proxied", "ttl") if k in r} for r in have]
        undo_file.write_text(json.dumps(old, indent=2) + "\n", encoding="utf-8")
        c.out(f"{SITE}: what it was kept in {undo_file}")
    gone = ", ".join(f"the {r['type']} record to {r['content']}" for r in have) or "nothing"
    _replace(c, zone, have, [{"type": "A", "name": SITE, "content": ip, "proxied": True, "ttl": 1}],
             f"{SITE}: an A record to {ip}, proxied, in place of {gone}")
    return "switched"


def undo_switch(c: Client, zone: str, undo_file: Path) -> str:
    if not undo_file.exists():
        raise CloudflareError(f"no {undo_file}: nothing was switched from here")
    old = json.loads(undo_file.read_text(encoding="utf-8"))
    have = records(c, zone, SITE)
    back = ", ".join(f"the {r['type']} record to {r['content']}" for r in old)
    _replace(c, zone, have, old, f"{SITE}: {back}, put back")
    if not c.dry:
        undo_file.unlink()
        c.out(f"{SITE}: {undo_file} removed; the next switch keeps what it finds")
    return "undone"


def origin_cert(c: Client, tls_dir: Path, run: Callable = RUN) -> str:
    """A key made in `tls_dir`, a request for it sent to Cloudflare, and the
    certificate written beside the key. The key never leaves `tls_dir`."""
    pem, key = tls_dir / "origin.pem", tls_dir / "origin.key"
    if pem.exists() and key.exists() and pem.stat().st_size and key.stat().st_size:
        c.out(f"the origin certificate: there already, {pem}")
        return "unchanged"
    if c.dry:
        c.out(f"would: a key made in {tls_dir}, and Cloudflare's origin certificate for "
              f"{', '.join(WIDGET_DOMAINS)}, valid {CERT_DAYS // 365} years")
        return "created"
    new_key = tls_dir / "origin.key.new"
    old_mask = os.umask(0o077)
    try:
        made = run(["openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", str(new_key),
                    "-subj", f"/CN={SITE}"], capture_output=True, text=True)
    finally:
        os.umask(old_mask)
    if made.returncode != 0 or "BEGIN CERTIFICATE REQUEST" not in made.stdout:
        new_key.unlink(missing_ok=True)
        raise CloudflareError(f"openssl could not make the key and its request: {made.stderr.strip()[-200:]}")
    try:
        cert = c.call("POST", "/certificates", {"csr": made.stdout, "hostnames": WIDGET_DOMAINS,
                                                "request_type": "origin-rsa", "requested_validity": CERT_DAYS})
    except CloudflareError:
        new_key.unlink(missing_ok=True)
        raise
    if not cert or "BEGIN CERTIFICATE" not in (cert.get("certificate") or ""):
        new_key.unlink(missing_ok=True)
        raise CloudflareError("POST /certificates: no certificate in Cloudflare's answer")
    pem.write_text(cert["certificate"].rstrip("\n") + "\n", encoding="utf-8")
    os.chmod(new_key, 0o600)
    new_key.replace(key)
    c.out(f"the origin certificate: made for {', '.join(WIDGET_DOMAINS)}, until {cert.get('expires_on', '?')}, "
          f"in {pem}; its key in {key}, mode 600")
    c.out("a running edge reads them on: docker compose -p caro-edge -f compose.edge.yml restart")
    return "created"


def status(c: Client, zone: str, account: str) -> None:
    c.out(f"the zone {ZONE}: its id is {zone}; on the server, for the edge's purge (PHASE4_SETUP, step 2):")
    for env in ("production", "staging"):
        c.out(f"  bash /opt/caro/deploy/set-env.sh {env} CARO_CF_ZONE_ID={zone}")
    for name in (SITE, STAGING):
        have = records(c, zone, name)
        c.out(f"{name}: " + (", ".join(f"{r['type']} {r['content']}"
                                       f"{' proxied' if r.get('proxied') else ' DNS only'}" for r in have)
                             or "no record"))
    _entry, rules, at = cache_rules(c, zone)
    c.out(f"cache rules: {len(rules)}, " + ("CARO's not among them" if at is None else
                                           f"CARO's number {at + 1}" + "".join(
                                               f", and «{later}» after it switches the cache off"
                                               for later in _overridden(rules, at))))
    widgets = c.call("GET", f"/accounts/{account}/challenges/widgets", query={"per_page": 50}) or []
    mine = [w for w in widgets if w.get("name") == WIDGET]
    c.out("the Turnstile widget: " + (f"site key {mine[0]['sitekey']}" if mine else "none"))


# The address `ip a` shows inside a network, which is not the server's.
LOCAL = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                                                 "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
                                                 "0.0.0.0/8"))


def _ip(text: str) -> str:
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an address: {text}") from None
    if ip.version != 4 or any(ip in n for n in LOCAL) or ip.is_multicast:
        raise argparse.ArgumentTypeError(f"not the server's public IPv4 address: {text}")
    return str(ip)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=("status", "staging", "cache", "turnstile", "switch", "undo-switch",
                                        "origin-cert"))
    ap.add_argument("--ip", type=_ip, help="the server's public IPv4 address")
    ap.add_argument("--tls-dir", type=Path, default=TLS_DIR, help="where origin-cert writes (/etc/caro/tls)")
    ap.add_argument("--dry-run", action="store_true", help="say what would change, change nothing")
    return ap


def main(argv: list[str] | None = None, env=None, opener: Callable | None = None,
         out: Callable[[str], None] = print, here: Path | None = None, run: Callable = RUN) -> int:
    a = parser().parse_args(argv)
    env = os.environ if env is None else env
    token = (env.get("CLOUDFLARE_API_TOKEN") or "").strip()
    if not token:
        print("cloudflare-setup: CLOUDFLARE_API_TOKEN is not set (see the top of this file)", file=sys.stderr)
        return 2
    if a.command == "staging" and not a.ip:
        print("cloudflare-setup: staging needs --ip, the server's IPv4 address", file=sys.stderr)
        return 2
    if a.command == "origin-cert" and not a.tls_dir.is_dir():
        print(f"cloudflare-setup: no directory {a.tls_dir} (PHASE1_SETUP, step 2 makes it)", file=sys.stderr)
        return 2
    here = Path.cwd() if here is None else here
    c = Client(token, opener, a.dry_run, out)
    try:
        zone, account = zone_of(c)
        if a.command == "status":
            status(c, zone, account)
        elif a.command == "staging":
            ensure_a(c, zone, STAGING, a.ip)
        elif a.command == "cache":
            ensure_cache_rule(c, zone)
        elif a.command == "turnstile":
            ensure_widget(c, account, here / SECRET_FILE)
        elif a.command == "switch":
            switch(c, zone, a.ip or staging_address(c, zone), here / UNDO_FILE)
        elif a.command == "origin-cert":
            origin_cert(c, a.tls_dir, run)
        else:
            undo_switch(c, zone, here / UNDO_FILE)
    except CloudflareError as e:
        hint = (f"; this command needs {NEEDS[a.command]}, and the zone noxioai.com among the token's"
                if e.status == 403 or 10000 in e.codes else "")
        print(f"cloudflare-setup: stopped: {e}{hint}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
