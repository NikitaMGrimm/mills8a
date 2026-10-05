#!/bin/sh
# Download pages 49 and 51 of the 1922 Lanston Monotype specimen book (public
# domain, Internet Archive item monotypespecimen00lansrich): Modern 8A at
# 9-12pt (p. 49, roman, small caps, italic) and 14 and 18pt (p. 51, roman).
set -e
cd "$(dirname "$0")"
mkdir -p scans
ID=monotypespecimen00lansrich
for p in 49 51; do
  curl -sSfL -o "scans/lanston1922-p$p.jp2" \
    "https://archive.org/download/$ID/${ID}_jp2.zip/${ID}_jp2%2F${ID}_00$p.jp2"
done
ls -l scans/lanston1922-*.jp2
