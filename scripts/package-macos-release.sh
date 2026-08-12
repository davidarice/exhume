#!/bin/zsh
set -euo pipefail

project_dir="${0:A:h:h}"
source_app="${1:-$project_dir/dist/Final Crack Pro.app}"
output_dir="${OUTPUT_DIR:-$project_dir/dist/release}"
identity="${FCP_CODESIGN_IDENTITY:-}"
notary_profile="${FCP_NOTARY_PROFILE:-}"

if [[ -z "$identity" || -z "$notary_profile" ]]; then
  print -u2 "Set FCP_CODESIGN_IDENTITY and FCP_NOTARY_PROFILE in your local shell."
  print -u2 "Their real values must not be committed to this repository."
  exit 1
fi
test -d "$source_app"

stage_dir="$(mktemp -d /tmp/fcp7pro-release.XXXXXX)"
trap 'rm -rf "$stage_dir"' EXIT
app="$stage_dir/Final Crack Pro.app"
zip="$stage_dir/Final-Crack-Pro.zip"
dmg="$output_dir/Final-Crack-Pro-1.5.0-macOS.dmg"
receipt_dir="${FCP_RECEIPT_DIR:-$project_dir/.signing-local/receipts}"

mkdir -p "$output_dir" "$receipt_dir"
ditto --norsrc --noextattr "$source_app" "$app"
xattr -cr "$app"

codesign --force --deep --options runtime --timestamp \
  --sign "$identity" "$app"
codesign --verify --deep --strict --verbose=2 "$app"

# Notarize and staple the app before placing it in the DMG.
ditto -c -k --keepParent "$app" "$zip"
xcrun notarytool submit "$zip" --keychain-profile "$notary_profile" \
  --wait --output-format json > "$receipt_dir/app-notary.json"
xcrun stapler staple "$app"
xcrun stapler validate "$app"

dmg_root="$stage_dir/dmg-root"
mkdir -p "$dmg_root"
ditto --norsrc --noextattr "$app" "$dmg_root/Final Crack Pro.app"
ln -s /Applications "$dmg_root/Applications"
hdiutil create -quiet -volname "Final Crack Pro" -srcfolder "$dmg_root" \
  -format UDZO -ov "$dmg"

xcrun notarytool submit "$dmg" --keychain-profile "$notary_profile" \
  --wait --output-format json > "$receipt_dir/dmg-notary.json"
xcrun stapler staple "$dmg"
xcrun stapler validate "$dmg"
shasum -a 256 "$dmg" > "$dmg.sha256.txt"

print "Release DMG: $dmg"
print "Checksum: $dmg.sha256.txt"
print "Private receipts: $receipt_dir"
