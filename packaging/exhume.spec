# PyInstaller recipe for the Exhume desktop app: Exhume.app on macOS, an Exhume folder (Exhume.exe
# or exhume) on Windows and Linux. Build from the repository root with a python.org or Homebrew
# Python that has packaging/requirements-desktop.txt installed:
#     pyinstaller packaging/exhume.spec
# EXHUME_TARGET_ARCH=universal2 builds one Mac app for Apple Silicon and Intel (needs a universal2
# Python, such as python.org's installer).
import importlib.metadata
import os
import re
import sys
import sysconfig

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

ROOT = os.path.dirname(SPECPATH)   # SPECPATH: this file's folder, set by PyInstaller
ICONS = os.path.join(SPECPATH, "icons")

# Apple's own Python (Command Line Tools, Xcode, the system) must never be bundled: the project
# ships no Apple binary. python.org and Homebrew builds are fine.
if any(part in sys.base_prefix for part in ("CommandLineTools", "Xcode.app", "/System/")):
    raise SystemExit("Refusing to build with Apple's Python (%s): use a python.org or Homebrew "
                     "Python." % sys.base_prefix)

with open(os.path.join(ROOT, "orchestrator", "__init__.py"), encoding="utf-8") as fh:
    VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', fh.read()).group(1)

# Licences ship with the app (MIT and BSD require it): ours, the notices list, Python's, and the
# metadata folder (licence files included) of every runtime package in this environment.
BUILD_ONLY = {"pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "macholib", "packaging",
              "setuptools", "pip", "pefile", "pywin32-ctypes", "pillow"}
datas = [(os.path.join(ROOT, "webapp", "static"), os.path.join("webapp", "static")),
         (os.path.join(ROOT, "LICENSE"), "."),
         (os.path.join(SPECPATH, "THIRD_PARTY_NOTICES.txt"), ".")]
for licence in (os.path.join(sysconfig.get_path("stdlib"), "LICENSE.txt"),
                os.path.join(sys.base_prefix, "LICENSE.txt")):
    if os.path.isfile(licence):
        datas.append((licence, "."))
        break
for dist in importlib.metadata.distributions():
    name = dist.metadata["Name"]
    if name and name.lower() not in BUILD_ONLY:
        datas += copy_metadata(name)

sys.path.insert(0, ROOT)           # so the converter's modules can be listed below
a = Analysis(
    [os.path.join(ROOT, "desktop.py")],
    pathex=[ROOT],
    datas=datas,
    # the converter imports some modules inside functions; list them all to be safe
    hiddenimports=collect_submodules("orchestrator") + collect_submodules("webapp"),
    excludes=["unittest", "pydoc", "test"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Exhume" if sys.platform != "linux" else "exhume",
    console=False,                 # no terminal window; output goes to the app's log file
    upx=False,                     # compressed executables trip more antivirus false alarms
    icon=os.path.join(ICONS, "exhume.ico" if sys.platform == "win32" else "exhume.icns"),
    target_arch=os.environ.get("EXHUME_TARGET_ARCH") or None,
    codesign_identity=None,        # ad-hoc signature (Apple Silicon needs one to launch at all)
)
coll = COLLECT(exe, a.binaries, a.datas, name="Exhume", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Exhume.app",
        icon=os.path.join(ICONS, "exhume.icns"),
        bundle_identifier="app.exhume.desktop",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": "Exhume",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.video",
            "NSHumanReadableCopyright": "Copyright (c) 2026 David Rice. MIT licence.",
        },
    )
