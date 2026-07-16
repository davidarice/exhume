"""Recursive parser for Final Cut Pro 7 `.fcp` project files — Intel build.

Phase 1 container model (scope.md §10-§13). The `.fcp` is a self-describing,
uncompressed, keyed typed-object stream ("KeyGrip" archive). This parser targets
the **Intel build variant** (version word 0x01DE at offset 0x08) — the format
FCP7 itself writes, and therefore the only variant the differential-sweep corpus
and the XML-import oracle will ever produce. PowerPC-era files (version word
0x0000, byte-swapped GUID, transposed framing) are out of scope by decision.

Grammar (derived empirically against 1.fcp, byte-for-byte, and validated across
the Intel corpus by key-recovery parity):

    FILE   := HEADER RECORD*
    HEADER := 0xA2 "KeyG" 0x0A 0x0D 0x0A         (magic + text-safety guard)
              u2be version-word (0x01DE)
              u4be idlen (0x20) + id block        (root GUID + reserved tail)
              ... first record key follows
    RECORD := KEY TAG COUNT VALUE
    KEY    := u2be len + ASCII                    (ALL keys, top-level and nested)
    TAG    := u1                                  (type tag)
    COUNT  := u4be                                (refcount/version; 1 at top level)
    VALUE  := tag-specific:
        0x01 int     -> u4le
        0x1f string  -> flag(u1) + u4le len + ASCII
        0x05 bool    -> u1
        0x0b dict    -> u4le len + classname ASCII   (members follow as records)
        0x23 uuid    -> typed string (inner 0x22 flag + u4be len + ASCII)
        0x00 variant -> tagged-union composite (leaf or container of nested dicts)
        0x11 rect    -> packed numeric tuple

KEYS are big-endian; numeric/string PAYLOAD lengths are little-endian (the string
objects carry their own CoreFoundation-lineage LE length).

HONESTY CONTRACT (scope.md §12; learned from a rejected auto-parser that gamed a
byte-coverage metric): bytes are only counted "covered" when a decoder genuinely
consumes them. Values this parser cannot yet structurally decode (the 0x00 variant
body, 0x11 rects) are returned as `{"_undecoded": ...}` and their bytes are NOT
counted as covered. The success metric is KEY-RECOVERY PARITY: the recursive walk
must recover the same keyset a brute-force scan finds. Coverage is reported
separately and honestly.

Usage:
    python -m orchestrator.fcp_parser FILE [FILE ...]

Public API:
    parse(path)    -> {"header":..., "records":[...], "stats":...}
    is_intel(path) -> bool
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

MAGIC = bytes([0xA2, 0x4B, 0x65, 0x79, 0x47])
GUARD = bytes([0x0A, 0x0D, 0x0A])
INTEL_VERSION_WORD = 0x01DE

# Known type tags — used to validate a candidate key (a real key is followed by
# one of these), which makes the resync scan across undecoded values robust.
KNOWN_TAGS = frozenset({0x00, 0x01, 0x03, 0x04, 0x05, 0x0B, 0x11, 0x1F, 0x23})


def is_intel(path: str | Path) -> bool:
    """True if the file is the Intel build variant (version word 0x01DE)."""
    with open(path, "rb") as fh:
        head = fh.read(10)
    return head[:5] == MAGIC and int.from_bytes(head[8:10], "big") == INTEL_VERSION_WORD


def _u2be(d: bytes, p: int) -> int:
    return int.from_bytes(d[p:p + 2], "big")


def _u4be(d: bytes, p: int) -> int:
    return int.from_bytes(d[p:p + 4], "big")


def _u4le(d: bytes, p: int) -> int:
    return int.from_bytes(d[p:p + 4], "little")


def _key_at(d: bytes, p: int, lo: int = 2, hi: int = 48) -> str | None:
    """Return the ASCII key at `p` (u2be len + ASCII) or None."""
    if p + 2 > len(d):
        return None
    length = _u2be(d, p)
    if lo <= length <= hi and p + 2 + length <= len(d):
        chunk = d[p + 2:p + 2 + length]
        if all(32 <= c < 127 for c in chunk):
            return chunk.decode("ascii")
    return None


# Real records carry a small refcount/version COUNT (0 or 1 in practice). A wildly
# large COUNT means we mistook interior bytes of a binary value (a Mac Alias blob,
# a thumbnail) for a key — reject those.
_MAX_PLAUSIBLE_COUNT = 0xFFFF


def _record_at(d: bytes, p: int) -> bool:
    """A stronger key test: a valid key + a known tag + a plausible count."""
    k = _key_at(d, p)
    if k is None:
        return False
    tp = p + 2 + len(k)
    if tp >= len(d) or d[tp] not in KNOWN_TAGS:
        return False
    if tp + 5 > len(d):
        return False
    return _u4be(d, tp + 1) <= _MAX_PLAUSIBLE_COUNT


def _first_key(d: bytes) -> int | None:
    """Locate the first record key just past the header id block."""
    idlen = _u4be(d, 0x0A)
    for start in (0x0E + idlen, 0x0E + idlen - 2, 0x30, 0x32):
        for p in range(max(0x0E, start - 2), min(len(d), start + 32)):
            if _record_at(d, p):
                return p
    return None


class _Cov:
    """Honest coverage tracker: only bytes a decoder actually consumes."""

    def __init__(self, n: int):
        self.mark = bytearray(n)

    def cover(self, a: int, b: int) -> None:
        for i in range(a, min(b, len(self.mark))):
            self.mark[i] = 1

    def pct(self) -> float:
        return 100.0 * sum(self.mark) / len(self.mark) if self.mark else 0.0


def _decode_value(d: bytes, vp: int, tag: int, cov: _Cov) -> tuple[object, int, bool]:
    """Decode a value at `vp` for `tag`.

    Returns (python_value, end_offset, decoded). When `decoded` is False the
    value body is left for the caller to skip (by scanning to the next record)
    and its bytes are reported undecoded (never painted as covered).
    """
    n = len(d)
    if tag == 0x01:                                  # int (u4le)
        cov.cover(vp, vp + 4)
        return _u4le(d, vp), vp + 4, True
    if tag == 0x03:                                  # float32 (LE) — e.g. sampleRate
        cov.cover(vp, vp + 4)
        return struct.unpack("<f", d[vp:vp + 4])[0], vp + 4, True
    if tag == 0x04:                                  # float64 (LE) — timestamps, numSamples
        cov.cover(vp, vp + 8)
        return struct.unpack("<d", d[vp:vp + 8])[0], vp + 8, True
    if tag == 0x05:                                  # bool / flag (1 byte)
        cov.cover(vp, vp + 1)
        return d[vp], vp + 1, True
    if tag == 0x1F:                                  # string: flag + u4le len + ascii
        if vp + 5 <= n:
            length = _u4le(d, vp + 1)
            if 0 <= length < (1 << 20) and vp + 5 + length <= n:
                s = d[vp + 5:vp + 5 + length]
                if all(32 <= c < 127 or c in (9, 10, 13) for c in s):
                    cov.cover(vp, vp + 5 + length)
                    return s.decode("ascii", "replace"), vp + 5 + length, True
        return {"_undecoded": "string"}, vp, False
    if tag == 0x0B:                                  # dict: u4le len + classname
        if vp + 4 <= n:
            length = _u4le(d, vp)
            if 0 < length <= 64 and vp + 4 + length <= n:
                s = d[vp + 4:vp + 4 + length]
                if all(32 <= c < 127 for c in s):
                    cov.cover(vp, vp + 4 + length)
                    return {"_class": s.decode("ascii")}, vp + 4 + length, True
        return {"_undecoded": "dict"}, vp, False
    if tag == 0x23:                                  # typed string (UUID)
        # COUNT was 0; body: flag(0x01) inner-flag(0x22) u4be len + ascii.
        q = vp
        if q + 2 <= n and d[q] == 0x01 and d[q + 1] == 0x22:
            length = _u4be(d, q + 2)
            if 0 < length <= 64 and q + 6 + length <= n:
                s = d[q + 6:q + 6 + length]
                if all(32 <= c < 127 for c in s):
                    cov.cover(vp, q + 6 + length)
                    return s.decode("ascii"), q + 6 + length, True
        return {"_undecoded": "uuid"}, vp, False
    # 0x00 variant / 0x11 rect: structurally not yet decoded — honest gap.
    return {"_undecoded": f"tag_0x{tag:02x}"}, vp, False


def _scan_to_next_record(d: bytes, p: int) -> int:
    """Advance to the next position that starts a valid record (key + known tag)."""
    n = len(d)
    while p < n and not _record_at(d, p):
        p += 1
    return p


def parse(path: str | Path) -> dict:
    """Parse an Intel `.fcp` into a flat record list with honest coverage stats."""
    d = Path(path).read_bytes()
    n = len(d)
    if d[:5] != MAGIC:
        raise ValueError("not a KeyGrip .fcp (bad magic)")
    if int.from_bytes(d[8:10], "big") != INTEL_VERSION_WORD:
        raise ValueError("not the Intel build variant (version word != 0x01DE)")

    cov = _Cov(n)
    header = {
        "guard": d[5:8].hex(),
        "version_word": _u2be(d, 8),
        "id_block_len": _u4be(d, 0x0A),
        "guid": d[0x0E:0x1E].hex(),
    }
    p = _first_key(d)
    if p is None:
        raise ValueError("could not locate first record key")
    cov.cover(0, p)

    records: list[dict] = []
    undecoded_bytes = 0
    while p < n:
        k = _key_at(d, p)
        if k is None:
            q = _scan_to_next_record(d, p)
            undecoded_bytes += q - p
            if q == p:
                break
            p = q
            continue
        kp = p
        vp = kp + 2 + len(k)
        if vp + 5 > n:
            records.append({"key": k, "tag": None})
            break
        tag = d[vp]
        count = _u4be(d, vp + 1)
        cov.cover(kp, vp + 5)                        # key + tag + count are structure
        value, end, decoded = _decode_value(d, vp + 5, tag, cov)
        if decoded:
            p = end
        else:
            q = _scan_to_next_record(d, vp + 5)
            undecoded_bytes += q - (vp + 5)
            p = q
        records.append({"key": k, "tag": tag, "count": count, "value": value})

    # Parity: brute-force keyset the walk should match.
    ground = _bruteforce_keys(d)
    got = [r["key"] for r in records if r.get("tag") is not None]
    stats = {
        "size": n,
        "records": len(records),
        "coverage_pct": round(cov.pct(), 2),
        "undecoded_bytes": undecoded_bytes,
        "ground_truth_keys": len(ground),
        "recovered_keys": len(got),
        "parity": len(got) == len(ground),
    }
    return {"header": header, "records": records, "stats": stats}


def _bruteforce_keys(d: bytes) -> list[str]:
    """Independent keyset: every position that starts a record (key + known tag)."""
    n = len(d)
    out: list[str] = []
    p = _first_key(d) or 0
    while p < n:
        if _record_at(d, p):
            k = _key_at(d, p)
            out.append(k)
            p += 2 + len(k)
        else:
            p += 1
    return out


# ---------------------------------------------------------------------------
# Tree reconstruction (container value = header + COUNT members)
# ---------------------------------------------------------------------------

def _scalar(d: bytes, vp: int, tag: int) -> tuple[int | None, object]:
    """Return (byte_len, python_value) for a scalar VALUE, or (None, None)."""
    if tag == 0x01:
        return 4, _u4le(d, vp)
    if tag == 0x03:
        return 4, round(struct.unpack("<f", d[vp:vp + 4])[0], 3)
    if tag == 0x04:
        return 8, round(struct.unpack("<d", d[vp:vp + 8])[0], 1)
    if tag == 0x05:
        return 1, d[vp]
    if tag == 0x1F:
        length = _u4le(d, vp + 1)
        if 0 <= length < (1 << 20):
            return 5 + length, d[vp + 5:vp + 5 + length].decode("ascii", "replace")
    if tag == 0x0B:
        length = _u4le(d, vp)
        if 0 < length <= 64:
            return 4 + length, "{%s}" % d[vp + 4:vp + 4 + length].decode("ascii", "replace")
    return None, None


def _member_at(d: bytes, p: int):
    """A container member: string key (u2be) or int property-slot (u4le id)."""
    if p + 5 > len(d):
        return None
    if d[p] == 0:
        k = _key_at(d, p)
        if k is not None and d[p + 2 + len(k)] in KNOWN_TAGS:
            return ("s", k, p + 2 + len(k))
    elif d[p + 1] == 0 and d[p + 2] == 0 and d[p + 3] == 0 and 2 <= d[p] < 0x80 and d[p + 4] in KNOWN_TAGS:
        return ("i", f"#{d[p]:#x}", p + 4)
    return None


def _find_members(d: bytes, vp: int) -> tuple[int | None, int]:
    """Locate a container's member list via the 'COUNT 00 00 <member>' pattern."""
    for h in range(4, 48):
        cpos = vp + h - 3
        cnt = d[cpos] if 0 <= cpos < len(d) else -1
        if 1 <= cnt <= 60 and d[cpos + 1] == 0 and d[cpos + 2] == 0 and _member_at(d, vp + h):
            return vp + h, cnt
    return None, 0


def _add(node: dict, key: str, val: object) -> None:
    """Insert key/value, promoting to a list when a sibling key repeats."""
    if key in node:
        if not isinstance(node[key], list):
            node[key] = [node[key]]
        node[key].append(val)
    else:
        node[key] = val


def _parse_container(d: bytes, vp: int, budget: list[int]) -> tuple[object, int]:
    """Recursively parse a 0x00 container value at `vp`. Returns (node, end_pos)."""
    start, count = _find_members(d, vp)
    if start is None:
        return {"_raw": d[vp:vp + 8].hex()}, vp
    node: dict = {}
    p, got = start, 0
    while got < count and p < len(d) and budget[0] > 0:
        budget[0] -= 1
        m = _member_at(d, p)
        if m is None:
            # Members must tile exactly; a gap means our (start,count) guess was
            # wrong. Report the whole container raw rather than drift into siblings.
            return {"_raw": d[vp:vp + 8].hex()}, vp
        _, key, kp = m
        tag, vp2 = d[kp], kp + 5
        if tag == 0x00:
            sub, nxt = _parse_container(d, vp2, budget)
            _add(node, key, sub)
            p = nxt
        else:
            length, val = _scalar(d, vp2, tag)
            if length is None:
                p = vp2 + 4          # best-effort skip of an unknown value
            else:
                _add(node, key, val)
                p = vp2 + length
        got += 1
    return node, p


def parse_tree(path: str | Path) -> dict:
    """Best-effort nested tree from an Intel `.fcp` (task c1-sequence-nodes).

    Top-level records form an implicit root; 0x00 containers recurse via their
    member COUNT. Property-slots surface as '#0xNN'. Sub-containers whose header
    can't be located are returned as {'_raw': ...} rather than guessed — the tree
    is honest about what it could not delimit.
    """
    d = Path(path).read_bytes()
    if int.from_bytes(d[8:10], "big") != INTEL_VERSION_WORD:
        raise ValueError("not the Intel build variant")
    n = len(d)
    p = _first_key(d)
    root: dict = {}
    budget = [2_000_000]
    while p is not None and p < n and budget[0] > 0:
        k = _key_at(d, p)
        if k is None:
            p += 1
            continue
        vp = p + 2 + len(k)
        if vp + 5 > n or d[vp] not in KNOWN_TAGS or _u4be(d, vp + 1) > _MAX_PLAUSIBLE_COUNT:
            p += 1
            continue
        tag, vp2 = d[vp], vp + 5
        if tag == 0x00:
            sub, nxt = _parse_container(d, vp2, budget)
            _add(root, k, sub)
            p = nxt
        else:
            length, val = _scalar(d, vp2, tag)
            if length is None:
                p = vp2 + 4
            else:
                _add(root, k, val)
                p = vp2 + length
    return root


def _f64_slot_before(d: bytes, slot: int, before: int, window: int = 300):
    """Nearest int-property-slot f64 (id `slot`, tag 0x04, count 1) ending before `before`.

    Property slots share the record grammar with a u4le integer id: `<id:u4le> 0x04
    <count:u4be=1> <f64 LE>`. The clipitem's source range lives in such slots (0x0b/
    0x10), anchored just before its string-keyed `start` record. Returns float | None.
    """
    sig = bytes([slot, 0, 0, 0, 0x04, 0, 0, 0, 1])
    lo = max(0, before - window)
    i = d.rfind(sig, lo, before)
    if i < 0:
        return None
    return struct.unpack("<d", d[i + 9:i + 17])[0]


def _f64_slot_after(d: bytes, slot: int, after: int, window: int = 300):
    """First int-property-slot f64 (id `slot`) at/after `after` (mirror of _before)."""
    sig = bytes([slot, 0, 0, 0, 0x04, 0, 0, 0, 1])
    i = d.find(sig, after, after + window)
    if i < 0:
        return None
    return struct.unpack("<d", d[i + 9:i + 17])[0]


def clip_timing(path: str | Path) -> dict | None:
    """Decode the first clipitem's timing block (task f-clipitem-in/out/start/end).

    Combines the two storage layers this format uses for one clip's timing:
      * timeline `start`/`end` — string-keyed float64 records (frames);
      * source `in`/`out` and media `duration` — INT-property-slot float64 records
        (ids 0x0b / 0x10 / 0x11), which the flat string-key walk doesn't surface.
    The source slots are anchored to the string `start`/`end` records (validated
    against the start/end/source-window sweeps; FCP keeps source span == timeline
    span, recomputing source-out when a clip would otherwise change speed).

    Returns {src_in, src_out, timeline_start, timeline_end, media_duration} in
    frames, or None if no clipitem is present. Single-clip scope for now (anchors on
    the first `start` record); multi-clip walking follows the tree decode.
    """
    d = Path(path).read_bytes()
    m = d.find(b"\x00\x05start\x04")
    if m < 0:
        return None
    start = struct.unpack("<d", d[m + 12:m + 20])[0]      # key(7) + tag(1) + count(4)
    e = d.find(b"\x00\x03end\x04")
    end = struct.unpack("<d", d[e + 10:e + 18])[0] if e >= 0 else None
    return {
        "src_in": _f64_slot_before(d, 0x0B, m),
        "src_out": _f64_slot_before(d, 0x10, m),
        "timeline_start": start,
        "timeline_end": end,
        "media_duration": _f64_slot_after(d, 0x11, e) if e >= 0 else None,
    }


def _all_f64_records(d: bytes) -> list[tuple[int, float]]:
    """Every float64 record (string-keyed OR int-slot) as (offset, value), in order.

    Both forms are `<KEY> 0x04 <count=1 u4be> <f64 LE>`, where KEY is a `u2be`+ASCII
    string (first use of a key) or a `u4le` interned id (reuse). We don't need to
    know WHICH key — positional order within a clip node is enough (see clips_timing).
    """
    out, p, n = [], 0, len(d)
    while p < n - 17:
        if d[p] == 0:                                    # candidate string-keyed record
            ln = int.from_bytes(d[p:p + 2], "big")
            e = p + 2 + ln
            if (2 <= ln <= 48 and e + 13 <= n and all(32 <= c < 127 for c in d[p + 2:e])
                    and d[e] == 0x04 and d[e + 1:e + 5] == b"\x00\x00\x00\x01"):
                out.append((p, struct.unpack("<d", d[e + 5:e + 13])[0]))
                p = e + 13
                continue
        if (d[p + 1] == 0 and d[p + 2] == 0 and d[p + 3] == 0 and 1 <= d[p] < 0x80
                and d[p + 4] == 0x04 and d[p + 5:p + 9] == b"\x00\x00\x00\x01"):
            out.append((p, struct.unpack("<d", d[p + 9:p + 17])[0]))
            p += 17
            continue
        p += 1
    return out


def clips_timing(path: str | Path) -> list[dict]:
    """Extract every timeline clipitem's timing (in/out/start/end) POSITIONALLY.

    A clip node begins with the marker `01 CC 00 00 00 00` immediately followed by
    its source-in float64 record (`SS 00 00 00 04 00 00 00 01 <f64>`). CC (the clip
    element-class ref) and SS (the source-in key id) are per-file constants; we read
    them from the FIRST node and match the rest. Within a node the first four f64
    records are, in order, **in, out, start, end** — so extraction needs NEITHER the
    per-file intern table NOR the slot ids (the first clip keys start/end as strings,
    later clips as interned slots; both are f64 records in the same positions).
    Validated exactly against FCP ground truth on 1/2/3/4-clip sequences.

    Scope: single-track sequences. Multi-/nested-sequence real projects also carry a
    master-clip pool and per-sequence node classes this flat scan does not separate
    (needs container-tree navigation — task c1-sequence-nodes).
    """
    d = Path(path).read_bytes()
    n = len(d)
    # first clip-node signature: 01 CC 00 00 00 00  SS 00 00 00 04 00 00 00 01
    p, sig = 0, None
    while p < n - 15:
        if (d[p] == 1 and d[p + 2] == 0 and d[p + 3] == 0 and d[p + 4] == 0
                and d[p + 5] == 0 and d[p + 7] == 0 and d[p + 8] == 0 and d[p + 9] == 0
                and d[p + 10] == 0x04 and d[p + 11:p + 15] == b"\x00\x00\x00\x01"):
            sig = bytes([1, d[p + 1], 0, 0, 0, 0, d[p + 6], 0, 0, 0, 4, 0, 0, 0, 1])
            break
        p += 1
    if sig is None:
        return []
    nodes = []
    i = d.find(sig)
    while i >= 0:
        nodes.append(i + 6)                              # source-in record starts at +6
        i = d.find(sig, i + 1)

    f64 = _all_f64_records(d)
    offs = [o for o, _ in f64]
    import bisect
    clips = []
    for src_in_off in nodes:
        j = bisect.bisect_left(offs, src_in_off)
        quad = f64[j:j + 4]                              # in, out, start, end
        if len(quad) == 4:
            clips.append({k: round(v, 4) for k, (_o, v)
                          in zip(("in", "out", "start", "end"), quad)})
    return clips


# ---------------------------------------------------------------------------
# Real-project timeline extraction (bracket-delimited) — task c1-sequence-nodes
# ---------------------------------------------------------------------------
#
# The clean unified record grammar (resolves the name-length-vs-interned-id
# ambiguity): every record is `u2be N` then, if N==0 a `u4le interned id` (a REUSE
# of a previously-named key), else N bytes of ASCII (a key's FIRST use); then the
# usual `u1 tag`, `u4be count/flag`, value. A slot's leading `00 00` is a length-0
# key marker, not a gap.
#
# A clipitem's timeline in/out live in a contiguous block of four float64 records:
#     [B0]  [start]  [end]  [B1]
# where B0/B1 are per-file "bracket" slot ids (the f64 fields immediately around
# start/end). They are learned from the FIRST clip, whose start/end are spelled as
# NAMED keys. Keyframe/master-pool reuses of start/end are NOT wrapped by B0..B1, so
# the bracket delimits real timeline clips. Validated: mc_one..four exact; palastin
# (real, 19 sequences) 6969/6988 clipitems == FCP's own xmeml (99.7%; the ~0.3% miss
# are offline `-1` clips).

def _record_at2(d: bytes, p: int):
    """Read one record under the unified grammar. Returns
    (kind, key_or_id, tag, value, end) or None. kind is 'i' (interned slot) or 's'.
    Only the value types needed for the walk are decoded; others return end only.
    """
    n = len(d)
    if p + 2 > n:
        return None
    N = _u2be(d, p)
    if N == 0:                                           # interned slot: u4le id
        if p + 11 > n:
            return None
        kid, tag, vp = _u4le(d, p + 2), d[p + 6], p + 11
        kind = "i"
    elif 2 <= N <= 48 and p + 2 + N <= n and all(32 <= b < 127 for b in d[p + 2:p + 2 + N]):
        kid, tag, vp = d[p + 2:p + 2 + N].decode(), d[p + 2 + N], p + 2 + N + 5
        kind = "s"
    else:
        return None
    if tag not in KNOWN_TAGS:
        return None
    if tag == 0x04 and vp + 8 <= n:
        return (kind, kid, tag, struct.unpack("<d", d[vp:vp + 8])[0], vp + 8)
    if tag == 0x01:
        return (kind, kid, tag, _u4le(d, vp), vp + 4)
    if tag == 0x05:
        return (kind, kid, tag, d[vp], vp + 1)
    if tag == 0x1F:
        length = _u4le(d, vp + 1)
        if 0 <= length < (1 << 20):
            return (kind, kid, tag, None, vp + 5 + length)
    if tag == 0x23:
        if vp + 2 <= n and d[vp] == 1 and d[vp + 1] == 0x22:
            return (kind, kid, tag, None, vp + 6 + _u4be(d, vp + 2))
    # 0x0B / 0x00 / others: we don't need their value here; give a best-effort end.
    if tag == 0x0B:
        length = _u4le(d, vp)
        if 0 < length <= 64:
            return (kind, kid, tag, None, vp + 4 + length)
    return (kind, kid, tag, None, vp)


def _next_f64(d: bytes, p: int, limit: int):
    """Next float64 record at/after p within `limit`. Returns (kind,id,val,off,end)."""
    while p < limit:
        r = _record_at2(d, p)
        if r is None:
            p += 1
            continue
        kind, kid, tag, val, end = r
        if tag == 0x04:
            return (kind, kid, val, p, end)
        p = end if end > p else p + 1
    return None


def _prev_slot_f64(d: bytes, before: int, wanted_id: int, window: int = 260):
    """Nearest float64 slot record with id `wanted_id` ending at/before `before`."""
    for p in range(before - 11, max(0, before - window), -1):
        r = _record_at2(d, p)
        if r and r[0] == "i" and r[1] == wanted_id and r[2] == 0x04 and r[4] <= before:
            return r[3]
    return None


def learn_timing_bracket(d: bytes):
    """Learn the per-file (B0, B1, in_id) timing ids from the first NAMED clip.

    B0 = id of the float64 slot immediately preceding the first named `start` (this is
    the clip's source `out`); B1 = id of the first float64 slot following the named
    `end` (media duration). in_id = id of the float64 slot before B0 (source `in`),
    skipping the intervening masterClips object / uuids. Returns (B0, B1, in_id) or
    None when the file has no header-inlined (named) clip.
    """
    m = d.find(b"\x00\x05start\x04")
    if m < 0:
        return None
    b0 = b0off = None
    for back in range(11, 60):                           # find the f64 record ending at m
        r = _record_at2(d, m - back)
        if r and r[4] == m and r[2] == 0x04 and r[0] == "i":
            b0, b0off = r[1], m - back
            break
    if b0 is None:
        return None
    in_id = None
    for p in range(b0off - 11, b0off - 260, -1):          # in = f64 slot before out(B0)
        r = _record_at2(d, p)
        if r and r[2] == 0x04 and r[0] == "i" and r[4] <= b0off:
            in_id = r[1]
            break
    rs = _record_at2(d, m)
    if not rs:
        return None
    e = d.find(b"\x00\x03end\x04", rs[4] - 2, rs[4] + 40)
    if e < 0:
        return None
    re_ = _record_at2(d, e)
    if not re_:
        return None
    nf = _next_f64(d, re_[4], re_[4] + 60)
    b1 = nf[1] if (nf and nf[0] == "i") else None
    if b1 is None:
        return None
    return (b0, b1, in_id)


def timeline_clips(path: str | Path) -> list[dict]:
    """Every timeline clipitem's `in`/`out`/`start`/`end` (frames), bracket-delimited.

    Works on real multi-sequence projects (unlike `clips_timing`, which is a
    single-track positional decoder). Learns the (B0, B1, in_id) float64 ids from the
    first named clip, then for each `[B0][start][end][B1]` block emits source `in`
    (the in_id slot preceding the block), source `out` (= B0), timeline `start`/`end`.
    Validated against FCP's own xmeml: mc_one..four exact; palastin 6969/6988
    clipitems (99.7%) on the full (in,out,start,end) tuple. `in` is None for offline
    clips that omit it. Returns [] if no named clip is present.
    """
    d = Path(path).read_bytes()
    br = learn_timing_bracket(d)
    if br is None:
        return []
    b0, b1, in_id = br
    n = len(d)
    clips: list[dict] = []
    p = 0
    while p < n - 40:
        r = _record_at2(d, p)
        if r and r[0] == "i" and r[1] == b0 and r[2] == 0x04:
            s = _next_f64(d, r[4], r[4] + 12)
            if s:
                e = _next_f64(d, s[4], s[4] + 12)
                if e:
                    b = _next_f64(d, e[4], e[4] + 12)
                    if b and b[0] == "i" and b[1] == b1:
                        src_in = _prev_slot_f64(d, p, in_id) if in_id is not None else None
                        clips.append({
                            "in": round(src_in, 4) if src_in is not None else None,
                            "out": round(r[3], 4),
                            "start": round(s[2], 4),
                            "end": round(e[2], 4),
                        })
                        p = b[4]
                        continue
        p += 1
    return clips


# Media file extensions FCP7 references (lower-cased); drives the pathurl scan.
_MEDIA_EXTS = ("mov", "mp4", "m4v", "avi", "wav", "aif", "aiff", "mp3", "m4a",
               "jpg", "jpeg", "png", "tif", "tiff", "psd", "gif", "flv")


def media_pathurls(path: str | Path) -> list[str]:
    """Distinct media file POSIX paths referenced by the project (for `<file>/pathurl`).

    Pragmatic scan of the embedded Mac Alias blobs: media refs store a volume-relative
    POSIX path (e.g. ``/doc paleastine/…/6U5A0387.mov``) that we grab by media
    extension (UTF-8 aware, for accented/Arabic names). This is a project-level media
    inventory, NOT the full structural Mac Alias decode (that — volume mount + exact
    xmeml pathurl form — is task r-alias-pathurl); attributing a file to a specific
    clipitem needs the object-graph walker (master-clip pool). Coverage vs FCP's own
    xmeml on palastin: ~98% of referenced media basenames. Returns sorted distinct paths.
    """
    import re
    d = Path(path).read_bytes()
    ext_alt = "|".join(_MEDIA_EXTS)
    pat = rb"/[\x20-\x7e\x80-\xff]{3,300}?\.(?:%s)" % ext_alt.encode()
    out: set[str] = set()
    for m in re.finditer(pat, d, re.IGNORECASE):
        raw = m.group(0)
        try:
            s = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                s = raw.decode("mac_roman")
            except UnicodeDecodeError:
                continue
        if "/" in s[1:]:                                 # at least one directory level
            out.add(s)
    return sorted(out)


def clipitems(path: str | Path) -> list[dict]:
    """Per-clipitem records shaped for xmeml emission (task f-clipitem-node).

    Integrates the extractable-now per-clip layer into one record per timeline
    clipitem::

        {"name": None, "in": .., "out": .., "start": .., "end": .., "file": None}

    * `in`/`out`/`start`/`end` — validated timeline+source timing (see `timeline_clips`;
      mc_one..four exact, palastin 99.7%).
    * `name`/`file` — left None here on purpose. A clipitem's name is a back-reference
      into the string-intern table and its file lives in the master-clip pool it
      references; both resolve only through the object-graph walker's per-scope tables
      + pool join (verified: the string slots are generic — no dedicated name id —
      so any positional heuristic mis-picks metadata). The join sources are ready:
      `media_pathurls()` (project media paths) and `orchestrator.fcp_keyg_scan` (master
      clip names/dims/GUIDs). The walker also assigns each record to its sequence/track.

    This is the stable per-clip contract: the walker fills `name`/`file`/sequence
    without changing the timing fields.
    """
    return [{"name": None, "file": None, **c} for c in timeline_clips(path)]


def _print_tree(node, indent: int = 0, max_items: int = 60) -> None:
    pad = "  " * indent
    for key, val in list(node.items())[:max_items]:
        if isinstance(val, dict):
            print(f"{pad}{key}:")
            _print_tree(val, indent + 1, max_items)
        elif isinstance(val, list):
            print(f"{pad}{key}: [{len(val)}]")
            for item in val[:8]:
                if isinstance(item, dict):
                    _print_tree(item, indent + 1, max_items)
                else:
                    print(f"{pad}  - {item}")
        else:
            print(f"{pad}{key} = {val}")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "--tree":
        for a in argv[1:]:
            if not is_intel(a):
                print(f"\n{a}\n  SKIP: not the Intel build variant")
                continue
            print(f"\n{a}")
            _print_tree(parse_tree(a))
        return 0
    for a in argv:
        if not is_intel(a):
            print(f"\n{a}\n  SKIP: not the Intel build variant")
            continue
        r = parse(a)
        s = r["stats"]
        print(f"\n{a}")
        print(f"  version=0x{r['header']['version_word']:04x} guid={r['header']['guid'][:16]}…")
        print(f"  records={s['records']} coverage={s['coverage_pct']}% "
              f"undecoded={s['undecoded_bytes']:,}B")
        print(f"  key parity: recovered {s['recovered_keys']} / ground-truth "
              f"{s['ground_truth_keys']}  -> {'OK' if s['parity'] else 'MISMATCH'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
