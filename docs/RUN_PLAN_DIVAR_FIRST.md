# The first live Divar run — plan and predictions

Written 2026-10-29, **before the run**, from what one saved page showed
(`first_run.py --page`, 2026-10-26: 24 of 24 listings read). A prediction that
turns out wrong is reported as wrong, with its number; this file is not edited
after the run, and what the run shows goes in the next D-entry
([WORKING_AGREEMENT](WORKING_AGREEMENT.md)). The run is the owner's: a session
does not start a request to a source.

The point of this run is **not volume.** It answers one question: does the
adapter, as built, do on the live site what it did on the saved page, and
what does `?page=2` do. Nothing is fitted on it, and no estimator is changed
by it (D35).

## Before

1. The review the ROADMAP names (product gaps, item 1): Divar's terms and its
   robots directives for the car category, read by the owner, and the finding
   recorded whatever it says. If the terms forbid this use, the run does not
   happen.
2. `git status` clean on `divar-page-round`; `python3 tests/run_all.py` green.
3. A salt that lives outside the repository:
   `export CARO_SELLER_SALT="$(head -c 24 /dev/urandom | base64)"`
   (nothing prints it, and nothing here stores a seller identifier; the salt is
   required because the hash helper refuses to run without one).

## The run

```
python3 scripts/first_run.py --source divar --city tehran --pages 2
```

Three requests in all: `robots.txt` (read through the gate, plain HTTP, the
adapter's honest User-Agent), `/s/tehran/car`, and `/s/tehran/car?page=2`, a
pause of two to five seconds (now and then longer) after each. No login, no
click, no contact. If a page does not answer three times running the adapter
stops and says so; **do not retry harder, change the User-Agent, or wait
less.** A block is a result and goes in the record.

## What to send back

The run's whole output (counts and short categories; no title, price or
token is in it), `ls -lR data/snapshots/`, and the output of

```
grep -rcE '09[0-9]{9}|\+98[0-9]{10}' data/snapshots/*/divar-*.json
```

which must print `0` for every file.

## Predictions

Made from one page; they are the numbers the run can contradict.

| # | prediction | what a miss means |
|---|---|---|
| R1 | robots.txt is the one of 2026-10-26 (92 bytes, four rules) and the run goes on | policy changed: the run stops by itself, and that is the result |
| R2 | page 1: 200, 24 listings read (23 to 26), none skipped | the page shape moved, or the site served another page to a script |
| R3 | `price` cross-check: `agree` on at least 85% of listings, `ld_only` the rest, no `label_wrong_*` | the unit or the label changed |
| R4 | the odometer: `agree` on at least 80%, at most one `disagree` per 24 | the card text or the unit changed |
| R5 | body condition read from the page's field on at least 90% of listings; no damage value outside the four seen (intact, some-scratches, some-paint, half-paint) | a new value: it is `unknown`, named in the report |
| R6 | make and model: 50 to 70% of listings have a model (the table is domestic only) | the mix of cars on the page differs |
| R7 | at most 4 of 24 are held back by the price floor | the number of token prices is not what one page showed |
| R8 | **`?page=2`**: either it adds new listings (the second page reads about as many as the first, with no token repeated) or the run says `stopped early: page 2 added no new listing`. Which of the two is not predicted: it has not been asked | — |
| R9 | the verdict is NOT READY (no model reaches 30 eligible listings) | cannot be a miss on this size |
| R10 | the snapshot holds one record per listing read, `integrity` is whatever `assess_integrity` says, and the grep above prints 0 | a number-like string in a snapshot is a leak: stop, tell the session, publish nothing |

## After

- Nothing in `data/snapshots/` is committed or published (it is operational,
  `.gitignore`d; DATA_CONTRACT). Promotion to `data/corpora/` is a separate
  step with its own plan, and one page of one city is too small to promote.
- The session reads the output, reports each row of the table as held or
  missed, and writes it into the next D-entry after the owner's push. What it
  shows decides the next step: widen the make/model table to what the page
  actually carries (the report counts the brand and the model), probe other
  cities and pages, or fix what the miss showed.
- ROADMAP step 4 closes when the run's inventory is read and recorded,
  published or not.
