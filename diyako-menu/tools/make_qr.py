#!/usr/bin/env python3
"""Make the Instagram QR as crisp vector SVG in the menu's ink colour.

Needs: qrcode  (pip install qrcode); to read a QR from a screenshot also opencv-python-headless
Usage:
    python3 tools/make_qr.py https://instagram.com/<handle>
    python3 tools/make_qr.py --from-image screenshot.png     (reads the link out of an existing QR)
Writes assets/instagram-qr.svg; tools/build.py picks it up on the next build.
"""
import sys
from pathlib import Path

import qrcode

ROOT = Path(__file__).resolve().parent.parent
INK = "#1d1712"


def read_link(image_path):
    import cv2

    img = cv2.imread(str(image_path))
    data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
    if not data:
        sys.exit("no QR code found in " + str(image_path))
    return data


def svg_for(data):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    qr.add_data(data)
    qr.make(fit=True)
    m = qr.get_matrix()
    n = len(m)
    runs = []
    for y, row in enumerate(m):
        x = 0
        while x < n:
            if row[x]:
                start = x
                while x < n and row[x]:
                    x += 1
                runs.append(f"M{start} {y}h{x - start}v1h-{x - start}z")
            else:
                x += 1
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" shape-rendering="crispEdges" '
            f'role="img" aria-label="QR: {data}"><path fill="{INK}" d="{"".join(runs)}"/></svg>')


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--from-image":
        link = read_link(sys.argv[2])
    elif len(sys.argv) == 2:
        link = sys.argv[1]
    else:
        sys.exit(__doc__)
    out = ROOT / "assets" / "instagram-qr.svg"
    out.write_text(svg_for(link), encoding="utf-8")
    print("link:", link)
    print("wrote", out.relative_to(ROOT))
