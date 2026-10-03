#!/bin/sh
# Typeset tex/mills.tex in Mills Modern and in plain Computer Modern.
#   ./render.sh pk|type1
set -e
cd "$(dirname "$0")"
KIND=${1:-type1}
B=$PWD/build
mkdir -p out
export TEXINPUTS="$PWD/tex:" TFMFONTS="$B/tfm:" PKFONTS="$B/pk:"
export T1FONTS="$B/type1:" ENCFONTS="$B/type1:"
MAP=""
[ "$KIND" = type1 ] && MAP='\pdfmapfile{+millsmodern.map}' && export TEXFONTMAPS="$B/type1:"
cd out
pdflatex -interaction=nonstopmode -jobname=mills "$MAP\\input{mills}" >/dev/null || { tail -30 mills.log; exit 1; }
pdflatex -interaction=nonstopmode -jobname=mills-cm '\def\usecm{}\input{mills}' >/dev/null || { tail -30 mills-cm.log; exit 1; }
pdftoppm -r 200 -png -singlefile mills.pdf mills
pdftoppm -r 200 -png -singlefile mills-cm.pdf mills-cm
echo "out/mills.pdf out/mills-cm.pdf"
