"""Audit the sorts and fonts for the problems that are easy to miss: glyphs
built from the wrong impressions, real glyphs the scans have but the fonts
do not use, and glyphs whose weight is off.  Run after build.sh:

    python3 audit.py

Prints a report and writes contact sheets to work/audit-*.png:

1. OCR disagreement: sorts whose impressions Tesseract confidently reads as
   another letter (the bold G hid in the bold O that way).  Greek, symbols
   and ligatures always show up (OCR has no Greek); look for Latin letters.
2. Unused real glyphs: clusters of >= 5 impressions in no sort that look
   like no master (audit-unused.png).  This found the question mark, the
   bold hyphen, Γ Σ Φ θ, Fraktur and script capitals and ü á ä.
3. Weight: glyphs whose stroke is > 12% off their class (lowercase,
   capitals, figures, Greek) in each text font.  Stem-only glyphs (1 I J)
   always read heavy, the g light.
4. Mixed masters: masters with an unusually large share of half-inked
   pixels, a double image of two shapes averaged (audit-blur.png; the 9 pt
   X with a bold one).
"""
import os
import pickle
import unicodedata
from collections import Counter

import numpy as np
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.freetypePen import FreeTypePen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
FONTS = os.path.join(HERE, "fonts")


def load(name):
    return pickle.load(open(os.path.join(WORK, name), "rb"))


def sheet(items, path, cols=10, cell=120):
    """items: [(label, image in [0,1])] -> a contact sheet."""
    rows = max(1, (len(items) + cols - 1) // cols)
    out = Image.new("L", (cols * cell, rows * cell), 255)
    d = ImageDraw.Draw(out)
    for j, (label, img) in enumerate(items):
        im = Image.fromarray((255 - 255 * np.clip(np.asarray(img, dtype=float), 0, 1))
                             .astype(np.uint8))
        im.thumbnail((cell - 6, cell - 24))
        x, y = (j % cols) * cell, (j // cols) * cell
        out.paste(im, (x + 3, y + 3))
        d.text((x + 3, y + cell - 13), label[:22], fill=0)
    out.save(path)


def normalised(img):
    a = np.asarray(img, dtype=float) > 0.5
    ys, xs = np.nonzero(a)
    if len(ys) == 0:
        return None, 1.0
    a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    im = Image.fromarray((a * 255).astype(np.uint8)).resize((32, 32), Image.BILINEAR)
    return np.asarray(im) > 127, a.shape[1] / a.shape[0]


def ocr_disagreement(inst, members, sorts):
    print("1. sorts whose impressions OCR reads as another letter (>= 8%):")
    for key, cids in sorted(sorts.items(), key=lambda kv: str(kv[0])):
        ms = [inst[i] for c in cids for i in members[c]]
        conf = [m["ch"] for m in ms if m["ch"] and len(m["ch"]) == 1 and m["conf"] > 90]
        if len(ms) < 5 or not conf:
            continue
        c = Counter(conf)
        other = [(ch, n) for ch, n in c.most_common()
                 if ch.isascii() and ch.isalpha() and ch.lower() != key[0].lower()]
        if other and other[0][1] >= 3 and other[0][1] / len(conf) > 0.08 \
                and key[0].isascii() and key[0].isalpha():
            print(f"   {key}: {other[0][1]} of {len(conf)} read as {other[0][0]!r}")


def unused(rows, sorts, masters, inst, members):
    used = {c for cs in sorts.values() for c in cs}
    refs = [(normalised(m["img"])) for m in masters.values()]
    found = []
    for r in rows:
        if r["id"] in used or r["n"] < 5:
            continue
        n, asp = normalised(r["mean"])
        if n is None:
            continue
        best = max(((n & rn).sum() / max(1, (n | rn).sum())
                    * (1.0 if abs(np.log(asp / ra)) < 0.25 else 0.5))
                   for rn, ra in refs if rn is not None)
        if best < 0.6:
            ocr = Counter(inst[i]["ch"] for i in members[r["id"]] if inst[i]["ch"])
            found.append((r["n"], r["id"], "".join(k for k, _ in ocr.most_common(2)), r["mean"]))
    found.sort(key=lambda f: -f[0])
    print(f"2. unused clusters (>= 5 impressions) unlike any master: {len(found)}, "
          f"{sum(f[0] for f in found)} impressions (work/audit-unused.png)")
    sheet([(f"#{c} n{n} {o}", m) for n, c, o, m in found],
          os.path.join(WORK, "audit-unused.png"))


def stroke(gs, name):
    pen, bp = FreeTypePen(gs), BoundsPen(gs)
    gs[name].draw(pen)
    gs[name].draw(bp)
    if not bp.bounds:
        return None
    x0, y0, x1, y1 = bp.bounds
    k = 0.4
    a = pen.array(width=int((x1 - x0) * k) + 8, height=int((y1 - y0) * k) + 8,
                  transform=(k, 0, 0, k, -x0 * k + 4, -y0 * k + 4), contain=False) > 0.5
    if a.sum() < 20:
        return None
    e = ndimage.distance_transform_edt(np.pad(a, 1))
    return 2 * np.percentile(e[e > 0], 90) / k


def glyph_class(c):
    if c.isdigit():
        return "figure"
    if "GREEK" in unicodedata.name(c, ""):
        return "greek-" + ("upper" if c.isupper() else "lower")
    if c.isascii() and c.isalpha():
        return "upper" if c.isupper() else "lower"
    return None


def weights():
    print("3. stroke weight > 12% off its class:")
    for f in sorted(os.listdir(FONTS)):
        if not f.endswith(".otf") or "Math" in f:
            continue
        t = TTFont(os.path.join(FONTS, f))
        gs = t.getGlyphSet()
        by = {}
        for cp, name in t.getBestCmap().items():
            k = glyph_class(chr(cp))
            s = stroke(gs, name) if k else None
            if s:
                by.setdefault(k, []).append((chr(cp), s))
        out = []
        for k, v in by.items():
            med = np.median([s for _, s in v])
            out += [f"{c} {s / med:.2f}" for c, s in v if abs(s / med - 1) > 0.12]
        print(f"   {f}: {', '.join(sorted(out)) or 'none'}")


def mixed(masters):
    res = []
    for k, m in masters.items():
        a = np.asarray(m["img"], dtype=float)
        ink = (a > 0.5).sum()
        if ink >= 200 and m["n"] >= 10:
            res.append((((a > 0.15) & (a < 0.85)).sum() / ink, k, m))
    med = np.median([r[0] for r in res])
    worst = sorted((r for r in res if r[0] > 1.45 * med), key=lambda r: -r[0])
    print(f"4. masters with a double image (half-inked share > 1.45 x median): {len(worst)} "
          f"(work/audit-blur.png; the old-style figures are resampled and always show)")
    for g, k, m in worst:
        print(f"   {k} n={m['n']} {g / med:.2f}x")
    sheet([(f"{k[0]} {k[1]}{k[2]} n{m['n']}", m["img"]) for _, k, m in worst],
          os.path.join(WORK, "audit-blur.png"))


def main():
    inst = load("instances.pkl")
    clusters = load("clusters.pkl")
    members = {c["id"]: c["members"] for c in clusters}
    sorts, rows, masters = load("sorts.pkl"), load("classified.pkl"), load("masters.pkl")
    ocr_disagreement(inst, members, sorts)
    unused(rows, sorts, masters, inst, members)
    weights()
    mixed(masters)


if __name__ == "__main__":
    main()
