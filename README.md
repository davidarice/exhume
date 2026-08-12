# Final Crack Pro

**Version 1.5.0** — the version is also shown in the terminal when you start the app.

**Open old Final Cut Pro 7 projects in modern editing software.**

Final Crack Pro reads a Final Cut Pro 7 project file (`.fcp`) directly — you do **not**
need Final Cut Pro installed — and converts it to XML that **DaVinci Resolve** and
**Adobe Premiere Pro** can import. Your edit comes across: every clip, in the right
place, with timing and media links intact, so you can relink your footage and see the
cut exactly as it was.

> ### 🔒 Everything runs on your computer.
> There is no website and no upload. Your project files and media **never leave your
> machine** — Final Crack Pro runs a small page in your own browser and does all the
> work locally. You can even unplug from the internet while you use it.

---

## Get it running

### Downloadable Mac app

A self-contained macOS `.app` can bundle the Python runtime so users do not need
to install Python. The reproducible development and release process is described
in [MACOS_PACKAGING.md](MACOS_PACKAGING.md).

### Run from source

You need **Python 3** (version 3.8 or newer). Then it's one command.

### 1. Download this project

Click the green **Code** button on this page → **Download ZIP**, then unzip it.
(Or, if you use git: `git clone <this repo>`.)

### 2. Make sure you have Python 3

Open **Terminal** (macOS/Linux) or **Command Prompt** (Windows) and run:

```
python3 --version
```

If you see something like `Python 3.11.x`, you're set — skip to step 3. If it says
"command not found" or the version is below 3.8, install Python:

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
cd path/to/final-crack-pro
python3 run.py
```

(On Windows, use `python run.py` or `py run.py`.)

Your browser opens automatically. Drag in a `.fcp` project, pick the sequences you
want, and download the converted XML. Press **Ctrl+C** in the Terminal window to stop.

Then in Resolve or Premiere: **File → Import** and choose the downloaded `.xml`.

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

Final Crack Pro is fully offline. It serves a page only to your own computer
(`127.0.0.1`), processes the file you give it, and deletes its temporary working copies
afterward. Nothing is sent anywhere.

## License & notice

Released under the [MIT License](LICENSE).

Not affiliated with, endorsed by, or connected to Apple. "Final Cut Pro" is a trademark
of Apple Inc. This is an independent tool that reads the project **file format** for
interoperability so you can move your own projects to other software.
