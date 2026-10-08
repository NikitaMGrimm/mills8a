#!/bin/sh
# Install Mills 8A into your personal TeX tree (TEXMFHOME, e.g. ~/texmf or
# ~/Library/texmf), from mills8a.tds.zip or from build/tds/.
#   ./install.sh            install
#   ./install.sh --dvips    also enable the map file for dvips (latex + dvips)
# pdfLaTeX needs nothing more: \usepackage{mills8a} loads its own map file.
set -e
cd "$(dirname "$0")"
home=$(kpsewhich -var-value TEXMFHOME)
[ -n "$home" ] || { echo "kpsewhich not found: is TeX Live installed?"; exit 1; }
if [ -d build/tds ]; then src=build/tds
elif [ -f mills8a.tds.zip ]; then
  src=$(mktemp -d); unzip -q mills8a.tds.zip -d "$src"
else echo "run ./make-tds.sh first"; exit 1; fi
mkdir -p "$home"
cp -R "$src"/. "$home"/
echo "installed into $home"
# TEXMFHOME is searched without a file database; refresh one if it has it
[ -f "$home/ls-R" ] && mktexlsr "$home" >/dev/null 2>&1 || true
if [ "$1" = "--dvips" ]; then
  updmap-user --enable Map=mills8a.map >/dev/null && echo "map enabled for dvips"
fi
kpsewhich mills8a.sty >/dev/null && echo "ok: \\usepackage{mills8a} is found"
