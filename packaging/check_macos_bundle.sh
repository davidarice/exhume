#!/bin/sh
# Fail if a built Exhume.app contains anything of Apple's: the project never ships an Apple binary
# or framework. Apple's libraries may be *linked* (that's how every Mac app works) but not *copied*.
# usage: packaging/check_macos_bundle.sh path/to/Exhume.app
set -eu
app="$1"
status=0

# a framework inside the app other than the bundled Python
others=$(find "$app" -name "*.framework" -type d -prune ! -name "Python.framework")
if [ -n "$others" ]; then
    echo "Unexpected frameworks in the app:"; echo "$others"; status=1
fi

# a copied library still carries its Apple install name (/System/... or /usr/lib/...)
find "$app" -type f | while IFS= read -r f; do
    if file -b "$f" | grep -q "Mach-O"; then
        id=$(otool -D "$f" 2>/dev/null | sed -n 2p)
        case "$id" in
            /System/*|/usr/lib/*) echo "Apple library copied into the app: $f ($id)"; exit 1 ;;
        esac
    fi
done || status=1

[ "$status" -eq 0 ] && echo "Bundle check passed: no Apple libraries or frameworks inside $app"
exit "$status"
