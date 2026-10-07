# Mills 8A

A digital revival of **Monotype Modern No. 8A**, the typeface of the
*Bulletin of the American Mathematical Society* in the 1940s, for LaTeX.
It is named after W. H. Mills, *A prime-representing function* (Bull. AMS 53,
1947), the page this project started from.

![Mills 8A type specimen](docs/specimen.png)

Monotype Modern 8A (Lanston Monotype's series 8, roman with italic) is a
Scotch-style "modern" face: strong contrast, ball terminals, cast in hot metal
and printed by letterpress. It was a standard face of American mathematical
printing from the 1920s to the 1960s, and it is the face Knuth modelled
Computer Modern on. Mills 8A is not a redrawing. Its glyphs are traced from the
type itself: averaged from about 900,000 letter impressions on 461 scanned
pages of the *Bulletin* and the *Transactions* (1940–1948). The shapes, the
weight of the ink, the Monotype unit widths and the real 1947 script sorts are
all as they were printed.

## The 1947 page, reset

The Mills page as printed in 1947 (left), and reset from the LaTeX source in
Mills 8A with LuaLaTeX and with pdfLaTeX:

![1947 scan, LuaLaTeX, pdfLaTeX](docs/comparison.png)

[`mills-compare.pdf`](mills-compare.pdf) has the three side by side and then
each on its own page.

## What is in the family

| font | contents |
|---|---|
| Mills8A-Regular | roman, small caps, f-ligatures, lining and old-style figures, accents (Latin-1, Latin Extended-A) |
| Mills8A-Italic | italic, Greek, f-ligatures |
| Mills8A-Bold, -BoldItalic | bold (from the titles); bold italic (synthesized) |
| Mills8A-Regular9, -Italic9 | the 9 pt cut, for footnotes and references |
| Mills8A-Math | OpenType math: the 1947 letters, Greek, operators, relations, Fraktur, display ∑ ∏ ∫, and the real first- and second-order **script sorts** for indices |

The same family is built twice:

- **OpenType** for LuaLaTeX (`fontspec`, `unicode-math`). Each letter can also
  be set as one of up to 8 real impressions at random (`rand`), and a small
  baseline wobble (`tex/mills8a-jitter.lua`) imitates the letterpress line.
- **Type 1 / TFM** for pdfLaTeX, using only standard TeX font machinery: T1
  text fonts, OML/OMS/OMX math fonts at 11, 6.5 and 5.5 pt (so indices use the
  real script sorts, as `cmmi7`/`cmmi5` do), and a virtual font that puts the
  1947 big operators into `cmex10`.

## Using it

pdfLaTeX:

```latex
\usepackage{mills8a}            % or [osf] for old-style figures in text
```

with `revival/pdftex/tex` on `TEXINPUTS` and `revival/pdftex/fonts` on
`TFMFONTS`, `VFFONTS`, `T1FONTS`, `ENCFONTS` and `TEXFONTMAPS` (see
`render.sh`).

LuaLaTeX:

```latex
\usepackage{unicode-math}
\setmainfont{Mills8A-Regular.otf}[
  RawFeature=+rand,                                   % random 1947 impressions
  SizeFeatures={{Size=-10, Font=Mills8A-Regular9.otf}, {Size=10-}},
  SmallCapsFont=Mills8A-Regular.otf, SmallCapsFeatures={RawFeature=+smcp},
  ItalicFont=Mills8A-Italic.otf,
  ItalicFeatures={SizeFeatures={{Size=-10, Font=Mills8A-Italic9.otf}, {Size=10-}}},
  BoldFont=Mills8A-Bold.otf, BoldItalicFont=Mills8A-BoldItalic.otf]
\setmathfont{Mills8A-Math.otf}
\DeclareMathSizes{10.95}{11}{6.48}{5.51}                 % the measured script sizes
```

with `revival/fonts` on `OPENTYPEFONTS`. Add `Numbers=OldStyle` for old-style
figures. The Bulletin set 11 pt type on 12 pt leading; `tex/mills.tex` shows the
complete setup, including the 1947 script positions.

## How it was made

1. **Segment** each 600 dpi page into glyph impressions, with Tesseract for a
   first reading and the page's lines (`revival/segment.py`, `baselines.py`).
2. **Normalize the scans**: each paper's ink weight and type size are measured
   against the Erdős paper and corrected (`docweight.py`).
3. **Cluster** identical sorts and label them (`cluster.py`, `classify.py`,
   `assign.py`). Rules do most of it; `overrides.tsv` holds the hand
   corrections, each naming one impression, so re-clustering does not
   invalidate it.
4. **Average** each sort's impressions at 4× resolution, aligned to ¼ px
   (`masters.py`). Old-style figures come from the years in the Bulletin's
   running heads (`oldstyle.py`).
5. **Trace and space** the masters into OpenType fonts (`build_font.py`). Side
   bearings are fitted from 230,000 letter pairs in the text and land on
   Monotype's 18-unit grid. Then accents (`accents.py`), the math font on Latin
   Modern Math's tables (`build_math.py`), bold and 9 pt (`build_sizes.py`),
   and the pdfLaTeX fonts (`pdftex/build_pdftex.py`).
6. **Check**: `check_fonts.py` tests baselines, heights, side bearings and the
   script sorts of every font, and `proof/` has proof sheets of everything the
   family sets, in both engines.

`revival/README.md` describes each step, the measurements behind it, and
where each glyph comes from.

## How much is real

From the 1940s scans: every roman and italic letter and figure at 11 pt
(except the roman J), the old-style figures, punctuation, 23 small caps, 20
bold capitals, Greek, most math operators and relations, the display ∑ ∏ ∫,
Fraktur 𝔄 𝔅 ℭ 𝔇 𝔊 𝔖 𝔛, the 9 pt cut, and about 60 script sorts.

Filled in otherwise:

- from the 1922 Lanston *Specimen Book* (No. 8A at 9–18 pt): the roman J,
  small caps J Q X, and `$`;
- built from 1947 sorts: the *fl*/*ffl* and italic *ffi*/*ffl* ligatures, the
  en and em dashes, most script sizes that have no real sort, and bold
  lowercase;
- from Latin Modern, thickened to the type's weight: accents other than the
  dieresis, rarer punctuation and symbols, and the math symbols the scans
  lack.

## Building

The scans are not in the repository; `revival/README.md` lists them (free
from the AMS back issues). With them in `revival/scans/`:

    revival/fetch-specimen.sh     # the 1922 specimen pages (public domain)
    revival/build.sh              # about 1.5-2 h on 4 cores; clustering is most of it
    ./render.sh                   # the PDFs, proof sheets and the images above

Requires TeX Live (pdfLaTeX, LuaLaTeX, `lcdf-typetools`), Tesseract, potrace,
and Python 3 with numpy, scipy, Pillow and fontTools. The built fonts are
committed in `revival/fonts/` and `revival/pdftex/fonts/`.

## Sources and licences

- The scans: *Bulletin* and *Transactions of the AMS*, 1940–1948, from the
  AMS back-issue archive; not redistributed here.
- *The Monotype Specimen Book of Type Faces*, Lanston Monotype, 1922
  (public domain).
- Latin Modern Math (GUST Font License), the base of `Mills8A-Math.otf`.
