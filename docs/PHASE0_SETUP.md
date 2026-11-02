# Phase 0 — the owner's steps, written down

Phase 0 of the plan ([REARCHITECTURE](REARCHITECTURE.md); Tecso-Dev/caro
issue 3) closes when the site answers at `caro.noxioai.com` through
Cloudflare, a test alert has reached Telegram, and its decision entry
exists. What a session could build is built: the reachability probe, error
reports in the API, the operator's test report, CODEOWNERS. What is left is
done in four accounts, and only the owner can do it. Each step below says
what to do, what to see when it worked, and what to send back.

No step asks for a key to be written here or in a conversation: a DSN, a
token or a password is typed into the service that holds it, and stays
there.

## 1. GitHub: `main` protected, and the two environments

`main` takes changes only by pull request, only with the three checks
green, and never by force; no approval is required, because a session
merges its own pull requests once CI is green (WORKING_AGREEMENT). From
this repository's folder, with the GitHub CLI signed in:

```
gh api -X PUT repos/sahandmusanezhad/caro/branches/main/protection --input - <<'EOF'
{"required_status_checks": {"strict": false, "contexts": ["suites", "web", "postgres"]},
 "enforce_admins": true,
 "required_pull_request_reviews": {"required_approving_review_count": 0},
 "restrictions": null,
 "allow_force_pushes": false,
 "allow_deletions": false}
EOF
gh api -X PUT repos/sahandmusanezhad/caro/environments/staging
gh api -X PUT repos/sahandmusanezhad/caro/environments/production
```

Worked when: the first command prints the protection back, with
`"enforce_admins": {"enabled": true}`, and the other two print each
environment's name. Send back: their last lines.

## 2. Sentry: the API's error reports

1. Make an account at sentry.io and a project whose platform is
   **FastAPI**. Copy its **DSN**.
2. In the Vercel project, Settings → Environment Variables, add
   `SENTRY_DSN` with that DSN, for **Production**, and redeploy.
3. Ask the API for a test report. The operator's token and the six digits
   of the authenticator are the inbox's (`/admin`):

   ```
   read -s -p "operator token: " T; echo; read -p "authenticator code: " C
   curl -s -X POST https://caro-rho.vercel.app/api/admin/report-test -H "x-admin-token: $T" -H "x-admin-code: $C"; echo; unset T C
   ```

Worked when: it prints `{"reports":"on","event_id":"…"}` and an event with
that id, «a test report, sent by the operator …», is in the project. If it
prints `{"reports":"off"}`, the DSN did not reach the deployment. Send back:
what it printed.

## 3. Cloudflare in front of `caro.noxioai.com`

`noxioai.com` is on Cloudflare's nameservers and `caro` points at Vercel,
unproxied. In the Cloudflare dashboard, for `noxioai.com`:

1. **Vercel first.** In the Vercel project, Settings → Domains,
   `caro.noxioai.com` shows *Valid Configuration*. If it does not, fix that
   before anything here: Vercel must have issued its certificate.
2. **SSL/TLS → Overview:** encryption mode **Full (strict)**.
3. **DNS → Records:** the `caro` CNAME, Proxy status **Proxied** (the
   orange cloud).
4. **Security → WAF → Managed rules:** the **Cloudflare Free Managed
   Ruleset** on.
5. **Security → WAF → Rate limiting rules**, one rule, *API*: when the URI
   path starts with `/api/`, 100 requests in 10 seconds from one address,
   then **Block** for 10 seconds. The API keeps its own limits behind it.
6. **Caching → Cache Rules**, one rule, *API is not cached*: when the URI
   path starts with `/api/`, **Bypass cache**. Phase 4 caches three of
   them, keyed by the corpus's digest; until then none is.
7. **Security → Bots → Bot Fight Mode** on. It can challenge a client that
   is not a browser; if step 4's monitors or the site check below are
   challenged, turn it off and say so -- phase 4 decides bots with what the
   traffic shows.

Worked when, from any machine:

```
curl -sI https://caro.noxioai.com/ | grep -i -E "^(server|cf-ray)"
curl -s https://caro.noxioai.com/api/health; echo
```

prints `server: cloudflare`, a `cf-ray` line, and `{"ok":true}`; and the
site check, run against the new address, prints what it prints against
Vercel, with `server: cloudflare` on its last line:

```
python3 scripts/site_check.py --site https://caro.noxioai.com
```

Send back: the three outputs. If seller listings are ever switched on,
`CARO_SITE_ORIGINS` must hold `https://caro.noxioai.com`.

## 4. UptimeRobot, alerting to Telegram

1. Make an account at uptimerobot.com. **Integrations → Telegram**: follow
   its link to UptimeRobot's bot, start it, and confirm.
2. **New monitor**, type **Keyword**: URL
   `https://caro.noxioai.com/api/health`, keyword `true`, alert when the
   keyword is **not** found; the Telegram contact attached.
3. **New monitor**, type **HTTP(s)**: URL `https://caro.noxioai.com/`; the
   Telegram contact attached.
4. Send a test: in the contact's settings **Test notification**, or pause a
   monitor and start it again.

Worked when: both monitors are *Up*, and the test reached Telegram. Send
back: that it did. UptimeRobot checks from outside Iran: it says whether
the site is up, not whether Iran reaches it -- that is the probe's.

## Then

With the four answers, a session writes phase 0's decision entry -- the
plan accepted, the agreement for two, the probe and the hosting it
decided, the four services set up -- and the issue is closed.
