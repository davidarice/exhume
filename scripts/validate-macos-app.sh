#!/bin/zsh
set -euo pipefail

project_dir="${0:A:h:h}"
app="${1:-$project_dir/dist/Final Crack Pro.app}"

test -d "$app"

# File Provider-managed folders can attach Finder metadata that codesign rejects.
# Validate a clean, disposable copy exactly as release packaging does.
stage_dir="$(mktemp -d /tmp/fcp7pro-validate.XXXXXX)"
trap 'rm -rf "$stage_dir"' EXIT
ditto --norsrc --noextattr "$app" "$stage_dir/Final Crack Pro.app"
xattr -cr "$stage_dir/Final Crack Pro.app"
app="$stage_dir/Final Crack Pro.app"
executable="$app/Contents/MacOS/Final Crack Pro"
test -x "$executable"

bundle_id="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$app/Contents/Info.plist")"
version="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$app/Contents/Info.plist")"
build="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$app/Contents/Info.plist")"
archs="$(lipo -archs "$executable")"

[[ "$bundle_id" == "ca.macvfx.fcp7pro" ]]
[[ "$version" == "1.5.0" ]]
[[ "$build" == "1" ]]
[[ "$archs" == *"arm64"* || "$archs" == *"x86_64"* ]]

print "Bundle ID: $bundle_id"
print "Version/build: $version ($build)"
print "Architectures: $archs"

verify_log="$stage_dir/codesign-verify.log"
if codesign --verify --deep --strict --verbose=2 "$app" 2>"$verify_log"; then
  signature="$(codesign -dv --verbose=4 "$app" 2>&1 | awk -F= '/^Signature=/{print $2}')"
  print "Code signature: valid (${signature:-unknown})"
else
  cat "$verify_log" >&2
  print -u2 "Code signature: invalid"
  exit 1
fi
