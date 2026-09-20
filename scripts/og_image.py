"""Write site/og.png, the 1200 by 630 link-preview image: the site name and the
20-dot line (14 filled) on Berkeley Blue. Pillow only; the font is DejaVu Sans
from matplotlib's bundled fonts so the image is reproducible anywhere the
analysis runs. Usage: python scripts/og_image.py [--out site/og.png]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BLUE = (0, 50, 98)
GOLD = (253, 181, 21)
WHITE = (255, 255, 255)
MUTED = (200, 212, 228)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    try:
        import matplotlib

        base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        return ImageFont.truetype(str(base / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")), size)
    except Exception:  # noqa: BLE001 - fall back to Pillow's default face
        return ImageFont.load_default(size=size)


def draw(out: Path, *, filled: int = 14) -> Path:
    img = Image.new("RGB", (1200, 630), BLUE)
    d = ImageDraw.Draw(img)
    d.text((80, 90), "Berkeley Waitlist Odds", font=font(64, bold=True), fill=WHITE)
    d.text((80, 175), "Will you get off the waitlist?", font=font(38), fill=MUTED)
    r, gap, x0, y = 22, 20, 80, 320
    for i in range(20):
        cx = x0 + i * (2 * r + gap) + r
        if i < filled:
            d.ellipse((cx - r, y - r, cx + r, y + r), fill=GOLD)
        else:
            d.ellipse((cx - r, y - r, cx + r, y + r), outline=GOLD, width=4)
    d.text((80, 380), f"About {filled} in 20 comparable students got in by the last waitlist run", font=font(30), fill=WHITE)
    d.text((80, 520), "Historical odds by course and position, from enrollment snapshots", font=font(26), fill=MUTED)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, optimize=True)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=Path("site/og.png"))
    args = p.parse_args(argv)
    out = draw(args.out)
    print(out, out.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
