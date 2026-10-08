"""Finish the committed OpenType fonts, without repeating OCR or tracing.

Also run at the end of build.sh, before the pdfTeX conversion. The typographic
line metrics are kept separate from the Windows metrics used for clipping.
"""
import argparse
import math
import unicodedata
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables import otTables

from unicode_fonts import add_accented_smallcaps, add_mark_features, add_unicode

FONTS = Path(__file__).resolve().parent / "fonts"


def glyph_bounds(font, name):
    glyphs = font.getGlyphSet()
    pen = BoundsPen(glyphs)
    glyphs[name].draw(pen)
    return pen.bounds


def update_ink_metrics(font):
    boxes = [glyph_bounds(font, name) for name in font.getGlyphOrder()]
    boxes = [box for box in boxes if box is not None]
    os2 = font["OS/2"]
    # These are clipping bounds, not a request to change the document's leading.
    os2.usWinAscent = max(os2.usWinAscent, math.ceil(max(b[3] for b in boxes)))
    os2.usWinDescent = max(os2.usWinDescent, math.ceil(-min(b[1] for b in boxes)))
    cmap = font.getBestCmap()
    for ch, field in (("x", "sxHeight"), ("H", "sCapHeight")):
        if ord(ch) in cmap:
            setattr(os2, field, round(glyph_bounds(font, cmap[ord(ch)])[3]))


def set_advance(font, name, advance):
    top = font["CFF "].cff.topDictIndex[0]
    width = None if advance == top.Private.defaultWidthX else advance - top.Private.nominalWidthX
    pen = T2CharStringPen(width, None, roundTolerance=0)
    top.CharStrings[name].draw(pen)
    top.CharStrings[name] = pen.getCharString(top.Private, top.GlobalSubrs)
    font["hmtx"].metrics[name] = (advance, font["hmtx"].metrics[name][1])


def normalize_accent_advances(font):
    cmap = font.getBestCmap()
    order = font.getGlyphOrder()
    for cp, name in cmap.items():
        ch = chr(cp)
        decomposed = unicodedata.normalize("NFD", ch)
        if (not ch.isalpha() or len(decomposed) < 2
                or not all(unicodedata.combining(c) for c in decomposed[1:])
                or ord(decomposed[0]) not in cmap):
            continue
        base = cmap[ord(decomposed[0])]
        advance = font["hmtx"][base][0]
        # Rare sorts have an underdetermined spacing fit. An accent does not
        # change its letter's Monotype set width; retain the traced ink itself.
        for variant in [name] + [n for n in order if n.startswith(name + ".r")]:
            if font["hmtx"][variant][0] != advance:
                set_advance(font, variant, advance)


def add_smallcaps_feature(font):
    order = set(font.getGlyphOrder())
    cmap = font.getBestCmap()
    mapping = {name: name + ".sc" for name in set(cmap.values())
               if name + ".sc" in order}
    if not mapping:
        return
    table = font["GSUB"].table
    existing = next((f for f in table.FeatureList.FeatureRecord
                     if f.FeatureTag == "smcp"), None)
    if existing:
        return
    sub = otTables.SingleSubst()
    sub.mapping = mapping
    lookup = otTables.Lookup()
    lookup.LookupType, lookup.LookupFlag = 1, 0
    lookup.SubTable, lookup.SubTableCount = [sub], 1
    index = len(table.LookupList.Lookup)
    table.LookupList.Lookup.append(lookup)
    table.LookupList.LookupCount = len(table.LookupList.Lookup)
    feature = otTables.FeatureRecord()
    feature.FeatureTag = "smcp"
    feature.Feature = otTables.Feature()
    feature.Feature.FeatureParams = None
    feature.Feature.LookupListIndex = [index]
    feature.Feature.LookupCount = 1
    feature_index = len(table.FeatureList.FeatureRecord)
    table.FeatureList.FeatureRecord.append(feature)
    table.FeatureList.FeatureCount = len(table.FeatureList.FeatureRecord)
    for record in table.ScriptList.ScriptRecord:
        if record.ScriptTag in ("DFLT", "latn"):
            lang = record.Script.DefaultLangSys
            lang.FeatureIndex.append(feature_index)
            lang.FeatureCount = len(lang.FeatureIndex)
    # smcp must run before rand so alternates are selected from the small caps.
    records = table.FeatureList.FeatureRecord
    sorted_indices = sorted(range(len(records)), key=lambda i: records[i].FeatureTag)
    remap = {old: new for new, old in enumerate(sorted_indices)}
    table.FeatureList.FeatureRecord = [records[i] for i in sorted_indices]
    for record in table.ScriptList.ScriptRecord:
        langs = [record.Script.DefaultLangSys] + [r.LangSys for r in record.Script.LangSysRecord]
        for lang in filter(None, langs):
            lang.FeatureIndex = sorted(remap[i] for i in lang.FeatureIndex)
            if lang.ReqFeatureIndex != 0xFFFF:
                lang.ReqFeatureIndex = remap[lang.ReqFeatureIndex]


def finish(font):
    if "MATH" not in font:
        add_unicode(font)
        normalize_accent_advances(font)
        add_accented_smallcaps(font)
        add_smallcaps_feature(font)
        add_mark_features(font)
    update_ink_metrics(font)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fonts", nargs="*", type=Path,
                        help="OTF files; defaults to revival/fonts/*.otf")
    args = parser.parse_args()
    for path in args.fonts or sorted(FONTS.glob("*.otf")):
        font = TTFont(path, recalcTimestamp=False)
        finish(font)
        font.save(path)
        print(f"Finished {path.name}")


if __name__ == "__main__":
    main()
