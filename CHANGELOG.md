# What's new in Exhume

## 2.1.2 — 2026-10-17

- **Leaner app, same results.** The old project reader and XML writer, unused since 2.0.0, are removed. Conversions are identical to 2.1.1's, byte for byte, on every test project.

## 2.1.1 — 2026-10-13

- **Every sequence is listed.** A sequence nested inside an earlier sequence used to be left out of the list (one test project showed 46 of its 55 sequences). It now appears and converts like any other.

## 2.1.0 — 2026-10-13

- **Exhume is a desktop app** for macOS (Apple Silicon and Intel), Windows and Linux. No Python or Terminal needed: download it from the releases page, open it, drag in a project.
  - macOS and Windows: Exhume opens in its own window.
  - Linux: Exhume opens in your browser, with a small window to quit from.
- Quitting stops any conversion that is still running and deletes Exhume's temporary files.
- Converted files are saved rather than opened in the page.
- Running from source now needs Python 3.9 or newer (it was 3.8).
- The apps aren't code-signed yet: the README shows how to open them the first time.

## 2.0.0 — 2026-10-08

- **Renamed from Final Crack Pro to Exhume.** Old links redirect.
- **XML written the way Final Cut Pro 7 writes it.** The converter was rebuilt from a written description of Final Cut's own XML exporter; on the projects used to check it, its output is identical to Final Cut's export.
- A new project reader for Intel and PowerPC-era files alike: about three times faster, using a third less memory.
- Each project is read once, and every selected sequence is converted from that one reading.
- A hosted edition lives at [exhume.app](https://exhume.app).

## 1.5.0 — 2026-07-20

- Opens projects saved on PowerPC Macs around 2005 (Final Cut Pro 5 era).
- The version number is shown when Exhume starts.

## 1.4.0 — 2026-07-18

- Fixed audio clips being cut short in some projects (Intel-era projects, and projects with effects on their audio).

## 1.2.0 — 2026-07-17

- Opens projects saved on PowerPC Macs around 2007.
- Motion keyframes (position, scale and rotation changing over time) come across exactly.
