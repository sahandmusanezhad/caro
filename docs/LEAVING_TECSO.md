# Leaving Tecso-Dev/caro — caro on the owner's account alone

The owner chose on 2026-11-21 that caro is on the owner's account alone:
nothing is pushed to `Tecso-Dev/caro` (D119), its open issues move to this
repository's Issues, the site's contact page sends people here, and
`Tecso-Dev/caro` is deleted. A session can take none of the steps in the
owner's accounts: its access reaches this repository alone, and deleting a
repository takes an admin's rights on it and the owner's own sign-in. These
are the owner's steps, each with what to see when it worked.

They run on your own Mac, where `gh` is signed in as you, in a terminal, in
this repository's checkout. Paste one block at a time, and read what it
prints before the next. No step asks for a token or prints one.

## 1. Issues on here

In https://github.com/sahandmusanezhad/caro/settings, **General →
Features**, tick **Issues**. Worked when this prints `true`:

```
gh repo view sahandmusanezhad/caro --json hasIssuesEnabled -q .hasIssuesEnabled
```

## 2. This repository is not deleted with it

Deleting a private repository deletes its forks. These two lines read and
change nothing:

```
gh repo view Tecso-Dev/caro --json visibility,parent -q '"Tecso-Dev/caro: \(.visibility), fork of \(.parent.owner.login // "-")/\(.parent.name // "-")"'
gh repo view sahandmusanezhad/caro --json visibility,parent -q '"sahandmusanezhad/caro: \(.visibility), fork of \(.parent.owner.login // "-")/\(.parent.name // "-")"'
```

Go on only if the first says `PUBLIC`, or the second does not say `fork of
Tecso-Dev/caro`. D68 found `Tecso-Dev/caro` to be the fork: a fork starts
with Issues off, and its Issues had been turned on.

## 3. A full copy

Every branch and tag, and every issue and pull request with its comments,
in a new folder. Nothing is pushed anywhere:

```
mkdir -p ~/caro-tecso-backup && cd ~/caro-tecso-backup && \
git clone -q --mirror https://github.com/Tecso-Dev/caro.git caro.git && \
gh issue list -R Tecso-Dev/caro --state all --limit 1000 --json number,title,body,state,labels,author,createdAt,closedAt,comments > issues.json && \
gh pr list -R Tecso-Dev/caro --state all --limit 1000 --json number,title,body,state,headRefName,author,createdAt,closedAt,comments > prs.json && \
git -C caro.git branch --list && ls -l issues.json prs.json; cd -
```

Worked when it lists the branches and the two files, neither empty. On
2026-11-20 it had two branches this repository does not, besides `main`:
`docs/rearchitecture-plan` and one a session made; the copy keeps both.

## 4. Its open issues, made here

The first line prints what it would make and makes nothing; the second
makes it:

```
python3 scripts/move_issues.py ~/caro-tecso-backup/issues.json --dry-run
python3 scripts/move_issues.py ~/caro-tecso-backup/issues.json
```

Each open issue is made here with its title, where it came from, who opened
it and when, its labels there, its body and its comments in order. A
mention is written as code, so that no one is notified again. Closed issues
stay in the copy. What it made is written to
`~/caro-tecso-backup/moved.tsv`: run again, it makes only what is not there,
so nothing is made twice. It refuses a target in `Tecso-Dev`.

Worked when the second ends with a line `Tecso-Dev/caro#N` and its address
here for each open issue.

## 5. Tecso-Dev/caro deleted

Only after step 4. In the browser, as an admin of it:
https://github.com/Tecso-Dev/caro/settings → **Danger Zone** → **Delete
this repository** → type `Tecso-Dev/caro`. Its deploy key goes with it. The
secret that held the key's other half stays here until it is taken out:

```
gh secret delete TECSO_DEPLOY_KEY -R sahandmusanezhad/caro
```

Worked when `gh repo view Tecso-Dev/caro` says it cannot be found, and
`gh secret list -R sahandmusanezhad/caro` no longer names `TECSO_DEPLOY_KEY`.

## What changes with it

- **The site on Vercel** is built from `Tecso-Dev/caro`, in a project of
  another account (D78), and runs `b9f9090`. Nothing can build it again
  once the repository is gone; whether the project keeps serving what it
  built is its holder's to see. Open https://caro-rho.vercel.app after
  step 5. The site's next home is the server
  ([PHASE1_SETUP](PHASE1_SETUP.md)).
- **Its contact page**, at `b9f9090`, sends people to `Tecso-Dev/caro`'s
  Issues, which go with it. `main` sends them here, which a site shows once
  it runs `main`.
- **Sobhan** followed the phases in its issues; the open ones are here
  after step 4.

## Then

Send back what step 4 printed — the `Tecso-Dev/caro#N` lines — and what
step 5's two checks printed. With them a session moves the issue numbers
the documents cite to their new ones here, and records the move and the
delete in a decision entry.
