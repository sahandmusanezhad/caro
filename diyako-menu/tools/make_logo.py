#!/usr/bin/env python3
"""Rebuild the Diyako leather badge as clean vector SVG.

The geometry was measured from a photo of the leather patch on the menu cover:

* the square-kufic logotype sits on a 22 x 15 grid (strokes 2 units, gaps 1 unit);
* the ring is a 24-unit Greek key: light key lines cut into a dark band;
* «رستوران دیاکو» arcs over the top, «Diyako Restaurant» under the bottom,
  five outlined stars sit between the top text and the logotype.

Text is shaped with HarfBuzz and converted to outlines, so the SVG needs no font.

Needs: fonttools, uharfbuzz, shapely  (pip install fonttools brotli uharfbuzz shapely)
Usage: python3 tools/make_logo.py <vazirmatn-arabic.woff2> <vazirmatn-latin.woff2> <out_dir>
Writes: logo-leather.svg (web, textured), logo-flat.svg (print, no filters),
        logo-ink.svg (one colour, currentColor), logo-mark.svg (favicon).
"""
import io
import math
import sys

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

R = 500.0                      # badge radius in SVG units (viewBox -500 .. 500)
RING_OUT, RING_IN = 452.0, 352.0
UNITS = 24                     # Greek key units around the ring
STITCH_R = 474.0


def fmt(v):
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


# ---------------------------------------------------------------- logotype
def logotype_path(u=26.0):
    """Square-kufic «دیاکو». Grid origin = top-left of the main body."""
    rects = [
        (0, 0, 9, 9),                                   # و head (square loop)
        (7, 9, 9, 10), (0, 10, 9, 12),                  # و tail
        (9, 7, 15, 9),                                  # baseline joining و ک ا
        (10, 0, 12, 12),                                # tall stroke
        (10, 10, 15, 12),                               # lower baseline (ی ا)
        (13, 0, 15, 9),                                 # second tall stroke
        (13, 0, 22, 2),                                 # top bar
        (16, 3, 22, 5), (20, 3, 22, 12), (16, 10, 22, 12),   # د
        (10, 13, 12, 15), (13, 13, 15, 15),             # the two dots of ی
    ]
    hole = box(2, 2, 7, 7)
    shape = unary_union([box(*r) for r in rects]).difference(hole)
    ox, oy = -11 * u, -6 * u          # centre the 22 x 12 main body on the badge centre
    parts = []
    geoms = getattr(shape, "geoms", [shape])
    for g in geoms:
        for ring in [g.exterior, *g.interiors]:
            pts = list(ring.coords)[:-1]
            d = "M" + " L".join(f"{fmt(ox + x * u)} {fmt(oy + y * u)}" for x, y in pts) + "Z"
            parts.append(d)
    return "".join(parts)


# ---------------------------------------------------------------- greek key
def key_unit_path():
    """One unit of the ring: the dark corridor around a light square spiral.

    (u, v) grid: u runs clockwise along the ring (period P), v runs inward from
    the outer edge (height H). Light lines are cut out of the dark band.
    """
    P, H, w = 13.0, 12.0, 1.25
    half = w / 2
    pos_u = [0.0, 3.25, 6.5, 9.75, 13.0]      # boundary, left side, stub, right side, next boundary
    top_v, mid_v, bot_v = 2.4, 6.0, 9.6
    light = [
        box(-half, 0, half, H),                                   # boundary between units
        box(P - half, 0, P + half, H),                            # next boundary
        box(pos_u[1] - half, bot_v - half, P, bot_v + half),      # bottom line, from the next boundary
        box(pos_u[1] - half, top_v - half, pos_u[1] + half, bot_v + half),   # left side
        box(pos_u[1] - half, top_v - half, pos_u[3] + half, top_v + half),   # top line
        box(pos_u[3] - half, top_v - half, pos_u[3] + half, mid_v + half),   # right side
        box(pos_u[2] - half, mid_v - half, pos_u[3] + half, mid_v + half),   # middle line
        box(pos_u[2] - half, 4.2, pos_u[2] + half, mid_v + half),            # inner stub
    ]
    dark = box(0, 0, P, H).difference(unary_union(light))

    span = 2 * math.pi / UNITS

    def theta(u):
        return u / P * span

    def rad(v):
        return RING_OUT - v / H * (RING_OUT - RING_IN)

    def pt(u, v):
        t, r = theta(u), rad(v)
        return r * math.sin(t), -r * math.cos(t)

    out = []
    geoms = getattr(dark, "geoms", [dark])
    for g in geoms:
        for ring in [g.exterior, *g.interiors]:
            pts = list(ring.coords)
            x0, y0 = pt(*pts[0])
            d = [f"M{fmt(x0)} {fmt(y0)}"]
            for (ua, va), (ub, vb) in zip(pts, pts[1:]):
                x, y = pt(ub, vb)
                if abs(va - vb) < 1e-9 and abs(ua - ub) > 1e-9:      # along the ring: arc
                    r = rad(va)
                    sweep = 1 if ub > ua else 0
                    d.append(f"A{fmt(r)} {fmt(r)} 0 0 {sweep} {fmt(x)} {fmt(y)}")
                else:                                                 # radial: straight line
                    d.append(f"L{fmt(x)} {fmt(y)}")
            out.append("".join(d) + "Z")
    return "".join(out)


# ---------------------------------------------------------------- text on arcs
def load_hb_font(path, wght):
    tt = TTFont(path)
    tt.flavor = None
    buf = io.BytesIO()
    tt.save(buf)
    face = hb.Face(buf.getvalue())
    font = hb.Font(face)
    font.set_variations({"wght": wght})
    return font, face.upem


def shape(font, text):
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {"kern": True, "liga": True})
    return buf.glyph_infos, buf.glyph_positions


def glyph_path(font, gid, matrix):
    pen = SVGPathPen(None, ntos=fmt)
    font.draw_glyph_with_pen(gid, TransformPen(pen, matrix))
    return pen.getCommands()


def arc_text(font, upem, text, size, radius, top=True, tracking=0.0):
    """Lay `text` along a circle. top=True: over the top, glyph tops outward,
    baseline on `radius`. top=False: under the bottom, glyph tops inward."""
    infos, positions = shape(font, text)
    s = size / upem
    # a subset font may lack the space glyph: shaping gives .notdef (gid 0) — draw nothing, keep a word gap
    advs = [(0.27 * upem if info.codepoint == 0 else p.x_advance) for info, p in zip(infos, positions)]
    xs, x = [], 0.0
    for adv in advs:
        xs.append(x)
        x += adv + (tracking * upem if adv else 0)
    total = x
    parts = []
    for info, p, x0, adv in zip(infos, positions, xs, advs):
        if info.codepoint == 0:
            continue
        if adv:
            anchor = x0 + adv / 2
        else:                                   # mark: anchor on its own ink
            ext = font.get_glyph_extents(info.codepoint)
            anchor = x0 + p.x_offset + ext.x_bearing + ext.width / 2
        along = (anchor - total / 2) * s        # distance along the arc from its middle
        ang = along / radius
        if top:
            cx, cy = radius * math.sin(ang), -radius * math.cos(ang)
            rot = ang
        else:
            cx, cy = radius * math.sin(ang), radius * math.cos(ang)
            rot = -ang
        c, si = math.cos(rot), math.sin(rot)
        # local glyph coords (font units, y up) -> centred on anchor, scaled, y flipped
        lx = x0 + p.x_offset - anchor
        ly = p.y_offset
        # point (gx, gy) -> local (s*(gx+lx), -s*(gy+ly)) -> rotate -> translate
        a, b = s * c, s * si
        cc, d = s * si, -s * c
        e = cx + c * s * lx + si * s * ly
        f = cy + si * s * lx - c * s * ly
        parts.append(glyph_path(font, info.codepoint, (a, b, cc, d, e, f)))
    return "".join(parts), total * s / radius


def star_path(cx, cy, ro, ri, rot):
    pts = []
    for k in range(10):
        r = ro if k % 2 == 0 else ri
        t = rot + k * math.pi / 5
        pts.append((cx + r * math.sin(t), cy - r * math.cos(t)))
    return "M" + " L".join(f"{fmt(x)} {fmt(y)}" for x, y in pts) + "Z"


# ---------------------------------------------------------------- assemble
def build(ar_path, la_path):
    fa, upem_a = load_hb_font(ar_path, 760)
    fl, upem_l = load_hb_font(la_path, 640)

    top_text, top_span = arc_text(fa, upem_a, "رستوران دیاکو", 82, 268, top=True)
    bot_text, bot_span = arc_text(fl, upem_l, "Diyako Restaurant", 60, 330, top=False, tracking=0.012)

    stars = []
    for k in range(5):
        t = math.radians((k - 2) * 16.5)
        r = 222
        stars.append(star_path(r * math.sin(t), -r * math.cos(t), 24.5, 10.5, t))

    unit = key_unit_path()
    return {
        "logotype": logotype_path(),
        "key_unit": unit,
        "top_text": top_text,
        "bot_text": bot_text,
        "stars": "".join(stars),
        "spans": (math.degrees(top_span), math.degrees(bot_span)),
    }


def engraving(parts, cls=""):
    uses = "".join(
        f'<use href="#dk-key" transform="rotate({fmt(k * 360 / UNITS)})"/>' for k in range(UNITS)
    )
    return (
        f'<g{cls}>'
        f'<path id="dk-key" d="{parts["key_unit"]}"/>{uses}'
        f'<path d="{parts["logotype"]}"/>'
        f'<path d="{parts["top_text"]}"/>'
        f'<path d="{parts["bot_text"]}"/>'
        f'<path d="{parts["stars"]}" fill="none" stroke="currentColor" stroke-width="5.5" stroke-linejoin="round"/>'
        "</g>"
    )


def svg_leather(parts, textured=True):
    defs = [
        '<radialGradient id="dk-leather" cx="38%" cy="30%" r="78%">'
        '<stop offset="0" stop-color="#e2aa6f"/><stop offset=".42" stop-color="#c17f43"/>'
        '<stop offset=".82" stop-color="#9d5b2b"/><stop offset="1" stop-color="#7d4520"/></radialGradient>',
        '<radialGradient id="dk-rim" cx="50%" cy="50%" r="50%">'
        '<stop offset=".9" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#3a1d0b" stop-opacity=".45"/></radialGradient>',
    ]
    if textured:
        defs.append(
            '<filter id="dk-grain" x="0" y="0" width="100%" height="100%">'
            '<feTurbulence type="fractalNoise" baseFrequency=".75" numOctaves="3" seed="7" result="n"/>'
            '<feColorMatrix in="n" type="matrix" values="0 0 0 0 .23  0 0 0 0 .12  0 0 0 0 .05  0 0 0 -1.6 1.15" result="g"/>'
            '<feComposite in="g" in2="SourceGraphic" operator="in"/></filter>'
        )
        defs.append(
            '<filter id="dk-deboss" x="-5%" y="-5%" width="110%" height="110%">'
            '<feMorphology in="SourceAlpha" operator="dilate" radius="1.6" result="d"/>'
            '<feGaussianBlur in="d" stdDeviation="2.2" result="b"/>'
            '<feFlood flood-color="#5b2f12" flood-opacity=".38"/><feComposite in2="b" operator="in" result="burn"/>'
            '<feOffset in="SourceAlpha" dy="2.6" result="o"/>'
            '<feFlood flood-color="#ffe2b8" flood-opacity=".5"/><feComposite in2="o" operator="in" result="hi"/>'
            '<feMerge><feMergeNode in="burn"/><feMergeNode in="hi"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
        )
    body = [
        '<circle r="500" fill="url(#dk-leather)"/>',
    ]
    if textured:
        body.append('<circle r="500" fill="#000" filter="url(#dk-grain)" opacity=".55"/>')
    body += [
        '<circle r="500" fill="url(#dk-rim)"/>',
        f'<circle r="{fmt(STITCH_R)}" fill="none" stroke="#5c3317" stroke-opacity=".55" stroke-width="5" '
        'stroke-dasharray="15 11" transform="translate(0 1.6)"/>',
        f'<circle r="{fmt(STITCH_R)}" fill="none" stroke="#f6dfbf" stroke-width="4" stroke-dasharray="15 11" stroke-linecap="round"/>',
        '<circle r="497" fill="none" stroke="#5e3416" stroke-opacity=".6" stroke-width="5"/>',
    ]
    filt = ' filter="url(#dk-deboss)"' if textured else ""
    body.append(f'<g fill="#3a2214" color="#3a2214"{filt}>{engraving(parts)}</g>')
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-500 -500 1000 1000" role="img" '
        'aria-label="رستوران دیاکو">'
        f'<defs>{"".join(defs)}</defs>{"".join(body)}</svg>'
    )


def svg_ink(parts):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-500 -500 1000 1000" role="img" '
        'aria-label="رستوران دیاکو">'
        f'<g fill="currentColor" color="currentColor">'
        '<circle r="497" fill="none" stroke="currentColor" stroke-width="6"/>'
        f'<circle r="{fmt(STITCH_R)}" fill="none" stroke="currentColor" stroke-width="3.5" stroke-dasharray="15 11"/>'
        f'{engraving(parts)}</g></svg>'
    )


if __name__ == "__main__":
    ar, la, out = sys.argv[1], sys.argv[2], sys.argv[3].rstrip("/")
    parts = build(ar, la)
    print("text spans (deg): top %.1f, bottom %.1f" % parts["spans"])
    mark = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-500 -500 1000 1000">'
        '<circle r="500" fill="#a8652e"/><circle r="452" fill="none" stroke="#f3ead8" stroke-width="22"/>'
        f'<path fill="#f3ead8" fill-rule="evenodd" transform="translate(0 -30) scale(1.18)" d="{parts["logotype"]}"/></svg>'
    )
    for name, svg in (
        ("logo-mark.svg", mark),
        ("logo-leather.svg", svg_leather(parts, True)),
        ("logo-flat.svg", svg_leather(parts, False)),
        ("logo-ink.svg", svg_ink(parts)),
    ):
        with open(f"{out}/{name}", "w", encoding="utf-8") as fh:
            fh.write(svg)
        print(name, len(svg), "bytes")
