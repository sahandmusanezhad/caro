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

Step 2's settings are `deploy/set-env.sh`'s, and steps 3 and 4 are one run
of `scripts/grafana_setup.py`. Each step says what to run, and then the
same by hand.

## 1. A Grafana Cloud stack

On grafana.com, a free account and a stack. In the stack's **Prometheus**
card, under **Details**, there are three things:

- the **Remote Write Endpoint**, ending `/api/prom/push`;
- the **Username / Instance ID**, a number;
- the way to a token: an access policy whose only scope is
  **metrics:write**, and a token made under it.

Then, in the stack's Grafana, a service account for steps 3 and 4:
**Administration → Users and access → Service accounts → Add service
account**, role **Admin**, then **Add service account token**. Delete it
when the steps are done.

By hand, step 4 needs instead a second policy with **rules:write** alone,
and a token under it.

## 2. The collector on the server

On the server, bring the checkout up to `main` first: the collector reads
its file from it.

```
cd /opt/caro && git pull --ff-only
```

Then:

```
bash /opt/caro/deploy/set-env.sh staging COMPOSE_PROFILES=observe GRAFANA_CLOUD_PROM_URL GRAFANA_CLOUD_PROM_USER GRAFANA_CLOUD_TOKEN
```

It asks for the three in turn, none shown: the Remote Write Endpoint, the
Instance ID, the metrics:write token. By hand, the same lines in
`/etc/caro/staging.env`:

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

Then do the same with `production`. To stop it again,
`bash /opt/caro/deploy/set-env.sh staging COMPOSE_PROFILES=` and
`... stop observe`: a service whose profile is off is not stopped by `up`.

## 3 and 4. The dashboard, the alerts, and where they go

On the server, where production's file holds the bot and the chat of the
server's alerts ([PHASE3_SETUP](PHASE3_SETUP.md)):

```
cd /opt/caro
read -r GRAFANA_URL && export GRAFANA_URL
read -rs GRAFANA_TOKEN && export GRAFANA_TOKEN
python3 scripts/grafana_setup.py all --env-file /etc/caro/production.env
```

The first line reads the stack's address, `https://` and the stack's name
`.grafana.net`; the second the service account's token, not shown. Then it
does, in order:
- the dashboard, on the stack's own Prometheus;
- the seven alerts, as Grafana-managed rules in the folder CARO, by
  Grafana's own conversion of `deploy/grafana/alerts.yml`. No data means
  no alert, as in Prometheus;
- the contact point `caro-telegram`, and two routes to it in front of the
  stack's own: a page within half a minute and again every four hours,
  tickets every three hours and again each day;
- a test message, sent by Grafana to the chat.

Run again, it finds the dashboard and the routes as they are and writes
neither. `status` says what the stack holds, and `--dry-run` what it
would do.

Worked when three things hold:

- it ends `the test: sent by Grafana`, and the message is in the chat;
- **Alerting → Alert rules** lists the seven in the folder CARO;
- the dashboard CARO shows staging: answers by route, the search's
  percentiles, the corpus served.

By hand, the dashboard: in Grafana, **Dashboards → New → Import**: upload
`deploy/grafana/caro.json` and choose the stack's Prometheus as its data
source.

By hand, the alerts: from any machine with `mimirtool` (Grafana's, version
2 or later), in the checkout:

```
mimirtool rules load deploy/grafana/alerts.yml \
  --address=<the Remote Write Endpoint without /api/prom/push> \
  --id=<the Instance ID> --key=<the rules:write token>
```

Rules loaded so are the stack's Prometheus's own, and send to the
Alertmanager it names. In Grafana, **Alerting → Contact points**, for that
Alertmanager, add a Telegram contact point with the bot and the chat. In
**Notification policies**, route both severities to it:

- `severity=page` at once;
- `severity=ticket` grouped, every few hours.

Worked by hand when **Alerting → Alert rules** lists the seven and the
contact point's **Test** arrives in the chat.

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
