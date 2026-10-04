#!/bin/sh
# Download page 49 of the 1922 Lanston Monotype specimen book (public domain,
# Internet Archive item monotypespecimen00lansrich): "No. 8A, Book Arrangement C".
set -e
cd "$(dirname "$0")"
mkdir -p scans
ID=monotypespecimen00lansrich
curl -sSfL -o scans/lanston1922-p49.jp2 \
  "https://archive.org/download/$ID/${ID}_jp2.zip/${ID}_jp2%2F${ID}_0049.jp2"
ls -l scans/lanston1922-p49.jp2
