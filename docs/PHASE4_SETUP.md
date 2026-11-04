# Phase 4 — the edge, the owner's steps

Phase 4 of the plan ([REARCHITECTURE](REARCHITECTURE.md); Tecso-Dev/caro
issue 7) is the edge: what Cloudflare keeps, Turnstile, and the load the
search holds. What a session could build is built:

- **What the edge may keep** (`webapp/api/edge.py`): `/api/models`,
  `/api/model` and `/api/corpus`, and no other answer, say a shared cache
  may keep them for `CARO_EDGE_TTL` seconds (300 by default), with an ETag
  and the served corpus's digest (`X-Caro-Corpus`); `/api/health` names the
  same digest and is kept by nobody. A fault about the source is never kept.
- **The purge** (`scripts/edge_purge.py`): after a deploy that changed the
  runs, what Cloudflare kept is purged, by host where Cloudflare allows it.
- **Turnstile** (`webapp/api/turnstile.py`, `components/Turnstile.tsx`) on
  the seller's code request, where every message spends the SMS account's
  credit, and on the contact form: verified on the server; off without its
  keys.
- **The baseline** ([PERF](PERF.md), `perf/search.js`): 28 ms at the 95th
  percentile with ten users here; the target, 300 ms on the server.
- **The site check** prints an `edge` line: what Cloudflare kept of the
  models, and whether its corpus is the one health names.

What is left is in Cloudflare's dashboard, GitHub's settings and the
server's env files. No step asks for a key to be written into this
repository or pasted into a conversation.

## 1. The cache rule

Phase 0's rule bypasses the cache for every `/api/` address. In Cloudflare,
**Caching → Cache Rules**, keep it, and add a rule **after** it — when two
match, the later one's settings win:

- name: *API answers that say they may be kept*
- when: *URI Path* is in `/api/models`, `/api/model`, `/api/corpus`
- then: **Eligible for cache**; *Edge TTL*: use the origin's cache-control
  header; *Browser TTL*: respect the origin.

Worked when, from any machine, twice:

```
curl -sI https://caro.noxioai.com/api/models | grep -iE 'cf-cache-status|x-caro-corpus|cache-control'
```

the second answer says `cf-cache-status: HIT`, and `python3
scripts/site_check.py --site https://caro.noxioai.com` prints an `edge` line
that ends `the same`.

## 2. The purge

In Cloudflare, **My Profile → API Tokens → Create Token → Custom token**:
permission *Zone → Cache Purge → Purge*, zone resources *Include → Specific
zone → noxioai.com*. The zone's id is on the zone's **Overview** page. On the
server, in `/etc/caro/production.env` and `/etc/caro/staging.env`:

```
CARO_CF_API_TOKEN=<the token>
CARO_CF_ZONE_ID=<the zone's id>
CARO_SITE_HOST=caro.noxioai.com            (staging: caro-staging.noxioai.com)
```

Worked when, after the next release, `journalctl -u caro-pull@production`
shows `edge-purge: caro.noxioai.com purged by host` — or `by addresses`,
where Cloudflare's plan does not purge by host, and then a model's page
lives out its five minutes.

## 3. Turnstile

In Cloudflare, **Turnstile → Add widget**: name `caro`, hostnames
`caro.noxioai.com` and `caro-staging.noxioai.com`, mode *Managed*. It gives a
site key and a secret key. In this order, because a secret set before the
site draws the widget refuses every code request:

1. GitHub, **Settings → Secrets and variables → Actions → Variables**:
   `NEXT_PUBLIC_TURNSTILE_SITE_KEY` = the site key (it is public: the
   browser is sent it). The next merge's site image draws the check.
2. Staging's file: `CARO_TURNSTILE_SECRET=<the secret key>`. Then
   `https://caro-staging.noxioai.com/login` shows the check, and a code
   arrives; `/contact` sends a message.
3. The next release tag; then production's file, the same line.

## 4. The baseline on the server

On the server, against staging's API, inside its own network, for a minute:

```
cd /opt/caro
docker run --rm --network caro-staging_internal -e CARO_BASE=http://api:8000 \
  -v /opt/caro/perf:/perf:ro grafana/k6 run /perf/search.js
```

Worked when its two thresholds are ticked. Send back the `http_req_duration`
and `http_reqs` lines: they go into [PERF](PERF.md)'s table.

## Then

Phase 4 closes when the three answers are served from the cache more than
80% of the time (Cloudflare's **Caching → Overview**, filtered to the three
paths), the target holds on the server, and no kept answer carries a digest
other than the corpus being served — the site check's `edge` line, read
after each release. Send back what steps 1 to 4 printed; a session records
them in the phase's decision entry.
