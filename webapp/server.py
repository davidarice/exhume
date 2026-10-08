"""Exhume backend: upload a binary .fcp project, scan its sequences,
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
import shutil
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

def _tc(frames, timebase):
    """hh:mm:ss:ff at the sequence's timebase (non-drop; the UI's duration column)."""
    f = int(frames)
    ff = f % timebase
    sec = f // timebase
    return f"{sec // 3600:02d}:{sec // 60 % 60:02d}:{sec % 60:02d}:{ff:02d}"


def _sequences_of(root):
    """The browser's sequences in document order from the whole-project document: the
    <sequence> elements under <project><children> and any <bin><children>, skipping the
    id-only references the exporter writes for a sequence met earlier (spec §3)."""
    out = []

    def walk(children):
        for el in children:
            if el.tag == "sequence" and el.find("media") is not None:
                out.append(el)
            elif el.tag == "bin":
                ch = el.find("children")
                if ch is not None:
                    walk(ch)

    ch = root.find("project/children")
    if ch is not None:
        walk(ch)
    return out


_DOCS = {}          # per worker process: path -> (size, mtime, parsed project); at most _DOC_CACHE
_DOC_CACHE = 2


def _load(path):
    """The parsed project, parsed once per worker process and kept while the upload is unchanged:
    parsing is the larger half of a conversion, and a scan and the conversions that follow it
    all read the same file."""
    from orchestrator import xmeml_emit
    st = os.stat(path)
    key = (st.st_size, st.st_mtime_ns)
    hit = _DOCS.get(path)
    if hit is not None and hit[0] == key:
        return hit[1]
    doc = xmeml_emit.load(path)
    if len(_DOCS) >= _DOC_CACHE:
        _DOCS.pop(next(iter(_DOCS)))
    _DOCS[path] = (key, doc)
    return doc


def _scan_worker(path):
    """One full export -> small plain-JSON summary per sequence (crosses the process boundary)."""
    import xml.etree.ElementTree as ET
    from orchestrator import xmeml_emit
    # triage BEFORE the expensive parse: real KeyGrip magic (the spec reader takes
    # Intel and PowerPC-era byte orders alike)
    with open(path, "rb") as fh:
        head = fh.read(16)
    if head[:5] != b"\xa2KeyG":
        raise ValueError("This is not a Final Cut Pro project file.")
    root = ET.fromstring(xmeml_emit.export_project(_load(path), project_name=os.path.splitext(os.path.basename(path))[0]))
    seqs = []
    for i, s in enumerate(_sequences_of(root)):
        rate = s.find("rate")
        tb = int(rate.findtext("timebase") or 0) if rate is not None else 0
        ntsc = (rate.findtext("ntsc") if rate is not None else "") == "TRUE"
        fmt = s.find("media/video/format/samplecharacteristics")
        items = [it for kind in ("video", "audio")
                 for tr in s.findall(f"media/{kind}/track") for it in tr]
        dur = int(float(s.findtext("duration") or 0))
        raw = s.findtext("name")
        seqs.append({
            "index": i,
            "name": raw or f"Sequence {i + 1}",
            "raw_name": raw,     # exact name from the binary (may be null)
            "uuid": s.findtext("uuid"),
            "timebase": tb,
            "ntsc": ntsc,
            "fps": f"{tb * 1000 / 1001:.2f}" if ntsc else str(tb),
            "width": int(fmt.findtext("width")) if fmt is not None and fmt.findtext("width") else None,
            "height": int(fmt.findtext("height")) if fmt is not None and fmt.findtext("height") else None,
            "vtracks": len(s.findall("media/video/track")),
            "atracks": len(s.findall("media/audio/track")),
            "clips": sum(1 for it in items if it.tag == "clipitem"),
            "transitions": sum(1 for it in items if it.tag == "transitionitem"),
            "generators": sum(1 for it in items if it.tag == "generatoritem"),
            "duration_frames": dur,
            "duration_tc": _tc(dur, tb) if tb else None,
            "start_tc": s.findtext("timecode/string"),
            "markers": len(s.findall("marker")),
        })
    if not seqs:
        raise ValueError("no sequences found in this project")
    return seqs


def _convert_worker(path, parts):
    """Export the selected sequences (by UUID, else by name) as their own xmeml documents, parsing
    the project once; `parts` is a list of (index, which, out_path); returns {index: byte count}."""
    from orchestrator import xmeml_emit
    doc = _load(path)
    sizes = {}
    for index, which, out_path in parts:
        xml = xmeml_emit.export_item(doc, which)
        # temp file + rename so a concurrent reader never sees a partial file
        tmp = out_path + ".tmp"
        Path(tmp).write_bytes(xml)
        os.replace(tmp, out_path)
        sizes[index] = len(xml)
    return sizes


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
                p["bytes"] = fut.result()[p["index"]]
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
    server_version = "Exhume/1.0"

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

        tmpdir = tempfile.mkdtemp(prefix="exhume-")
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
        work = []
        for i in indices:
            stem = _sanitize_component(job["sequences"][i]["raw_name"], f"sequence-{i + 1}")
            fname = f"{i + 1:02d} - {stem}.xml"
            out_path = str(out_dir / fname)
            seq = job["sequences"][i]
            work.append((i, seq.get("uuid") or seq["raw_name"], out_path))
            parts.append({"index": i, "name": fname, "path": out_path,
                          "future": None, "bytes": None})
        fut = _submit(_convert_worker, job["path"], work)   # one parse for all selected sequences
        for p in parts:
            p["future"] = fut
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
    ap = argparse.ArgumentParser(description="Exhume backend")
    ap.add_argument("--port", type=int, default=_default_port())
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    _pool = ProcessPoolExecutor(max_workers=_pool_size())
    atexit.register(_cleanup_tempdirs)
    threading.Thread(target=_reaper_loop, daemon=True).start()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.allowed_hosts = {f"{h}:{args.port}"
                            for h in ("127.0.0.1", "localhost", "[::1]", args.host)}
    print(f"Exhume backend on http://{args.host}:{args.port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        _pool.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
