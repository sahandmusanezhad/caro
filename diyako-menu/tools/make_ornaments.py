#!/usr/bin/env python3
"""Draw the vintage print ornaments as SVG symbols (standard library only).

    python3 tools/make_ornaments.py      -> src/ornaments.svg

* o-flourish  a Victorian corner scroll (tapered strokes, spiral curls, ball ends)
* o-lamp-head / o-lamp-base   a gas street lamp; the pole between them is CSS, so the
                              lamp can be any height without stretching the drawing
* o-hand      a manicule (pointing hand), drawn pointing left for right-to-left text
* icons for the footer boxes
"""
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def f(v):
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def poly(pts):
    return "M" + "L".join(f"{f(x)} {f(y)}" for x, y in pts) + "Z"


def circle(cx, cy, r):
    return (f"M{f(cx - r)} {f(cy)}a{f(r)} {f(r)} 0 1 0 {f(2 * r)} 0a{f(r)} {f(r)} 0 1 0 {f(-2 * r)} 0Z")


# ------------------------------------------------------------------ tapered strokes
def bezier(p0, p1, p2, p3, n=60):
    out = []
    for i in range(n + 1):
        t = i / n
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


def spiral(start, heading, r0, turns, shrink, direction=1, n=90):
    """A logarithmic spiral that leaves `start` along `heading` and curls inward."""
    pts, x, y, h = [start], start[0], start[1], heading
    total = turns * 2 * math.pi
    for i in range(1, n + 1):
        t = total * i / n
        r = r0 * math.exp(-shrink * t)
        step = r * total / n
        h += direction * total / n
        x += step * math.cos(h)
        y += step * math.sin(h)
        pts.append((x, y))
    return pts


def taper(pts, w0, w1, ball=None, w_mid=None):
    """Outline a centre line whose width runs from w0 to w1 (optionally bulging to w_mid)."""
    n = len(pts)
    left, right = [], []
    for i, (x, y) in enumerate(pts):
        if i == 0:
            dx, dy = pts[1][0] - x, pts[1][1] - y
        elif i == n - 1:
            dx, dy = x - pts[i - 1][0], y - pts[i - 1][1]
        else:
            dx, dy = pts[i + 1][0] - pts[i - 1][0], pts[i + 1][1] - pts[i - 1][1]
        L = math.hypot(dx, dy) or 1
        nx, ny = -dy / L, dx / L
        t = i / (n - 1)
        w = w0 + (w1 - w0) * t
        if w_mid is not None:
            w += (w_mid - (w0 + w1) / 2) * math.sin(math.pi * t)
        left.append((x + nx * w / 2, y + ny * w / 2))
        right.append((x - nx * w / 2, y - ny * w / 2))
    d = poly(left + right[::-1])
    if ball:
        d += circle(pts[-1][0], pts[-1][1], ball)
    return d


def leaf(base, tip, width):
    """A pointed teardrop from base to tip."""
    (x0, y0), (x1, y1) = base, tip
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy)
    nx, ny = -dy / L * width, dx / L * width
    return (f"M{f(x0)} {f(y0)}C{f(x0 + dx * .35 + nx)} {f(y0 + dy * .35 + ny)} {f(x0 + dx * .8 + nx * .6)} {f(y0 + dy * .8 + ny * .6)} {f(x1)} {f(y1)}"
            f"C{f(x0 + dx * .8 - nx * .6)} {f(y0 + dy * .8 - ny * .6)} {f(x0 + dx * .35 - nx)} {f(y0 + dy * .35 - ny)} {f(x0)} {f(y0)}Z")


def scroll(p0, p1, p2, p3, r0, turns, shrink, direction, w0, w1, w_mid, ball):
    arm = bezier(p0, p1, p2, p3, 50)
    head = math.atan2(arm[-1][1] - arm[-2][1], arm[-1][0] - arm[-2][0])
    curl = spiral(arm[-1], head, r0, turns, shrink, direction)
    return taper(arm + curl[1:], w0, w1, ball=ball, w_mid=w_mid)


def flourish():
    """Top-right corner scroll in a 140 x 140 box (corner at the top right)."""
    parts = [
        # long arm along the top edge, curling down and back
        scroll((136, 5), (108, 2), (74, 12), (46, 10), 15, 1.35, 0.27, -1, 5.2, 1.0, 6.2, 2.9),
        # long arm down the side, curling left and back
        scroll((136, 5), (139, 33), (128, 66), (130, 94), 15, 1.35, 0.27, 1, 5.2, 1.0, 6.2, 2.9),
        # inner tendril, curling back toward the corner
        scroll((126, 14), (110, 18), (100, 30), (96, 46), 8.5, 1.25, 0.3, -1, 3.2, 0.8, 3.6, 1.9),
        # small counter-curls branching off each arm
        scroll((92, 9), (86, 16), (88, 26), (96, 26), 4.6, 1.1, 0.34, -1, 2.2, 0.7, None, 1.5),
        scroll((132, 50), (124, 54), (114, 50), (114, 42), 4.6, 1.1, 0.34, 1, 2.2, 0.7, None, 1.5),
        # leaves
        leaf((132, 9), (110, 31), 5.2),
        leaf((70, 14), (58, 26), 3.2),
        leaf((133, 70), (121, 82), 3.2),
    ]
    for cx, cy, r in ((106, 36, 2.4), (62, 30, 1.6), (125, 86, 1.6), (84, 36, 1.3), (118, 62, 1.3)):
        parts.append(circle(cx, cy, r))
    return "".join(parts)


# ------------------------------------------------------------------ street lamp
def lamp_head():
    """Lantern, collar and the top of the pole; 100 wide, 196 tall; pole is x 46..54."""
    d = []
    d.append(poly([(50, 0), (53.2, 12), (46.8, 12)]))                       # spike
    d.append(circle(50, 15.5, 4.6))                                          # finial ball
    d.append("M29 45C29 31 40 21 50 20C60 21 71 31 71 45Z")                  # bell roof
    d.append(poly([(19, 52), (81, 52), (75, 44), (25, 44)]))                 # brim
    d.append(poly([(24, 54), (76, 54), (65, 108), (35, 108)]))               # lantern frame
    d.append(poly([(34, 108), (66, 108), (58, 118), (42, 118)]))             # lantern base cone
    d.append(circle(50, 123, 6.4))                                           # collar ball
    d.append(poly([(46, 128), (54, 128), (54, 196), (46, 196)]))             # pole top
    d.append(poly([(42.5, 146), (57.5, 146), (57.5, 151), (42.5, 151)]))     # ring
    d.append(poly([(43.5, 170), (56.5, 170), (56.5, 174), (43.5, 174)]))     # ring
    black = "".join(d)
    # scroll brackets either side of the collar (stroked)
    brackets = ("M45 131C33 129 23 135 26 145C28 151 35 150 34 145C33.4 142 30.5 142 30 144"
                "M55 131C67 129 77 135 74 145C72 151 65 150 66 145C66.6 142 69.5 142 70 144")
    # glass panes cut in paper colour, split by a centre mullion and a cross bar
    panes = "".join([
        poly([(29.5, 58), (47.5, 58), (47.5, 79), (34, 79)]),
        poly([(34.8, 83), (47.5, 83), (47.5, 104), (38.8, 104)]),
        poly([(52.5, 58), (70.5, 58), (66, 79), (52.5, 79)]),
        poly([(52.5, 83), (65.2, 83), (61.2, 104), (52.5, 104)]),
    ])
    roof_line = "M33 40C35 32 42 26 50 25"
    return black, brackets, panes, roof_line


def lamp_base():
    """The foot of the lamp; 100 wide, 150 tall; pole enters at the top, x 46..54."""
    d = [
        poly([(46, 0), (54, 0), (54, 34), (46, 34)]),
        "M41 36C41 31 59 31 59 36C59 41 41 41 41 36Z",                         # knob
        "M45 40C45 72 39 92 31 104L69 104C61 92 55 72 55 40Z",                  # flared shaft
        poly([(27, 104), (73, 104), (73, 112), (27, 112)]),
        "M22 115C22 113 24 112 26 112L74 112C76 112 78 113 78 115L78 124L22 124Z",
        poly([(17, 126), (83, 126), (83, 148), (17, 148)]),                     # plinth
    ]
    white = "M31 117H69M23 132H77M23 141H77M48.6 46V96"
    return "".join(d), white


# ------------------------------------------------------------------ manicule
def hand():
    """Pointing hand, 100 x 52, pointing LEFT (index finger at x = 4)."""
    black = "".join([
        # index finger
        "M8 14H52V25H8C5 25 3.5 23 3.5 19.5C3.5 16 5 14 8 14Z",
        # thumb lying on the finger
        "M40 14C42 8 50 6 58 8L66 11V16H42Z",
        # back of the hand
        "M46 12H70V48H54C48 48 44 45 44 40V20Z",
        # folded fingers
        "M30 26H48V34H33C30.8 34 29.5 32.5 29.5 30S30.8 26 33 26Z",
        "M32 34.5H48V42H35C32.8 42 31.5 40.6 31.5 38.2S32.8 34.5 35 34.5Z",
        "M35 42.5H50V49.5H38C35.8 49.5 34.5 48.2 34.5 46S35.8 42.5 38 42.5Z",
        # cuff with ruffle
        "M70 9H84V51H70Z",
        "M85 6L90 10L95 6L97 13L93 17L97 22L93 27L97 32L93 37L97 42L95 49L90 45L85 49Z",
    ])
    white = "M46 25.6H28M48 34.2H31M49.5 42.2H34M42 16.5H64M76 12V48"
    return black, white


# ------------------------------------------------------------------ footer icons
def icon_camera():
    return ("M14 6H34C38.4 6 42 9.6 42 14V34C42 38.4 38.4 42 34 42H14C9.6 42 6 38.4 6 34V14C6 9.6 9.6 6 14 6Z"
            "M14 10C11.8 10 10 11.8 10 14V34C10 36.2 11.8 38 14 38H34C36.2 38 38 36.2 38 34V14C38 11.8 36.2 10 34 10Z"
            + circle(24, 24, 8.5) + circle(24, 24, 5) + circle(34, 14, 2.2))


def icon_receipt():
    return ("M10 4H38V44L34 41L30 44L26 41L22 44L18 41L14 44L10 41Z"
            "M15 12H33V15H15ZM15 19H33V22H15ZM15 26H27V29H15ZM15 33H30V36H15Z")


def icon_cup():
    return ("M8 18H36V30C36 37 30 42 23 42H21C14 42 8 37 8 30Z"
            "M36 21H39C42.3 21 45 23.7 45 27S42.3 33 39 33H35.5V29.5H39C40.4 29.5 41.5 28.4 41.5 27S40.4 24.5 39 24.5H36Z"
            "M4 44H40C40 46.2 38.2 48 36 48H8C5.8 48 4 46.2 4 44Z")


def icon_steam():
    return "M16 14C13 10 19 8 16 3M23 14C20 10 26 8 23 3M30 14C27 10 33 8 30 3"


def star(cx, cy, ro, ri, n=5, rot=-math.pi / 2):
    pts = []
    for k in range(2 * n):
        r = ro if k % 2 == 0 else ri
        t = rot + k * math.pi / n
        pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    return poly(pts)


def main():
    black, brackets, panes, roof_line = lamp_head()
    base, base_white = lamp_base()
    hb, hw = hand()
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" class="sprite" aria-hidden="true" focusable="false"><defs>
<symbol id="o-flourish" viewBox="0 0 140 140"><path fill="currentColor" d="{flourish()}"/></symbol>
<symbol id="o-lamp-head" viewBox="0 0 100 196"><path fill="currentColor" d="{black}"/><path d="{brackets}" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round"/><path fill="var(--paper, #fff)" d="{panes}"/><path d="{roof_line}" fill="none" stroke="var(--paper, #fff)" stroke-width="1.6" stroke-linecap="round"/></symbol>
<symbol id="o-lamp-base" viewBox="0 0 100 150"><path fill="currentColor" d="{base}"/><path d="{base_white}" fill="none" stroke="var(--paper, #fff)" stroke-width="1.6"/></symbol>
<symbol id="o-hand" viewBox="0 0 100 54"><path fill="currentColor" d="{hb}"/><path d="{hw}" fill="none" stroke="var(--paper, #fff)" stroke-width="1.5" stroke-linecap="round"/></symbol>
<symbol id="o-star" viewBox="0 0 20 20"><path fill="currentColor" d="{star(10, 10.6, 9.6, 3.9)}"/></symbol>
<symbol id="o-diamond" viewBox="0 0 40 12"><path fill="currentColor" d="{poly([(20, 0), (26, 6), (20, 12), (14, 6)])}{circle(6, 6, 2.2)}{circle(34, 6, 2.2)}"/></symbol>
<symbol id="ic-camera" viewBox="0 0 48 48"><path fill="currentColor" fill-rule="evenodd" d="{icon_camera()}"/></symbol>
<symbol id="ic-receipt" viewBox="0 0 48 48"><path fill="currentColor" fill-rule="evenodd" d="{icon_receipt()}"/></symbol>
<symbol id="ic-cup" viewBox="0 0 48 52"><path fill="currentColor" d="{icon_cup()}"/><path d="{icon_steam()}" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/></symbol>
</defs></svg>
'''
    out = ROOT / "src" / "ornaments.svg"
    out.write_text(svg, encoding="utf-8")
    print("wrote", out.relative_to(ROOT), len(svg), "bytes")


if __name__ == "__main__":
    main()
