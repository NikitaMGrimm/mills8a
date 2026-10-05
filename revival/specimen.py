"""Extract the Modern 8A alphabets from the 1922 Lanston Monotype specimen
book, to supply letters the 1947 pages never use.

Page 49 shows 9, 10, 11 and 12 pt with roman, small caps and italic
alphabets; page 51 shows 14 and 18 pt roman.  Every line listed in LINES is
segmented into glyphs (small components such as i-dots attach to the
nearest large one) and matched in order against its known text; a line
whose count does not match at any threshold is reported and skipped.

The pages are ~460 dpi grayscale scans of a lightly printed book, so a single
impression often breaks at thin hairlines; build_font.py therefore averages
all impressions of a letter, scaled to a common size.

Output: work/specimen.pkl {"glyphs": {(glyph, style): [impression, ...]}}
where an impression is dict(cov, top, size): ink coverage in [0, 1] at the
scan's resolution, the crop's top relative to the baseline (specimen px,
negative = above) and the point size.
"""
import os
import pickle

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")

LOWER = "abcdefghijklmnopqrstuvwxyz"
CAPS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
# (page, x0, x1, y0, y1, size, style, text) -- line boxes found by row profile
LINES = [
    ("p49", 130, 1390, 1667, 1713, 9, "R", "12345" + LOWER + "67890$"),
    ("p49", 130, 1390, 1731, 1778, 9, "R", CAPS),
    ("p49", 130, 1390, 1803, 1833, 9, "SC", CAPS),
    ("p49", 130, 1390, 1851, 1897, 9, "I", "12345" + LOWER + "67890$"),
    ("p49", 130, 1390, 1915, 1959, 9, "I", CAPS),
    ("p49", 1440, 2640, 1639, 1690, 10, "R", "12345" + LOWER + "67890$"),
    ("p49", 1440, 2640, 1708, 1760, 10, "R", CAPS),
    ("p49", 1440, 2640, 1787, 1820, 10, "SC", CAPS),
    ("p49", 1440, 2640, 1840, 1890, 10, "I", "12345" + LOWER + "67890$"),
    ("p49", 1440, 2640, 1909, 1957, 10, "I", CAPS),
    ("p49", 130, 1390, 3347, 3405, 11, "R", "12345" + LOWER + "67890$"),
    ("p49", 130, 1390, 3421, 3479, 11, "R", CAPS),
    ("p49", 130, 1390, 3506, 3544, 11, "SC", CAPS),
    ("p49", 130, 1390, 3563, 3620, 11, "I", "12345" + LOWER + "67890$"),
    ("p49", 130, 1390, 3636, 3693, 11, "I", CAPS),
    ("p49", 1440, 2640, 3320, 3381, 12, "R", "1234" + LOWER + "567$"),
    ("p49", 1440, 2640, 3401, 3461, 12, "R", CAPS[:23]),
    ("p49", 1440, 2640, 3492, 3532, 12, "SC", CAPS),
    ("p49", 1440, 2640, 3554, 3613, 12, "I", "1234" + LOWER + "567$"),
    ("p49", 1440, 2640, 3635, 3694, 12, "I", CAPS[:23]),
    ("p51", 150, 2650, 1634, 1704, 14, "R", LOWER),
    ("p51", 150, 2650, 1710, 1779, 14, "R", CAPS),
    ("p51", 150, 2650, 1788, 1847, 14, "R", "1234567890$"),
    ("p51", 150, 2650, 3163, 3257, 18, "R", LOWER),
    ("p51", 150, 2650, 3262, 3354, 18, "R", CAPS),
    ("p51", 150, 2650, 3363, 3440, 18, "R", "1234567890$"),
]
DESCENDERS = set("gjpqy$QJ")


def segment(sub, expect):
    """Split one text line into glyphs; None unless exactly `expect` found."""
    lab, n = ndimage.label(sub, structure=np.ones((3, 3)))
    if n == 0:
        return None
    objs = ndimage.find_objects(lab)
    areas = ndimage.sum(sub, lab, range(1, n + 1))
    big = [k for k in range(n) if areas[k] > 0.12 * np.median(areas)]
    small = [k for k in range(n) if k not in big]
    # merge big pieces that overlap horizontally (a letter broken at a hairline)
    big.sort(key=lambda k: objs[k][1].start)
    merged = []
    for k in big:
        if merged:
            p = merged[-1]
            px0 = min(objs[q][1].start for q in p); px1 = max(objs[q][1].stop for q in p)
            kx0, kx1 = objs[k][1].start, objs[k][1].stop
            if min(px1, kx1) - max(px0, kx0) > 0.5 * min(px1 - px0, kx1 - kx0):
                p.append(k)
                continue
        merged.append([k])
    groups = {p[0]: p for p in merged}
    big = list(groups)
    for k in small:                        # attach dots to the nearest glyph
        cx = (objs[k][1].start + objs[k][1].stop) / 2
        near = min(big, key=lambda b: abs((objs[b][1].start + objs[b][1].stop) / 2 - cx))
        groups[near].append(k)
    order = sorted(groups, key=lambda b: objs[b][1].start)
    if len(order) != expect:
        return None
    return lab, objs, groups, order


def coverage(page):
    g = np.array(Image.open(os.path.join(HERE, "scans", f"lanston1922-{page}.jp2"))
                 .convert("L")).astype(float)
    paper, ink = np.percentile(g, 90), np.percentile(g, 1)
    return np.clip((paper - g) / (paper - ink), 0, 1)


def main():
    pages = {}
    out = {}
    for page, x0, x1, y0, y1, size, style, text in LINES:
        if page not in pages:
            pages[page] = coverage(page)
        # a little vertical room for ascenders/descenders beyond the band
        cov = pages[page][y0 - 6:y1 + 6, x0:x1]
        for thr in (0.3, 0.35, 0.4, 0.45, 0.5, 0.25, 0.55, 0.6, 0.2):
            seg = segment(cov > thr, len(text))
            if seg is not None:
                break
        else:
            print(f"{page} {size}pt {style} {text[:10]}...: no threshold gives {len(text)}; skipped")
            continue
        lab, objs, groups, order = seg
        bottoms = [objs[b][0].stop for b, ch in zip(order, text) if ch not in DESCENDERS]
        base = int(np.median(bottoms))
        for b, ch in zip(order, text):
            ks = groups[b]
            ys0 = min(objs[k][0].start for k in ks); ys1 = max(objs[k][0].stop for k in ks)
            xs0 = min(objs[k][1].start for k in ks); xs1 = max(objs[k][1].stop for k in ks)
            mask = np.isin(lab[ys0:ys1, xs0:xs1], [k + 1 for k in ks])
            mask = ndimage.binary_dilation(mask, iterations=2)    # keep the soft edge
            c = cov[ys0:ys1, xs0:xs1] * mask
            out.setdefault((ch, style), []).append(dict(cov=c, top=ys0 - base, size=size))
        print(f"{page} {size}pt {style} {text[:10]}...: ok (threshold {thr})")
    pickle.dump(dict(glyphs=out), open(os.path.join(WORK, "specimen.pkl"), "wb"))
    n = sum(len(v) for v in out.values())
    print(f"{n} impressions of {len(out)} glyphs")


if __name__ == "__main__":
    main()
