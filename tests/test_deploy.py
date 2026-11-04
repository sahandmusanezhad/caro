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
      set(_svc) == {"postgres", "catalog-load", "api", "site", "alerts", "edge-purge"}
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
            "CARO_TURNSTILE_SECRET")
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

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
