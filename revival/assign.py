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

# Relative heights measured from the scans (ink spread included):
# 11pt body = 1.0, 9pt ~ 0.84, 8pt ~ 0.77, 7pt ~ 0.67, 6pt ~ 0.59.
SIZES = [(11, 1.0), (9, 0.84), (8, 0.77), (7, 0.67), (6, 0.59)]
ALWAYS_ROMAN = set(string.digits + string.punctuation) | set("—–’‘“”")


def size_class(r):
    if r > 1.12:
        return None                    # display sizes and pairs: by hand only
    return min(SIZES, key=lambda s: abs(s[1] - r))[0]


def load_overrides():
    ov = {}
    for line in open(os.path.join(HERE, "overrides.tsv"), encoding="utf-8"):
        if not line.strip() or line.startswith("#"):
            continue
        f = line.rstrip("\n").split("\t")
        cid = int(f[0])
        if f[1] == "skip":
            ov[cid] = None
        else:
            size = f[3]
            ov[cid] = (f[1], f[2], int(size) if size.isdigit() else size)
    return ov


def main():
    rows = pickle.load(open(os.path.join(WORK, "classified.pkl"), "rb"))
    ov = load_overrides()
    # Reference (body-size) cluster per OCR label and style, ignoring the
    # clusters corrected by hand (those are often mislabelled symbols).
    ref = {}
    for c in rows:
        if c["id"] in ov:
            continue
        key = (c["ocr1"], c["style"])
        if key not in ref or c["n"] > ref[key]["n"]:
            ref[key] = c

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
            r = ref[(c["ocr1"], c["style"])]
            if c["w"] > 1.35 * r["w"]:
                continue               # two letters touching
            style = "R" if g in ALWAYS_ROMAN else c["style"]
            size = size_class(c["h"] / r["h"])
            if style == "R" and g.isascii() and g.isupper() and g not in "JQ":
                # roman capitals: absolute cap height separates the sizes,
                # and in particular 11pt small caps from real capitals
                h = c["h"]
                size = (11 if 56 <= h <= 65 else "SC" if 42 <= h <= 49 else
                        9 if 50 <= h <= 55 else 8 if 34 <= h <= 40 else None)
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
