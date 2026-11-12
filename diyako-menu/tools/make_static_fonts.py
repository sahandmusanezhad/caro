#!/usr/bin/env python3
"""Cut static weights out of the variable fonts, for the PDF.

Chromium embeds variable fonts in a PDF as Type 3 fonts, which some print shops'
RIPs dislike; static instances embed as ordinary TrueType.

Needs: fonttools, brotli
Usage: python3 tools/make_static_fonts.py      (writes assets/fonts/static/*.woff2)
"""
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
OUT = FONTS / "static"

JOBS = {
    "vazirmatn": (600, 700, 800),
    "markazi": (600, 700),
}

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for family, weights in JOBS.items():
        for subset in ("arabic", "latin"):
            src = FONTS / f"{family}-{subset}.woff2"
            for w in weights:
                font = TTFont(src)
                static = instantiateVariableFont(font, {"wght": w}, updateFontNames=False)
                static.flavor = "woff2"
                dst = OUT / f"{family}-{subset}-{w}.woff2"
                static.save(dst)
                print(dst.relative_to(ROOT), dst.stat().st_size // 1024, "KB")
