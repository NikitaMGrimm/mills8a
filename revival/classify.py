"""Propose a (glyph, style, size) label for every cluster.

style: R roman, I italic, B bold -- from measured slant and stroke weight.
size:  ratio of the cluster's height to the body-size cluster of the same
       glyph and style (1.0 = 11pt body; ~0.73 = 8pt; ~0.6 = 6/7pt).

Writes labels.tsv (to be corrected by hand) and work/review-*.png sheets
showing each cluster with its proposed label.
"""
import os
import pickle

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")


def slant(mean):
    """Shear angle (deg, positive = leaning right) that makes vertical
    strokes most vertical: maximises the peakiness of the column profile."""
    bm = mean > 0.5
    ys, xs = np.nonzero(bm)
    if len(ys) < 20:
        return 0.0
    yc = ys - ys.mean()
    best = (-1, 0.0)
    for a in np.arange(-6, 26, 1.0):
        x = np.round(xs + yc * np.tan(np.radians(a))).astype(int)
        prof = np.bincount(x - x.min())
        score = (prof.astype(float) ** 2).sum()
        if score > best[0]:
            best = (score, a)
    return best[1]


def stroke(mean):
    """Mean stroke thickness in px: 2 * max of the distance transform along
    the medial region, approximated by the 75th percentile of the EDT."""
    bm = mean > 0.5
    if bm.sum() < 20:
        return 0.0
    edt = ndimage.distance_transform_edt(bm)
    return 2 * np.percentile(edt[bm], 90)


def main():
    cl = pickle.load(open(os.path.join(WORK, "clusters.pkl"), "rb"))
    rows = []
    for c in cl:
        bm = c["mean"] > 0.5
        ys, xs = np.nonzero(bm)
        if len(ys) == 0:
            continue
        h = ys.max() - ys.min() + 1
        w = xs.max() - xs.min() + 1
        top = c["top"] + ys.min()
        c.update(h=h, w=w, ttop=top, bottom=top + h, slant=slant(c["mean"]),
                 stroke=stroke(c["mean"]),
                 ocr1=c["ocr"][0][0] if c["ocr"] else None)
        rows.append(c)

    for c in rows:
        c["style"] = "I" if c["slant"] >= 8 else "R"
    # Body reference per (ocr label, style): the most populous cluster.
    ref = {}
    for c in rows:
        key = (c["ocr1"], c["style"])
        if key not in ref or c["n"] > ref[key]["n"]:
            ref[key] = c
    for c in rows:
        r = ref[(c["ocr1"], c["style"])]
        c["size"] = round(c["h"] / r["h"], 2)
        # bold: noticeably thicker strokes than the reference at similar size
        if c["style"] == "R" and c["size"] > 0.9 and c["stroke"] > 1.3 * r["stroke"]:
            c["style"] = "B"

    with open(os.path.join(HERE, "labels.tsv"), "w") as f:
        f.write("# id\tn\tglyph\tstyle\tsize\tocr\tslant\tstroke\th\n")
        for c in rows:
            f.write(f"{c['id']}\t{c['n']}\t{c['ocr1']}\t{c['style']}\t{c['size']}\t"
                    f"{c['ocr']}\t{c['slant']:.0f}\t{c['stroke']:.1f}\t{c['h']}\n")
    pickle.dump(rows, open(os.path.join(WORK, "classified.pkl"), "wb"))
    review(rows)


def review(rows, min_n=2, per=96, cols=12, cell=120):
    """Contact sheets at true relative scale (all glyphs same px/pt)."""
    rows = [c for c in rows if c["n"] >= min_n]
    for s in range(0, len(rows), per):
        chunk = rows[s:s + per]
        nr = (len(chunk) + cols - 1) // cols
        sheet = Image.new("L", (cols * cell, nr * cell), 255)
        d = ImageDraw.Draw(sheet)
        for j, c in enumerate(chunk):
            im = Image.fromarray((255 - 255 * c["mean"]).astype(np.uint8))
            im = im.resize((max(1, im.width // 1), max(1, im.height // 1)))
            im = im.crop((0, 0, min(im.width, cell - 4), min(im.height, cell - 26)))
            x, y = (j % cols) * cell, (j // cols) * cell
            sheet.paste(im, (x + 2, y + 2))
            d.text((x + 3, y + cell - 24), f"#{c['id']} n{c['n']}", fill=0)
            d.text((x + 3, y + cell - 12), f"{c['ocr1']!r} {c['style']} {c['size']}", fill=0)
            d.rectangle([x, y, x + cell - 1, y + cell - 1], outline=200)
        sheet.save(os.path.join(WORK, f"review-{s // per:02d}.png"))


if __name__ == "__main__":
    main()
