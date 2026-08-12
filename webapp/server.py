"""FinalCrackPro backend: upload a binary .fcp project, scan its sequences,
and convert selected ones to importable XMEML over a small stdlib HTTP API.

Pure Python 3 stdlib. Parsing/conversion is CPU-bound (seconds to tens of
seconds per sequence), so all parser work runs in a shared process pool and
the HTTP threads only poll futures.
"""

import argparse
import atexit
import json
import os
import re
import secrets
import shutil
import signal
import sys
import tempfile
import threading
import time
import traceback
import uuid
import zipfile
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

# repo root on sys.path so `orchestrator` imports (also runs in spawned workers)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MAX_UPLOAD = 2 * 1024 ** 3
MAX_JOBS = 16                    # live (unreaped) uploads at once
MAX_TOTAL_BYTES = 8 * 1024 ** 3  # ceiling on stored upload bytes across jobs
JOB_TTL = 60 * 60                # evict jobs idle this long (seconds)
REAP_EVERY = 60
CHUNK = 256 * 1024
ID_RE = re.compile(r"[0-9a-f]{32}")
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}

# module-level registries only (no persistence); guarded by _lock
_lock = threading.Lock()
_jobs = {}       # job id -> {dir, path, filename, size, future, sequences, error}
_converts = {}   # convert id -> {job, parts, error, zip}
_tempdirs = []
_pool = None     # shared ProcessPoolExecutor, created in main()


# --- worker-process functions (module-level so they pickle) -------------------

def _le_sibling(path):
    """Deterministic path of the little-endian transcode next to the upload."""
    return str(Path(path).with_name("project_le.fcp"))


def _scan_worker(path):
    """One full parse -> small plain-JSON summary (crosses the process boundary)."""
    from orchestrator import export
    from orchestrator.emit import _tc_string
    # triage BEFORE the expensive parse: real KeyGrip magic, and the byte-order
    # flag at 0x08 (01 = Intel/little-endian; 00 = PowerPC-era big-endian, the
    # same object graph with byte-swapped scalars)
    with open(path, "rb") as fh:
        head = fh.read(16)
    if head[:5] != b"\xa2KeyG":
        raise ValueError("This is not a Final Cut Pro project file.")
    from orchestrator import keyg_swab
    if keyg_swab.is_big_endian(head):
        # PowerPC-era project: transcode once to a little-endian twin beside
        # the upload and scan THAT (_convert_worker picks the twin up too)
        le_path = _le_sibling(path)
        try:
            tmp = le_path + ".tmp"
            keyg_swab.swab_file(path, tmp)
            os.replace(tmp, le_path)
        except Exception:
            raise ValueError(
                "this is a PowerPC-era (big-endian) Final Cut Pro project — "
                "an older byte order this converter can't read yet. "
                "Re-saving it with Intel FCP 6/7 would convert it.") from None
        path = le_path
    rich = export._enriched_sequences(path)
    seqs = []
    for i, s in enumerate(rich):
        tracks = s["video"] + s["audio"]
        items = [it for tr in tracks for it in tr]
        dur = max((int(it["end"]) for it in items
                   if it.get("end") is not None and int(it["end"]) >= 0), default=0)
        tb, ntsc = s["timebase"], s["ntsc"] == "TRUE"
        # start_tc is None (default) or {'frame','displayformat'} — test None
        # explicitly (frame 0 is a real recovered value); DF sequences show
        # the semicolon string
        stc = s.get("start_tc")
        if isinstance(stc, dict):
            df = stc.get("displayformat") == "DF"
            start_str = _tc_string(int(stc["frame"]), tb, df) if stc.get("frame") is not None else None
        else:
            start_str = _tc_string(int(stc), tb) if stc else None
        raw = s["name"] or None
        seqs.append({
            "index": i,
            "name": raw or f"Sequence {i + 1}",
            "raw_name": raw,     # exact name from the binary (may be null)
            "timebase": tb,
            "ntsc": ntsc,
            "fps": f"{tb * 1000 / 1001:.2f}" if ntsc else str(tb),
            "width": s["width"],
            "height": s["height"],
            "vtracks": len(s["video"]),
            "atracks": len(s["audio"]),
            "clips": sum(1 for it in items if it.get("kind", "clip") == "clip"),
            "transitions": sum(1 for it in items if it.get("kind") == "transition"),
            "generators": sum(1 for it in items if it.get("kind") == "generator"),
            "duration_frames": dur,
            "duration_tc": _tc_string(dur, tb),
            "start_tc": start_str,
            "markers": len(s.get("markers") or []),
        })
    if not seqs:
        raise ValueError("no sequences found in this project")
    return seqs


def _convert_worker(path, index, out_path):
    """Re-parse the project and export one sequence; returns the XML byte count."""
    from orchestrator import export
    le_path = _le_sibling(path)
    if os.path.exists(le_path):     # big-endian upload: use the transcoded twin
        path = le_path
    xml = export.export_importable_sequence(path, seq_index=index)
    # temp file + rename so a concurrent reader never sees a partial file
    tmp = out_path + ".tmp"
    Path(tmp).write_bytes(xml)
    os.replace(tmp, out_path)
    return len(xml)


# --- helpers -------------------------------------------------------------------

def _sanitize_component(name, fallback):
    """Filesystem-safe name from untrusted binary strings: whitelist
    [A-Za-z0-9 ._-], collapse runs, strip; never empty."""
    clean = re.sub(r"[^A-Za-z0-9 ._-]+", " ", name or "")
    clean = re.sub(r"\s+", " ", clean).strip(" .")
    return clean or fallback


def _header_filename(name):
    """ASCII-only Content-Disposition value: no CR/LF/quotes/backslashes."""
    out = name.encode("ascii", "replace").decode("ascii")
    return re.sub(r'[\r\n"\\]', "", out)


def _job_state(job):
    """Snapshot a job, materializing a finished scan future (lazy polling:
    a running parse is never waited on). Call with _lock held."""
    fut = job["future"]
    if fut is not None and fut.done():
        try:
            job["sequences"] = fut.result()
        except Exception as exc:
            traceback.print_exc()
            job["error"] = str(exc) or exc.__class__.__name__
        job["future"] = None
    if job["error"] is not None:
        return {"status": "error", "error": job["error"]}
    if job["sequences"] is None:
        return {"status": "parsing"}
    return {"status": "ready", "filename": job["filename"], "size": job["size"],
            "sequences": job["sequences"]}


def _convert_state(conv):
    """Snapshot a conversion, materializing finished futures. Call with _lock held."""
    for p in conv["parts"]:
        fut = p["future"]
        if fut is not None and fut.done():
            try:
                p["bytes"] = fut.result()
            except Exception as exc:
                traceback.print_exc()
                conv["error"] = (f"sequence {p['index']}: "
                                 f"{str(exc) or exc.__class__.__name__}")
            p["future"] = None
    if conv["error"] is not None:
        return {"status": "error", "error": conv["error"]}
    done = sum(1 for p in conv["parts"] if p["future"] is None)
    if done < len(conv["parts"]):
        return {"status": "working", "done": done, "total": len(conv["parts"])}
    return {"status": "done",
            "files": [{"index": p["index"], "name": p["name"], "bytes": p["bytes"]}
                      for p in conv["parts"]]}


def _pool_size():
    return max(2, (os.cpu_count() or 2) // 2)


def _submit(fn, *args):
    """Submit to the shared pool; if a dead worker broke it (segfault/OOM),
    rebuild the executor so one poisoned job cannot brick the whole service."""
    global _pool
    with _lock:
        try:
            return _pool.submit(fn, *args)
        except BrokenProcessPool:
            _pool.shutdown(wait=False, cancel_futures=True)
            _pool = ProcessPoolExecutor(max_workers=_pool_size())
            return _pool.submit(fn, *args)


def _reap_stale_jobs():
    """Evict jobs (and their conversions and tempdirs) idle longer than JOB_TTL."""
    cutoff = time.time() - JOB_TTL
    with _lock:
        dead = {jid for jid, job in _jobs.items() if job["ts"] < cutoff}
        if not dead:
            return
        dirs = [_jobs.pop(jid)["dir"] for jid in dead]
        for cid in [c for c, v in _converts.items() if v["job"] in dead]:
            del _converts[cid]
        for d in dirs:
            if d in _tempdirs:
                _tempdirs.remove(d)
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)


def _reaper_loop():
    while True:
        time.sleep(REAP_EVERY)
        _reap_stale_jobs()


def _cleanup_tempdirs():
    for d in _tempdirs:
        shutil.rmtree(d, ignore_errors=True)


# --- HTTP handler ----------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FinalCrackPro/1.0"

    def do_GET(self):
        self._safely(self._route_get)

    def do_POST(self):
        self._safely(self._route_post)

    def _safely(self, route):
        try:
            route()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            traceback.print_exc()
            try:
                self._json({"error": "internal server error"}, 500)
            except OSError:
                pass

    # -- routing

    def _forbid(self, msg):
        self.close_connection = True   # body (if any) is left unread
        self._json({"error": msg}, 403)

    def _host_ok(self):
        """Only the expected loopback authority may address us (anti DNS-rebinding)."""
        return self.headers.get("Host", "") in self.server.allowed_hosts

    def _cross_site(self):
        """True for requests a foreign origin could have sent: browser fetch/XHR
        (even no-cors) always carries Origin; our SPA also sends X-FCP: 1,
        which cross-origin no-cors requests cannot set."""
        origin = self.headers.get("Origin")
        if origin is not None and urlsplit(origin).netloc not in self.server.allowed_hosts:
            return True
        return self.headers.get("X-FCP") != "1"

    def _route_get(self):
        if not self._host_ok():
            return self._forbid("bad Host header")
        path = urlsplit(self.path).path
        if path == "/":
            return self._static("index.html")
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        if path == "/api/session":
            return self._json({"shutdown_token": self.server.shutdown_token})
        if m := re.fullmatch(r"/api/job/([0-9a-f]{32})", path):
            return self._job_status(m.group(1))
        if m := re.fullmatch(r"/api/convert/([0-9a-f]{32})", path):
            return self._convert_status(m.group(1))
        if m := re.fullmatch(r"/api/download/([0-9a-f]{32})(?:/(\d+))?", path):
            idx = int(m.group(2)) if m.group(2) is not None else None
            return self._download(m.group(1), idx)
        self._json({"error": "not found"}, 404)

    def _route_post(self):
        if not self._host_ok():
            return self._forbid("bad Host header")
        url = urlsplit(self.path)
        if url.path.startswith("/api/") and self._cross_site():
            return self._forbid("cross-site request rejected")
        if url.path == "/api/upload":
            return self._upload(url.query)
        if url.path == "/api/convert":
            return self._convert()
        if url.path == "/api/shutdown":
            return self._shutdown()
        self.close_connection = True   # unread body would poison keep-alive
        self._json({"error": "not found"}, 404)

    # -- responses

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype, download_name=None):
        path = Path(path)
        if not path.is_file():
            return self._json({"error": "file missing"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(path.stat().st_size))
        if download_name:
            self.send_header("Content-Disposition",
                             f'attachment; filename="{_header_filename(download_name)}"')
        self.end_headers()
        with open(path, "rb") as fh:
            while chunk := fh.read(CHUNK):
                self.wfile.write(chunk)

    # -- static files

    def _static(self, name):
        # untrusted path segment: flat filenames with whitelisted extensions only
        # ('%' rejected pre-decode, so no percent-escape smuggling)
        if "/" in name or ".." in name or "%" in name:
            return self._json({"error": "bad path"}, 400)
        ctype = STATIC_TYPES.get(os.path.splitext(name)[1].lower())
        if ctype is None:
            return self._json({"error": "bad path"}, 400)
        self._file(STATIC_DIR / name, ctype)

    # -- API: upload + job status

    def _shutdown(self):
        """Stop this local app instance after a same-origin, tokened request."""
        supplied = self.headers.get("X-FCP-Shutdown", "")
        if not secrets.compare_digest(supplied, self.server.shutdown_token):
            return self._forbid("bad shutdown token")
        self._json({"status": "stopping"})
        # BaseServer.shutdown() must be called from a different thread than
        # serve_forever(), which is the main thread in the packaged app.
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def _upload(self, query):
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError:
            length = 0
        if length <= 0:
            self.close_connection = True
            return self._json({"error": "missing or empty body"}, 400)
        if length > MAX_UPLOAD:
            self.close_connection = True
            return self._json({"error": "body exceeds 2 GiB limit"}, 413)
        with _lock:
            full = (len(_jobs) >= MAX_JOBS
                    or sum(j["size"] for j in _jobs.values()) + length > MAX_TOTAL_BYTES)
        if full:
            self.close_connection = True
            return self._json({"error": "too many stored uploads — try again later"}, 429)

        # ?name= is display/download naming only: unquote once, then basename
        raw_name = next((v for k, _, v in
                         (p.partition("=") for p in query.split("&")) if k == "name"), "")
        filename = os.path.basename(unquote(raw_name)) or "upload.fcp"

        tmpdir = tempfile.mkdtemp(prefix="finalcrackpro-")
        with _lock:
            _tempdirs.append(tmpdir)
        dest = Path(tmpdir) / "project.fcp"
        remaining = length
        with open(dest, "wb") as out:
            while remaining:
                chunk = self.rfile.read(min(CHUNK, remaining))
                if not chunk:
                    break
                out.write(chunk)
                remaining -= len(chunk)
        if remaining:
            self.close_connection = True
            return self._json({"error": "truncated upload"}, 400)

        job_id = uuid.uuid4().hex
        fut = _submit(_scan_worker, str(dest))
        with _lock:
            _jobs[job_id] = {"dir": tmpdir, "path": str(dest), "filename": filename,
                             "size": length, "future": fut, "ts": time.time(),
                             "sequences": None, "error": None}
        self._json({"job": job_id})

    def _job_status(self, job_id):
        with _lock:
            job = _jobs.get(job_id)
            if job:
                job["ts"] = time.time()
            state = _job_state(job) if job else None
        if job is None:
            return self._json({"error": "unknown job"}, 404)
        self._json(state)

    # -- API: convert + status + download

    def _convert(self):
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError:
            length = 0
        if not 0 < length <= 1024 * 1024:
            self.close_connection = True
            return self._json({"error": "missing or oversized body"}, 400)
        try:
            req = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            return self._json({"error": "invalid JSON body"}, 400)

        job_id = req.get("job") if isinstance(req, dict) else None
        if not (isinstance(job_id, str) and ID_RE.fullmatch(job_id)):
            return self._json({"error": "bad job id"}, 400)
        with _lock:
            job = _jobs.get(job_id)
            state = _job_state(job) if job else None
        if job is None:
            return self._json({"error": "unknown job"}, 404)
        if state["status"] != "ready":
            return self._json({"error": f"job is {state['status']}, not ready"}, 409)

        indices = req.get("indices")
        n = len(job["sequences"])
        if (not isinstance(indices, list) or not indices
                or not all(isinstance(i, int) and not isinstance(i, bool)
                           and 0 <= i < n for i in indices)):
            return self._json({"error": "bad indices"}, 400)
        indices = sorted(set(indices))

        conv_id = uuid.uuid4().hex
        # per-conversion subdir: repeat converts of one job never share paths
        out_dir = Path(job["dir"]) / conv_id
        out_dir.mkdir()
        parts = []
        for i in indices:
            stem = _sanitize_component(job["sequences"][i]["raw_name"], f"sequence-{i + 1}")
            fname = f"{i + 1:02d} - {stem}.xml"
            out_path = str(out_dir / fname)
            fut = _submit(_convert_worker, job["path"], i, out_path)
            parts.append({"index": i, "name": fname, "path": out_path,
                          "future": fut, "bytes": None})
        with _lock:
            job["ts"] = time.time()
            _converts[conv_id] = {"job": job_id, "parts": parts,
                                  "error": None, "zip": None}
        self._json({"convert": conv_id})

    def _convert_status(self, conv_id):
        with _lock:
            conv = _converts.get(conv_id)
            state = _convert_state(conv) if conv else None
            if conv and (job := _jobs.get(conv["job"])):
                job["ts"] = time.time()
        if conv is None:
            return self._json({"error": "unknown conversion"}, 404)
        self._json(state)

    def _download(self, conv_id, index):
        with _lock:
            conv = _converts.get(conv_id)
            state = _convert_state(conv) if conv else None
            job = _jobs.get(conv["job"]) if conv else None
            if job:
                job["ts"] = time.time()
        if conv is None or job is None:
            return self._json({"error": "unknown conversion"}, 404)
        if state["status"] == "error":
            return self._json({"error": state["error"]}, 500)
        if state["status"] != "done":
            return self._json({"error": "conversion not finished"}, 409)

        parts = conv["parts"]
        if index is not None:
            part = next((p for p in parts if p["index"] == index), None)
            if part is None:
                return self._json({"error": "unknown sequence index"}, 404)
            return self._file(part["path"], "application/xml", part["name"])
        if len(parts) == 1:
            return self._file(parts[0]["path"], "application/xml", parts[0]["name"])

        with _lock:   # build the bundle once; serialize concurrent first downloads
            zip_path = conv["zip"]
            if zip_path is None:
                stem = _sanitize_component(Path(job["filename"]).stem, "project")
                zip_path = str(Path(job["dir"]) / conv_id / f"{stem}-xmeml.zip")
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for p in parts:
                        zf.write(p["path"], arcname=p["name"])
                conv["zip"] = zip_path
        self._file(zip_path, "application/zip", Path(zip_path).name)


# --- entrypoint -----------------------------------------------------------------

def _default_port():
    try:
        return int(os.environ.get("FCP_PORT", "8577"))
    except ValueError:
        return 8577


def main():
    global _pool
    ap = argparse.ArgumentParser(description="FinalCrackPro backend")
    ap.add_argument("--port", type=int, default=_default_port())
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    _pool = ProcessPoolExecutor(max_workers=_pool_size())
    atexit.register(_cleanup_tempdirs)
    threading.Thread(target=_reaper_loop, daemon=True).start()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.shutdown_token = secrets.token_urlsafe(32)
    server.allowed_hosts = {f"{h}:{args.port}"
                            for h in ("127.0.0.1", "localhost", "[::1]", args.host)}

    # Finder/Dock Quit normally reaches a GUI process as SIGTERM. Convert it
    # into the same orderly server shutdown used by the browser's Quit button.
    def request_shutdown(_signum, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, request_shutdown)
        signal.signal(signal.SIGTERM, request_shutdown)
    print(f"FinalCrackPro backend on http://{args.host}:{args.port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        _pool.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
