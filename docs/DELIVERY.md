# Delivery — from a merge to the site, by itself

What happens after a pull request is merged into `main`, and the one step
in the owner's accounts that makes the site follow it with no one at a
keyboard.

## After a merge

Every merge into `main` runs two workflows, in this repository alone:

- **`ci`**: the suites, the same against Postgres, the site's typecheck,
  lint and build, and every key route in a browser.
- **`images`**:
  - both images built, the API's suites run inside its image, the two
    started together, read, and walked in a browser;
  - then both pushed to `ghcr.io/sahandmusanezhad` as `:staging`, and as
    `:production` on a release tag `v*`;
  - then two jobs, `reached` and `deliver`, below.

**Until the switch to the server, the site is Vercel's.** Vercel builds it
from `main` of `Tecso-Dev/caro`. The job `deliver` brings that `main` to
each merge, only when both workflows passed on the very commit:
1. a fast-forward, never a force (`deploy/deliver.sh`). Where that `main`
   has commits of its own, nothing is pushed, the job fails, and a person
   sorts it out;
2. it waits until the site's `/api/health` names the commit
   (`scripts/deploy_wait.py`), up to fifteen minutes;
3. it reads the site from the outside (`scripts/site_check.py`), the same
   lines `tecso-release.sh` printed.

It reaches `Tecso-Dev/caro` by a deploy key of that repository alone, kept
as this repository's secret `TECSO_DEPLOY_KEY`. Without it, the job says so
and does nothing, and the owner's `tecso-release.sh` stays the way to move
the site.

**Once the server serves the site** ([PHASE1_SETUP](PHASE1_SETUP.md)):
- the server brings each environment to its tag's image every minute
  (`deploy/pull.sh`), and nothing here reaches the server;
- with the GitHub variable `CARO_STAGING_URL` set, the job `reached` waits
  until staging runs the commit and reads it from the outside;
- production follows a release tag, `CARO_PRODUCTION_URL` the same way.

## The one step: the deploy key

On your own machine, where `gh` is signed in as you, in an empty directory:

```
ssh-keygen -t ed25519 -N "" -C caro-deliver -f caro-deliver
gh repo deploy-key add caro-deliver.pub -R Tecso-Dev/caro --allow-write --title caro-deliver
gh secret set TECSO_DEPLOY_KEY -R sahandmusanezhad/caro < caro-deliver
rm caro-deliver caro-deliver.pub
```

- The first line makes a key pair there. The private half goes into this
  repository's secret by the third line, read from the file, and is then
  deleted. It is never on the screen, in a conversation, or anywhere else.
- The key can write to `Tecso-Dev/caro` and to nothing else.
- The second line needs admin rights on `Tecso-Dev/caro`. Where `gh`
  refuses it, send `caro-deliver.pub` to whoever administers that
  repository: it is the public half, and nothing in it is secret. They add
  it under **Settings → Deploy keys → Add deploy key**, with **Allow write
  access**. You run the third and fourth lines.
- Where a rule protects that `main`, the key must be among those it lets
  through: **Settings → Rules**, the rule's **Bypass list**, **Deploy
  keys**.

Worked when, after the next merge, the images run on `main` shows the job
`deliver` green, with:
- `deliver: Tecso-Dev/caro main <before> -> <the merge>`;
- `deploy-wait: https://caro-rho.vercel.app runs <the merge>`;
- the site check's lines.

To try it at once: **Actions → images**, the latest run on `main`,
**Re-run all jobs**.

**When it fails:**
- **The wait shows `(no build)` until it gives up.** Vercel did not give
  the API the commit it deployed. In the Vercel project, **Settings →
  Environment Variables**, **Automatically expose System Environment
  Variables** must be on. It is on unless someone turned it off, and the
  project is its holder's to change.
- **`deliver` says `has commits ... does not`.** Someone pushed to
  `Tecso-Dev/caro`'s `main` by hand. Nothing was pushed over it.

## When Vercel is retired

[PHASE6_SETUP](PHASE6_SETUP.md)'s step 4 takes the job `deliver` out with
the rest of Vercel's side. The deploy key is then removed from
`Tecso-Dev/caro`'s **Deploy keys**, and the secret from this repository's
**Settings → Secrets and variables → Actions**.
