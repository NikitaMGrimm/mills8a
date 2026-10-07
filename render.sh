#!/bin/sh
# Typeset the Mills page in Mills 8A with LuaLaTeX and pdfLaTeX, the
# comparison PDF, the proof sheets and the README images.
#   ./render.sh
set -e
cd "$(dirname "$0")"
mkdir -p out/proof
R=$PWD/revival
P=$R/pdftex
export TEXINPUTS="$PWD/tex:" LUAINPUTS="$PWD/tex:"

lua() {   # lualatex with the OpenType fonts
  OPENTYPEFONTS="$R/fonts:" lualatex -interaction=nonstopmode "$@" >/dev/null
}
pdf() {   # pdflatex with the Type 1 / TFM fonts
  TEXINPUTS="$P/tex:$TEXINPUTS" TFMFONTS="$P/fonts:" VFFONTS="$P/fonts:" T1FONTS="$P/fonts:" \
  ENCFONTS="$P/fonts:" TEXFONTMAPS="$P/fonts:" pdflatex -interaction=nonstopmode "$@" >/dev/null
}

cd out
lua -jobname=mills-8a mills.tex || { tail -30 mills-8a.log; exit 1; }
pdf -jobname=mills-8a-pdf mills.tex || { tail -30 mills-8a-pdf.log; exit 1; }

# the comparison: overview, scan and both versions, each page headed with
# its version and the build
for t in compare compare-scan; do
  pdflatex -interaction=nonstopmode "$t.tex" >/dev/null || { tail -30 $t.log; exit 1; }
done
printf '\\newcommand\\buildid{built %s, commit %s}\n' "$(date +%Y-%m-%d)" \
  "$(git -C .. rev-parse --short HEAD 2>/dev/null || echo unknown)" > build-id.tex
pdflatex -interaction=nonstopmode -jobname=mills-compare compare-all.tex >/dev/null \
  || { tail -30 mills-compare.log; exit 1; }

# proof sheets of everything the family sets
lua -output-directory=proof proof-lua.tex || { tail -30 proof/proof-lua.log; exit 1; }
pdf -output-directory=proof proof-pdf.tex || { tail -30 proof/proof-pdf.log; exit 1; }

# the specimen and the comparison images shown in README.md
pdf specimen.tex || { tail -30 specimen.log; exit 1; }
mkdir -p ../docs
pdftoppm -r 170 -png -singlefile specimen.pdf ../docs/specimen
pdftoppm -r 110 -png -singlefile -f 1 -l 1 mills-compare.pdf ../docs/comparison

grep -l "Missing character" *.log proof/*.log || true
echo "out/mills-8a.pdf out/mills-8a-pdf.pdf out/mills-compare.pdf out/proof/*.pdf docs/*.png"
