#!/usr/bin/env python3
"""The owner's Grafana steps, done through the stack's own API with a token
of the owner's (docs/PHASE7_SETUP.md, steps 3 and 4).

    read -r GRAFANA_URL && export GRAFANA_URL
    read -rs GRAFANA_TOKEN && export GRAFANA_TOKEN
    python3 scripts/grafana_setup.py <command> [--dry-run]

The first line reads the stack's address, https:// and the stack's name
.grafana.net; the second the token, without showing it or keeping it in the
shell's history: paste each, then Enter.

    status      what the stack holds of the rest, read only
    dashboard   deploy/grafana/caro.json, on the stack's Prometheus (step 3)
    alerts      deploy/grafana/alerts.yml's groups, as Grafana-managed rules in
                the folder CARO, on the same Prometheus (step 4)
    telegram    the contact point caro-telegram -- the bot and the chat of the
                server's alerts -- and two routes to it: severity=page at
                once, severity=ticket grouped every three hours (step 4)
    test        a test message to caro-telegram, sent by Grafana itself
    all         dashboard, alerts, telegram and test, in that order

What it reads from the environment, and sends nowhere but the stack:
- GRAFANA_URL, the stack's address, https unless it is this machine's own;
- GRAFANA_TOKEN, a service account's token: in the stack's Grafana,
  Administration -> Users and access -> Service accounts -> Add service
  account, role Admin, then Add service account token;
- for telegram and all, CARO_ALERT_TELEGRAM_TOKEN and CARO_ALERT_TELEGRAM_CHAT,
  the server's bot and chat (PHASE3_SETUP, step 2), or with --env-file the
  same two lines from that file: run on the server, --env-file
  /etc/caro/production.env reads them where they are.

The alerts become Grafana-managed rules, by Grafana's own conversion of
Prometheus rules, which Grafana 13.3 has, the version this was tried on:
they then go out through the same contact point and routes as everything
else the stack sends. Where a
stack does not convert them, the script says so, and mimirtool loads
alerts.yml as its first lines say.

No token is printed. Each command reads before it writes, and with
--dry-run writes nothing. Run again, the dashboard and the routes are found
unchanged and written no more. The alerts' groups are loaded again, which
changes nothing in a group that is the same. The contact point is written
again, since Grafana never shows the bot's token back. A refusal stops it
with Grafana's own words.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = "deploy/grafana/caro.json"
ALERTS = "deploy/grafana/alerts.yml"
FOLDER = "CARO"
CONVERT = "/api/convert/prometheus/config/v1/rules"
CONTACT = "caro-telegram"
# The two routes, in front of any the stack has. Each duration is written as
# Grafana writes it back, so that a second run finds them the same.
ROUTES = [
    {"receiver": CONTACT, "object_matchers": [["grafana_folder", "=", FOLDER], ["severity", "=", "page"]],
     "group_by": ["alertname", "env"], "group_wait": "30s", "group_interval": "5m", "repeat_interval": "4h"},
    {"receiver": CONTACT, "object_matchers": [["grafana_folder", "=", FOLDER], ["severity", "=", "ticket"]],
     "group_by": ["alertname", "env"], "group_wait": "10m", "group_interval": "3h", "repeat_interval": "1d"},
]
RECEIVERS = ("/apis/notifications.alerting.grafana.app/v1beta1/namespaces/{ns}/receivers",
             "/apis/notifications.alerting.grafana.app/v0alpha1/namespaces/{ns}/receivers")
# Written through the API, yet editable in Grafana's own pages afterwards.
EDITABLE = {"X-Disable-Provenance": "true"}
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
OPENER: Callable = urllib.request.urlopen


class GrafanaError(RuntimeError):
    """Grafana refused, or did not answer as its API does. The message holds
    Grafana's words and never a token."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class Client:
    def __init__(self, url: str, token: str, opener: Callable | None = None, dry: bool = False,
                 out: Callable[[str], None] = print) -> None:
        self._url, self._token = url.rstrip("/"), token
        self._opener, self.dry, self.out = opener or OPENER, dry, out

    def call(self, method: str, path: str, body=None, query: dict | None = None,
             headers: dict | None = None, missing_ok: bool = False):
        """The answer of one call, parsed; None for a 404 where `missing_ok`.
        A body that is bytes is sent as it is; any other, as JSON."""
        url = self._url + path + ("?" + urllib.parse.urlencode(query) if query else "")
        if isinstance(body, bytes) or body is None:
            data = body
        else:
            data = json.dumps(body).encode("utf-8")
        h = {"Authorization": f"Bearer {self._token}", "Accept": "application/json",
             "Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with self._opener(req, timeout=30) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404 and missing_ok:
                return None
            try:
                answer = json.loads(e.read().decode("utf-8"))
                words = answer.get("message") or answer.get("error") or f"HTTP {e.code}"
            except Exception:          # noqa: BLE001 -- not Grafana's JSON
                words = f"HTTP {e.code}"
            raise GrafanaError(f"{method} {path}: {words}", e.code) from None
        except Exception as e:         # noqa: BLE001 -- no answer at all
            raise GrafanaError(f"{method} {path}: no answer ({type(e).__name__})") from None
        try:
            return json.loads(raw.decode("utf-8")) if raw.strip() else None
        except ValueError:
            raise GrafanaError(f"{method} {path}: an answer that is not JSON") from None

    def write(self, method: str, path: str, body=None, what: str = "", headers: dict | None = None):
        """A change: said and made, or with --dry-run only said."""
        if self.dry:
            self.out(f"would: {what}")
            return None
        result = self.call(method, path, body, headers=headers)
        self.out(what)
        return result


def rule_groups(text: str) -> list[tuple[str, str]]:
    """Each group of a Prometheus rule file, as the document the ruler API
    takes: its `  - name:` line made `name:`, and the group's other lines
    dedented by four. The file's own layout is the contract, which a group's
    line that is not indented under it breaks loudly."""
    lines = text.split("\n")
    if "groups:" not in lines:
        raise GrafanaError(f"{ALERTS}: no `groups:` line")
    groups: list[list[str]] = []
    for line in lines[lines.index("groups:") + 1:]:
        if line.startswith("  - name: "):
            groups.append([line[4:]])
        elif not groups:
            if line.strip() and not line.lstrip().startswith("#"):
                raise GrafanaError(f"{ALERTS}: a line before the first group: {line!r}")
        elif line.strip() and not line.startswith("    "):
            raise GrafanaError(f"{ALERTS}: a line outside its group: {line!r}")
        else:
            groups[-1].append(line[4:])
    if not groups:
        raise GrafanaError(f"{ALERTS}: no group")
    return [(g[0].split(":", 1)[1].strip(), "\n".join(g).rstrip("\n") + "\n") for g in groups]


def pick_datasource(c: Client, name: str | None = None) -> tuple[str, str]:
    """The stack's Prometheus: the one named, the only one, or the only one
    whose name ends -prom, which is how Grafana Cloud names a stack's own."""
    proms = [d for d in c.call("GET", "/api/datasources") or [] if d.get("type") == "prometheus"]
    names = ", ".join(d["name"] for d in proms) or "none"
    if name:
        chosen = [d for d in proms if d["name"] == name]
    elif len(proms) == 1:
        chosen = proms
    else:
        chosen = [d for d in proms if d["name"].endswith("-prom")]
    if len(chosen) != 1:
        raise GrafanaError(f"which Prometheus? The stack has: {names}. Name it with --datasource")
    return chosen[0]["uid"], chosen[0]["name"]


def _same_dashboard(have: dict, want: dict) -> bool:
    keep = lambda d: {k: v for k, v in d.items() if k not in ("id", "version")}   # noqa: E731
    return keep(have) == keep(want)


def ensure_dashboard(c: Client, ds_uid: str, ds_name: str, root: Path) -> str:
    want = json.loads((root / DASHBOARD).read_text(encoding="utf-8"))
    for v in want.get("templating", {}).get("list", []):
        if v.get("type") == "datasource":
            v["current"] = {"selected": True, "text": ds_name, "value": ds_uid}
    have = c.call("GET", f"/api/dashboards/uid/{want['uid']}", missing_ok=True)
    if have and _same_dashboard(have.get("dashboard") or {}, want):
        c.out(f"the dashboard: there already, on {ds_name}")
        return "unchanged"
    c.write("POST", "/api/dashboards/db",
            {"dashboard": {**want, "id": None}, "overwrite": True, "message": "scripts/grafana_setup.py"},
            f"the dashboard {want['title']}: {'brought to the file' if have else 'made'}, on {ds_name}")
    return "changed" if have else "created"


def _folder_groups(c: Client) -> set[str]:
    folders = [f for f in c.call("GET", "/api/folders") or [] if f.get("title") == FOLDER]
    if not folders:
        return set()
    rules = c.call("GET", "/api/v1/provisioning/alert-rules") or []
    return {r["ruleGroup"] for r in rules if r.get("folderUID") == folders[0]["uid"]}


def load_alerts(c: Client, ds_uid: str, ds_name: str, root: Path) -> list[str]:
    groups = rule_groups((root / ALERTS).read_text(encoding="utf-8"))
    before = _folder_groups(c)
    for name, doc in groups:
        try:
            c.write("POST", f"{CONVERT}/{urllib.parse.quote(FOLDER)}", doc.encode("utf-8"),
                    f"the alerts: the group {name} loaded into the folder {FOLDER}, on {ds_name}",
                    headers={"Content-Type": "application/yaml", "X-Grafana-Alerting-Datasource-UID": ds_uid})
        except GrafanaError as e:
            if e.status != 404:
                raise
            raise GrafanaError(f"this Grafana does not convert Prometheus rules ({e}): load {ALERTS} with "
                               "mimirtool instead, as its first lines say", 404) from None
    for name in sorted(before - {n for n, _ in groups}):
        c.write("DELETE", f"{CONVERT}/{urllib.parse.quote(FOLDER)}/{urllib.parse.quote(name)}", None,
                f"the alerts: the group {name}, no longer in {ALERTS}, taken away")
    return [n for n, _ in groups]


def ensure_telegram(c: Client, bot: str, chat: str) -> None:
    have = c.call("GET", "/api/v1/provisioning/contact-points", query={"name": CONTACT}) or []
    body = {"name": CONTACT, "type": "telegram", "settings": {"bottoken": bot, "chatid": chat},
            "disableResolveMessage": False}
    if have:
        c.write("PUT", f"/api/v1/provisioning/contact-points/{have[0]['uid']}", {**body, "uid": have[0]["uid"]},
                f"the contact point {CONTACT}: written again, to the chat {chat}", headers=EDITABLE)
    else:
        c.write("POST", "/api/v1/provisioning/contact-points", body,
                f"the contact point {CONTACT}: made, to the chat {chat}", headers=EDITABLE)
    tree = c.call("GET", "/api/v1/provisioning/policies") or {}
    routes = tree.get("routes") or []
    others = [r for r in routes if r.get("receiver") != CONTACT]
    want = ROUTES + others
    if routes == want:
        c.out(f"the routes to {CONTACT}: there already")
        return
    c.write("PUT", "/api/v1/provisioning/policies",
            {**{k: v for k, v in tree.items() if k != "provenance"}, "routes": want},
            f"the routes: severity=page and severity=ticket to {CONTACT}, before the {len(others)} other(s)",
            headers=EDITABLE)


def _receiver(c: Client):
    ns = (c.call("GET", "/api/frontend/settings") or {}).get("namespace") or "default"
    for base in RECEIVERS:
        got = c.call("GET", base.format(ns=ns), missing_ok=True)
        if got is not None:
            for item in got.get("items") or []:
                if (item.get("spec") or {}).get("title") == CONTACT:
                    return base.format(ns=ns), item
            raise GrafanaError(f"no contact point {CONTACT}: run telegram first")
    raise GrafanaError(f"this Grafana does not test from its API: Alerting -> Contact points -> {CONTACT} -> Test")


def test_telegram(c: Client) -> None:
    if c.dry:
        c.out(f"would: ask Grafana to send a test to {CONTACT}")
        return
    base, item = _receiver(c)
    integration = item["spec"]["integrations"][0]
    answer = c.write("POST", f"{base}/{item['metadata']['name']}/test", {"integration": integration},
                     f"the test: asked of Grafana, to {CONTACT}")
    if not isinstance(answer, dict) or answer.get("status") != "success":
        words = answer.get("error") if isinstance(answer, dict) else None
        raise GrafanaError(f"Grafana could not send the test: {words or 'no reason given'}")
    c.out("the test: sent by Grafana; it is in the chat when the bot and the chat are right")


def status(c: Client, datasource: str | None) -> None:
    health = c.call("GET", "/api/health") or {}
    c.out(f"Grafana {health.get('version', '?')}")
    try:
        uid, name = pick_datasource(c, datasource)
        c.out(f"the stack's Prometheus: {name}")
    except GrafanaError as e:
        c.out(str(e))
    board = c.call("GET", "/api/dashboards/uid/caro", missing_ok=True)
    c.out("the dashboard: " + ("there" if board else "none"))
    groups = _folder_groups(c)
    c.out(f"the alerts in the folder {FOLDER}: " + (", ".join(sorted(groups)) or "none"))
    have = c.call("GET", "/api/v1/provisioning/contact-points", query={"name": CONTACT}) or []
    c.out(f"the contact point {CONTACT}: " + (f"to the chat {have[0]['settings'].get('chatid')}" if have else "none"))
    routes = (c.call("GET", "/api/v1/provisioning/policies") or {}).get("routes") or []
    ours = [r for r in routes if r.get("receiver") == CONTACT]
    c.out(f"the routes to {CONTACT}: " + ("as this script makes them" if routes[:len(ROUTES)] == ROUTES
                                           else f"{len(ours)}, not as this script makes them" if ours else "none"))


def env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines, as compose reads the server's env files."""
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    return values


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=("status", "dashboard", "alerts", "telegram", "test", "all"))
    ap.add_argument("--datasource", help="the Prometheus to use, by name, when the stack has several")
    ap.add_argument("--env-file", type=Path, help="a file with CARO_ALERT_TELEGRAM_TOKEN and _CHAT")
    ap.add_argument("--dry-run", action="store_true", help="say what would change, change nothing")
    return ap


def main(argv: list[str] | None = None, env=None, opener: Callable | None = None,
         out: Callable[[str], None] = print, root: Path = ROOT) -> int:
    a = parser().parse_args(argv)
    env = os.environ if env is None else env
    url, token = (env.get("GRAFANA_URL") or "").strip(), (env.get("GRAFANA_TOKEN") or "").strip()
    if not url or not token:
        print("grafana-setup: GRAFANA_URL and GRAFANA_TOKEN are needed (see the top of this file)", file=sys.stderr)
        return 2
    u = urllib.parse.urlparse(url)
    if not (u.scheme == "https" or (u.scheme == "http" and u.hostname in LOCAL_HOSTS)):
        print(f"grafana-setup: {url} is not https: the token is sent only over https", file=sys.stderr)
        return 2
    bot = chat = ""
    if a.command in ("telegram", "all"):
        values = env_file(a.env_file) if a.env_file else {}
        bot = (env.get("CARO_ALERT_TELEGRAM_TOKEN") or values.get("CARO_ALERT_TELEGRAM_TOKEN") or "").strip()
        chat = (env.get("CARO_ALERT_TELEGRAM_CHAT") or values.get("CARO_ALERT_TELEGRAM_CHAT") or "").strip()
        if not bot or not chat:
            print("grafana-setup: telegram needs CARO_ALERT_TELEGRAM_TOKEN and CARO_ALERT_TELEGRAM_CHAT",
                  file=sys.stderr)
            return 2
    c = Client(url, token, opener, a.dry_run, out)
    try:
        if a.command == "status":
            status(c, a.datasource)
            return 0
        if a.command in ("dashboard", "alerts", "all"):
            ds_uid, ds_name = pick_datasource(c, a.datasource)
            if a.command in ("dashboard", "all"):
                ensure_dashboard(c, ds_uid, ds_name, root)
            if a.command in ("alerts", "all"):
                load_alerts(c, ds_uid, ds_name, root)
        if a.command in ("telegram", "all"):
            ensure_telegram(c, bot, chat)
        if a.command in ("test", "all"):
            test_telegram(c)
    except GrafanaError as e:
        hint = ("; the service account needs the Admin role, and its token to be whole"
                if e.status in (401, 403) else "")
        print(f"grafana-setup: stopped: {e}{hint}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
