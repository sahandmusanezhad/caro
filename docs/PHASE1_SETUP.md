# Phase 1 — the server, the owner's steps

Phase 1 of the plan ([REARCHITECTURE](REARCHITECTURE.md); Tecso-Dev/caro
issue 4) puts CARO on a server of its own: the site and the API as two
images, Postgres beside them, staging and production as two environments on
one Hetzner server, reached only through Cloudflare. What a session could
build is built:

- **The two images.** `Dockerfile` builds the API's image, one for the API
  and the workers, with a role per command (`webapp/role.py`).
  `webapp/web/Dockerfile` builds the site's.
- **On a laptop:** `compose.yml` runs the site, the API and Postgres.
- **On the server:**
  - `compose.vps.yml` is one environment;
  - `compose.edge.yml` is the server's one nginx (`deploy/nginx/caro.conf`), answering Cloudflare's addresses and no one else's;
  - `deploy/pull.sh`, run every minute by a timer, brings each environment to the image its tag names.
- **The workflow:** `.github/workflows/images.yml` builds both images on every pull request and runs the API's suites inside its image. It pushes them as `:staging` on every merge into `main` and as `:production` on every release tag.

Nothing reaches the server to deploy: the server asks. No key to it is kept
in GitHub.

What is left is done on the server and in the owner's accounts, below, in
order. Until the last step the site is served by Vercel exactly as now, and
the last step can be undone in a minute.

No step asks for a secret to be written into this repository or pasted into
a conversation. A password, a token or a certificate's key is made on the
server or typed into the service that holds it, and stays there.

## 1. A server at Hetzner

In the Hetzner Cloud console, in a project of its own:

1. **Add server.** Location Falkenstein or Nuremberg, image Ubuntu 24.04,
   type CX22 (2 vCPU, 4 GB) or larger, your SSH public key. Enable
   **Backups**: from phase 2 the database holds what sellers post.
2. **Firewall.** A firewall applied to the server:
   - inbound TCP 443 from Cloudflare's ranges only
     ([cloudflare.com/ips](https://www.cloudflare.com/ips/), IPv4 and IPv6);
   - inbound TCP 22 from your VPN's exit address only;
   - nothing else.

   Iran does not reach Hetzner (phase 0's probe), so you reach the server
   through your VPN, and visitors reach it through Cloudflare.

Worked when: `ssh root@<the server's address>` works through your VPN.

## 2. Docker, this repository, and the server's files

On the server, as root:

```
apt-get update && apt-get -y upgrade
curl -fsSL https://get.docker.com | sh
git clone https://github.com/sahandmusanezhad/caro /opt/caro
install -d -m 0700 /etc/caro /etc/caro/tls
install -d -m 0755 /etc/caro/nginx
/opt/caro/deploy/cloudflare-ips.sh
```

Worked when: the last command prints `… ranges written to /etc/caro/nginx`.

## 3. The origin certificate

In Cloudflare, for `noxioai.com`:

1. Open **SSL/TLS → Origin Server → Create Certificate**.
2. Choose RSA, with the hostnames `caro.noxioai.com` and `caro-staging.noxioai.com`, valid for 15 years.
3. On the server, paste the certificate into `/etc/caro/tls/origin.pem` and the private key into `/etc/caro/tls/origin.key`, then:

```
chmod 600 /etc/caro/tls/origin.key
```

The key is shown once, by Cloudflare, and goes nowhere but that file.
**SSL/TLS → Overview** stays **Full (strict)** (PHASE0_SETUP, step 3).

## 4. Each environment's settings

```
cp /opt/caro/deploy/env.example /etc/caro/production.env
cp /opt/caro/deploy/env.example /etc/caro/staging.env
chmod 600 /etc/caro/*.env
```

Edit each file on the server (`nano /etc/caro/staging.env`).

- **Staging:**
  - `CARO_ENV=staging`
  - `CARO_ENV_FILE=/etc/caro/staging.env`
  - both images with the tag `:staging`
- **Production:** the values the template already has.
- **Both:**
  - `POSTGRES_PASSWORD`: a value of its own for each environment, from `openssl rand -hex 24`;
  - `CARO_ADMIN_TOKEN` and `CARO_ADMIN_TOTP_SECRET`, as on Vercel today (webapp/README.md);
  - `SENTRY_DSN`, if phase 0's step 2 is done.

## 5. The images, readable by the server

The merge of this pull request runs the images workflow, which pushes
`ghcr.io/sahandmusanezhad/caro-api` and `caro-site`. On GitHub, open your
profile → **Packages**. For each of the two, open **Package settings →
Change visibility** and make it **Public**: the images hold the published
corpora and code, both public already, and nothing else.

Worked when: on the server,

```
docker pull ghcr.io/sahandmusanezhad/caro-api:staging
```

succeeds.

## 6. The edge, and staging

On the server:

```
cd /opt/caro
docker compose -p caro-edge -f compose.edge.yml up -d
cp deploy/systemd/caro-* /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now caro-pull@staging.timer caro-cloudflare-ips.timer
```

Then, in Cloudflare **DNS → Records**, add `caro-staging`:

- type A;
- the server's IPv4 address;
- **Proxied**.

Worked when, from your own machine, with no VPN:

```
python3 scripts/site_check.py --site https://caro-staging.noxioai.com
```

prints the same lines as for the site today and `cf-ray: yes`.

Then, in GitHub, open **Settings → Secrets and variables → Actions →
Variables** and add `CARO_STAGING_URL` = `https://caro-staging.noxioai.com`.
From then on every merge waits until staging runs the new commit, and reads
it from the outside (the job `reached`). If Cloudflare's Bot Fight Mode
challenges that job, turn Bot Fight Mode off (PHASE0_SETUP, step 7): on the
free plan no rule can skip it.

## 7. Production

From your own checkout, on `main` as merged:

```
git tag v1.0.0
git push https://github.com/sahandmusanezhad/caro v1.0.0
```

The images workflow tags both images `:production`. Then, on the server:

```
systemctl enable --now caro-pull@production.timer
```

Worked when, on the server, a minute later:

```
docker compose -p caro-production --env-file /etc/caro/production.env -f compose.vps.yml ps
```

shows `api` and `site` healthy.

## 8. The switch

In Cloudflare **DNS → Records**, change `caro`:

- **from:** the CNAME to Vercel;
- **to:** type A, the server's IPv4 address, **Proxied**.

The site is served from the server a minute later. Add the variable
`CARO_PRODUCTION_URL` = `https://caro.noxioai.com` in GitHub. Read it:

```
python3 scripts/site_check.py --site https://caro.noxioai.com
```

To undo it, put the CNAME back. Vercel keeps deploying `Tecso-Dev/caro`
until it is retired, which waits until the server has served for a week.

## Then

Send back what steps 1, 6, 7 and 8 printed. With them a session records the
phase in its decision entry, and the Vercel project is retired.
