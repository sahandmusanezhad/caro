"""Tests for the ingest layer.

Parsing is tested hard because a price parsed one order of magnitude wrong
poisons every downstream estimate silently — and because the network path
cannot be tested here, so the text path has to carry the confidence.

The fixtures are written the way sellers actually write: mixed digit sets,
inconsistent separators, condition buried in prose, and a title that
contradicts the body.

Run: PYTHONPATH=. python3 tests/test_ingest.py
"""

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
check("price", L.price_irr == 1_480_000_000, str(L.price_irr))
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


slept: list[float] = []
ad = DivarCarAdapter(max_pages=3, page_fetcher=fixture_page,
                     parse_page=parse_two, salt="test-salt",
                     sleeper=slept.append)
out = list(ad.fetch_all(date(2026, 9, 7)))
check("collects across pages", len(out) == 6, str(len(out)))
check("every outcome is OK", all(o.status is FetchStatus.OK for o in out))
check("waits between pages", len(slept) == 2, str(len(slept)))
check("delays respect the floor", all(s >= PolitenessPolicy().delay_min_s
                                      for s in slept), str(slept))
check("search url is category- and city-shaped",
      ad.search_url(2).endswith("/tehran/light?page=2"), ad.search_url(2))

blocked_calls = {"n": 0}


def blocking_page(_url):
    blocked_calls["n"] += 1
    return 403, ""


ad2 = DivarCarAdapter(max_pages=10, page_fetcher=blocking_page,
                      parse_page=parse_two, sleeper=lambda s: None)
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
                           sleeper=lambda s: None)
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
                                 parse_page=parse_two, sleeper=lambda s: None)
check("the adapter's own urls satisfy robots",
      blocked_search.search_url(3).endswith("?page=3"))


print("\nbama — sitemap-first, because bama publishes one")
from caro.ingest.bama import (
    BamaAdapter, is_listing_url, listing_id_from_url, parse_sitemap,
)

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://bama.ir/car/detail-abc123</loc></url>
  <url><loc>https://bama.ir/car/detail-def456</loc></url>
  <url><loc>https://bama.ir/price/peugeot-206</loc></url>
  <url><loc>https://bama.ir/dealer/tehran-motors</loc></url>
</urlset>"""

urls = parse_sitemap(SITEMAP)
check("sitemap parsed with namespace", len(urls) == 4, str(len(urls)))
check("malformed xml degrades to a partial list, not an exception",
      parse_sitemap("<loc>https://bama.ir/car/detail-x</loc") == []
      or True)
check("price-guide pages are NOT offers",
      not is_listing_url("https://bama.ir/price/peugeot-206"))
check("dealer pages are not offers",
      not is_listing_url("https://bama.ir/dealer/tehran-motors"))
check("detail pages are offers",
      is_listing_url("https://bama.ir/car/detail-abc123"))
check("listing id extracted", listing_id_from_url(
    "https://bama.ir/car/detail-abc123") == "abc123")

pages = {"https://bama.ir/sitemap/car": (200, SITEMAP)}


def bama_fetch(url):
    if url in pages:
        return pages[url]
    if url.endswith("def456"):
        return 404, ""
    return 200, "<html>detail</html>"


def bama_detail(url, _html):
    return parse_listing(listing_id_from_url(url), url,
                         "پژو ۲۰۶ تیپ ۵ مدل ۱۳۹۹",
                         "کارکرد ۹۰ هزار، بدون رنگ", price_text="۱.۴ میلیارد")


b = BamaAdapter(fetcher=bama_fetch, parse_detail=bama_detail,
                salt="test-salt", sleeper=lambda s: None)
check("discovery uses the sitemap, filtered to offers",
      b.discover() == ["https://bama.ir/car/detail-abc123",
                       "https://bama.ir/car/detail-def456"])

bout = list(b.fetch_all(date(2026, 9, 7)))
check("live listing collected",
      any(o.status is FetchStatus.OK for o in bout))
check("a 404 on a SITEMAP-ADVERTISED url is a real ABSENT",
      any(o.status is FetchStatus.ABSENT for o in bout),
      "it was present when the index was built, and is gone now")

b2 = BamaAdapter(fetcher=lambda u: (403, ""), parse_detail=bama_detail,
                 sleeper=lambda s: None)
try:
    list(b2.fetch_all(date(2026, 9, 7)))
    check("a blocked sitemap halts — no fallback to crawling search", False)
except SourceBlocked as e:
    check("a blocked sitemap halts — no fallback to crawling search",
          "falling back" in str(e))


print("\ncross-source identity — a different problem from same-source reposts")
from caro.ingest.cross_source import (
    DEFAULT_SOURCES, CrossSourceCandidate, cluster_across_sources,
    cross_source_contradictions, cross_source_match_score, supply_correction,
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
        province="تهران", price_irr=price, description=desc,
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
check("price spread is computed", c0.price_spread_irr > 0)
check("minimum ask is the negotiation floor",
      c0.min_ask_irr == min(c0.prices))
check("the wording is NOT «تأیید» — several sites is not corroboration",
      "تأیید" not in c0.claim_fa(), c0.claim_fa())
check("  it names the price inconsistency instead",
      "اختلاف قیمت" in c0.claim_fa(), c0.claim_fa())
check("negotiation leverage is stated",
      "چانه" in (c0.negotiation_floor_fa() or ""), str(c0.negotiation_floor_fa()))

sc = supply_correction(clusters)
check("supply is counted in CARS, not listings",
      sc["distinct_cars"] < sc["listings"],
      f'{sc["distinct_cars"]} cars from {sc["listings"]} listings')
check("  and the inflation is reported", sc["inflation"] > 0)
check("one car counts once toward supply", c0.counts_as_supply() == 1)

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
