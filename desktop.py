#!/usr/bin/env python3
"""Exhume desktop app: the same local converter as run.py, in a window of its own.

This is the entry point of the downloadable builds (see packaging/). On macOS and Windows the page
shows in a native window (pywebview) and closing it quits. Where that isn't available (the Linux
build, or a Windows without Microsoft's Edge WebView2 runtime) the page opens in the browser, with
a small window to quit from. Nothing leaves the computer either way.

From source: pip install -r packaging/requirements-desktop.txt, then python desktop.py.
`--self-test` checks a build without opening a window (used by the release workflow).
"""
import multiprocessing
import os
import sys
import threading
import time
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

WINDOW_SIZE = (1100, 800)
MIN_WINDOW_SIZE = (800, 600)


def _log_dir():
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Logs", "Exhume")
    if sys.platform == "win32":
        return os.path.join(os.environ.get("LOCALAPPDATA") or home, "Exhume")
    return os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache"), "exhume")


def _log_to_file():
    """A built app has no terminal: keep its output in a log file, fresh each start, so a problem
    report can include it."""
    try:
        os.makedirs(_log_dir(), exist_ok=True)
        log = open(os.path.join(_log_dir(), "exhume.log"), "w", buffering=1, encoding="utf-8")
    except OSError:
        return
    sys.stdout = sys.stderr = log


def _open_browser(url):
    if getattr(sys, "frozen", False) and sys.platform.startswith("linux"):
        # the built app points LD_LIBRARY_PATH at its own libraries; a browser started with that
        # setting can crash, so hand it the original one
        original = os.environ.get("LD_LIBRARY_PATH_ORIG")
        if original is None:
            os.environ.pop("LD_LIBRARY_PATH", None)
        else:
            os.environ["LD_LIBRARY_PATH"] = original
    webbrowser.open(url)


def _on_mac_quit(cleanup):
    """Quit from the menu bar, the Dock or a logout ends a Mac app without returning to Python, so
    run the cleanup when macOS announces the quit. Returns the observer (keep a reference)."""
    if sys.platform != "darwin":
        return None
    try:
        import AppKit
        import Foundation
    except ImportError:
        return None
    return Foundation.NSNotificationCenter.defaultCenter().addObserverForName_object_queue_usingBlock_(
        AppKit.NSApplicationWillTerminateNotification, None, None, lambda _note: cleanup())


def _run_window(url, on_start=None):
    """Show the page in a native window until it is closed. False when this computer can't show
    one, so the caller falls back to the browser. `on_start(window)` runs on its own thread once
    the window is up (the GUI self-test)."""
    try:
        import webview
    except ImportError:                     # the Linux build ships without pywebview
        return False
    if sys.platform == "win32":
        try:
            from webview.platforms import winforms
        except Exception:
            return False
        if winforms.renderer != "edgechromium":
            # no WebView2 runtime: pywebview would fall back to Internet Explorer, which can't run
            # the page
            return False
    webview.settings["ALLOW_DOWNLOADS"] = True
    window = webview.create_window("Exhume", url, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1],
                                   min_size=MIN_WINDOW_SIZE)
    try:
        if on_start:
            webview.start(on_start, (window,))
        else:
            webview.start()
    except Exception as exc:                # no usable GUI backend
        print("Exhume: no app window (%s); using the browser" % exc)
        return False
    return True


def _run_browser_fallback(url):
    """The page in the browser, plus a small window that keeps the app alive and quits it."""
    _open_browser(url)
    try:
        import tkinter as tk
        root = tk.Tk()
    except Exception:                       # no Tk or no display: a terminal session
        print("Exhume is running at %s (press Ctrl+C to stop)" % url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return
    root.title("Exhume")
    root.resizable(False, False)
    frame = tk.Frame(root, padx=24, pady=20)
    frame.pack()
    tk.Label(frame, text="Exhume is running in your browser.", font=("TkDefaultFont", 13, "bold")).pack(anchor="w")
    tk.Label(frame, text="Keep this window open while you convert. Closing it quits Exhume.",
             fg="#555555").pack(anchor="w", pady=(4, 14))
    buttons = tk.Frame(frame)
    buttons.pack(anchor="e")
    tk.Button(buttons, text="Open again", command=lambda: _open_browser(url)).pack(side="left", padx=(0, 8))
    tk.Button(buttons, text="Quit", command=root.destroy).pack(side="left")
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()


def _self_test(url):
    """Serve the page, then upload a file that isn't a project: the spawned converter worker must
    start, load the bundled converter and refuse it. Returns a process exit code."""
    import json
    import urllib.request

    def fetch(path, data=None, headers=None):
        req = urllib.request.Request(url + path, data=data, headers=headers or {})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read()

    try:
        status, page = fetch("/")
        assert status == 200 and b"<title>Exhume" in page, "page"
        status, _ = fetch("/static/app.js")
        assert status == 200, "app.js"
        _, body = fetch("/api/upload?name=self-test.fcp", data=b"not a project " * 64,
                        headers={"X-FCP": "1", "Content-Type": "application/octet-stream"})
        job = json.loads(body)["job"]
        deadline = time.time() + 180
        while time.time() < deadline:
            state = json.loads(fetch("/api/job/" + job)[1])
            if state["status"] != "parsing":
                assert state.get("error") == "This is not a Final Cut Pro project file.", state
                print("Exhume self-test passed")
                return 0
            time.sleep(0.5)
        raise AssertionError("the converter worker did not answer within 3 minutes")
    except Exception as exc:
        print("Exhume self-test FAILED: %r" % (exc,))
        return 1


def _self_test_window(url):
    """Open the real window, check the page loaded in it, close it. Returns a process exit code."""
    seen = {}

    def check(window):
        if window.events.loaded.wait(60):
            seen["title"] = window.evaluate_js("document.title")
        window.destroy()

    shown = _run_window(url, check)
    ok = shown and seen.get("title") == "Exhume"
    print("Exhume window self-test %s (%s)" % ("passed" if ok else "FAILED",
                                                seen if shown else "no window on this computer"))
    return 0 if ok else 1


def main():
    args = sys.argv[1:]
    self_test = "--self-test" in args or "--self-test-gui" in args
    if getattr(sys, "frozen", False) and not self_test:
        _log_to_file()

    from orchestrator import __version__
    from webapp import server

    # spawn everywhere: forking a process that runs a GUI is unsafe
    httpd = server.make_server("127.0.0.1", 0, mp_context=multiprocessing.get_context("spawn"),
                               quiet=True)
    url = "http://127.0.0.1:%d" % httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print("Exhume v%s at %s" % (__version__, url))

    stopped = threading.Event()

    def cleanup():                   # stop the server and any conversion; delete the temp files
        if not stopped.is_set():
            stopped.set()
            server.shutdown_all(httpd)

    quit_observer = _on_mac_quit(cleanup)   # the reference keeps the observer registered
    try:
        if "--self-test-gui" in args:
            code = _self_test_window(url)
        elif self_test:
            code = _self_test(url)
        else:
            if not _run_window(url):
                _run_browser_fallback(url)
            code = 0
    finally:
        cleanup()
    sys.exit(code)


if __name__ == "__main__":
    multiprocessing.freeze_support()   # must come first: in a built app the workers re-run this file
    main()
