#!/usr/bin/env python3
"""Crop a generated PDF down to its line-item table, for a release-note figure.

A screenshot of a whole A4 invoice is unreadable at the width a release note
gets. What the reader needs is the part that changed, at full size — and it
should come from the real PDF rather than from the HTML behind it, so the
figure shows what actually lands in a participant's inbox.

The table is found rather than measured by hand: our PDF templates draw it
under a full-width dark header bar, so the first such bar below the letterhead
is the top, and the table ends where a sustained run of blank rows begins.
Pass --box to override when that assumption does not hold.

Usage:
  scripts/crop-pdf-figure.py invoice.pdf --out docs/release-notes/screenshots/1.9.0-x.png
  scripts/crop-pdf-figure.py invoice.pdf --out x.png --page 2 --dpi 200
  scripts/crop-pdf-figure.py invoice.pdf --out x.png --box 96,426,1143,579

Needs `pdftoppm` (poppler-utils) on PATH and Pillow, which the backend already
depends on.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

DARK = 110          # below this grey level counts as the header bar
BLANK = 245         # above this counts as background
HEADER_WIDTH = 0.7  # the bar must span this fraction of the page
BLANK_RUN = 12      # blank rows that end the table


def detect_box(im: Image.Image) -> tuple[int, int, int, int]:
    grey = im.convert("L")
    w, h = grey.size
    px = grey.load()

    def is_bar(y: int) -> bool:
        return sum(1 for x in range(w) if px[x, y] < DARK) > w * HEADER_WIDTH

    # Skip the letterhead: a logo can also be a wide dark run.
    top = next((y for y in range(int(h * 0.15), h) if is_bar(y)), None)
    if top is None:
        sys.exit("No table header bar found. Pass --box x0,y0,x1,y1 explicitly.")

    y, blanks = top, 0
    while y < h - 1:
        y += 1
        blanks = blanks + 1 if all(px[x, y] > BLANK for x in range(w)) else 0
        if blanks >= BLANK_RUN:
            break
    xs = [x for x in range(w) if px[x, top + 3] < DARK]
    return min(xs), top, max(xs), y - blanks


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--pad", type=int, default=8)
    ap.add_argument("--box", help="x0,y0,x1,y1 in rendered pixels, instead of detection")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        stem = Path(tmp) / "page"
        subprocess.run(
            ["pdftoppm", "-png", "-r", str(args.dpi),
             "-f", str(args.page), "-l", str(args.page), str(args.pdf), str(stem)],
            check=True, stderr=subprocess.DEVNULL,
        )
        rendered = next(Path(tmp).glob("page*.png"))
        im = Image.open(rendered).convert("RGB")
        x0, y0, x1, y1 = (
            tuple(int(v) for v in args.box.split(",")) if args.box else detect_box(im)
        )
        pad = args.pad
        crop = im.crop((max(0, x0 - pad), max(0, y0 - pad),
                        min(im.width, x1 + pad + 1), min(im.height, y1 + pad)))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        crop.save(args.out)
        print(f"{args.out} ({crop.width}x{crop.height}) from {args.pdf} page {args.page}")


if __name__ == "__main__":
    main()
