"""U286: draw the desktop icon of the live HUD (disposable output, reproducible from this script).

The icon repeats the HUD's own picture so it is recognisable at 16 px: a dark tile, the five-engine
donut in the HUD colors, the UAOS hub, and the green Flagman satellite on its orbit.
Usage: python make_hud_icon.py <out.ico>
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 1024  # drawn 4x larger than the 256 px icon, then downsampled for smooth edges
COLORS = ["#60a5fa", "#f59e0b", "#a78bfa", "#34d399", "#f472b6"]  # codex, claude, agy, haiku, ollama (HUD COLORS)
SHARES = [0.34, 0.28, 0.16, 0.12, 0.10]  # fixed decorative split; the icon shows identity, not live data


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([24, 24, S - 24, S - 24], radius=210, fill="#0f1115", outline="#2c313c", width=18)
    box = [200, 200, S - 200, S - 200]
    start = -90.0
    for color, share in zip(COLORS, SHARES):
        end = start + share * 360
        d.arc(box, start + 2.5, end - 2.5, fill=color, width=120)
        start = end
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([700, 150, 880, 330], fill="#22c55e")
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(40)))
    d = ImageDraw.Draw(img)
    d.ellipse([735, 185, 845, 295], fill="#22c55e", outline="#0f1115", width=14)  # Flagman satellite
    d.ellipse([400, 400, S - 400, S - 400], fill="#e8eaed")  # UAOS hub
    d.ellipse([455, 455, S - 455, S - 455], fill="#0f1115")
    return img.resize((256, 256), Image.LANCZOS)


def main() -> int:
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    draw().save(out, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
