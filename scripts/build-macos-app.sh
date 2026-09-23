#!/bin/zsh
set -euo pipefail

project_dir="${0:A:h:h}"
python_bin="${PYTHON_BIN:-/opt/homebrew/bin/python3.12}"
venv_dir="$project_dir/.venv-build"

if [[ ! -x "$python_bin" ]]; then
  print -u2 "Python 3.12 was not found at: $python_bin"
  print -u2 "Set PYTHON_BIN to a standalone CPython 3.12 executable."
  exit 1
fi

if [[ -f "$venv_dir/bin/pyinstaller" ]]; then
  if ! grep -Fq "$venv_dir/bin/python" "$venv_dir/bin/pyinstaller"; then
    print "Recreating build environment after the project moved."
    rm -rf "$venv_dir"
  fi
fi

"$python_bin" -m venv "$venv_dir"
"$venv_dir/bin/python" -m pip install --disable-pip-version-check \
  --requirement "$project_dir/requirements-build.txt"

cd "$project_dir"
"$project_dir/scripts/generate-macos-icon.sh"
"$venv_dir/bin/pyinstaller" --noconfirm --clean FCP7ExportTool.spec

app="$project_dir/dist/FCP7 Export Tool.app"
test -d "$app"
print "Built (development/ad-hoc signed): $app"
print "Run scripts/validate-macos-app.sh before testing or packaging."
