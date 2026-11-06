# Phase 6 — the site in its own image, Vercel retired: the owner's steps

Phase 6 of the plan ([REARCHITECTURE](REARCHITECTURE.md); Tecso-Dev/caro
issue 8) takes the site off Vercel. What a session could build is built:

- **The site's own image** (`webapp/web/Dockerfile`, built in phase 1): the
  standalone server Next.js writes, beside the API behind the server's one
  nginx (`compose.edge.yml`, `deploy/nginx/caro.conf`), through Cloudflare,
  `/api/*` to the API's container.
- **Both images walked in a browser before they are pushed**
  (`.github/workflows/images.yml`): every key route at a desk and on a
  phone, light and dark, and the seller listings from a code to a number
  shown. It is the check CI's `e2e` job makes on the tree
  (`webapp/web/e2e/routes.mjs`), made on the images the server pulls.
- **The read after each deploy holds the environments to Cloudflare**
  (`scripts/site_check.py --cloudflare`): staging, and production once
  `CARO_PRODUCTION_URL` names it, answer through Cloudflare, with no part
  served by Vercel, or the images workflow's `reached` job fails.
- **The repository without Vercel**, on the branch `phase6-vercel-gone`, a
  pull request kept as a draft: `vercel.json` out, the site check and the
  reach probe at `caro.noxioai.com`, and the comments and the webapp README
  that named Vercel naming the server. It merges after step 3 and not
  before: until then `main` of `Tecso-Dev/caro` deploys to Vercel from
  `vercel.json`, and putting the CNAME back undoes the switch.

What is left is in the owner's accounts and the Vercel project's. No step
asks for a key to be written into this repository or pasted into a
conversation.

## 1. The site served from the server

[PHASE1_SETUP](PHASE1_SETUP.md) to its end: the server, staging, the first
release, and step 8, the switch, `caro.noxioai.com` an A record to the
server, proxied. Worked when, from any machine:

```
python3 scripts/site_check.py --site https://caro.noxioai.com --cloudflare; echo "exit $?"
```

prints its lines, `headers  server: cloudflare  cf-ray: yes` among them,
and then `exit 0`.

## 2. A week on the server

The switch stays undoable while the Vercel project exists: the CNAME put
back, and Vercel serves `main` of `Tecso-Dev/caro` again. Keep it so for a
week, as PHASE1_SETUP says, and read the line above once a day.

Worked when seven days' reads each ended `exit 0`.

## 3. The Vercel project retired

The project is in another account than the owner's (D78): its holder
deletes it. In Vercel, open the project and its **Settings**; **Delete
Project** is at the foot of the general settings. The Vercel app installed
on GitHub for `Tecso-Dev/caro` deploys nothing without a project; its
holder may remove it under the organization's **Settings → GitHub Apps**.

Worked when, from any machine:

```
curl -sI https://caro-rho.vercel.app | grep -iE '^HTTP|x-vercel-error'
python3 scripts/site_check.py --site https://caro.noxioai.com --cloudflare; echo "exit $?"
```

the first prints a 404 and `x-vercel-error: DEPLOYMENT_NOT_FOUND`, and the
second still ends `exit 0`.

## 4. The repository's side

Tell a session that step 3 is done. It brings `phase6-vercel-gone` up to
`main`, marks its pull request ready, and merges it once CI is green, with
the README's and the roadmap's lines that say where the site is served.

## Then

Phase 6 closes when the site answers from the server through Cloudflare
(step 1's line), the suites are green against it (the images workflow's
walk and its `reached` job, on every merge), and the decision entry records
that the site left Vercel. Send back what steps 1 and 3 printed; a session
records them in that entry.
