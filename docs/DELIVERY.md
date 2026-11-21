# Delivery — what follows a merge, and where the work is pushed

What happens after a pull request is merged into `main`. The work is pushed
to `github.com/sahandmusanezhad/caro` alone; nothing here pushes to another
repository.

## After a merge

Every merge into `main` runs two workflows, in this repository alone:

- **`ci`**: the suites, the same against Postgres, the site's typecheck,
  lint and build, and every key route in a browser.
- **`images`**:
  - both images built, the API's suites run inside its image, the two
    started together, read from the outside, and walked in a browser;
  - then both pushed to `ghcr.io/sahandmusanezhad` as `:staging`, and as
    `:production` on a release tag `v*`;
  - then the job `reached`, below.

## Nothing pushed to Tecso-Dev/caro

The owner chose on 2026-11-21, for good, that the work is pushed to this
repository alone (D119): nothing goes to `Tecso-Dev/caro`, by a session, by a
workflow or by hand ([WORKING_AGREEMENT](WORKING_AGREEMENT.md)).

Until then its `main` was brought to the merges: by the owner, by hand,
until 2026-11-18, then by the images workflow's job `deliver`, a
fast-forward by a deploy key of that repository's, which read the site
after each (D110). The job is gone, and `deploy/deliver.sh` with it. DP46
holds that no workflow here checks out another repository, holds a key but
the token GitHub gives each run, or runs `git push`.

**The site on Vercel stays where it was left.** Vercel builds
https://caro-rho.vercel.app from `main` of `Tecso-Dev/caro`, which stays at
`b9f9090`, #42's merge, the last commit it was given, at 07:29Z on
2026-11-20; the job read it on the site a minute later (D118). A site runs `main`
again once the server serves it ([PHASE1_SETUP](PHASE1_SETUP.md),
[PHASE6_SETUP](PHASE6_SETUP.md)), where nothing is pushed either: the
server pulls the images.

## The key that is left

Nothing reads it now, but the deploy key `caro-deliver` can still write to
`Tecso-Dev/caro`, and this repository still holds its private half as the
secret `TECSO_DEPLOY_KEY`. Both go. Deleting `Tecso-Dev/caro`, which the
owner chose the same day ([LEAVING_TECSO](LEAVING_TECSO.md)), takes the key
with it, and then the first line below is all that is left. Before that,
on your own machine, where `gh` is signed in as you, paste these together:

```
gh secret delete TECSO_DEPLOY_KEY -R sahandmusanezhad/caro
for id in $(gh repo deploy-key list -R Tecso-Dev/caro --json id,title -q '.[] | select(.title == "caro-deliver") | .id'); do gh repo deploy-key delete "$id" -R Tecso-Dev/caro; done
```

- The first line takes the secret out of this repository.
- The second takes the key out of `Tecso-Dev/caro`, found by its title,
  and needs admin rights there. Without them, whoever administers that
  repository removes `caro-deliver` under **Settings → Deploy keys**.
- Neither prints a key, and neither pushes anything.

Worked when `gh secret list -R sahandmusanezhad/caro` no longer names
`TECSO_DEPLOY_KEY`, and `gh repo deploy-key list -R Tecso-Dev/caro` no
longer names `caro-deliver`.

## Once the server serves the site

[PHASE1_SETUP](PHASE1_SETUP.md):
- the server brings each environment to its tag's image every minute
  (`deploy/pull.sh`), and nothing here reaches the server;
- with the GitHub variable `CARO_STAGING_URL` set, the job `reached` waits
  until staging runs the commit and reads it from the outside;
- production follows a release tag, `CARO_PRODUCTION_URL` the same way.

## When Vercel is retired

[PHASE6_SETUP](PHASE6_SETUP.md)'s steps 3 and 4: the Vercel project
deleted by its holder, then this repository without `vercel.json`, in the
pull request #24, a draft until then.
