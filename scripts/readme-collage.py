#!/usr/bin/env python3
"""Compose the README hero image: four app screenshots in a 2x2 grid.

The README shows one picture instead of a stack of screenshots. Capture the
four tiles in English against the seeded dev stack (from `frontend/`):

    export SCREENSHOT_BASE_URL=http://localhost:5173 \
           SCREENSHOT_API_URL=http://localhost:8001/api/v1 \
           SHOT_DIR=/tmp/readme-shots SHOT_MODE=viewport SHOT_WAIT=1500
    SHOT_NAME=overview SHOT_URL=/                npm run shot
    SHOT_NAME=balance  SHOT_URL=/dashboard       npm run shot
    SHOT_NAME=invoices SHOT_URL=/billing/invoices npm run shot
    SHOT_NAME=tariffs  SHOT_URL=/tariffs         npm run shot

then, from the repository root:

    python scripts/readme-collage.py /tmp/readme-shots docs/readme-collage.png

Needs Pillow.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

TILES = ["overview", "balance", "invoices", "tariffs"]
TILE_SIZE = (720, 450)  # half of the 1440x900 capture
GAP = 28
MARGIN = 40
RADIUS = 14
BACKGROUND = (244, 246, 242, 255)
BORDER = (214, 220, 212, 255)
SCALE = 2  # draw at 2x, then downsample, for smooth rounded corners


def tile(source: Path) -> Image.Image:
    """One screenshot, scaled, with rounded corners and a hairline border."""
    w, h = TILE_SIZE[0] * SCALE, TILE_SIZE[1] * SCALE
    image = Image.open(source).convert("RGBA").resize((w, h), Image.LANCZOS)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), RADIUS * SCALE, fill=255)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(image, (0, 0), mask)
    ImageDraw.Draw(out).rounded_rectangle(
        (0, 0, w - 1, h - 1), RADIUS * SCALE, outline=BORDER, width=SCALE
    )
    return out


def main(source_dir: Path, target: Path) -> None:
    cols = 2
    rows = 2
    tw, th = TILE_SIZE[0] * SCALE, TILE_SIZE[1] * SCALE
    gap, margin = GAP * SCALE, MARGIN * SCALE
    width = margin * 2 + cols * tw + (cols - 1) * gap
    height = margin * 2 + rows * th + (rows - 1) * gap

    canvas = Image.new("RGBA", (width, height), BACKGROUND)
    shadows = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadows)
    placed = []
    for index, name in enumerate(TILES):
        x = margin + (index % cols) * (tw + gap)
        y = margin + (index // cols) * (th + gap)
        placed.append((tile(source_dir / f"{name}.png"), x, y))
        shadow_draw.rounded_rectangle(
            (x, y + 8 * SCALE, x + tw, y + th + 8 * SCALE),
            RADIUS * SCALE,
            fill=(20, 40, 28, 60),
        )
    canvas.alpha_composite(shadows.filter(ImageFilter.GaussianBlur(14 * SCALE)))
    for image, x, y in placed:
        canvas.alpha_composite(image, (x, y))

    final = canvas.resize((width // SCALE, height // SCALE), Image.LANCZOS).convert("RGB")
    final.save(target, optimize=True)
    print(f"wrote {target} ({final.width}x{final.height})")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
