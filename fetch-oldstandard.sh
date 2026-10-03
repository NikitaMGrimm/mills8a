#!/bin/sh
# Download the Old Standard OpenType fonts (text + math, SIL OFL) from CTAN.
set -e
cd "$(dirname "$0")"
D=build/oldstandard
mkdir -p "$D"
curl -sSfL -o "$D/oldstandard.zip" https://mirrors.ctan.org/fonts/oldstandard.zip
unzip -oqj "$D/oldstandard.zip" 'oldstandard/opentype/*.otf' -d "$D"
ls "$D"/*.otf
