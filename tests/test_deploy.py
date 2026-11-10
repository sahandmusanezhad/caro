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
check("DP26: the switch keeps what caro.noxioai.com was beside the owner, then makes it an A record to "
      "the server, proxied, in one batch that takes Vercel's CNAME away; run again it is found; a switch "
      "to a new address keeps the first switch's file; undone, in one batch, Vercel's CNAME is back as it "
      "was and the file is gone; with nothing kept, undo refuses; a batch Cloudflare refuses leaves the "
      "name as it was; a record left beside the server's is taken away, the A record alone kept; and "
      "where the list answers with other names' records too, none of them is taken away or kept as "
      "what the name was",
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
      and [x["name"] for x in json.loads((Path(_tmp_cf3.name) / "cloudflare-undo.json").read_text())] == ["caro.noxioai.com"],
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
_every = [c for f in (_f1, _f2, _f3, _f3h, _f4, _f6) for c in f.calls]
_files = "".join(p.read_text() for p in _here_cf.iterdir()) + "".join(p.read_text() for p in _tls.iterdir())
check("DP28: without a token it stops before asking anything; Cloudflare's refusal stops it with "
      "Cloudflare's words and the permission that command needs; the zone is the one of that exact name, "
      "and a token that sees only another stops it; every request goes to api.cloudflare.com with the "
      "token as a bearer, and the token is in no line printed and no file written",
      _cf5a[0] == 2 and "CLOUDFLARE_API_TOKEN" in _cf5a[2]
      and _cf5b[0] == 1 and "Authentication error" in _cf5b[2] and "Zone / Zone / Read" in _cf5b[2]
      and _cf5c[0] == 1 and "Zone / Cache Rules / Edit" in _cf5c[2]
      and _cf5z[0] == 0 and _writes(_f5z) == [("POST", "/zones/z1/dns_records")]
      and _cf5n[0] == 1 and "sees no zone noxioai.com" in _cf5n[2]
      and all(c[4] == "api.cloudflare.com" and c[3] == f"Bearer {_CF_TOKEN}" for c in _every)
      and not any(_CF_TOKEN in o + e for runs in (_cf1, _cf2, _cf3, _cf4, _cf6) for _, o, e in runs)
      and _CF_TOKEN not in _cf5b[2] + _cf5c[2] and _CF_TOKEN not in _files,
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
      "repository the server pulls from, keeps no key to the server, and waits on an environment "
      "only where a variable names it",
      _wf.index("docker build --target test") < _wf.index("docker push")
      and _wf.index("scripts/site_check.py --site http://127.0.0.1:3000") < _wf.index("docker push")
      and _wf.count(_only_here) == 2 and "if: github.event_name == 'push'\n" not in _wf
      and "ghcr.io/sahandmusanezhad/" in text("deploy/env.example") and "ssh" not in _wf.lower()
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

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
