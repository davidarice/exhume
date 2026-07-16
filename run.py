#!/usr/bin/env python3
"""Final Crack Pro — convert Final Cut Pro 7 projects to XML, entirely on your machine.

Just run:

    python3 run.py

Your browser opens a local page where you drag in a .fcp project and download
importable XML for DaVinci Resolve or Adobe Premiere Pro. Nothing is uploaded
anywhere — there is no server and no internet connection is used.
"""
import os
import socket
import sys
import threading
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

MIN_PY = (3, 8)
DEFAULT_PORT = 8577


def _pick_port(preferred):
    """A free loopback port: the preferred one if available, else OS-assigned."""
    for candidate in (preferred, 0):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", candidate))
            port = s.getsockname()[1]
            s.close()
            return port
        except OSError:
            continue
    return preferred


def main():
    if sys.version_info < MIN_PY:
        sys.exit(
            "Final Crack Pro needs Python %d.%d or newer — you have %s.\n"
            "See the README for how to install a current Python."
            % (MIN_PY[0], MIN_PY[1], sys.version.split()[0]))

    port = _pick_port(DEFAULT_PORT)
    url = "http://127.0.0.1:%d" % port
    print()
    print("  Final Crack Pro is running — everything stays on this computer.")
    print("  Open this in your browser:  %s" % url)
    print("  (it should open automatically; press Ctrl+C here to stop)")
    print()

    # open the browser a moment after the server starts listening
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    from webapp import server
    sys.argv = ["final-crack-pro", "--port", str(port), "--host", "127.0.0.1"]
    try:
        server.main()
    except KeyboardInterrupt:
        print("\n  Stopped. Your files were never uploaded anywhere. Goodbye.\n")


if __name__ == "__main__":
    main()
