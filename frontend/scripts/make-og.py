"""Render public/og.png (1200x630) for DriftWatch. Deterministic: fixed seed.

Needs Pillow + fontTools (brotli) and a prior `npm run build`, which leaves the
IBM Plex woff2 files from next/font in .next/static/media.
Run from frontend/:  python scripts/make-og.py
"""
import glob, io, math, random
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

BG, FG, MUTED, LINE = "#0a0e14", "#e6edf3", "#8a97a6", "#1e2733"
NEUTRAL, DRIFT, DRIFT_EDGE = "#7d8794", "#d4901f", "#8a5300"
W, H, S = 1200, 630, 2  # draw at 2x, downsample for smooth edges


def plex(family, size, weight=None):
    for f in glob.glob(".next/static/media/*.woff2"):
        t = TTFont(f)
        if t["name"].getDebugName(1) == family and ord("A") in (t.getBestCmap() or {}):
            buf = io.BytesIO(); t.flavor = None; t.save(buf); buf.seek(0)
            font = ImageFont.truetype(buf, size * S)
            if weight:
                font.set_variation_by_axes([weight])
            return font
    raise SystemExit(f"{family} not found: run `npm run build` first")


img = Image.new("RGB", (W * S, H * S), BG)
d = ImageDraw.Draw(img)

# drift cloud on the right, bleeding off the edge like the hero
random.seed(7)
cx, cy, k = 900 * S, 360 * S, 46 * S
for i in range(240):
    x, y, z = (random.gauss(0, 1) for _ in range(3))
    px, py = cx + k * (x * 0.85 + z * 0.52), cy + k * (y * 0.94 - z * 0.33)
    r = max(1.6, 3.0 + 0.8 * z) * S
    if i < 20:
        a, dist = random.uniform(-1.3, -0.4), random.uniform(110, 210) * S
        qx, qy = px + dist * math.cos(a), py + dist * math.sin(a)
        d.line([(px, py), (qx, qy)], fill=LINE, width=S)
        r = 5 * S
        d.ellipse([qx - r, qy - r, qx + r, qy + r], fill=DRIFT, outline=DRIFT_EDGE, width=S)
    else:
        d.ellipse([px - r, py - r, px + r, py + r], fill=NEUTRAL)

# text block, left aligned on a 72px margin
m = 72 * S
d.text((m, 200 * S), "DriftWatch", font=plex("IBM Plex Sans", 76, 600), fill=FG)
promise = plex("IBM Plex Sans", 36, 400)
d.text((m, 310 * S), "Notice when your LLM app", font=promise, fill=FG)
d.text((m, 358 * S), "gets quietly worse.", font=promise, fill=FG)
d.text((m, 470 * S), "Watches live outputs over time. Never changes requests or responses.",
       font=plex("IBM Plex Mono", 20), fill=MUTED)

img.resize((W, H), Image.LANCZOS).save("public/og.png", optimize=True)
print("wrote public/og.png")
