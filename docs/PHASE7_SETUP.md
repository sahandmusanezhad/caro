# Phase 7 — observability, scale and D56: the owner's steps

Phase 7 of the plan ([REARCHITECTURE](REARCHITECTURE.md); Tecso-Dev/caro
issue 9) is observability, ten times the load, and D56's review. What a
session could build is built:

- **The API's own numbers** (`webapp/api/metrics.py`): `/metrics`, by route
  template. Nothing personal is in it, and only the server's collector
  reads it.
- **The collector** (`deploy/alloy/config.alloy`, the `observe` service of
  `compose.vps.yml`): Grafana Alloy reads `/metrics` every 30 s and writes
  it to Grafana Cloud. It sends metrics only, no log.
- **The SLOs and every alert** ([SLO](SLO.md)):
  - seven alerts in `deploy/grafana/alerts.yml`, each tested in CI by
    promtool;
  - the alerts the server, UptimeRobot, Sentry and CI raise, listed beside
    them.
- **The dashboard** (`deploy/grafana/caro.json`): the three SLOs against
  their targets, and the search, the faults and the collection.
- **D56, measured** ([D56_REVIEW](D56_REVIEW.md), `scripts/d56_measure.py`):
  - the stages and the hot path were measured in the sandbox;
  - the window and the disappearances wait on the owner's data.
- **Ten times the target**, a hundred users, was run in the sandbox
  ([PERF](PERF.md)).

What is left is in Grafana Cloud's dashboard, the server's env files and
the owner's machine. No step asks for a key to be written into this
repository or pasted into a conversation.

## 1. A Grafana Cloud stack

On grafana.com, a free account and a stack. In the stack's **Prometheus**
card, under **Details**, there are three things:

- the **Remote Write Endpoint**, ending `/api/prom/push`;
- the **Username / Instance ID**, a number;
- the way to a token: an access policy whose only scope is
  **metrics:write**, and a token made under it.

Make a second policy with **rules:write** alone, and a token under it, for
step 4.

## 2. The collector on the server

On the server, bring the checkout up to `main` first: the collector reads
its file from it.

```
cd /opt/caro && git pull --ff-only
```

Then in `/etc/caro/staging.env`:

```
COMPOSE_PROFILES=observe
GRAFANA_CLOUD_PROM_URL=<the Remote Write Endpoint>
GRAFANA_CLOUD_PROM_USER=<the Instance ID>
GRAFANA_CLOUD_TOKEN=<the metrics:write token>
```

The next pull, within a minute, starts `observe`.

Worked when two things hold:

- `docker compose -p caro-staging --env-file /etc/caro/staging.env -f
  compose.vps.yml ps observe` says it is running;
- in Grafana, **Explore** on the stack's Prometheus, `up{job="caro-api",
  env="staging"}` is 1.

Then do the same in `/etc/caro/production.env`. To stop it again, empty
`COMPOSE_PROFILES` and run `... stop observe`: a service whose profile is
off is not stopped by `up`.

## 3. The dashboard

In Grafana, **Dashboards → New → Import**: upload `deploy/grafana/caro.json`
and choose the stack's Prometheus as its data source.

Worked when the panels show staging: answers by route, the search's
percentiles, the corpus served.

## 4. The alerts, and where they go

From any machine with `mimirtool` (Grafana's, version 2 or later), in the
checkout:

```
mimirtool rules load deploy/grafana/alerts.yml \
  --address=<the Remote Write Endpoint without /api/prom/push> \
  --id=<the Instance ID> --key=<the rules:write token>
```

In Grafana, **Alerting → Contact points**, add a Telegram contact point:
the bot and the chat of the server's alerts ([PHASE3_SETUP](PHASE3_SETUP.md)).
In **Notification policies**, route both severities to it:

- `severity=page` at once;
- `severity=ticket` grouped, every few hours.

Worked when two things hold:

- **Alerting → Alert rules** lists the seven, CaroApiDown first;
- the contact point's **Test** arrives in the chat.

## 5. Ten times the target, on the server

As [PHASE4_SETUP](PHASE4_SETUP.md)'s step 4, with a hundred users:

```
cd /opt/caro
docker run --rm --network caro-staging_internal -e CARO_BASE=http://api:8000 -e CARO_VUS=100 \
  -v /opt/caro/perf:/perf:ro grafana/k6 run /perf/search.js
```

Worked when its two thresholds are ticked. Either way, send back the
`http_req_duration` and `http_reqs` lines: they go into PERF's table, and
they answer whether one server holds ten times the target.

## 6. D56's first two conditions

Once the worker has reported runs ([PHASE3_SETUP](PHASE3_SETUP.md)), on the
server:

```
docker compose -p caro-production --env-file /etc/caro/production.env \
  -f compose.vps.yml exec api python scripts/d56_measure.py window
```

On the owner's machine, in the checkout, where the snapshots and the
watch's observations are:

```
python3 scripts/d56_measure.py durations
```

Send back what both print.

## Then

Phase 7 closes on two things:

- **the dashboards and the SLOs are live:** steps 2 to 4, numbers arriving,
  the dashboard showing them, the alerts loaded and tried;
- **the D56 decision is written:** done on 2026-11-10. The owner kept D56
  (D107) and chose one server without Kubernetes (D108), from
  [D56_REVIEW](D56_REVIEW.md). Steps 5 and 6 are what would reopen either.
