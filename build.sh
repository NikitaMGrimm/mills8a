#!/bin/sh
# Build the Mills Modern fonts and the sample document.
#   ./build.sh pk     -- 1200 dpi bitmap fonts (fast, for tuning parameters)
#   ./build.sh type1  -- traced Type 1 outlines via mftrace (default)
set -e
cd "$(dirname "$0")"
KIND=${1:-type1}
ROOT=$PWD
FONTS=$(cd mf && ls mm*.mf | grep -v mmbase | sed 's/\.mf$//')
B=$ROOT/build
mkdir -p "$B/tfm" "$B/pk" "$B/type1" "$B/work" "$B/tmp"
export MFINPUTS="$ROOT/mf:"

for f in $FONTS; do
  if [ "$KIND" = pk ]; then
    (cd "$B/work" && mf -interaction=batchmode "\\mode=ljfour; mag:=2; input $f" >/dev/null) || { echo "mf failed on $f (see build/work/$f.log)" >&2; exit 1; }
    gftopk "$B/work/$f.1200gf" "$B/pk/$f.1200pk" >/dev/null
    cp "$B/work/$f.tfm" "$B/tfm/"
  else
    (cd "$B/work" && mf -interaction=batchmode "\\mode=ljfour; input $f" >/dev/null)
    cp "$B/work/$f.tfm" "$B/tfm/"
    (cd "$B/type1" && TMPDIR="$B/tmp" TFMFONTS="$B/tfm:" \
       mftrace --simplify --formats=pfb "$f" >/dev/null 2>&1) \
      || { echo "mftrace failed on $f" >&2; exit 1; }
  fi
done

if [ "$KIND" != pk ]; then
  : > "$B/type1/millsmodern.map"
  for f in $FONTS; do
    name=$(t1disasm "$B/type1/$f.pfb" | grep -m1 '^/FontName'  | sed 's|^/FontName /\([^ ]*\).*|\1|')
    echo "$f $name <$f.pfb" >> "$B/type1/millsmodern.map"
  done
fi
echo "built $(echo $FONTS | wc -w) fonts ($KIND)"
