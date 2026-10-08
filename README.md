# Exhume

**Version 2.0.0** — the version is also shown in the terminal when you start the app.

New in 2.0.0: the XML is now produced the way Final Cut Pro 7 itself writes it — on the
projects used to check it, the output is identical to Final Cut's own XML export.

**Open old Final Cut Pro 7 projects in modern editing software.**

Exhume reads a Final Cut Pro 7 project file (`.fcp`) directly — you do **not**
need Final Cut Pro installed — and converts it to XML that **DaVinci Resolve** and
**Adobe Premiere Pro** can import. Your edit comes across: every clip, in the right
place, with timing and media links intact, so you can relink your footage and see the
cut exactly as it was.

> ### 🔒 This version runs entirely on your computer.
> Nothing is uploaded. Your project files and media **never leave your machine** —
> Exhume runs a small page in your own browser and does all the work locally. You can
> even unplug from the internet while you use it.
>
> Prefer not to install anything? The hosted edition at **[exhume.app](https://exhume.app)**
> does the same conversion on our servers and deletes your project within 24 hours.

*Exhume was previously published as "Final Crack Pro"; old links to that repository
redirect here.*

---

## Get it running

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
cd path/to/exhume
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

Exhume is fully offline. It serves a page only to your own computer
(`127.0.0.1`), processes the file you give it, and deletes its temporary working copies
afterward. Nothing is sent anywhere.

## License & notice

Released under the [MIT License](LICENSE).

Not affiliated with, endorsed by, or connected to Apple. "Final Cut Pro" is a trademark
of Apple Inc. This is an independent tool that reads the project **file format** for
interoperability so you can move your own projects to other software.
