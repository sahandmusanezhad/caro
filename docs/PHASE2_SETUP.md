# Phase 2 — the seller listings switched on, the owner's steps

Phase 2 of the plan ([REARCHITECTURE](REARCHITECTURE.md); Tecso-Dev/caro
issue 5) is the data layer and the seller listings. What a session could
build is built:

- **The read model.** The catalog: the published runs in Postgres, the API
  serving from it. Phase 1's server loads it from the image at every deploy
  (catalog-load) and serves from it (`compose.vps.yml`).
- **The driver.** `psycopg` in `webapp/requirements.txt`.
- **The store and the listings.** The seller listings' store, login,
  listings, review and pages, built since 2026-10-30
  ([SELLER_LISTINGS](SELLER_LISTINGS.md)), with the store in each
  environment's own Postgres, switched on by its env file.
- **The SMS.** Kavenegar behind the login's provider interface
  (`webapp/api/sms.py`).
- **The bound.** 50 MB for a published corpus, in the data contract and in
  promotion.

What is left needs an SMS account and the server of phase 1. The steps are
below, staging first. No step asks for a key to be written into this
repository or pasted into a conversation: a key is typed into the server's
env file, and nowhere else.

## 1. An SMS account

Kavenegar is the provider the plan proposes and the one built; another needs
a session to build it behind the same interface. At
[kavenegar.com](https://kavenegar.com):

1. Make an account, and add credit.
2. In the panel, copy the account's **API key**. It stays in the panel and in
   the server's env file.
3. Under the one-time-code templates, make a template named `caro-login`,
   with the text `کد ورود کارو: %token`, and wait until Kavenegar approves it.
   A template is the route Kavenegar keeps for one-time codes. Without one,
   the code goes as an ordinary message from a line of the account
   (`CARO_SMS_KAVENEGAR_SENDER`).

## 2. Staging, with your own number

On the server, add to `/etc/caro/staging.env` (`nano`):

```
CARO_SELLER_STORE=on
CARO_STORE_SECRET=<openssl rand -hex 32, run on the server>
CARO_SITE_ORIGINS=https://caro-staging.noxioai.com
CARO_SMS_PROVIDER=kavenegar
CARO_SMS_KAVENEGAR_KEY=<the API key>
CARO_SMS_KAVENEGAR_TEMPLATE=caro-login
```

The timer brings staging to it within a minute. Then, in GitHub, open
**Settings → Secrets and variables → Actions → Variables** and add
`NEXT_PUBLIC_SELLER_LISTINGS` = `on`. The site's next image draws the links
to the seller listings; it is built on the next merge into `main`.

Worked when, on `https://caro-staging.noxioai.com`, with your own number:

1. `/login` sends a code that arrives, and logs you in.
2. `/sell` posts a car.
3. `/admin` shows it pending, and you approve it: the token (and the
   authenticator's code, where it is on -- a fresh one for each request),
   «در انتظار تأیید», «در انتظار تأیید را باز کن», «تأیید و انتشار».
4. `/listings` shows it, and «نمایش شماره» shows your number.

If the login says the code was not sent, the API wrote one line saying why,
with nothing of the key or the number in it. On the server:

```
docker logs caro-staging-api-1 2>&1 | grep kavenegar | tail -n 3
```

`(status 418)` and the like is Kavenegar's own answer, which its REST
documentation names: 418 is the account's credit, 424 a template it does not
have, 501 an account that may still send only to its owner's number. A name
such as `(TimeoutError)` or `(URLError)` is Kavenegar not reached from the
server, and one reason is Kavenegar answering only from inside Iran. Send
back the line: it holds nothing a stranger could use.

## 3. Production

The same lines in `/etc/caro/production.env`, with
`CARO_SITE_ORIGINS=https://caro.noxioai.com` and a secret of its own. Then
tag the next release (PHASE1_SETUP, step 7) so production runs the image
that draws the links.

Worked when step 2's four checks pass on `https://caro.noxioai.com`. That is
the condition phase 2 closes on.

## Then

Send back the four checks from staging and from production, with what each
printed or showed. A session records them in the phase's decision entry.
