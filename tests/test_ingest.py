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

# A budget that binds is not a thin market, and run 6 could not tell its
# operator which of the two it had hit: it asked for 50 listings, was allowed
# three category pages, and reported 18 as though that were what Bama had.
_ST = BamaAdapter(fetcher=lambda u: (200, SITEMAP), max_categories=1)
_ST.discover_categories()
_ST.stats.categories_tried = 1
check("the run records the category budget it was given",
      _ST.stats.category_budget == 1, str(_ST.stats.category_budget))
check("  and says the budget stopped discovery, not the market",
      "category BUDGET ran out" in _ST.stats.report(),
      "1 of 2 categories opened, and the old report said nothing")
_ST.stats.category_budget = 99
check("  while a budget that did not bind says nothing",
      "category BUDGET ran out" not in _ST.stats.report())

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
            body="<p>وضعیت بدنه</p><p>دور رنگ</p>"):
    car = {
        "@context": "https://schema.org", "@type": ["Product", "Car"],
        "name": "پراید،  131", "identifier": "ki4vo2q1",
        "brand": {"@type": "Brand", "name": "پراید"},
        "color": "سفید", "vehicleTransmission": "دنده ای",
        "fuelType": "بنزینی", "productionDate": year, "vehicleModelDate": year,
        "mileageFromOdometer": {"@type": "QuantitativeValue",
                                "value": km, "unitCode": "KMT"},
        "offers": {"@type": "Offer", "price": price,
                   "priceCurrency": currency},
    }
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

pages = {"https://bama.ir/sitemap/car": (200, SITEMAP),
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
        mileage_status="plausible") for i in range(n)]


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
        price_status="display_confirmed", mileage_status="plausible")


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


print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
