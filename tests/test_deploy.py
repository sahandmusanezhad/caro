"""The images and the server's files keep the promises the deploy rests on.

    Run: PYTHONPATH=. python3 tests/test_deploy.py

WHY THIS SUITE EXISTS

CARO runs on a server it reaches only through Cloudflare (docs/PHASE1_SETUP.md,
the plan's phase 1). Several of the things that keep it safe there are lines
in files no other suite reads, and each fails silently: an allow list read
from the client's address instead of the connection's admits everyone; a
compose file that publishes the API's port bypasses the edge; an image that
runs as root, or a secret given a default, is a mistake that works. Each has
a row here, and so do the role dispatcher of the one image and the script
the workflow waits on a deploy with.

It needs nothing beyond Python. Building and running the images is the
images workflow's job (.github/workflows/images.yml), which builds both,
runs the API's suites inside its image and reads them together.
"""
import io
import ipaddress
import os
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import deploy_wait  # noqa: E402
from webapp import role  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILS.append(name)


def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def blocks(compose: str) -> dict[str, str]:
    """The services of a compose file, each with the lines under it."""
    out, name, lines = {}, None, []
    section = None
    for line in compose.splitlines():
        if re.match(r"^\S", line):
            section = line.split(":")[0]
            continue
        m = re.match(r"^  ([a-z][a-z0-9-]*):\s*$", line)
        if section == "services" and m:
            if name:
                out[name] = "\n".join(lines)
            name, lines = m.group(1), []
        elif section == "services" and name:
            lines.append(line)
    if name:
        out[name] = "\n".join(lines)
    return out


# ---------------------------------------------------------------------------
print("\nthe one image's roles")

_a = role.api_argv({})
_b = role.api_argv({"CARO_API_PORT": "9000", "CARO_FORWARDED_ALLOW_IPS": "172.31.250.0/24"})
_bad = None
try:
    role.api_argv({"CARO_API_PORT": "eighty"})
except SystemExit as e:
    _bad = str(e)
check("DP1: the api role serves webapp.api.main:app on 8000, one worker, no server header, and "
      "believes no forwarded header unless told whose; a port that is not one stops it",
      _a[:2] == ["uvicorn", "webapp.api.main:app"] and _a[_a.index("--port") + 1] == "8000"
      and _a[_a.index("--workers") + 1] == "1" and "--no-server-header" in _a
      and "--no-proxy-headers" in _a and "--proxy-headers" not in _a
      and _b[_b.index("--port") + 1] == "9000" and "--proxy-headers" in _b
      and _b[_b.index("--forwarded-allow-ips") + 1] == "172.31.250.0/24"
      and _bad is not None and "eighty" in _bad, str((_a, _b, _bad)))

_ran = []
_rc_api = role.main(["api"], env={}, execvp=lambda f, a: _ran.append((f, a)))


class _Ok:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _refused(*a, **k):
    raise ConnectionRefusedError("nothing listens")


_err = io.StringIO()
_old_err, sys.stderr = sys.stderr, _err
try:
    _rc_unknown = role.main(["dance"], env={})
finally:
    sys.stderr = _old_err
check("DP2: a role per command -- api becomes uvicorn itself, healthcheck answers by /api/health, "
      "and a role it does not know is refused with the ones it does",
      _rc_api == 0 and len(_ran) == 1 and _ran[0][0] == "uvicorn" and _ran[0][1] == role.api_argv({})
      and role.healthy(8000, opener=lambda *a, **k: _Ok()) is True
      and role.healthy(8000, opener=_refused) is False
      and _rc_unknown == 2 and all(r in _err.getvalue() for r in role.ROLES),
      str((_rc_api, _ran, _rc_unknown, _err.getvalue())))

# ---------------------------------------------------------------------------
print("\nthe images")

_df = text("Dockerfile")
_stages = re.findall(r"^FROM (\S+)(?: AS (\S+))?", _df, re.MULTILINE)
_api = _df.split("FROM api AS test")[0]
_copied = [c.split()[0:-1] for c in re.findall(r"^COPY (?!--)(.+)$", _api, re.MULTILINE)]
_sources = [s for c in _copied for s in c]
_ignore = text(".dockerignore").split()
check("DP3: the API's image is its last stage, runs as a user of its own with a health check and "
      "the role dispatcher, copies only what exists and nothing a collection writes, and keeps "
      ".env, the snapshots and the inbox out of its context",
      _stages[-1] == ("api", "") and ("python:3.12-slim-bookworm", "api") in _stages
      and re.search(r"^USER caro$", _api, re.MULTILINE) is not None
      and "HEALTHCHECK" in _api and 'ENTRYPOINT ["python", "-m", "webapp.role"]' in _api
      and all((ROOT / s).exists() for s in _sources)
      and not any("snapshots" in s or s.startswith("tests") for s in _sources)
      and all(x in _ignore for x in (".env", ".env.*", "data/snapshots", "data/inbox")),
      str((_stages, _sources)))

_sdf = text("webapp/web/Dockerfile")
_final = _sdf.rsplit("FROM node:22-bookworm-slim\n", 1)[1]
check("DP4: the site's image runs Next.js's standalone server as the uid that owns nothing, its "
      "health check asks the port it serves, and the four settings Next.js writes at build time "
      "are build arguments with nothing given by default but the API's container, the workflow "
      "handing each the repository's variable",
      "USER node" in _final and 'CMD ["node", "server.js"]' in _final
      and "process.env.PORT" in _final and "CARO_SITE_STANDALONE=1" in _sdf
      and "ARG CARO_API=http://api:8000" in _sdf and "ARG NEXT_PUBLIC_SENTRY_DSN=\n" in _sdf
      and "ARG NEXT_PUBLIC_SELLER_LISTINGS=\n" in _sdf and "ARG NEXT_PUBLIC_TURNSTILE_SITE_KEY=\n" in _sdf
      and all(f"{k}: ${{{{ vars.{k} }}}}" in text(".github/workflows/images.yml")
              and f"--build-arg {k}" in text(".github/workflows/images.yml")
              for k in ("NEXT_PUBLIC_SENTRY_DSN", "NEXT_PUBLIC_SELLER_LISTINGS", "NEXT_PUBLIC_TURNSTILE_SITE_KEY"))
      and "CARO_SITE_STANDALONE === '1'" in text("webapp/web/next.config.mjs"),
      _final[:200])

# ---------------------------------------------------------------------------
print("\nthe server's compose files")

_vps = text("compose.vps.yml")
_svc = blocks(_vps)
_hard = all(("read_only: true" in _svc[s] and "cap_drop: [ALL]" in _svc[s]
             and "no-new-privileges:true" in _svc[s]) for s in ("api", "site", "catalog-load", "alerts"))
check("DP5: an environment publishes no port, runs its API, its site and its alerts read-only with "
      "every capability dropped, takes its images from its env file and its password with no default, "
      "joins the edge under api-<env> and site-<env> -- the alerts on no network but its own -- and has "
      "a seller store only where its file switches one on",
      set(_svc) == {"postgres", "catalog-load", "api", "site", "alerts", "edge-purge", "observe"}
      and 'command: ["alerts"]' in _svc["alerts"]
      and not re.search(r"^\s+(- edge|edge:)\s*$", _svc["alerts"], re.MULTILINE)
      and 'profiles: ["purge"]' in _svc["edge-purge"] and "read_only: true" in _svc["edge-purge"]
      and "cap_drop: [ALL]" in _svc["edge-purge"] and "- purge:/var/lib/caro-purge" in _svc["edge-purge"]
      and "CARO_OPS_URL: postgresql://" in _svc["api"] and "CARO_OPS_URL: postgresql://" in _svc["alerts"]
      and not any(re.search(r"^\s+ports:", b, re.MULTILINE) for b in _svc.values())
      and _hard and "${CARO_API_IMAGE:?" in _svc["api"] and "${CARO_SITE_IMAGE:?" in _svc["site"]
      and "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?" in _svc["postgres"]
      and ":-" not in _vps.split("POSTGRES_PASSWORD")[1].split("\n")[0]
      and 'aliases: ["api-${CARO_ENV:?' in _svc["api"] and 'aliases: ["site-${CARO_ENV}"]' in _svc["site"]
      and re.search(r"edge:\n\s+external: true\n\s+name: caro_edge", _vps) is not None
      and 'CARO_TRUST_PROXY: "1"' in _svc["api"]
      and "DATABASE_URL: ${CARO_SELLER_STORE:+postgresql://" in _svc["api"],
      str(sorted(_svc)))

_obs = _svc.get("observe", "")
_alloy = text("deploy/alloy/config.alloy")
_alloy_code = "\n".join(l for l in _alloy.splitlines() if not l.lstrip().startswith("//"))
check("DP20: the collector is Alloy at a version, started only where the env file names its profile, "
      "as its own user, read-only with every capability dropped, on the environment's own network alone, its usage "
      "reports off; it reads /metrics at the API and writes to the address, user and token the env file "
      "gives it, with nothing of theirs in a file and no log read -- and without them the environment "
      "still starts",
      'profiles: ["observe"]' in _obs and re.search(r"image: grafana/alloy:v\d+\.\d+\.\d+\n", _obs) is not None
      and 'user: "473:473"' in _obs
      and "--disable-reporting" in _obs and "- ./deploy/alloy/config.alloy:/etc/alloy/config.alloy:ro" in _obs
      and "read_only: true" in _obs and "cap_drop: [ALL]" in _obs and "no-new-privileges:true" in _obs
      and re.search(r"networks:\n\s+- internal\n", _obs) is not None and "edge" not in _obs
      and "CARO_METRICS_TARGET: api:8000" in _obs
      and all(f"{k}: ${{{k}:-}}" in _obs for k in ("GRAFANA_CLOUD_PROM_URL", "GRAFANA_CLOUD_PROM_USER",
                                                    "GRAFANA_CLOUD_TOKEN"))
      and 'metrics_path    = "/metrics"' in _alloy_code and 'sys.env("CARO_METRICS_TARGET")' in _alloy_code
      and 'url = sys.env("GRAFANA_CLOUD_PROM_URL")' in _alloy_code
      and 'password = sys.env("GRAFANA_CLOUD_TOKEN")' in _alloy_code
      and "loki" not in _alloy_code and "http" not in _alloy_code.replace("prometheus", ""),
      _obs[:400])

_rules = text("deploy/grafana/alerts.yml")
_rtest = text("deploy/grafana/alerts_test.yml")
_ci = text(".github/workflows/ci.yml")
_metrics_src = text("webapp/api/metrics.py")
_alerts = re.findall(r"^\s+- alert: (\w+)$", _rules, re.MULTILINE)
_used = set(re.findall(r"\b(caro_[a-z_]+)", _rules))
_exposed = {m for m in re.findall(r"\b(caro_[a-z_]+)", _metrics_src)}
_exposed |= {f"caro_request_seconds_{s}" for s in ("bucket", "sum", "count")}
_blocks_r = re.split(r"\n\s+- alert: ", _rules)[1:]
check("DP21: every alert reads only what /metrics says, carries a severity and a summary, and is tried by "
      "the alerts' own tests, which CI runs by promtool at a version; the availability alerts count the "
      "public reads alone and the search's the bucket at 300 ms",
      len(_alerts) == 7 and _used <= _exposed
      and all("severity: page" in b or "severity: ticket" in b for b in _blocks_r)
      and all("summary:" in b for b in _blocks_r)
      and all(re.search(rf"^\s+alertname: {a}$", _rtest, re.MULTILINE) for a in _alerts)
      and re.search(r"prom/prometheus:v\d+\.\d+\.\d+ test rules alerts_test\.yml", _ci) is not None
      and _rules.count('route=~"/api/(search|search/reweight|models|model|corpus|compare|health|listing/.+)"') == 8
      and 'le="0.3"' in _rules and "0.3" in _metrics_src.split("BUCKETS = (")[1].split(")")[0],
      str((_alerts, sorted(_used - _exposed))))

_dash = json.loads(text("deploy/grafana/caro.json"))
_targets = [t for pnl in _dash["panels"] for t in pnl["targets"]]
_dexprs = [t["expr"] for t in _targets]
_dused = set(re.findall(r"\b(caro_[a-z_]+)", " ".join(_dexprs)))
_dvars = {v["name"]: v for v in _dash["templating"]["list"]}
_titles = {pnl["title"]: pnl for pnl in _dash["panels"]}
_steps = lambda pnl: [st.get("value") for st in
                      pnl["fieldConfig"]["defaults"].get("thresholds", {}).get("steps", [])]
check("DP22: the dashboard reads only what /metrics says, each expression for the environment chosen and "
      "from the Prometheus chosen; it shows the three SLOs against their targets -- 99.5% of the public "
      "reads, the alerts' own, and 95% of searches within the bucket at 300 ms -- and the API's answer to "
      "its collector",
      _dash.get("uid") == "caro" and _dused <= _exposed and len(_dexprs) >= 10
      and all('env="$env"' in e for e in _dexprs)
      and all(t["datasource"] == {"type": "prometheus", "uid": "${datasource}"} for t in _targets)
      and _dvars["datasource"]["type"] == "datasource" and _dvars["datasource"]["query"] == "prometheus"
      and _dvars["env"]["definition"] == 'label_values(up{job="caro-api"}, env)'
      and 0.995 in _steps(_titles["Availability, 30 days (SLO 99.5%)"])
      and 0.95 in _steps(_titles["Searches within 300 ms, 30 days (SLO 95%)"])
      and 'le="0.3"' in _titles["Searches within 300 ms, 30 days (SLO 95%)"]["targets"][0]["expr"]
      and 'route=~"/api/(search|search/reweight|models|model|corpus|compare|health|listing/.+)"'
      in _titles["Availability, 30 days (SLO 99.5%)"]["targets"][0]["expr"]
      and any("since the last collected run" in tl.lower() for tl in _titles)
      and 'up{job="caro-api", env="$env"}' in _titles["The API answers its collector"]["targets"][0]["expr"],
      str(sorted(_dused - _exposed)))

# ---------------------------------------------------------------------------
print("\nthe owner's Cloudflare steps, through its API with the owner's token")
import contextlib as _ctx_cf                                            # noqa: E402
import io as _io_cf                                                     # noqa: E402
import urllib.error as _ue_cf                                           # noqa: E402
import urllib.parse as _up_cf                                           # noqa: E402

from scripts import cloudflare_setup as _cf                             # noqa: E402

_CF_TOKEN = "made-up-cloudflare-token-0123456789"


class _FakeCloudflare:
    """Cloudflare's API as the script uses it, kept in memory; every call logged."""

    def __init__(self, records=(), rules=None, widgets=(), refuse_batch=False, refuse_cert=False,
                 ignore_filter=False, zones=None):
        self.records = [dict(r) for r in records]
        self.rules = rules              # None: the zone has no entry point
        self.widgets = [dict(w) for w in widgets]
        self.refuse_batch, self.refuse_cert, self.certs = refuse_batch, refuse_cert, []
        self.ignore_filter = ignore_filter      # a list that answers with every name's records
        self.zones = [{"id": "z1", "name": "noxioai.com", "account": {"id": "a1"}}] if zones is None else zones
        self.calls, self.seq = [], 0

    def _ok(self, result):
        body = json.dumps({"success": True, "errors": [], "result": result}).encode()
        return _ctx_cf.nullcontext(type("R", (), {"read": lambda _s: body})())

    def _refuse(self, req, code, message):
        raise _ue_cf.HTTPError(req.full_url, 400, "Bad Request", {}, _io_cf.BytesIO(json.dumps(
            {"success": False, "errors": [{"code": code, "message": message}]}).encode()))

    def _post_record(self, body):
        self.seq += 1
        self.records.append({**body, "id": f"r{self.seq}"})
        return self.records[-1]

    def __call__(self, req, timeout=30):
        u = _up_cf.urlparse(req.full_url)
        q = dict(_up_cf.parse_qsl(u.query))
        body = json.loads(req.data) if req.data else None
        m, path = req.get_method(), u.path.removeprefix("/client/v4")
        self.calls.append((m, path, body, req.get_header("Authorization"), u.netloc))
        if path == "/zones" and m == "GET":
            return self._ok(self.zones)
        if path == "/zones/z1/dns_records":
            if m == "GET":
                return self._ok([r for r in self.records if self.ignore_filter or r["name"] == q.get("name.exact")])
            return self._ok(self._post_record(body))
        if path == "/zones/z1/dns_records/batch" and m == "POST":
            if self.refuse_batch:       # Cloudflare's one transaction: nothing of it is made
                self._refuse(req, 81053, "An A, AAAA, or CNAME record with that host already exists.")
            gone = {d["id"] for d in body.get("deletes", [])}
            self.records = [r for r in self.records if r["id"] not in gone]
            return self._ok({"deletes": [{"id": i} for i in sorted(gone)],
                             "posts": [self._post_record(r) for r in body.get("posts", [])]})
        if path.startswith("/zones/z1/dns_records/"):
            rid = path.rsplit("/", 1)[1]
            if m == "DELETE":
                self.records = [r for r in self.records if r["id"] != rid]
                return self._ok({"id": rid})
            for r in self.records:
                if r["id"] == rid:
                    r.update(body)
                    return self._ok(r)
        if path == "/zones/z1/rulesets/phases/http_request_cache_settings/entrypoint":
            if m == "GET":
                if self.rules is None:
                    raise _ue_cf.HTTPError(req.full_url, 404, "Not Found", {}, _io_cf.BytesIO(
                        b'{"success": false, "errors": [{"message": "could not find entrypoint ruleset"}]}'))
                return self._ok({"id": "rs1", "phase": "http_request_cache_settings", "rules": self.rules})
            self.rules = [{**r, "id": r.get("id", f"rule{i}"), "version": "1"} for i, r in enumerate(body["rules"])]
            return self._ok({"id": "rs1", "rules": self.rules})
        if path == "/zones/z1/rulesets/rs1/rules" and m == "POST":
            self.rules.append({**body, "id": f"rule{len(self.rules)}", "version": "1"})
            return self._ok({"id": "rs1", "rules": self.rules})
        if path == "/accounts/a1/challenges/widgets":
            if m == "GET":
                return self._ok([{k: w[k] for k in ("sitekey", "name", "domains")} for w in self.widgets])
            w = {**body, "sitekey": "0x4AAAAAAA-made-up-sitekey", "secret": "0x4AAAAAAA-made-up-secret"}
            self.widgets.append(w)
            return self._ok(w)
        if path.startswith("/accounts/a1/challenges/widgets/"):
            if m == "GET":
                return self._ok(self.widgets[0])
            if m == "PUT":          # the whole widget: what is not sent goes back to what a new one has
                w = self.widgets[0]
                self.widgets[0] = {"sitekey": w["sitekey"], "secret": w["secret"], "bot_fight_mode": False,
                                   "clearance_level": "no_clearance", **body}
                return self._ok(self.widgets[0])
        if path == "/certificates" and m == "POST":
            if self.refuse_cert:
                self._refuse(req, 1100, "Failed to validate requested hostname caro-staging.noxioai.com")
            self.certs.append(body)
            return self._ok({"id": "c1", "certificate": "-----BEGIN CERTIFICATE-----\nMADEUP\n-----END CERTIFICATE-----\n",
                             "hostnames": body["hostnames"], "expires_on": "2041-11-06 00:00:00 +0000 UTC"})
        raise AssertionError(f"the fake has no {m} {path}")


def _cf_run(fake, *argv, here=None, env=None, run=None):
    out, err = _io_cf.StringIO(), _io_cf.StringIO()
    with _ctx_cf.redirect_stderr(err):
        try:
            rc = _cf.main(list(argv), env={"CLOUDFLARE_API_TOKEN": _CF_TOKEN} if env is None else env,
                          opener=fake, out=lambda line: out.write(line + "\n"), here=here,
                          **({"run": run} if run else {}))
        except SystemExit as e:         # what argparse does with an argument it refuses
            rc = e.code
    return rc, out.getvalue(), err.getvalue()


def _writes(fake):
    return [(m, p) for m, p, *_ in fake.calls if m != "GET"]


_f1 = _FakeCloudflare()
_cf1 = [_cf_run(_f1, "staging", "--ip", "203.0.113.10") for _ in range(2)]
_w1 = _writes(_f1)
_cf1b = _cf_run(_f1, "staging", "--ip", "203.0.113.11")
_f1d = _FakeCloudflare()
_cf1d = _cf_run(_f1d, "staging", "--ip", "203.0.113.10", "--dry-run")
_f1c = _FakeCloudflare(records=[{"id": "c1", "type": "CNAME", "name": "caro-staging.noxioai.com",
                                 "content": "somewhere.example", "proxied": False}])
_cf1c = _cf_run(_f1c, "staging", "--ip", "203.0.113.10")
_f1g = _FakeCloudflare(records=[{"id": "g1", "type": "A", "name": "caro-staging.noxioai.com",
                                 "content": "203.0.113.10", "proxied": False}])
_cf1g = _cf_run(_f1g, "staging", "--ip", "203.0.113.10")
_f1p = _FakeCloudflare()
_cf1p = [_cf_run(_f1p, "staging", *a) for a in (("--ip", "192.168.1.10"), ("--ip", "10.0.0.5"), ())]
check("DP23: staging's record is made once, an A record to the server, proxied; run again it is found and "
      "nothing is written; a new address changes it; one made by hand to the server but not proxied is "
      "made proxied; --dry-run writes nothing; a record of another kind at the name is not touched; an "
      "address inside a network, or none, stops it before anything",
      [rc for rc, *_ in _cf1] == [0, 0] and _w1 == [("POST", "/zones/z1/dns_records")]
      and _f1.records[0]["content"] == "203.0.113.11" and _f1.records[0]["proxied"] is True
      and _f1.records[0]["type"] == "A" and _cf1b[0] == 0 and _writes(_f1)[-1][0] == "PATCH"
      and "already" in _cf1[1][1] and _cf1d[0] == 0 and _writes(_f1d) == [] and "would:" in _cf1d[1]
      and _cf1c[0] == 1 and _writes(_f1c) == [] and "CNAME" in _cf1c[2]
      and _cf1g[0] == 0 and _writes(_f1g) == [("PATCH", "/zones/z1/dns_records/g1")]
      and _f1g.records[0]["proxied"] is True
      and [rc for rc, *_ in _cf1p] == [2, 2, 2] and _f1p.calls == [],
      str((_cf1, _cf1b, _cf1d, _cf1c, _cf1g, _cf1p, _writes(_f1))))

_bypass = {"id": "keep1", "description": "phase 0: no cache for /api/", "expression": 'starts_with(http.request.uri.path, "/api/")',
           "action": "set_cache_settings", "action_parameters": {"cache": False}, "enabled": True,
           "version": "3", "last_updated": "2026-11-03T00:00:00Z"}
_f2 = _FakeCloudflare(rules=[dict(_bypass)])
_cf2 = [_cf_run(_f2, "cache") for _ in range(2)]
_post2 = [c for c in _f2.calls if c[0] != "GET"]
_f2n = _FakeCloudflare(rules=None)
_cf2n = _cf_run(_f2n, "cache")
_hand = {"id": "h1", "description": "API answers that say they may be kept", "action": "set_cache_settings",
         "expression": '(http.request.uri.path in {"/api/models" "/api/model" "/api/corpus"})',
         "action_parameters": {"cache": True}, "enabled": True}
_f2h = _FakeCloudflare(rules=[dict(_bypass), dict(_hand)])
_cf2h = _cf_run(_f2h, "cache")
_f2e = _FakeCloudflare(rules=[{**_hand, "description": "mine", "expression":
                               '(http.request.uri.path in {"/api/models"  "/api/model"\n "/api/corpus"})'}])
_cf2e = _cf_run(_f2e, "cache")
_f2o = _FakeCloudflare(rules=[dict(_hand), dict(_bypass)])
_cf2o = _cf_run(_f2o, "cache")
check("DP24: the cache rule is added alone at the end of the zone's rules, none of which is sent back or "
      "changed; it makes the three answers eligible, the origin's Cache-Control deciding for how long; "
      "run again, it is found; made by hand under PHASE4's name, or under any name with the same "
      "expression, it is found and nothing is written; a rule after it that switches the cache off is "
      "said; a zone with no entry point gets it as its first",
      [rc for rc, *_ in _cf2] == [0, 0] and [(c[0], c[1]) for c in _post2] == [("POST", "/zones/z1/rulesets/rs1/rules")]
      and _post2[0][2] == _cf.RULE and _f2.rules[0] == _bypass
      and [r["description"] for r in _f2.rules] == [_bypass["description"], _cf.RULE_NAME]
      and _cf.RULE["action"] == "set_cache_settings"
      and _cf.RULE["action_parameters"] == {"cache": True, "edge_ttl": {"mode": "respect_origin"},
                                            "browser_ttl": {"mode": "respect_origin"}}
      and _cf.RULE["expression"] == '(http.request.uri.path in {"/api/models" "/api/model" "/api/corpus"})'
      and _cf.RULE["enabled"] is True
      and "there already" in _cf2[1][1] and "switches the cache off" not in _cf2[1][1]
      and _cf2n[0] == 0 and [r["description"] for r in _f2n.rules] == [_cf.RULE_NAME]
      and _writes(_f2n) == [("PUT", "/zones/z1/rulesets/phases/http_request_cache_settings/entrypoint")]
      and _cf2h[0] == 0 and _writes(_f2h) == [] and "there already" in _cf2h[1]
      and _cf2e[0] == 0 and _writes(_f2e) == []
      and _cf2o[0] == 0 and _writes(_f2o) == [] and "switches the cache off" in _cf2o[1]
      and _bypass["description"] in _cf2o[1],
      str((_cf2, _post2, _cf2n, _cf2h, _cf2e, _cf2o)))

_tmp_cf = tempfile.TemporaryDirectory()
_here_cf = Path(_tmp_cf.name)
_f3 = _FakeCloudflare()
_cf3 = [_cf_run(_f3, "turnstile", here=_here_cf) for _ in range(2)]
_sec = _here_cf / "turnstile-secret.txt"
_f3h = _FakeCloudflare(widgets=[{"sitekey": "0x4BBB-by-hand", "name": "caro", "domains": ["caro.noxioai.com"],
                                 "mode": "non-interactive", "secret": "0x4BBB-by-hand-secret",
                                 "bot_fight_mode": True, "clearance_level": "managed"}])
_cf3h = _cf_run(_f3h, "turnstile", here=_here_cf)
check("DP25: the Turnstile widget is made once, managed, for the site's two hostnames; its site key is "
      "printed and its secret written beside the owner, mode 600, and printed nowhere; run again it is "
      "found and not made twice; one made by hand for one hostname gets the other, its mode and its other "
      "settings kept",
      [rc for rc, *_ in _cf3] == [0, 0] and len(_f3.widgets) == 1
      and _f3.widgets[0]["mode"] == "managed" and _f3.widgets[0]["name"] == "caro"
      and _f3.widgets[0]["domains"] == ["caro.noxioai.com", "caro-staging.noxioai.com"]
      and all("0x4AAAAAAA-made-up-sitekey" in o for _, o, _ in _cf3)
      and not any("made-up-secret" in o + e for _, o, e in _cf3)
      and [m for m, *_ in _writes(_f3)] == ["POST"]
      and _cf3h[0] == 0 and [m for m, *_ in _writes(_f3h)] == ["PUT"]
      and _f3h.widgets[0]["domains"] == ["caro.noxioai.com", "caro-staging.noxioai.com"]
      and _f3h.widgets[0]["mode"] == "non-interactive" and len(_f3h.widgets) == 1
      and _f3h.widgets[0]["bot_fight_mode"] is True and _f3h.widgets[0]["clearance_level"] == "managed"
      and _sec.read_text().strip() == "0x4BBB-by-hand-secret" and (_sec.stat().st_mode & 0o777) == 0o600
      and "by-hand-secret" not in _cf3h[1] + _cf3h[2],
      str((_cf3, _cf3h)))

_vercel = {"id": "v1", "type": "CNAME", "name": "caro.noxioai.com", "content": "cname.vercel-dns.com",
           "proxied": False, "ttl": 1}
_undo = _here_cf / "cloudflare-undo.json"
_f4 = _FakeCloudflare(records=[_vercel])
_cf4 = [_cf_run(_f4, "switch", "--ip", "203.0.113.10", here=_here_cf) for _ in range(2)]
_w4 = _writes(_f4)
_after_switch = [(r["type"], r["content"], r["proxied"]) for r in _f4.records]
_cf4m = _cf_run(_f4, "switch", "--ip", "203.0.113.20", here=_here_cf)
_kept = json.loads(_undo.read_text())
_cf4u = _cf_run(_f4, "undo-switch", here=_here_cf)
_after_undo = [(r["type"], r["content"], r["proxied"]) for r in _f4.records]
_tmp_cf2 = tempfile.TemporaryDirectory()
_cf4n = _cf_run(_FakeCloudflare(), "undo-switch", here=Path(_tmp_cf2.name))
_f4r = _FakeCloudflare(records=[_vercel], refuse_batch=True)
_cf4r = _cf_run(_f4r, "switch", "--ip", "203.0.113.10", here=Path(_tmp_cf2.name))
_f4x = _FakeCloudflare(records=[{"id": "x1", "type": "A", "name": "caro.noxioai.com", "content": "203.0.113.10",
                                 "proxied": True}, {"id": "x2", "type": "AAAA", "name": "caro.noxioai.com",
                                                    "content": "2001:db8::1", "proxied": True}])
_cf4x = _cf_run(_f4x, "switch", "--ip", "203.0.113.10", here=Path(_tmp_cf2.name))
_www = {"id": "w1", "type": "A", "name": "www.noxioai.com", "content": "198.51.100.5", "proxied": True}
_tmp_cf3 = tempfile.TemporaryDirectory()
_f4i = _FakeCloudflare(records=[_www, _vercel], ignore_filter=True)
_cf4i = _cf_run(_f4i, "switch", "--ip", "203.0.113.10", here=Path(_tmp_cf3.name))
_batch4i = [c[2] for c in _f4i.calls if c[1].endswith("/batch")]
_stg = {"id": "s1", "type": "A", "name": "caro-staging.noxioai.com", "content": "203.0.113.30", "proxied": True}
_tmp_cf4 = tempfile.TemporaryDirectory()
_f4s = _FakeCloudflare(records=[_stg, _vercel])
_cf4s = _cf_run(_f4s, "switch", here=Path(_tmp_cf4.name))
_f4z = _FakeCloudflare(records=[_vercel])
_cf4z = _cf_run(_f4z, "switch", here=Path(_tmp_cf4.name))
_f4t = _FakeCloudflare(records=[_stg, {**_stg, "id": "s2", "content": "203.0.113.31"}, _vercel])
_cf4t = _cf_run(_f4t, "switch", here=Path(_tmp_cf4.name))
_f4p = _FakeCloudflare(records=[{**_stg, "content": "192.168.1.10", "proxied": False}, _vercel])
_cf4p = _cf_run(_f4p, "switch", here=Path(_tmp_cf4.name))
check("DP26: the switch keeps what caro.noxioai.com was beside the owner, then makes it an A record to "
      "the server, proxied, in one batch that takes Vercel's CNAME away; run again it is found; a switch "
      "to a new address keeps the first switch's file; undone, in one batch, Vercel's CNAME is back as it "
      "was and the file is gone; with nothing kept, undo refuses; a batch Cloudflare refuses leaves the "
      "name as it was; a record left beside the server's is taken away, the A record alone kept; and "
      "where the list answers with other names' records too, none of them is taken away or kept as "
      "what the name was; given no address, it takes the one staging's record has, and with none there, "
      "two, or one inside a network, it stops before writing",
      [rc for rc, *_ in _cf4] == [0, 0] and _w4 == [("POST", "/zones/z1/dns_records/batch")]
      and _after_switch == [("A", "203.0.113.10", True)] and "already" in _cf4[1][1]
      and _cf4m[0] == 0 and [(r["type"], r["content"]) for r in _kept] == [("CNAME", "cname.vercel-dns.com")]
      and _cf4u[0] == 0 and _after_undo == [("CNAME", "cname.vercel-dns.com", False)] and not _undo.exists()
      and _writes(_f4)[-1] == ("POST", "/zones/z1/dns_records/batch") and len(_writes(_f4)) == 3
      and _cf4n[0] == 1
      and _cf4r[0] == 1 and [(r["type"], r["content"]) for r in _f4r.records] == [("CNAME", "cname.vercel-dns.com")]
      and "already exists" in _cf4r[2]
      and _cf4x[0] == 0 and [(r["type"], r["content"]) for r in _f4x.records] == [("A", "203.0.113.10")]
      and _cf4i[0] == 0 and _batch4i and _batch4i[0]["deletes"] == [{"id": "v1"}]
      and [r for r in _f4i.records if r["name"] == "www.noxioai.com"] == [_www]
      and [x["name"] for x in json.loads((Path(_tmp_cf3.name) / "cloudflare-undo.json").read_text())] == ["caro.noxioai.com"]
      and _cf4s[0] == 0 and [(r["name"], r["type"], r["content"]) for r in _f4s.records if r["name"] == "caro.noxioai.com"]
      == [("caro.noxioai.com", "A", "203.0.113.30")] and "as caro-staging.noxioai.com's record has it: 203.0.113.30" in _cf4s[1]
      and _cf4z[0] == 1 and "give the switch --ip" in _cf4z[2] and _writes(_f4z) == []
      and _cf4t[0] == 1 and "2 A records" in _cf4t[2] and _writes(_f4t) == []
      and _cf4p[0] == 1 and "not the server's public IPv4 address" in _cf4p[2] and _writes(_f4p) == [],
      str((_cf4, _cf4m, _cf4u, _after_switch, _after_undo, _cf4n, _cf4r, _cf4x, _cf4i)))

_tls_cf = tempfile.TemporaryDirectory()
_tls = Path(_tls_cf.name)
_f6 = _FakeCloudflare()
_cf6d = _cf_run(_f6, "origin-cert", "--tls-dir", str(_tls), "--dry-run")
_dry_files = sorted(x.name for x in _tls.iterdir())
_cf6 = [_cf_run(_f6, "origin-cert", "--tls-dir", str(_tls)) for _ in range(2)]
_key6 = (_tls / "origin.key").read_text() if (_tls / "origin.key").exists() else ""
_tls_cf2 = tempfile.TemporaryDirectory()
_tls2 = Path(_tls_cf2.name)
_cf6n = _cf_run(_FakeCloudflare(), "origin-cert", "--tls-dir", str(_tls2 / "none"))
_cf6r = _cf_run(_FakeCloudflare(refuse_cert=True), "origin-cert", "--tls-dir", str(_tls2))
_after_refused = sorted(x.name for x in _tls2.iterdir())
_f6o = _FakeCloudflare()
_cf6o = _cf_run(_f6o, "origin-cert", "--tls-dir", str(_tls2),
                run=lambda argv, **_k: subprocess.CompletedProcess(argv, 1, "", "req: unable to write the key"))
check("DP27: the origin certificate is made on the server: the key by openssl in the certificate's "
      "directory, mode 600, and only its request sent to Cloudflare, for the site's two hostnames, RSA, "
      "fifteen years; the certificate written beside the key; run again, nothing is asked; --dry-run "
      "writes nothing; a directory that is not there stops it before anything; a certificate Cloudflare "
      "refuses, or a key openssl could not make, leaves no key behind",
      _cf6d[0] == 0 and _dry_files == [] and [rc for rc, *_ in _cf6] == [0, 0] and len(_f6.certs) == 1
      and _f6.certs[0]["csr"].startswith("-----BEGIN CERTIFICATE REQUEST-----")
      and _f6.certs[0]["hostnames"] == ["caro.noxioai.com", "caro-staging.noxioai.com"]
      and _f6.certs[0]["request_type"] == "origin-rsa" and _f6.certs[0]["requested_validity"] == 5475
      and "PRIVATE KEY" in _key6 and ((_tls / "origin.key").stat().st_mode & 0o777) == 0o600
      and (_tls / "origin.pem").read_text().startswith("-----BEGIN CERTIFICATE-----")
      and sorted(x.name for x in _tls.iterdir()) == ["origin.key", "origin.pem"]
      and not any(_key6.strip().split("\n")[1] in json.dumps(c[2]) for c in _f6.calls if c[2])
      and not any("PRIVATE KEY" in o + e for _, o, e in _cf6)
      and "there already" in _cf6[1][1] and _cf6n[0] == 2
      and _cf6r[0] == 1 and "Failed to validate" in _cf6r[2] and _after_refused == []
      and _cf6o[0] == 1 and "unable to write" in _cf6o[2] and _f6o.certs == []
      and list(_tls2.iterdir()) == [],
      str((_cf6d, _cf6, _dry_files, _cf6n, _cf6r, _cf6o)))


class _Refusing(_FakeCloudflare):
    def __call__(self, req, timeout=30):
        self.calls.append((req.get_method(), req.full_url, None, None, None))
        raise _ue_cf.HTTPError(req.full_url, 403, "Forbidden", {}, _io_cf.BytesIO(
            b'{"success": false, "errors": [{"code": 10000, "message": "Authentication error"}]}'))


_cf5a = _cf_run(_FakeCloudflare(), "status", env={})
_cf5b = _cf_run(_Refusing(), "status")
_cf5c = _cf_run(_Refusing(), "cache")
_f5z = _FakeCloudflare(zones=[{"id": "zX", "name": "my-noxioai.com", "account": {"id": "aX"}},
                              {"id": "z1", "name": "noxioai.com", "account": {"id": "a1"}}])
_cf5z = _cf_run(_f5z, "staging", "--ip", "203.0.113.10")
_cf5n = _cf_run(_FakeCloudflare(zones=[{"id": "zX", "name": "my-noxioai.com", "account": {"id": "aX"}}]), "status")
_cf5s = _cf_run(_FakeCloudflare(rules=[dict(_hand)]), "status")
_every = [c for f in (_f1, _f2, _f3, _f3h, _f4, _f6) for c in f.calls]
_files = "".join(p.read_text() for p in _here_cf.iterdir()) + "".join(p.read_text() for p in _tls.iterdir())
check("DP28: without a token it stops before asking anything; Cloudflare's refusal stops it with "
      "Cloudflare's words and the permission that command needs; the zone is the one of that exact name, "
      "and a token that sees only another stops it; status gives the zone's id as the server's line for "
      "the purge; every request goes to api.cloudflare.com with the "
      "token as a bearer, and the token is in no line printed and no file written; the two files it "
      "writes beside the owner are ones git ignores, so a checkout never offers them to a commit",
      _cf5a[0] == 2 and "CLOUDFLARE_API_TOKEN" in _cf5a[2]
      and _cf5b[0] == 1 and "Authentication error" in _cf5b[2] and "Zone / Zone / Read" in _cf5b[2]
      and _cf5c[0] == 1 and "Zone / Cache Rules / Edit" in _cf5c[2]
      and _cf5z[0] == 0 and _writes(_f5z) == [("POST", "/zones/z1/dns_records")]
      and _cf5n[0] == 1 and "sees no zone noxioai.com" in _cf5n[2]
      and _cf5s[0] == 0 and "bash /opt/caro/deploy/set-env.sh production CARO_CF_ZONE_ID=z1\n" in _cf5s[1]
      and "bash /opt/caro/deploy/set-env.sh staging CARO_CF_ZONE_ID=z1\n" in _cf5s[1] and "CARO's number 1" in _cf5s[1]
      and all(c[4] == "api.cloudflare.com" and c[3] == f"Bearer {_CF_TOKEN}" for c in _every)
      and not any(_CF_TOKEN in o + e for runs in (_cf1, _cf2, _cf3, _cf4, _cf6) for _, o, e in runs)
      and _CF_TOKEN not in _cf5b[2] + _cf5c[2] and _CF_TOKEN not in _files
      and {"turnstile-secret.txt", "cloudflare-undo.json"} <= set(text(".gitignore").split("\n")),
      str((_cf5a, _cf5b, _cf5c)))

_edge = text("compose.edge.yml")
_esvc = blocks(_edge)
check("DP6: the edge is nginx alone, the only thing on the server that publishes a port -- 443 -- "
      "with its files read-only, and it makes the network the environments join",
      set(_esvc) == {"nginx"} and re.findall(r'^\s+- "(\S+)"$', _esvc["nginx"].split("volumes:")[0],
                                             re.MULTILINE) == ["443:443"]
      and all(v.endswith(":ro") for v in re.findall(r"^\s+- (\S+:\S+)$", _esvc["nginx"].split(
          "volumes:")[1].split("networks:")[0], re.MULTILINE))
      and re.search(r"networks:\n  edge:\n    name: caro_edge", _edge) is not None
      and "ports:" not in text("compose.vps.yml"),
      _esvc.get("nginx", "")[:300])

# ---------------------------------------------------------------------------
print("\nthe edge's nginx")

_ng = text("deploy/nginx/caro.conf")
check("DP7: only Cloudflare is answered, judged by the address that connected and not the one "
      "realip put in its place; any other is closed without an answer; a name the server does not "
      "serve gets no handshake; the API is told the client Cloudflare named and nothing longer",
      re.search(r"^geo \$realip_remote_addr \$caro_from_cloudflare \{", _ng, re.MULTILINE) is not None
      and not re.search(r"^geo \$remote_addr", _ng, re.MULTILINE)
      and re.search(r"^\s*allow\s", _ng, re.MULTILINE) is None
      and re.search(r"if \(\$caro_from_cloudflare = 0\) \{\s*return 444;", _ng) is not None
      and re.search(r"listen 443 ssl default_server;\s*server_name _;\s*ssl_reject_handshake on;", _ng)
      is not None
      and "real_ip_header CF-Connecting-IP;" in _ng
      and "proxy_set_header X-Forwarded-For $remote_addr;" in _ng
      and "proxy_add_x_forwarded_for" not in _ng and "server_tokens off;" in _ng
      and re.search(r"caro\.noxioai\.com\s+production;", _ng) is not None
      and re.search(r"caro-staging\.noxioai\.com\s+staging;", _ng) is not None
      and "proxy_pass http://api-$caro_env:8000;" in _ng
      and "proxy_pass http://site-$caro_env:3000;" in _ng,
      _ng[:200])


def _ranges(path, pattern):
    return [m.group(1) for m in re.finditer(pattern, text(path), re.MULTILINE)]


_real = _ranges("deploy/nginx/cloudflare-realip.conf", r"^set_real_ip_from (\S+);$")
_geo = _ranges("deploy/nginx/cloudflare-geo.conf", r"^(\S+) 1;$")
_nets = []
for r in _geo:
    try:
        _nets.append(ipaddress.ip_network(r))
    except ValueError:
        _nets.append(None)
check("DP8: the repository's lists of Cloudflare's ranges are the same two lists, every entry a "
      "network, none private or loopback, both families present",
      _real == _geo and len(_geo) >= 10 and None not in _nets
      and not any(n.is_private or n.is_loopback for n in _nets)
      and {n.version for n in _nets} == {4, 6}, str(_geo))

_sh = text("deploy/cloudflare-ips.sh")
check("DP9: the server's lists are read from Cloudflare's published ranges, refused when they "
      "hold fewer than ten, fall back to the repository's only when the server has none, and the "
      "edge is reloaded only after nginx accepts them",
      "https://www.cloudflare.com/ips-v4" in _sh and "https://www.cloudflare.com/ips-v6" in _sh
      and '-lt 10' in _sh and 'elif [ ! -s "$OUT/cloudflare-geo.conf" ]' in _sh
      and 'nginx -t -q && docker exec "$EDGE" nginx -s reload' in _sh
      and "/etc/caro/nginx:/etc/nginx/caro:ro" in _edge, _sh[:200])

# ---------------------------------------------------------------------------
print("\nthe server's settings and timers")

_env = text("deploy/env.example")
_set = dict(re.findall(r"^([A-Z_]+)=(.*)$", _env, re.MULTILINE))
_needed = set(re.findall(r"\$\{([A-Z_]+)", _vps))
_secrets = ("POSTGRES_PASSWORD", "CARO_ADMIN_TOKEN", "CARO_ADMIN_TOTP_SECRET", "SENTRY_DSN",
            "CARO_STORE_SECRET", "CARO_SMS_KAVENEGAR_KEY", "CARO_SELLER_STORE", "CARO_CF_API_TOKEN",
            "CARO_TURNSTILE_SECRET", "GRAFANA_CLOUD_TOKEN")
check("DP10: the env file's template names every variable an environment's compose file reads, "
      "and gives no secret a value and the seller store no switch",
      _needed <= set(_set) and all(_set.get(k) == "" for k in _secrets)
      and _set.get("CARO_ENV") in ("production", "staging"),
      str((sorted(_needed - set(_set)), {k: _set.get(k) for k in _secrets})))


def _pull(*args):
    p = subprocess.run(["sh", str(ROOT / "deploy/pull.sh"), *args], capture_output=True, text=True)
    return p.returncode, p.stderr


_p_none, _p_bad = _pull(), _pull("everywhere")
_missing = not Path("/etc/caro/staging.env").exists()
_p_staging = _pull("staging") if _missing else (2, "/etc/caro/staging.env is missing")
_units = {u: text(f"deploy/systemd/{u}") for u in (
    "caro-pull@.service", "caro-pull@.timer", "caro-cloudflare-ips.service", "caro-cloudflare-ips.timer")}
check("DP11: the pull script takes production or staging and nothing else, stops before docker when "
      "the environment's file is missing, and the timers run the scripts that exist",
      _p_none[0] == 2 and _p_bad[0] == 2 and "production|staging" in _p_bad[1]
      and _p_staging[0] == 2 and "/etc/caro/staging.env is missing" in _p_staging[1]
      and "ExecStart=/opt/caro/deploy/pull.sh %i" in _units["caro-pull@.service"]
      and "ExecStart=/opt/caro/deploy/cloudflare-ips.sh" in _units["caro-cloudflare-ips.service"]
      and "OnUnitActiveSec=1min" in _units["caro-pull@.timer"]
      and "OnCalendar=daily" in _units["caro-cloudflare-ips.timer"],
      str((_p_none, _p_bad, _p_staging)))

# ---------------------------------------------------------------------------
print("\nwaiting for a deploy")


def _script(answers):
    it = iter(answers)

    def read(site):
        a = next(it)
        if isinstance(a, Exception):
            raise a
        return a
    return read


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


_c1, _o1 = _Clock(), []
_r1 = deploy_wait.wait("https://x", "new", 100, 10, read=_script([ConnectionResetError(), "old", "old", "new"]),
                       clock=_c1, sleep=_c1.sleep, out=_o1.append)
_c2, _o2 = _Clock(), []
_r2 = deploy_wait.wait("https://x", "new", 25, 10, read=_script(["old"] * 10), clock=_c2, sleep=_c2.sleep,
                       out=_o2.append)
check("DP12: a deploy is waited for until /api/health names the commit -- a connection that fails "
      "counts as no answer, each change is said once -- and a commit that never arrives is a "
      "failure at the timeout, after the last thing seen",
      _r1 == 0 and _o1 == ["deploy-wait: https://x runs no answer: ConnectionResetError",
                           "deploy-wait: https://x runs old", "deploy-wait: https://x runs new"]
      and _r2 == 1 and _o2[0] == "deploy-wait: https://x runs old" and "did not answer within 25 s" in _o2[-1]
      and _c2.t == 30, str((_r1, _o1, _r2, _o2, _c2.t)))

_wk = text("compose.worker.yml")
_wsvc = blocks(_wk)
check("DP14: the worker's compose file is a queue and a worker, and publishes no port; the queue is on a "
      "network that reaches nothing outside, the worker on it and on one that reaches the sources; the "
      "worker runs read-only with every capability dropped, from the image and with the password its "
      "env file names and no default, keeps its snapshots and transcripts in volumes, and asks its own "
      "queue",
      set(_wsvc) == {"queue", "worker"}
      and not any(re.search(r"^\s+ports:", b, re.MULTILINE) for b in _wsvc.values())
      and re.search(r"^  queue:\n    internal: true", _wk.split("\nnetworks:\n", 1)[1], re.MULTILINE) is not None
      and "- queue" in _wsvc["queue"] and "- out" not in _wsvc["queue"]
      and "- queue" in _wsvc["worker"] and "- out" in _wsvc["worker"]
      and all(x in _wsvc["worker"] for x in ("read_only: true", "cap_drop: [ALL]", "no-new-privileges:true",
                                              'command: ["worker"]', "${CARO_API_IMAGE:?",
                                              "${CARO_WORKER_ENV_FILE:?", "snapshots:/app/data/snapshots",
                                              "transcripts:/app/data/transcripts",
                                              "CARO_QUEUE_URL: postgresql://caro:${CARO_QUEUE_PASSWORD}@queue:5432/caro"))
      and "POSTGRES_PASSWORD: ${CARO_QUEUE_PASSWORD:?" in _wsvc["queue"], str(sorted(_wsvc)))

_wenv = text("deploy/worker.env.example")
_wset = dict(re.findall(r"^([A-Z_]+)=(.*)$", _wenv, re.MULTILINE))
_wneeded = set(re.findall(r"\$\{([A-Z_]+)", _wk))
_wsecrets = ("CARO_QUEUE_PASSWORD", "CARO_SELLER_SALT", "CARO_WORKER_TOKEN", "CARO_BUCKET_KEY_ID",
             "CARO_BUCKET_SECRET")
check("DP15: the worker's env template names every variable its compose file reads, gives no secret a "
      "value, reports to the server over https and pulls the image this repository pushes; the "
      "server's template names the worker's token, the expected runs and the bot, with no value",
      _wneeded <= set(_wset) and all(_wset.get(k) == "" for k in _wsecrets)
      and _wset.get("CARO_INGEST_URL", "").startswith("https://")
      and _wset.get("CARO_API_IMAGE", "").startswith("ghcr.io/sahandmusanezhad/caro-api:")
      and _wset.get("CARO_COLLECT") == "03:30 --source khodro45 --pages 60"
      and all(_set.get(k) == "" for k in ("CARO_WORKER_TOKEN", "CARO_ALERT_EXPECT", "CARO_ALERT_TELEGRAM_TOKEN",
                                          "CARO_ALERT_TELEGRAM_CHAT")),
      str((sorted(_wneeded - set(_wset)), {k: _wset.get(k) for k in _wsecrets})))

check("DP16: the image carries the worker -- first_run, the worker and the alerts, and a snapshots and a "
      "transcripts directory its user owns -- runs the collection suite in its test stage, and keeps a "
      "laptop's transcripts and queue out of its context",
      all(x in _sources for x in ("scripts/first_run.py", "webapp/worker.py", "webapp/alerts.py"))
      and "chown caro data/inbox data/snapshots data/transcripts" in _api
      and "python tests/run_all.py collection" in _df.split("FROM api AS test")[1]
      and all(x in _ignore for x in ("data/transcripts", "data/queue")), str(_sources))

from scripts import edge_purge                                          # noqa: E402


class _Answer:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


with tempfile.TemporaryDirectory() as _pd:
    _pd = Path(_pd)
    (_pd / "corpora").mkdir()
    (_pd / "corpora" / "run1.json").write_text('{"a": 1}', encoding="utf-8")
    _penv = {"CARO_CF_API_TOKEN": "made-up-cloudflare-token-0123", "CARO_CF_ZONE_ID": "zone123",
             "CARO_SITE_HOST": "caro.example", "CARO_PURGE_STATE": str(_pd / "state" / "key"), "CARO_RUN": ""}

    def _cf(answers, seen):
        def open_(req, timeout):
            seen.append(json.loads(req.data))
            a = answers.pop(0)
            if isinstance(a, Exception):
                raise a
            return _Answer(json.dumps(a).encode())
        return open_

    _p_out, _p_seen = [], []
    _p_off = edge_purge.main([], env={}, out=_p_out.append)
    _p1 = edge_purge.main([], env=_penv, opener=_cf([{"success": True}], _p_seen), corpora=_pd / "corpora",
                          out=_p_out.append)
    _p2 = edge_purge.main([], env=_penv, opener=_cf([], _p_seen), corpora=_pd / "corpora", out=_p_out.append)
    (_pd / "corpora" / "run2.json").write_text('{"b": 2}', encoding="utf-8")
    _p3 = edge_purge.main([], env=_penv, opener=_cf([{"success": False, "errors": [{"code": 1}]},
                                                      {"success": True}], _p_seen),
                          corpora=_pd / "corpora", out=_p_out.append)
    _p4 = edge_purge.main([], env={**_penv, "CARO_RUN": "run1"},
                          opener=_cf([TimeoutError("x"), {"success": False}], _p_seen),
                          corpora=_pd / "corpora", out=_p_out.append)
    _p5 = edge_purge.main([], env={**_penv, "CARO_RUN": "run1"}, opener=_cf([{"success": True}], _p_seen),
                          corpora=_pd / "corpora", out=_p_out.append)
    _keys = (edge_purge.corpus_key(_pd / "corpora", ""), edge_purge.corpus_key(_pd / "corpora", "run1"))
check("DP17: the edge is purged only when the runs or the served one changed -- off without Cloudflare's "
      "token and zone, nothing asked when the runs are as they were -- by host, or by the two fixed "
      "addresses where Cloudflare refuses that; a purge that did not happen is said and tried after the "
      "next change, and nothing printed holds the token",
      (_p_off, _p1, _p2, _p3, _p4, _p5) == (0, 0, 0, 0, 1, 0) and "off" in _p_out[0]
      and _p_seen == [{"hosts": ["caro.example"]},
                      {"hosts": ["caro.example"]},
                      {"files": ["https://caro.example/api/models", "https://caro.example/api/corpus"]},
                      {"hosts": ["caro.example"]}, {"files": ["https://caro.example/api/models",
                                                               "https://caro.example/api/corpus"]},
                      {"hosts": ["caro.example"]}]
      and "nothing purged" in _p_out[2] and "by addresses" in _p_out[3] and "did not purge" in _p_out[4]
      and _keys[0] != _keys[1] and not any("made-up-cloudflare-token" in o for o in _p_out),
      str((_p_off, _p1, _p2, _p3, _p4, _p5, _p_out)))

_pull_sh = text("deploy/pull.sh")
check("DP18: the pull purges the edge after it changed the environment's API, and a purge that fails does "
      "not undo the deploy",
      'before=$($C ps -q api' in _pull_sh and 'after=$($C ps -q api' in _pull_sh
      and _pull_sh.index("before=") < _pull_sh.index("up -d") < _pull_sh.index("after=")
      and 'if [ "$before" != "$after" ]; then\n    $C --profile purge run --rm edge-purge || true\nfi'
      in _pull_sh, _pull_sh[-400:])

_wf = text(".github/workflows/images.yml")
_only_here = "if: github.event_name == 'push' && github.repository == 'sahandmusanezhad/caro'"
check("DP13: the images workflow runs the API's suites inside its image and reads both images "
      "together before it pushes anything, pushes only on a merge or a tag and only from the "
      "repository the server pulls from, keeps no key to the server -- its one key is Tecso-Dev/caro's "
      "deploy key -- and waits on an environment only where a variable names it",
      _wf.index("docker build --target test") < _wf.index("docker push")
      and _wf.index("scripts/site_check.py --site http://127.0.0.1:3000") < _wf.index("docker push")
      and _wf.count(_only_here) == 2 and "if: github.event_name == 'push'\n" not in _wf
      and "ghcr.io/sahandmusanezhad/" in text("deploy/env.example")
      # The one key here is the deploy key of Tecso-Dev/caro, which Vercel builds from (DP43):
      # none reaches the server.
      and "ssh" not in _wf.lower().replace("ssh-key: ${{ secrets.tecso_deploy_key }}", "", 1)
      and "vars.CARO_STAGING_URL" in _wf and "if: env.URL != ''" in _wf
      and "packages: write" in _wf and "contents: read" in _wf, "")


def _step(wf: str, name: str) -> str:
    """One step of a workflow, from its name to the next step; "" where there is none."""
    at = wf.find(f"- name: {name}")
    if at < 0:
        return ""
    nxt = wf.find("\n      - ", at)
    return wf[at:] if nxt < 0 else wf[at:nxt]


def _before(text: str, first: str, then: str) -> bool:
    """Both are in `text`, `first` before `then`."""
    a, b = text.find(first), text.find(then)
    return 0 <= a < b


_browser_img = _step(_wf, "The site's image for the browser")
_pushed_img = _step(_wf, "The site's image")
_walk = _step(_wf, "Every key route in a browser")
_smoke = _step(_wf, "Both images, started together")
check("DP19: the images workflow walks both images in a browser before it pushes anything -- every key "
      "route and the seller listings, the code read from the API container's log, the fake SMS against "
      "a SQLite store -- and where the pushed site draws Turnstile, which no browser here can pass, "
      "the browser walks one built without that one argument",
      _before(_wf, "node e2e/routes.mjs", "docker push")
      and "if: vars.NEXT_PUBLIC_TURNSTILE_SITE_KEY != ''" in _browser_img
      and "run:" in _browser_img and "NEXT_PUBLIC_TURNSTILE_SITE_KEY" not in _browser_img.split("run:", 1)[1]
      and "--build-arg NEXT_PUBLIC_TURNSTILE_SITE_KEY" in _pushed_img
      and "--build-arg NEXT_PUBLIC_SENTRY_DSN --build-arg NEXT_PUBLIC_SELLER_LISTINGS" in _browser_img
      and "CARO_SITE: ${{ vars.NEXT_PUBLIC_TURNSTILE_SITE_KEY != '' && 'http://127.0.0.1:3001' "
          "|| 'http://127.0.0.1:3000' }}" in _walk
      and "-p 127.0.0.1:3001:3000 caro-site:browser" in _browser_img
      and _before(_walk, 'docker logs -f api > "$CARO_API_LOG"', "node e2e/routes.mjs")
      and "CARO_SMS_PROVIDER=fake" in _smoke and "DATABASE_URL=sqlite:////tmp/" in _smoke
      and "CARO_ADMIN_TOKEN=made-up-for-the-images-job-operator" in _smoke
      and "CARO_E2E_ADMIN_TOKEN: made-up-for-the-images-job-operator" in _walk
      and "npm install --no-save" in _wf, "")

# ---------------------------------------------------------------------------
print("\nthe server's side of phase 1, in one command")
import shutil as _sh_bs                                                  # noqa: E402

# The tools the bootstrap and the ranges' script use, from this machine; the
# ones that would change a server -- docker, systemctl, apt-get, curl, ip and
# the certificate's python3 -- are stand-ins that write down what they were
# asked, so no row depends on what this machine has installed.
_BS_TOOLS = ("sh", "bash", "sed", "grep", "tr", "awk", "cut", "head", "install", "chmod", "mv", "openssl",
             "dirname", "mkdir", "mktemp", "rm", "cat", "wc", "date", "cp", "env", "touch")


def _bs_world(docker=True, served=False, unreadable=(), short_ranges=False,
              addrs=("203.0.113.7",)):
    d = Path(tempfile.mkdtemp())
    tools, stubs, units = d / "tools", d / "bin", d / "units"
    for x in (tools, stubs, units):
        x.mkdir()
    for t in _BS_TOOLS:
        (tools / t).symlink_to(_sh_bs.which(t))
    calls = d / "calls"

    def stub(name, body):
        (stubs / name).write_text(f'#!/bin/sh\necho "{name} $*" >> "{calls}"\n{body}\n')
        (stubs / name).chmod(0o755)

    # `docker manifest inspect` fails for a tag the server cannot read.
    docker_body = 'case "$1 $2 $3" in\n%s  *) exit 0;;\nesac' % "".join(
        f'  "manifest inspect "*:{tag}) exit 1;;\n' for tag in unreadable)
    if docker:
        stub("docker", docker_body)
    (d / "docker.later").write_text(f'#!/bin/sh\necho "docker $*" >> "{calls}"\n{docker_body}\n')
    stub("systemctl", "exit 0")
    stub("apt-get", "exit 0")
    # Cloudflare's published ranges: not reachable, or two lists too short to be them.
    ranges = ('out=$(echo "$*" | sed "s/.* -o //"); echo "203.0.113.0/24" > "$out"; exit 0' if short_ranges
              else "exit 7")
    stub("curl", 'case "$*" in\n  *get.docker.com*) echo "cp %s %s/docker; chmod 755 %s/docker";;\n'
                 '  *caro-staging.noxioai.com*) exit %d;;\n  *cloudflare.com/ips-*) %s;;\n  *) exit 7;;\nesac'
         % (d / "docker.later", stubs, stubs, 0 if served else 7, ranges))
    stub("ip", "\n".join(f'echo "{i + 2}: if{i}    inet {a}/32 brd {a} scope global if{i}"'
                          for i, a in enumerate(addrs)))
    stub("python3", 'echo "-----BEGIN CERTIFICATE-----" > "$4/origin.pem"; echo "-----BEGIN PRIVATE KEY-----" > "$4/origin.key"')
    return d


def _bs_run(d, *args, home=None, token=None):
    env = {"PATH": f"{d / 'bin'}:{d / 'tools'}", "CARO_HOME": str(ROOT if home is None else home),
           "CARO_ETC": str(d / "etc"), "CARO_UNITS": str(d / "units"), "HOME": str(d)}
    if token:
        env["CLOUDFLARE_API_TOKEN"] = token
    p = subprocess.run([_sh_bs.which("bash"), str(ROOT / "deploy/bootstrap.sh"), *args],
                       capture_output=True, text=True, env=env, timeout=60)
    calls = (d / "calls").read_text().splitlines() if (d / "calls").exists() else []
    (d / "calls").unlink(missing_ok=True)
    return p.returncode, p.stdout, p.stderr, calls


def _env_of(path):
    return dict(re.findall(r"^([A-Z_]+)=(.*)$", path.read_text(), re.MULTILINE))


def _mode(path):
    return path.stat().st_mode & 0o777


_bsA = _bs_world()
_rA = _bs_run(_bsA)
_etcA = _bsA / "etc"
_st, _pr = _env_of(_etcA / "staging.env"), _env_of(_etcA / "production.env")
_tmpl = _env_of(ROOT / "deploy/env.example")
_made = {"CARO_ENV", "CARO_ENV_FILE", "CARO_API_IMAGE", "CARO_SITE_IMAGE", "POSTGRES_PASSWORD",
         "CARO_SITE_ORIGINS", "CARO_SITE_HOST"}
check("DP29: on a fresh server the bootstrap makes each environment's file from the template, mode 600: "
      "its name, its own path, its images' tag, its origin and host, and a database password of its "
      "own, printed nowhere, every other line as the template has it; /etc/caro and its tls directory "
      "700; the ranges and the units in place; and with no origin certificate yet, no edge and no timer, "
      "the certificate, the admin keys and staging's name said to be left",
      _rA[0] == 0 and _st["CARO_ENV"] == "staging" and _pr["CARO_ENV"] == "production"
      and _st["CARO_ENV_FILE"] == str(_etcA / "staging.env") and _pr["CARO_ENV_FILE"] == str(_etcA / "production.env")
      and _st["CARO_API_IMAGE"] == "ghcr.io/sahandmusanezhad/caro-api:staging"
      and _st["CARO_SITE_IMAGE"] == "ghcr.io/sahandmusanezhad/caro-site:staging"
      and _pr["CARO_API_IMAGE"] == "ghcr.io/sahandmusanezhad/caro-api:production"
      and _st["CARO_SITE_ORIGINS"] == "https://caro-staging.noxioai.com" and _st["CARO_SITE_HOST"] == "caro-staging.noxioai.com"
      and _pr["CARO_SITE_ORIGINS"] == "https://caro.noxioai.com" and _pr["CARO_SITE_HOST"] == "caro.noxioai.com"
      and all(re.fullmatch(r"[0-9a-f]{48}", e["POSTGRES_PASSWORD"]) for e in (_st, _pr))
      and _st["POSTGRES_PASSWORD"] != _pr["POSTGRES_PASSWORD"]
      and all({k: v for k, v in e.items() if k not in _made} == {k: v for k, v in _tmpl.items() if k not in _made}
              for e in (_st, _pr))
      and not any(e["POSTGRES_PASSWORD"] in _rA[1] + _rA[2] for e in (_st, _pr))
      and _mode(_etcA / "staging.env") == 0o600 and _mode(_etcA / "production.env") == 0o600
      and _mode(_etcA) == 0o700 and _mode(_etcA / "tls") == 0o700 and _mode(_etcA / "nginx") == 0o755
      and (_etcA / "nginx/cloudflare-geo.conf").exists()
      and sorted(x.name for x in (_bsA / "units").iterdir()) == sorted(_units)
      and "systemctl daemon-reload" in _rA[3]
      and not any(c.startswith(("docker compose -p caro-edge", "systemctl enable")) for c in _rA[3])
      and "the origin certificate" in _rA[1] and "CARO_ADMIN_TOKEN CARO_ADMIN_TOTP_SECRET" in _rA[1]
      and f"bash {ROOT}/deploy/set-env.sh staging CARO_ADMIN_TOKEN CARO_ADMIN_TOTP_SECRET\n" in _rA[1]
      and "staging --ip 203.0.113.7" in _rA[1],
      str((_rA, sorted(_st.items()))))

(_etcA / "staging.env").write_text((_etcA / "staging.env").read_text()
                                   .replace("CARO_ADMIN_TOKEN=\n", "CARO_ADMIN_TOKEN=the-owner-s-own\n")
                                   .replace("CARO_ADMIN_TOTP_SECRET=\n", "CARO_ADMIN_TOTP_SECRET=the-owner-s-too\n"))
_before_bs = {n: (_etcA / n).read_bytes() for n in ("staging.env", "production.env")}
(_etcA / "tls/origin.pem").write_text("-----BEGIN CERTIFICATE-----\n")
(_etcA / "tls/origin.key").write_text("-----BEGIN PRIVATE KEY-----\n")
_rB = _bs_run(_bsA)
_rC = _bs_run(_bsA, "--production")
_bsS = _bs_world(served=True)
(_bsS / "etc/tls").mkdir(parents=True)
(_bsS / "etc/tls/origin.pem").write_text("c\n")
(_bsS / "etc/tls/origin.key").write_text("k\n")
_rS = _bs_run(_bsS, "--production")
_bsU = _bs_world()
_rU = _bs_run(_bsU, "--everything")
_bsE = _bs_world()
_rE = _bs_run(_bsE, home="/opt/caro")
check("DP30: run again, the bootstrap writes no environment's file it finds -- the owner's values stay "
      "byte for byte -- and with the certificate in place it starts the edge, then staging's pull and the "
      "ranges' timer, and production's only with --production; staging answering through its name is "
      "taken as its name done; anything but --production, or a checkout other than the one the units "
      "run, stops it before anything",
      _rB[0] == 0 and {n: (_etcA / n).read_bytes() for n in _before_bs} == _before_bs
      and f"docker compose -p caro-edge -f {ROOT}/compose.edge.yml up -d --quiet-pull" in _rB[3]
      and "systemctl enable --now caro-cloudflare-ips.timer caro-pull@staging.timer" in _rB[3]
      and _rB[3].index("systemctl enable --now caro-cloudflare-ips.timer caro-pull@staging.timer")
      > _rB[3].index(f"docker compose -p caro-edge -f {ROOT}/compose.edge.yml up -d --quiet-pull")
      and not any("caro-pull@production" in c for c in _rB[3]) and "--production" in _rB[1]
      and "staging.env: CARO_ADMIN" not in _rB[1] and "production.env: CARO_ADMIN_TOKEN" in _rB[1]
      and _rC[0] == 0 and "systemctl enable --now caro-pull@production.timer" in _rC[3]
      and "after the release tag" not in _rC[1]
      and _rS[0] == 0 and "staging: answers" in _rS[1] and "staging --ip" not in _rS[1]
      and _rU[0] == 2 and _rU[3] == [] and not (_bsU / "etc").exists()
      and _rE[0] == 2 and "this checkout is" in _rE[2] and _rE[3] == [] and not (_bsE / "etc").exists(),
      str((_rB, _rC, _rS, _rU, _rE)))

def _with_cert(d):
    (d / "etc/tls").mkdir(parents=True)
    (d / "etc/tls/origin.pem").write_text("c\n")
    (d / "etc/tls/origin.key").write_text("k\n")
    return d


_bsP = _with_cert(_bs_world(unreadable=("staging", "production")))
_rP = _bs_run(_bsP, "--production")
_bsT = _with_cert(_bs_world(unreadable=("production",)))
_rT = _bs_run(_bsT, "--production")
_rN = _bs_run(_bs_world(addrs=("172.17.0.1", "10.0.0.2", "192.168.4.4", "100.64.0.9", "203.0.113.8")))
_rO = _bs_run(_bs_world(addrs=("172.17.0.1", "10.0.0.2")))
_bsR = _bs_world(short_ranges=True)
_rR = _bs_run(_bsR)
check("DP31: an image the server cannot read is said and not waited on: staging's as the packages to "
      "make public, production's as the release tag first, with production's timer not started; the "
      "address given for staging's name is the first that is not inside a network, and none is given "
      "when there is none; and where Cloudflare's ranges cannot be had at all, it stops before any "
      "settings are made, since the edge would not start",
      _rP[0] == 0 and "Change visibility -> Public" in _rP[1] and "the release tag first" in _rP[1]
      and not any("caro-pull@production" in c for c in _rP[3])
      and any(c.startswith("systemctl enable --now caro-cloudflare-ips.timer caro-pull@staging.timer") for c in _rP[3])
      and _rT[0] == 0 and "Change visibility" not in _rT[1] and "the release tag first" in _rT[1]
      and not any("caro-pull@production" in c for c in _rT[3])
      and "Change visibility" not in _rC[1] and "the release tag first" not in _rC[1]
      and "staging --ip 203.0.113.8" in _rN[1] and "staging --ip" not in _rO[1] and _rO[0] == 0
      and _rR[0] == 2 and "no list of Cloudflare's ranges" in _rR[2]
      and not (_bsR / "etc/staging.env").exists() and not any(c.startswith("systemctl") for c in _rR[3]),
      str((_rP, _rT, _rN, _rO, _rR)))

_bsD = _bs_world(docker=False)
_rD = _bs_run(_bsD, token="made-up-cloudflare-token-for-the-bootstrap")
_cD = _rD[3]


def _at(calls, start):
    return next((i for i, c in enumerate(calls) if c.startswith(start)), -1)


check("DP32: on a server without Docker the bootstrap upgrades the system, then installs Docker from "
      "get.docker.com, before anything asks for it; with Cloudflare's token in its environment it has the "
      "origin certificate made on the server, into its tls directory, and then starts the edge and the "
      "timers in the same run; the token is printed nowhere",
      _rD[0] == 0
      and 0 <= _at(_cD, "apt-get update") < _at(_cD, "apt-get -y -q -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold upgrade") < _at(_cD, "curl -fsSL https://get.docker.com")
      < _at(_cD, "docker compose version")
      < _at(_cD, f"python3 {ROOT}/scripts/cloudflare_setup.py origin-cert --tls-dir {_bsD / 'etc/tls'}")
      < _at(_cD, "docker compose -p caro-edge") < _at(_cD, "systemctl enable --now caro-cloudflare-ips.timer")
      and "made-up-cloudflare-token" not in _rD[1] + _rD[2],
      str(_rD))

# ---------------------------------------------------------------------------
print("\nan environment's settings written on the server, without an editor")


def _se(etc, *args, stdin=""):
    p = subprocess.run([_sh_bs.which("bash"), str(ROOT / "deploy/set-env.sh"), *args], input=stdin,
                       capture_output=True, text=True, timeout=30, env={"PATH": os.environ["PATH"], "CARO_ETC": str(etc)})
    return p.returncode, p.stdout, p.stderr


_seA = _bs_world()
_bs_run(_seA)
_seE = _seA / "etc"
_se_before = (_seE / "staging.env").read_text()
_se_prod = (_seE / "production.env").read_bytes()
_s1 = _se(_seE, "staging", "CARO_TURNSTILE_SECRET", stdin="0x4AAA-made-up-turnstile-secret\n")
_se_after1 = (_seE / "staging.env").read_text()
_s2 = _se(_seE, "staging", "COMPOSE_PROFILES=observe", "GRAFANA_CLOUD_PROM_URL", "GRAFANA_CLOUD_TOKEN",
          "SENTRY_DSN=https://k@o1.ingest.sentry.io/7",
          stdin="https://prometheus-prod-01.grafana.example/api/prom/push\nglc_made-up-token==\n")
_se2 = _env_of(_seE / "staging.env")
_s3 = _se(_seE, "staging", "COMPOSE_PROFILES=")
with (_seE / "staging.env").open("a") as _f_se:
    _f_se.write("CARO_EDGE_TTL=900\n")           # a second line for a name, which compose would read last
_s4 = _se(_seE, "staging", "CARO_EDGE_TTL=120")
_se4 = (_seE / "staging.env").read_text()
(_seE / "staging.env").write_text(_se4.replace("GRAFANA_CLOUD_PROM_USER=\n", ""))   # a file older than the template
_s5 = _se(_seE, "staging", "GRAFANA_CLOUD_PROM_USER=123456")
_se5 = (_seE / "staging.env").read_text()
check("DP33: a setting named alone is read from what is typed or piped and its line replaced where it is, "
      "every other line of the file byte for byte, mode 600, the value printed nowhere; NAME=value is "
      "written as given and NAME= empties it; several are written in one run; a name's second line, which "
      "would win, goes; a name the file lacks is added at its end; the other environment's file is not "
      "touched",
      _s1[0] == 0 and _se_after1 == _se_before.replace("CARO_TURNSTILE_SECRET=\n", "CARO_TURNSTILE_SECRET=0x4AAA-made-up-turnstile-secret\n")
      and _se_after1 != _se_before and "made-up-turnstile-secret" not in _s1[1] + _s1[2]
      and "staging: CARO_TURNSTILE_SECRET written" in _s1[1]
      and _s2[0] == 0 and _se2["COMPOSE_PROFILES"] == "observe"
      and _se2["GRAFANA_CLOUD_PROM_URL"] == "https://prometheus-prod-01.grafana.example/api/prom/push"
      and _se2["GRAFANA_CLOUD_TOKEN"] == "glc_made-up-token==" and _se2["SENTRY_DSN"] == "https://k@o1.ingest.sentry.io/7"
      and _se2["CARO_TURNSTILE_SECRET"] == "0x4AAA-made-up-turnstile-secret" and "glc_made-up" not in _s2[1] + _s2[2]
      and _s3[0] == 0 and _env_of(_seE / "staging.env")["COMPOSE_PROFILES"] == ""
      and _s4[0] == 0 and _se4.count("CARO_EDGE_TTL=") == 1 and "CARO_EDGE_TTL=120\n" in _se4
      and _se4.index("CARO_EDGE_TTL=120") < _se4.index("CARO_CF_API_TOKEN=")
      and _s5[0] == 0 and _se5.endswith("GRAFANA_CLOUD_PROM_USER=123456\n")
      and _mode(_seE / "staging.env") == 0o600 and (_seE / "production.env").read_bytes() == _se_prod
      and sorted(x.name for x in _seE.iterdir()) == ["nginx", "production.env", "staging.env", "tls"],
      str((_s1, _s2, _s3, _s4, _s5)))

_se_keep = (_seE / "staging.env").read_bytes()
_refused = {
    "a name the template does not have": _se(_seE, "staging", "CARO_TURNSTYLE_SECRET=x"),
    "not a name": _se(_seE, "staging", "caro_inbox=on"),
    "a pattern for a name": _se(_seE, "staging", "CARO_.*=x"),
    "another environment": _se(_seE, "preview", "CARO_INBOX=on"),
    "a path for an environment": _se(_seE, "../etc/staging", "CARO_INBOX=on"),
    "no setting": _se(_seE, "staging"),
    "which environment the file is": _se(_seE, "staging", "CARO_ENV=production"),
    "its own path": _se(_seE, "staging", "CARO_ENV_FILE=/etc/caro/production.env"),
    "a database password that is set": _se(_seE, "staging", "POSTGRES_PASSWORD=another"),
    "a space": _se(_seE, "staging", "CARO_ADMIN_TOKEN", stdin="two words\n"),
    "a dollar": _se(_seE, "staging", "CARO_ADMIN_TOKEN", stdin="pa$word\n"),
    "a hash": _se(_seE, "staging", "CARO_ADMIN_TOKEN=pass#word"),
    "a quote": _se(_seE, "staging", "CARO_ADMIN_TOKEN", stdin="it's\n"),
    "an empty line": _se(_seE, "staging", "CARO_ADMIN_TOKEN", stdin="\n"),
    "no line": _se(_seE, "staging", "CARO_ADMIN_TOKEN", stdin=""),
    "one good, one bad": _se(_seE, "staging", "CARO_INBOX=on", "CARO_ADMIN_TOKEN", stdin="pa$word\n"),
}
_se_none = _se(_seA / "nowhere", "staging", "CARO_INBOX=on")
(_seE / "production.env").write_text((_seE / "production.env").read_text().replace(
    "POSTGRES_PASSWORD=" + _env_of(_seE / "production.env")["POSTGRES_PASSWORD"], "POSTGRES_PASSWORD="))
_se_pw = _se(_seE, "production", "POSTGRES_PASSWORD", stdin="0123456789abcdef\n")
check("DP34: it changes all it was asked or nothing: a name the template does not have, or a pattern "
      "that would match one, an environment that is not one, or a path to one, the file's own environment "
      "and path, a database password that is set, a value "
      "with a space, a dollar, a hash or a quote, an empty line or none, and one bad setting beside a "
      "good one each stop it with the file byte for byte as it was; a file that is not there names the "
      "bootstrap; a database password is taken only where there is none",
      all(rc == 2 for rc, *_ in _refused.values()) and (_seE / "staging.env").read_bytes() == _se_keep
      and "is not a setting deploy/env.example has" in _refused["a name the template does not have"][2]
      and "the database was made with it" in _refused["a database password that is set"][2]
      and "no line to read" in _refused["no line"][2] and "an empty line" in _refused["an empty line"][2]
      and "pa$word" not in "".join(o + e for _, o, e in _refused.values())
      and _se_none[0] == 2 and "bootstrap.sh makes it" in _se_none[2]
      and _se_pw[0] == 0 and _env_of(_seE / "production.env")["POSTGRES_PASSWORD"] == "0123456789abcdef"
      and sorted(x.name for x in _seE.iterdir()) == ["nginx", "production.env", "staging.env", "tls"],
      str(({k: v for k, v in _refused.items() if v[0] != 2}, _se_none, _se_pw)))

# ---------------------------------------------------------------------------
print("\nthe owner's Grafana steps, through the stack's API with the owner's token")
import base64 as _b64_gf                                                 # noqa: E402

from scripts import grafana_setup as _gf                                # noqa: E402

_GF_TOKEN = "glsa_made-up-grafana-token_0123456789"
_GF_URL = "https://caro.grafana.example"


class _FakeGrafana:
    """A Grafana stack's API as the script uses it, kept in memory; every call logged."""

    def __init__(self, datasources=None, routes=(), groups=(), test_fails=None, receivers_api=True, convert=True,
                 convert_error=None, other_rules=(), other_receivers=()):
        self.datasources = datasources if datasources is not None else [
            {"uid": "p1", "name": "grafanacloud-caro-prom", "type": "prometheus"},
            {"uid": "u1", "name": "grafanacloud-usage", "type": "prometheus"},
            {"uid": "l1", "name": "grafanacloud-caro-logs", "type": "loki"}]
        self.dashboard, self.version = None, 0
        self.groups = {g: "name: " + g + "\n" for g in groups}     # the folder CARO's groups
        self.contacts = []
        self.tree = {"receiver": "grafana-default-email", "group_by": ["grafana_folder", "alertname"],
                     "routes": [dict(r) for r in routes]}
        self.test_fails, self.receivers_api, self.convert, self.tests = test_fails, receivers_api, convert, []
        self.convert_error, self.other_rules, self.other_receivers = convert_error, list(other_rules), list(other_receivers)
        self.calls = []

    def _ok(self, result, raw=None):
        body = raw if raw is not None else json.dumps(result).encode()
        return _ctx_cf.nullcontext(type("R", (), {"read": lambda _s: body})())

    def _no(self, req, code, message):
        raise _ue_cf.HTTPError(req.full_url, code, "No", {}, _io_cf.BytesIO(json.dumps({"message": message}).encode()))

    def __call__(self, req, timeout=30):
        u = _up_cf.urlparse(req.full_url)
        q = dict(_up_cf.parse_qsl(u.query))
        m, path = req.get_method(), _up_cf.unquote(u.path)
        raw = req.data or b""
        self.calls.append((m, path, raw, {k.lower(): v for k, v in req.header_items()}, u.netloc))
        body = json.loads(raw) if raw and req.get_header("Content-type") == "application/json" else None
        if path == "/api/health":
            return self._ok({"version": "13.3.0"})
        if path == "/api/datasources":
            return self._ok(self.datasources)
        if path == "/api/dashboards/uid/caro":
            if self.dashboard is None:
                self._no(req, 404, "Dashboard not found")
            return self._ok({"dashboard": self.dashboard, "meta": {}})
        if path == "/api/dashboards/db" and m == "POST":
            self.version += 1
            self.dashboard = {**body["dashboard"], "id": 7, "version": self.version}
            return self._ok({"status": "success", "uid": "caro", "version": self.version})
        if path == "/api/folders":
            return self._ok([{"uid": "f1", "title": "CARO"}] if self.groups else [])
        if path == "/api/v1/provisioning/alert-rules":
            return self._ok(self.other_rules + [{"title": f"r{i}", "ruleGroup": g, "folderUID": "f1"}
                                                for i, g in enumerate(self.groups)])
        if path == "/api/convert/prometheus/config/v1/rules/CARO" and m == "POST":
            if not self.convert:
                self._no(req, 404, "Not found")
            if self.convert_error:
                self._no(req, 400, self.convert_error)
            text_ = raw.decode()
            self.groups[text_.split("\n", 1)[0].split(":", 1)[1].strip()] = text_
            return self._ok({"status": "success"})
        if path.startswith("/api/convert/prometheus/config/v1/rules/CARO/") and m == "DELETE":
            self.groups.pop(path.rsplit("/", 1)[1])
            return self._ok({"status": "success"})
        if path == "/api/v1/provisioning/contact-points":
            if m == "GET":
                return self._ok([{**c, "settings": {**c["settings"], "bottoken": "[REDACTED]"}}
                                 for c in self.contacts if c["name"] == q.get("name")])
            self.contacts.append({**body, "uid": f"cp{len(self.contacts) + 1}"})
            return self._ok(self.contacts[-1])
        if path.startswith("/api/v1/provisioning/contact-points/") and m == "PUT":
            for c in self.contacts:
                if c["uid"] == path.rsplit("/", 1)[1]:
                    c.update(body)
            return self._ok({"message": "contactpoint updated"})
        if path == "/api/v1/provisioning/policies":
            if m == "GET":
                return self._ok(self.tree)
            self.tree = body
            return self._ok({"message": "policies updated"})
        if path == "/api/frontend/settings":
            return self._ok({"namespace": "stacks-42"})
        base = "/apis/notifications.alerting.grafana.app/v1beta1/namespaces/stacks-42/receivers"
        if path.startswith("/apis/") and not self.receivers_api:
            self._no(req, 404, "page not found")
        if path == base:
            return self._ok({"items": self.other_receivers + [{"metadata": {"name": _b64_gf.urlsafe_b64encode(c["name"].encode()).decode().rstrip("=")},
                                        "spec": {"title": c["name"], "integrations": [
                                            {"uid": c["uid"], "type": "telegram", "settings": {"chatid": c["settings"]["chatid"]},
                                             "secureFields": {"bottoken": True}}]}} for c in self.contacts]})
        if path.startswith(base + "/") and path.endswith("/test") and m == "POST":
            self.tests.append((path, body))
            if self.test_fails:
                return self._ok({"status": "failure", "error": self.test_fails})
            return self._ok({"status": "success", "duration": "1s"})
        raise AssertionError(f"the fake has no {m} {path}")


def _gf_run(fake, *argv, env=None, root=None):
    out, err = _io_cf.StringIO(), _io_cf.StringIO()
    e = {"GRAFANA_URL": _GF_URL, "GRAFANA_TOKEN": _GF_TOKEN, "CARO_ALERT_TELEGRAM_TOKEN": "123456:made-up-bot",
         "CARO_ALERT_TELEGRAM_CHAT": "-1009876543210"} if env is None else env
    with _ctx_cf.redirect_stderr(err):
        rc = _gf.main(list(argv), env=e, opener=fake, out=lambda line: out.write(line + "\n"),
                      **({"root": root} if root else {}))
    return rc, out.getvalue(), err.getvalue()


def _gwrites(fake):
    return [(m, p) for m, p, *_ in fake.calls if m != "GET"]


_alerts_text = text("deploy/grafana/alerts.yml")
_groups = _gf.rule_groups(_alerts_text)
_rebuilt = "groups:\n" + "\n".join(
    "\n".join(["  - " + d.split("\n")[0]] + [("    " + ln) if ln.strip() else "" for ln in d.rstrip("\n").split("\n")[1:]])
    for _, d in _groups)
_tail = _alerts_text.split("groups:\n", 1)[1].rstrip("\n")
try:
    _gf.rule_groups("groups:\n  - name: a\n    rules:\n  oops: 1\n")
    _bad_layout = "taken"
except _gf.GrafanaError as e:
    _bad_layout = str(e)
check("DP35: the alerts' file is cut into its groups as the ruler API takes them, each a document of its "
      "own, and put back together they are the file again, every line that is not blank in its place; all "
      "seven alerts are in them; a line outside a group stops it",
      [n for n, _ in _groups] == ["caro-availability", "caro-search", "caro-corpus", "caro-collection"]
      and all(d.startswith("name: " + n + "\n") for n, d in _groups)
      and [ln.rstrip() for ln in _rebuilt.split("\n") if ln.strip()]
      == [ln.rstrip() for ln in ("groups:\n" + _tail).split("\n") if ln.strip()]
      and sum(d.count("\n  - alert: ") for _, d in _groups) == 7 == _alerts_text.count("- alert: ")
      and "outside its group" in _bad_layout,
      str([n for n, _ in _groups]))

_g1 = _FakeGrafana()
_gr1 = [_gf_run(_g1, "dashboard") for _ in range(2)]
_posted = [c for c in _g1.calls if c[0] == "POST"]
_sent_board = json.loads(_posted[0][2])["dashboard"] if _posted else {}
_dsvar = [v for v in _sent_board.get("templating", {}).get("list", []) if v.get("type") == "datasource"]
_tmp_gf = tempfile.TemporaryDirectory()
_root_gf = Path(_tmp_gf.name)
(_root_gf / "deploy/grafana").mkdir(parents=True)
_changed_board = json.loads(text("deploy/grafana/caro.json"))
_changed_board["title"] = "CARO, changed"
(_root_gf / "deploy/grafana/caro.json").write_text(json.dumps(_changed_board))
_gr1c = _gf_run(_g1, "dashboard", root=_root_gf)
_g1o = _FakeGrafana(datasources=[{"uid": "only", "name": "prometheus", "type": "prometheus"}])
_gr1o = _gf_run(_g1o, "dashboard")
_g1m = _FakeGrafana(datasources=[{"uid": "a", "name": "one-prom", "type": "prometheus"},
                                 {"uid": "b", "name": "two-prom", "type": "prometheus"}])
_gr1m = _gf_run(_g1m, "dashboard")
_gr1n = _gf_run(_g1m, "dashboard", "--datasource", "two-prom")
_g1p = _FakeGrafana(datasources=[{"uid": "old", "name": "grafanacloud-caro-prom", "type": "prometheus"},
                                 {"uid": "new", "name": "caro-prom", "type": "prometheus"}])
_gr1p = _gf_run(_g1p, "dashboard", "--datasource", "caro-prom")
check("DP36: the dashboard is put on the stack's own Prometheus -- the only one, or the one whose name ends "
      "-prom, or the one of exactly the name given -- the file as it is but for its datasource chosen; run again it is found "
      "and not written; a changed file is written over it; two that end -prom and none named stops it, "
      "naming them",
      [rc for rc, *_ in _gr1] == [0, 0] and len(_posted) == 1 and _posted[0][1] == "/api/dashboards/db"
      and json.loads(_posted[0][2])["overwrite"] is True and _sent_board.get("id") is None
      and _dsvar and _dsvar[0]["current"] == {"selected": True, "text": "grafanacloud-caro-prom", "value": "p1"}
      and {k: v for k, v in _sent_board.items() if k not in ("templating", "id")}
      == {k: v for k, v in json.loads(text("deploy/grafana/caro.json")).items() if k != "templating"}
      and "there already" in _gr1[1][1]
      and _gr1c[0] == 0 and _g1.dashboard["title"] == "CARO, changed" and "brought to the file" in _gr1c[1]
      and _gr1o[0] == 0 and _g1o.dashboard["templating"]["list"][0]["current"]["value"] == "only"
      and _gr1m[0] == 1 and "one-prom, two-prom" in _gr1m[2] and _gwrites(_g1m)[:1] == [("POST", "/api/dashboards/db")]
      and _g1m.dashboard["templating"]["list"][0]["current"]["value"] == "b"
      and _gr1p[0] == 0 and _g1p.dashboard["templating"]["list"][0]["current"]["value"] == "new",
      str((_gr1, _gr1c, _gr1o, _gr1m, _gr1n, _gr1p)))

_g2 = _FakeGrafana(groups=("caro-retired", "caro-search"),
                   other_rules=[{"title": "theirs", "ruleGroup": "their-group", "folderUID": "f2"}])
_gr2d = _gf_run(_g2, "alerts", "--dry-run")
_w2d = _gwrites(_g2)
_gr2 = _gf_run(_g2, "alerts")
_conv = [c for c in _g2.calls if c[0] == "POST"]
_gr2x = _gf_run(_FakeGrafana(convert=False), "alerts")
_gr2e = _gf_run(_FakeGrafana(convert_error="invalid rule group: unknown function rat"), "alerts")
check("DP37: the alerts are loaded group by group into the folder CARO through Grafana's conversion of "
      "Prometheus rules, each group's document as the file has it, as YAML, on the stack's Prometheus; a "
      "group the folder has and the file no longer does is taken away, and no other, nor any group of "
      "another folder; --dry-run loads nothing; a Grafana that does not convert them says to load them "
      "with mimirtool, and any other refusal is said in Grafana's words",
      _gr2d[0] == 0 and _w2d == [] and _gr2d[1].count("would:") == 5
      and _gr2[0] == 0 and [c[1] for c in _conv] == ["/api/convert/prometheus/config/v1/rules/CARO"] * 4
      and [c[2].decode() for c in _conv] == [d for _, d in _groups]
      and all(c[3].get("content-type") == "application/yaml"
              and c[3].get("x-grafana-alerting-datasource-uid") == "p1" for c in _conv)
      and ("DELETE", "/api/convert/prometheus/config/v1/rules/CARO/caro-retired") in _gwrites(_g2)
      and sorted(_g2.groups) == sorted(n for n, _ in _groups)
      and _gr2x[0] == 1 and "does not convert Prometheus rules" in _gr2x[2] and "mimirtool" in _gr2x[2]
      and _gr2e[0] == 1 and "unknown function rat" in _gr2e[2] and "does not convert" not in _gr2e[2]
      and [p for m, p in _gwrites(_g2) if m == "DELETE"] == ["/api/convert/prometheus/config/v1/rules/CARO/caro-retired"],
      str((_gr2d, _gr2, _gr2x, _gr2e)))

_theirs = {"receiver": "someone-else", "object_matchers": [["team", "=", "other"]]}
_g3 = _FakeGrafana(routes=[_theirs])
_gr3 = [_gf_run(_g3, "telegram") for _ in range(2)]
_w3 = _gwrites(_g3)
_tmp_gf2 = tempfile.TemporaryDirectory()
_envf = Path(_tmp_gf2.name) / "production.env"
_envf.write_text("CARO_ENV=production\nCARO_ALERT_TELEGRAM_TOKEN=654321:from-the-file\nCARO_ALERT_TELEGRAM_CHAT=-100555\n")
_g3f = _FakeGrafana()
_gr3f = _gf_run(_g3f, "telegram", "--env-file", str(_envf), env={"GRAFANA_URL": _GF_URL, "GRAFANA_TOKEN": _GF_TOKEN})
_gr3n = _gf_run(_FakeGrafana(), "telegram", env={"GRAFANA_URL": _GF_URL, "GRAFANA_TOKEN": _GF_TOKEN})
_gr3b = _gf_run(_FakeGrafana(), "telegram", env={"GRAFANA_URL": _GF_URL, "GRAFANA_TOKEN": _GF_TOKEN,
                                                 "CARO_ALERT_TELEGRAM_TOKEN": "123456:made-up-bot"})
_timing = [(r["group_wait"], r["group_interval"], r["repeat_interval"]) for r in _g3.tree["routes"][:2]]
check("DP38: the contact point caro-telegram is made once with the server's bot and chat, editable in "
      "Grafana's pages, and written again on a second run; the two routes -- a page within half a minute and "
      "again every four hours, tickets every three hours and again each day -- go in front of the stack's own, "
      "which stay as they were, and on a second run are found and not written; the bot and the chat can "
      "come from the server's env file; without either it stops before anything",
      [rc for rc, *_ in _gr3] == [0, 0] and len(_g3.contacts) == 1
      and _g3.contacts[0]["type"] == "telegram"
      and _g3.contacts[0]["settings"] == {"bottoken": "123456:made-up-bot", "chatid": "-1009876543210"}
      and [m for m, _ in _w3] == ["POST", "PUT", "PUT"] and _w3[1] == ("PUT", "/api/v1/provisioning/policies")
      and all(c[3].get("x-disable-provenance") == "true" for c in _g3.calls if c[0] in ("POST", "PUT"))
      and _g3.tree["routes"] == _gf.ROUTES + [_theirs] and _g3.tree["receiver"] == "grafana-default-email"
      and [r["object_matchers"][1] for r in _g3.tree["routes"][:2]] == [["severity", "=", "page"], ["severity", "=", "ticket"]]
      and all(r["object_matchers"][0] == ["grafana_folder", "=", "CARO"] for r in _g3.tree["routes"][:2])
      and "there already" in _gr3[1][1] and not any("made-up-bot" in o + e for _, o, e in _gr3)
      and _gr3f[0] == 0 and _g3f.contacts[0]["settings"] == {"bottoken": "654321:from-the-file", "chatid": "-100555"}
      and _gr3n[0] == 2 and "CARO_ALERT_TELEGRAM_TOKEN" in _gr3n[2] and _gr3b[0] == 2
      and _timing == [("30s", "5m", "4h"), ("10m", "3h", "1d")],
      str((_gr3, _gr3f, _gr3n, _gr3b, _w3, _timing)))

_g4 = _FakeGrafana(other_receivers=[{"metadata": {"name": "ZW1haWw"}, "spec": {"title": "email", "integrations": [
    {"uid": "em1", "type": "email", "settings": {"addresses": "ops@example.invalid"}}]}}])
_gr4 = _gf_run(_g4, "all")
_g4d = _FakeGrafana()
_gr4d = _gf_run(_g4d, "all", "--dry-run")
_g4f = _FakeGrafana(test_fails="failed to send telegram message: Bad Request: chat not found")
_gr4f = _gf_run(_g4f, "all")
_gr4n = _gf_run(_FakeGrafana(), "test")
_gr4o = _gf_run(_FakeGrafana(receivers_api=False), "all")
check("DP39: all does the dashboard, the alerts, the contact point and its routes, then has Grafana send "
      "a test to the chat, finding the contact point by its title in the stack's own namespace, among others; "
      "with --dry-run it writes and sends nothing; a test "
      "Grafana could not send stops it with Grafana's words; with no contact point, or no API to test from, "
      "it says what to do",
      _gr4[0] == 0 and _g4.dashboard is not None and len(_g4.groups) == 4 and len(_g4.contacts) == 1
      and len(_g4.tests) == 1 and _g4.tests[0][0].endswith("/namespaces/stacks-42/receivers/Y2Fyby10ZWxlZ3JhbQ/test")
      and _g4.tests[0][1]["integration"]["uid"] == "cp1" and "sent by Grafana" in _gr4[1]
      and _gr4f[0] == 1 and "chat not found" in _gr4f[2]
      and _gr4n[0] == 1 and "run telegram first" in _gr4n[2]
      and _gr4o[0] == 1 and "Contact points -> caro-telegram -> Test" in _gr4o[2]
      and _gr4d[0] == 0 and _gwrites(_g4d) == [] and _g4d.tests == [] and "would: ask Grafana to send a test" in _gr4d[1],
      str((_gr4, _gr4f, _gr4n, _gr4o, _gr4d)))


class _GfRefusing(_FakeGrafana):
    def __call__(self, req, timeout=30):
        self.calls.append((req.get_method(), req.full_url, b"", {}, ""))
        self._no(req, 403, "You'll need additional permissions to perform this action")


_gr5a = _gf_run(_FakeGrafana(), "status", env={"GRAFANA_URL": _GF_URL})
_gr5h = _gf_run(_FakeGrafana(), "status", env={"GRAFANA_URL": "http://caro.grafana.example", "GRAFANA_TOKEN": _GF_TOKEN})
_gr5l = _gf_run(_FakeGrafana(), "status", env={"GRAFANA_URL": "http://127.0.0.1:3300", "GRAFANA_TOKEN": _GF_TOKEN})
_gr5r = _gf_run(_GfRefusing(), "dashboard")
_gevery = [c for f in (_g1, _g2, _g3, _g4) for c in f.calls]
check("DP40: without the stack's address and token it stops before asking anything; an address that is "
      "not https stops it, but on this machine's own; a refusal stops it with Grafana's words and what the "
      "token needs; every request goes to the stack with the token as a bearer, and the token is in no "
      "line printed",
      _gr5a[0] == 2 and "GRAFANA_TOKEN" in _gr5a[2]
      and _gr5h[0] == 2 and "https" in _gr5h[2] and _gr5l[0] == 0
      and _gr5r[0] == 1 and "additional permissions" in _gr5r[2] and "Admin" in _gr5r[2]
      and all(c[4] == "caro.grafana.example" and c[3].get("authorization") == f"Bearer {_GF_TOKEN}" for c in _gevery)
      and not any(_GF_TOKEN in o + e for runs in (_gr1, _gr3, [_gr4, _gr4f, _gr5r]) for _, o, e in runs),
      str((_gr5a, _gr5h, _gr5l, _gr5r)))

# ---------------------------------------------------------------------------
print("\neach green merge delivered to the site Vercel builds, a fast-forward and never a force")


def _git(cwd, *args):
    p = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", "-c", "init.defaultBranch=main",
                        *args], cwd=cwd, capture_output=True, text=True, env={**os.environ, "HOME": str(cwd)})
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr}")
    return p.stdout.strip()


def _dl_world():
    """This repository at A -> B -> C; Tecso-Dev/caro, a bare repository, at A; its checkout."""
    d = Path(tempfile.mkdtemp())
    src, origin, dst = d / "src", d / "origin.git", d / "dst"
    src.mkdir()
    _git(src, "init", "-q")
    shas = []
    for n in "ABC":
        (src / "f").write_text(n)
        _git(src, "add", "f")
        _git(src, "commit", "-q", "-m", n)
        shas.append(_git(src, "rev-parse", "HEAD"))
    _git(d, "init", "-q", "--bare", str(origin))
    _git(src, "push", "-q", str(origin), f"{shas[0]}:refs/heads/main")
    _git(d, "clone", "-q", str(origin), str(dst))
    return d, src, origin, dst, shas


def _deliver(src, dst, sha):
    p = subprocess.run(["sh", str(ROOT / "deploy/deliver.sh"), str(src), str(dst), sha], capture_output=True,
                       text=True, timeout=60, env={**os.environ, "HOME": str(dst.parent)})
    return p.returncode, p.stdout, p.stderr


def _main_of(origin):
    return _git(origin, "rev-parse", "main")


_dlA, _srcA, _orgA, _dstA, (_a, _b, _c) = _dl_world()
_d1 = _deliver(_srcA, _dstA, _c)
_after1 = _main_of(_orgA)
_d2 = _deliver(_srcA, _dstA, _c)
# A later merge, D, delivered before C's job runs.
(_srcA / "f").write_text("D")
_git(_srcA, "commit", "-q", "-am", "D")
_dD = _git(_srcA, "rev-parse", "HEAD")
_git(_srcA, "push", "-q", str(_orgA), f"{_dD}:refs/heads/main")
_git(_srcA, "checkout", "-q", _c)
_d3 = _deliver(_srcA, _dstA, _c)
check("DP41: a commit of main is pushed to Tecso-Dev/caro's main where that main is behind it, and only "
      "then; run again it is found there; where a later merge was delivered first, it is found held there "
      "and nothing moves back",
      _d1[0] == 0 and _after1 == _c and f"{_a} -> {_c}" in _d1[1]
      and _d2[0] == 0 and "already" in _d2[1] and _main_of(_orgA) == _dD
      and _d3[0] == 0 and "a later merge was delivered first" in _d3[1] and _main_of(_orgA) == _dD,
      str((_d1, _d2, _d3)))

_dlB, _srcB, _orgB, _dstB, (_a2, _b2, _c2) = _dl_world()
# Tecso-Dev/caro's main gets a commit of its own, which this repository does not have.
_other = Path(tempfile.mkdtemp()) / "other"
_git(_dlB, "clone", "-q", str(_orgB), str(_other))
(_other / "g").write_text("theirs")
_git(_other, "add", "g")
_git(_other, "commit", "-q", "-m", "someone else's")
_git(_other, "push", "-q", "origin", "HEAD:refs/heads/main")
_theirs = _main_of(_orgB)
_d4 = _deliver(_srcB, _dstB, _c2)
_git(_srcB, "checkout", "-q", _b2)
_d5 = _deliver(_srcB, _dstB, _c2)
# A main GitHub would not let the key write: the push refused, and the job with it.
_dlC, _srcC, _orgC, _dstC, (_a3, _b3, _c3) = _dl_world()
(_orgC / "hooks/pre-receive").write_text("#!/bin/sh\necho 'refused: main is protected' >&2\nexit 1\n")
(_orgC / "hooks/pre-receive").chmod(0o755)
_d6 = _deliver(_srcC, _dstC, _c3)
_dl_text = text("deploy/deliver.sh")
check("DP42: where Tecso-Dev/caro's main has a commit of its own, nothing is pushed and the job fails, saying "
      "so; a checkout that is not at the commit pushes nothing; a push GitHub refuses fails the job; the "
      "script never forces a push",
      _d4[0] == 1 and "has commits" in _d4[2] and _main_of(_orgB) == _theirs
      and _d5[0] == 1 and f"is at {_b2}, not {_c2}" in _d5[2] and _main_of(_orgB) == _theirs
      and _d6[0] != 0 and "main is protected" in _d6[2] and _main_of(_orgC) == _a3 and "->" not in _d6[1]
      and "--force" not in _dl_text and '"+' not in _dl_text and " -f " not in _dl_text,
      str((_d4, _d5)))

_dj = _wf[_wf.index("\n  deliver:"):]
_dsteps = {n: _step(_dj, n) for n in ("No delivery key yet", "CI passed on this commit", "Tecso-Dev/caro, by its deploy key",
                                       "Its main brought to this commit, a fast-forward and never a force",
                                       "The site runs this commit", "The site, read from the outside")}
check("DP43: each merge into this repository's main is delivered only after its images passed and CI passed "
      "on the very commit, and never from a pull request; without the deploy key it says so and does "
      "nothing; with it, Tecso-Dev/caro is reached by that key alone, its main moved by deliver.sh, and "
      "the site waited for until it runs the commit, then read from the outside; the job may read the "
      "runs and the code, and write nothing here",
      "    needs: images\n" in _dj
      and "if: github.event_name == 'push' && github.ref == 'refs/heads/main' && github.repository == 'sahandmusanezhad/caro'" in _dj
      and all(_dsteps.values())
      and "if: env.HAS_KEY != 'true'" in _dsteps["No delivery key yet"]
      and all("if: env.HAS_KEY == 'true'" in t for n, t in _dsteps.items() if n != "No delivery key yet")
      and "HAS_KEY: ${{ secrets.TECSO_DEPLOY_KEY != '' }}" in _dj
      and _dj.count("secrets.TECSO_DEPLOY_KEY") == 2
      and "ssh-key: ${{ secrets.TECSO_DEPLOY_KEY }}" in _dsteps["Tecso-Dev/caro, by its deploy key"]
      and "repository: Tecso-Dev/caro" in _dsteps["Tecso-Dev/caro, by its deploy key"]
      and '--workflow ci.yml --commit "$GITHUB_SHA"' in _dsteps["CI passed on this commit"]
      and '"completed success") echo' in _dsteps["CI passed on this commit"]
      and 'completed*) echo "::error::ci did not pass on this commit ($run): nothing is delivered"; exit 1 ;;'
          in _dsteps["CI passed on this commit"]
      and _dsteps["CI passed on this commit"].rstrip().endswith("exit 1")
      and _before(_dj, "- name: CI passed on this commit", "- name: Tecso-Dev/caro, by its deploy key")
      and _before(_dj, "- name: Tecso-Dev/caro, by its deploy key", "- name: Its main brought to this commit")
      and 'sh deploy/deliver.sh "$GITHUB_WORKSPACE" "$GITHUB_WORKSPACE/tecso" "$GITHUB_SHA"'
          in _dsteps["Its main brought to this commit, a fast-forward and never a force"]
      and _before(_dj, "- name: Its main brought to this commit", "- name: The site runs this commit")
      and '--build "$GITHUB_SHA"' in _dsteps["The site runs this commit"]
      and "scripts/site_check.py --site \"$SITE\"" in _dsteps["The site, read from the outside"]
      and "      contents: read\n      actions: read\n" in _dj and "packages: write" not in _dj
      and "--force" not in _dj,
      _dj[:300])

# The weekly audit (.github/workflows/audit.yml), the owner's choice of 2026-11-19.
_au = text(".github/workflows/audit.yml")
_au_on = _au[_au.index("\non:"):_au.index("\npermissions:")]
_au_site = _au[_au.index("\n  site:"):_au.index("\n  api:")]
_au_api = _au[_au.index("\n  api:"):]
_py_image = re.search(r"^FROM python:(\d+\.\d+)", text("Dockerfile"), re.MULTILINE)
check("DP44: the dependencies are read against the advisories every week and by hand, never on a push or a "
      "pull request, so an advisory stops no merge and no delivery; the site's whole lockfile fails on high "
      "or critical, and what the API's image installs -- numpy and webapp/requirements.txt, on the image's "
      "Python -- fails on any; pip-audit is at a version, the runners and Node are ci.yml's, and the jobs "
      "may read the code and nothing more",
      re.search(r'\n  schedule:\n    - cron: "\d+ \d+ \* \* \d"\n', _au_on) is not None
      and "\n  workflow_dispatch:\n" in _au_on and "push" not in _au_on and "pull_request" not in _au_on
      and re.findall(r"^\s*([\w-]+): (read|write)$", _au, re.MULTILINE) == [("contents", "read")]
      and "    defaults:\n      run:\n        working-directory: webapp/web\n" in _au_site
      and "        run: npm audit --audit-level=high\n" in _au_site and "--omit" not in _au_site
      and _py_image is not None and f'python-version: "{_py_image.group(1)}"' in _au_api
      and "pip install numpy -r webapp/requirements.txt" in text("Dockerfile")
      and re.search(r'run: python -m pip install "pip-audit==\d+\.\d+\.\d+"\n', _au_api) is not None
      and 'echo numpy > "$RUNNER_TEMP/core.txt"' in _au_api
      and 'python -m pip_audit -r "$RUNNER_TEMP/core.txt" -r webapp/requirements.txt\n' in _au_api
      and len(re.findall(r"runs-on: (\S+)", _au)) == 2 and "continue-on-error" not in _au and "if:" not in _au
      and set(re.findall(r"runs-on: (\S+)", _au)) == set(re.findall(r"runs-on: (\S+)", _ci))
      and re.findall(r"node-version: (\S+)", _au) == sorted(set(re.findall(r"node-version: (\S+)", _ci)))
      and "npm audit" not in _ci and "pip-audit" not in _ci and "npm ci --no-audit" in _ci
      and "audit" not in _wf.replace("--no-audit", ""),
      _au[:300])

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
