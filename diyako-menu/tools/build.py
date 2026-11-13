#!/usr/bin/env python3
"""Build the Diyako menu, vintage black-and-white print style, from data/menu.json.

    python3 tools/build.py

Writes:
    index.html   the digital menu — one self-contained file (fonts, logo, ornaments inlined)
    print.html   the paper menu, two A4 sheets; tools/make_pdf.js turns it into the PDF

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
ZWNJ = "‌"


def fa(n):
    """1250 -> ۱٬۲۵۰"""
    s = f"{n:,}".replace(",", "٬") if isinstance(n, int) else str(n)
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
    return re.sub(r"<\?xml[^>]*>", "", svg).strip()


# ------------------------------------------------------------------ fonts
ARABIC = "U+0600-06FF,U+0750-077F,U+08A0-08FF,U+200C-200E,U+2010-2011,U+204F,U+2E41,U+FB50-FDFF,U+FE70-FEFC"
LATIN = "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+20AC,U+2122,U+2212,U+2215,U+FEFF,U+FFFD"
FONTS = [
    ("Vazirmatn", "vazirmatn-arabic.woff2", "100 900", ARABIC),
    ("Vazirmatn", "vazirmatn-latin.woff2", "100 900", LATIN),
    ("Lalezar", "lalezar-arabic.woff2", "400", ARABIC),
    ("Markazi", "markazi-arabic.woff2", "400 700", ARABIC),
    ("Markazi", "markazi-latin.woff2", "400 700", LATIN),
    ("Ruqaa", "arefruqaa-arabic-700.woff2", "700", ARABIC),
]
STATIC_WEIGHTS = {"Vazirmatn": (600, 700, 800), "Markazi": (600, 700)}


def font_faces(static=False):
    """@font-face rules with the fonts inlined; static=True uses the fixed weights in
    assets/fonts/static (tools/make_static_fonts.py), which embed cleanly in a PDF."""
    out = []

    def face(family, path, weight, urange):
        data = base64.b64encode(path.read_bytes()).decode()
        out.append(f"@font-face{{font-family:'{family}';font-style:normal;font-weight:{weight};font-display:swap;"
                   f"src:url(data:font/woff2;base64,{data}) format('woff2');unicode-range:{urange}}}")

    for family, fname, weight, urange in FONTS:
        if static and family in STATIC_WEIGHTS:
            stem = fname[: -len(".woff2")]
            for w in STATIC_WEIGHTS[family]:
                face(family, ASSETS / "fonts" / "static" / f"{stem}-{w}.woff2", w, urange)
        else:
            face(family, ASSETS / "fonts" / fname, weight, urange)
    return "\n".join(out)


# ------------------------------------------------------------------ building blocks
def corners():
    return "".join(
        f'<svg class="corner corner--{c}" aria-hidden="true"><use href="#o-flourish"/></svg>'
        for c in ("tr", "tl", "br", "bl")
    )


def lamp(side):
    return (f'<div class="lamp lamp--{side}" aria-hidden="true">'
            '<svg class="lamp__head" viewBox="0 0 100 196"><use href="#o-lamp-head"/></svg>'
            '<i class="lamp__pole"></i>'
            '<svg class="lamp__base" viewBox="0 0 100 150"><use href="#o-lamp-base"/></svg></div>')


def hand():
    return '<svg class="hand" viewBox="0 0 100 54" aria-hidden="true"><use href="#o-hand"/></svg>'


def star():
    return '<svg class="st" viewBox="0 0 20 20" aria-hidden="true"><use href="#o-star"/></svg>'


def item_li(it):
    note = f'<small>{esc(it["note"])}</small>' if it.get("note") else ""
    tag = f'<em class="tag">{esc(it["tag"])}</em>' if it.get("tag") else ""
    price = price_html(it.get("price"))
    q = norm(it["name"] + " " + it.get("note", ""))
    tail = (f'<span class="dots" aria-hidden="true"></span><span class="price">{price}</span>'
            if price else "")
    return f'<li class="item" data-q="{esc(q)}"><span class="name">{esc(it["name"])}{tag}{note}</span>{tail}</li>'


def ht_box(cat):
    """Halftone box, like the reference's «SIGNATURE SAUCES»."""
    shared = cat.get("price")
    lines = []
    for it in cat["items"]:
        p = price_html(it.get("price"))
        q = norm(it["name"] + " " + it.get("note", ""))
        parts = [esc(x.strip()) for x in it["name"].split("/")]
        name = '<i class="sep">·</i>'.join(f"<span>{x}</span>" for x in parts)
        price = f'<span class="ht__price">{p}</span>' if p else ""
        lines.append(f'<li class="ht__item" data-q="{esc(q)}"><b>{name}</b>{price}</li>')
    head_price = (f'<span class="ht__each">هر سرویس <b>{fa(shared)}</b></span>' if shared else "")
    return (f'<aside class="ht cat" id="cat-{cat["id"]}" aria-label="{esc(cat["title"])}">'
            f'<h3 class="ht__title">{esc(cat["title"])}</h3>{head_price}'
            f'<ul class="ht__list">{"".join(lines)}</ul></aside>')


def category(cat, show_title=True):
    if cat.get("box"):
        return ht_box(cat)
    title = ""
    if show_title:
        note = f' <small>({esc(cat["note"])})</small>' if cat.get("note") else ""
        title = f'<h3 class="sub">{esc(cat["title"])}{note}</h3>'
    long = " cat--long" if len(cat["items"]) > 10 else ""
    return (f'<div class="cat{long}" id="cat-{cat["id"]}">{title}'
            f'<ul class="items">{"".join(item_li(i) for i in cat["items"])}</ul></div>')


def sec_head(title, hid):
    return (f'<header class="head">{star()}<h2 id="{hid}">{esc(title)}</h2>{star()}</header>'
            '<div class="head__rule" aria-hidden="true"></div>')


def section(sec, extra_cls=""):
    cats = sec["categories"]
    single = len(cats) == 1
    body = "".join(category(c, show_title=not single) for c in cats)
    return (f'<section id="{sec["id"]}" class="sec sec--{sec["id"]} {extra_cls}" aria-labelledby="h-{sec["id"]}">'
            f'{sec_head(sec["title"], "h-" + sec["id"])}<div class="flow">{body}</div></section>')


def masthead(d, edition=None):
    m, meta = d["masthead"], d["meta"]
    badge = svg_inner(read(ASSETS / "logo-ink.svg")).replace("<svg ", '<svg class="badge" ', 1)
    sub = esc(m["subline"]) if not edition else esc(edition)
    return f'''
<header class="mast">
  <div class="mast__row">
    <div class="ear ear--start"><p class="ear__big">{esc(m["ear_start"])}</p><p class="ear__small">{esc(m["ear_start_small"])}</p></div>
    <div class="mast__badge">{badge}</div>
    <div class="ear ear--end"><p class="ear__big">{esc(m["ear_end"])}</p><p class="ear__small ear__small--en">{esc(m["ear_end_small"])}</p></div>
  </div>
  <div class="ribbon"><span>{esc(m["ribbon"])}</span></div>
  <p class="mast__sub">{sub}</p>
</header>'''


def strip(d, left, date=False):
    m = d["masthead"]
    first = '<span data-today>شمارهٔ امروز</span>' if date else f'<span>{esc(left)}</span>'
    return (f'<div class="strip">{first}<b>{esc(m["welcome"])}</b><span>{esc(m["follow"])}</span></div>')


def hero(h, cls=""):
    return (f'<div class="hero {cls}"><p class="hero__line"><span class="script">{esc(h["script"])}</span>{hand()}</p>'
            f'<p class="hero__title">{esc(h["title"])}</p><p class="hero__sub">{esc(h["sub"])}</p></div>')


def specials(d):
    sp, unit = d["specials"], d["meta"]["unit"]
    boxes = []
    for it in sp["items"]:
        q = norm(it["name"] + " " + it.get("note", ""))
        boxes.append(
            f'<article class="sp sp--{it["style"]}" data-q="{esc(q)}"><span class="sp__label">{esc(it["label"])}</span>'
            f'<b class="sp__name">{esc(it["name"])}</b><span class="sp__note">{esc(it["note"])}</span>'
            f'<span class="sp__price">{price_html(it["price"])}</span></article>'
        )
    return f'''
<section id="specials" class="specials" aria-labelledby="h-specials">
  <h2 class="banner" id="h-specials"><span class="script">{esc(sp["script"])}</span>{hand()}<span class="banner__title">{esc(sp["title"])}</span></h2>
  <div class="sp-grid">{"".join(boxes)}</div>
  <p class="fine">همهٔ قیمت‌ها به {esc(unit)} است.</p>
</section>'''


def qr_block(d):
    qr_file = ASSETS / "instagram-qr.svg"
    if qr_file.exists():
        return svg_inner(read(qr_file)).replace("<svg ", '<svg class="qr" ', 1)
    return ('<div class="qr qr--soon" role="img" aria-label="کد QR اینستاگرام">'
            '<span></span><span></span><span></span><b>QR</b></div>')


def footer(d):
    insta = d["meta"].get("instagram", {})
    boxes = []
    for fb in d["footer"]:
        extra = ""
        if fb.get("qr"):
            link = (f'<a class="foot__link" href="{esc(insta["url"])}" rel="noopener" dir="ltr">@{esc(insta.get("handle", ""))}</a>'
                    if insta.get("url") else "")
            extra = qr_block(d) + link
        boxes.append(
            f'<div class="foot__box"><h2 class="foot__bar">{esc(fb["title"])}</h2>'
            f'<div class="foot__body"><svg class="foot__icon" aria-hidden="true"><use href="#ic-{fb["icon"]}"/></svg>'
            f'<p>{esc(fb["text"])}</p>{extra}</div></div>'
        )
    return f'<footer class="foot">{"".join(boxes)}</footer>'


# ------------------------------------------------------------------ digital page
def build_digital(d):
    secs = {s["id"]: s for s in d["sections"]}
    sprite = read(SRC / "ornaments.svg")
    ink = svg_inner(read(ASSETS / "logo-ink.svg")).replace("<svg ", '<svg class="mini-badge" ', 1)
    ink = ink.replace('id="dk-key"', 'id="dk-key-mini"').replace('href="#dk-key"', 'href="#dk-key-mini"')
    favicon = "data:image/svg+xml," + read(ASSETS / "logo-mark.svg").replace("#", "%23").replace('"', "'")
    nav = ['<a href="#irani">ایرانی</a>', '<a href="#specials">ویژه‌ها</a>']
    nav += [f'<a href="#{s["id"]}">{esc(s["nav"])}</a>' for s in d["sections"] if s["id"] != "irani"]
    css = read(SRC / "style.css")
    js = read(SRC / "app.js")

    body = f'''
<div class="sheet" id="top">
  {corners()}
  {masthead(d)}
  {strip(d, "", date=True)}
  <div class="nav-sentinel" aria-hidden="true"></div>
  <nav class="nav" aria-label="بخش‌های منو">
    <div class="nav__inner">
      <a class="nav__home" href="#top" aria-label="بالای صفحه">{ink}</a>
      <div class="nav__list">{"".join(nav)}</div>
      <button type="button" class="nav__search" aria-label="جستجو در منو" aria-expanded="false">
        <svg class="ic-s" viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5"/></svg>
        <svg class="ic-x" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>
      </button>
    </div>
    <div class="search" hidden><input type="search" placeholder="جستجو در منو… مثلاً لاته یا کوبیده" aria-label="جستجو در منو" autocomplete="off"></div>
  </nav>
  <main>
    <p class="search-empty" hidden>چیزی پیدا نشد؛ شاید با نامِ دیگری در منو آمده باشد.</p>
    <div class="lampframe">
      {lamp("s")}
      {hero(d["hero"])}
      {section(secs["irani"])}
      {lamp("e")}
    </div>
    {specials(d)}
    {section(secs["intl"])}
    {section(secs["starters"])}
    {hero(d["cafe_hero"], "hero--cafe")}
    {section(secs["coffee"])}
    {section(secs["warm"])}
    {section(secs["cold"])}
    {section(secs["hookah"])}
  </main>
  {footer(d)}
</div>'''

    return f'''<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>منوی دیاکو · رستوران و کافه</title>
<meta name="description" content="منوی رستوران و کافهٔ دیاکو: غذای ایرانی، پیتزا و برگر، قهوه، چای، شیک و قلیان.">
<meta name="theme-color" content="#111111">
<link rel="icon" type="image/svg+xml" href="{favicon}">
<style>
{font_faces()}
{css}
</style>
</head>
<body>
{sprite}{body}
<script>
{js}
</script>
</body>
</html>
'''


# ------------------------------------------------------------------ print (A4)
def build_print(d):
    secs = {s["id"]: s for s in d["sections"]}
    sprite = read(SRC / "ornaments.svg")

    def cats(sid, *ids):
        return [c for c in secs[sid]["categories"] if not ids or c["id"] in ids]

    def col(title, categories, hid):
        return (f'<div class="pcol">{sec_head(title, hid)}'
                f'{"".join(category(c, show_title=len(categories) > 1) for c in categories)}</div>')

    page1 = f'''
<div class="page page--food">
  {corners()}
  {masthead(d, "ویژه\u200cنامه\u0654 رستوران · غذای ایرانی و فرنگی")}
  {strip(d, "صفحه\u0654 ۱ · رستوران")}
  <div class="lampframe">
    {lamp("s")}
    {hero(d["hero"])}
    <div class="lampbody">
      {col(secs["irani"]["title"], cats("irani"), "p-irani")}
      {col(secs["intl"]["title"], cats("intl", "pizza", "burger", "pasta"), "p-intl")}
    </div>
    {lamp("e")}
  </div>
  <div class="prow">
    {col(secs["starters"]["title"], cats("starters", "salad"), "p-salad")}
    <div class="pcol pcol--plain">{"".join(category(c) for c in cats("starters", "soup", "fried") + cats("intl", "steak"))}</div>
    <div class="pcol pcol--plain pcol--box">{"".join(category(c) for c in cats("starters", "soft-drinks"))}</div>
  </div>
  {specials(d)}
  {footer(d)}
</div>'''

    page2 = f'''
<div class="page page--cafe">
  {corners()}
  {masthead(d, "ویژه\u200cنامه\u0654 کافه · قهوه، چای، شیک و قلیان")}
  {strip(d, "صفحه\u0654 ۲ · کافه")}
  <div class="lampframe">
    {lamp("s")}
    {hero(d["cafe_hero"])}
    <div class="lampbody lampbody--3">
      {col(secs["coffee"]["title"], cats("coffee", "espresso", "milk-coffee", "cold-coffee", "brewed"), "p-coffee")}
      {col(secs["warm"]["title"], cats("warm"), "p-warm")}
      {col(secs["cold"]["title"], cats("cold"), "p-cold")}
    </div>
    {lamp("e")}
  </div>
  <div class="phookah">
    <div class="phookah__row">{"".join(category(c) for c in cats("hookah") + cats("coffee", "dessert"))}</div>
  </div>
  {footer(d)}
</div>'''

    css = read(SRC / "print.css")
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
{sprite}{page1}{page2}
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
