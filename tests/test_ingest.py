"""Tests for the ingest layer.

Parsing is tested hard because a price parsed one order of magnitude wrong
poisons every downstream estimate silently — and because the network path
cannot be tested here, so the text path has to carry the confidence.

The fixtures are written the way sellers actually write: mixed digit sets,
inconsistent separators, condition buried in prose, and a title that
contradicts the body.

Run: PYTHONPATH=. python3 tests/test_ingest.py
"""

import json
import os
from datetime import date

from caro.ingest.base import MultiSourceCollector, salted_fingerprint
from caro.ingest.divar_car import (
    CarListing, DivarCarAdapter, PolitenessPolicy, SourceBlocked,
    extract_body_condition, extract_color, extract_fuel, extract_gearbox,
    extract_make_model, extract_trim, has_document_issue, parse_listing,
)
from caro.ingest.persian import (
    normalize, parse_mileage_km, parse_price, parse_year_jalali,
)
from caro.tracking import FetchStatus, Integrity

os.environ.setdefault("CARO_SELLER_SALT", "test-salt")
FAILS: list[str] = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILS.append(name)


# ---------------------------------------------------------------------------
print("\npersian normalisation")
check("persian digits", normalize("۱۳۹۹") == "1399")
check("arabic-indic digits", normalize("١٣٩٩") == "1399")
check("arabic yeh/kaf folded", normalize("كيلومتر") == "کیلومتر")
check("ZWNJ becomes a space", normalize("دوگانه‌سوز") == "دوگانه سوز")
check("whitespace collapsed", normalize("  ۲۰۶   تیپ  ۵ ") == "206 تیپ 5")


print("\nprice parsing — the field most costly to get wrong")
for text, want in [
    ("۱٬۴۸۰٬۰۰۰٬۰۰۰ تومان", 1_480_000_000),
    ("1,480,000,000", 1_480_000_000),
    ("۱ میلیارد و ۴۸۰ میلیون", 1_480_000_000),
    ("۱.۵ میلیارد تومان", 1_500_000_000),
    ("۸۵۰ میلیون", 850_000_000),
    ("قیمت: ۹۲۰,۰۰۰,۰۰۰ تومان", 920_000_000),
    ("۱۴٬۸۰۰٬۰۰۰٬۰۰۰ ریال", 1_480_000_000),      # rial → toman
]:
    got = parse_price(text)
    check(f"«{text}» → {want:,}", got == want, f"got {got!r}")

for text in ("توافقی", "قیمت توافقی است", "تماس بگیرید", ""):
    check(f"«{text}» → None (missing, not zero)", parse_price(text) is None)


print("\nmileage parsing")
for text, want in [
    ("۸۰ هزار کیلومتر", 80_000),
    ("۱۲۰,۰۰۰ کیلومتر", 120_000),
    ("کارکرد ۴۵۰۰۰", 45_000),
    ("کارکرد: 210000 کیلومتر", 210_000),
    ("صفر کیلومتر", 0),
    ("کارکرد ۸۰", 80_000),          # bare small number next to a km label
]:
    got = parse_mileage_km(text)
    check(f"«{text}» → {want:,}", got == want, f"got {got!r}")


print("\nyear parsing")
for text, want in [("مدل ۱۳۹۹", 1399), ("مدل 1398", 1398),
                   ("مدل ۲۰۱۸", 1397), ("مدل ۹۹", 1399)]:
    got = parse_year_jalali(text)
    check(f"«{text}» → {want}", got == want, f"got {got!r}")


# ---------------------------------------------------------------------------
print("\ncar fields — nothing here transfers from property listings")
check("make/model from an alias",
      extract_make_model("پژو 206 تیپ ۵ سفید") == ("Peugeot", "206"))
check("make/model from a bare model number",
      extract_make_model("فروش 405 دوگانه") == ("Peugeot", "405"))
check("saipa alias", extract_make_model("پراید 131 مدل ۹۵")[1] == "Pride")
check("unknown model returns None, not a guess",
      extract_make_model("فروش موتور سیکلت") == (None, None))
check("trim extracted", "تیپ 5" in (extract_trim("206 تیپ ۵ پانوراما") or ""))
check("gearbox: automatic", extract_gearbox("گیربکس اتوماتیک") == "automatic")
check("gearbox: manual", extract_gearbox("دنده‌ای معمولی") == "manual")
check("fuel: dual", extract_fuel("دوگانه سوز کارخانه") == "dual")
check("colour", extract_color("رنگ سفید صدفی") == "سفید")


print("\nbody condition — the field no marketplace filter exposes")
for text, want in [
    ("بدون رنگ، فول", "intact"),
    ("لکه رنگ روی درب", "minor_paint"),
    ("دور رنگ", "multi_paint"),
    ("گلگیر تعویض شده", "replaced_part"),
    ("تصادفی و شاسی خورده", "accident"),
    ("فروش فوری، تماس بگیرید", "unknown"),
]:
    got = extract_body_condition(text)
    check(f"«{text}» → {want}", got == want, f"got {got}")

check("the WORSE claim wins when title and body disagree",
      extract_body_condition("206 بدون رنگ | گلگیر تعویض شده")
      == "replaced_part")
check("an empty description is unknown, not intact",
      extract_body_condition("") == "unknown")

check("document issue detected", has_document_issue("سند در گرو بانک") is True)
check("clear document detected", has_document_issue("سند آزاد") is False)
check("silence is None, not False", has_document_issue("فروش 206") is None)


# ---------------------------------------------------------------------------
print("\nend-to-end listing parse")
L = parse_listing(
    listing_id="gYx1", url="https://divar.ir/v/gYx1",
    title="پژو ۲۰۶ تیپ ۵، مدل ۱۳۹۹، سفید",
    description="کارکرد ۸۰ هزار، بیمه تا آخر سال، بدون رنگ به‌جز گلگیر تعویض شده. "
                "سند آزاد. دوگانه‌سوز نیست. اتوماتیک.",
    price_text="۱٬۴۸۰٬۰۰۰٬۰۰۰ تومان", city="تهران",
    seller_raw="09121234567")

check("id and url kept", L.listing_id == "gYx1" and L.url.endswith("gYx1"))
check("price", L.asking_price_toman == 1_480_000_000, str(L.asking_price_toman))
check("make/model", (L.make, L.model) == ("Peugeot", "206"))
check("year", L.year_jalali == 1399, str(L.year_jalali))
check("mileage", L.mileage_km == 80_000, str(L.mileage_km))
check("gearbox", L.gearbox == "automatic", str(L.gearbox))
check("colour", L.color == "سفید")
check("condition takes the worse disclosed claim",
      L.body_condition == "replaced_part", L.body_condition)
check("documents clear", L.document_issue is False)

fo = L.to_fetch_outcome(salt="test-salt")
check("becomes a FetchOutcome the tracker accepts",
      fo.status is FetchStatus.OK and fo.listing_id == "divar:gYx1")
check("PHONE NUMBER NEVER LEAVES — only a salted hash",
      fo.seller_fingerprint is not None
      and "0912" not in (fo.seller_fingerprint or ""))
check("  and the hash is not reversible without the salt",
      fo.seller_fingerprint != salted_fingerprint("09121234567", "other-salt"))
check("  and no raw seller field exists on FetchOutcome",
      not hasattr(fo, "seller_raw") and not hasattr(fo, "phone"))


# ---------------------------------------------------------------------------
print("\nadapter behaviour — politeness is enforced, not documented")

def fixture_page(_url):
    return 200, "<html>two cars</html>"


def parse_two(_html):
    return [
        parse_listing("a1", "https://divar.ir/v/a1", "پراید ۱۳۱ مدل ۹۵",
                      "کارکرد ۲۱۰ هزار، بدون رنگ", price_text="۲۸۰ میلیون"),
        parse_listing("a2", "https://divar.ir/v/a2", "206 تیپ ۲ مدل ۱۳۹۲",
                      "دور رنگ، کارکرد ۱۸۰ هزار", price_text="۶۵۰ میلیون"),
    ]


# Divar's file as the comment in divar_car.py transcribes it, served to the
# adapters below as their robots.txt.
DIVAR_ROBOTS_2026_09_07 = """User-agent: *
Disallow: /my-divar/*
Disallow: /new
Disallow: /s/*/*?*q=*
Disallow: /adminbot
"""


def divar_robots(_url):
    return 200, DIVAR_ROBOTS_2026_09_07


slept: list[float] = []
events: list[str] = []
page_urls: list[str] = []


def _page(u):
    events.append("page")
    page_urls.append(u)
    return fixture_page(u)


def _robots(u):
    events.append("robots")
    return divar_robots(u)


def _sleep(s):
    events.append("sleep")
    slept.append(s)


ad = DivarCarAdapter(max_pages=3, page_fetcher=_page,
                     parse_page=parse_two, salt="test-salt",
                     sleeper=_sleep, robots_fetcher=_robots)
out = []
try:
    for _o in ad.fetch_all(date(2026, 9, 7)):
        out.append(_o)
except RuntimeError as e:          # a refusal here shows as missing pages
    events.append(f"raised {type(e).__name__}")
check("collects across pages", len(out) == 6, str(len(out)))
check("every outcome is OK", all(o.status is FetchStatus.OK for o in out))
_at = [i for i, e in enumerate(events) if e == "page"]
_pages_span = events[_at[0]:_at[-1] + 1] if _at else []
check("waits between pages", _pages_span.count("sleep") == 2, str(events))
check("robots.txt is read first, and a wait follows it",
      events[:3] == ["robots", "sleep", "page"], str(events))
check("  through robots_fetcher, never the browser",
      not any(u.endswith("/robots.txt") for u in page_urls), str(page_urls))
check("delays respect the floor", all(s >= PolitenessPolicy().delay_min_s
                                      for s in slept), str(slept))
check("search url is category- and city-shaped",
      ad.search_url(2).endswith("/tehran/car?page=2"), ad.search_url(2))

blocked_calls = {"n": 0}


def blocking_page(_url):
    blocked_calls["n"] += 1
    return 403, ""


ad2 = DivarCarAdapter(max_pages=10, page_fetcher=blocking_page,
                      parse_page=parse_two, sleeper=lambda s: None,
                      robots_fetcher=divar_robots)
got, raised = [], False
try:
    for o in ad2.fetch_all(date(2026, 9, 7)):
        got.append(o)
except SourceBlocked:
    raised = True

check("a 403 is UNKNOWN, never ABSENT",
      all(o.status is FetchStatus.UNKNOWN for o in got), str(got))
check("STOPS when blocked — no rotation, no retry-harder", raised)
check("  and stops promptly", blocked_calls["n"] == 3, str(blocked_calls["n"]))

timeouts = DivarCarAdapter(max_pages=10, parse_page=parse_two,
                           page_fetcher=lambda u: (_ for _ in ()).throw(
                               TimeoutError("network")),
                           sleeper=lambda s: None, robots_fetcher=divar_robots)
tgot, traised = [], False
try:
    for o in timeouts.fetch_all(date(2026, 9, 7)):
        tgot.append(o)
except SourceBlocked:
    traised = True
check("a thrown fetch is UNKNOWN too, not a crash",
      traised and all(o.status is FetchStatus.UNKNOWN for o in tgot))

ad3 = DivarCarAdapter()
try:
    list(ad3.fetch_all(date(2026, 9, 7)))
    check("refuses to run without a fetcher", False, "it ran")
except RuntimeError as e:
    check("refuses to run without a fetcher", "Refusing to guess" in str(e))


print("\ncollector merges sources without letting one poison the snapshot")


class Dead:
    name = "dead-source"

    def fetch_all(self, on):
        raise ConnectionError("down")


class Live:
    name = "live-source"

    def fetch_all(self, on):
        return [l.to_fetch_outcome("live", "test-salt") for l in parse_two("")]


snap = MultiSourceCollector([Live(), Dead()]).collect(date(2026, 9, 7))
check("live source contributes", sum(
    1 for o in snap.outcomes if o.status is FetchStatus.OK) == 2)
check("dead source contributes IGNORANCE, not absence",
      any(o.status is FetchStatus.UNKNOWN
          and "dead-source" in o.listing_id for o in snap.outcomes))
check("  so its listings are never recorded as disappeared",
      not any(o.status is FetchStatus.ABSENT for o in snap.outcomes))
check("snapshot carries an integrity verdict",
      snap.integrity in (Integrity.OK, Integrity.PARTIAL, Integrity.SUSPECT))




# ---------------------------------------------------------------------------
print("\nrobots.txt compliance — verified from the live file, enforced in code")
from caro.ingest.divar_car import (
    DIVAR_ROBOTS_CHECKED, RobotsViolation, assert_allowed,
)
check(f"the check is dated ({DIVAR_ROBOTS_CHECKED})", bool(DIVAR_ROBOTS_CHECKED))
for u in ("https://divar.ir/s/tehran/light",
          "https://divar.ir/s/tehran/light?page=4",
          "https://divar.ir/v/pzhw-206/gYx1"):
    try:
        assert_allowed(u)
        check(f"allowed: {u.split('divar.ir')[1]}", True)
    except RobotsViolation:
        check(f"allowed: {u}", False, "wrongly refused")

for u, why in (("https://divar.ir/s/tehran/light?q=206", "search urls"),
               ("https://divar.ir/s/tehran/light?page=2&q=pride", "search urls"),
               ("https://divar.ir/my-divar/bookmarks", "/my-divar"),
               ("https://divar.ir/new", "/new")):
    try:
        assert_allowed(u)
        check(f"refused ({why})", False, f"LEAKED {u}")
    except RobotsViolation:
        check(f"refused ({why})", True)

blocked_search = DivarCarAdapter(city="tehran", page_fetcher=fixture_page,
                                 parse_page=parse_two, sleeper=lambda s: None,
                                 robots_fetcher=divar_robots)
check("the adapter's own urls satisfy robots",
      blocked_search.search_url(3).endswith("?page=3"))

print("\ndivar asks robots.txt as well, and keeps the transcription beside it")
_pcalls: list[str] = []


def _counted_page(u):
    _pcalls.append(u)
    return fixture_page(u)


def _divar_run(**kw):
    """What fetch_all raised, if anything, as everything / one url / ran."""
    try:
        list(DivarCarAdapter(max_pages=2, page_fetcher=_counted_page,
                             parse_page=parse_two, sleeper=lambda s: None,
                             **kw).fetch_all(date(2026, 10, 7)))
        return "ran"
    except RobotsViolation as e:
        return "everything" if e.everything else "one url"


_how = _divar_run(robots_fetcher=lambda u: (200, "User-agent: *\nDisallow: /s/\n"))
check("a page robots.txt disallows raises before it is requested",
      _how == "one url" and _pcalls == [], f"{_how} {_pcalls}")
_pcalls.clear()
_how = _divar_run()
check("with no robots fetcher, nothing is requested at all",
      _how == "everything" and _pcalls == [], f"{_how} {_pcalls}")

from caro.ingest import divar_car as _divar_mod                      # noqa: E402
_rcalls: list[str] = []
_divar_mod.CATEGORIES["search"] = "https://divar.ir/s/{city}/light?q=206"
try:
    _t11 = DivarCarAdapter(
        category="search", sleeper=lambda s: None,
        robots_fetcher=lambda u: (_rcalls.append(u)
                                  or (200, "User-agent: *\nAllow: /\n")))
    try:
        _t11.search_url(1)
        _why = "allowed"
    except RobotsViolation as e:
        _why = str(e)
finally:
    del _divar_mod.CATEGORIES["search"]
check("a q= url is refused by the 2026-09-07 transcription, even when "
      "today's robots.txt allows everything", "search urls" in _why, _why)
check("  and refused before robots.txt is asked", _rcalls == [],
      str(_rcalls))


# ---------------------------------------------------------------------------
print("\nrobots.txt read by RFC 9309 — a matcher of our own")
from caro.ingest.divar_car import USER_AGENT                         # noqa: E402
from caro.ingest.robots import PRODUCT_TOKEN, allowed, rules_for     # noqa: E402


def robots_says(text, token, path):
    return allowed(rules_for(text, token)[0], "https://example.com" + path)


# RFC 9309 §5.1 and §5.2, and the cases of §2.2.2 and §2.2.3, transcribed by
# hand rather than fetched — the round that wrote them sent no request
# anywhere. What is asserted is the RFC's semantics; compare the example
# text with the RFC before quoting it as the RFC's.
RFC_5_1 = """User-Agent: *
Disallow: *.gif$
Disallow: /example/
Allow: /publications/

User-Agent: foobot
Disallow:/
Allow:/example/page.html
Allow:/example/allowed.gif

User-Agent: barbot
User-Agent: bazbot
Disallow: /example/page.html

User-Agent: quxbot
"""
RFC_5_2 = """User-Agent: foobot
Allow: /example/page/
Disallow: /example/page/disallowed.gif
"""

for _tok, _path, _want in [
    ("foobot", "/example/page.html", True),      # an allow inside Disallow: /
    ("foobot", "/example/allowed.gif", True),
    ("foobot", "/example/other.html", False),
    ("foobot", "/publications/a.html", False),   # the * group is not foobot's
    ("foobot", "/robots.txt", True),             # always, even under Disallow: /
    ("barbot", "/example/page.html", False),     # two tokens, one group
    ("bazbot", "/example/page.html", False),
    ("barbot", "/example/other.html", True),
    ("bazbot", "/picture.gif", True),
    ("quxbot", "/example/page.html", True),      # an empty group of its own
    ("otherbot", "/picture.gif", False),         # everyone else: the * group
    ("otherbot", "/picture.gif?size=2", True),   # $ is the end of the url
    ("otherbot", "/example/x", False),
    ("otherbot", "/publications/a.gif", True),   # the longer allow wins
    ("otherbot", "/elsewhere", True),
]:
    check(f"RFC 9309 §5.1  {_tok:<8} {_path:<22} "
          f"{'allowed' if _want else 'refused'}",
          robots_says(RFC_5_1, _tok, _path) is _want)
for _path, _want in [("/example/page/", True),
                     ("/example/page/disallowed.gif", False),
                     ("/example/page/other.gif", True)]:
    check(f"RFC 9309 §5.2  the longest match decides: {_path} "
          f"{'allowed' if _want else 'refused'}",
          robots_says(RFC_5_2, "foobot", _path) is _want)
check("an allow and a disallow of one length: allow wins",
      robots_says("User-agent: *\nDisallow: /p\nAllow: /p\n", "x", "/p"))
check("  whichever is written first",
      robots_says("User-agent: *\nAllow: /p\nDisallow: /p\n", "x", "/p"))

for _rule, _path, _want, _why in [
    ("/this/path/exactly$", "/this/path/exactly", False, "$ ends the pattern"),
    ("/this/path/exactly$", "/this/path/exactly/more", True,
     "  and nothing longer matches it"),
    ("/this/*/exactly", "/this/a/b/exactly", False, "* runs across slashes"),
    ("/path/file-with-a-%2A.html", "/path/file-with-a-*.html", False,
     "%2A matches a literal *"),
    ("/path/foo-%24", "/path/foo-$", False, "%24 matches a literal $"),
    ("/foo/bar/%E3%83%84", "/foo/bar/ツ", False,
     "non-ASCII is compared percent-encoded"),
    ("/foo/bar/ツ", "/foo/bar/%E3%83%84", False, "  from either side"),
    ("/foo/bar/baz", "/foo/bar/%62%61%7A", False,
     "an escaped unreserved octet is decoded"),
    ("/Example", "/example", True, "the match is case-sensitive"),
]:
    check(f"{_why}: Disallow {_rule} · {_path}",
          robots_says(f"User-agent: *\nDisallow: {_rule}\n", "x", _path)
          is _want)

# The matcher and assert_allowed are two readings of one text, the file
# DIVAR_ROBOTS_2026_09_07 above, and they must agree.
_divar_rules, _divar_group = rules_for(DIVAR_ROBOTS_2026_09_07)
check("divar: no group names us, so the * group is ours", _divar_group == "*")
for _u, _want in [("https://divar.ir/s/tehran/light", True),
                  ("https://divar.ir/s/tehran/light?page=4", True),
                  ("https://divar.ir/v/pzhw-206/gYx1", True),
                  ("https://divar.ir/s/tehran/light?q=206", False),
                  ("https://divar.ir/s/tehran/light?page=2&q=pride", False),
                  ("https://divar.ir/my-divar/bookmarks", False),
                  ("https://divar.ir/new", False),
                  ("https://divar.ir/adminbot", False)]:
    try:
        assert_allowed(_u)
        _static = True
    except RobotsViolation:
        _static = False
    check(f"divar 2026-09-07  {_u.split('divar.ir')[1]:<31}"
          f"{'allowed' if _want else 'refused'}, as assert_allowed says",
          allowed(_divar_rules, _u) is _want and _static is _want,
          f"matcher {allowed(_divar_rules, _u)}, assert_allowed {_static}")

# Bama's directives, as docs/NETWORK_OBSERVATION_2026-09-11.md §1 records
# them and as they were read again on 2026-10-06 (D72), with the one of the
# eleven Sitemap lines this project uses. The other ten are not rules.
BAMA_ROBOTS = """User-agent: *
Disallow: /uploads/Bamalmages/CampaignBanner/
Disallow: temp.bama.ir/robots.txt

Sitemap: https://bama.ir/sitemap/car
"""
_bama_rules, _ = rules_for(BAMA_ROBOTS)
for _u, _want, _why in [
    ("https://bama.ir/sitemap/car", True, "the sitemap"),
    ("https://bama.ir/car/pride", True, "a category page"),
    ("https://bama.ir/car/peugeot?mileage=0", True, "  with a filter"),
    ("https://bama.ir/car/detail-ffdrszax-peugeot-206ir-type5-1396", True,
     "a listing"),
    ("https://bama.ir/uploads/Bamalmages/CampaignBanner/a.jpg", False,
     "a campaign banner"),
    ("https://bama.ir/temp.bama.ir/robots.txt", True,
     "the malformed line names a host, not a path, and matches nothing"),
]:
    check(f"bama: {_why} — {'allowed' if _want else 'refused'}",
          allowed(_bama_rules, _u) is _want)

check("our product token is in the User-Agent we send (RFC 9309 §2.2.1)",
      PRODUCT_TOKEN in USER_AGENT, f"{PRODUCT_TOKEN!r} / {USER_AGENT!r}")
_G = """User-agent: *
Disallow: /

User-agent: caro-RESEARCH/0.3
Allow: /
Disallow: /private
"""
check("a group naming us is ours, and * is not",
      robots_says(_G, PRODUCT_TOKEN, "/x"))
check("  named case-insensitively, the version after the token ignored",
      rules_for(_G)[1] == PRODUCT_TOKEN, str(rules_for(_G)[1]))
check("  and its own rules still bind",
      robots_says(_G, PRODUCT_TOKEN, "/private") is False)
_TWO = "User-agent: CARO-research\nDisallow: /a\n\nUser-agent: CARO-research\nDisallow: /b\n"
check("two groups naming us are combined",
      not robots_says(_TWO, PRODUCT_TOKEN, "/a")
      and not robots_says(_TWO, PRODUCT_TOKEN, "/b"))
check("a token that only begins like ours is someone else's",
      robots_says("User-agent: CARO\nDisallow: /\n", PRODUCT_TOKEN, "/x"))
check("no group for us and no *: no rule applies",
      rules_for("User-agent: otherbot\nDisallow: /\n") == ([], None))
check("rules before the first user-agent line are ignored",
      robots_says("Disallow: /\nUser-agent: *\nDisallow: /x\n",
                  PRODUCT_TOKEN, "/y"))
check("an empty Disallow is no rule",
      robots_says("User-agent: *\nDisallow:\n", PRODUCT_TOKEN, "/y"))
check("comments, and the case of a field's name, change nothing",
      robots_says("user-AGENT: * # everyone\nDISALLOW: /x # not this\n",
                  PRODUCT_TOKEN, "/x") is False)


# ---------------------------------------------------------------------------
print("\nthe robots gate — read once, judged, recorded, asked every time")
import hashlib as _hashlib                                            # noqa: E402
from datetime import datetime as _datetime                            # noqa: E402
from caro.ingest.robots import RobotsGate, describe                   # noqa: E402


def _utc(stamp):
    """Whether `stamp` is an ISO time in UTC — False for anything else,
    so a record that lost its time fails a check instead of the suite."""
    try:
        return _datetime.fromisoformat(stamp).utcoffset().total_seconds() == 0
    except (TypeError, ValueError, AttributeError):
        return False


def _asks(gate, *urls):
    """gate.check on each url; the first refusal, or None."""
    for u in urls:
        try:
            gate.check(u)
        except RobotsViolation as e:
            return e
    return None


def gate_for(status, body="", *, fetch=True, pause=None):
    """A gate over a fake origin that answers robots.txt with (status, body),
    and the list of urls it was asked for."""
    asked = []

    def f(u):
        asked.append(u)
        if isinstance(status, Exception):
            raise status
        return status, body
    return (RobotsGate("https://bama.ir", f if fetch else None,
                       source="test", pause=pause), asked)


for _status, _body, _want, _why in [
    (200, BAMA_ROBOTS, "rules", "200, a robots.txt: its rules"),
    (200, "", "rules", "200, empty: no rule, so everything is allowed"),
    (200, "<!DOCTYPE html><html><body>لطفا صبر کنید</body></html>",
     "deny_all", "200, a page: not a policy"),
    (200, '<?xml version="1.0"?><urlset></urlset>', "deny_all",
     "200, any other markup: not a policy either"),
    (200, "User-agent: *\nDisallow: /�\n", "deny_all",
     "200, not UTF-8"),
    (404, "", "allow_all", "404: unavailable, so no rule applies"),
    (403, "", "allow_all", "403: any other 4xx, the same"),
    (429, "", "deny_all", "429: asked to slow down"),
    (500, "", "deny_all", "500: unreachable"),
    (503, "", "deny_all", "503: any 5xx, the same"),
    (0, "", "deny_all", "no response"),
    (TimeoutError("network"), "", "deny_all", "a fetcher that raises"),
    (301, "", "deny_all", "a redirect nobody followed"),
]:
    _g, _ = gate_for(_status, _body)
    check(f"robots.txt {_why} -> {_want}", _g.ensure()["verdict"] == _want,
          _g.ensure()["verdict"])
_g, _asked = gate_for(200, "", fetch=False)
check("no robots fetcher -> deny_all, and nothing was asked",
      _g.ensure()["verdict"] == "deny_all" and _asked == [])

_g, _asked = gate_for(200, BAMA_ROBOTS)
check("nothing is fetched before the gate is first asked", _asked == [])
_refused = _asks(_g, "https://bama.ir/sitemap/car", "https://bama.ir/car/pride",
                 "https://bama.ir/car/detail-ffdrszax-peugeot-206ir-type5-1396")
check("robots.txt is fetched once, however often the gate is asked",
      _asked == ["https://bama.ir/robots.txt"] and _refused is None,
      f"{_asked} {_refused}")
_rec = _g.record
_raw = BAMA_ROBOTS.encode("utf-8")
check("the record says which file and which bytes",
      _rec["url"] == "https://bama.ir/robots.txt" and _rec["http_status"] == 200
      and _rec["bytes"] == len(_raw)
      and _rec["sha256"] == _hashlib.sha256(_raw).hexdigest(), str(_rec))
check("  when, in UTC", _utc(_rec["fetched_at"]), str(_rec["fetched_at"]))
check("  and what it meant: the verdict, the group, the rule count",
      (_rec["verdict"], _rec["group"], _rec["rules"]) == ("rules", "*", 2),
      str(_rec))
check("  with the text it judged kept beside it", _g.text == BAMA_ROBOTS)
check("  on one line when printed",
      "\n" not in describe(_rec) and isinstance(_rec["sha256"], str)
      and _rec["sha256"] in describe(_rec), describe(_rec))
_g5, _ = gate_for(503)
_r5 = _g5.ensure()
check("a 5xx has no bytes to keep, and the record says so",
      _r5["http_status"] == 503 and _r5["sha256"] is None
      and _g5.text is None, str(_r5))

try:
    _g.check("https://bama.ir/uploads/Bamalmages/CampaignBanner/a.jpg")
    check("a disallowed url raises before it is requested", False, "allowed")
except RobotsViolation as e:
    check("a disallowed url raises before it is requested",
          not e.everything, str(e))
try:
    _g5.check("https://bama.ir/car/pride")
    check("deny_all raises for any url, as everything", False, "allowed")
except RobotsViolation as e:
    check("deny_all raises for any url, as everything", e.everything, str(e))
_go, _asked_o = gate_for(200, BAMA_ROBOTS)
try:
    _go.check("https://divar.ir/s/tehran/light")
    check("another origin is refused without a fetch", False, "allowed")
except RobotsViolation:
    check("another origin is refused without a fetch", _asked_o == [],
          str(_asked_o))
check("allows() gives the same answer without raising",
      _g.allows("https://bama.ir/car/pride")
      and not _g.allows("https://bama.ir/uploads/Bamalmages/CampaignBanner/a")
      and not _g5.allows("https://bama.ir/car/pride"))
_paused = []
_gp, _ = gate_for(200, BAMA_ROBOTS, pause=lambda: _paused.append(1))
_refused = _asks(_gp, "https://bama.ir/car/pride", "https://bama.ir/car/tiba")
check("reading robots.txt is a request, so one pause follows it",
      _paused == [1] and _refused is None, f"{_paused} {_refused}")


print("\nbama — parsed against the real page structure, observed 2026-09-07")
from caro.ingest.bama import (
    BamaAdapter, DiscoveryUnavailable, classify_detail_page,
    extract_listing_links, is_category_url, is_listing_url,
    listing_id_from_url, parse_detail_page, parse_sitemap, parse_slug,
)

# The sitemap lists BRAND pages, not listings. The first live run collected
# zero because the code assumed otherwise; this fixture is the real shape.
SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://bama.ir/car</loc></url>
  <url><loc>https://bama.ir/car/peugeot</loc></url>
  <url><loc>https://bama.ir/car/peugeot?mileage=0</loc></url>
  <url><loc>https://bama.ir/car/peugeot?mileage=1</loc></url>
  <url><loc>https://bama.ir/car/saipa</loc></url>
</urlset>"""

check("sitemap parses", len(parse_sitemap(SITEMAP)) == 5)
check("sitemap holds CATEGORIES, not listings",
      not any(is_listing_url(u) for u in parse_sitemap(SITEMAP)))
check("filter permutations are skipped",
      [u for u in parse_sitemap(SITEMAP) if is_category_url(u)]
      == ["https://bama.ir/car/peugeot", "https://bama.ir/car/saipa"],
      "?mileage=0/1 slice the same inventory and multiply requests")

# ---------------------------------------------------------------------------
# WHICH categories get opened — run 6's real defect
# ---------------------------------------------------------------------------
#
# `cats[:max_categories]` takes a prefix, the sitemap is ordered, so a prefix
# is the alphabet. Run 6 asked for 50 listings across the market and opened
# `audi`, `amg`, `arya`: 18 luxury EVs. Nothing was broken and every rate that
# run measured described three pages chosen by sort order.
_MANY = ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/'
         'schemas/sitemap/0.9">'
         + "".join(f"<url><loc>https://bama.ir/car/{n}</loc></url>"
                   for n in ("amg", "arya", "audi", "benz", "bmw", "dena",
                             "kia", "peugeot", "pride", "quik", "samand",
                             "tiba"))
         + "</urlset>")


def _sitemap_world(u):
    """robots.txt answered as bama answers it, and the sitemap for the rest.
    No sleeper of its own: the gate pauses after robots.txt, as after any
    request, and these adapters would otherwise sleep for real."""
    return (200, BAMA_ROBOTS) if u.endswith("/robots.txt") else (200, _MANY)


def _cats(**kw):
    ad = BamaAdapter(fetcher=_sitemap_world, max_categories=3,
                     sleeper=lambda s: None, **kw)
    return [u.rsplit("/", 1)[-1] for u in ad.discover_categories()]


check("with no seed the draw is still the sitemap prefix",
      _cats() == ["amg", "arya", "audi"],
      "unchanged on purpose — a silent change of sampling is worse than an "
      "explicit one")
check("a seed draws from the WHOLE list instead",
      _cats(sample_seed=0) != ["amg", "arya", "audi"], str(_cats(sample_seed=0)))
check("  and the same seed draws the same categories",
      _cats(sample_seed=7) == _cats(sample_seed=7),
      "a sample nobody can reproduce cannot be compared with the next run")
check("  while a different seed draws different ones",
      _cats(sample_seed=1) != _cats(sample_seed=2),
      f"{_cats(sample_seed=1)} vs {_cats(sample_seed=2)}")
check("a pinned make list is NOT shuffled — the pin is the registration",
      _cats(only_makes=("pride", "peugeot", "dena"), sample_seed=0)
      == ["dena", "peugeot", "pride"],
      "sitemap order within a deliberate slice")

_ad = BamaAdapter(fetcher=_sitemap_world, max_categories=3,
                  sample_seed=0, sleeper=lambda s: None)
_ad.discover_categories()
check("the run records which rule chose the categories",
      "seed" in _ad.stats.category_rule, _ad.stats.category_rule)
check("  and the budget, so a budget that bound is visible afterwards",
      _ad.stats.category_budget == 3 and _ad.stats.categories_found == 12,
      f"{_ad.stats.category_budget} / {_ad.stats.categories_found}")
_ad.stats.categories_tried = 3        # what discover_listings would record
check("  and the report says the budget stopped it, not a thin market",
      "category BUDGET ran out" in _ad.stats.report(),
      "run 6 could not tell the operator which of the two it had hit")
_ad.stats.category_budget = 99
check("  while a budget that did not bind says nothing",
      "category BUDGET ran out" not in _ad.stats.report())

CATEGORY = '''<a href="/car/detail-6xphr0fb-peugeot-206ir-type2-1401">a</a>
<a href="/car/detail-ffdrszax-peugeot-206ir-type5-1396">b</a>
<a href="/car/detail-ffdrszax-peugeot-206ir-type5-1396">dup</a>
<a href="/car/peugeot">not a listing</a>'''
links = extract_listing_links(CATEGORY)
check("listing links extracted and deduped", len(links) == 2, str(len(links)))
check("category links are not mistaken for listings",
      all(is_listing_url(u) for u in links))

for slug_url, want in [
    ("detail-ffdrszax-peugeot-206ir-type5-1396", ("Peugeot", "206", 1396)),
    ("detail-uznbau54-peugeot-206sd-v9-1388", ("Peugeot", "206 SD", 1388)),
    ("detail-txoqrr6c-peugeot-pars-mt-1388", ("Peugeot", "Pars", 1388)),
]:
    s = parse_slug(slug_url)
    check(f"slug → {want}",
          (s["make"], s["model"], s["year_jalali"]) == want, str(s))
check("market codes fold to one model key",
      parse_slug("detail-x-peugeot-206ir-type5-1396")["model"] == "206",
      "otherwise comparables split across spellings of one car")

# Verbatim from bama.ir/car/detail-ffdrszax-peugeot-206ir-type5-1396,
# including the related-listings block that must NOT be parsed.
REAL_DETAIL = """<div>
<p>بازگشت</p><p>پژو، 206</p><p>تیپ 5</p><p>1396</p>
<p>کارکرد 146,000 کیلومتر</p><p>1 ساعت پیش</p><p>ری، تهران</p>
<p>1,180,000,000</p><p>تومان</p>
<p>وضعیت بدنه</p><p>درب تعویض</p>
<p>رنگ بدنه</p><p>سفید</p><p>رنگ داخل</p><p>مشکی</p>
<p>گیربکس</p><p>دنده ای</p>
<p>نمایش شماره</p><p>۰۹۳۶۱۰۴۲۹XX</p>
<p>توضیحات</p><p>فروش 206 مدل 96 صندوق عقب رنگ</p>
<p>آگهی های مرتبط</p><p>290 آگهی مرتبط</p>
<p>پژو، 206</p><p>تیپ 5</p><p>1383</p><p>کارکرد 412,000 کیلومتر</p>
<p>660,000,000</p><p>تومان</p>
<p>پژو، 206</p><p>1390</p><p>کارکرد 35,000 کیلومتر</p>
<p>1,570,000,000</p><p>تومان</p></div>"""

RU = "https://bama.ir/car/detail-ffdrszax-peugeot-206ir-type5-1396"
D = parse_detail_page(RU, REAL_DETAIL)
check("price belongs to THIS car", D.asking_price_toman == 1_180_000_000, str(D.asking_price_toman))
check("  not to a related listing below it",
      D.asking_price_toman not in (660_000_000, 1_570_000_000))
check("mileage belongs to THIS car", D.mileage_km == 146_000, str(D.mileage_km))
check("  not 412,000 or 35,000 from the related block",
      D.mileage_km not in (412_000, 35_000))
check("bama's STRUCTURED body condition is used",
      D.body_condition == "replaced_part", D.body_condition)
check("colour from the labelled field", D.color == "سفید")
check("gearbox from the labelled field", D.gearbox == "manual")
check("identity survives from the url slug",
      (D.make, D.model, D.year_jalali) == ("Peugeot", "206", 1396))
check("MASKED PHONE IS NEVER READ",
      D.seller_raw is None and "0936" not in (D.description or "")
      and "۰۹۳۶" not in (D.description or ""))
check("description is the seller's text only",
      D.description == "فروش 206 مدل 96 صندوق عقب رنگ", D.description)

# ---------------------------------------------------------------------------
print("\nbama json-ld — the structured spine, observed live 2026-09-07")
from caro.ingest.bama import (                                    # noqa: E402
    ParseTrace, jsonld_car, ld_mileage_km, ld_price_toman, ld_year_jalali,
)

# The field names and nesting below are verbatim from a live detail page.
def ld_page(price="850000000", currency="IRR", km=43000, year=1398,
            body="<p>وضعیت بدنه</p><p>دور رنگ</p>", name="پراید،  131",
            url=None):
    car = {
        "@context": "https://schema.org", "@type": ["Product", "Car"],
        "name": name, "identifier": "ki4vo2q1",
        "brand": {"@type": "Brand", "name": "پراید"},
        "color": "سفید", "vehicleTransmission": "دنده ای",
        "fuelType": "بنزینی", "productionDate": year, "vehicleModelDate": year,
        "mileageFromOdometer": {"@type": "QuantitativeValue",
                                "value": km, "unitCode": "KMT"},
        "offers": {"@type": "Offer", "price": price,
                   "priceCurrency": currency},
    }
    if url:
        car["url"] = url
    # Navigation renders ABOVE the article, exactly as the live page does.
    return ("<html><body><nav><p>خودرو</p><p>قیمت روز خودرو</p>"
            "<p>1,234,567,890</p><p>تومان</p></nav>"
            '<script type="application/ld+json">' + json.dumps(car)
            + "</script><article><p>کارکرد 43,000 کیلومتر</p>"
            + body + "</article></body></html>")

LU = "https://bama.ir/car/detail-ki4vo2q1-pride-131-se-1398"

check("the Product/Car node is found", jsonld_car(ld_page()) is not None)
check("  and nested inside @graph too",
      jsonld_car('<script type="application/ld+json">'
                 '{"@context":"x","@graph":[{"@type":["Product","Car"],'
                 '"name":"y"}]}</script>') is not None,
      "pages routinely nest the payload one level down")

check("IRR is converted to toman", ld_price_toman(
    {"price": "850000000", "priceCurrency": "IRR"})[0] == 85_000_000)
check("toman is left alone", ld_price_toman(
    {"price": "850000000", "priceCurrency": "IRT"})[0] == 850_000_000)

# The single most destructive parse error in the codebase.
bad, why = ld_price_toman({"price": "850000000", "priceCurrency": "XYZ"})
check("an UNRECOGNISED currency yields None, never a coerced number",
      bad is None, "a 10x price error poisons every estimate silently")
check("  and says which currency it did not recognise", "XYZ" in (why or ""))

nego, why2 = ld_price_toman({"price": "0", "priceCurrency": "IRR"})
check("«توافقی» stays missing rather than becoming zero", nego is None)
check("  and is distinguished from an absent block",
      why2 != ld_price_toman(None)[1], f"{why2!r} vs {ld_price_toman(None)[1]!r}")

check("mileage comes from mileageFromOdometer",
      ld_mileage_km({"mileageFromOdometer":
                     {"value": 43000, "unitCode": "KMT"}}) == 43_000)
check("  and miles are converted, not assumed to be km",
      ld_mileage_km({"mileageFromOdometer":
                     {"value": 1000, "unitCode": "SMI"}}) == 1609)
check("gregorian model years convert to jalali",
      ld_year_jalali({"vehicleModelDate": 2018}) == 1397)
check("  while jalali years pass through",
      ld_year_jalali({"vehicleModelDate": 1398}) == 1398)

tr = ParseTrace()
J = parse_detail_page(LU, ld_page(), trace=tr)
check("THE NAVIGATION PRICE IS NOT THIS CAR'S PRICE",
      J.asking_price_toman == 850_000_000,
      f"got {J.asking_price_toman}; the menu above the article carries 1,234,567,890")
check("  and the run records that the structured block supplied it",
      tr.price_source == "jsonld", tr.price_source)
check("mileage from the structured block", J.mileage_km == 43_000)
check("identifier is taken from the page, not guessed from the url",
      J.listing_id == "ki4vo2q1")

check("BODY CONDITION still comes from the spec table",
      J.body_condition == "multi_paint", J.body_condition)
check("  because itemCondition:UsedCondition is true of every car on the site",
      tr.condition_source == "field", tr.condition_source)

# If the site drops its structured block, the fill rate must not stay
# healthy-looking while the quality collapses. The trace is what shows it.
tr2 = ParseTrace()
parse_detail_page(RU, REAL_DETAIL, trace=tr2)
check("a page with no structured block is recorded as text-parsed",
      tr2.used_jsonld is False and tr2.price_source == "text",
      f"{tr2.used_jsonld} / {tr2.price_source}")

tr3 = ParseTrace()
N = parse_detail_page(LU, ld_page(currency="XYZ"), trace=tr3)
check("an unparseable price is MISSING, not the navigation's number",
      N.asking_price_toman is None, str(N.asking_price_toman))
check("  which the inventory can then count and exclude from fitting",
      tr3.price_source == "none")
check("  and the reason names the currency, so a site change is visible",
      "XYZ" in (tr3.price_reason or ""), str(tr3.price_reason))

# The text path is what runs if bama ever drops its structured block, so the
# navigation hazard has to be handled there too — not only routed around.
NAV_ONLY = ("<div><p>خودرو</p><p>قیمت روز خودرو</p>"
            "<p>1,234,567,890</p><p>تومان</p>"
            "<p>کارکرد 146,000 کیلومتر</p>"
            "<p>1,180,000,000</p><p>تومان</p>"
            "<p>وضعیت بدنه</p><p>سالم</p></div>")
tr4 = ParseTrace()
V = parse_detail_page(RU, NAV_ONLY, trace=tr4)
check("with NO structured block, the text price is still the car's",
      V.asking_price_toman == 1_180_000_000,
      f"got {V.asking_price_toman}; the menu price 1,234,567,890 sits above it")
check("  because the scan is anchored at the article, not the page top",
      tr4.price_source == "text")
check("mileage is read from the anchor line itself", V.mileage_km == 146_000)

# ---------------------------------------------------------------------------
print("\nprice reconciliation — a currency LABEL can be wrong")
from caro.ingest.bama import reconcile_price                       # noqa: E402

check("two readings that agree are trusted",
      reconcile_price(850_000_000, 850_000_000) == (850_000_000, "agree"))
check("  with tolerance, since a rendered string rounds",
      reconcile_price(850_000_000, 849_999_000)[1] == "agree")

# The hazard the currency whitelist CANNOT catch: a page that declares IRR
# and publishes a toman figure. `IRR` is a code we recognise, so the guard
# stays silent while the divide-by-ten makes the price a tenth of the truth.
val, why = reconcile_price(85_000_000, 850_000_000)
check("a page declaring IRR but showing toman is caught by the cross-check",
      why == "label_wrong_ld_10x_low", why)
check("  and the DISPLAYED price wins, because that is what a buyer acts on",
      val == 850_000_000, str(val))

val2, why2 = reconcile_price(8_500_000_000, 850_000_000)
check("the opposite mislabelling is caught too",
      why2 == "label_wrong_ld_10x_high" and val2 == 850_000_000)

val3, why3 = reconcile_price(770_000_000, 850_000_000)
check("an UNEXPLAINED disagreement yields no price at all",
      val3 is None and why3 == "unexplained_disagreement",
      "a discrepancy we cannot account for is not a number to pick between")

check("one reading alone is used, and recorded as such",
      reconcile_price(850_000_000, None)[1] == "ld_only"
      and reconcile_price(None, 850_000_000)[1] == "text_only")

# ---------------------------------------------------------------------------
print("\nbama declares IRR and publishes toman — verified against 76 pages")
from caro.ingest.bama import BAMA_TO_TOMAN, _TO_TOMAN                # noqa: E402

check("read as ISO, IRR would be a tenth of a toman",
      _TO_TOMAN["IRR"] == 0.1)
check("bama's OBSERVED convention overrides its declared one",
      BAMA_TO_TOMAN["IRR"] == 1.0,
      "every page pairs priceCurrency IRR with the toman figure it displays")

# The live case, end to end: JSON-LD "850000000"/IRR beside «۸۵۰,۰۰۰,۰۰۰ تومان».
LIVE = ld_page(price="850000000", currency="IRR",
               body="<p>850,000,000</p><p>تومان</p>"
                    "<p>وضعیت بدنه</p><p>سالم</p>")
tr6 = ParseTrace()
A = parse_detail_page(LU, LIVE, trace=tr6)
check("the structured and displayed prices agree under that convention",
      A.asking_price_toman == 850_000_000 and tr6.price_agreement == "agree",
      f"{A.asking_price_toman} / {tr6.price_agreement}")
check("  and the corroborated case is distinguishable in the trace",
      tr6.price_source == "jsonld+text", tr6.price_source)

# If bama ever fixes its label, the figure would become a true rial amount and
# the displayed price would be a tenth of it. The cross-check is what notices;
# without it the override would silently start multiplying every price by ten.
FIXED_LABEL = ld_page(price="8500000000", currency="IRR",
                      body="<p>850,000,000</p><p>تومان</p>"
                           "<p>وضعیت بدنه</p><p>سالم</p>")
tr5 = ParseTrace()
M = parse_detail_page(LU, FIXED_LABEL, trace=tr5)
check("a site that starts meaning IRR literally is CAUGHT, not absorbed",
      tr5.price_agreement == "label_wrong_ld_10x_high", tr5.price_agreement)
check("  and the price shown to buyers is the one kept",
      M.asking_price_toman == 850_000_000, str(M.asking_price_toman))

# An instalment listing: the article's only numbers are a deposit and a
# monthly payment, neither of which is the car's cash price. Observed live on
# detail-fenkds6r-tiba-hatchback-ex-1394.
INSTALMENT = ld_page(price="580000000", currency="IRR",
                     body="<p>جزئیات اقساط</p><p>پیش پرداخت</p>"
                          "<p>400,000,000</p><p>تومان</p>"
                          "<p>وضعیت بدنه</p><p>سالم</p>")
tr7 = ParseTrace()
I = parse_detail_page(LU, INSTALMENT, trace=tr7)
check("an instalment listing yields NO price rather than a deposit",
      I.asking_price_toman is None, str(I.asking_price_toman))
check("  because a down payment is not comparable to a cash asking price",
      tr7.price_agreement == "unexplained_disagreement", tr7.price_agreement)

# ---------------------------------------------------------------------------
print("\nfour semantic classes, transcribed from four pages on 2026-09-10")
# ---------------------------------------------------------------------------
#
# Run 9 collected 74 listings and reported 65 appraisal-eligible. Reading the
# pages by hand showed that number meant "rows the parser could extract a
# price and a mileage for" and not "used cars with a cash asking price".
# Three of the four classes below are transcribed from the page named beside
# them; the fourth is the ordinary shape this file already exercises.
#
# What each one is FOR is the whole point. Two of them carry a perfectly
# extracted number that is not an asking price, and no check in this project
# could say so before, because every check was about the extraction.

from caro.ingest.quality import (                                    # noqa: E402
    ASSIGNMENT_CUES, classify_product, eligibility,
)

# ---- detail-x20klg7t: an assignment ---------------------------------------
# «حواله» — a claim on a car not yet built. Year 1405, 30,000,000 toman, and
# it is not a used car at any price. The word is in bama's own `name`; the
# control is detail-jy04yagr, whose `name` is «پراید،  151».
ASSIGNMENT = ld_page(price="30000000", currency="IRR", km=0, year=1405,
                     name="حواله کوییک،  دنده ای S",
                     url="https://bama.ir/car/detail-x20klg7t-quick-manuals-1405",
                     body="<p>وضعیت بدنه</p><p>سالم</p>"
                          "<p>30,000,000</p><p>تومان</p>")
A = parse_detail_page("https://bama.ir/car/detail-x20klg7t", ASSIGNMENT,
                      trace=ParseTrace())
check("«حواله» in the canonical name is read as an assignment",
      A.product_class == "assignment", A.product_class)
check("  and it says the SOURCE named it, not that we guessed",
      A.product_class_source == "canonical_name", A.product_class_source)
check("  an assignment is NOT appraisal-eligible",
      not eligibility(A)[0])
check("    and the reason names the class rather than the price",
      any("product class" in w for w in eligibility(A)[1]),
      str(eligibility(A)[1]))
check("  the price itself is left alone — it is a real number, wrongly typed",
      A.asking_price_toman == 30_000_000, str(A.asking_price_toman))
check("  and the canonical url is carried, not rebuilt from the id",
      A.source_url.endswith("-quick-manuals-1405"), str(A.source_url))

# ---- detail-jy04yagr: a financing total ------------------------------------
# The corpus MAXIMUM of run 9, at 1.83B toman on a Pride: 600M down, a second
# instalment of 150M, then sixty months at 18M. Every quality check passed and
# all of them were right — the extraction was correct. The number is not an
# asking price.
FINANCING = ld_page(price="1830000000", currency="IRR", km=0, year=1404,
                    name="پراید،  151",
                    body="<p>وضعیت بدنه</p><p>سالم</p>"
                         "<p>1,830,000,000</p><p>تومان</p>"
                         "<p>جزئیات اقساط</p><p>پیش پرداخت</p>"
                         "<p>600,000,000</p><p>تومان</p>")
F = parse_detail_page("https://bama.ir/car/detail-jy04yagr", FINANCING,
                      trace=ParseTrace())
check("a payment schedule makes the price a financing total",
      F.price_kind == "financing_total", F.price_kind)
check("  cited to the block bama itself renders",
      F.price_kind_source == "rendered_payment_schedule", F.price_kind_source)
check("  THE PRICE STILL EXTRACTS CLEANLY — that was never the problem",
      F.asking_price_toman == 1_830_000_000, str(F.asking_price_toman))
check("  and it is refused anyway, as not a cash asking price",
      not eligibility(F)[0] and any("cash asking price" in w
                                    for w in eligibility(F)[1]),
      str(eligibility(F)[1]))
check("  the car itself is still a car",
      F.product_class == "vehicle", F.product_class)

# «قسط» alone must not do this. It appears in ordinary ad copy, and a keyword
# match would have classified honest cash listings as financing.
STRAY = ld_page(body="<p>وضعیت بدنه</p><p>سالم</p>"
                     "<p>850,000,000</p><p>تومان</p>"
                     "<p>توضیحات</p><p>قسطی معاوضه میکنم</p>")
check("a stray «قسط» in seller prose is NOT a payment schedule",
      parse_detail_page(LU, STRAY, trace=ParseTrace()).price_kind == "cash")

# ---- detail-oyx0bgr5: negotiable -------------------------------------------
# «قیمت توافقی» stands where a price would be. The parser already yielded no
# number for this page; what was missing is the difference between a seller
# who will not name one and an extraction that failed.
NEGOTIABLE = ld_page(price="0", currency="IRR", km=87000, year=1402,
                     name="کوییک،  دنده ای S",
                     body="<p>قیمت توافقی</p>"
                          "<p>وضعیت بدنه</p><p>دو لکه رنگ</p>")
N2 = parse_detail_page("https://bama.ir/car/detail-oyx0bgr5", NEGOTIABLE,
                       trace=ParseTrace())
check("«قیمت توافقی» yields NO number, as it already did",
      N2.asking_price_toman is None, str(N2.asking_price_toman))
check("  and is now distinguishable from a failed extraction",
      N2.price_kind == "negotiable", N2.price_kind)
check("  which is not eligible either, and says which of the two it is",
      not eligibility(N2)[0])

# ---- the control: an ordinary cash listing ---------------------------------
# Not transcribed from a page — this is the shape the rest of this file has
# exercised all along, and the point is that NOTHING about it changed.
C = parse_detail_page(LU, ld_page(), trace=ParseTrace())
check("an ordinary listing is a vehicle sold for cash",
      C.product_class == "vehicle" and C.price_kind == "cash",
      f"{C.product_class} / {C.price_kind}")
check("  and `cash` admits it is a default reading, not a finding",
      C.price_kind_source == "no_contrary_evidence", C.price_kind_source)
check("  it is eligible, exactly as before these two fields existed",
      eligibility(C)[0], str(eligibility(C)[1]))

# ---- and the invariant that ties them together -----------------------------
check("a class we could not determine is not a vehicle",
      classify_product("", from_canonical=True)[0] == "unknown")
# The same eligible listing, differing only in its class. Built with
# `replace` so it is the real record, not a stand-in that could drift.
from dataclasses import replace as _replace                          # noqa: E402
check("  and never decays into one",
      not eligibility(_replace(C, product_class="unknown"))[0],
      "the same row that was eligible one line above")
check("  nor does an unrecorded one",
      not eligibility(_replace(C, product_class=None))[0])
check("  and a cash price on an assignment does not rescue it",
      not eligibility(_replace(C, product_class="assignment"))[0])
check("ONE assignment cue, because one is what has been observed",
      len(ASSIGNMENT_CUES) == 1,
      "widening this list by imagination is how a parser learns to see what "
      "it was told to find")


# ---------------------------------------------------------------------------
print("\nsemantic validity — 'in range' is not 'true'")
from caro.ingest.quality import (                                    # noqa: E402
    PriceStatus, Validity, classify_mileage, classify_price_value, eligibility,
)

# Every one of these was in the 2026-09-07 corpus, and every one passes a
# 0 <= km <= 1,000,000 bound.
check("999,990 km on a 1384 pride is the placeholder, not an odometer",
      classify_mileage(999_990, 1384).status is Validity.SUSPICIOUS)
check("1 km on a 1385 pride is «ask me», typed as a digit",
      classify_mileage(1, 1385).status is Validity.SUSPICIOUS)
check("6,000 km on a 21-year-old car is ~300 km/year",
      classify_mileage(6_000, 1385).status is Validity.SUSPICIOUS)
check("  and the reason says the rate, so it can be argued with",
      "km/year" in (classify_mileage(6_000, 1385).reason or ""))
check("125 km on a 1395 tiba is caught too",
      classify_mileage(125, 1395).status is Validity.SUSPICIOUS)

check("3,100 km on a CURRENT-year car is perfectly plausible",
      classify_mileage(3_100, 1405).status is Validity.PLAUSIBLE,
      "the rate rule must not fire on cars too young to have driven far")
check("43,000 km on a 1398 car is plausible",
      classify_mileage(43_000, 1398).status is Validity.PLAUSIBLE)

check("SUSPICIOUS and IMPOSSIBLE are different states",
      classify_mileage(-5_000, 1390).status is Validity.IMPOSSIBLE
      and classify_mileage(1, 1385).status is Validity.SUSPICIOUS,
      "1 km is implausible; a negative odometer cannot be a reading at all")
check("an absent odometer is UNKNOWN, never suspicious",
      classify_mileage(None, 1390).status is Validity.UNKNOWN,
      "declining to say is a different fact from saying something untrue")
check("mileage with no year is judged on magnitude alone",
      classify_mileage(6_000, None).status is Validity.PLAUSIBLE)

check("a price below any car's floor is suspicious",
      classify_price_value(5_000_000).status is Validity.SUSPICIOUS)
check("  and a real one is not",
      classify_price_value(850_000_000).status is Validity.PLAUSIBLE)

# The whole point of the status living on the record: the appraiser filters
# on it. Before this, plausibility existed only in the report and W1 was
# still free to consume 999,990 km as a fact.
J2 = parse_detail_page(LU, ld_page(km=999_990, year=1384), trace=ParseTrace())
check("THE SUSPICIOUS ODOMETER IS FLAGGED ON THE LISTING ITSELF",
      J2.mileage_status == "suspicious", J2.mileage_status)
check("  and the value is KEPT, not deleted",
      J2.mileage_km == 999_990,
      "dropping it would erase the evidence that the source publishes "
      "placeholders at all")
ok2, why2 = eligibility(J2)
check("  and it is refused entry to the appraiser",
      not ok2 and any("mileage" in w for w in why2), str(why2))

good = parse_detail_page(LU, LIVE, trace=ParseTrace())
check("a sound listing IS appraisal-eligible", eligibility(good)[0],
      str(eligibility(good)[1]))
check("the instalment listing is not", not eligibility(I)[0])

# ---------------------------------------------------------------------------
# UNKNOWN PROVENANCE FAILS CLOSED
#
# eligibility() reads both status fields with getattr-and-default, so it
# accepts objects that never set them. It used to let those through: `None in
# UNUSABLE_PRICE` is False and the mileage branch only rejects two named
# values. Nothing exploited it — CarListing defaults price_status to "absent",
# which is already unusable — so the guarantee rested on a dataclass default
# rather than on the gate. D1's rule is why that is not good enough: a fetch
# we could not make is not an absence, and a provenance we never recorded is
# not a clean one.
#
# The three-way check is the point. It is not enough that None is refused; it
# has to be refused WITHOUT collapsing into one of the valid statuses, and a
# genuinely sound listing has to stay eligible.
from dataclasses import dataclass as _dc                            # noqa: E402


@_dc
class _Prov:
    """The appraisal-required fields, with provenance varied one at a time."""
    asking_price_toman: int = 700_000_000
    year_jalali: int = 1395
    mileage_km: int = 90_000
    model: str = "pride"
    price_status: object = PriceStatus.DISPLAY_CONFIRMED.value
    mileage_status: object = "plausible"
    product_class: str = "vehicle"
    price_kind: str = "cash"


ok_v, _ = eligibility(_Prov())
ok_neg, why_neg = eligibility(_Prov(price_status=PriceStatus.NEGOTIABLE.value))
ok_non, why_non = eligibility(_Prov(price_status=None))

check("a recorded, usable price provenance IS eligible", ok_v)
check("  a NEGOTIABLE price is not", not ok_neg and any("negotiable" in w for w in why_neg),
      str(why_neg))
check("  and an ABSENT price_status is not either",
      not eligibility(_Prov(price_status=PriceStatus.ABSENT.value))[0])
check("UNRECORDED price provenance is refused, not assumed clean",
      not ok_non, str(why_non))
check("  and it says so in its own words, not by collapsing into another status",
      any("provenance unknown" in w for w in why_non), str(why_non))
check("  which is the difference between this gate and a dataclass default",
      ok_v and not ok_non,
      "the same listing, differing only in whether provenance was recorded")

ok_ms, why_ms = eligibility(_Prov(mileage_status=None))
check("UNRECORDED mileage provenance is refused on the same grounds",
      not ok_ms and any("provenance unknown" in w for w in why_ms), str(why_ms))
check("  and a recorded suspicious reading still refuses for ITS own reason",
      any("mileage is suspicious" in w
          for w in eligibility(_Prov(mileage_status="suspicious"))[1]))

# Not changed here, and recorded rather than fixed in passing: mileage_status
# == "unknown" is CarListing's default and still passes this gate. It is
# covered in practice because APPRAISAL_REQUIRED rejects a missing mileage_km,
# so the state only arises if a reading was taken and never judged. That is a
# narrower question than the one this commit answers, and folding it in would
# make the fix hard to review.
check("KNOWN ASYMMETRY: mileage_status 'unknown' still passes, unlike an "
      "absent price_status",
      eligibility(_Prov(mileage_status="unknown"))[0],
      "recorded so it cannot change silently; see the note above")

check("price status records that the display confirmed it",
      good.price_status == PriceStatus.DISPLAY_CONFIRMED.value,
      good.price_status)
check("  and the raw values are preserved for replay",
      (good.price_raw, good.price_currency_raw) == ("850000000", "IRR"),
      f"{good.price_raw} / {good.price_currency_raw}")
check("  including the number actually shown to the buyer",
      good.price_displayed_toman == 850_000_000,
      "without it, a corrected price is indistinguishable from a raw one")

# ---------------------------------------------------------------------------
print("\nregression: the exact source quirks the live runs found")
check("saina-manuals-mtgas-1404 — SAINA IS A MODEL, NOT A MAKE",
      (parse_slug("detail-xproyaln-saina-manuals-mtgas-1404")["make"],
       parse_slug("detail-xproyaln-saina-manuals-mtgas-1404")["model"])
      == ("Saipa", "Saina"),
      "read naively this yields make='Saina', model='manuals', and the "
      "2026-09-07 run reported 31 models where there are 12")
check("  and the variant lands in trim, where the ladder can relax it",
      parse_slug("detail-xproyaln-saina-manuals-mtgas-1404")["trim"]
      == "manuals mtgas")
check("runna-plus-tu5-1403 likewise maps to its manufacturer",
      (parse_slug("detail-k7lhz5sa-runna-plus-tu5-1403")["make"],
       parse_slug("detail-k7lhz5sa-runna-plus-tu5-1403")["model"])
      == ("IKCO", "Runna"))
check("a genuine make is still read as one",
      (parse_slug("detail-ffdrszax-peugeot-206ir-type5-1396")["make"],
       parse_slug("detail-ffdrszax-peugeot-206ir-type5-1396")["model"])
      == ("Peugeot", "206"),
      "the two url shapes must not be confused in either direction")

# ---------------------------------------------------------------------------
print("\ncomparable-set variation — size is not coverage")
from caro.ingest.coverage import (                                   # noqa: E402
    MIN_ELIGIBLE, assess_model, relative_iqr, top_share,
)


def fake(year, km, price, cond="intact", seller="unknown"):
    return CarListing(
        listing_id=f"x{year}{km}{price}", url="u", title="t", description="",
        asking_price_toman=price, make="Saipa", model="Tiba", trim=None,
        year_jalali=year, mileage_km=km, gearbox="manual", fuel="petrol",
        color="سفید", body_condition=cond, document_issue=False, city="تهران",
        price_status="display_confirmed", mileage_status="plausible",
        seller_type=seller)


# Forty listings, every one the same car. Mechanically this clears the count
# gate; statistically there is nothing in it to fit.
clone = assess_model("Saipa Tiba", [fake(1399, 85_000 + i * 50,
                                         900_000_000 + i * 100_000)
                                    for i in range(40)])
check(f"{MIN_ELIGIBLE}+ listings is NOT sufficient on its own",
      clone.n_eligible >= MIN_ELIGIBLE and not clone.sufficient,
      "forty near-identical cars would fit and report a narrow interval")
check("  the degenerate year is named", any("model year" in f
                                            for f in clone.findings))
check("  and so is the flat mileage", any("mileage IQR" in f
                                          for f in clone.findings))
check("  and the single body condition", any("body condition" in f
                                             for f in clone.findings),
      "the risk layer would have nothing to discriminate on")

varied = assess_model("Saipa Tiba", [
    fake(1393 + (i % 8), 20_000 + (i % 10) * 30_000,
         600_000_000 + (i % 9) * 90_000_000,
         cond=["intact", "minor_paint", "multi_paint", "replaced_part"][i % 4])
    for i in range(40)])
check("a genuinely varied set of the same size IS sufficient",
      varied.sufficient, str(varied.findings))

thin_but_varied = assess_model("Saipa Tiba", [
    fake(1393 + i, 20_000 + i * 40_000, 600_000_000 + i * 120_000_000,
         cond=["intact", "minor_paint", "accident"][i % 3]) for i in range(9)])
check("spread without count is still not sufficient",
      not thin_but_varied.degenerate and not thin_but_varied.sufficient,
      "both gates, or neither counts")

check("relative IQR compares across price scales",
      relative_iqr([100, 100, 100, 100]) == 0.0
      and (relative_iqr([50, 100, 150, 200]) or 0) > 0.5)
check("top_share reports the dominant level",
      top_share(["a", "a", "a", "b"]) == (0.75, "a"))
check("relative IQR refuses to guess from too few points",
      relative_iqr([1, 2]) is None)

# The seller signal exists to catch one forecourt posing as a market, and it
# is inferred from the business, never from a person.
from caro.ingest.bama import detect_seller_type                      # noqa: E402
check("a dealership badge marks the listing as trade",
      detect_seller_type(["اتو شرکت", "1 سال فعالیت مداوم در باما"]) == "dealer")
check("  and union membership does too",
      detect_seller_type(["عضو رسمی اتحادیه نمایشگاه داران"]) == "dealer")
check("no badge is UNKNOWN, never asserted to be private",
      detect_seller_type(["توضیحات", "ماشین سالم"]) == "unknown",
      "small dealers post like individuals; absence of a badge proves nothing")
check("the seller signal reads no personal identifier",
      detect_seller_type(["نمایش شماره", "۰۹۱۲۳۴۵۶۷XX"]) == "unknown",
      "a phone number must never become a seller feature")

# A diagnostic that quietly becomes a feature is how a pipeline starts
# modelling itself. seller_type answers "is this one forecourt?", which is a
# question about our sampling — never about the car.
from caro.appraisal import Row                                       # noqa: E402
from caro.ingest.quality import DiagnosticLeakedIntoModel             # noqa: E402

leaked = False
try:
    Row(listing_id="r1", cluster_id="c1", first_seen_ordinal=1,
        model_key="Saipa|Tiba|EX", year_jalali=1399, mileage_km=80_000,
        asking_price_toman=900_000_000, features={"seller_type": 1.0})
except DiagnosticLeakedIntoModel:
    leaked = True
check("SELLER TYPE CANNOT BE USED AS A PREDICTOR", leaked,
      "the estimator would learn 'fair value depends on who is selling' from "
      "a correlation that is real and an inference that is not")

for f in ("mileage_status", "price_status", "price_provenance"):
    caught = False
    try:
        Row(listing_id="r", cluster_id="c", first_seen_ordinal=1,
            model_key="m", year_jalali=1399, mileage_km=1.0,
            asking_price_toman=1.0, features={f: 1.0})
    except DiagnosticLeakedIntoModel:
        caught = True
    check(f"  nor {f}", caught)

ok_row = Row(listing_id="r2", cluster_id="c2", first_seen_ordinal=1,
             model_key="Saipa|Tiba|EX", year_jalali=1399, mileage_km=80_000,
             asking_price_toman=900_000_000,
             features={"body_condition_score": 0.8})
check("a genuine vehicle feature still passes",
      ok_row.features["body_condition_score"] == 0.8,
      "the guard must not become a reason to have no features at all")

pages = {"https://bama.ir/robots.txt": (200, BAMA_ROBOTS),
         "https://bama.ir/sitemap/car": (200, SITEMAP),
         "https://bama.ir/car/peugeot": (200, CATEGORY),
         "https://bama.ir/car/saipa": (200, "")}


def bama_fetch(url):
    if url in pages:
        return pages[url]
    if "6xphr0fb" in url:
        return 404, ""
    return 200, REAL_DETAIL


collected = []
b = BamaAdapter(fetcher=bama_fetch, salt="test-salt", max_listings=10,
                sleeper=lambda s: None, on_listing=collected.append)
check("two-stage discovery reaches real listings",
      len(b.discover_listings()) == 2, str(b.discover_listings()))
bout = list(b.fetch_all(date(2026, 9, 7)))
check("a listing is collected", len(collected) == 1)
check("a 404 on a just-advertised url is a real ABSENT",
      any(o.status is FetchStatus.ABSENT for o in bout))

b2 = BamaAdapter(fetcher=lambda u: (403, ""), sleeper=lambda s: None)
try:
    b2.discover_listings()
    check("a blocked sitemap halts, with no fallback to search crawling", False)
except DiscoveryUnavailable as e:
    check("a blocked sitemap halts, with no fallback to search crawling",
          "falling back" in str(e))
    check("  and says we COULD NOT LOOK, not that bama is empty",
          "not that bama has no listings" in str(e))
check("DiscoveryUnavailable is distinguishable from a mid-run block",
      issubclass(DiscoveryUnavailable, SourceBlocked)
      and DiscoveryUnavailable is not SourceBlocked)

print("\nsoft-404: a 200 is not proof the listing is there")
for status, html, want, why in [
    (404, "", FetchStatus.ABSENT, "hard 404"),
    (200, "کارکرد 100,000 کیلومتر تومان", FetchStatus.OK, "real listing"),
    (200, "این آگهی موجود نیست", FetchStatus.ABSENT, "soft 404, stated"),
    (200, "لطفا صبر کنید", FetchStatus.UNKNOWN, "challenge page"),
    (200, "", FetchStatus.UNKNOWN, "empty body"),
    (403, "", FetchStatus.UNKNOWN, "blocked"),
    (301, "", FetchStatus.UNKNOWN, "redirect landing"),
]:
    got = classify_detail_page(status, html)
    check(f"{status} + {why} -> {want.value}", got is want, got.value)
check("a 200 with no listing markers is never ABSENT",
      classify_detail_page(200, "<html><body></body></html>")
      is not FetchStatus.ABSENT,
      "calling a partial render an absence fabricates a disappearance")

print("\ndiscovery telemetry — coverage claims need these numbers")
b3 = BamaAdapter(fetcher=bama_fetch, salt="test-salt", max_listings=10,
                 sleeper=lambda s: None)
list(b3.fetch_all(date(2026, 9, 7)))
st = b3.stats
check("sitemap urls counted", st.sitemap_urls == 5, str(st.sitemap_urls))
check("categories separated from listings", st.categories_found == 2)
check("per-category listing counts recorded",
      len(st.listings_per_category) == 2, str(st.listings_per_category))
check("a category that returned nothing is recorded as zero, not omitted",
      0 in st.listings_per_category.values())
check("raw vs unique urls both counted",
      st.listing_urls_raw >= st.listing_urls_unique)
check("detail outcomes tallied by status", bool(st.detail_status),
      str(st.detail_status))
check("the report renders", "DISCOVERY" in st.stats_report()
      if hasattr(st, "stats_report") else "DISCOVERY" in st.report())


print("\nbama asks robots.txt before every request, and stops where it says")
from urllib.parse import urlsplit as _urlsplit                        # noqa: E402


def bama_world(robots=(200, BAMA_ROBOTS)):
    """bama_fetch with robots.txt answered as given, and every url asked."""
    asked = []

    def f(u):
        asked.append(u)
        return robots if _urlsplit(u).path == "/robots.txt" else bama_fetch(u)
    return f, asked


def _robots_asks(asked):
    return sum(_urlsplit(u).path == "/robots.txt" for u in asked)


def _drain(adapter):
    """Every outcome of a run, and what stopped it: everything / one url /
    ran. Anything else is the suite's to see, and is not caught."""
    out = []
    try:
        for o in adapter.fetch_all(date(2026, 10, 7)):
            out.append(o)
        return out, "ran"
    except RobotsViolation as e:
        return out, "everything" if e.everything else "one url"


_f, _asked = bama_world()
_r1 = BamaAdapter(fetcher=_f, salt="test-salt", max_listings=10,
                  sleeper=lambda s: None)
_drain(_r1)
check("robots.txt is read once for a whole run: sitemap, categories, "
      "listings", _robots_asks(_asked) == 1 and len(_asked) == 6, str(_asked))
check("  and before anything else",
      _asked[:1] == ["https://bama.ir/robots.txt"], str(_asked[:2]))
_r2 = BamaAdapter(fetcher=_f, salt="test-salt", max_listings=10,
                  sleeper=lambda s: None)
_drain(_r2)
check("a second adapter is a second execution, and reads it again",
      _robots_asks(_asked) == 2, str(_robots_asks(_asked)))
_rep1 = _r1.stats.report()
check("DISCOVERY names the robots.txt it obeyed, and what it refused",
      bool(_r1.robots.record)
      and isinstance(_r1.robots.record["sha256"], str)
      and _r1.robots.record["sha256"] in _rep1
      and "refused by it         0 url(s)" in _rep1, _rep1[:400])

_DETAIL_B = "https://bama.ir/car/detail-ffdrszax-peugeot-206ir-type5-1396"
_f, _asked = bama_world((200, "User-agent: *\nDisallow: /car/detail-ffdrszax\n"))
_got = []
_r3 = BamaAdapter(fetcher=_f, salt="test-salt", max_listings=10,
                  sleeper=lambda s: None, on_listing=_got.append)
_out3, _ = _drain(_r3)
check("a listing robots.txt disallows is never requested",
      _DETAIL_B not in _asked, str(_asked))
check("  gets no outcome at all — not ABSENT, not UNKNOWN",
      not any("ffdrszax" in o.listing_id for o in _out3) and _got == [],
      str([o.listing_id for o in _out3]))
check("  and is counted", _r3.stats.robots_refused == 1,
      str(_r3.stats.robots_refused))
check("the listing it allows is requested as before",
      any("6xphr0fb" in u for u in _asked)
      and any(o.status is FetchStatus.ABSENT for o in _out3), str(_asked))
_f, _asked = bama_world((200, "User-agent: *\nDisallow: /car/saipa\n"))
_r4 = BamaAdapter(fetcher=_f, salt="test-salt", max_listings=10,
                  sleeper=lambda s: None)
_drain(_r4)
check("a category it disallows is not requested, not tried, and counted",
      "https://bama.ir/car/saipa" not in _asked
      and _r4.stats.robots_refused == 1 and _r4.stats.categories_tried == 1
      and "https://bama.ir/car/saipa" not in _r4.stats.listings_per_category,
      str(_asked))
_f, _asked = bama_world((503, ""))
_r5 = BamaAdapter(fetcher=_f, salt="test-salt", max_listings=10,
                  sleeper=lambda s: None)
_, _halt = _drain(_r5)
check("a robots.txt that cannot be read halts the run before its first page",
      _halt == "everything" and _asked == ["https://bama.ir/robots.txt"],
      f"{_halt} {_asked}")
_f, _asked = bama_world((200, "User-agent: CARO-research\nDisallow: /sitemap/\n"))
_r6 = BamaAdapter(fetcher=_f, salt="test-salt", max_listings=10,
                  sleeper=lambda s: None)
_, _halt = _drain(_r6)
check("a sitemap disallowed to us stops discovery: nothing to enumerate from",
      _halt == "one url" and _asked == ["https://bama.ir/robots.txt"],
      f"{_halt} {_asked}")


print("\ncross-source identity — a different problem from same-source reposts")
from caro.ingest.cross_source import (
    DEFAULT_SOURCES, CrossSourceCandidate, MatchVerdict, classify_cross_source,
    cluster_across_sources, cross_source_contradictions,
    cross_source_match_score, supply_correction,
)

check("three offer sources, each with a stated role",
      sum(1 for s in DEFAULT_SOURCES if s.contributes_offers) == 3)
check("roles are distinct",
      len({s.role for s in DEFAULT_SOURCES}) == 3)


def cand(src, lid, price, *, imgs=("i1", "i2", "i3"), color="سفید",
         km=82_000, desc="پژو 206 تیپ 5 بدون رنگ بیمه کامل"):
    return CrossSourceCandidate(
        source=src, listing_id=lid, make="Peugeot", model="206",
        trim="تیپ 5", year_jalali=1399, mileage_km=km, color=color,
        province="تهران", asking_price_toman=price, description=desc,
        image_phashes=imgs)


same_car_a = cand("bama", "b1", 1_450_000_000)
same_car_b = cand("divar", "d1", 1_420_000_000)
s, why = cross_source_match_score(same_car_a, same_car_b)
check(f"one car on two sites links (score={s:.2f})", s >= 0.80, str(why))
check("  price is NOT used as identity evidence",
      not any("price" in r for r in why),
      "across sites, price differing is expected of the SAME car")

diff_car = cand("divar", "d2", 1_430_000_000, imgs=("z9",), km=140_000)
s2, why2 = cross_source_match_score(same_car_a, diff_car)
check("different mileage vetoes", s2 == 0.0 and any("mileage" in r for r in why2))

s3, _ = cross_source_match_score(same_car_a, cand("bama", "b2", 1_400_000_000))
check("same-source pairs are refused here", s3 == 0.0)

clusters = cluster_across_sources([same_car_a, same_car_b,
                                   cand("sheypoor", "s1", 1_440_000_000)])
xs = [c for c in clusters if c.is_cross_source]
check("a cross-source cluster forms", len(xs) >= 1)
c0 = xs[0]
check("it spans more than one source", len(c0.sources) >= 2, str(c0.sources))
check("price spread is computed", c0.price_spread_toman > 0)
check("minimum ask is the lowest PUBLISHED price, and says nothing about "
      "what the seller would take",
      c0.min_ask_toman == min(c0.prices))
check("the wording is NOT «تأیید» — several sites is not corroboration",
      "تأیید" not in c0.claim_fa(), c0.claim_fa())
check("  it names the price inconsistency instead",
      "اختلاف قیمت" in c0.claim_fa(), c0.claim_fa())
check("the price gap is stated as an OBSERVATION",
      "منتشر شده" in (c0.price_gap_fa() or ""), str(c0.price_gap_fa()))
check("  and never claims the seller would accept the lowest price",
      "پذیرفته" not in (c0.price_gap_fa() or "")
      and "قبول" not in (c0.price_gap_fa() or ""),
      "a price published somewhere may be stale, channel-specific, or raised since")

print("\nthree-state matching — AMBIGUOUS is never merged")
strong = classify_cross_source(cand("bama", "b9", 1_450_000_000),
                               cand("divar", "d9", 1_420_000_000))
check("corroborated evidence -> MATCH", strong.verdict is MatchVerdict.MATCH)
check("  and may_merge is true", strong.may_merge)

one_photo = classify_cross_source(
    cand("bama", "b8", 1_450_000_000, imgs=("dealer_showroom",), desc=""),
    cand("divar", "d8", 1_420_000_000, imgs=("dealer_showroom",), desc=""))
check("a SINGLE shared photo does not merge",
      not one_photo.may_merge, one_photo.verdict.value)
check("  because dealers reuse one showroom shot across their inventory",
      one_photo.verdict in (MatchVerdict.AMBIGUOUS, MatchVerdict.NO_MATCH))

unrelated = classify_cross_source(cand("bama", "b7", 1_450_000_000),
                                  cand("divar", "d7", 1_400_000_000,
                                       imgs=("z1",), desc="ماشین دیگر", km=95_000))
check("a genuinely different car -> NO_MATCH",
      unrelated.verdict is MatchVerdict.NO_MATCH)
check("ambiguous pairs are recorded on the cluster, not discarded",
      hasattr(clusters[0], "ambiguous_with"))

sc = supply_correction(clusters)
check("supply is counted in CARS, not listings",
      sc["distinct_cars"] < sc["listings"],
      f'{sc["distinct_cars"]} cars from {sc["listings"]} listings')
check("  and the inflation is reported", sc["inflation"] > 0)
check("one car counts once toward supply", c0.counts_as_supply() == 1)

# ---------------------------------------------------------------------------
print("\nrun 3 ladder — four outcomes that must never collapse into one")
import sys as _sys
_sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from scripts.run3_matrix import (                                    # noqa: E402
    INVALID, READY, TOO_FEW, TOO_FLAT, ArmResult, compare,
)


def lst(n, *, year=lambda i: 1393 + (i % 8), km=lambda i: 20_000 + (i % 10) * 30_000,
        price=lambda i: 600_000_000 + (i % 9) * 90_000_000,
        cond=lambda i: ["intact", "minor_paint", "multi_paint", "accident"][i % 4]):
    return [CarListing(
        listing_id=f"id{i}", url=f"u{i}", title="t", description="",
        asking_price_toman=price(i), make="Saipa", model="Tiba", trim=None,
        year_jalali=year(i), mileage_km=km(i), gearbox="manual", fuel="petrol",
        color="سفید", body_condition=cond(i), document_issue=False,
        city="تهران", price_status="display_confirmed",
        mileage_status="plausible", product_class="vehicle",
        price_kind="cash") for i in range(n)]


thin = ArmResult("Saipa Tiba", "depth", lst(12), fetched=12)
check("12 eligible listings -> INSUFFICIENT_OBSERVATIONS",
      thin.outcome == TOO_FEW, thin.outcome)

flat = ArmResult("Saipa Tiba", "depth",
                 lst(40, year=lambda i: 1399, km=lambda i: 85_000 + i * 40,
                     cond=lambda i: "intact"), fetched=40)
check("40 near-identical listings -> INSUFFICIENT_VARIATION, not READY",
      flat.outcome == TOO_FLAT, flat.outcome)
check("  and NOT reported as too few — the counts were met",
      flat.eligible >= 30, str(flat.eligible))

good = ArmResult("Saipa Tiba", "variation", lst(40), fetched=40)
check("40 varied listings -> SAMPLE_SUFFICIENT", good.outcome == READY,
      f"{good.outcome} {good.cov.findings}")

# The one that matters most: a run that fetched the wrong pages says nothing
# about the market, and must not be laundered into a finding about variation.
broken = ArmResult("Saipa Tiba", "variation",
                   lst(40, year=lambda i: 1399, cond=lambda i: "intact"),
                   fetched=40, acquisition_ok=False,
                   acquisition_note="?year= did not change the feed")
check("A FAILED PRE-FLIGHT IS ITS OWN VERDICT, NOT 'NO VARIATION'",
      broken.outcome == INVALID, broken.outcome)
check("  even though the same rows would otherwise read as TOO_FLAT",
      flat.outcome == TOO_FLAT,
      "invalid acquisition is decided first, on purpose")

check("the ladder reports every stage, not just the last",
      all(k in good.line() for k in ("40", "SAMPLE_SUFFICIENT")), good.line())
check("  and its top outcome does not read as permission to serve",
      "READY" not in READY,
      "the label names a sampling result; the serving decision is D30's")

rep = compare({"depth": lst(12), "variation": lst(12)},
              fetched={"depth": 12, "variation": 12})
check("pooled verdict names which gate failed", TOO_FEW in rep)
check("  and arm overlap is measured, since identical arms compare nothing",
      "ARM INDEPENDENCE" in rep and "100% overlap" in rep,
      "both arms were given the same listing ids")

# ---------------------------------------------------------------------------
print("\nstratification — variation is not representativeness")
from caro.ingest.stratification import (                             # noqa: E402
    herfindahl, kish_effective_n, normalised_entropy, sensitivity,
    stratify, weighted_quantile,
)


def trimmed(trim, year, km, price, cond="intact"):
    return CarListing(
        listing_id=f"{trim}{year}{price}", url="u", title="t", description="",
        asking_price_toman=price, make="Saipa", model="Pride", trim=trim,
        year_jalali=year, mileage_km=km, gearbox="manual", fuel="petrol",
        color="سفید", body_condition=cond, document_issue=False, city="تهران",
        price_status="display_confirmed", mileage_status="plausible",
        product_class="vehicle", price_kind="cash")


check("HHI is 1.0 when one facet holds everything", herfindahl([1.0]) == 1.0)
check("  and 1/k when perfectly even",
      abs(herfindahl([0.25] * 4) - 0.25) < 1e-9)
check("normalised entropy is 1.0 for a flat distribution",
      abs(normalised_entropy([0.25] * 4) - 1.0) < 1e-9)
check("  and low when one facet dominates",
      normalised_entropy([0.97, 0.01, 0.01, 0.01]) < 0.25)

check("effective n equals n under equal weights",
      abs(kish_effective_n([1.0] * 20) - 20) < 1e-9)
check("  and is SMALLER under uneven weights",
      kish_effective_n([10.0] + [1.0] * 19) < 20,
      "the gap between n and n_eff is the price of an uneven design")

# 30 listings of one trim and 3 of another: varied enough to pass coverage,
# but the sample is not the market in the proportions it suggests.
skew = ([trimmed("131 se", 1390 + i % 8, 50_000 + i * 9_000,
                 500_000_000 + i * 12_000_000) for i in range(30)]
        + [trimmed("111 sx", 1395 + i, 40_000 + i * 20_000,
                   900_000_000 + i * 60_000_000) for i in range(3)])
rep = stratify(skew)["Saipa Pride"]
check("stratify counts eligible listings per trim facet",
      rep.n_eligible == 33 and len(rep.counts) == 2, str(rep.counts))
check("  and reports the dominant facet's share",
      abs(rep.top[1] / rep.n_eligible - 30 / 33) < 1e-9)
check("  HHI flags the concentration", rep.hhi > 0.8, f"{rep.hhi:.2f}")

s = sensitivity(skew)
check("the median MOVES when trims are weighted equally",
      s["equal_trim"] != s["observed"],
      f"{s['observed']} vs {s['equal_trim']}")
check("  and the span is reported as a fraction of the median",
      s["relative_span"] > 0.10, f"{s['relative_span']:.1%}")

even = [trimmed(f"t{i % 6}", 1390 + i % 8, 50_000 + i * 7_000,
                600_000_000 + (i % 9) * 15_000_000) for i in range(36)]
s2 = sensitivity(even)
check("an evenly-spread sample is INSENSITIVE to reweighting",
      s2["relative_span"] < 0.10, f"{s2['relative_span']:.1%}")
check("  which is the whole point: the span separates a robust estimate "
      "from one that rests on the sampling design",
      s2["relative_span"] < s["relative_span"])

check("weighted quantile honours the weights",
      weighted_quantile([(10, 1.0), (20, 99.0)], 0.5) == 20)
check("  and matches coverage.py's quantile convention under equal weights",
      weighted_quantile([(v, 1.0) for v in (10, 20, 30, 40)], 0.5)
      == float(sorted([10, 20, 30, 40])[int(0.5 * 3)]),
      "two quantile conventions in one codebase would eventually disagree "
      "about a price and nobody would know which was meant")

# ---------------------------------------------------------------------------
print("\nconditional scope + the three-way uncertainty split")
from caro.appraisal import (                                         # noqa: E402
    ESTIMAND, AggregateOutOfScope, MarketEstimator, SamplingSensitivity,
)
from caro.ingest.stratification import MIN_PER_TRIM, conditional_scope  # noqa: E402

fat = [trimmed(f"t{i % 4}", 1390 + i % 8, 40_000 + i * 8_000,
               500_000_000 + (i % 7) * 40_000_000) for i in range(40)]
sc = conditional_scope(fat)
check("a corpus concentrated in a few well-populated trims is IN SCOPE",
      sc.ok and sc.covered_share == 1.0, str(sc.failures))

# 40 listings spread one-per-trim: varied, eligible, and every estimate is
# extrapolated from the pool rather than supported by its own trim.
sparse = [trimmed(f"t{i}", 1390 + i % 8, 40_000 + i * 8_000,
                  500_000_000 + (i % 7) * 40_000_000) for i in range(40)]
sc2 = conditional_scope(sparse)
check("ONE LISTING PER TRIM is not in scope, however varied",
      not sc2.ok, str(sc2.covered_share))
check("  and the reason names extrapolation from the pooled distribution",
      any("extrapolation" in f for f in sc2.failures), str(sc2.failures))
check("  with the thin trims listed so they can be looked at",
      len(sc2.thin_trims) == 40)
check("passing the COUNT gate does not imply passing scope",
      len(sparse) >= 30 and not sc2.ok,
      "30 is a safety floor, not a guarantee of coverage or precision")

# The third uncertainty must not hide inside the first two (D8, extended).
ss = SamplingSensitivity(relative_span=0.137, observed=1.15e9,
                         equal_facet=1.24e9, drop_one_min=1.08e9,
                         drop_one_max=1.24e9)
check("a wide sampling span is flagged as material", ss.material)
check("  and a narrow one is not",
      not SamplingSensitivity(0.019, 5.4e8, 5.4e8, 5.3e8, 5.4e8).material)
check("  and it reads as a SAMPLING span, not a confidence band",
      "sampling span" in str(ss) and "confidence" not in str(ss),
      "no amount of extra listings collected the same way shrinks it")

me = MarketEstimator(estimator=None)
raised = False
try:
    me.aggregate(1.15e9, what="Saipa Tiba median asking price")
except AggregateOutOfScope as e:
    raised = "out of scope" in str(e)
check("A MODEL-LEVEL AGGREGATE IS REFUSED WITHOUT ITS SPAN", raised,
      "a warning beside a market median gets quoted without the warning")
check("  and the refusal states the estimand",
      "CONDITIONAL" in ESTIMAND and "not a population-weighted" in ESTIMAND)

me2 = MarketEstimator(estimator=None, sampling=ss)
val, span = me2.aggregate(1.15e9, what="Saipa Tiba median")
check("  while the same aggregate WITH a span is allowed through",
      val == 1.15e9 and span.relative_span == 0.137)
check("thresholds were not moved to rescue a model",
      MIN_PER_TRIM == 5,
      "Tiba's sensitivity is a fact to report, not a reason to change a gate")

print("\ntrim pages — the two guards the Run 5 pre-flight paid for")
from caro.ingest.bama import (                                    # noqa: E402
    ITEMLIST_CAP, TRIM_PAGE_CAP, parse_trim_page,
)


def _trim_html(slugs):
    """A trim page's shape: detail links, plus an ItemList truncated to five
    exactly as the live site truncates it."""
    ld = ('<script type="application/ld+json">{"@type":"ItemList",'
          '"itemListElement":['
          + ",".join('{"url":"https://bama.ir/car/%s"}' % s
                     for s in slugs[:ITEMLIST_CAP]) + "]}</script>")
    body = "".join('<a href="/car/%s">x</a>' % s for s in slugs)
    return ld + body


# Observed 2026-09-07: a real thin trim, nine listings.
real = [f"detail-a{i}b{i}c-tiba-sedan-sxcng-139{i}" for i in range(9)]
tp = parse_trim_page(_trim_html(real), "tiba-sedan-sxcng")
check("a trim page is counted from RENDERED links, not the ItemList",
      tp.n == 9, f"got {tp.n}; the ItemList only ever shows {ITEMLIST_CAP}")
check("  so the ItemList cap cannot become an inventory count",
      tp.n != ITEMLIST_CAP,
      "/car/pride — the whole Pride inventory — reports 5 items")
check("  and a clean page is not flagged", not tp.contaminated)

# Observed 2026-09-07: tara-v1 and renault-l90-e2 each served a generic feed,
# 32 listings, none of them the trim, the same Hyundai first in both.
feed = [f"detail-z{i}q{i}w-hyundai-santafeix45-2700cc-200{i}" for i in range(8)]
bad = parse_trim_page(_trim_html(feed), "tara-v1")
check("a generic feed served under a trim slug is CONTAMINATED",
      bad.contaminated, "tara-v1 returned 32 listings, 0 on-trim")
check("  and contributes zero observations, not 8",
      bad.n == 0,
      "those are real cars; they are not evidence about this trim")

mixed = parse_trim_page(_trim_html(real[:3] + feed[:2]), "tiba-sedan-sxcng")
check("a page with a related-listings rail is NOT contaminated",
      not mixed.contaminated and mixed.n == 3,
      "contamination is 'none on trim', not 'some off trim' — a threshold "
      "would need a rationale nobody has measured")

deep = [f"detail-c{i}d{i}e-pride-141-basic-138{i%9}" for i in range(TRIM_PAGE_CAP)]
cap = parse_trim_page(_trim_html(deep), "pride-141-basic")
check(f"a page at {TRIM_PAGE_CAP} links reports it is at the page cap",
      cap.at_page_cap, "30 means 'at least 30', never 'exactly 30'")
check("  a shorter page does not", not tp.at_page_cap)

# ---------------------------------------------------------------------------
print("\nsnapshot integrity — reserved fields that no run ever filled")
# SCOPE, stated because this check is easy to read as more than it is. It is
# pinned to the frozen Run 5 snapshot, so what it enforces is a FROZEN
# SNAPSHOT CONTRACT — "this corpus's reserved fields are filled or named" —
# and NOT universal ingestion correctness. A future collection is not covered
# by it. Registering one means writing the same check against that snapshot.
# D41's addendum. `data/snapshots/run5` carries an eleven-field record per
# listing, and COND — body condition — is the empty string on all 403 of
# them. Nothing failed: the format reserves the field, the parser reads it
# correctly, and the run simply never wrote it. 272 assertions above this
# line and not one of them asks whether a field the format reserves is ever
# non-empty on real data.
#
# So this is that question, with the gaps named. A field listed in
# KNOWN_EMPTY is one we have DECIDED about; anything else empty across a
# whole snapshot is a collection bug nobody has noticed yet. When a future
# run fills COND the assertion below fails on purpose, and the fix is to
# delete the entry — the same shape as D36's retired-claim guard, where a
# gap has to be removed deliberately rather than fading out.
KNOWN_EMPTY = {
    "DESC": "excluded on purpose — descriptions carry masked phone numbers "
            "and no eligibility or estimator rule reads them",
    "COND": "NOT on purpose. Bama publishes «وضعیت بدنه» on the detail page "
            "and Run 5 did not record it, which is why four of six ranking "
            "terms are constant on real data (D41 addendum)",
}
SNAP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "snapshots", "run5", "listings.json")
if os.path.exists(SNAP):
    from scripts.replay_run3 import (
        ANCHORED, COND, CUR, DEALER, DESC, KM, KM_LINE, PRICE, PRICE_TEXT,
        SLUG, YEAR,
    )
    NAMES = {SLUG: "SLUG", ANCHORED: "ANCHORED", DEALER: "DEALER",
             YEAR: "YEAR", KM: "KM", PRICE: "PRICE", CUR: "CUR",
             KM_LINE: "KM_LINE", PRICE_TEXT: "PRICE_TEXT", COND: "COND",
             DESC: "DESC"}
    recs = json.load(open(SNAP, encoding="utf-8"))
    empty = {NAMES[i] for i in range(len(recs[0]))
             if all(r[i] in (None, "") for r in recs)}
    check("every reserved snapshot field is either filled or a NAMED gap",
          empty == set(KNOWN_EMPTY),
          f"empty={sorted(empty)} named={sorted(KNOWN_EMPTY)} — an unnamed "
          f"one is a collection bug; a named one that filled up means the "
          f"gap closed and the entry should be deleted")
    check("  and COND is still the open one",
          "COND" in empty,
          "if this fails, Bama's condition block is being recorded now: "
          "remove COND from KNOWN_EMPTY and re-check the ranking terms")
    for name in sorted(empty):
        print(f"      {name}: {KNOWN_EMPTY.get(name, 'UNEXPLAINED')}")
else:
    print("      (run5 snapshot absent — skipped)")


# ---------------------------------------------------------------------------
print("\nlocation — positional, bounded, and validated against the thirty-one")
# ---------------------------------------------------------------------------
#
# Bama renders no «موقعیت» label, which is why `province` is empty on all 76
# records of run 11 and why repost matching — which blocks and scores on
# `province` — has been running with one signal absent.
#
# OBSERVED is verbatim from `scripts/location_probe.py` against
# detail-oniy1maq on 2026-09-16. The variants around it are the cases a
# positional rule has to survive, and the last three are the ones that decide
# whether it is safe: a rule that cannot refuse is a rule that records a
# price as a province.

from caro.ingest.bama import extract_location                       # noqa: E402
from caro.ingest.persian import PROVINCES, province_of              # noqa: E402

OBSERVED_LOCATION_BLOCK = [
    "پراید،  141", "ساده", "1388",
    "کارکرد 500,000 کیلومتر",
    "5 روز پیش",
    "رباط کریم، تهران",
    "350,000,000",
    "تومان",
]


def _without(lines, drop):
    return [ln for ln in lines if ln != drop]


def _swap(lines, old, new):
    return [new if ln == old else ln for ln in lines]


for _name, _lines, _want_prov, _want_src in [
    ("the page as measured",
     OBSERVED_LOCATION_BLOCK, "تهران", "after_odometer"),
    # Round 4 §5: the relative phrase stops being rendered as a listing ages,
    # so the location is not at a fixed offset from the odometer.
    ("with the date line gone",
     _without(OBSERVED_LOCATION_BLOCK, "5 روز پیش"), "تهران", "after_odometer"),
    # A capital named as its province, alone, is the city: Bama leaves out a
    # province named as its city (run15, 2026-10-14). A province alone whose
    # capital is named otherwise is still what the line states.
    ("a capital named as its province, alone, is the city",
     _swap(OBSERVED_LOCATION_BLOCK, "رباط کریم، تهران", "تهران"),
     "تهران", "city_names_province"),
    ("a province alone, no capital's name, is stated",
     _swap(OBSERVED_LOCATION_BLOCK, "رباط کریم، تهران", "فارس"),
     "فارس", "after_odometer"),
    ("a city with no province is refused, not inferred",
     _swap(OBSERVED_LOCATION_BLOCK, "رباط کریم، تهران", "کرج"),
     None, "window_had_no_province"),
    ("no location: the PRICE is not taken instead",
     _without(OBSERVED_LOCATION_BLOCK, "رباط کریم، تهران"),
     None, "window_had_no_province"),
    ("no odometer line is a different fact from no province",
     [ln for ln in OBSERVED_LOCATION_BLOCK if not ln.startswith("کارکرد")],
     None, "no_anchor"),
    ("a label, if the page ever grows one back, read as a line is: a "
     "capital alone by the city",
     ["موقعیت", "اصفهان"] + OBSERVED_LOCATION_BLOCK, "اصفهان",
     "city_names_province"),
    ("  and a label that states its province, stated",
     ["موقعیت", "رباط کریم، تهران"] + OBSERVED_LOCATION_BLOCK, "تهران",
     "labelled"),
]:
    _raw, _prov, _src = extract_location(_lines)
    check(f"{_name} → {_want_prov or 'refused'}", _prov == _want_prov,
          f"got {_prov!r}")
    check(f"  and says how: {_want_src}", _src == _want_src, f"got {_src!r}")

check("the raw line is kept as rendered, city and all",
      extract_location(OBSERVED_LOCATION_BLOCK)[0] == "رباط کریم، تهران",
      str(extract_location(OBSERVED_LOCATION_BLOCK)[0]))

check("thirty-one provinces, no more and no fewer",
      len(PROVINCES) == 31 and len(set(PROVINCES)) == 31, str(len(PROVINCES)))

for _txt, _want in [
    ("رباط کریم، تهران", "تهران"),
    ("مشهد، خراسان رضوی", "خراسان رضوی"),
    ("تهران", None),               # the city alone: province_from_city's
    ("کرج", None),                 # a city, and البرز is not inferred from it
    ("350,000,000", None),
    ("کارکرد 500,000 کیلومتر", None),
    ("5 روز پیش", None),
    ("", None),
    (None, None),
]:
    check(f"province_of({_txt!r:26}) = {_want!r}", province_of(_txt) == _want,
          f"got {province_of(_txt)!r}")

# City, province, district: real lines, read off run13's pages by the probe
# on 2026-10-06 and out of date_watch's stored lines on 2026-10-10, where
# only the last part was read and so none of them was. The two-part lines
# below them are real too: the first part is the CITY, and a city is not a
# province the line states, whatever its name.
for _txt, _want in [
    ("مشهد، خراسان رضوی، فلسطین", "خراسان رضوی"),
    ("رشت، گیلان، قلی پور", "گیلان"),
    ("شیراز، فارس، فرهنگیان", "فارس"),
    ("کرج، البرز، گوهردشت", "البرز"),
    ("تهران، آذری", None),
    ("اصفهان، کهندژ", None),
]:
    check(f"province_of({_txt!r:28}) = {_want!r}", province_of(_txt) == _want,
          f"got {province_of(_txt)!r}")
_3 = _swap(OBSERVED_LOCATION_BLOCK, "رباط کریم، تهران", "شیراز، فارس، فرهنگیان")
check("a line of three parts gives its middle one, found after the odometer",
      extract_location(_3)[1:] == ("فارس", "after_odometer"),
      str(extract_location(_3)))

# A two-part line whose city is one of the thirteen capitals named as their
# province is: the nine read off date_watch's stored lines on 2026-10-10 — the
# largest shape among the misses, and where the market is. Refused below: a
# city that is not one of the thirteen, a province's name in the city's place,
# and anything but two parts.
from caro.ingest.persian import (                                   # noqa: E402
    SAME_NAME_CAPITALS, province_from_city)

check("thirteen capitals share their province's name, each a province",
      len(SAME_NAME_CAPITALS) == 13 and SAME_NAME_CAPITALS <= set(PROVINCES),
      str(sorted(SAME_NAME_CAPITALS - set(PROVINCES))))
for _txt, _want in [
    ("تهران، رسالت", "تهران"),
    ("تهران، مرزداران", "تهران"),
    ("تهران، تولید دارو", "تهران"),
    ("تهران، تهران\u200cنو", "تهران"),
    ("تهران، جنت\u200cآباد شمالی", "تهران"),
    ("تهران، شاهین", "تهران"),
    ("تهران، گرگان", "تهران"),        # a district of Tehran, not the city
    ("اصفهان، کهندژ", "اصفهان"),
    ("اصفهان، برازنده", "اصفهان"),
    ("کرج، گلشهر", None),             # البرز's capital, not named البرز
    ("گلستان، مرکز", None),           # a province's name in the city's place
    ("البرز، مرکز", None),
    ("تهران، آذری، شرقی", None),      # three parts: not this rule's shape
    ("تهران", "تهران"),               # the city alone, its province left out
    ("فارس", None),                   # a province alone is no city's
    ("رباط کریم، تهران", None),       # the city is not one of the thirteen
]:
    check(f"province_from_city({_txt!r:30}) = {_want!r}",
          province_from_city(_txt) == _want,
          f"got {province_from_city(_txt)!r}")

# A lone name: three real lines of run15 (2026-10-14), read out of its
# snapshot — «کرمان» on three listings, «زنجان» and «یزد» on one each. Every
# one of its 74 lines is «city، province، district», the province left out
# where it is named as the city and the district where there is none, so
# each of these is a city and states no province; and none of the other 43
# lines run15 read as stated is a province alone.
for _txt in ("کرمان", "زنجان", "یزد"):
    check(f"«{_txt}» alone: no province stated, the city's own",
          (province_of(_txt), province_from_city(_txt)) == (None, _txt),
          repr((province_of(_txt), province_from_city(_txt))))

_c = _swap(OBSERVED_LOCATION_BLOCK, "رباط کریم، تهران", "تهران، آذری")
check("a page whose city names its province: found, and said to be by the city",
      extract_location(_c) == ("تهران، آذری", "تهران", "city_names_province"),
      str(extract_location(_c)))
_both = _swap(OBSERVED_LOCATION_BLOCK, "5 روز پیش", "تهران، آذری")
_both = _swap(_both, "رباط کریم، تهران", "شیراز، فارس، فرهنگیان")
check("  a stated province wins, though the city line comes first",
      extract_location(_both)[1:] == ("فارس", "after_odometer"),
      str(extract_location(_both)))
check("  and «کرج» alone is still refused, as before",
      extract_location(_swap(OBSERVED_LOCATION_BLOCK, "رباط کریم، تهران",
                             "کرج"))[1:] == (None, "window_had_no_province"))

for _line, _want in [("تهران، آذری", ("تهران", "city")),
                     ("رباط کریم، تهران", ("تهران", "stated")),
                     ("کرمان", ("کرمان", "city")),
                     ("کرج", (None, "none"))]:
    _car = parse_detail_page(
        LU, ld_page(body=f"<p>{_line}</p><p>500,000,000</p><p>تومان</p>"))
    check(f"parse_detail_page on «{_line}»: province and source {_want}",
          (_car.city, _car.province_source) == _want,
          str((_car.city, _car.province_source)))
    # The line goes with the province it gave, for the snapshot's audit; a
    # page that gave none keeps none.
    check(f"  and keeps «{_line}» as the line it was read from" if _want[0]
          else "  and keeps no line, having read no province",
          _car.location_raw == (_line if _want[0] else None),
          repr(_car.location_raw))

# A new car: «صفر کیلومتر» where the reading is, then the age slot, then the
# location — the two new cars among date_watch's nineteen, as it stored them
# (read 2026-10-10), nine rounds each with the location unmoved. Neither was
# anchored before, so neither was read.
for _name, _lines, _want in [
    ("a new car whose line states its province",
     ["صفر کیلومتر", "22 ساعت پیش", "شیراز، فارس، فرهنگیان"],
     ("شیراز، فارس، فرهنگیان", "فارس", "after_odometer")),
    ("a new car whose city is one of the thirteen",
     ["صفر کیلومتر", "1405/6/19", "تهران، شاهین"],
     ("تهران، شاهین", "تهران", "city_names_province")),
]:
    check(f"{_name}: anchored on «صفر کیلومتر»",
          extract_location(_lines) == _want, str(extract_location(_lines)))
_later = ["کارکرد 500,000 کیلومتر", "5 روز پیش", "350,000,000", "تومان",
          "خودرو سالم", "صفر کیلومتر", "1405/6/19", "تهران، شاهین"]
check("  the first odometer line decides; «صفر کیلومتر» below it is not a "
      "second chance",
      extract_location(_later) == (None, None, "window_had_no_province"),
      str(extract_location(_later)))
_inside = ["خرید خودرو صفر کیلومتر", "1405/6/19", "تهران، شاهین"]
check("  and «صفر کیلومتر» inside a line is not an odometer line",
      extract_location(_inside) == (None, None, "no_anchor"),
      str(extract_location(_inside)))
for _line, _want in [("شیراز، فارس، فرهنگیان", ("فارس", "stated")),
                     ("تهران، شاهین", ("تهران", "city"))]:
    _page = ld_page(body=f"<p>1405/6/19</p><p>{_line}</p>"
                         "<p>500,000,000</p><p>تومان</p>").replace(
        "<p>کارکرد 43,000 کیلومتر</p>", "<p>صفر کیلومتر</p>")
    _car = parse_detail_page(LU, _page)
    check(f"parse_detail_page on a new car's «{_line}»: province and source "
          f"{_want}",
          "کارکرد" not in _page
          and (_car.city, _car.province_source) == _want,
          str(("کارکرد" in _page, _car.city, _car.province_source)))

# A province as the source spells it. Probed on bama:4flyapjw, 2026-10-11 —
# run14's one listing with no province: its window holds
# «یاسوج، کهکیلویه و بویراحمد», with ک where the province's name has گ, and
# so was read as naming no province at all. A spelling seen on a page is
# held in a closed table with where it was seen; ک and گ are not folded.
import caro.ingest.persian as _persian                               # noqa: E402

_KB = "کهگیلویه و بویراحمد"
check("province_of reads a province as the source spells it",
      province_of("یاسوج، کهکیلویه و بویراحمد") == _KB,
      repr(province_of("یاسوج، کهکیلویه و بویراحمد")))
_probed = ["کارکرد 200,000 کیلومتر", "12 ساعت پیش",
           "یاسوج، کهکیلویه و بویراحمد", "قیمت توافقی", "وضعیت بدنه"]
check("  and the probed window gives it, stated, the line kept as rendered",
      extract_location(_probed)
      == ("یاسوج، کهکیلویه و بویراحمد", _KB, "after_odometer"),
      str(extract_location(_probed)))
check("  but a word one letter from a province is not read as it",
      province_of("گرمان") is None, repr(province_of("گرمان")))
_sp = getattr(_persian, "PROVINCE_SPELLINGS", None)
check("  the spellings are a closed table, each naming one of the 31 and "
      "none itself one",
      bool(_sp) and all(v in PROVINCES and k not in PROVINCES
                        for k, v in _sp.items()), repr(_sp))

# ---------------------------------------------------------------------------
# the probe's phone guard — the claim that was false until it was run
# ---------------------------------------------------------------------------
# `scripts/location_probe.py` prints raw page lines, and bama renders the
# seller's number as one of them. Its first draft asserted in prose that no
# phone number was printed, reasoning from "nothing looks for one", and the
# first real run printed «۰۹۳۰۸۹۰۸۱XX».
#
# The prose is now a function, and the function is now checked here, because
# a guard on a constraint this project treats as non-negotiable should not be
# the one thing in the repository whose only evidence is a sentence. The
# first case below is the exact string that leaked; the keeps are the lines
# section 3 exists to display, which a plain length rule would have blanked.
from scripts.location_probe import redact_phone_like                 # noqa: E402

check("the line that actually leaked is redacted",
      redact_phone_like("۰۹۳۰۸۹۰۸۱XX") == "[11 digits redacted]",
      redact_phone_like("۰۹۳۰۸۹۰۸۱XX"))

for _line in [
    "کارکرد 500,000 کیلومتر",   # the anchor section 3 is built on
    "350,000,000",              # the price, three lines below it
    "رباط کریم، تهران",         # the value the whole probe is looking for
    "5 روز پیش",
    "1388",
    "4 سیلندر یورو3",
    "103 نیوتن‌متر",
    "1.3 لیتر",
    "نمایش شماره",              # the label, which carries no digits
]:
    check(f"survives untouched: {_line!r:28}",
          redact_phone_like(_line) == _line, redact_phone_like(_line))

for _line in [
    "09123456789",
    "۰۹۱۲ ۳۴۵ ۶۷۸۹",
    "0912-345-6789",
    "۰۲۱۸۸۷۷۶۶۵۵",
]:
    check(f"redacted: {_line!r:22}", "redacted" in redact_phone_like(_line),
          redact_phone_like(_line))

check("redacted mid-sentence, leaving the sentence",
      redact_phone_like("تماس ۰۹۱۲۳۴۵۶۷۸۹ فقط پیامک")
      == "تماس [11 digits redacted] فقط پیامک",
      redact_phone_like("تماس ۰۹۱۲۳۴۵۶۷۸۹ فقط پیامک"))

# The stated limit, asserted as a limit. This is here so that the docstring's
# "what this does not catch" cannot quietly become false in either direction:
# if someone widens the rule to cover it, this fails and the docstring gets
# corrected in the same commit.
check("a landline punctuated like a price is NOT caught, as documented",
      redact_phone_like("021,8877,6655") == "021,8877,6655",
      redact_phone_like("021,8877,6655"))

# And the guarantee that matters more than any of the above: the adapter has
# never read that line, whatever the probe does.
check("the adapter still records no seller_raw",
      parse_detail_page("https://bama.ir/car/detail-pnone", ld_page()) is None
      or parse_detail_page("https://bama.ir/car/detail-pnone",
                           ld_page()).seller_raw is None)


# ---------------------------------------------------------------------------
print("\nwhat a run writes says which robots.txt it obeyed")
import argparse as _argparse                                          # noqa: E402
import contextlib as _contextlib                                      # noqa: E402
import io as _io                                                      # noqa: E402
import re as _re                                                      # noqa: E402
import tempfile as _tempfile                                          # noqa: E402
from pathlib import Path as _Path                                     # noqa: E402
from scripts import first_run as _first_run                           # noqa: E402

_ROBOTS_SHA = _hashlib.sha256(BAMA_ROBOTS.encode("utf-8")).hexdigest()
_UTC_STAMP = _re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00")


def _first_run_into(tmp, fetcher):
    """first_run.collect against a fake bama, its snapshots in `tmp`."""
    args = _argparse.Namespace(source="bama", limit=10, categories=None,
                               makes="", seed=0, city="tehran", pages=1)
    old, _first_run.SNAPSHOT_DIR = _first_run.SNAPSHOT_DIR, _Path(tmp)
    out = _io.StringIO()
    try:
        with _contextlib.redirect_stdout(out):
            _, path = _first_run.collect(args, [], fetcher=fetcher,
                                         sleeper=lambda s: None)
        return json.loads(path.read_text(encoding="utf-8")), out.getvalue()
    finally:
        _first_run.SNAPSHOT_DIR = old


with _tempfile.TemporaryDirectory() as _tmp:
    try:
        _snap, _printed = _first_run_into(_tmp, bama_world()[0])
    except RobotsViolation as e:
        _snap, _printed = {"notes": [f"raised: {e}"]}, ""
_notes = [n for n in _snap["notes"] if n.startswith("robots.txt ")]
check("first_run: the snapshot names the robots.txt the run obeyed",
      len(_notes) == 1 and _ROBOTS_SHA in _notes[0], str(_snap["notes"]))
check("  and when it was read", bool(_notes) and bool(_UTC_STAMP.search(_notes[0])),
      str(_notes))
check("  and DISCOVERY printed the same", _ROBOTS_SHA in _printed)
_f, _asked = bama_world((503, ""))
with _tempfile.TemporaryDirectory() as _tmp:
    try:
        _first_run_into(_tmp, _f)
        _how = "ran"
    except RobotsViolation as e:
        _how = "everything" if e.everything else "one url"
    _left = list(_Path(_tmp).rglob("*"))
check("first_run: no policy, no request past robots.txt and nothing written",
      _how == "everything" and _asked == ["https://bama.ir/robots.txt"]
      and _left == [], f"{_how} {_asked} {_left}")

from scripts import date_watch as _date_watch                         # noqa: E402

_WATCH_ROWS = [
    {"listing_id": "bama:ffdrszax",
     "source_url": "https://bama.ir/car/detail-ffdrszax-peugeot-206ir-type5-1396"},
    {"listing_id": "bama:6xphr0fb",
     "source_url": "https://bama.ir/car/detail-6xphr0fb-peugeot-206ir-type2-1401"},
    {"listing_id": "bama:zzzz9999",
     "source_url": "https://bama.ir/car/detail-zzzz9999-pride-131-se-1398"},
]
_WATCH_ROBOTS = "User-agent: *\nDisallow: /car/detail-zzzz9999\n"
_f, _asked = bama_world((200, _WATCH_ROBOTS))
_wad = BamaAdapter(fetcher=_f, max_listings=1, max_categories=1,
                   sleeper=lambda s: None)
def _one_round(wad):
    """date_watch.run_round into a temporary file: its result, its rows."""
    with _tempfile.TemporaryDirectory() as tmp:
        w = _Path(tmp) / "w.jsonl"
        try:
            done = _date_watch.run_round(_WATCH_ROWS, wad, w)
        except RobotsViolation as e:
            done = f"raised: {e}"
        rows = ([json.loads(ln) for ln in
                 w.read_text(encoding="utf-8").splitlines()]
                if w.exists() else None)
    return done, rows


_done, _lines = _one_round(_wad)
_lines = _lines or []
_wsha = _hashlib.sha256(_WATCH_ROBOTS.encode("utf-8")).hexdigest()
check("date_watch: every row of a round carries the robots.txt it obeyed",
      len(_lines) == 2 and all((ln.get("robots") or {}).get("sha256") == _wsha
                               and _utc(ln["robots"].get("fetched_at"))
                               for ln in _lines), str(_lines)[:300])
check("  read once for the round, not once a row",
      _robots_asks(_asked) == 1, str(_asked))
check("  and a listing it disallows is neither requested nor written",
      _done == (2, 1) and not any("zzzz9999" in u for u in _asked)
      and not any(ln["listing_id"] == "bama:zzzz9999" for ln in _lines),
      f"{_done} {_asked}")
_f, _asked = bama_world((503, ""))
_wad = BamaAdapter(fetcher=_f, max_listings=1, max_categories=1,
                   sleeper=lambda s: None)
_done, _rows = _one_round(_wad)
_wrote = _rows is not None
check("date_watch: no policy, no request past robots.txt and nothing written",
      _done is None and not _wrote
      and _asked == ["https://bama.ir/robots.txt"], f"{_done} {_asked}")

# "Once per execution" holds because an execution is a process and a process
# builds one adapter. A script that built one inside a loop would read
# robots.txt once per turn of it, and nothing above would notice, so the
# scripts are read for that shape. A heuristic, not a proof: a construction
# hidden in a function that a loop calls is not seen.
import ast as _ast                                                    # noqa: E402

_ADAPTERS = ("BamaAdapter", "DivarCarAdapter")
_LOOPS = (_ast.For, _ast.AsyncFor, _ast.While, _ast.ListComp, _ast.SetComp,
          _ast.DictComp, _ast.GeneratorExp)


def _builds(node):
    f = node.func if isinstance(node, _ast.Call) else None
    name = (f.id if isinstance(f, _ast.Name)
            else f.attr if isinstance(f, _ast.Attribute) else "")
    return name in _ADAPTERS


_in_loop, _found, _written = {}, 0, 0
for _p in sorted((_Path(__file__).resolve().parent.parent
                  / "scripts").glob("*.py")):
    _src = _p.read_text(encoding="utf-8")
    _tree = _ast.parse(_src)
    _found += sum(_builds(n) for n in _ast.walk(_tree))
    _written += sum(_src.count(f"{a}(") for a in _ADAPTERS)
    _hits = sorted({n.lineno for loop in _ast.walk(_tree)
                    if isinstance(loop, _LOOPS)
                    for n in _ast.walk(loop) if _builds(n)})
    if _hits:
        _in_loop[_p.name] = _hits
check("no script builds an adapter inside a loop: one execution, one "
      "adapter, one robots.txt", not _in_loop, str(_in_loop))
check("  and the scan saw every adapter the scripts build",
      _found == _written and _found > 0, f"{_found} of {_written}")


# ---------------------------------------------------------------------------
print("\npage_probe: a few public pages, kept on this machine")
# The roadmap's method for a source whose markup nothing here holds: the owner
# probes, the pages stay on his machine, the adapter is written offline against
# them. Divar has no listing-page extraction and Sheypoor and Khodro45 have no
# adapter. These tests run the probe against a fake world: no network, no
# browser. Every page is made here; none is a page a source served.
from caro.ingest.divar_car import PolitenessPolicy as _PPolicy        # noqa: E402
from scripts import page_probe as _pp                                  # noqa: E402

_PP_ROBOTS = "User-agent: *\nDisallow: /my-divar/*\nDisallow: /private\n"
_PP_ORIGIN = "https://shop.example"
_PP_A, _PP_B, _PP_C = (f"{_PP_ORIGIN}/cars/{n}" for n in "abc")


def _pp_world(robots=(200, _PP_ROBOTS), pages=None):
    """(fetch, robots_fetch, requested urls, robots urls, sleeps)."""
    pages = pages or {}
    asked, robots_asked, sleeps = [], [], []

    def robots_fetch(url):
        robots_asked.append(url)
        return robots

    def fetch(url):
        asked.append(url)
        r = pages.get(url, (404, ""))
        if isinstance(r, Exception):
            raise r
        return r

    return fetch, robots_fetch, asked, robots_asked, sleeps


def _pp_run(urls, *, tmp, source="shop", origin=_PP_ORIGIN, world=None,
            sub="run"):
    fetch, robots_fetch, asked, robots_asked, sleeps = (
        world or _pp_world(pages={u: (200, f"<html>{u}</html>") for u in urls}))
    res = _pp.probe(origin, urls, source=source, fetch=fetch,
                    robots_fetch=robots_fetch, out_dir=_Path(tmp) / sub,
                    policy=_PPolicy(), sleeper=sleeps.append)
    return res, asked, robots_asked, sleeps


with _tempfile.TemporaryDirectory() as _tmp:
    _res, _asked, _rasked, _slept = _pp_run([_PP_A, _PP_B], tmp=_tmp)
    _m = _res.manifest
    _files = sorted(p.name for p in _res.out_dir.glob("*.html"))
    check("a probe keeps each page that returned, numbered, beside probe.json",
          len(_files) == 2 and _files[0].startswith("01-")
          and _files[1].startswith("02-")
          and (_res.out_dir / "probe.json").exists() and _res.exit_code == 0,
          str(_files))
    check("  the manifest's sha256 and size are those of the bytes kept",
          all(hashlib_ok for hashlib_ok in [
              p["sha256"] == _hashlib.sha256(
                  (_res.out_dir / p["saved_as"]).read_bytes()).hexdigest()
              and p["bytes"] == len((_res.out_dir / p["saved_as"]).read_bytes())
              for p in _m["pages"]]))
    check("  robots.txt is read once, and before any page",
          _rasked == [_PP_ORIGIN + "/robots.txt"] and _asked == [_PP_A, _PP_B])
    check("  it is recorded with the sha256 of what was read",
          _hashlib.sha256(_PP_ROBOTS.encode("utf-8")).hexdigest()
          in _m["robots_line"] and _m["robots"]["http_status"] == 200)
    check("  the User-Agent is ours and says who to write to",
          _m["user_agent"] == _PPolicy().user_agent
          and PRODUCT_TOKEN in _m["user_agent"] and "contact:" in _m["user_agent"])
    check("  the pause follows robots.txt and stands between two pages, not "
          "after the last",
          len(_slept) == 2 and all(s >= _PPolicy().delay_min_s for s in _slept),
          str(_slept))
    check("  the manifest parses as JSON",
          json.loads((_res.out_dir / "probe.json").read_text(
              encoding="utf-8"))["source"] == "shop")

with _tempfile.TemporaryDirectory() as _tmp:
    _res, _asked, _rasked, _slept = _pp_run([_PP_A], tmp=_tmp)
    check("one page: the only pause is the one after robots.txt",
          len(_slept) == 1, str(_slept))

with _tempfile.TemporaryDirectory() as _tmp:
    _priv = f"{_PP_ORIGIN}/private"
    _res, _asked, _, _ = _pp_run([_PP_A, _priv, _PP_B], tmp=_tmp)
    _mp = _res.manifest["pages"]
    check("a url robots.txt disallows is not requested, and the probe goes on",
          _asked == [_PP_A, _PP_B] and _mp[1]["requested"] is False
          and "disallows" in _mp[1]["refused"] and _res.exit_code == 0,
          str(_asked))

with _tempfile.TemporaryDirectory() as _tmp:
    _w = _pp_world(robots=(503, ""), pages={_PP_A: (200, "<html></html>")})
    _res, _asked, _, _ = _pp_run([_PP_A, _PP_B], tmp=_tmp, world=_w)
    check("robots.txt that gives no policy: nothing is requested, and it says so",
          _asked == [] and _res.exit_code == 1
          and "no policy" in (_res.manifest["halted"] or "")
          and not list(_res.out_dir.glob("*.html")), str(_res.manifest["halted"]))

with _tempfile.TemporaryDirectory() as _tmp:
    _w = _pp_world(pages={_PP_A: (200, "<html>a</html>"), _PP_B: (403, ""),
                          _PP_C: (200, "<html>c</html>")})
    _res, _asked, _, _ = _pp_run([_PP_A, _PP_B, _PP_C], tmp=_tmp, world=_w)
    _mp = _res.manifest["pages"]
    check("the first page that does not return stops the probe: no retry, the "
          "third is never asked",
          _asked == [_PP_A, _PP_B] and _mp[1]["not_returned"] == "http 403"
          and _res.exit_code == 1 and "recorded" in _res.manifest["halted"],
          str(_asked))
    check("  what returned before it is kept",
          len(list(_res.out_dir.glob("*.html"))) == 1)

with _tempfile.TemporaryDirectory() as _tmp:
    _w = _pp_world(pages={_PP_A: RuntimeError("boom"), _PP_B: (200, "<html/>")})
    _res, _asked, _, _ = _pp_run([_PP_A, _PP_B], tmp=_tmp, world=_w)
    check("an error is not a page: recorded, and the probe stops",
          _asked == [_PP_A] and _res.manifest["pages"][0]["not_returned"]
          .startswith("RuntimeError") and _res.exit_code == 1)

with _tempfile.TemporaryDirectory() as _tmp:
    _w = _pp_world(pages={_PP_A: (200, "")})
    _res, _, _, _ = _pp_run([_PP_A], tmp=_tmp, world=_w)
    check("a 200 with an empty body is not a page",
          _res.manifest["pages"][0]["not_returned"] == "empty body"
          and _res.exit_code == 1)

with _tempfile.TemporaryDirectory() as _tmp:
    _res, _asked, _, _ = _pp_run(["https://other.example/x", _PP_A], tmp=_tmp)
    check("a url on another origin is refused, not requested",
          _asked == [_PP_A] and "not on" in _res.manifest["pages"][0]["refused"])

with _tempfile.TemporaryDirectory() as _tmp:
    _w = _pp_world()
    _res, _asked, _, _ = _pp_run(
        ["https://divar.ir/s/tehran/light?q=206"], tmp=_tmp, source="divar",
        origin="https://divar.ir", world=_w)
    check("divar: the 2026-09-07 transcription is asked as well; a search url "
          "is refused and nothing is requested",
          _asked == [] and "search urls" in _res.manifest["pages"][0]["refused"]
          and _res.exit_code == 1)

for _what, _kw in [
    ("no url", dict(urls=[])),
    (f"more than {_pp.MAX_URLS} urls",
     dict(urls=[f"{_PP_ORIGIN}/{i}" for i in range(_pp.MAX_URLS + 1)])),
    ("a source name with a path in it", dict(urls=[_PP_A], source="../x")),
    ("a source name in capitals", dict(urls=[_PP_A], source="Divar")),
]:
    with _tempfile.TemporaryDirectory() as _tmp:
        _w = _pp_world()
        try:
            _pp.probe(_PP_ORIGIN, _kw["urls"], source=_kw.get("source", "shop"),
                      fetch=_w[0], robots_fetch=_w[1],
                      out_dir=_Path(_tmp) / "run", sleeper=lambda s: None)
            _raised = False
        except _pp.ProbeRefused:
            _raised = True
        check(f"refused: {_what}; nothing was asked",
              _raised and _w[2] == [] and _w[3] == [])

_w = _pp_world()
try:
    _pp.probe(_PP_ORIGIN, [_PP_A], source="shop", fetch=_w[0],
              robots_fetch=_w[1], out_dir=_pp.ROOT / "data" / "probe-test",
              sleeper=lambda s: None)
    _raised = False
except _pp.ProbeRefused:
    _raised = True
check("a folder inside the repository is refused: what a probe keeps is never "
      "committed", _raised and _w[2] == [] and _w[3] == []
      and not (_pp.ROOT / "data" / "probe-test").exists())

with _tempfile.TemporaryDirectory() as _tmp:
    _pp_run([_PP_A], tmp=_tmp)
    try:
        _pp_run([_PP_A], tmp=_tmp)
        _raised = False
    except _pp.ProbeRefused:
        _raised = True
    check("a run is never overwritten", _raised)

# --- the skeleton
_PP_CARD = ('<article class="post-card" data-testid="post-card" '
            'data-token="aB3dE5fGh{i}"><a href="/v/aB3dE5fGh{i}?src=feed" '
            'class="card-link"><h2 class="title">پراید ۱۱۱ مدل ۱۳۹۸ تمیز {i}'
            '</h2><div class="price">۲۵۰,۰۰۰,۰۰۰ تومان</div></a>'
            '<span class="seller">نمایشگاه آقای رضایی</span>'
            '<a href="tel:09121234567">تماس</a>'
            '<a href="mailto:seller@example.com">ایمیل</a>'
            '<img alt="09121234567" src="https://img.example/p/abc123def456.jpg?w=300">'
            '</article>')
_PP_PAGE = ("<html><head><script>var phone='09121234567'</script>"
            "<style>.a{color:red}</style></head><body><main class='list'>"
            + "".join(_PP_CARD.format(i=i) for i in range(1, 6))
            + "<footer>۰۲۱-۱۲۳۴۵۶۷۸ — 0912 123 4567</footer></main></body></html>")
_SK = _pp.skeleton(_PP_PAGE, name="fake.html")
_SK_TREE = _SK.split("# tree:")[1]
check("skeleton: no phone number, no email and no token of the page is in it",
      not any(x in _SK for x in ("09121234567", "0912", "۰۹۱۲", "۰۲۱",
                                 "seller@", "example.com", "aB3dE5fGh")))
check("  and no digit taken from the page: what is left is the repeat counts "
      "and the h1-h6 of a tag",
      not _re.search(r"\d", _re.sub(r"\bh[1-6]\b", "h", _re.sub(
          r"  ×\d+", "", _SK_TREE))), _SK_TREE)
check("  script and style are not shown", "var phone" not in _SK
      and "color:red" not in _SK)
check("  five identical cards are one row with the count",
      _SK_TREE.count("article") == 1 and "×5" in _SK_TREE)
check("  the links are counted over the whole page, by masked path",
      "/v/<tok>  (5)" in _SK and "tel:…  (5)" in _SK
      and "mailto:…  (5)" in _SK)
check("  a tel: and a mailto: link are their scheme alone, and not one row",
      "[href=tel:…]" in _SK_TREE and "[href=mailto:…]" in _SK_TREE)
check("  a test id with a dash and no digit stays: a selector needs it",
      "[data-testid=post-card]" in _SK_TREE)
check("  a text is cut at 40 characters and digits are #",
      '"پراید # مدل # تمیز #"' in _SK_TREE
      and '"' + "x" * 40 + '…"' in _pp.skeleton("<p>" + "x" * 90 + "</p>"))
check("  --no-text leaves every text out and keeps the shape",
      "رضایی" not in _pp.skeleton(_PP_PAGE, with_text=False)
      and "span .seller" in _pp.skeleton(_PP_PAGE, with_text=False))
check("  two rows of different shape are not merged",
      _pp.skeleton("<ul><li class='a'>x</li><li class='b'>y</li></ul>")
      .count("li .") == 2)
check("  a digit in a class does not split a row",
      _pp.skeleton("<ul><li class='c-1'>x</li><li class='c-2'>y</li></ul>")
      .count("li .") == 1)
check("  it is deterministic", _pp.skeleton(_PP_PAGE) == _pp.skeleton(_PP_PAGE))

with _tempfile.TemporaryDirectory() as _tmp:
    _f = _Path(_tmp) / "p.html"
    _f.write_text(_PP_PAGE, encoding="utf-8")
    _out = _io.StringIO()
    with _contextlib.redirect_stdout(_out):
        _rc = _pp.main(["--skeleton", str(_f)])
    check("the command line prints a skeleton with no network and exits 0",
          _rc == 0 and "# tree:" in _out.getvalue())
try:
    with _contextlib.redirect_stderr(_io.StringIO()):
        _pp.main([])
    _usage = False
except SystemExit as _e:
    _usage = _e.code == 2
check("the command line with nothing to do is a usage error", _usage)


# --- rows and scripts: found, not scrolled to
# The first real page, Divar's car category (816,689 bytes), began with 400 lines
# of menu and filters, and the listings were past them. And a listing token
# with no digit in it (about one in four) made its card a row of its own.
_PP_TOKS = ["AbCdEfGh", "xYzWvUtS", "QwErTyUi", "Ab3Cd3Ef", "pLoKiJuH", "zXcVbNmQ"]
_PP_LIST = ("<ul class='sub'>" + "".join(
    f"<li class='sub-item'>t{n}</li>" for n in range(4)) + "</ul>")
_PP_CARDS = "".join(
    f'<div class="card-wrap"><a class="kt-post-card" href="/v/pride-tamiz/'
    f'{_PP_TOKS[i % 6]}"><h2 class="title">پراید ۱۱۱ مدل ۱۳۹۸ {i}</h2>'
    f'<div class="desc">۱۲۰ کیلومتر</div><div class="desc">۲۵۰ تومان</div>'
    f'{_PP_LIST}</a></div>' for i in range(1, 25))
_PP_SIDE = ("<nav>" + "".join(
    f'<a class="kt-chip" href="/s/tehran/cat{c}x">c{c}</a>'
    for c in "abcdefghij") + "</nav><aside><ul>" + "".join(
    f'<li class="acc"><a href="/s/tehran/{c}-category">name {c}</a></li>'
    for c in "abcd") + "</ul></aside>")
_PP_LISTING = f"<body>{_PP_SIDE}<main>{_PP_CARDS}</main></body>"
_RW = _pp.rows(_PP_LISTING, with_text=False)
_RW_HEADS = [l for l in _RW.splitlines() if l.startswith("# ×")]
check("rows: the cards come first, with the count and where they sit",
      _RW_HEADS and _RW_HEADS[0].startswith("# ×24,")
      and "under: body > main" in _RW_HEADS[0], str(_RW_HEADS))
check("  one instance of them is printed in full, and not 24",
      _RW.count("kt-post-card [href=") == 1 and "title" in _RW)
check("  cards whose tokens hold no digit are one row all the same, and no "
      "token is printed",
      "×24" in _RW and not any(t in _RW for t in _PP_TOKS)
      and "[href=/v/pride-tamiz/<tok>]" in _RW)
check("  the rows inside a card are not shown again as a group of their own",
      len(_RW_HEADS) >= 1 and not any("sub" in l for l in _RW_HEADS))
check("  a group of single elements (the chips) is not a row",
      "kt-chip" not in _RW)
check("  a group that is not inside a card is (the accordion)",
      any("acc" in _RW.split(h)[1].split("#")[0] for h in _RW_HEADS[1:2]))
check("  a group of two is not a row",
      "none found" in _pp.rows("<ul><li class='a'><b>1</b></li>"
                               "<li class='a'><b>2</b></li></ul>"))
check("  top=1 shows one group",
      len([l for l in _pp.rows(_PP_LISTING, top=1).splitlines()
           if l.startswith("# ×")]) == 1)
check("  with text, digits are # and a name is there; --no-text leaves it out",
      '"پراید # مدل #' in _pp.rows(_PP_LISTING)
      and "پراید" not in _pp.rows(_PP_LISTING, with_text=False))
check("  it is deterministic", _pp.rows(_PP_LISTING) == _pp.rows(_PP_LISTING))

_PP_STATE = {"listings": [{"token": "Ab3Cd3Ef", "title": "پراید ۱۱۱", "price": 250000000,
                           "mileage": "120000", "phone": "09121234567", "seller": "رضایی",
                           "image": "https://x.example/a.jpg", "bargain": True,
                           "meta": {"lat": 35.7, "ids": [1, 2, 3]}}] * 24,
             "filters": {f"k{i}": {"min": 1} for i in range(50)},
             "by_id": {f"12345678{i}": {"n": 1} for i in range(3)}}
_PP_SCRIPTS = (
    "<html><head><script>window.__STATE__ = " + json.dumps(_PP_STATE, ensure_ascii=False)
    + ";</script><script type='application/ld+json'>" + json.dumps(
        {"@type": "ItemList", "itemListElement": [{"position": i, "url": f"https://d.ir/v/x{i}"}
                                                  for i in range(1, 25)]})
    + "</script><script>window.D = JSON.parse(" + json.dumps(json.dumps(
        {"a": [{"b": "c" * 40}] * 9, "pad": "z" * 300}, ensure_ascii=False)) + ");</script>"
    "<script>" + "var x = 1;" * 60 + "</script><script>var s = 1;</script>"
    "<script src='/web-assets/main.js'></script></head></html>")
_SC = _pp.scripts_report(_PP_SCRIPTS)
check("scripts: the keys, the length of each list and the kind of each value "
      "are printed, after an assignment",
      all(x in _SC for x in ("listings: list of 24", "price: int", "title: fa-text",
                             "phone: digits(11)", "image: url", "bargain: bool",
                             "lat: float", "ids: list of 3")), _SC)
check("  and no value is: not a phone, a name, a token, a price or a url",
      not any(x in _SC for x in ("09121234567", "رضایی", "Ab3Cd3Ef", "250000000",
                                 "120000", "x.example", "35.7")))
check("  a bare JSON script (ld+json) and a JSON.parse(\"...\") are read too",
      "itemListElement: list of 24" in _SC and "a: list of 9" in _SC)
check("  fifty uniform keys are one line, and an id used as a key is masked",
      "<50 keys such as" in _SC and "k#" in _SC and "12345678" not in _SC)
check("  a long script that is not JSON is said not to be; a short one and an "
      "external one are not read",
      "not JSON" in _SC and "var s = 1" not in _SC and "main.js" not in _SC
      and "1 external" in _SC)
check("  it is deterministic", _pp.scripts_report(_PP_SCRIPTS) == _pp.scripts_report(_PP_SCRIPTS))

check("the link table folds a first segment that holds many paths into one row",
      "/s/<…>  (14)" in _pp.skeleton(_PP_LISTING)
      and "/v/pride-tamiz/<tok>  (24)" in _pp.skeleton(_PP_LISTING))
check("an id-like run is a token: a digit; in the path of a link also both "
      "cases. A word is not, and camelCase is structure outside a path",
      all(_pp._is_token(t) for t in ("Ab3Cd3Ef", "rawButton-W5tTZw", "3f9a1c2e"))
      and all(_pp._is_token(t, strict=True) for t in ("AbCdEfGh", "Ab3Cd3Ef"))
      and not any(_pp._is_token(t, strict=True) for t in (
          "post-card", "buy-apartment", "kt-new-modal", "short"))
      and not _pp._is_token("itemListElement")
      and _pp._mask_token("itemListElement") == "itemListElement"
      and _pp._mask_href("/s/tehran/buy-apartment") == "/s/tehran/buy-apartment"
      and _pp._mask_href("/v/pride-tamiz/AbCdEfGh") == "/v/pride-tamiz/<tok>")
check("a JSON key: a name stays, a digit run or a long hex id is data",
      _pp._mask_key("itemListElement") == "itemListElement"
      and _pp._mask_key("by_id") == "by_id"
      and _pp._mask_key("123456780") == "<tok>" and _pp._mask_key("7") == "#"
      and _pp._mask_key("k12") == "k#")
with _tempfile.TemporaryDirectory() as _tmp:
    _f = _Path(_tmp) / "p.html"
    _f.write_text(_PP_LISTING + _PP_SCRIPTS, encoding="utf-8")
    for _flag, _mark in (("--rows", "# rows of"), ("--scripts", "# scripts of")):
        _out = _io.StringIO()
        with _contextlib.redirect_stdout(_out):
            _rc = _pp.main([_flag, str(_f)])
        check(f"the command line {_flag} prints with no network and exits 0",
              _rc == 0 and _mark in _out.getvalue())


print("\ndivar's category page — read from the shape the probe found")
# Invented to the SHAPE that `page_probe.py --rows/--scripts` printed on
# 2026-10-26 (a list of vehicle objects in one ld+json script; the same
# vehicles as article.kt-post-card with a link to /v/<slug>/<token>). No
# value here was on that page: the probe prints none.
import html as _html
from caro.ingest import divar_page as _dp
from caro.ingest.divar_page import (
    DivarPageParser, PageTrace, parse_divar_page, read_cards, token_of,
)
from caro.ingest.quality import eligibility as _eligibility


def _node(tok, name="پراید ۱۳۱ SE", *, year="1395", km="120000", price="4500000000",
          cur="IRR", unit="KMT", city="تهران", district="پونک", gear="Manual",
          vin="9SECRETVIN0001", host="https://divar.ir", slug="pride", extra=None):
    n = {"@context": "https://schema.org", "@type": "Car", "name": name,
         "productionDate": year, "vehicleModelDate": year,
         "vehicleIdentificationNumber": vin,
         "image": "https://s100.divarcdn.com/static/photo/" + tok + ".jpg",
         "category": "passenger-car", "color": "سفید", "model": "131",
         "vehicleTransmission": gear, "knownVehicleDamages": "ندارد",
         "url": f"{host}/v/{slug}/{tok}",
         "itemCondition": "https://schema.org/UsedCondition",
         "brand": {"@type": "Brand", "name": "سایپا"},
         "web_info": {"title": name, "city_persian": city,
                      "district_persian": district,
                      "category_slug_persian": "سواری"}}
    if km is not None:
        n["mileageFromOdometer"] = {"@type": "QuantitativeValue", "value": km,
                                    "unitCode": unit}
    if year is None:
        del n["productionDate"], n["vehicleModelDate"]
    offers = {"@type": "Offer", "availability": "https://schema.org/InStock"}
    if price is not None:
        offers["price"], offers["priceCurrency"] = price, cur
    n["offers"] = offers
    n.update(extra or {})
    return n


def _card(tok, title="پراید ۱۳۱ SE", lines=("۱۲۰٬۰۰۰ کیلومتر", "۴۵۰٬۰۰۰٬۰۰۰ تومان"),
          slug="pride", classes="kt-post-card kt-post-card--outlined"):
    ds = "".join(f'<div class="kt-post-card__description">{_html.escape(x)}</div>'
                 for x in lines)
    return (f'<div class="widget-col-d2306"><div><article class="{classes}">'
            f'<a class="kt-post-card__action" href="/v/{slug}/{tok}">'
            f'<div class="kt-post-card__body"><div class="kt-post-card__info">'
            f'<h2 class="kt-post-card__title">{_html.escape(title)}</h2>{ds}'
            f'<div class="kt-post-card__bottom"><span class="kt-post-card__bottom-description '
            f'kt-text-truncate" title="x">لحظاتی پیش در تهران</span></div></div>'
            f'<div class="kt-post-card-thumbnail"><div><picture><img class="kt-image-block__image" '
            f'src="https://s100.divarcdn.com/p.webp" alt="x"></picture></div>'
            f'<div class="kt-tag"><i class="kt-icon"></i><span class="kt-tag__text">نردبان</span></div>'
            f'</div></div></a></article></div>')


def _page(nodes, cards=(), *, extra_ld=()):
    ld = [json.dumps(list(nodes), ensure_ascii=False)] if nodes is not None else []
    ld += list(extra_ld)
    return ("<html><head>"
            + "".join(f'<script type="application/ld+json">{x}</script>' for x in ld)
            + '</head><body><div class="post-list__items-container-e44b2">'
            + "".join(cards) + "</div></body></html>")


_T = ["AbCd1234", "EfGh5678", "IjKl9012"]
_p1 = parse_divar_page(_page([_node(t) for t in _T], [_card(t) for t in _T]))
check("X1: three nodes with their cards are three listings, in page order, "
      "identified by the token",
      [x.listing_id for x in _p1] == _T, str([x.listing_id for x in _p1]))
_tr = PageTrace()
parse_divar_page(_page([_node(t) for t in _T], [_card(t) for t in _T]), _tr)
check("  read from json-ld, and the trace says how many of each",
      (_tr.source, _tr.ld_nodes, _tr.cards, _tr.emitted) == ("jsonld", 3, 3, 3),
      str(_tr))
_a = _p1[0]
check("X2: IRR 4,500,000,000 and a card that says 450,000,000 toman agree: "
      "the price, display-confirmed, with what each side said kept",
      (_a.asking_price_toman, _a.price_status, _a.price_provenance,
       _a.price_displayed_toman, _a.price_currency_raw, _a.price_raw)
      == (450_000_000, "display_confirmed", "jsonld+text", 450_000_000, "IRR",
          "4500000000"), str(_a))


def _one(node, card=None, **kw):
    return parse_divar_page(_page([node], [card] if card else []), **kw)[0]


_b = _one(_node("AbCd1234", price="450000000"), _card("AbCd1234"))
check("X3: a toman figure under an IRR label is corrected by what the buyer sees",
      (_b.asking_price_toman, _b.price_status) == (450_000_000, "label_corrected"),
      str((_b.asking_price_toman, _b.price_status)))
_c = _one(_node("AbCd1234"))
check("X4: with no card the label is read literally, and the status says the "
      "unit is unconfirmed",
      (_c.asking_price_toman, _c.price_status, _c.price_provenance)
      == (450_000_000, "structured_only", "jsonld"), str(_c))
_d = _one(_node("AbCd1234", price=None), _card("AbCd1234", lines=("۱۲۰٬۰۰۰ کیلومتر", "توافقی")))
check("X5: no price and «توافقی» on the card is negotiable, not absent, and the "
      "listing is refused as a price",
      (_d.asking_price_toman, _d.price_status, _d.price_kind)
      == (None, "negotiable", "negotiable")
      and not _eligibility(_d)[0], str(_d))
_e = _one(_node("AbCd1234"), _card("AbCd1234", lines=("۱۲۰٬۰۰۰ کیلومتر",
                                                        "پیش‌پرداخت ۲۰۰٬۰۰۰٬۰۰۰ تومان")))
check("X6: a deposit on the card is no asking price, whatever the node says",
      (_e.asking_price_toman, _e.price_status) == (None, "ambiguous"),
      str((_e.asking_price_toman, _e.price_status)))
_f = _one(_node("AbCd1234"), _card("AbCd1234", lines=("۱۲۰٬۰۰۰ کیلومتر", "۶۰۰٬۰۰۰٬۰۰۰ تومان")))
check("X7: two prices that no unit explains are no price",
      (_f.asking_price_toman, _f.price_status) == (None, "ambiguous"),
      str((_f.asking_price_toman, _f.price_status)))
_g = _one(_node("AbCd1234", price=None), _card("AbCd1234", lines=("۱۲۰٬۰۰۰ کیلومتر",)))
check("X8: no price anywhere and no «توافقی» is absent, which is not a refusal "
      "to name one",
      (_g.asking_price_toman, _g.price_status) == (None, "absent"),
      str((_g.asking_price_toman, _g.price_status)))
_h = _one(_node("AbCd1234"), _card("AbCd1234", lines=("۴۵۰٬۰۰۰٬۰۰۰ تومان", "۱۰ میلیون تومان ماهانه")[:1]
                                   + ("۳۰۰٬۰۰۰٬۰۰۰ تومان",)))
check("X9: two «تومان» lines on a card show no price; the node's stands, unconfirmed",
      (_h.price_displayed_toman, _h.asking_price_toman, _h.price_status)
      == (None, 450_000_000, "structured_only"), str(_h))

_i = _one(_node("AbCd1234"), _card("AbCd1234"))
check("X10: the node and the card say the same odometer: 120,000 km, plausible",
      (_i.mileage_km, _i.mileage_status) == (120000, "plausible"),
      str((_i.mileage_km, _i.mileage_status)))
_j = _one(_node("AbCd1234", km="5"), _card("AbCd1234"))
check("X11: 5 against 120,000 is no odometer, and the note names both",
      (_j.mileage_km, _j.mileage_status) == (None, "unknown")
      and "5 vs 120000" in (_j.mileage_note or ""), str(_j.mileage_note))
_k = _one(_node("AbCd1234", km="119800"), _card("AbCd1234", lines=("۱۲۰ هزار کیلومتر", "۴۵۰٬۰۰۰٬۰۰۰ تومان")))
check("X12: a card that rounds to thousands agrees with the exact node; the "
      "node's number is kept",
      _k.mileage_km == 119800, str(_k.mileage_km))
check("X13: the node's odometer alone is judged by age",
      _one(_node("AbCd1234")).mileage_km == 120000
      and _one(_node("AbCd1234", km="40000", year="1395")).mileage_status == "plausible"
      and _one(_node("AbCd1234", km="9000", year="1395")).mileage_status == "suspicious")
_l = _one(_node("AbCd1234", km=None), _card("AbCd1234", lines=("کارکرد ۸۰ هزار کیلومتر", "۴۵۰٬۰۰۰٬۰۰۰ تومان")))
check("X14: no odometer on the node and one on the card is the card's",
      _l.mileage_km == 80000, str(_l.mileage_km))
_m = _one(_node("AbCd1234", km="0"))
check("X15: 0 km on a ten-year-old car is the placeholder rule's, and the gate refuses it",
      (_m.mileage_km, _m.mileage_status) == (0, "suspicious")
      and not _eligibility(_m)[0], str((_m.mileage_km, _m.mileage_status)))
check("X16: 1395 is 1395, the Gregorian 2016 is 1395, a title's «۹۵» is 1395 when "
      "the node has no date, and the node beats a title one year apart",
      _one(_node("AbCd1234", year="1395")).year_jalali == 1395
      and _one(_node("AbCd1234", year="2016")).year_jalali == 1395
      and _one(_node("AbCd1234", year=None, name="پراید ۱۳۱ مدل ۹۵")).year_jalali == 1395
      and _one(_node("AbCd1234", year="1395", name="پراید ۱۳۱ مدل ۹۴")).year_jalali == 1395)   # one apart: the node's (J2)

_secret = _page([_node("AbCd1234", vin="9SECRETVIN0001")], [_card("AbCd1234")],
                extra_ld=[json.dumps({
                    "@context": "https://schema.org", "@type": "Organization",
                    "name": "x", "contactPoint": {"telephone": "+98-21-0000000",
                                                   "email": "help@divar.example"},
                    "telephone": "02100000000"})])
_sl = parse_divar_page(_secret)
_seen_text = repr(_sl) + repr([o.to_fetch_outcome("divar", "s") for o in _sl])
check("X17: no vehicle identifier, no image and no contact from the page is in a "
      "listing or in the outcome made from it",
      len(_sl) == 1 and not any(x in _seen_text for x in (
          "9SECRETVIN0001", "divarcdn", "02100000000", "help@divar", "+98-21")))
_n = _one(_node("AbCd1234"))
check("X18: Tehran is its own province, known from the city; the district stays in "
      "the line that goes to the snapshot only",
      (_n.city, _n.province_source, _n.location_raw) == ("تهران", "city", "تهران، پونک"),
      str((_n.city, _n.province_source, _n.location_raw)))
_o = _one(_node("AbCd1234", city="کرج", district="گلشهر"))
check("X19: Karaj names no province here, and says so",
      (_o.city, _o.province_source, _o.location_raw) == (None, "none", "کرج، گلشهر"),
      str((_o.city, _o.province_source, _o.location_raw)))
_tr = PageTrace()
_bc = json.dumps({"@type": "BreadcrumbList", "itemListElement": []})
parse_divar_page(_page([_node("AbCd1234")], [_card("AbCd1234")], extra_ld=[_bc]), _tr)
check("X20: a breadcrumb and an organisation are not vehicles", _tr.ld_nodes == 1, str(_tr.ld_nodes))
_tr = PageTrace()
_bad = parse_divar_page(_page([_node("AbCd1234")], [], extra_ld=["{not json"]), _tr)
check("X21: a script that is not JSON is skipped, and the others still read",
      [x.listing_id for x in _bad] == ["AbCd1234"])
_tr = PageTrace()
_sk = parse_divar_page(_page([_node("AbCd1234"), _node("EfGh5678", host="https://evil.example"),
                              {**_node("IjKl9012"), "url": "https://divar.ir/s/tehran/car"}],
                             []), _tr)
check("X22: a vehicle on another host, or with no token, is skipped and counted",
      [x.listing_id for x in _sk] == ["AbCd1234"]
      and _tr.skipped["foreign url"] == 1 and _tr.skipped["no token"] == 1, str(_tr.skipped))
check("X23: the same token twice on a page is one listing",
      len(parse_divar_page(_page([_node("AbCd1234"), _node("AbCd1234")], []))) == 1)
_q = _one(_node("AbCd1234", name="حواله پراید ۱۳۱"))
check("X24: «حواله» in the title is an assignment, and the gate refuses it",
      _q.product_class == "assignment" and not _eligibility(_q)[0])
_r = _one(_node("AbCd1234", name="پراید ۱۳۱ فول بدون رنگ"))
check("X25: a condition the title states is read, and labelled as prose",
      (_r.body_condition, _r.condition_source) == ("intact", "description"))
check("X26: Persian and Latin digits on a card are the same numbers",
      _one(_node("AbCd1234"), _card("AbCd1234", lines=("120,000 km کیلومتر", "450,000,000 تومان")))
      .price_status == "display_confirmed")
_cards = read_cards(_card("AbCd1234", slug="%D9%BE%D8%B1%D8%A7%DB%8C%D8%AF-%DB%B1%DB%B3%DB%B1"))
check("X27: a percent-encoded Persian slug does not move the token",
      token_of(_cards[0].href) == "AbCd1234" and token_of("/s/tehran/car") is None
      and token_of("/v/gYx1Zq") == "gYx1Zq" and token_of("/v/") is None
      and token_of("/s/tehran/car/AbCd1234") is None, str(_cards[0].href))
_tr = PageTrace()
_pr = parse_divar_page(_page([_node("AbCd1234"), _node("EfGh5678")],
                             [_card("AbCd1234"), _card("ZzZz0000")]), _tr)
check("X28: a card with no node is not a listing, and a node with no card is",
      [x.listing_id for x in _pr] == ["AbCd1234", "EfGh5678"]
      and (_tr.cards_without_ld, _tr.ld_without_card) == (1, 1), str(_tr))
_tr = PageTrace()
_co = parse_divar_page(_page(None, [_card(t, title=f"پژو ۲۰۶ تیپ ۵ مدل ۹۶") for t in _T]), _tr)
check("X29: with no node at all the cards are read, and the price says it is the "
      "displayed one only",
      len(_co) == 3 and _tr.source == "cards"
      and (_co[0].asking_price_toman, _co[0].price_status, _co[0].price_provenance,
           _co[0].year_jalali) == (450_000_000, "displayed_only", "text", 1396)
      and _co[0].url == "https://divar.ir/v/pride/AbCd1234", str(_co[0]))
check("X30: nothing, an empty string and None are no listings and no exception",
      parse_divar_page(_page(None, [])) == [] and parse_divar_page("") == []
      and parse_divar_page(None) == [])
check("X31: a gearbox is read from English or Persian, else from the title",
      [_one(_node("AbCd1234", gear=g)).gearbox for g in ("Manual", "Automatic", "اتوماتیک")]
      == ["manual", "automatic", "automatic"]
      and _one(_node("AbCd1234", gear="???", name="پراید اتوماتیک")).gearbox == "automatic"
      and _one(_node("AbCd1234", gear="???")).gearbox is None)
_tr = PageTrace()
parse_divar_page(_page([_node("AbCd1234", extra={"owner_name": "رضایی"})],
                       [_card("AbCd1234")]), _tr)
check("X32: the counted values are those eight keys and no other, and a colour or a "
      "name is not among them",
      set(_tr.enums) == {"@type", "priceCurrency", "unitCode", "vehicleTransmission",
                         "knownVehicleDamages", "category", "brand", "model"}
      and _tr.enums["priceCurrency"] == {"IRR": 1} and _tr.enums["unitCode"] == {"KMT": 1}
      and "سفید" not in repr(_tr.enums) and "رضایی" not in repr(_tr.enums), str(_tr.enums))
check("X33: a damage field no one has seen the values of sets no condition",
      _one(_node("AbCd1234", extra={"knownVehicleDamages": "تصادفی"})).body_condition == "unknown")
_pp2 = DivarPageParser()
_x1 = _pp2(_page([_node("AbCd1234"), _node("EfGh5678")], []))
_x2 = _pp2(_page([_node("EfGh5678"), _node("IjKl9012")], []))
check("X34: a page served twice adds nothing, and the repeat is counted",
      [x.listing_id for x in _x1] == ["AbCd1234", "EfGh5678"]
      and [x.listing_id for x in _x2] == ["IjKl9012"]
      and _pp2.traces[1].duplicates == 1, str(_pp2.traces[1]))
_html_ok = _page([_node(t) for t in _T], [_card(t) for t in _T])
_ad = DivarCarAdapter(max_pages=1, page_fetcher=lambda u: (200, _html_ok),
                      parse_page=DivarPageParser(), salt="test-salt",
                      sleeper=lambda s: None, robots_fetcher=divar_robots)
_outs = list(_ad.fetch_all(date(2026, 10, 26)))
check("X35: through the adapter: OK outcomes named divar:<token>, no seller fingerprint",
      [o.listing_id for o in _outs] == [f"divar:{t}" for t in _T]
      and all(o.status is FetchStatus.OK and o.seller_fingerprint is None for o in _outs))
check("X36: the default category is the one that answered (/s/tehran/car); "
      "/s/tehran/light answered 404 on 2026-10-26",
      DivarCarAdapter().category == "car"
      and DivarCarAdapter(robots_fetcher=divar_robots,
                          sleeper=lambda s: None).search_url(1)
      == "https://divar.ir/s/tehran/car")
_trs = []
for _pgs in (_page([_node("AbCd1234"), _node("EfGh5678", price="450000000")],
                   [_card("AbCd1234", title="پراید خصوصی رضایی"), _card("EfGh5678")]),):
    _t = PageTrace()
    parse_divar_page(_pgs, _t)
    _trs.append(_t)
_rep = "\n".join(_dp.report(_trs))
check("X37: the report names each price code and each value counted, and no title",
      all(x in _rep for x in ("agree", "label_wrong", "IRR", "KMT", "Manual"))
      and "رضایی" not in _rep and "AbCd1234" not in _rep, _rep)
_cs = read_cards(_card("AbCd1234", classes="kt-post-card--outlined kt-post-card extra"))
check("C1: a card is found by its class, in whatever order the classes come",
      len(_cs) == 1 and _cs[0].href == "/v/pride/AbCd1234")
check("C2: a card with no link has no token and is skipped, counted",
      (lambda t: (parse_divar_page(_page([_node("AbCd1234")],
                                         ['<article class="kt-post-card"><h2 class="kt-post-card__title">x</h2></article>',
                                          _card("AbCd1234")]), t), t.skipped["card without a token"])[1])(PageTrace()) == 1)
_cs = read_cards(_card("AbCd1234", title="A & B", lines=("a", "b", "c")))
check("C3/C4: entities in a title are decoded, and every description line is kept in order",
      _cs[0].title == "A & B" and _cs[0].lines == ["a", "b", "c"]
      and _cs[0].bottom == "لحظاتی پیش در تهران" and _cs[0].tags == ["نردبان"], str(_cs))
_torn = ('<article class="kt-post-card"><a class="kt-post-card__action" href="/v/s/AbCd1234">'
         '<div class="kt-post-card__info"><h2 class="kt-post-card__title">اول</h2>'
         '<div class="kt-post-card__description">یک</article>'
         + _card("EfGh5678", title="دوم"))
_tc = read_cards(_torn)
check("an unclosed tag inside a card does not swallow the card after it",
      [(c.title, c.href.rsplit("/", 1)[-1]) for c in _tc]
      == [("اول", "AbCd1234"), ("دوم", "EfGh5678")], str(_tc))


print("\nfirst_run reads a Divar page, live (faked) and saved")


def _divar_world(html_by_page):
    asked = []

    def fetch(url):
        asked.append(url)
        if url.endswith("/robots.txt"):
            return divar_robots(url)
        return 200, html_by_page(url)
    return fetch, asked


_fr_args = _argparse.Namespace(source="divar", limit=10, categories=None, makes="",
                               seed=0, city="tehran", pages=2)
_fetch, _asked = _divar_world(lambda u: _html_ok)
with _tempfile.TemporaryDirectory() as _tmp:
    _old, _first_run.SNAPSHOT_DIR = _first_run.SNAPSHOT_DIR, _Path(_tmp)
    _out = _io.StringIO()
    try:
        with _contextlib.redirect_stdout(_out):
            _got, _spath = _first_run.collect(_fr_args, [], fetcher=_fetch,
                                              sleeper=lambda s: None)
        _snap = json.loads(_spath.read_text(encoding="utf-8"))
    finally:
        _first_run.SNAPSHOT_DIR = _old
check("first_run --source divar: the category page, then page 2, over plain HTTP",
      [u for u in _asked if "/s/" in u]
      == ["https://divar.ir/s/tehran/car", "https://divar.ir/s/tehran/car?page=2"],
      str(_asked))
check("  three listings, once, though page 2 served the same page again",
      len(_got) == 3 and len([o for o in _snap["outcomes"]
                              if o["listing_id"].startswith("divar:")]) == 3,
      str(len(_got)))
check("  the snapshot names the robots.txt it obeyed, and holds no vehicle number",
      any(n.startswith("robots.txt ") for n in _snap["notes"])
      and "9SECRETVIN0001" not in json.dumps(_snap, ensure_ascii=False))
check("  and the page report was printed, with the duplicates counted",
      "DIVAR PAGE READ" in _out.getvalue() and "duplicates" in _out.getvalue(),
      _out.getvalue()[-400:])

with _tempfile.TemporaryDirectory() as _tmp:
    _pf = _Path(_tmp) / "01-abc.html"
    _pf.write_text(_html_ok, encoding="utf-8")
    _out = _io.StringIO()
    _argv, _first_run.sys.argv = _first_run.sys.argv, ["first_run.py", "--page", str(_pf)]
    _salt = os.environ.pop("CARO_SELLER_SALT", None)
    try:
        with _contextlib.redirect_stdout(_out):
            _rc = _first_run.main()
    finally:
        _first_run.sys.argv = _argv
        if _salt is not None:
            os.environ["CARO_SELLER_SALT"] = _salt
    _left = [x for x in _Path(_tmp).rglob("*") if x != _pf]
check("first_run --page: offline, with no salt, writes nothing, prints the inventory "
      "and the report",
      _rc == 0 and "CORPUS INVENTORY  (3 listings)" in _out.getvalue()
      and "DIVAR PAGE READ" in _out.getvalue() and _left == [], _out.getvalue()[:300])


print("\na price under the floor is not an asking price")
_low = _one(_node("AbCd1234", price="50000000"),
            _card("AbCd1234", lines=("۱۲۰٬۰۰۰ کیلومتر", "۵٬۰۰۰٬۰۰۰ تومان")))
_ok, _why = _eligibility(_low)
check("Y4: 5,000,000 toman, confirmed by the card and with everything else sound, "
      "is not eligible, and the reason names the price",
      _low.asking_price_toman == 5_000_000 and not _ok
      and any("price is not an asking price" in w and "5,000,000" in w for w in _why),
      str((_ok, _why)))
_fine = _one(_node("AbCd1234"), _card("AbCd1234"))
check("  450,000,000 is eligible, and a missing price has the one reason it had",
      _eligibility(_fine) == (True, [])
      and _eligibility(_one(_node("AbCd1234", price=None), _card("AbCd1234",
                            lines=("۱۲۰٬۰۰۰ کیلومتر",))))[1].count("no asking_price_toman") == 1
      and not any("not an asking price" in w for w in _eligibility(
          _one(_node("AbCd1234", price=None), _card("AbCd1234", lines=("۱۲۰٬۰۰۰ کیلومتر",))))[1]))
check("Y5: the funnel of first_run holds it back and says why",
      any("price is not an asking price" in ln
          for ln in _first_run.funnel(2, [_low, _fine])), str(_first_run.funnel(2, [_low, _fine])))


print("\ndivar's damage field is the page's own body condition")


def _cond(value, name="پراید ۱۳۱ SE"):
    x = _one(_node("AbCd1234", name=name, extra={"knownVehicleDamages": value}))
    return x.body_condition, x.condition_source


check("Y1: the four values the first real page showed, mapped, and the source "
      "is the field",
      [_cond(v) for v in ("intact", "some-scratches", "some-paint", "half-paint")]
      == [("intact", "field"), ("minor_paint", "field"), ("minor_paint", "field"),
          ("multi_paint", "field")], str([_cond(v) for v in ("intact",)]))
check("  a value not seen is unknown with no source, and the report names it",
      _cond("full-paint") == ("unknown", "none")
      and any("full-paint:1" in ln and "⚠" in ln for ln in (lambda t: (
          parse_divar_page(_page([_node("AbCd1234", extra={"knownVehicleDamages": "full-paint"})],
                                 [_card("AbCd1234")]), t), _dp.report([t]))[1])(PageTrace())))
check("  and the seen values raise no such warning",
      not any("⚠ damage" in ln for ln in (lambda t: (
          parse_divar_page(_page([_node("AbCd1234", extra={"knownVehicleDamages": "intact"})],
                                 [_card("AbCd1234")]), t), _dp.report([t]))[1])(PageTrace())))
check("Y2: the worse claim wins: a title that says «تصادفی» over a field that says "
      "intact is an accident, from the prose",
      _cond("intact", "پراید ۱۳۱ تصادفی") == ("accident", "description"))
check("  and a field that says some-paint under a title that says «فول بدون رنگ» "
      "stays some-paint, from the field",
      _cond("some-paint", "پراید ۱۳۱ فول بدون رنگ") == ("minor_paint", "field"))
check("  the same claim twice is the field's",
      _cond("intact", "پراید ۱۳۱ فول بدون رنگ") == ("intact", "field"))
check("Y3: no field and «بدون رنگ» in the title is intact, from the prose; "
      "neither is unknown with no source",
      _cond(None, "پراید ۱۳۱ فول بدون رنگ") == ("intact", "description")
      and _cond(None) == ("unknown", "none"))


print("\ndivar's report: the odd cases as numbers, and the brand and the model")
_odd_nodes = [_node("AbCd1234", price="50000000"),                       # 5,000,000 toman
              _node("EfGh5678", year="1395", name="پراید ۱۳۱ مدل ۹۰"),    # 1395 vs 1390
              _node("IjKl9012", km="5")]                                  # 5 vs 120,000
_odd_cards = [_card("AbCd1234", lines=("۱۲۰٬۰۰۰ کیلومتر", "۵٬۰۰۰٬۰۰۰ تومان")),
              _card("EfGh5678", title="پراید ۱۳۱ مدل ۹۰"),
              _card("IjKl9012")]
_t = PageTrace()
parse_divar_page(_page(_odd_nodes, _odd_cards), _t)
_rep = "\n".join(_dp.report([_t]))
check("Y6: a price under the floor is printed as the figure, a year that differs "
      "as the pair, an odometer that disagrees as the pair",
      "odd cases (numbers only)" in _rep
      and "price below the floor" in _rep and "5,000,000" in _rep
      and "year differs" in _rep and "(1395, 1390)" in _rep
      and "odometer differs" in _rep and "(5, 120000)" in _rep, _rep)
check("  and no title, token or word of the page is among them",
      not any(x in _rep for x in ("مدل ۹۰", "AbCd1234", "EfGh5678", "پراید")))
_t = PageTrace()
parse_divar_page(_page([_node("AbCd1234")], [_card("AbCd1234")]), _t)
check("  a clean page prints no odd cases",
      "odd cases" not in "\n".join(_dp.report([_t])))
_t = PageTrace()
_many = [f"Tk{i:06d}" for i in range(15)]
parse_divar_page(_page([_node(k, price="50000000") for k in _many],
                       [_card(k, lines=("۱۲۰٬۰۰۰ کیلومتر", "۵٬۰۰۰٬۰۰۰ تومان")) for k in _many]), _t)
_rows = [ln for ln in _dp.report([_t]) if "price below the floor" in ln]
check("  at most twelve of a kind, then the count of the rest",
      len(_rows) == 13 and "… and 3 more" in _rows[-1], str(_rows))

_t = PageTrace()
parse_divar_page(_page([_node("AbCd1234", extra={"brand": {"@type": "Brand", "name": "Peugeot"},
                                                  "model": "206"}),
                        _node("EfGh5678", extra={"brand": {"@type": "Brand", "name": "Pars"},
                                                  "model": "09123456789"}),
                        _node("IjKl9012", extra={"brand": "a@b.example",
                                                  "model": "x" * 41})], []), _t)
check("Y7: «Peugeot» and «206» are counted; an eleven-digit string, an address and "
      "forty-one characters are not",
      _t.enums["brand"] == {"Peugeot": 1, "Pars": 1} and _t.enums["model"] == {"206": 1},
      str((_t.enums["brand"], _t.enums["model"])))
_t = PageTrace()
_ks = [f"K{i:06d}" for i in range(25)]
parse_divar_page(_page([_node(k, extra={"model": f"m{i}"}) for i, k in enumerate(_ks)], []), _t)
check("  twenty distinct values per key, and the rest are «(other)»",
      len(_t.enums["model"]) == 21 and _t.enums["model"]["(other)"] == 5,
      str(_t.enums["model"]))


print("\na number in prose is a price or an odometer only where the words say so")


def _pl(title, desc="", **kw):
    x = parse_listing("t", "https://divar.ir/v/t", title, desc, **kw)
    return x.asking_price_toman, x.mileage_km


check("A1: «پژو 206 تیپ 5» is neither a price of 206 toman nor an odometer of 206 km",
      _pl("پژو 206 تیپ 5") == (None, None) and _pl("۲۰۶ تیپ ۵ مدل ۹۶") == (None, None),
      str(_pl("پژو 206 تیپ 5")))
check("A2: «کارکرد ۸۰ هزار» is an odometer and not a price of 80,000",
      _pl("پراید ۱۳۱ مدل ۹۵", "کارکرد ۸۰ هزار") == (None, 80_000),
      str(_pl("پراید ۱۳۱ مدل ۹۵", "کارکرد ۸۰ هزار")))
check("A3: a price in prose: a scale word, or a long figure and a currency word",
      [_pl("پراید", d)[0] for d in (
          "۲۸۰ میلیون تومان", "۱ میلیارد و ۴۸۰ میلیون", "قیمت ۱٬۴۸۰٬۰۰۰٬۰۰۰ تومان",
          "پیش ۲۰٬۰۰۰ تومان قیمت ۸۵۰٬۰۰۰٬۰۰۰ تومان")]
      == [280_000_000, 1_480_000_000, 1_480_000_000, 850_000_000])
check("  six digits and «هزار» are no price",
      _pl("پراید", "۵۰۰٬۰۰۰ تومان")[0] is None and _pl("پراید", "۱۲۰ هزار تومان")[0] is None)
check("A4: an odometer in prose: next to «کارکرد» or «کیلومتر», or «صفر کیلومتر»",
      [_pl("پراید", d)[1] for d in (
          "کارکرد ۱۲۰٬۰۰۰ کیلومتر", "۸۰ هزار کیلومتر", "کارکرد ۸۰", "صفر کیلومتر",
          "کیلومتر ۴۵۰۰۰")] == [120_000, 80_000, 80_000, 0, 45_000])
check("A5: an explicit price_text and mileage_text are read as before, and win",
      _pl("پژو ۲۰۶", "۳۰۰ میلیون، کارکرد ۱۰ هزار", price_text="۲۸۰ میلیون",
          mileage_text="۱۲۰٬۰۰۰ کیلومتر") == (280_000_000, 120_000))


print("\nthe Divar adapter stops when a page adds nothing, and says why")


def _run_pages(pages, max_pages=5, parse=None):
    asked, slept_ = [], []

    def fetch(u):
        asked.append(u)
        return 200, pages(len(asked))
    ad_ = DivarCarAdapter(max_pages=max_pages, page_fetcher=fetch, parse_page=parse,
                          salt="test-salt", sleeper=slept_.append,
                          robots_fetcher=divar_robots)
    outs_ = list(ad_.fetch_all(date(2026, 10, 29)))
    return ad_, outs_, [u for u in asked if "/s/" in u], slept_


_three = _page([_node(t) for t in _T], [_card(t) for t in _T])
_n = {"i": 0}


def _then_empty(html):
    _n["i"] += 1
    return parse_divar_page(html) if _n["i"] == 1 else []


_n["i"] = 0
_ad, _outs, _reqs, _sl = _run_pages(lambda i: _three, parse=_then_empty)
check("B1: page 2 parses to nothing: three outcomes, two requests (not five), the "
      "reason named, and no wait after the stop",
      len(_outs) == 3 and len(_reqs) == 2 and _ad.stopped == "page 2 added no new listing"
      and len(_sl) == 2, str((len(_outs), _reqs, _ad.stopped, _sl)))   # robots' pause + 1->2
_ad, _outs, _reqs, _sl = _run_pages(lambda i: _three, parse=DivarPageParser())
check("B2: page 2 served as page 1 again, through the parser that remembers: the same",
      len(_outs) == 3 and len(_reqs) == 2 and _ad.stopped is not None, str(_reqs))
_k = {"i": 0}


def _fresh_each_page(html):
    _k["i"] += 1
    return [parse_listing(f"p{_k['i']}{j}", f"https://divar.ir/v/x/p{_k['i']}{j}x", "پراید", "",
                          price_text="۳۰۰ میلیون") for j in range(2)]


_ad, _outs, _reqs, _sl = _run_pages(lambda i: "<html>x</html>", parse=_fresh_each_page)
check("B3: pages that all yield are all requested, nothing is `stopped`, and the waits "
      "between them are as before",
      len(_reqs) == 5 and len(_outs) == 10 and _ad.stopped is None and len(_sl) == 5,
      str((len(_reqs), len(_outs), _ad.stopped, len(_sl))))
_ad4 = DivarCarAdapter(max_pages=10, page_fetcher=lambda u: (403, ""),
                       parse_page=parse_divar_page, sleeper=lambda s: None,
                       robots_fetcher=divar_robots)
_got4, _raised4 = [], False
try:
    for _o in _ad4.fetch_all(date(2026, 10, 29)):
        _got4.append(_o)
except SourceBlocked:
    _raised4 = True
check("B4: a 403 is still UNKNOWN three times and a SourceBlocked, and is not "
      "«added nothing»",
      _raised4 and len(_got4) == 3 and _ad4.stopped is None
      and all(o.status is FetchStatus.UNKNOWN for o in _got4))
_fr_args2 = _argparse.Namespace(source="divar", limit=10, categories=None, makes="",
                                seed=0, city="tehran", pages=5)
_fetch2, _asked2 = _divar_world(lambda u: _three)
with _tempfile.TemporaryDirectory() as _tmp:
    _old, _first_run.SNAPSHOT_DIR = _first_run.SNAPSHOT_DIR, _Path(_tmp)
    _out2 = _io.StringIO()
    try:
        with _contextlib.redirect_stdout(_out2):
            _first_run.collect(_fr_args2, [], fetcher=_fetch2, sleeper=lambda s: None)
    finally:
        _first_run.SNAPSHOT_DIR = _old
check("B5: first_run prints why it stopped early, and not when it did not",
      "stopped early: page 2 added no new listing" in _out2.getvalue()
      and len([u for u in _asked2 if "/s/" in u]) == 2)


print("\na counted value holds at most four digits in all")
_t = PageTrace()
_models = ["0912 345 6789", "0912-345-6789", "۰۹۱۲ ۳۴۵ ۶۷۸۹", "09 12 34 56 78", "12345",
           "206", "207i", "x70", "Pars", "Peugeot 206", "1234"]
parse_divar_page(_page([_node(f"Tk{i:06d}", extra={"model": m}) for i, m in enumerate(_models)], []), _t)
check("H1: a telephone number with separators, in any script, and five digits are not "
      "counted; «206», «207i», «x70», «Pars», «Peugeot 206» and four digits are",
      set(_t.enums["model"]) == {"206", "207i", "x70", "Pars", "Peugeot 206", "1234"},
      str(set(_t.enums["model"])))
check("  and none of them is in the report",
      not any(x in "\n".join(_dp.report([_t])) for x in ("0912", "۰۹۱۲", "12345", "09 12")))


print("\nthe Divar reader meets pages of any shape and does not crash")
import copy as _copy
import random as _random
_rnd = _random.Random(7)
_WEIRD = [None, 0, -1, 1.5, True, "", " ", "x" * 500, [], {}, [None], {"a": 1}, "۱۲۳", "9" * 40,
          ["a", 1], {"value": None}, {"value": "abc"}, {"value": [1]}, 1e30, "NaN", "\u0000"]
_KEYS = ["name", "productionDate", "vehicleModelDate", "mileageFromOdometer", "color", "model",
         "vehicleTransmission", "knownVehicleDamages", "url", "offers", "web_info", "brand",
         "category", "@type", "image", "vehicleIdentificationNumber"]
_LINES = ["۱۲۰٬۰۰۰ کیلومتر", "۴۵۰٬۰۰۰٬۰۰۰ تومان", "توافقی", "", "x", "۹۹۹۹۹۹۹۹۹۹۹۹ تومان",
          "پیش‌پرداخت ۱ تومان"]


def _fuzz_node(n):
    n = _copy.deepcopy(n)
    for _ in range(_rnd.randint(1, 4)):
        k = _rnd.choice(_KEYS)
        r = _rnd.random()
        if r < 0.15 and k in n:
            del n[k]
        elif r < 0.6 or not isinstance(n.get(k), dict) or not n[k]:
            n[k] = _copy.deepcopy(_rnd.choice(_WEIRD))
        else:
            n[k][_rnd.choice(list(n[k]))] = _copy.deepcopy(_rnd.choice(_WEIRD))
    return n


_crashes, _read = [], 0
_tk = [f"Tk{i:06d}" for i in range(6)]
for _it in range(400):
    _pg = _page([_fuzz_node(_node(t)) if _rnd.random() < 0.8 else _node(t) for t in _tk],
                [_card(t, lines=tuple(_rnd.choice(_LINES) for _ in range(_rnd.randint(0, 4))))
                 for t in _tk if _rnd.random() < 0.8])
    if _rnd.random() < 0.3:
        _pg = _pg[:_rnd.randint(0, len(_pg))]
    elif _rnd.random() < 0.3:
        _i = _rnd.randint(0, len(_pg) - 1)
        _pg = _pg[:_i] + _pg[_i + _rnd.randint(1, 50):]
    try:
        _tr = PageTrace()
        for _x in parse_divar_page(_pg, _tr):
            _x.to_fetch_outcome("divar", "s")
        _dp.report([_tr])
        _read += 1
    except Exception as _e:                          # noqa: BLE001
        _crashes.append(f"{type(_e).__name__}: {_e}")
check("400 pages, each with 1 to 4 fields of 6 vehicles set to a value of the wrong type, "
      "some cut or torn: none raises, in the reader, in the outcome or in the report",
      not _crashes and _read == 400, str(_crashes[:2]))


print("\nfirst_run --replay reads a snapshot, so the loop closes")


def _replay(path_or_obj):
    """first_run.main() on --replay; its stdout and return code."""
    with _tempfile.TemporaryDirectory() as tmp:
        f = _Path(tmp) / "snap.json"
        f.write_text(path_or_obj if isinstance(path_or_obj, str)
                     else json.dumps(path_or_obj, ensure_ascii=False), encoding="utf-8")
        argv, _first_run.sys.argv = _first_run.sys.argv, ["first_run.py", "--replay", str(f)]
        out = _io.StringIO()
        try:
            with _contextlib.redirect_stdout(out):
                rc = _first_run.main()
        finally:
            _first_run.sys.argv = argv
    return rc, out.getvalue()


_fetch3, _ = _divar_world(lambda u: _three)
with _tempfile.TemporaryDirectory() as _tmp:
    _old, _first_run.SNAPSHOT_DIR = _first_run.SNAPSHOT_DIR, _Path(_tmp)
    _live = _io.StringIO()
    try:
        with _contextlib.redirect_stdout(_live):
            _lst, _sp = _first_run.collect(_fr_args, [], fetcher=_fetch3, sleeper=lambda s: None)
            print(_first_run.inventory(_lst, None, fetched=len(_lst)))
        _snap_text = _sp.read_text(encoding="utf-8")
    finally:
        _first_run.SNAPSHOT_DIR = _old
_rc, _txt = _replay(_snap_text)
check("R1: a snapshot the Divar collect wrote replays as its listings",
      _rc == 0 and "replayed 3 listings" in _txt and "CORPUS INVENTORY  (3 listings)" in _txt,
      _txt[:200])
_snap_obj = json.loads(_snap_text)
_snap_obj["outcomes"].append({"listing_id": "__page__:divar:2", "status": "unknown", "http_status": 403})
_rc, _txt = _replay(_snap_obj)
check("R2: a record of a page that did not answer is a fetch and not a listing",
      "replayed 3 listings" in _txt, _txt[:120])
_rows = lambda t: [ln for ln in t.splitlines()
                   if ln.split(" ")[0] in ("asking_price_toman", "year_jalali", "mileage_km", "make",
                                           "model", "trim", "gearbox", "fuel", "color", "body_condition")]
check("R3: the field rates of the replay are the ones printed at collection",
      _rows(_txt) == _rows(_live.getvalue()) and len(_rows(_txt)) == 10,
      str((_rows(_txt)[:2], _rows(_live.getvalue())[:2])))
_rc, _txt = _replay({"listings": [{"listing_id": "a1", "url": "https://divar.ir/v/a1",
                                    "title": "پراید ۱۳۱ مدل ۹۵", "description": "کارکرد ۲۱۰ هزار",
                                    "price_text": "۲۸۰ میلیون"}]})
check("R4: the older file, with a top-level listings, replays as before",
      _rc == 0 and "replayed 1 listings" in _txt)
_rc, _txt = _replay({"nothing": 1})
check("R5: a file with neither key replays as nothing, and does not raise",
      _rc == 0 and "replayed 0 listings" in _txt and "nothing to report" in _txt, _txt[:120])


print("\nan odometer the node gives in thousands and the card in km")
_th = _one(_node("AbCd1234", km="280"), _card("AbCd1234", lines=("۲۸۰٬۰۰۰ کیلومتر", "۴۵۰٬۰۰۰٬۰۰۰ تومان")))
_t = PageTrace()
parse_divar_page(_page([_node("AbCd1234", km="280")], [_card("AbCd1234", lines=("۲۸۰٬۰۰۰ کیلومتر", "۴۵۰٬۰۰۰٬۰۰۰ تومان"))]), _t)
check("J1: the node says 280 and the card 280,000: the card's km is used, and the code says so",
      _th.mileage_km == 280_000 and _t.mileage["ld_in_thousands"] == 1 and not _t.odd["odometer differs"],
      str((_th.mileage_km, dict(_t.mileage))))
check("  the card's rounding to thousands is allowed here too (119 against «۱۲۰ هزار»)",
      _one(_node("AbCd1234", km="119"), _card("AbCd1234", lines=("۱۲۰ هزار کیلومتر", "۴۵۰٬۰۰۰٬۰۰۰ تومان"))).mileage_km == 120_000)
_t = PageTrace()
_zero = parse_divar_page(_page([_node("AbCd1234", km="0")], [_card("AbCd1234")]), _t)[0]
check("  but 0 against 120,000 and 5 against 120,000 are still no odometer",
      _zero.mileage_km is None and _t.mileage["disagree"] == 1
      and _one(_node("AbCd1234", km="5"), _card("AbCd1234")).mileage_km is None)
check("  and a node that already agrees in km is not read as thousands",
      _one(_node("AbCd1234", km="120000"), _card("AbCd1234")).mileage_km == 120_000)


print("\ntwo years that differ by two or more are no year")
_yt = PageTrace()
_ys = parse_divar_page(_page([_node("AbCd1234", year="1405", name="پژو ۲۰۶ مدل ۸۵"),
                              _node("EfGh5678", year="1405", name="پژو ۲۰۶ مدل ۶۰"),
                              _node("IjKl9012", year="1404", name="پژو ۲۰۶ مدل ۱۴۰۵"),
                              _node("MnOp3456", year="1399", name="پژو ۲۰۶ مدل ۹۹")], []), _yt)
check("J2: the node's 1405 against a title's 85 or 60 is no year; 1404 against 1405 is the "
      "node's; equal is equal; the counts say which",
      [x.year_jalali for x in _ys] == [None, None, 1404, 1399]
      and (_yt.year["differ_far"], _yt.year["differ_near"], _yt.year["agree"]) == (2, 1, 1),
      str(([x.year_jalali for x in _ys], dict(_yt.year))))
check("  a listing with no year is held back by the gate, with that reason",
      "no year_jalali" in _eligibility(_ys[0])[1] and not _eligibility(_ys[0])[0])
check("  the pair is printed as numbers: (1405, 1385) and (1405, 1360), and (1404, 1405)",
      all(x in "\n".join(_dp.report([_yt])) for x in ("(1405, 1385)", "(1405, 1360)", "(1404, 1405)")))
check("  exactly two apart is no year too, and the pair is still printed",
      _one(_node("AbCd1234", year="1403", name="پژو ۲۰۶ مدل ۱۴۰۵")).year_jalali is None)
check("  a node with no title year keeps its year, and a title with no node year keeps its",
      _one(_node("AbCd1234", year="1405", name="پژو")).year_jalali == 1405
      and _one(_node("AbCd1234", year=None, name="پژو ۲۰۶ مدل ۸۵")).year_jalali == 1385)
_yf = PageTrace()
parse_divar_page(_page([_node("AbCd1234", extra={"vehicleModelDate": "1385", "productionDate": "1405"}),
                        _node("EfGh5678", extra={"vehicleModelDate": "1399", "productionDate": "1399"})], []), _yf)
_yg = PageTrace()
parse_divar_page(_page([_node("AbCd1234", year=None, extra={"vehicleModelDate": "1385"})], []), _yg)
check("J3: a node with one year field only lists no pair",
      _yg.odd["year fields differ"] == [])
check("J3: a node whose two year fields differ is listed as the pair (model date, production date)",
      _yf.odd["year fields differ"] == [(1385, 1405)]
      and "year fields differ" in "\n".join(_dp.report([_yf])) and "(1385, 1405)" in "\n".join(_dp.report([_yf])))


print("\nthe report says how many values it did not count, and why")
_tn = PageTrace()
parse_divar_page(_page([
    _node("Tk000001", extra={"brand": {"@type": "Brand", "name": ""}, "model": "x" * 41}),
    _node("Tk000002", extra={"brand": {"@type": "Brand", "name": "a@b.example"}, "model": "0912 345 6789"}),
    _node("Tk000003", extra={"brand": None, "model": "206"}),
    _node("Tk000004", extra={"brand": {"@type": "Brand", "name": "Gac"}, "model": "Gac Emkoo"})], []), _tn)
_rep_n = "\n".join(_dp.report([_tn]))
check("J4: empty, longer than forty, an address, more than four digits and absent are named, "
      "with a count each, and only those words",
      all(x in _rep_n for x in ("brand: empty 1", "model: long 1", "brand: address 1",
                                "model: digits 1", "brand: absent 1"))
      and "a@b.example" not in _rep_n and "0912" not in _rep_n, _rep_n)
_tn = PageTrace()
parse_divar_page(_page([_node("Tk000001")], []), _tn)
check("  a page whose values are all counted lists none of the first four reasons",
      not any(f"{k}: {w}" in "\n".join(_dp.report([_tn])) for k in ("brand", "model")
              for w in ("empty", "long", "address", "digits")))

print("\nmake and model from the page's own brand and model, where the table has nothing")
_sm = lambda b, m, name="سواری": _one(_node("AbCd1234", name=name,
                                            extra={"brand": {"@type": "Brand", "name": b}, "model": m}))
check("J5: «Gac» under «Gac Emkoo Hybrid 2.0L Pro» is (Gac, Emkoo); «Lamari ECHO 1.5 Turbo» "
      "(Lamari, ECHO); «Fownix Fx Premium-normal» (Fownix, Fx)",
      [(x.make, x.model) for x in (_sm("Gac", "Gac Emkoo Hybrid 2.0L Pro"),
                                    _sm("Lamari", "Lamari ECHO 1.5 Turbo"),
                                    _sm("Fownix", "Fownix Fx Premium-normal"))]
      == [("Gac", "Emkoo"), ("Lamari", "ECHO"), ("Fownix", "Fx")])
check("  a word the table knows for that make is its canonical one: «207i» is 207, «Pars» is Pars",
      [(x.make, x.model) for x in (_sm("Peugeot", "Peugeot 207i Automatic TU5P"),
                                    _sm("Peugeot", "Peugeot Pars latest"))]
      == [("Peugeot", "207"), ("Peugeot", "Pars")])
check("  a model that does not begin with the brand's name is taken from its first word",
      (lambda x: (x.make, x.model))(_sm("Gac", "Emkoo Hybrid")) == ("Gac", "Emkoo"))
check("  the table wins where it matches: a title that says «پراید» is Saipa Pride, "
      "whatever the page's brand says",
      (lambda x: (x.make, x.model))(_sm("Gac", "Gac Emkoo", name="پراید ۱۳۱ SE")) == ("Saipa", "Pride"))
check("  a brand that is a model of the table's («Pride», «Saina», «Tara») is left to the table, "
      "and with no title match it stays unread",
      [(x.make, x.model) for x in (_sm("Pride", "Pride Saba GLXI"), _sm("Saina", "Saina manual S"),
                                    _sm("Tara", "Tara"))] == [(None, None)] * 3)
check("  no brand, an empty one, no model, a word of forty-one characters or a telephone number: unread",
      [(x.make, x.model) for x in (
          _one(_node("AbCd1234", name="سواری", extra={"brand": None, "model": "Gac Emkoo"})),
          _sm("", "Emkoo"), _sm("Gac", ""), _sm("Gac", "Gac " + "x" * 41),
          _sm("Gac", "Gac 0912 345 6789"))] == [(None, None)] * 5)
check("  and the listing is eligible for a model it only has from the page",
      "no model" not in " ".join(_eligibility(_sm("Gac", "Gac Emkoo Hybrid"))[1]))


print("\npage_probe --survey: one answer for a page nobody has read")
_SV_VEHICLES = [{
    "@type": "Car", "title": "پراید ۱۳۱ تیپ " + str(i), "offers": {"price": str(4500000000 + i * 10), "priceCurrency": "IRR"},
    "mileageFromOdometer": {"value": "120000", "unitCode": "KMT"},
    "damage": ["intact", "some-paint", "half-paint"][i % 3],
    "web_info": {"city_persian": "تهران", "title": f"عنوان آگهی شماره {i}"},
    "contactPoint": {"email": f"seller{i}@example.test"} if i < 5 else {"email": ""},
    "seller": {"name": "Rezaei" if i < 5 else "", "phone": "0912 345 6789" if i < 5 else ""},
    "token": f"Tk{i:06d}x", "rare": "once" if i == 0 else "a" + str(i)[:1] * (i % 4 + 1)} for i in range(24)]
_SV_PAGE = ("<html><head><link rel='next' href='/s/tehran/car?page=2'>"
            "<script type='application/ld+json'>" + json.dumps(_SV_VEHICLES, ensure_ascii=False)
            + "</script></head><body><a href='/s/tehran/car?page=2'>2</a><a href='/s/tehran/car?p=3&q9=1'>3</a>"
            + _PP_CARDS + "</body></html>")
_SV = _pp.survey(_SV_PAGE, name="p.html")
_order = [_SV.find(x) for x in ("# skeleton of", "# pagination hints", "# rows of", "# scripts of", "# values of")]
check("S1: the survey holds the links, the pagination hints, the rows, the scripts and the values, in that order",
      all(i >= 0 for i in _order) and _order == sorted(_order), str(_order))
check("S2: the categories are printed under their paths: the currency, the unit, the three slugs, the city",
      all(x in _SV for x in ("priceCurrency: IRR:24", "unitCode: KMT:24", "intact:8",
                             "some-paint:8", "half-paint:8", "city_persian: تهران:24")), _SV[-900:])
check("S3: no title, price, email, phone or seller name is printed; nor a Persian text under a key that "
      "names no kind of thing; nor a path of many values",
      not any(x in _SV for x in ("عنوان آگهی", "4500000010", "seller0@", "0912", "Rezaei", "پراید ۱۳۱ تیپ",
                                 "Tk000001x", "once")), _SV)
_vals = _SV[_SV.index("# values of"):]
check("  a value used fewer than three times, or a path of more than twelve, is not printed",
      "once" not in _vals and "token" not in _vals)
_pg = _pp.pagination_hints(_SV_PAGE)
check("S4: the pagination hints name the parameters, with counts, and rel=next, and no value of a parameter "
      "(the page number in the rel=next target is the one value kept: Q4)",
      "page:" in _pg and "p:" in _pg and "q9:" in _pg and "next:" in _pg
      and "=2" not in _pg.split("rel targets")[0] and "q9=" not in _pg, _pg)
check("S5: the survey is deterministic and holds no raw price, id or phone",
      _pp.survey(_SV_PAGE, name="p.html") == _SV and "4500000010" not in _SV and "Tk0000" not in _SV)
with _tempfile.TemporaryDirectory() as _tmp:
    _f = _Path(_tmp) / "p.html"
    _f.write_text(_SV_PAGE, encoding="utf-8")
    _out = _io.StringIO()
    with _contextlib.redirect_stdout(_out):
        _rc = _pp.main(["--survey", str(_f)])
check("S6: --survey FILE prints it on the command line with no network and exits 0",
      _rc == 0 and "# values of" in _out.getvalue() and "# pagination hints" in _out.getvalue())

_real_probe, _real_http = _pp.probe, _pp.http_fetcher
_pp.probe = lambda *a, **k: _real_probe(*a, **k, sleeper=lambda s: None)
_pp.http_fetcher = lambda policy=None: (lambda u: (200, "User-agent: *\nDisallow: /private\n")
                                         if u.endswith("/robots.txt") else (200, _SV_PAGE))
try:
    with _tempfile.TemporaryDirectory() as _tmp:
        _out = _io.StringIO()
        with _contextlib.redirect_stdout(_out):
            _rc = _pp.main(["--source", "shop", "--origin", "https://shop.example",
                            "--url", "https://shop.example/cars", "--out", _tmp])
finally:
    _pp.probe, _pp.http_fetcher = _real_probe, _real_http
check("S6: the end of a probe tells the owner to run --survey, and not three views",
      _rc == 0 and "page_probe.py --survey " in _out.getvalue()
      and "--rows " not in _out.getvalue() and "--scripts " not in _out.getvalue(),
      _out.getvalue()[-400:])


print("\nfirst_run --page reads several pages with one memory of the tokens")


def _pages_run(*pages):
    with _tempfile.TemporaryDirectory() as tmp:
        files = []
        for i, html_ in enumerate(pages):
            f = _Path(tmp) / f"0{i}.html"
            f.write_text(html_, encoding="utf-8")
            files.append(str(f))
        argv, _first_run.sys.argv = _first_run.sys.argv, ["first_run.py", "--page", *files]
        out = _io.StringIO()
        try:
            with _contextlib.redirect_stdout(out):
                rc = _first_run.main()
        finally:
            _first_run.sys.argv = argv
    return rc, out.getvalue()


_p2 = _page([_node(t) for t in ("Zz000001", "Zz000002")], [_card(t) for t in ("Zz000001", "Zz000002")])
_rc, _txt = _pages_run(_three, _three)
check("M1: a page given twice adds nothing: 3 listings in all, and the repeats are counted",
      _rc == 0 and "read 3 listing(s) from 2 pages" in _txt and "page 2 of 2: 0 new, 3 repeated" in _txt
      and "pages 2" in _txt and "duplicates" in _txt, _txt[:300])
_rc, _txt = _pages_run(_three, _p2)
check("M2: two different pages of 3 and 2: 5 in all, none repeated",
      "read 5 listing(s) from 2 pages" in _txt and "page 2 of 2: 2 new, 0 repeated" in _txt, _txt[:200])
_rc, _txt = _pages_run(_three)
check("M3: one page prints what it did: the line naming the file, and no per-page line",
      "read 3 listing(s) from /" in _txt and "page 1 of" not in _txt, _txt[:120])


print("\npage_probe reads a Next.js page's data stream, and the browser can be waited for")
_cars = [{"id": f"c{i}", "title": f"پراید ۱۳۱ شمارهٔ {i}", "price": 4500000000 + i, "city": "تهران",
          "brand": "Pride", "status": "available", "phone": "0912 345 6789", "seller_name": "Rezaei"}
         for i in range(5)]
_row0 = '0:["$","$L1",null,{"children":["$","div",null,{"cars":' + json.dumps(_cars, ensure_ascii=False) + ',"pad":"' + "z" * 200 + '"}]}]\n'
_row1 = '1:I["chunks/main.js",[],"default"]\n'
_cut = len(_row0) // 2
_push = lambda chunk: "self.__next_f.push([1," + json.dumps(chunk, ensure_ascii=False) + "])"
_RSC_PAGE = ("<html><body><script>" + _push(_row0[:_cut]) + "</script><script>"
             + _push(_row0[_cut:] + _row1 + "x" * 300) + "</script></body></html>")
_texts = [_push(_row0[:_cut]), _push(_row0[_cut:] + _row1)]
_rows, _n, _size = _pp.rsc_rows(_texts)
check("R1: the pushes are joined, a row cut between two is whole, and the module row is not JSON",
      _n == 2 and len(_rows) == 1 and _rows[0][3]["children"][3]["cars"][4]["id"] == "c4",
      str((_n, len(_rows))))
from caro.ingest import nextjs as _nx
check("K0: the reader is caro/ingest/nextjs.py's, and the probe uses that one",
      _pp.rsc_rows is _nx.rsc_rows and _nx.page_rows(_RSC_PAGE) == _rows)
check("  inline_scripts reads the two pushes and no external script; a page without one has no rows",
      _nx.inline_scripts("<html><script src='a.js'></script>" + _RSC_PAGE[6:]) == _nx.inline_scripts(_RSC_PAGE)
      and len(_nx.inline_scripts(_RSC_PAGE)) == 2 and _nx.page_rows("<html><p>x</p></html>") == []
      and _nx.page_rows("") == [], str(len(_nx.inline_scripts(_RSC_PAGE))))
_sc = _pp.scripts_report(_RSC_PAGE)
check("R2: the scripts view says once what the stream is, and does not call each push «not JSON»",
      "Next.js data stream (self.__next_f.push): 2 script(s)" in _sc and "1 JSON row(s)" in _sc
      and "not JSON" not in _sc, _sc)
_dl = _pp.data_lists_report(_RSC_PAGE, name="p.html")
check("R3: the list of five cars is found, with its shape and its categories",
      "5 objects, 8 keys in common" in _dl and "price: int" in _dl and "title: fa-text" in _dl
      and "brand: Pride:5" in _dl and "city: تهران:5" in _dl and "status: available:5" in _dl, _dl)
check("R4: no title, price, phone or seller name is in it, nor in the survey",
      not any(x in (_dl + _pp.survey(_RSC_PAGE)) for x in ("0912", "Rezaei", "پراید ۱۳۱", "4500000001", "4500000003", "c4")),
      _dl)
check("  and a page with no such list says so",
      "(none)" in _pp.data_lists_report("<html><body><p>x</p></body></html>"))
_seen = {}
_real_pw = _pp.playwright_fetcher
_pp.playwright_fetcher = lambda policy=None, wait_ms=1500: (_seen.update(wait=wait_ms)
                                                             or (lambda u: (200, _RSC_PAGE)))
_real_probe2 = _pp.probe
_pp.probe = lambda *a, **k: _real_probe2(*a, **k, sleeper=lambda s: None)
_real_http2 = _pp.http_fetcher
_pp.http_fetcher = lambda policy=None: (lambda u: (200, "User-agent: *\nDisallow: /private\n"))
for _mod in ("playwright", "playwright.sync_api"):
    sys_modules = __import__("sys").modules
    sys_modules.setdefault(_mod, type(__import__("sys"))(_mod))
try:
    with _tempfile.TemporaryDirectory() as _tmp:
        _o = _io.StringIO()
        with _contextlib.redirect_stdout(_o):
            _rc7 = _pp.main(["--source", "shop", "--origin", "https://shop.example", "--url",
                             "https://shop.example/cars", "--render", "browser", "--wait", "7", "--out", _tmp])
        _w7 = _seen.get("wait")
        _refused = []
        for _bad in ("0.1", "31"):
            try:
                with _contextlib.redirect_stderr(_io.StringIO()):
                    _pp.main(["--source", "shop", "--origin", "https://shop.example", "--url",
                              "https://shop.example/cars", "--render", "browser", "--wait", _bad,
                              "--out", _tmp])
                _refused.append(False)
            except SystemExit as _e:
                _refused.append(_e.code == 2)
        _seen.clear()
        with _contextlib.redirect_stdout(_io.StringIO()):
            _pp.main(["--source", "shop", "--origin", "https://shop.example", "--url",
                      "https://shop.example/cars", "--render", "browser", "--out", _tmp + "/b"])
finally:
    _pp.playwright_fetcher, _pp.probe, _pp.http_fetcher = _real_pw, _real_probe2, _real_http2
check("R5: --wait 7 reaches the browser fetcher as 7000 ms; 0.1 and 31 are refused; the default is 1500",
      _rc7 == 0 and _w7 == 7000 and _refused == [True, True] and _seen.get("wait") == 1500,
      str((_rc7, _w7, _refused, _seen)))


print("\npage_probe shows numbers, booleans, what sits beside a list, and the markup around a link")
_kh = [{"slug": f"car-{i}-x", "active": True, "guaranteed": i % 3 == 0, "price_type": [1, 2][i % 2],
        "price": 1250000000 + i * 1000000, "final_price": "1200000000", "views": 100 + i * 7,
        "image": {"count": i % 2 + 5}, "page": 40 + i, "message": 50 + i, "identifier": 770000 + i,
        "token": 910000 + i, "number": 880000 + i,
        "car_specifications": {"klm": 50000 + i * 1000, "document": None},
        "car_properties": {"year": "1403" if i % 4 else "2017", "brand": {"title_en": "Peugeot"}},
        "city": {"title_en": "Tehran"}, "phone": 9123456789 + i, "seller": {"name": "Rezaei", "price": 111111 + i,
                                                                             "mobile": 9120000000 + i}}
       for i in range(12)]
_kh_state = {"queries": [{"queryKey": ["cars", {"page": 1}], "state": {"status": "success", "data": {
    "pages": [{"count": 4817, "title": "فهرست خودروهای دست دوم", "owner_name": "Rezaei",
               "next": "https://khodro45.example/api/cars/?page=2&city=tehran&cursor=AbCdEfGhIjKl&q=%D8%B3",
               "previous": None, "results": _kh}], "pageParams": [1]}}}]}
_kh_row = "5:" + json.dumps({"children": ["$", "div", None, {"dehydratedState": _kh_state}]}, ensure_ascii=False) + "\n"
_KH_PAGE = ("<html><head><link rel='next' href='/buy-car/?page_num=2&amp;q=AbCdEfGhIjKl&amp;sort=new'>"
            "<link rel=prev href=\"/buy-car/\"><link rel=\"next\" href=\"/buy-car/?page_num=2&amp;q=AbCdEfGhIjKl&amp;sort=new\">"
            "</head><body><script>" + _push(_kh_row) + "</script></body></html>")
_KH_DL = _pp.data_lists_report(_KH_PAGE, name="k.html")
_KH_V = _pp.values_report(_KH_PAGE, name="k.html")
check("Q1: a boolean and a small integer are categories: true:12, false:8 / true:4, 1:6  2:6; views (12 values) is none",
      "active: true:12" in _KH_DL and "guaranteed: false:8  true:4" in _KH_DL and "price_type: 1:6  2:6" in _KH_DL
      and "car_specifications.document: null:12" in _KH_DL
      and "    views: " not in _KH_DL.split("  categories:")[1].split("  quantities")[0], _KH_DL)
check("Q2: a price, a mileage and a year have a summary: count, distinct, smallest, middle, largest; "
      "a digit string is a number",
      "price: n=12 distinct=12 min=1250000000 median=1256000000 max=1261000000 zero=0" in _KH_DL
      and "car_specifications.klm: n=12 distinct=12 min=50000 median=56000 max=61000 zero=0" in _KH_DL
      and "car_properties.year: n=12 distinct=2 min=1403 median=1403 max=2017 zero=0" in _KH_DL
      and "final_price: n=12 distinct=1 min=1200000000 median=1200000000 max=1200000000 zero=0" in _KH_DL,
      _KH_DL)
check("  an id, a token, a number, a phone, a person's price, and the words image / page / message "
      "have no summary, nor does a list of two",
      not any(f"    {x}: n=" in _KH_DL for x in ("identifier", "token", "number", "phone", "seller.price",
                                                 "seller.mobile", "message", "page"))
      and "n=12 distinct=12 min=770000" not in _KH_DL and "111111" not in _KH_DL and "9123456789" not in _KH_DL
      and "message: n=" not in _KH_V and "page: n=" not in _KH_V, _KH_DL)
_two = ("<html><body><script type='application/ld+json'>" + json.dumps(
    {"pad": "z" * 400, "offers": [{"price": 1}, {"price": 2}], "more": [{"price": 5}, {"price": 6}, {"price": 7}]})
        + "</script></body></html>")
check("  a path with two numbers has none, and one with three has (the same script: it is read)",
      "more[].price: n=3 distinct=3 min=5 median=6 max=7 zero=0" in _pp.values_report(_two)
      and "offers" not in _pp.values_report(_two).split("# quantities")[1], _pp.values_report(_two))
check("Q3: beside the list: the total, the next page's path and the NAMES of its parameters "
      "(a page number kept, an id not), a null; no title, no name",
      "count: int = 4817" in _KH_DL and "previous: null = null" in _KH_DL
      and "next: url = /api/cars/?page=2&city=tehran&cursor=…&q=…" in _KH_DL
      and "فهرست" not in _KH_DL and "owner_name: str" in _KH_DL and "Rezaei" not in _KH_DL,
      _KH_DL[:700])
check("  a list with nothing beside it has no such line",
      "beside the list" not in _pp.data_lists_report(
          "<html><body><script type='application/ld+json'>" + json.dumps(_kh[:4]) + "</script></body></html>"))
_pg2 = _pp.pagination_hints(_KH_PAGE)
check("Q4: rel=next / rel=prev show their path and parameter names; a page number kept, an id not; "
      "the same target once",
      "next -> /buy-car/?page_num=2&q=…&sort=new" in _pg2 and "prev -> /buy-car/" in _pg2
      and _pg2.count("next -> ") == 1 and "AbCdEf" not in _pg2, _pg2)

_SP_CARDS = (
    '<div class="list"><div class="card"><a href="/v/pride-131/AbCd1234Ef"><img src="a.jpg"><span>پراید ۱۳۱ مدل ۱۳۹۰</span></a>'
    '<div class="price">۱۲۰ میلیون تومان</div></div>'
    '<div class="card promoted"><a href="/v/peugeot-206/GhIj5678Kl"><img src="b.jpg"><img src="c.jpg"><span>پژو ۲۰۶</span></a>'
    '<span class="badge">نردبان</span><div class="price">۲۵۰ میلیون تومان</div><div class="place">تهران</div></div>'
    '<div class="card"><a href="/v/samand/MnOp9012Qr"><span>سمند</span></a><div class="price">توافقی</div></div>'
    '<div class="card"><a href="/v/tiba/StUv3456Wx"><img src="d.jpg"></a><p>تیبا</p><p class="price">۹۰ میلیون</p>'
    '<p class="place">کرج</p><i class="icon"></i></div>'
    '<a href="tel:09123456789">0912 345 6789</a><a href="/s/iran/car">همه</a></div>')
_SP_PAGE = "<html><body>" + _SP_CARDS + "</body></html>"
_rw = _pp.rows(_SP_PAGE, name="s.html")
_ar = _pp.around(_SP_PAGE, "/v/", up=1, name="s.html")
check("Q5: cards that differ in shape: `rows` finds none, `around` prints the first two with where they sit",
      "# none found" in _rw and "4 link(s), 4 different parent(s) 1 level(s) up, 4 different shape(s)" in _ar
      and _ar.count("# parent ") == 2 and "div .card\n" in _ar and "div .card .promoted\n" in _ar
      and "img [src=….jpg]  ×2" in _ar and "under: html > body > div.list" in _ar and "# parent 3" not in _ar
      and "تیبا" not in _ar, _ar)
_a0, _a8 = _pp.around(_SP_PAGE, "/v/", up=0), _pp.around(_SP_PAGE, "/v/", up=8)
check("  --up 0 is the link itself, and 8 climbs to the page's root and no further",
      _a0.splitlines()[2] == "a [href=/v/<tok>/<tok>]" and "4 different parent(s) 0 level(s) up" in _a0
      and "1 different parent(s) 8 level(s) up" in _a8 and _a8.splitlines()[2].startswith("html"), _a0 + _a8[:300])
check("  no link with that prefix: it says so",
      "0 link(s)" in _pp.around(_SP_PAGE, "/x/") and "# none found" in _pp.around(_SP_PAGE, "/x/"))
_ar_t = _pp.around(_SP_PAGE, "/v/", up=1)
check("Q6: texts as `rows` shows them: 40 characters, every digit «#»; tel: is not a link under «/»",
      "پراید ###" not in _ar_t and "پراید # مدل #" in _ar_t and "# میلیون تومان" in _ar_t
      and "4 link(s)" in _pp.around(_SP_PAGE, "/v/") and "5 link(s)" in _pp.around(_SP_PAGE, "/")
      and "tel:09" not in _pp.around(_SP_PAGE, "/"), _ar_t)
with _tempfile.TemporaryDirectory() as _tmp:
    _f = _Path(_tmp) / "s.html"
    _f.write_text(_SP_PAGE, encoding="utf-8")
    _o = _io.StringIO()
    with _contextlib.redirect_stdout(_o):
        _rc = _pp.main(["--around", "/v/", str(_f), "--up", "1", "--no-text"])
    _bad = []
    for _argv in (["--around", "/v/", str(_f), "--up", "9"], ["--around", "/v/", str(_f), "--up", "-1"],
                  ["--around", "v/", str(_f)]):
        try:
            with _contextlib.redirect_stderr(_io.StringIO()):
                _pp.main(_argv)
            _bad.append(False)
        except SystemExit as _e:
            _bad.append(_e.code == 2)
check("  --around PREFIX FILE [--up N] on the command line: exits 0 with no network and no text; "
      "--up 9 and -1, and a prefix that is not a path, are refused",
      _rc == 0 and "4 link(s)" in _o.getvalue() and "پراید" not in _o.getvalue()
      and "[href=/v/<tok>/<tok>]" in _o.getvalue() and _bad == [True, True, True], _o.getvalue()[:300])
_all = _KH_DL + _KH_V + _pg2 + _pp.survey(_KH_PAGE) + _pp.around(_SP_PAGE, "/v/", with_text=False)
_a4 = _pp.around(_SP_PAGE, "/v/", up=1, show=4, name="s.html")
_a9 = _pp.around(_SP_PAGE, "/v/", up=1, show=9)
check("Q9a: show=4 prints four parents, the header is the one of the default; more than there are prints those there are",
      _a4.count("# parent ") == 4 and _a9.count("# parent ") == 4 and _a9.count("\n\n\n") == 0
      and _a4.splitlines()[0] == _ar.splitlines()[0] and _pp.around(_SP_PAGE, "/v/", up=1, show=1).count("# parent ") == 1,
      _a9)
with _tempfile.TemporaryDirectory() as _tmp:
    _f = _Path(_tmp) / "s.html"
    _f.write_text(_SP_PAGE, encoding="utf-8")
    _o = _io.StringIO()
    with _contextlib.redirect_stdout(_o):
        _rc = _pp.main(["--around", "/v/", str(_f), "--up", "1", "--show", "3", "--no-text"])
    _bad = []
    for _n in ("0", "7", "-1"):
        try:
            with _contextlib.redirect_stderr(_io.StringIO()):
                _pp.main(["--around", "/v/", str(_f), "--show", _n])
            _bad.append(False)
        except SystemExit as _e:
            _bad.append(_e.code == 2)
check("  --show 3 on the command line prints three; 0, 7 and -1 are refused",
      _rc == 0 and _o.getvalue().count("# parent ") == 3 and _bad == [True, True, True], _o.getvalue()[:200])
check("Q7: no phone, no name, no person's price, no title, no token and no id in any of them",
      not any(x in _all for x in ("9123456789", "0912", "Rezaei", "111111", "فهرست", "AbCd1234", "GhIj5678",
                                  "پراید", "770000", "910000", "880000", "AbCdEfGh")), _all[:400])


print("\nkhodro45's list -- read from the shape the owner's survey and --around found")
# Invented to the SHAPE of `/buy-car/` (2026-10-29): a Next.js page whose data
# stream holds state.queries[].state.data.pages[] = {count, next, previous,
# results}, and the same results as cards a[href=/buy-car/<brand>-<model>/<city>/<slug>/]
# with «قیمت», a figure and the toman icon. No value here was on that page.
from collections import Counter                                      # noqa: E402
from caro.ingest import khodro45 as _k45                             # noqa: E402
from caro.ingest.khodro45 import Khodro45Adapter, Khodro45Parser, parse_khodro45  # noqa: E402
from caro.ingest.robots import RobotsViolation as _RV                 # noqa: E402


def _k45_result(slug, *, brand=("پژو", "Peugeot", "peugeot"), model=("پارس", "Pars", "pars"),
                year="1402", price=1188000000, final=1212000000, ptype=2, klm=127860,
                city=("زاهدان", "Zahedan"), tags=("شاسی پلمپ",), option="XU7", active=True):
    return {"slug": slug, "active": active, "guaranteed": False, "immediate_delivery": False,
            "price_type": ptype, "price": price, "final_price": final, "has_installment": True,
            "views": 40, "car_properties": {
                "brand": {"title": brand[0], "title_en": brand[1], "seo_slug": brand[2]},
                "model": {"title": model[0], "title_en": model[1], "seo_slug": model[2]},
                "option": option, "trim": "", "year": year},
            "city": {"title": city[0], "title_en": city[1]}, "branch": None,
            "car_specifications": {"document": None, "klm": klm, "is_klm_matched": None},
            "image": {"uuid": "u", "url": "https://cdn.example/x.webp"}, "identifier": 770001,
            "created_time": "2026-10-28T10:00:00", "fmp_tags": [{"id": 6, "title": t} for t in tags]}


def _k45_card(r, *, figure="final", km=None, year=None, negotiable=False):
    cp = r["car_properties"]
    href = (f"/buy-car/{cp['brand']['seo_slug']}-{cp['model']['seo_slug']}/"
            f"{r['city']['title_en'].lower()}/{r['slug']}/")
    if figure == "final":
        fig = f"{r['final_price']:,}"
    elif figure == "price":
        fig = f"{r['price']:,}"
    else:
        fig = figure
    price_block = ('<p class="font-normal">قیمت</p><div class="flex"><p class="font-semibold">توافقی</p></div>'
                   if negotiable else
                   f'<p class="font-normal">قیمت</p><div class="flex"><p class="font-semibold">{fig}</p>'
                   '<span class="icon-toman text-lg"></span></div>') if fig is not None or negotiable else ""
    km_text = km if km is not None else f"{r['car_specifications']['klm']:,} km"
    return (f'<div class="gap-4"><a class="flex h-full w-full" href="{href}" target="_blank">'
            '<div class="bg-common-100"><div class="aspect"><div class="AsyncImage-root"></div></div>'
            '<div class="flex p-3"><h2 class="flex"><span class="font-semibold">' + cp["brand"]["title"] + '</span>'
            '<span class="mx-2">|</span><span class="flex"><span><span class="block" title="t">'
            + cp["model"]["title"] + '</span></span><span class="mx-2">|</span>'
            f'<span class="font-semibold">{year if year is not None else cp["year"]}</span></span></h2>'
            f'<ul><li><p title="o">{cp["option"]}</p><span>|</span></li><li><p>{km_text}</p><span>|</span></li>'
            f'<li><p>{r["city"]["title"]}</p></li></ul>'
            '<div class="flex"><div class="flex" data-tag-item=""><span data-testid="website.abc12345.listing-tag.'
            + (r["fmp_tags"][0]["title"] if r["fmp_tags"] else "x") + '"><p>'
            + (r["fmp_tags"][0]["title"] if r["fmp_tags"] else "x") + '</p></span></div></div></div>'
            '<div class="flex"><span>خدمات خودرو45</span></div>'
            f'<div class="bg-common-200">{price_block}</div></div></a></div>')


def _k45_page(results, cards=(), *, count=1812,
              nxt="https://khodro45.com/api/v2/car_listing/?limit=12&offset=12&ordering=-created_time"):
    state = {"queries": [
        {"queryKey": ["brands"], "state": {"status": "success", "data": [
            {"id": 96, "title": "پژو", "title_en": "Peugeot", "seo_slug": "peugeot", "logo": {}}] * 3}},
        {"queryKey": ["car_listing", {"limit": 12}], "state": {"status": "success", "data": {
            "pages": [{"count": count, "next": nxt, "previous": None, "results": list(results)}],
            "pageParams": [None]}}}]}
    row = "7:" + json.dumps(["$", "$L1b", None, {"state": state}], ensure_ascii=False) + "\n"
    half = len(row) // 2
    push = lambda chunk: "self.__next_f.push([1," + json.dumps(chunk, ensure_ascii=False) + "])"
    return ("<!DOCTYPE html><html><head><script src='/_next/static/chunks/main.js'></script></head><body>"
            "<header><nav><ul><li><a href='/buy-car/'><p>خرید خودرو</p></a></li></ul></nav></header>"
            "<main><div class='pt-6'>" + "".join(cards) + "</div></main>"
            "<script>" + push('0:["$","html",null,{}]\n' + row[:half]) + "</script>"
            "<script>" + push(row[half:] + '8:I["chunks/x.js",[],"default"]\n') + "</script>"
            "</body></html>")


_kr = [_k45_result("cla-tsznel"), _k45_result("cla-umvzwp", brand=("فونیکس", "Fownix", "fownix"),
                                               model=("تیگو ۷ پرو", "Tiggo 7 Pro", "tiggo7pro"),
                                               price=2970000000, final=3030000000, klm=10303, option="MC اتوماتیک"),
       _k45_result("cla-dbqpay", brand=("هایما", "Haima", "haima"), model=("اس ۷", "S7", "s7"),
                   price=8415990000, final=8585990000, klm=234951, year="2017",
                   city=("اصفهان", "Isfahan"), tags=("بدون رنگ",))]
_K45_PAGE = _k45_page(_kr, [_k45_card(r) for r in _kr])
_ktr = []
_k1 = parse_khodro45(_K45_PAGE, _ktr)
check("K1: three results with their cards are three listings, in page order, by slug, at the card's address",
      [x.listing_id for x in _k1] == ["cla-tsznel", "cla-umvzwp", "cla-dbqpay"]
      and _k1[0].url == "https://khodro45.com/buy-car/peugeot-pars/zahedan/cla-tsznel/"
      and _k1[0].source_url == _k1[0].url and _ktr[0].kind == "html"
      and (_ktr[0].results, _ktr[0].cards, _ktr[0].emitted, _ktr[0].count) == (3, 3, 3, 1812),
      str([(x.listing_id, x.url) for x in _k1]) + str(_ktr[0]))
check("K2: the card shows final_price: that is the asking price, display-confirmed, with what the card showed kept",
      (_k1[0].asking_price_toman, _k1[0].price_status, _k1[0].price_provenance,
       _k1[0].price_displayed_toman, _k1[0].price_raw) == (1212000000, "display_confirmed", "data+card",
                                                           1212000000, "1212000000")
      and _ktr[0].shown == Counter({"final_price": 3}), str(_k1[0]))
_k2p = parse_khodro45(_k45_page(_kr[:1], [_k45_card(_kr[0], figure="price")]))[0]
_k2n_tr = []
_k2n = parse_khodro45(_k45_page(_kr[:1], [_k45_card(_kr[0], figure="999,000,000")]), _k2n_tr)[0]
check("  the card shows price: price; the card shows a third number: no price, both fields listed",
      (_k2p.asking_price_toman, _k2p.price_raw) == (1188000000, "1188000000")
      and (_k2n.asking_price_toman, _k2n.price_status) == (None, "ambiguous")
      and _k2n_tr[0].odd["card price is neither field"] == [(1188000000, 1212000000, 999000000)],
      str((_k2p.asking_price_toman, _k2n.asking_price_toman, _k2n_tr[0].odd)))
_k2w = parse_khodro45(_k45_page(_kr[:1], [_k45_card(_kr[0], figure="1.2 میلیارد")]))[0]
_k2v = parse_khodro45(_k45_page(_kr[:1], [_k45_card(_kr[0], negotiable=True)]))[0]
check("  a figure with a word in it is not read; «توافقی» is negotiable; neither has a price",
      (_k2w.asking_price_toman, _k2w.price_status) == (None, "ambiguous")
      and (_k2v.asking_price_toman, _k2v.price_status, _k2v.price_kind) == (None, "negotiable", "negotiable"),
      str((_k2w.price_status, _k2v.price_status)))

_api = json.dumps({"count": 1812, "next": None, "previous": "x",
                   "results": [_k45_result("cla-api001", price=1500000000, final=1530300000),
                               _k45_result("cla-api002", price=1600000000, final=1632320000)]})
_kp = Khodro45Parser()
_kp(_K45_PAGE)
_ka = _kp(_api)
check("K3: a page of the API, with no card, takes the field the run's three cards showed: structured_only",
      [(x.listing_id, x.asking_price_toman, x.price_status) for x in _ka]
      == [("cla-api001", 1530300000, "structured_only"), ("cla-api002", 1632320000, "structured_only")]
      and _kp.traces[-1].kind == "api" and _kp.traces[-1].results_without_card == 2
      and _kp.next_url is None, str([(x.listing_id, x.asking_price_toman, x.price_status) for x in _ka]))
_kp2 = Khodro45Parser()
_kp2(_k45_page(_kr[:2], [_k45_card(r) for r in _kr[:2]]))
_ka2 = _kp2(_api)
_kp3 = Khodro45Parser()
_kp3(_k45_page(_kr, [_k45_card(_kr[0], figure="price"), _k45_card(_kr[1]), _k45_card(_kr[2])]))
_ka3 = _kp3(_api)
check("  two cards are not enough, and cards that showed both fields settle nothing: no price",
      [x.asking_price_toman for x in _ka2] == [None, None] and [x.asking_price_toman for x in _ka3] == [None, None]
      and _kp2.traces[-1].price["no card, no field settled"] == 2
      and any("show price on some" in ln for ln in _k45.report(_kp3.traces)),
      str([x.price_status for x in _ka2]))
check("  and their address is the rule the cards' links followed, three of three",
      _ka[0].url == "https://khodro45.com/buy-car/peugeot-pars/zahedan/cla-api001/"
      and [x.url for x in _ka2] == ["", ""], str((_ka[0].url, _ka2[0].url)))

_k4tr = []
_k4 = parse_khodro45(_k45_page([_k45_result("cla-type4x", ptype=4)], [_k45_card(_k45_result("cla-type4x", ptype=4))]),
                     _k4tr)[0]
check("K4: a price type other than 2 has no price, and the report says what is not known",
      (_k4.asking_price_toman, _k4.price_status) == (None, "ambiguous")
      and _k4tr[0].price["price_type 4"] == 1 and _k4tr[0].price_types["4"] == 1
      and any("price type other than 2" in ln for ln in _k45.report(_k4tr)), str(_k4tr[0].price))

_k5a = parse_khodro45(_k45_page([_k45_result("cla-km500x", klm=500, year="1405")],
                                [_k45_card(_k45_result("cla-km500x", klm=500, year="1405"), km="500 km")]))[0]
_k5tr = []
_k5d = parse_khodro45(_k45_page([_k45_result("cla-kmdiff", klm=120000)],
                                [_k45_card(_k45_result("cla-kmdiff", klm=120000), km="90,000 km")]), _k5tr)[0]
_k5o = parse_khodro45(_api)[0]
check("K5: the odometer as written: 500 km is 500; the card agrees with klm; 120,000 against 90,000 is none, listed; "
      "with no card klm alone",
      _k5a.mileage_km == 500 and _k1[0].mileage_km == 127860 and _k5d.mileage_km is None
      and _k5tr[0].mileage["disagree"] == 1 and _k5tr[0].odd["odometer differs"] == [(120000, 90000)]
      and _k5o.mileage_km == 127860 and _ktr[0].mileage == Counter({"agree": 3}),
      str((_k5a.mileage_km, _k5d.mileage_km, _k5o.mileage_km, _ktr[0].mileage)))
_k6tr = []
_k6 = parse_khodro45(_k45_page([_k45_result("cla-yrdiff")], [_k45_card(_k45_result("cla-yrdiff"), year="1401")]),
                     _k6tr)[0]
check("K6: 1402 is 1402; 2017 is 1396 and counted Gregorian; a card year that differs gives no year, listed",
      _k1[0].year_jalali == 1402 and _k1[2].year_jalali == 1396
      and _ktr[0].calendar == Counter({"jalali": 2, "gregorian": 1}) and _k6.year_jalali is None
      and _k6tr[0].odd["year differs"] == [(1402, 1401)], str((_k1[2].year_jalali, _ktr[0].calendar)))
_k7s = parse_khodro45(_k45_page([_k45_result("cla-samand", brand=("سمند", "Samand", "samand"),
                                             model=("LX", "LX", "lx"))]))[0]
_k7x = parse_khodro45(_k45_page([_k45_result("cla-longnm", brand=("برند", "B" * 41, "b"),
                                             model=("مدل", "M", "m"))]))[0]
check("K7: the table on the site's Persian names first (Peugeot Pars, IKCO Samand); else the English titles "
      "as given (Fownix Tiggo 7 Pro, Haima S7); a name that is not a category is none",
      [(x.make, x.model) for x in _k1] == [("Peugeot", "Pars"), ("Fownix", "Tiggo 7 Pro"), ("Haima", "S7")]
      and (_k7s.make, _k7s.model) == ("IKCO", "Samand") and (_k7x.make, _k7x.model) == (None, None),
      str([(x.make, x.model) for x in _k1]))
check("K8: Zahedan gives no province, Isfahan gives Isfahan from the city; the city's title is kept as the line",
      (_k1[0].city, _k1[0].province_source, _k1[0].location_raw) == (None, "none", "زاهدان")
      and (_k1[2].city, _k1[2].province_source, _k1[2].location_raw) == ("اصفهان", "city", "اصفهان"),
      str((_k1[0].city, _k1[2].city)))
check("K9: a tag «بدون رنگ» is intact, from a field; «شاسی پلمپ» leaves it unknown; the tags are counted",
      (_k1[2].body_condition, _k1[2].condition_source) == ("intact", "field")
      and (_k1[0].body_condition, _k1[0].condition_source) == ("unknown", "none")
      and _ktr[0].tags == Counter({"شاسی پلمپ": 2, "بدون رنگ": 1}), str(_ktr[0].tags))
_k10 = _k1[0].to_fetch_outcome("khodro45", "salt")
check("K10: seller unknown and no fingerprint, a vehicle by its canonical names, a cash price, automatic from "
      "the option, and the whole record eligible",
      (_k1[0].seller_type, _k1[0].seller_raw, _k10.seller_fingerprint) == ("unknown", None, None)
      and (_k1[0].product_class, _k1[0].product_class_source) == ("vehicle", "canonical_name")
      and _k1[0].price_kind == "cash" and _k1[1].gearbox == "automatic" and _k10.listing_id == "khodro45:cla-tsznel"
      and _eligibility(_k1[0]) == (True, []), str(_eligibility(_k1[0])))
_k11r = [_k45_result(f"cla-p{i}xyz", price=1000000000 + i * 100000000, final=1000000000 + i * 100000000)
         for i in range(5)]
_k11tr = []
parse_khodro45(_k45_page(_k11r, [_k45_card(r) for r in _k11r]), _k11tr)
_k11 = "\n".join(_k45.report(_k11tr))
check("K11: the report has counts and categories: no slug, no title, no price but the smallest, middle and "
      "largest; the site's count; the next page as its shape",
      "cla-" not in _k11 and "پارس" not in _k11 and "1.10B" not in _k11 and "1.30B" not in _k11
      and "min 1.00B   median 1.20B   max 1.40B" in _k11 and "the site's count 1812" in _k11
      and "/api/v#/car_listing/?limit&offset&ordering" in _k11 and "card shows" in _k11, _k11)
_k11i = parse_khodro45(_k45_page([_k45_result("cla-inactv", active=False)]), _k11tr)
check("  an inactive result is not a listing, and is counted; a page with no stream has none",
      _k11i == [] and _k11tr[-1].skipped["not active"] == 1
      and parse_khodro45("<html><body><a href='/buy-car/a-b/c/cla-zzz/'>x</a></body></html>") == []
      and parse_khodro45("") == [] and parse_khodro45("{not json") == [], str(_k11tr[-1].skipped))


def _k45_world(pages, robots="User-agent: *\nDisallow: /panel/\n"):
    asked = []

    def fetch(url):
        asked.append(url)
        if url.endswith("/robots.txt"):
            return 200, robots
        return pages.get(url, (404, ""))
    return fetch, asked


_K45_API2 = "https://khodro45.com/api/v2/car_listing/?limit=12&offset=12&ordering=-created_time"
_kw, _kasked = _k45_world({"https://khodro45.com/buy-car/": (200, _K45_PAGE), _K45_API2: (200, _api)})
_sleeps = []
_kad = Khodro45Adapter(max_pages=2, page_fetcher=_kw, robots_fetcher=_kw, parser=Khodro45Parser(),
                       sleeper=_sleeps.append)
_kout = list(_kad.fetch_all(date(2026, 10, 29)))
check("K12: the list, then the API page it names: robots.txt first, five listings, a pause after robots.txt and "
      "one between the pages, and two pages is all",
      _kasked == ["https://khodro45.com/robots.txt", "https://khodro45.com/buy-car/", _K45_API2]
      and [o.listing_id for o in _kout] == ["khodro45:cla-tsznel", "khodro45:cla-umvzwp", "khodro45:cla-dbqpay",
                                           "khodro45:cla-api001", "khodro45:cla-api002"]
      and len(_sleeps) == 2 and _kad.stopped is None, str((_kasked, _kad.stopped, len(_sleeps))))
_kw, _kasked = _k45_world({"https://khodro45.com/buy-car/": (200, _K45_PAGE)},
                          robots="User-agent: *\nDisallow: /buy-car/\n")
_kad = Khodro45Adapter(page_fetcher=_kw, robots_fetcher=_kw, parser=Khodro45Parser(), sleeper=lambda s: None)
try:
    list(_kad.fetch_all(date(2026, 10, 29)))
    _raised = False
except _RV:
    _raised = True
check("  a robots.txt that disallows /buy-car/ stops the run before its first page is asked for",
      _raised and _kasked == ["https://khodro45.com/robots.txt"], str(_kasked))
_kw, _kasked = _k45_world({"https://khodro45.com/buy-car/": (200, _K45_PAGE)},
                          robots="User-agent: *\nDisallow: /api/\n")
_kad = Khodro45Adapter(max_pages=3, page_fetcher=_kw, robots_fetcher=_kw, parser=Khodro45Parser(),
                       sleeper=lambda s: None)
_kout = list(_kad.fetch_all(date(2026, 10, 29)))
check("  the API disallowed: page 1 is kept, page 2 is not asked for, and the run says why",
      len(_kout) == 3 and _K45_API2 not in _kasked and "not requested" in (_kad.stopped or ""),
      str((_kasked, _kad.stopped)))
_kw, _kasked = _k45_world({"https://khodro45.com/buy-car/": (200, _k45_page(
    _kr, [_k45_card(r) for r in _kr], nxt="https://api.khodro45.com/v2/car_listing/?offset=12"))})
_kad = Khodro45Adapter(max_pages=3, page_fetcher=_kw, robots_fetcher=_kw, parser=Khodro45Parser(),
                       sleeper=lambda s: None)
_kout = list(_kad.fetch_all(date(2026, 10, 29)))
check("  a next page on another origin is not asked for",
      len(_kout) == 3 and not any("api.khodro45" in u for u in _kasked) and "not requested" in (_kad.stopped or ""),
      str((_kasked, _kad.stopped)))
_kw, _kasked = _k45_world({"https://khodro45.com/buy-car/": (200, _K45_PAGE), _K45_API2: (500, "")})
_kad = Khodro45Adapter(max_pages=3, page_fetcher=_kw, robots_fetcher=_kw, parser=Khodro45Parser(),
                       sleeper=lambda s: None)
_kout = list(_kad.fetch_all(date(2026, 10, 29)))
check("  a page that does not answer is an unknown outcome, the run stops, and nothing is asked again",
      [o.status for o in _kout][-1] is FetchStatus.UNKNOWN and _kasked.count(_K45_API2) == 1
      and "did not answer" in (_kad.stopped or ""), str((_kasked, _kad.stopped)))
_kw, _kasked = _k45_world({"https://khodro45.com/buy-car/": (200, _K45_PAGE),
                           _K45_API2: (200, _k45_page(_kr, [_k45_card(r) for r in _kr]))})
_kad = Khodro45Adapter(max_pages=3, page_fetcher=_kw, robots_fetcher=_kw, parser=Khodro45Parser(),
                       sleeper=lambda s: None)
_kout = list(_kad.fetch_all(date(2026, 10, 29)))
check("  a page that adds nothing new stops the run; no page_fetcher or parser: it refuses to guess",
      len(_kout) == 3 and _kasked.count(_K45_API2) == 1 and "added no new listing" in (_kad.stopped or ""),
      str((_kasked, _kad.stopped)))
try:
    list(Khodro45Adapter(robots_fetcher=_kw).fetch_all(date(2026, 10, 29)))
    _refused = False
except RuntimeError:
    _refused = True
check("  and with no fetcher it refuses", _refused)


print("\nfirst_run reads Khodro45, saved and live (faked)")
with _tempfile.TemporaryDirectory() as _tmp:
    _f1, _f2 = _Path(_tmp) / "01-k.html", _Path(_tmp) / "02-api.json"
    _f1.write_text(_K45_PAGE, encoding="utf-8")
    _f2.write_text(_api, encoding="utf-8")
    _out = _io.StringIO()
    _argv, _first_run.sys.argv = _first_run.sys.argv, ["first_run.py", "--source", "khodro45",
                                                       "--page", str(_f1), str(_f2)]
    _salt = os.environ.pop("CARO_SELLER_SALT", None)
    try:
        with _contextlib.redirect_stdout(_out):
            _rc = _first_run.main()
    finally:
        _first_run.sys.argv = _argv
        if _salt is not None:
            os.environ["CARO_SELLER_SALT"] = _salt
    _left = sorted(x.name for x in _Path(_tmp).rglob("*"))
check("K13: --source khodro45 --page reads the list page and a saved page of the API offline, with no salt, "
      "writes nothing, and prints the inventory and the report",
      _rc == 0 and "page 2 of 2: 2 new, 0 repeated" in _out.getvalue()
      and "read 5 listing(s) from 2 pages" in _out.getvalue() and "CORPUS INVENTORY  (5 listings)" in _out.getvalue()
      and "KHODRO45 PAGE READ" in _out.getvalue() and "DIVAR PAGE READ" not in _out.getvalue()
      and _left == ["01-k.html", "02-api.json"], _out.getvalue()[:400])
_kfr_args = _argparse.Namespace(source="khodro45", limit=10, categories=None, makes="", seed=0,
                                city="tehran", pages=2)
_kw, _kasked = _k45_world({"https://khodro45.com/buy-car/": (200, _K45_PAGE), _K45_API2: (200, _api)})
with _tempfile.TemporaryDirectory() as _tmp:
    _old, _first_run.SNAPSHOT_DIR = _first_run.SNAPSHOT_DIR, _Path(_tmp)
    _out = _io.StringIO()
    try:
        with _contextlib.redirect_stdout(_out):
            _kgot, _kspath = _first_run.collect(_kfr_args, [], fetcher=_kw, sleeper=lambda s: None)
        _ksnap = json.loads(_kspath.read_text(encoding="utf-8"))
    finally:
        _first_run.SNAPSHOT_DIR = _old
check("  --source khodro45 live: robots.txt, the list, the API page, over plain HTTP; five listings in the "
      "snapshot with the robots.txt it obeyed, and the report",
      _kasked == ["https://khodro45.com/robots.txt", "https://khodro45.com/buy-car/", _K45_API2]
      and len(_kgot) == 5 and len([o for o in _ksnap["outcomes"] if o["listing_id"].startswith("khodro45:")]) == 5
      and any(n.startswith("robots.txt ") for n in _ksnap["notes"]) and "KHODRO45 PAGE READ" in _out.getvalue(),
      str(_kasked) + _out.getvalue()[-300:])


print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
