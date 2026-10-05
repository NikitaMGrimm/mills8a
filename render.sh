#!/bin/sh
# Typeset tex/mills.tex in Mills Modern, plain Computer Modern and
# (if fetched) Old Standard.
#   ./render.sh pk|type1
set -e
cd "$(dirname "$0")"
KIND=${1:-type1}
B=$PWD/build
mkdir -p out
export TEXINPUTS="$PWD/tex:" LUAINPUTS="$PWD/tex:" TFMFONTS="$B/tfm:" PKFONTS="$B/pk:"
export T1FONTS="$B/type1:" ENCFONTS="$B/type1:"
MAP=""
[ "$KIND" = type1 ] && MAP='\pdfmapfile{+millsmodern.map}' && export TEXFONTMAPS="$B/type1:"
cd out
pdflatex -interaction=nonstopmode -jobname=mills "$MAP\\input{mills}" >/dev/null || { tail -30 mills.log; exit 1; }
pdflatex -interaction=nonstopmode -jobname=mills-cm '\def\usecm{}\input{mills}' >/dev/null || { tail -30 mills-cm.log; exit 1; }
if [ -d "$B/oldstandard" ]; then
  OPENTYPEFONTS="$B/oldstandard:" lualatex -interaction=nonstopmode -jobname=mills-oldstandard \
    '\def\useoldstandard{}\input{mills}' >/dev/null || { tail -30 mills-oldstandard.log; exit 1; }
  pdftoppm -r 200 -png -singlefile mills-oldstandard.pdf mills-oldstandard
  echo out/mills-oldstandard.pdf
else
  echo "skipping Old Standard (run ./fetch-oldstandard.sh first)"
fi
if [ -f ../revival/fonts/Mills8A-Regular.otf ]; then
  OPENTYPEFONTS="$PWD/../revival/fonts:" lualatex -interaction=nonstopmode -jobname=mills-8a \
    '\def\useeighta{}\input{mills}' >/dev/null || { tail -30 mills-8a.log; exit 1; }
  pdftoppm -r 200 -png -singlefile mills-8a.pdf mills-8a
  echo out/mills-8a.pdf
fi
pdftoppm -r 200 -png -singlefile mills.pdf mills
pdftoppm -r 200 -png -singlefile mills-cm.pdf mills-cm
echo "out/mills.pdf out/mills-cm.pdf"
