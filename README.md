# Exhume

**Version 2.1.0**

New in 2.1.0: Exhume is now a **downloadable app** for macOS, Windows and Linux. No Python, no
Terminal: download it, open it, drag in your project. (Since 2.0.0 the XML is produced the way
Final Cut Pro 7 itself writes it: on the projects used to check it, the output is identical to
Final Cut's own XML export.)

**Open old Final Cut Pro 7 projects in modern editing software.**

Exhume reads a Final Cut Pro 7 project file (`.fcp`) directly — you do **not**
need Final Cut Pro installed — and converts it to XML that **DaVinci Resolve** and
**Adobe Premiere Pro** can import. Your edit comes across: every clip, in the right
place, with timing and media links intact, so you can relink your footage and see the
cut exactly as it was.

> ### 🔒 This version runs entirely on your computer.
> Nothing is uploaded. Your project files and media **never leave your machine** —
> Exhume does all the work locally, and you can even unplug from the internet while you
> use it.
>
> Prefer not to install anything? The hosted edition at **[exhume.app](https://exhume.app)**
> does the same conversion on our servers and deletes your project within 24 hours.

*Exhume was previously published as "Final Crack Pro"; old links to that repository
redirect here.*

---

## Download the app

| | Download | Needs |
|---|---|---|
| **macOS** | [Exhume-macOS.dmg](https://github.com/davidarice/exhume/releases/latest/download/Exhume-macOS.dmg) | macOS 11 or newer, Apple Silicon or Intel |
| **Windows** | [Exhume-Windows-Setup.exe](https://github.com/davidarice/exhume/releases/latest/download/Exhume-Windows-Setup.exe) | Windows 10 or 11, 64-bit |
| **Linux** | [Exhume-Linux-x86_64.AppImage](https://github.com/davidarice/exhume/releases/latest/download/Exhume-Linux-x86_64.AppImage) | 64-bit Linux, Ubuntu 22.04 or similar and newer |

All versions are on the [releases page](https://github.com/davidarice/exhume/releases), with a
`SHA256SUMS.txt` to check the downloads against.

The apps aren't code-signed yet, so the first time you open Exhume your computer warns that it
can't check who made it. You only need to get past this once:

### macOS

1. Open `Exhume-macOS.dmg` and drag **Exhume** into **Applications**.
2. Open Exhume. macOS says it can't verify it; click **Done**.
3. Open **System Settings → Privacy & Security**, scroll down to **Security**, and click
   **Open Anyway** next to "Exhume was blocked". Confirm with your password, then **Open**.

(On macOS 14 Sonoma and earlier you can instead Control-click Exhume in Applications and choose
**Open**.)

Exhume opens in its own window. Close the window, or press **⌘Q**, to quit.

### Windows

1. Run `Exhume-Windows-Setup.exe`. If Windows says "Windows protected your PC", click
   **More info → Run anyway**.
2. The installer puts Exhume in your Start menu. It installs for your account only, so it
   doesn't ask for administrator rights. Uninstall it from **Settings → Apps** like any app.

Exhume opens in its own window, using Microsoft Edge WebView2, which comes with Windows 11 and
up-to-date Windows 10. Without it, Exhume opens in your web browser instead.

### Linux

1. Make the file executable: right-click → **Properties → Allow executing file as program**, or
   `chmod +x Exhume-Linux-x86_64.AppImage`.
2. Double-click it. Exhume opens in your web browser, with a small window that keeps it running;
   close that window to quit.

If it complains about FUSE, run it as
`./Exhume-Linux-x86_64.AppImage --appimage-extract-and-run`.

---

## Using Exhume

Drag in a `.fcp` project (or click to choose one), pick the sequences you want, and save the
converted XML. Then in Resolve or Premiere: **File → Import** and choose the `.xml`.

If something goes wrong, the app keeps a log you can attach to a bug report:
`~/Library/Logs/Exhume/exhume.log` (macOS), `%LOCALAPPDATA%\Exhume\exhume.log` (Windows) or
`~/.cache/exhume/exhume.log` (Linux).

---

## Or run it from source

If you'd rather not run a downloaded app, Exhume also runs straight from this code. You need
**Python 3** (version 3.9 or newer); nothing else is installed.

### 1. Download this project

Click the green **Code** button on this page → **Download ZIP**, then unzip it.
(Or, if you use git: `git clone <this repo>`.)

### 2. Make sure you have Python 3

Open **Terminal** (macOS/Linux) or **Command Prompt** (Windows) and run:

```
python3 --version
```

If you see something like `Python 3.11.x`, you're set — skip to step 3. If it says
"command not found" or the version is below 3.9, install Python:

- **macOS** — either:
  - with [Homebrew](https://brew.sh): `brew install python`, **or**
  - download the official installer from **https://www.python.org/downloads/** and run it.
- **Windows** — download the installer from **https://www.python.org/downloads/**,
  run it, and **tick "Add Python to PATH"** on the first screen.
- **Linux** — it's almost always already installed; if not, use your package manager
  (e.g. `sudo apt install python3` on Debian/Ubuntu).

### 3. Run it

In Terminal / Command Prompt, go to the unzipped folder and start it:

```
cd path/to/exhume
python3 run.py
```

(On Windows, use `python run.py` or `py run.py`.)

Your browser opens automatically. Press **Ctrl+C** in the Terminal window to stop.

---

## What to expect

- **Your cut is faithful** — clip order, in/out points, timeline placement, tracks, and
  the media file references (so you can relink your footage) all come across.
- **Simple effects and transitions** (dissolves, basic motion, opacity, speed changes)
  translate.
- **Complex or third‑party plugin effects may not** carry over — that's a limitation of
  moving between different editing systems, and you'd typically re‑apply those in your
  new app anyway. The important thing — the edit itself — is preserved.
- **PowerPC‑era projects** (from very old Final Cut versions) are supported; they're
  converted automatically.

Big projects can take anywhere from a few seconds to a couple of minutes to parse —
that's normal; give it a moment.

---

## Privacy

Exhume is fully offline. It serves a page only to your own computer
(`127.0.0.1`), processes the file you give it, and deletes its temporary working copies
when you quit. Nothing is sent anywhere.

## Building the app yourself

The downloads are built by [`.github/workflows/release.yml`](.github/workflows/release.yml) with
PyInstaller. To build one locally, use a python.org or Homebrew Python 3.14:

```
python3 -m venv .venv-desktop
.venv-desktop/bin/pip install -r packaging/requirements-desktop.txt
.venv-desktop/bin/pyinstaller packaging/exhume.spec
```

The app lands in `dist/`. `python desktop.py` runs the app version from source, and
`--self-test` checks a build without opening a window.

## License & notice

Released under the [MIT License](LICENSE). The downloadable app also contains the third-party
software listed in [`packaging/THIRD_PARTY_NOTICES.txt`](packaging/THIRD_PARTY_NOTICES.txt).

Not affiliated with, endorsed by, or connected to Apple. "Final Cut Pro" is a trademark
of Apple Inc. This is an independent tool that reads the project **file format** for
interoperability so you can move your own projects to other software.
