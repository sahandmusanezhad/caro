#!/usr/bin/env python3
"""Build the Diyako newspaper menu from data/menu.json.

    python3 tools/build.py

Writes, next to this folder's parent:
    index.html   the digital menu — one self-contained file (fonts, logo, styles inlined)
    print.html   the A4 paper menu, two pages; tools/make_pdf.js turns it into a PDF

Standard library only. Edit prices in data/menu.json and run it again.
"""
import base64
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC, ASSETS = ROOT / "src", ROOT / "assets"

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(n):
    """1250 -> ۱٬۲۵۰ ; '100' -> ۱۰۰"""
    if isinstance(n, int):
        s = f"{n:,}".replace(",", "٬")
    else:
        s = str(n)
    return s.translate(FA_DIGITS)


def esc(s):
    return html.escape(str(s), quote=True)


def norm(s):
    """Search key: unify Arabic/Persian letters, drop ZWNJ, marks and punctuation."""
    s = s.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک")
    s = re.sub(r"[‌ًٔ-ٟ]", "", s)
    s = re.sub(r"[()/·،]", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def price_html(p):
    if p is None:
        return ""
    if isinstance(p, list):
        return f'{fa(p[0])}<i class="slash">/</i>{fa(p[1])}'
    return fa(p)


def read(path):
    return Path(path).read_text(encoding="utf-8")


def svg_inner(svg):
    """Strip the XML wrapper so an SVG file can be inlined."""
    return re.sub(r"<\?xml[^>]*>", "", svg).strip()


# ------------------------------------------------------------------ fonts
FONTS = [
    # family, file, weight range, unicode-range
    ("Vazirmatn", "vazirmatn-arabic.woff2", "100 900",
     "U+0600-06FF,U+0750-077F,U+08A0-08FF,U+200C-200E,U+2010-2011,U+204F,U+2E41,U+FB50-FDFF,U+FE70-FEFC"),
    ("Vazirmatn", "vazirmatn-latin.woff2", "100 900",
     "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+20AC,U+2122,U+2212,U+2215,U+FEFF,U+FFFD"),
    ("Lalezar", "lalezar-arabic.woff2", "400",
     "U+0600-06FF,U+0750-077F,U+08A0-08FF,U+200C-200E,U+FB50-FDFF,U+FE70-FEFC"),
    ("Markazi", "markazi-arabic.woff2", "400 700",
     "U+0600-06FF,U+0750-077F,U+08A0-08FF,U+200C-200E,U+2010-2011,U+FB50-FDFF,U+FE70-FEFC"),
    ("Markazi", "markazi-latin.woff2", "400 700",
     "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+20AC,U+2122,U+2212,U+FEFF,U+FFFD"),
]


STATIC_WEIGHTS = {"Vazirmatn": (600, 700, 800), "Markazi": (600, 700)}


def font_faces(static=False):
    """@font-face rules with the fonts inlined. static=True uses the fixed weights from
    assets/fonts/static (made by tools/make_static_fonts.py), which embed cleanly in a PDF."""
    out = []

    def face(family, path, weight, urange):
        data = base64.b64encode(path.read_bytes()).decode()
        out.append(
            f"@font-face{{font-family:'{family}';font-style:normal;font-weight:{weight};font-display:swap;"
            f"src:url(data:font/woff2;base64,{data}) format('woff2');unicode-range:{urange}}}"
        )

    for family, fname, weight, urange in FONTS:
        if static and family in STATIC_WEIGHTS:
            stem = fname[: -len(".woff2")]
            for w in STATIC_WEIGHTS[family]:
                face(family, ASSETS / "fonts" / "static" / f"{stem}-{w}.woff2", w, urange)
        else:
            face(family, ASSETS / "fonts" / fname, weight, urange)
    return "\n".join(out)


# ------------------------------------------------------------------ greek key strip
def key_strip(dark, light, height=12):
    """Straight version of the badge's Greek key, as a CSS background tile."""
    P, H = 13, 12
    rects = [
        (0, 0, 0.625, H), (12.375, 0, 0.625, H),
        (2.625, 8.975, 10.375, 1.25),
        (2.625, 1.775, 1.25, 8.45),
        (2.625, 1.775, 7.75, 1.25),
        (9.125, 1.775, 1.25, 4.85),
        (5.875, 5.375, 4.5, 1.25),
        (5.875, 4.2, 1.25, 2.425),
    ]
    body = "".join(f"<rect x='{x}' y='{y}' width='{w}' height='{h}'/>" for x, y, w, h in rects)
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {P} {H}' width='{P}' height='{H}' "
           f"shape-rendering='crispEdges'><rect width='{P}' height='{H}' fill='{dark}'/>"
           f"<g fill='{light}'>{body}</g></svg>")
    return "url(\"data:image/svg+xml," + svg.replace("#", "%23").replace('"', "'") + "\")"


# ------------------------------------------------------------------ shared pieces
def item_li(it, cls="item"):
    name = esc(it["name"])
    note = f' <small>({esc(it["note"])})</small>' if it.get("note") else ""
    tag = f'<em class="tag">{esc(it["tag"])}</em>' if it.get("tag") else ""
    price = price_html(it.get("price"))
    q = norm(it["name"] + " " + it.get("note", ""))
    if price:
        tail = f'<span class="item__dots" aria-hidden="true"></span><span class="item__price">{price}</span>'
    else:
        tail = '<span class="item__dots item__dots--none" aria-hidden="true"></span>'
    return (f'<li class="{cls}" data-q="{esc(q)}"><span class="item__name">{name}{note}{tag}</span>{tail}</li>')


def category_html(cat, h="h3", print_mode=False):
    note = f' <span class="cat__note">({esc(cat["note"])})</span>' if cat.get("note") else ""
    title = f'<{h} class="cat__title"><span>{esc(cat["title"])}{note}</span></{h}>'
    layout = cat.get("layout")
    box = " cat--box" if cat.get("box") else ""
    if layout == "inline":
        names = "، ".join(esc(i["name"]) for i in cat["items"])
        q = norm(" ".join(i["name"] for i in cat["items"]))
        return (f'<div class="cat cat--inline{box}" id="cat-{cat["id"]}">{title}'
                f'<ul class="items"><li class="item item--inline" data-q="{esc(q)}">'
                f'<span class="item__name">{names}</span></li></ul></div>')
    if layout == "classifieds":
        cards = []
        for it in cat["items"]:
            parts = [esc(x.strip()) for x in it["name"].split("/")]
            body = '<i class="sep">·</i>'.join(f"<span>{p}</span>" for p in parts)
            cards.append(f'<li class="ad-card" data-q="{esc(norm(it["name"]))}"><b>{body}</b></li>')
        head = (f'<div class="classifieds__head"><span>طعم‌ها</span>'
                f'<span class="classifieds__price">هر سرویس <b>{fa(cat["price"])}</b></span></div>')
        return (f'<div class="cat cat--classifieds{box}" id="cat-{cat["id"]}">{title}{head}'
                f'<ul class="classifieds">{"".join(cards)}</ul></div>')
    items = "".join(item_li(i) for i in cat["items"])
    long = " cat--long" if len(cat["items"]) > 10 else ""
    return f'<div class="cat{box}{long}" id="cat-{cat["id"]}">{title}<ul class="items">{items}</ul></div>'


# ------------------------------------------------------------------ digital page
def build_digital(d):
    meta = d["meta"]
    pages = d["pages"]
    feat = d["featured"]
    sprite = read(SRC / "art.svg")
    badge = svg_inner(read(ASSETS / "logo-leather.svg")).replace("<svg ", '<svg class="badge" ', 1)
    ink = svg_inner(read(ASSETS / "logo-ink.svg")).replace("<svg ", '<svg class="mini-badge" ', 1)
    # ids inside the inline SVGs must stay unique once both sit in one page
    ink = ink.replace('id="dk-key"', 'id="dk-key-ink"').replace('href="#dk-key"', 'href="#dk-key-ink"')
    mark = read(ASSETS / "logo-mark.svg")
    favicon = "data:image/svg+xml," + mark.replace("#", "%23").replace('"', "'")

    page_no = {p["id"]: i + 2 for i, p in enumerate(pages)}

    nav_links = '<a href="#front">صفحهٔ اول</a>' + "".join(
        f'<a href="#{p["id"]}">{esc(p["nav"])}</a>' for p in pages
    )

    contents = "".join(
        f'<li><a href="#{p["id"]}"><span>{esc(p["section"])}</span><i aria-hidden="true"></i>'
        f'<span class="contents__what">{esc("، ".join(c["title"] for c in p["categories"][:3]))}</span>'
        f'<span class="contents__no">ص {fa(page_no[p["id"]])}</span></a></li>'
        for p in pages
    )

    lead, second = feat[0], feat[1]

    def price_line(f):
        note = f' <small>({esc(f["note"])})</small>' if f.get("note") else ""
        return (f'<div class="price-line"><span class="item__name">{esc(f["item"])}{note}</span>'
                f'<span class="item__dots" aria-hidden="true"></span>'
                f'<span class="item__price">{price_html(f["price"])}</span><span class="unit">{esc(meta["unit"])}</span></div>')

    front = f'''
<section id="front" class="page page--front" aria-labelledby="lead-h">
  <div class="front-grid">
    <article class="lead">
      <span class="kicker kicker--box">{esc(lead["kicker"])}</span>
      <h2 class="lead__headline" id="lead-h">{esc(lead["headline"])}</h2>
      <p class="deck">{esc(lead["deck"])}</p>
      <figure class="art art--lead">
        <svg viewBox="0 0 320 180" role="img" aria-label="بشقاب چلو شیشلیک"><use href="#a-shishlik"/></svg>
        <div class="stamp" aria-hidden="true"><span>{esc(lead["stamp"])}</span><b>{price_html(lead["price"])}</b><small>{esc(meta["unit"])}</small></div>
        <figcaption>{esc(lead["item"])} ({esc(lead["note"])})، تازه‌ترین خبرِ سفرهٔ ایرانی</figcaption>
      </figure>
      <p class="story"><span class="story__dl">دیاکو —</span> {esc(lead["body"])}</p>
      {price_line(lead)}
    </article>
    <div class="front-side">
      <article class="second">
        <span class="kicker">{esc(second["kicker"])}</span>
        <h2 class="second__headline">{esc(second["headline"])}</h2>
        <figure class="art art--second">
          <svg viewBox="0 0 320 120" role="img" aria-label="سیخ کباب بختیاری"><use href="#a-bakhtiari"/></svg>
        </figure>
        <p class="story">{esc(second["body"])}</p>
        {price_line(second)}
      </article>
      <aside class="contents" aria-label="فهرست">
        <h2 class="contents__title"><svg class="orn" aria-hidden="true"><use href="#o-fleuron"/></svg>در این شماره<svg class="orn" aria-hidden="true"><use href="#o-fleuron"/></svg></h2>
        <ol>{contents}</ol>
      </aside>
    </div>
  </div>
</section>'''

    sections = []
    for p in pages:
        cats = p["categories"]
        boxes = [c for c in cats if c.get("box")]
        flow = [c for c in cats if not c.get("box")]
        cls = "cols"
        if p["id"] == "hookah":
            cls = "cols cols--wide"
        extra = ""
        if p["id"] == "coffee":
            extra = f'''
    <aside class="fortune" aria-labelledby="fortune-h">
      <div class="fortune__head"><svg aria-hidden="true"><use href="#i-cup"/></svg><h3 id="fortune-h">فال قهوه</h3></div>
      <p class="fortune__text" aria-live="polite">فنجانت را برگردان و فالِ امروزت را بخوان.</p>
      <button type="button" class="fortune__btn">فالم را بگیر</button>
    </aside>'''
        box_html = "".join(category_html(c) for c in boxes)
        sections.append(f'''
<section id="{p["id"]}" class="page page--{p["id"]}" data-edition="{p["edition"]}" aria-labelledby="h-{p["id"]}">
  <header class="runhead">
    <span class="runhead__no">صفحهٔ {fa(page_no[p["id"]])}</span>
    <h2 class="runhead__sec" id="h-{p["id"]}">{esc(p["section"])}</h2>
    <span class="runhead__paper">{esc(meta["paper"])}</span>
  </header>
  <div class="page__intro">
    <svg class="vignette" aria-hidden="true"><use href="#i-{p["icon"]}"/></svg>
    <p class="lede">{esc(p["lede"])}</p>
  </div>
  <div class="{cls}">{"".join(category_html(c) for c in flow)}</div>
  {('<div class="page__extras">' + box_html + extra + '</div>') if (box_html or extra) else ''}
</section>''')

    insta = d["meta"].get("instagram", {})
    qr_file = ASSETS / "instagram-qr.svg"
    if qr_file.exists():
        qr = svg_inner(read(qr_file)).replace("<svg ", '<svg class="qr" ', 1)
        handle = esc(insta.get("handle", ""))
        link = (f'<a class="insta__btn" href="{esc(insta.get("url"))}" rel="noopener">@{handle}</a>'
                if insta.get("url") else "")
    else:
        qr = ('<div class="qr qr--soon" role="img" aria-label="کد QR اینستاگرام">'
              '<span></span><span></span><span></span><b>QR</b></div>')
        link = ""

    ticker_items = [
        f'{lead["item"]} به سبک {lead["note"]} به منوی دیاکو اضافه شد',
        f'{second["item"]}: جوجه و گوشت، روی یک سیخ',
        "هواشناسی: امروز هوا برای یک چای داغ عالی است",
        f'همهٔ قیمت‌ها به {meta["unit"]} است',
    ]
    tick = "".join(f"<span>{esc(t)}</span>" for t in ticker_items)

    css = read(SRC / "style.css")
    css = css.replace("/*KEY_STRIP_COPPER*/", key_strip("#a8652e", "#f3ead8"))
    css = css.replace("/*KEY_STRIP_INK*/", key_strip("#1d1712", "#f3ead8"))
    js = read(SRC / "app.js").replace("/*FORTUNES*/[]", json.dumps(d["fortunes"], ensure_ascii=False))

    doc = f'''<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>منوی دیاکو · روزنامهٔ دیاکو</title>
<meta name="description" content="منوی کافه و رستوران دیاکو: غذای ایرانی، پیتزا و برگر، قهوه، چای، شیک و قلیان.">
<meta name="theme-color" content="#f3ead8">
<link rel="icon" type="image/svg+xml" href="{favicon}">
<style>
{font_faces()}
{css}
</style>
</head>
<body>
{sprite}
<div class="paper" id="top">
  <header class="masthead">
    <div class="mast-top">
      <span>نسخهٔ دیجیتال</span>
      <span class="mast-top__en">DIYAKO · Restaurant &amp; Café</span>
    </div>
    <div class="mast-main">
      <div class="ear ear--start"><b>تک‌شماره</b><small>یک لبخند</small></div>
      {badge}
      <div class="ear ear--end"><b>قیمت‌ها</b><small>به {esc(meta["unit"])}</small></div>
    </div>
    <h1 class="nameplate">{esc(meta["paper"])}</h1>
    <p class="tagline"><svg class="orn" aria-hidden="true"><use href="#o-fleuron"/></svg><span>{esc(meta["subtitle"])}</span><svg class="orn" aria-hidden="true"><use href="#o-fleuron"/></svg></p>
    <div class="keyband" aria-hidden="true"></div>
    <div class="dateline">
      <span data-today>شمارهٔ امروز</span>
      <span class="dateline__mid">ویژه‌نامهٔ منو</span>
      <span>قیمت‌ها به {esc(meta["unit"])}</span>
    </div>
  </header>

  <div class="ticker" role="marquee" aria-label="خبر فوری">
    <span class="ticker__label">فوری</span>
    <div class="ticker__track"><div class="ticker__move"><div class="ticker__run">{tick}</div><div class="ticker__run" aria-hidden="true">{tick}</div></div></div>
  </div>

  <div class="sections-sentinel" aria-hidden="true"></div>
  <nav class="sections" aria-label="بخش‌های منو">
    <div class="sections__inner">
      <a class="sections__home" href="#top" aria-label="بالای صفحه">{ink}</a>
      <div class="sections__list">{nav_links}</div>
      <button type="button" class="sections__search" aria-label="جستجو در منو" aria-expanded="false">
        <svg class="ic-search" viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5"/></svg>
        <svg class="ic-close" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>
      </button>
    </div>
    <div class="search" hidden>
      <input type="search" inputmode="search" placeholder="جستجو در منو… مثلاً لاته یا کوبیده" aria-label="جستجو در منو" autocomplete="off">
    </div>
  </nav>

  <main>
    <p class="search-empty" hidden>چیزی پیدا نشد؛ شاید با نامِ دیگری در منو آمده باشد.</p>
    {front}
    {"".join(sections)}
  </main>

  <footer class="imprint">
    <div class="keyband" aria-hidden="true"></div>
    <section class="insta" aria-labelledby="insta-h">
      <span class="insta__label">آگهی</span>
      {qr}
      <div class="insta__text">
        <h2 id="insta-h">دیاکو در اینستاگرام</h2>
        <p>برای دیدنِ تازه‌های منو و حال‌وهوای دیاکو، صفحهٔ ما را دنبال کنید.</p>
        {link}
      </div>
    </section>
    <dl class="imprint__grid">
      <div><dt>صاحب‌امتیاز</dt><dd>رستوران دیاکو</dd></div>
      <div><dt>سردبیر</dt><dd>سرآشپز</dd></div>
      <div><dt>تیراژ</dt><dd>به تعدادِ مهمانانِ عزیز</dd></div>
    </dl>
    <p class="imprint__note">همهٔ قیمت‌ها به {esc(meta["unit"])} است.</p>
    <p class="noosh"><svg class="orn" aria-hidden="true"><use href="#o-fleuron"/></svg>نوش جان!<svg class="orn" aria-hidden="true"><use href="#o-fleuron"/></svg></p>
  </footer>
</div>
<script>
{js}
</script>
</body>
</html>
'''
    return doc


# ------------------------------------------------------------------ print (A4)
def build_print(d):
    meta = d["meta"]
    pages = {p["id"]: p for p in d["pages"]}
    feat = d["featured"]
    sprite = read(SRC / "art.svg")
    badge = svg_inner(read(ASSETS / "logo-flat.svg")).replace("<svg ", '<svg class="badge" ', 1)

    def cats(*ids):
        return [c for i in ids for c in pages[i]["categories"]]

    def column(categories):
        return "".join(category_html(c) for c in categories)

    insta = meta.get("instagram", {})
    qr_file = ASSETS / "instagram-qr.svg"
    if qr_file.exists():
        qr = svg_inner(read(qr_file)).replace("<svg ", '<svg class="qr" ', 1)
        handle = f'<b dir="ltr">@{esc(insta.get("handle", ""))}</b>' if insta.get("handle") else ""
    else:
        qr = '<div class="qr qr--soon"><span></span><span></span><span></span><b>QR</b></div>'
        handle = ""

    def masthead(edition, number):
        # "The [crest] Times": the badge sits between the two words of the nameplate
        w1, w2 = meta["paper"].split(" ", 1)
        return f'''
  <header class="masthead">
    <div class="mast-top"><span>{edition}</span><span class="mast-top__en">DIYAKO · Restaurant &amp; Café</span></div>
    <div class="mast-main">
      <div class="ear ear--start"><b>تک‌شماره</b><small>یک لبخند</small></div>
      <h1 class="nameplate"><span>{esc(w1)}</span>{badge}<span>{esc(w2)}</span></h1>
      <div class="ear ear--end"><b>قیمت‌ها</b><small>به {esc(meta["unit"])}</small></div>
    </div>
    <p class="tagline"><svg class="orn"><use href="#o-fleuron"/></svg><span>{esc(meta["subtitle"])}</span><svg class="orn"><use href="#o-fleuron"/></svg></p>
    <div class="keyband"></div>
    <div class="dateline"><span>{edition}</span><span class="dateline__mid">صفحهٔ {fa(number)}</span><span>همهٔ قیمت‌ها به {esc(meta["unit"])}</span></div>
  </header>'''

    def footer():
        return f'''
  <footer class="pfoot">
    <div class="pfoot__insta">{qr}<div><b>دیاکو در اینستاگرام</b><span>تازه‌ها را آنجا ببینید</span>{handle}</div></div>
    <p class="pfoot__imprint"><span>صاحب‌امتیاز: رستوران دیاکو</span><svg class="orn-star"><use href="#o-star"/></svg><span>سردبیر: سرآشپز</span><svg class="orn-star"><use href="#o-star"/></svg><span>تیراژ: به تعدادِ مهمانانِ عزیز</span></p>
    <p class="noosh">نوش جان!</p>
  </footer>'''

    lead, second = feat
    lead_strip = f'''
  <section class="pfront">
    <article class="plead">
      <svg class="plead__art" viewBox="0 0 320 180" aria-hidden="true"><use href="#a-shishlik"/></svg>
      <div class="plead__text">
        <span class="kicker kicker--box">{esc(lead["kicker"])}</span>
        <h2>{esc(lead["headline"])}</h2>
        <p>{esc(lead["deck"])}</p>
      </div>
      <div class="stamp"><span>{esc(lead["stamp"])}</span><b>{price_html(lead["price"])}</b><small>{esc(meta["unit"])}</small></div>
    </article>
    <article class="psecond">
      <span class="kicker">{esc(second["kicker"])}</span>
      <h2>{esc(second["headline"])}</h2>
      <svg class="psecond__art" viewBox="0 0 320 120" aria-hidden="true"><use href="#a-bakhtiari"/></svg>
      <div class="price-line"><span class="item__name">{esc(second["item"])}</span><span class="item__dots"></span><span class="item__price">{price_html(second["price"])}</span></div>
    </article>
  </section>'''

    def priced_cards(cat):
        """A narrow classifieds column: each item as a small ad with its price under the name."""
        cards = "".join(
            f'<li class="ad-card ad-card--priced"><b>{esc(i["name"])}</b>'
            + (f'<small>{esc(i["note"])}</small>' if i.get("note") else "")
            + f'<span class="ad-card__price">{price_html(i.get("price"))}</span></li>'
            for i in cat["items"]
        )
        return (f'<div class="cat cat--classifieds" id="cat-{cat["id"]}"><h3 class="cat__title"><span>{esc(cat["title"])}</span></h3>'
                f'<ul class="classifieds">{cards}</ul></div>')

    def heading(section, icon):
        return (f'<div class="psec"><svg class="psec__icon"><use href="#i-{icon}"/></svg>'
                f'<span>{esc(section)}</span></div>')

    page1 = f'''
<div class="sheet sheet--food">
  {masthead("ویژه‌نامهٔ رستوران", 1)}
  {lead_strip}
  <div class="pcols pcols--3">
    <div class="pcol">{heading(pages["irani"]["section"], "skewer")}{column(cats("irani"))}</div>
    <div class="pcol">{heading(pages["intl"]["section"], "pizza")}{column(cats("intl"))}</div>
    <div class="pcol">{heading(pages["starters"]["section"], "salad")}{column(cats("starters"))}</div>
  </div>
  {footer()}
</div>'''

    page2 = f'''
<div class="sheet sheet--cafe">
  {masthead("ویژه\u200cنامه\u0654 کافه", 2)}
  <div class="pgrid">
    <div class="pflow">
      {heading(pages["coffee"]["section"], "cup")}{column(cats("coffee"))}
      {heading(pages["warm"]["section"], "tea")}{column(cats("warm"))}
      {heading(pages["cold"]["section"], "glass")}{column(cats("cold"))}
    </div>
    <aside class="pclassified">{heading(pages["hookah"]["section"], "hookah")}{"".join(category_html(c) if c.get("layout") == "classifieds" else priced_cards(c) for c in cats("hookah"))}</aside>
  </div>
  {footer()}
</div>'''

    css = read(SRC / "print.css")
    css = css.replace("/*KEY_STRIP_COPPER*/", key_strip("#a8652e", "#ffffff"))
    return f'''<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<title>منوی چاپی دیاکو · A4</title>
<style>
{font_faces(static=True)}
{css}
</style>
</head>
<body>
{sprite}
{page1}
{page2}
</body>
</html>
'''


def main():
    data = json.loads(read(ROOT / "data" / "menu.json"))
    (ROOT / "index.html").write_text(build_digital(data), encoding="utf-8")
    (ROOT / "print.html").write_text(build_print(data), encoding="utf-8")
    for name in ("index.html", "print.html"):
        print(f"{name}: {(ROOT / name).stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
