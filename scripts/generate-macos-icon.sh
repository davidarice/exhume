#!/bin/zsh
set -euo pipefail

project_dir="${0:A:h:h}"
source_svg="$project_dir/packaging/AppIcon.svg"
asset_dir="$project_dir/.build-assets"
iconset="$asset_dir/FinalCrackPro.iconset"
master="$asset_dir/AppIcon.svg.png"

mkdir -p "$asset_dir"
rm -rf "$iconset"
mkdir -p "$iconset"

qlmanage -t -s 1024 -o "$asset_dir" "$source_svg" >/dev/null
test -f "$master"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$master" --out "$iconset/icon_${size}x${size}.png" >/dev/null
  retina=$((size * 2))
  sips -z "$retina" "$retina" "$master" --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$iconset" -o "$asset_dir/FinalCrackPro.icns"
print "Generated: $asset_dir/FinalCrackPro.icns"
