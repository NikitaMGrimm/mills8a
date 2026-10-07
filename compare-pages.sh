#!/bin/sh
# Side-by-side comparisons of the first page of each scanned paper with its
# reset in tex/pages/<paper>.tex: docs/pages/<paper>.png.  Needs the scans'
# page images (revival/work/pages, made by revival/build.sh).
#   ./compare-pages.sh [paper ...]
set -e
cd "$(dirname "$0")"
R=$PWD/revival; P=$R/pdftex
mkdir -p out/pages docs/pages
export TEXINPUTS="$P/tex:$PWD/tex:$PWD/tex/pages:" TFMFONTS="$P/fonts:" VFFONTS="$P/fonts:" \
  T1FONTS="$P/fonts:" ENCFONTS="$P/fonts:" TEXFONTMAPS="$P/fonts:"
papers=${*:-$(cd tex/pages && ls *.tex | sed 's/\.tex$//')}
for d in $papers; do
  pdflatex -interaction=nonstopmode -output-directory=out/pages "tex/pages/$d.tex" >/dev/null \
    || { tail -20 "out/pages/$d.log"; exit 1; }
  [ "$(pdfinfo out/pages/$d.pdf | awk '/^Pages/ {print $2}')" = 1 ] || echo "$d: more than one page"
  python3 revival/crop_scan.py "$R/work/pages/$d-000.png" "out/pages/$d-scan.png"
  bbox=$(gs -q -dNOPAUSE -dBATCH -sDEVICE=bbox "out/pages/$d.pdf" 2>&1 \
         | sed -n 's/^%%HiResBoundingBox: //p')
  (cd out && pdflatex -interaction=nonstopmode -jobname="compare-$d" \
     "\def\doc{$d}\def\bbox{$bbox}\input{compare-page}" >/dev/null) \
    || { tail -20 "out/compare-$d.log"; exit 1; }
  pdftoppm -r 90 -png -singlefile "out/compare-$d.pdf" "docs/pages/$d"
  echo "docs/pages/$d.png"
done
