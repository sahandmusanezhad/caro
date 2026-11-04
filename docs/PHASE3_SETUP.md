# Phase 3 — the collection worker, the owner's steps

Phase 3 of the plan ([REARCHITECTURE](REARCHITECTURE.md); Tecso-Dev/caro
issue 6) is the queue and the collection worker. What a session could
build is built:

- **The queue** (`caro/jobs.py`): jobs taken `FOR UPDATE SKIP LOCKED`, so
  two workers never take one; retried with a backoff, the error kept; a
  lock per source, so two collectors never share a domain's pause.
- **The worker** (`python -m webapp.role worker`, `webapp/worker.py`): each
  day, each run `CARO_COLLECT` names, as `scripts/first_run.py` with the
  owner's own arguments; what it printed is its transcript.
- **The bucket** (`caro/bucket.py`): a run's snapshot and transcript in
  Cloudflare R2, at `runs/<source>/<day>/attempt-<n>/`.
- **The records** (`POST /api/worker/runs`): one per run, kept in the
  environment's Postgres. Nothing personal is in one.
- **The alerts** (`alerts` in `compose.vps.yml`, `webapp/alerts.py`): a run
  not arrived by its time, a run stopped, a robots.txt that changed, a
  count far from the runs before it — to Telegram, from the server.
- **`compose.worker.yml`** and `deploy/worker.env.example`.

The worker runs on your own machine, as your runs do today. The working
agreement's rule that live requests start on your machine stands until you
choose a server in Iran for it; the same compose file runs there. No step
below sends a request to a source from anywhere else, and none asks for a
key to be written into this repository or pasted into a conversation.

## 1. The bucket

In Cloudflare's dashboard, **R2 Object Storage**:

1. **Create bucket**: `caro-runs`, location automatic.
2. **Manage API tokens → Create API token**: permission *Object Read &
   Write*, *Apply to specific buckets only*: `caro-runs`. It shows an
   access key id, a secret access key, and the account's S3 endpoint,
   `https://<account id>.r2.cloudflarestorage.com`. They are typed into the
   worker's file, step 3, and nowhere else.

## 2. The server's side

On the server, add to `/etc/caro/production.env` (`nano`):

```
CARO_WORKER_TOKEN=<openssl rand -hex 32, run on the server>
CARO_ALERT_EXPECT=khodro45@05:00
CARO_ALERT_TELEGRAM_TOKEN=<the bot's token>
CARO_ALERT_TELEGRAM_CHAT=<the chat's id>
```

The bot: in Telegram, **@BotFather → /newbot** gives its token; type it into
the file. Send the bot one message from your own account, then on the
server:

```
TOKEN=$(sed -n 's/^CARO_ALERT_TELEGRAM_TOKEN=//p' /etc/caro/production.env)
curl -s "https://api.telegram.org/bot$TOKEN/getUpdates" | grep -o '"chat":{"id":-\?[0-9]*'
```

The number is the chat's id. The timer brings production to the file within
a minute. Then:

```
cd /opt/caro
docker compose -p caro-production --env-file /etc/caro/production.env -f compose.vps.yml run --rm alerts alerts --test
```

Worked when it prints «the test message was sent» and the message arrives.

The worker is not a browser. If Cloudflare's Bot Fight Mode is on and the
worker's records are refused — its log says `the server did not take ...
(status 403)` — turn Bot Fight Mode off (PHASE0_SETUP, step 7): on the free
plan no rule can skip it.

## 3. The worker, on your machine

Copy `deploy/worker.env.example` to a file of its own, `~/.caro/worker.env`,
mode 600, and fill it there: the queue's password (`openssl rand -hex 24`);
`CARO_SELLER_SALT`, the one your runs use now, so a seller is hashed as
before; `CARO_WORKER_TOKEN`, the server's from step 2; the bucket's four
from step 1; and `CARO_WORKER_ENV_FILE`, the file's own path.

With Docker (`docker login ghcr.io` first, unless the packages were made
public in PHASE1_SETUP's step 5):

```
docker compose -p caro-worker --env-file ~/.caro/worker.env -f compose.worker.yml up -d
docker compose -p caro-worker --env-file ~/.caro/worker.env -f compose.worker.yml logs -f worker
```

Or without Docker, from your checkout, the queue in a file git ignores:

```
mkdir -p data/queue
set -a; . ~/.caro/worker.env; set +a
CARO_QUEUE_URL=sqlite:///data/queue/queue.sqlite3 python3 -m webapp.role worker
```

The worker runs each run at the time `CARO_COLLECT` names, in Tehran; a
machine asleep then runs it when it wakes, the same day, and a day it slept
through is missed, never run under the next day's date.

Worked when the first run's log ends with `collected, N listing(s)`, no alert
arrives, and the bucket holds `runs/khodro45/<day>/attempt-1/`, a
`snapshot.json` and a `transcript.txt`.

## 4. Seven days

Phase 3 closes when seven consecutive daily runs have come from the worker
with their transcripts and no manual step but promotion, and
`scripts/replicate_check.py` has compared two of them from the bucket. With
the bucket's four set in the shell from the worker's file:

```
python3 -m caro.bucket get runs/khodro45/<one day>/attempt-1/snapshot.json a.json
python3 -m caro.bucket get runs/khodro45/<the next day>/attempt-1/snapshot.json b.json
python3 scripts/replicate_check.py a.json b.json
```

## Then

Send back what step 2's test printed, the last lines of the first run's
log, and after seven days what the replicate check printed. A session
records them in the phase's decision entry. Moving the worker to a server in
Iran is your decision, since it changes the working agreement's rule; the
compose file runs there as it does here.
