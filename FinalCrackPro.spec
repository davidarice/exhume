# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the self-contained macOS application bundle."""

from pathlib import Path

project_root = Path(SPEC).resolve().parent

a = Analysis(
    [str(project_root / "run.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / "webapp" / "static"), "webapp/static"),
        (str(project_root / "LICENSE"), "licenses"),
        (str(project_root / "THIRD_PARTY_NOTICES.md"), "licenses"),
        (str(project_root / "packaging" / "PYTHON-LICENSE.txt"), "licenses"),
        (str(project_root / "packaging" / "PYINSTALLER-COPYING.txt"), "licenses"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Final Crack Pro",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Final Crack Pro",
)

app = BUNDLE(
    coll,
    name="Final Crack Pro.app",
    icon=str(project_root / ".build-assets" / "FinalCrackPro.icns"),
    bundle_identifier="com.fcp7.to.xml",
    version="1.5.0",
    info_plist={
        "CFBundleDisplayName": "Final Crack Pro",
        "CFBundleName": "Final Crack Pro",
        "CFBundleShortVersionString": "1.5.0",
        "CFBundleVersion": "1",
        "LSApplicationCategoryType": "public.app-category.video",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
    },
)
