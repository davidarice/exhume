# macOS application packaging

FCP7 Export Tool can be distributed as a self-contained macOS application. The
application includes its Python runtime; end users do not install Python or any
Python packages.

## Development build

Requirements on the build Mac:

- macOS 12 or newer;
- Apple Silicon Python 3.12 at `/opt/homebrew/bin/python3.12`, or set
  `PYTHON_BIN` to another CPython 3.12 executable;
- internet access the first time, to install the pinned PyInstaller build tool.

Build and validate:

```sh
./scripts/build-macos-app.sh
./scripts/validate-macos-app.sh
```

The result is `dist/FCP7 Export Tool.app`. It is an `onedir` PyInstaller bundle
with the identifier `com.fcp7.to.xml`. PyInstaller applies an ad-hoc signature
to development builds. That signature is suitable for local testing, not public
distribution.

The build currently targets the build Mac's architecture. Release both arm64
and x86_64 builds, or build with a universal2 CPython distribution after both
architectures pass the conversion acceptance test.

## Release signing and notarization

Never add certificate exports, Apple credentials, Team IDs, Keychain profile
contents, or notarization receipts to the repository. Configure real values only
in the local shell and macOS Keychain:

```sh
export FCP_CODESIGN_IDENTITY="Developer ID Application: Example Company (ABCDE12345)"
export FCP_NOTARY_PROFILE="fcp7-export-tool"
./scripts/package-macos-release.sh
```

The example identity is fictional. The script reads the actual identity and
notary profile locally, signs with hardened runtime, notarizes and staples the
app and DMG, then writes a SHA-256 checksum. Notarization JSON receipts default
to the ignored `.signing-local/receipts` directory.

Always test the packaged app on a clean Mac without Homebrew, Xcode, or Python.
The acceptance test must upload and convert a known `.fcp` fixture so the frozen
process pool is exercised—not just verify that the browser page opens.
