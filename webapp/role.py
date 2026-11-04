"""One image for the API and the workers, a role per command (docs/REARCHITECTURE.md, phase 1).

    python -m webapp.role api                 serve webapp.api.main:app
    python -m webapp.role catalog-load [...]  scripts/catalog_load.py, into CARO_CATALOG_URL
    python -m webapp.role healthcheck         exit 0 when this container's API answers /api/health

The image's entrypoint is this module and its default command is `api`, so
`docker run <image>` serves and `docker run <image> catalog-load --verify`
checks the catalog. Every setting is read from the environment by the code
that uses it; nothing secret is in the image. A role reads only its own:

    CARO_API_PORT              the port the API listens on inside the container (8000)
    CARO_FORWARDED_ALLOW_IPS   the addresses whose X-Forwarded-* headers uvicorn believes:
                               the edge's network, set by compose; unset, none is believed

One worker process, on purpose: the limits on the inbox and on the operator's
token, and the memory of spent authenticator codes, are a process's
(webapp/api/security.py, totp.py), so a second worker would halve every
limit and could accept one code twice.
"""
from __future__ import annotations

import os
import sys
import urllib.request

ROLES = ("api", "catalog-load", "healthcheck")


def _port(env) -> int:
    raw = env.get("CARO_API_PORT", "8000")
    if not raw.isdigit() or not 0 < int(raw) < 65536:
        raise SystemExit(f"CARO_API_PORT is not a port: {raw!r}")
    return int(raw)


def api_argv(env) -> list[str]:
    """The uvicorn command line the api role runs, from the environment."""
    argv = ["uvicorn", "webapp.api.main:app", "--host", "0.0.0.0", "--port", str(_port(env)),
            "--workers", "1", "--no-server-header", "--timeout-graceful-shutdown", "20"]
    allow = env.get("CARO_FORWARDED_ALLOW_IPS", "").strip()
    if allow:
        argv += ["--proxy-headers", "--forwarded-allow-ips", allow]
    else:
        argv += ["--no-proxy-headers"]
    return argv


def healthy(port: int, opener=urllib.request.urlopen) -> bool:
    try:
        with opener(f"http://127.0.0.1:{port}/api/health", timeout=3) as r:
            return r.status == 200
    except OSError:
        return False


def main(argv: list[str] | None = None, env=None, execvp=os.execvp) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if env is None else env
    role = argv[0] if argv else "api"
    if role == "api":
        cmd = api_argv(env)
        execvp(cmd[0], cmd)
        return 0
    if role == "catalog-load":
        from scripts import catalog_load
        return catalog_load.main(argv[1:])
    if role == "healthcheck":
        return 0 if healthy(_port(env)) else 1
    print(f"unknown role {role!r}; the roles are {', '.join(ROLES)}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
