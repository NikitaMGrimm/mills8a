"""Turn clusters into labelled sorts: (glyph, style, size) -> [cluster ids].

Rules first (OCR majority, measured slant, size class from relative height),
then the hand corrections in overrides.tsv win.  Writes work/sorts.pkl and
prints coverage of the 11pt roman and italic alphabets.
"""
import os
import pickle
import string

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")

ALWAYS_ROMAN = set(string.digits + string.punctuation) | set("—–’‘“”")


def size_class(h, h_body):
    """Size from height h relative to the body-size cluster's h_body, with
    the ~2 px of ink spread per edge removed first (it doesn't scale):
    11 = body, 9 = footnotes, S1 = first-order scripts (~6.5pt),
    S2 = second-order scripts (~5.5pt)."""
    r = (h - 4) / max(1, h_body - 4)
    if r > 1.12:
        return None                    # display sizes and pairs: by hand only
    return 11 if r > 0.92 else 9 if r > 0.75 else "S1" if r > 0.53 else "S2"


def load_overrides():
    """{cluster id: (glyph, style, size) or None}.  Each line names one
    impression (page@x0,y0); it applies to the cluster containing the
    impression nearest that corner (within 4 px), so cluster renumbering
    does not invalidate the file."""
    inst = pickle.load(open(os.path.join(WORK, "instances.pkl"), "rb"))
    clusters = pickle.load(open(os.path.join(WORK, "clusters.pkl"), "rb"))
    cluster_of = {i: c["id"] for c in clusters for i in c["members"]}
    by_page = {}
    for k, g in enumerate(inst):
        by_page.setdefault(g["page"], []).append((g["bbox"][0], g["bbox"][1], k))
    ov, missing = {}, []
    for line in open(os.path.join(HERE, "overrides.tsv"), encoding="utf-8"):
        if not line.strip() or line.startswith("#"):
            continue
        f = line.rstrip("\n").split("\t")
        page, xy = f[0].split("@")
        x, y = map(int, xy.split(","))
        near = min(by_page.get(page, []), key=lambda t: abs(t[0] - x) + abs(t[1] - y),
                   default=None)
        if near is None or abs(near[0] - x) + abs(near[1] - y) > 4 or near[2] not in cluster_of:
            missing.append(f[0])
            continue
        cid = cluster_of[near[2]]
        if f[1] == "skip":
            ov[cid] = None
        else:
            size = f[3]
            ov[cid] = (f[1], f[2], int(size) if size.isdigit() else size)
    if missing:
        print(f"overrides: {len(missing)} keys match no clustered impression: {missing[:5]}")
    return ov


def main():
    rows = pickle.load(open(os.path.join(WORK, "classified.pkl"), "rb"))
    ov = load_overrides()
    # Reference (body-size) cluster per OCR label and style, ignoring the
    # clusters corrected by hand (those are often mislabelled symbols).
    ref = {}
    # for letters, only full-size clusters can be the reference: a letter
    # used mostly as an index (italic j) has its most common cluster at
    # script size, against which the text size measured as display
    tallest = {}
    for c in rows:
        if c["id"] not in ov and c["n"] >= 5:
            key = (c["ocr1"], c["style"])
            tallest[key] = max(tallest.get(key, 0), c["h"])
    for c in rows:
        if c["id"] in ov:
            continue
        key = (c["ocr1"], c["style"])
        g = c["ocr1"]
        if g and len(g) == 1 and g.isalpha() and c["h"] < 0.85 * tallest.get(key, 0):
            continue
        if key not in ref or c["n"] > ref[key]["n"]:
            ref[key] = c
    for c in rows:                      # labels with no full-size cluster
        key = (c["ocr1"], c["style"])
        if c["id"] not in ov and (key not in ref or c["n"] > ref[key]["n"] and key not in tallest):
            ref.setdefault(key, c)

    sorts = {}
    for c in rows:
        if c["id"] in ov:
            lab = ov[c["id"]]
            if lab is None:
                continue
        else:
            if c["n"] < 2 or not c["ocr"]:
                continue
            g, cnt = c["ocr"][0]
            if g is None or len(g) != 1 or cnt < 0.6 * c["n"]:
                continue
            if c["style"] == "?":
                continue               # matches neither roman nor italic: by hand
            r = ref[(c["ocr1"], c["style"])]
            if c["w"] / c["h"] > 1.35 * r["w"] / r["h"]:
                continue               # two letters touching (the reference
                                       # may be another size, e.g. small caps)
            style = "R" if g in ALWAYS_ROMAN else c["style"]
            size = size_class(c["h"], r["h"])
            if style == "R" and g.isascii() and g.isupper() and g not in "JQ":
                # roman capitals: absolute cap height separates the sizes,
                # and in particular 11pt small caps from real capitals
                h = c["h"]
                size = (11 if 56 <= h <= 65 else "SC" if 42 <= h <= 49 else
                        9 if 50 <= h <= 55 else "S1" if 33 <= h <= 41 else None)
            if style == "R" and g in "0123456789":
                # figures: absolute height, as for capitals (relative to a
                # reference cluster that is itself 9pt they would pass as 11pt)
                h = c["h"]
                size = (11 if 55 <= h <= 64 else 9 if 46 <= h <= 54 else
                        "S1" if 33 <= h <= 40 else "S2" if 28 <= h <= 32 else None)
            if size is None:
                continue
            lab = (g, style, size)
        sorts.setdefault(lab, []).append(c["id"])

    pickle.dump(sorts, open(os.path.join(WORK, "sorts.pkl"), "wb"))
    nmem = {c["id"]: c["n"] for c in rows}
    for style in "RI":
        have = {g for (g, s, z) in sorts if s == style and z == 11}
        for name, alpha in [("lower", string.ascii_lowercase),
                            ("upper", string.ascii_uppercase), ("digits", string.digits)]:
            miss = "".join(ch for ch in alpha if ch not in have)
            print(f"{style} 11pt {name}: missing {miss or '-'}")
    other = sorted((g, s, str(z), sum(nmem[i] for i in ids)) for (g, s, z), ids in sorts.items()
                   if not (g.isascii() and g.isalnum()))
    print("symbols:", " ".join(f"{g}/{s}{z}:{n}" for g, s, z, n in other))


if __name__ == "__main__":
    main()
