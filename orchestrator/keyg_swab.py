#!/usr/bin/env python3
"""Big-endian (PowerPC-era) KeyGrip .fcp -> little-endian transcoder.

A 2008 PowerPC FCP project (MUSEO corpus) carries the SAME object grammar as
the gated Intel corpora with every multi-byte scalar stored big-endian and the
header byte-order flag at 0x08 set to 00 (Intel: 01).  This module walks the
BE file with a big-endian fork of keyg_walker2's TOKENIZER LAYER ONLY, records
the (offset, width) of every multi-byte scalar it recognizes, then reverses
each recorded span in place.  Byte swaps preserve widths, so every offset is
unchanged and the output is a well-formed little-endian KeyGrip file that the
existing, untouched pipeline (keyg_walker2 / keyg_grouper / export) parses.

Design (recon: scratchpad ppc/swap_spec.md + ppc/reconB/museo_quirks.md):

  * MIRROR CASCADE — a port of keyg_walker2.tokenize()/_value() with every
    branch predicate re-expressed for BE byte order (what the LE walker reads
    as `[tag u8][pad3]` is really a u32 tag word: the tag byte sits at word+3
    in BE files).  Each fired branch marks its scalar spans for swapping, so
    the LE walker sees exactly the byte shape the mirror predicate assumed.

  * LE-RAW FALLBACK — when NO mirror branch recognizes the bytes at p (junk
    pockets, version-0x16-only constructs the LE walker also would not know),
    the region is left byte-identical and ONE step of the untouched LE
    walker's decision cascade is evaluated on the raw bytes.  Because those
    bytes are identical in the swabbed output, the LE walker's behavior there
    IS this cascade: the involution holds by construction on inert pockets.
    (keyg_walker2 is imported read-only for this: delegating to the gated
    implementation is the strongest possible mirror of its decision tree —
    a hand copy could silently drift.)

  * GUID payloads are FIELD-swapped (u32,u16,u16 + 8 invariant bytes): the
    root/class GUIDs must byte-match the Intel constants keyg_walker2
    compares against (swap_spec section 4).  Alias blobs, waveform caches,
    thumbnails, DATA07 payloads, ASCII/UTF-8 string payloads stay untouched
    (natively big-endian / endian-invariant in BOTH dialects).

THE INVOLUTION INVARIANT (the campaign's oracle — a BE file has no FCP XML
export to diff against): tokenize_scoped(original, BE fork) must equal
keyg_walker2.tokenize_scoped(swab(original)) event-for-event (kind, offset,
decoded value).  See scratchpad ppc/invariant_check.py.

CLI:  python3 -m orchestrator.keyg_swab src.fcp dst.fcp
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from . import keyg_walker2 as _LE   # read-only: constants + LE-raw fallback

_u32 = lambda d, o: struct.unpack_from(">I", d, o)[0]
_u16be = lambda d, o: struct.unpack_from(">H", d, o)[0]

MAGIC = b"\xa2KeyG\x0a\x0d\x0a"

# grammar constants — imported so the fork stays in lockstep with the walker
SLOT_MAX_ID = _LE.SLOT_MAX_ID
SLOT_MAX_COUNT = _LE.SLOT_MAX_COUNT
SLOT_TAGS = _LE.SLOT_TAGS
FIXED_TAGS = _LE.FIXED_TAGS
DICT_MAX_COUNT = _LE.DICT_MAX_COUNT
ARRAY_ELEM_SIZES = _LE.ARRAY_ELEM_SIZES
VAL32_TAGS = _LE.VAL32_TAGS
FILESPEC_MAX_LEN = _LE.FILESPEC_MAX_LEN
BLOB_UNIT = _LE.BLOB_UNIT
MASTER_CLS = _LE.MASTER_CLS

# BE record magics: [u8 01][u32be count][u32be tag]
MAG_GUID1 = b"\x01\x00\x00\x00\x01\x00\x00\x00\x18"
MAG_G10_1 = b"\x01\x00\x00\x00\x01\x00\x00\x00\x10"
MAG_OTAG = b"\x01\x00\x00\x00\x01\x00\x00\x00\x00"
MAG_GUID2 = b"\x01\x00\x00\x00\x02\x00\x00\x00\x18"
MAG_G10_2 = b"\x01\x00\x00\x00\x02\x00\x00\x00\x10"
MAG_T1A = b"\x01\x00\x00\x00\x01\x00\x00\x00\x1a"    # v0x16 GUID family, kind 0x1a


def _gswap(g: bytes) -> bytes:
    """GUID field swap: u32 data1 + u16 data2 + u16 data3 + 8 invariant bytes."""
    return g[3::-1] + g[5:3:-1] + g[7:5:-1] + g[8:]


class Ctx:
    """Walk bookkeeping: swap spans, raw-mode arrays, inert-pocket ledger."""
    __slots__ = ("spans", "raw_arrays", "pockets", "record", "clean_from", "pokes")

    def __init__(self, record: bool = True):
        self.spans: dict[int, int] = {}      # offset -> width
        self.raw_arrays: set[int] = set()    # ARRAY events framed by the LE fallback
        self.pockets: list[tuple[int, int, str]] = []
        self.pokes: dict[int, bytes] = {}    # offset -> literal LE bytes (dialect fixups)
        self.record = record
        self.clean_from = -1                 # proven-clean arrival: skip prev_raw

    def mark(self, off: int, w: int) -> None:
        if not self.record:
            return
        prev = self.spans.get(off)
        if prev is not None and prev != w:
            raise AssertionError(f"span width conflict @0x{off:x}: {prev} vs {w}")
        self.spans[off] = w

    def poke(self, off: int, val: bytes) -> None:
        """Overwrite a word with fixed LE bytes (applied after the span
        reversals).  Used where a PPC-dialect constant differs from the
        Intel-canonical byte a plain byte-order swap would produce, so the
        swabbed stream is canonical and the LE walker needs no dialect branch."""
        if not self.record:
            return
        prev = self.pokes.get(off)
        if prev is not None and prev != val:
            raise AssertionError(f"poke conflict @0x{off:x}: {prev!r} vs {val!r}")
        self.pokes[off] = val

    def mark_all(self, marks) -> None:
        for off, w in marks:
            self.mark(off, w)

    def mark_guid(self, off: int) -> None:
        self.mark(off, 4); self.mark(off + 4, 2); self.mark(off + 6, 2)


def _mark_fixed(t: int, off: int, marks: list) -> None:
    """Interior spans of one FIXED-tag payload unit (swap_spec section 2.13)."""
    if t in (0x02, 0x12):
        marks.append((off, 4))                       # [u32 v][u8]
    elif t in (0x0e, 0x0f):
        marks.append((off, 4)); marks.append((off + 4, 4))
    elif t == 0x11:
        for k in range(4):
            marks.append((off + 4 * k, 4))
    # 0x08: single u8, nothing to swap


# --------------------------------------------------------------------------
# BE mirrors of the walker's helpers (span-transactional: local `marks` lists
# are committed by the caller only when the construct actually fires).
# --------------------------------------------------------------------------

def try_dict_prelude(d, p, hi, ev, ctx, strict=False):
    """[u32be 0][u8 Y 0|1][u32be C]; mirrors keyg_walker2.try_dict_prelude."""
    if p + 9 > hi or _u32(d, p) != 0 or d[p + 4] > 1:
        return None
    C = _u32(d, p + 5)
    if C > DICT_MAX_COUNT or (strict and C == 0):
        return None
    if C == 0:
        ev.append((p, "DICT", 0))
        ctx.mark(p, 4); ctx.mark(p + 5, 4)
        return p + 9
    b = d[p + 9]
    if b == 0:                          # numeric entry [00][u32 key][tagword]
        if strict:
            key = _u32(d, p + 10)
            if not (0 < key <= SLOT_MAX_ID):
                return None
            t = d[p + 17]               # BE tag byte at word+3 (LE reads d[p+14])
            if t not in SLOT_TAGS and t not in FIXED_TAGS and t not in (0x0c, 0x16, 0x06):
                return None
            if d[p + 14:p + 17] != b"\x00\x00\x00":
                return None
    elif 1 <= b <= 80:                  # named (DEF) entry [u8 len][ascii]
        # cap 80 (vs the LE walker's 40) so the BE walker recognizes a count-N
        # source-media P2/QT metadata dict whose first entry is a long DEF key
        # (reverse-DNS 'com.panasonic...device.manufacturer' = 68 chars). BE-only:
        # here it just lets the prelude's [0][Y][C] words get word-swapped, so the
        # swab emits correct LE bytes; the untouched LE walker (cap 40) then reads
        # the same region via its zeros+PTOK(C)+DEF path (RAW-free, as the native-LE
        # managed corpus proves), the BE/LE event split being a bounded resync
        # pocket. Without this the BE walker mis-frames the prelude words and the
        # swab corrupts the LE file (the P2 misframe that collapsed 'Final mit Logo').
        if not all(0x20 <= c < 0x7f for c in d[p + 10:p + 10 + b]):
            return None
    else:
        return None
    ev.append((p, "DICT", C))
    ctx.mark(p, 4); ctx.mark(p + 5, 4)
    return p + 9


def plausible_record_start(d, p, hi) -> bool:
    """BE mirror of the LE lookahead heuristic (post-swab shapes)."""
    for _ in range(12):
        if p >= hi:
            return True
        b = d[p]
        if b == 0:
            # BE keyed value [00][u32be kid][u32be tagword]
            if (p + 9 <= hi and 0 < _u32(d, p + 1) <= SLOT_MAX_ID
                    and d[p + 5:p + 8] == b"\x00\x00\x00" and d[p + 8] < 0x30):
                return True
            # BE array/prelude head [u32be 1|2][u8 f] surfaces as b==1|2 post-swab
            if p + 13 <= hi and _u32(d, p) in (1, 2) and d[p + 4] in (0, 1):
                return True
            p += 1
            continue
        if b == 1:
            return True
        if 2 <= b <= 40 and p + 1 + b <= hi and all(0x20 <= c < 0x7f for c in d[p + 1:p + 1 + b]):
            return True
        return False
    return False


def try_filespec(d, p, hi):
    """[01][u32be nf=5][u32be L][Mac Alias blob: BE-native, invariant] ...
    Probe only — the FILESPEC branch marks the nf/length words when it fires."""
    if d[p] != 1 or p + 5 > hi:
        return None
    nf = _u32(d, p + 1)
    if nf != 5 or p + 13 > hi:
        return None
    L = _u32(d, p + 5)
    # alias sniff: the blob-internal u16be size @+4 equals L in BOTH dialects
    if L > 0 and not (0x40 <= L < 0x8000 and p + 9 + L <= hi
                      and d[p + 9:p + 13] == b"\x00\x00\x00\x00" and _u16be(d, p + 13) == L):
        return None
    q = p + 5
    spans = []
    for _ in range(nf):
        if q + 4 > hi:
            return None
        ln = _u32(d, q)
        if ln > FILESPEC_MAX_LEN or q + 4 + ln > hi:
            return None
        spans.append((q + 4, ln))
        q += 4 + ln
    if not any(ln for _, ln in spans):
        return None
    if _u32(d, p + 5) == 0:
        vol = spans[2]      # missing-file variant: demand printable volume name
        if not (0 < vol[1] < 0x100 and all(0x20 <= c < 0x7f for c in d[vol[0]:vol[0] + vol[1]])):
            return None
    if not plausible_record_start(d, q, hi):
        return None
    return q, nf, spans


def _flagged(d, p, hi, marks, uuid=False):
    """One flagged payload: [00][u32be ref] | [01][u32be len][bytes]."""
    if p >= hi:
        return None
    fl = d[p]
    if fl == 0:
        marks.append((p + 1, 4))
        return p + 5, ("REF", _u32(d, p + 1))
    if fl != 1:
        return None
    if uuid:
        if d[p + 1:p + 5] != b"\x00\x00\x00\x22":
            return None
        ln = _u32(d, p + 5)
        if ln > 0x100:
            return None
        marks.append((p + 1, 4)); marks.append((p + 5, 4))
        return p + 9 + ln, ("UUID", d[p + 9:p + 9 + ln].decode("ascii", "replace"))
    ln = _u32(d, p + 1)
    if ln > 0x400000 or p + 5 + ln > hi:
        return None
    marks.append((p + 1, 4))
    return p + 5 + ln, ("STRINL", d[p + 5:p + 5 + ln].decode("utf-8", "replace"))


def try_named_array(d, p, hi, C, marks):
    """C x [01][u32be n][ascii class name][opaque body].  Element-header length
    words swap; body interiors are opaque learned-length pockets (kept raw)."""
    if not (1 <= C <= SLOT_MAX_COUNT):
        return None

    def elem_hdr(q):
        if q >= hi or d[q] != 1:
            return None
        n = _u32(d, q + 1)
        if not (0 < n <= 0x40) or not all(0x20 <= c < 0x7f for c in d[q + 5:q + 5 + n]):
            return None
        return q + 5 + n

    q = p
    blens = []
    hdr_marks = []
    for k in range(C):
        e = elem_hdr(q)
        if e is None:
            return None
        hdr_marks.append((q + 1, 4))
        if k == C - 1:
            if not blens:
                return None
            q = e + max(set(blens), key=blens.count)
            break
        r = None
        for cand in range(e, min(e + 0x200, hi)):
            if elem_hdr(cand) is not None:
                r = cand
                break
        if r is None:
            return None
        blens.append(r - e)
        q = r
    if q > hi:
        return None
    marks.extend(hdr_marks)
    return q


_TRAILER11 = b"\x01\x01" + b"\x00" * 9


def try_guidref_list(d, p, hi, ev, ctx):
    """Count-C GUID-ref list continuation (see the _mirror_step call site).
    p sits at the first 11-byte trailer, 15 bytes past the head.  Returns the
    offset after the final trailer's OTAGOBJ read, or None (leave to the
    status-quo fallback).  All refs are validated 0 < ref < 0x10000 so the
    post-swab bytes cannot satisfy the LE walker's NKEY gates."""
    h = p - 15
    C = _u32(d, h + 1)
    if not (2 <= C <= 64) or _u32(d, h + 5) != 0x18:
        return None
    if d[h + 9] != 1 or d[h + 10] != 0 or not (0 < _u32(d, h + 11) < 0x10000):
        return None
    ft = p + 22 * (C - 1)
    if ft + 13 > hi:
        return None
    marks = []
    out = []
    for k in range(C - 1):
        t = p + 22 * k
        e = t + 12
        if d[t:t + 12] != _TRAILER11 + b"\x00":
            return None
        if d[e:e + 4] != b"\x00\x00\x00\x18" or d[e + 4] != 1 or d[e + 5] != 0:
            return None
        ref = _u32(d, e + 6)
        if not (0 < ref < 0x10000):
            return None
        # LE walk over the swapped bytes: OTAGREF eats trailer+pad+tagword[:2]
        # (u32le at t+10 = 00 00 18 00), zeros skip, then BAREREF(ref)
        out.append((t, "OTAGREF", 0x00180000))
        out.append((e + 4, "BAREREF", ref))
        marks.append((e, 4)); marks.append((e + 6, 4))
    if d[ft:ft + 11] != _TRAILER11 or d[ft + 11] != 0 or d[ft + 12] != 0:
        return None
    out.append((ft, "OTAGOBJ"))
    ev.extend(out)
    ctx.mark_all(marks)
    return ft + 9


def try_bare_guidref_list(d, p, hi, ev, ctx):
    """0x16-only count-C GUID-ref list, BARE flavor (no 01-markers, no
    trailers): [01][u32be C][u32be 0x18][00][u32be ref] with entries 2..C
    each re-prefixed [u32be 0x18][00][u32be ref] at stride 9 (61 runs live,
    C 2..16, refs = GUID-table ids).  There is no LE twin for the interior,
    so the transform targets the LE walker's inert tokens instead: with the
    tagword swapped and the ref's top three bytes reversed ([00 00 hi] ->
    [hi 00 00]) each entry reads GUIDORPH(hi) + RAW(lo) — glue only, where
    the old framing read NKEY(ref)+BLOBREF pairs, i.e. bogus KEYED entries
    that consumed the enclosing clip-dict budgets (the other half of the
    MUSEO_Souvenirs audm/track loss).  Entries are processed greedily; the
    last processed entry's lo byte is left to the ordinary cascade unless a
    safe form-1 NKEY tail is proven (all 61 live runs), in which case its
    RAW is emitted and the walk resumes at the NKEY marker with the
    prev_raw hijack-guard waived (ctx.clean_from) so the real key record —
    typically the keyframe-dict head the old framing lost — parses.
    Constraints 2 <= hi,lo <= 0xff keep every interior token deterministic
    (lo==0 flips the walker's CNTW gate, lo==1/hi==1 its PTOK/BAREREF
    gates) — offending runs keep the status-quo junk framing
    (correct-or-absent)."""
    C = _u32(d, p + 1)
    if not (2 <= C <= 64) or _u32(d, p + 5) != 0x18 or d[p + 9] != 0:
        return None
    good = []
    for k in range(C):
        base = p + 5 + 9 * k
        if base + 9 > hi or d[base:base + 4] != b"\x00\x00\x00\x18" \
                or d[base + 4] != 0:
            break
        ref = _u32(d, base + 5)
        if ref > 0xffff or (ref >> 8) < 2 or (ref & 0xff) < 2:
            break
        good.append((base, ref))
    if not good:
        return None
    ev.append((p, "PTOK", C))
    ctx.mark(p + 1, 4)
    for i, (base, ref) in enumerate(good):
        ev.append((base, "GUIDORPH", (ref >> 8) & 0xff))
        ctx.mark(base, 4)
        ctx.mark(base + 5, 3)          # [00 00 hi] -> [hi 00 00]
        if i + 1 < len(good):
            ev.append((base + 8, "RAW", ref & 0xff))
    end = good[-1][0] + 8              # the final entry's lo byte
    q = end + 1
    if len(good) == C and q + 8 <= hi and d[q] == 0:
        # safe tail: form-1 NKEY whose post-swab kid bytes cannot satisfy
        # the LE walker's key/CNTW gates at the lo byte -> RAW(lo) proven
        kid = _u32(d, q + 1)
        if (0 < kid <= SLOT_MAX_ID and kid & 0xff
                and d[q + 5:q + 8] == b"\x00\x00\x00"
                and ((kid >> 8) & 0xff or (kid & 0xff) > 0x0f)):
            ev.append((end, "RAW", good[-1][1] & 0xff))
            ctx.clean_from = q
            return q
    return end


def try_be_refarray_v14(d, p, hi, ev, ctx):
    """v0x14 BE PTOK-headed ref-array (effect keyframe/point ref-list) — the BE
    mirror of keyg_walker2.refarray_end.  BE layout at the [01] PTOK head:
        [01][u32be C][00 00 00 18 CNTW][C units]
    unit = [00][u32be ref][00 00 00 18], the LAST unit's trailing tag dropped.
    The refs are valid slot ids (<= SLOT_MAX_ID) but > 0xffff, so the 0x16
    try_bare_guidref_list (ref <= 0xffff -> GUIDORPH) never claims them, and
    unhandled the LE walker reads each [ref][00 00 00 18] pair as a phantom
    NKEY(bigid)+BLOBREF that drains the enclosing clip DICT — severing video
    track 2 + the audm (Rat King Titles clip: PTOK(10) at 0x104f0b3 et al.).
    Reversing the count word, the CNTW tag, and each unit's ref+tag words
    yields the exact LE shape refarray_end consumes as one REFARRAY glue token
    (0 members).  Version-gated to 0x14; the all-units-validate gate mirrors
    refarray_end's own and makes an accidental hit near-impossible."""
    if not (d[0x2e] == 1 and _u32(d, 0x2f) == 0x14):
        return None
    C = _u32(d, p + 1)
    if not (2 <= C <= SLOT_MAX_COUNT) or _u32(d, p + 5) != 0x18:
        return None
    base = p + 9
    marks = []
    cnt = 0
    while cnt < C:
        if base + 5 > hi or d[base] != 0:
            break
        ref = _u32(d, base + 1)
        if not (0 < ref <= SLOT_MAX_ID):
            break
        marks.append((base + 1, 4))                    # ref BE -> LE
        base += 5
        if d[base:base + 4] == b"\x00\x00\x00\x18":     # inter-unit tag (last omits it)
            marks.append((base, 4))                    # 00 00 00 18 -> 18 00 00 00
            base += 4
        cnt += 1
    if cnt != C:
        return None
    ev.append((p, "PTOK", C))
    ev.append((p + 5, "REFARRAY", C))
    ctx.mark(p + 1, 4)                                  # count word BE -> LE
    ctx.mark(p + 5, 4)                                  # CNTW 00 00 00 18 -> 18 00 00 00
    ctx.mark_all(marks)
    return base


_SLOT_VALIDATE = True


def _slot_end_ok(d, q, hi) -> bool:
    """Mirror of the LE killer validation: bounded BE re-tokenize after a slot."""
    global _SLOT_VALIDATE
    if not plausible_record_start(d, q, hi):
        return False
    if q >= hi:
        return True
    _SLOT_VALIDATE = False
    try:
        sub = tokenize(d, q, min(q + 96, hi), Ctx(record=False))
    finally:
        _SLOT_VALIDATE = True
    for e in sub:
        if e[0] - q > 32:
            break
        if e[1] == "RAW":
            return False
    return True


def _slot_payload(d, q, hi, t, n, out, marks):
    """Shared SLOT/VAL32 payload walk.  Returns end offset or None."""
    if t in (0x01, 0x03):
        for k in range(n):
            marks.append((q + 4 * k, 4))
        return q + 4 * n
    if t == 0x04:
        for k in range(n):
            marks.append((q + 8 * k, 8))
        return q + 8 * n
    if t == 0x05:
        return q + n
    for _ in range(n):
        r = _flagged(d, q, hi, marks, uuid=(t == 0x23))
        if r is None:
            return None
        q, e = r
        out.append((q, ("S" if out and out[0][1] == "SLOT" else "V") + e[0], e[1]))
    return q


def try_slot(d, p, hi, ev, ctx):
    """[01][u32be sid][u32be tagword][u32be count][payload]."""
    if d[p] != 1 or p + 14 > hi:
        return None
    sid = _u32(d, p + 1)
    if sid > SLOT_MAX_ID:
        return None
    if d[p + 5:p + 8] != b"\x00\x00\x00":
        return None
    t = d[p + 8]
    if t not in SLOT_TAGS:
        return None
    marks = [(p + 1, 4), (p + 5, 4)]
    n = _u32(d, p + 9)
    if n > SLOT_MAX_COUNT:
        # count-less GUID slot (any sid): [01 marker][01|00] + GUID | ref
        if t == 0x18 and d[p + 9] == 1:
            if d[p + 10] == 1:
                g = d[p + 11:p + 27]
                ctx.mark_all(marks); ctx.mark_guid(p + 11)
                ctx.mark(p + 27 + 2, 4); ctx.mark(p + 27 + 7, 4)   # 11B trailer
                ev.append((p, "SLOTGUIDINL", sid, _gswap(g)))
                return p + 38
            if d[p + 10] == 0:
                ctx.mark_all(marks); ctx.mark(p + 11, 4)
                ev.append((p, "SLOTGUIDREF", sid, _u32(d, p + 11)))
                return p + 15
        return None
    marks.append((p + 9, 4))
    q = p + 13
    out = [(p, "SLOT", sid, t, n)]
    if t == 0x1e:
        if n and q < hi and d[q] == 0:            # F_1E_REF: [00][flag][u32 ref]
            for k in range(n):
                marks.append((q + 6 * k + 2, 4))
            q += 6 * n
        else:                                     # [mt][fl][u16 ti][u32 ci]
            for k in range(n):
                marks.append((q + 8 * k + 2, 2)); marks.append((q + 8 * k + 4, 4))
            q += 8 * n
    elif t == 0x18:
        for _ in range(n):
            if q < hi and d[q] == 1:
                out.append((q, "SGUIDINL", _gswap(d[q + 1:q + 17])))
                marks.append((q + 1, 4)); marks.append((q + 5, 2)); marks.append((q + 7, 2))
                q += 17
            elif q < hi and d[q] == 0:
                out.append((q, "SREF", _u32(d, q + 1)))
                marks.append((q + 1, 4)); q += 5
            else:
                return None
    elif t == 0x00:
        if n == 0:
            pass
        elif d[q] == 0:
            out.append((q, "SOBJREF", _u32(d, q + 1)))
            marks.append((q + 1, 4)); q += 5
        elif d[q] == 1:
            out.append((q, "SOBJINL")); q += 1
            sub_ctx = Ctx(record=False)
            r = try_dict_prelude(d, q, hi, out, sub_ctx)
            if r is not None:
                marks.append((q, 4)); marks.append((q + 5, 4))
                q = r
        else:
            return None
    else:
        q = _slot_payload(d, q, hi, t, n, out, marks)
        if q is None:
            return None
    if q > hi:
        return None
    if _SLOT_VALIDATE:
        if not _slot_end_ok(d, q, hi):
            return None
    elif not plausible_record_start(d, q, hi):
        return None
    ev.extend(out)
    ctx.mark_all(marks)
    return q


def try_val32(d, p, hi, ev, ctx):
    """Anonymous value: [01][u32be tagword][u32be n][n x payload]."""
    if d[p] != 1 or p + 10 > hi:
        return None
    if d[p + 1:p + 4] != b"\x00\x00\x00":
        return None
    t = d[p + 4]
    if t not in VAL32_TAGS:
        return None
    n = _u32(d, p + 5)
    if not (1 <= n <= 64):
        return None
    marks = [(p + 1, 4), (p + 5, 4)]
    q = p + 9
    out = [(p, "VAL32", t, n)]
    q = _slot_payload(d, q, hi, t, n, out, marks)
    if q is None or q > hi or not plausible_record_start(d, q, hi):
        return None
    ev.extend(out)
    ctx.mark_all(marks)
    return q


def _is_kfblob_be(d, tp) -> bool:
    """BE mirror of is_kfblob: BE tagword [00 00 00 T], T x 01, 00, then the
    RAW LE-defined 15-byte BLOB_UNITs (the interior is an unresolved pocket;
    the mirror fires only when the LE walker will also see units, i.e. when
    the raw bytes carry the LE unit pattern).  Zero expected BE instances."""
    if d[tp:tp + 3] != b"\x00\x00\x00":
        return False
    t = d[tp + 3]
    if not (5 <= t <= 0x20):
        return False
    op = tp + 4
    return (d[op:op + t] == b"\x01" * t and d[op + t] == 0
            and d[op + t + 1:op + t + 16] == BLOB_UNIT)


def _value(d, p, ev, hi, ctx):
    """Keyed value, BE mirror of keyg_walker2._value: [u32be tagword][u8 a].
    Bytes that do not carry the BE tagword shape (three zero bytes then tag)
    are NOT a BE keyed value: the region stays raw and the untouched LE
    walker's own _value defines the events (fallback)."""
    p0 = p
    if d[p:p + 3] != b"\x00\x00\x00":
        return _LE._value(d, p, ev, hi)
    t, a = d[p + 3], d[p + 4]
    # KFBLOB mirror (see _is_kfblob_be) — fires before tag dispatch, like LE
    if 5 <= t <= 0x20 and d[p0 + 4:p0 + 4 + t] == b"\x01" * t and d[p0 + 4 + t] == 0:
        q = p0 + 4 + t + 1
        u = 0
        while d[q:q + 15] == BLOB_UNIT:
            u += 1; q += 15
        if u >= 1:
            ctx.mark(p0, 4)
            ctx.pockets.append((p0 + 4, q, "KFBLOB unit run kept raw"))
            ev.append((p0, "KFBLOB", t, u))
            return q
    ctx.mark(p0, 4)
    p += 5
    if t == 0x01:
        ev.append((p0, "INT", _u32(d, p))); ctx.mark(p, 4); return p + 4
    if t == 0x04:
        ev.append((p0, "F64", struct.unpack_from(">d", d, p)[0])); ctx.mark(p, 8); return p + 8
    if t == 0x05:
        ev.append((p0, "BOOL", d[p])); return p + 1
    if t == 0x03:
        ev.append((p0, "F32")); ctx.mark(p, 4); return p + 4
    if t == 0x0b:
        ln = _u32(d, p); ctx.mark(p, 4)
        ev.append((p0, "FOURCC", d[p + 4:p + 4 + ln].decode("latin1")))
        return p + 4 + ln
    if t == 0x1f:
        if d[p] == 1:
            ln = _u32(d, p + 1); ctx.mark(p + 1, 4)
            ev.append((p0, "STRINL", d[p + 5:p + 5 + ln].decode("utf-8", "replace")))
            return p + 5 + ln
        ev.append((p0, "STRREF", _u32(d, p + 1))); ctx.mark(p + 1, 4); return p + 5
    if t == 0x00:
        # v0x13 keyed-OBJ inline with a=0 (BE mirror of the keyg_walker2 rule):
        # [tagword 0][00][01 01][prelude...] — consume the pair; the ELEMS
        # flavor's prelude head is handled by the array branch (words marked
        # there), the DICT flavor marks its prelude words here.
        if a == 0 and d[p] == 1 and d[p + 1] == 1:
            if _u32(d, p + 2) in (1, 2) and d[p + 6] in (0, 1):
                ev.append((p0, "OBJINL")); return p + 2
            sub: list = []
            r = try_dict_prelude(d, p + 2, hi, sub, ctx, strict=True)
            if r is not None:
                ev.append((p0, "OBJINL")); ev.extend(sub); return r
        # anika-2007 inline masterClip/captureSource object (value of a clipitem's
        # master-UUID DEF key): [00 00 00 00][a=0][class byte in MASTER_CLS]
        # [u32be 0x1f schema-tag][01 01][u32be namelen][ascii name] then a self-
        # terminating keyed-metadata body.  Word-swap ONLY the two BE u32 head
        # fields (the 0x1f schema word and namelen); the class byte, 01 01 marker
        # and name are endian-invariant, and the body's members tokenize on their
        # own.  The old LEAF misread double-swapped off+11 (01 01 + namelen) into
        # a 16M leaf count that buried the sequence.  Tightly gated: zero sites on
        # the other BE corpora (MUSEO/Aaron).
        if a == 0 and d[p0 + 5] in MASTER_CLS and _u32(d, p0 + 6) == 0x1f \
                and d[p0 + 10:p0 + 12] == b"\x01\x01":
            nl = _u32(d, p0 + 12)
            if 1 <= nl <= 64 and p0 + 16 + nl <= hi \
                    and all(0x20 <= c < 0x7f for c in d[p0 + 16:p0 + 16 + nl]):
                ev.append((p0, "MASTEROBJ", d[p0 + 16:p0 + 16 + nl].decode("utf-8", "replace")))
                ctx.mark(p0 + 6, 4); ctx.mark(p0 + 12, 4)
                return p0 + 16 + nl
        mk = d[p]; p += 1
        if mk == 0:
            ref = _u32(d, p)
            if a == 0 and ref > SLOT_MAX_ID and plausible_record_start(d, p, hi):
                ev.append((p0, "OBJEMPTY")); return p
            ev.append((p0, "OBJREF", ref)); ctx.mark(p, 4); return p + 4
        # LEAF: [u32 A<=0xff][u8 01][u32 B], next byte a DEF length (peeked). The
        # off+9 zero (d[p+3]) is required so the anika masterClip schema word
        # (BE 0x1f, nonzero low byte) can never reach this double-swap path.
        if (d[p + 4] == 1 and d[p] == 0 and d[p + 1] == 0 and d[p + 2] == 0 and d[p + 3] == 0
                and 1 <= d[p + 9] <= 40 and all(0x20 <= c < 0x7f for c in d[p + 10:p + 10 + d[p + 9]])):
            ev.append((p0, "LEAF")); ctx.mark(p, 4); ctx.mark(p + 5, 4); return p + 9
        ev.append((p0, "OBJINL"))
        r = try_dict_prelude(d, p, hi, ev, ctx)
        return r if r is not None else p
    if t == 0x23:
        if d[p] == 1 and d[p + 1:p + 5] == b"\x00\x00\x00\x22":
            ln = _u32(d, p + 5); ctx.mark(p + 1, 4); ctx.mark(p + 5, 4)
            ev.append((p0, "UUID", d[p + 9:p + 9 + ln].decode("ascii", "replace")))
            return p + 9 + ln
        # anika (v0x17, PPC-2007) inline UUID: same [01][type][len][ascii] geometry
        # as the Intel form above, but the type constant is 0x18, not 0x22 (byte-
        # proven: anika's 1544 UUIDs all carry 0x18; MUSEO/Aaron — the only other
        # BE corpora — carry 0x22, so this branch never fires on them).  A plain
        # byte-order swap would leave the LE type word as 18 00 00 00; instead we
        # POKE it to the Intel-canonical 22 00 00 00 so the UNTOUCHED LE walker
        # reads a normal inline UUID and no dialect branch is needed there.  Swap
        # the length word as usual.  Version-gated to 0x17 and guarded on a
        # printable, bounded-length body so a genuine UUIDREF whose ref value
        # happens to be 0x18 can never be misclaimed.
        if d[p] == 1 and d[p + 1:p + 5] == b"\x00\x00\x00\x18" \
                and d[0x2e] == 1 and _u32(d, 0x2f) == 0x17:
            ln = _u32(d, p + 5)
            if 0 < ln <= 0x100 and p + 9 + ln <= hi \
                    and all(0x20 <= c < 0x7f for c in d[p + 9:p + 9 + ln]):
                ctx.mark(p + 5, 4); ctx.poke(p + 1, b"\x22\x00\x00\x00")
                ev.append((p0, "UUID", d[p + 9:p + 9 + ln].decode("ascii", "replace")))
                return p + 9 + ln
        # F_UUIDL long form: managed-0x113 only, zero BE instances — no mirror
        ev.append((p0, "UUIDREF", _u32(d, p + 1))); ctx.mark(p + 1, 4); return p + 5
    if t == 0x1e:
        for k in range(a):
            ctx.mark(p + 8 * k + 2, 2); ctx.mark(p + 8 * k + 4, 4)
        ev.append((p0, "STRUCT1E", a)); return p + 8 * a
    if t == 0x07:
        if d[p] == 1:
            ln = _u32(d, p + 1); ctx.mark(p + 1, 4)
            ev.append((p0, "DATA07", ln)); return p + 5 + ln
        ev.append((p0, "DATA07REF", _u32(d, p + 1))); ctx.mark(p + 1, 4); return p + 5
    if t in (0x18, 0x21):
        if d[p] == 1:
            ln = _u32(d, p + 1); ctx.mark(p + 1, 4)
            ev.append((p0, "BLOBINL", t, ln)); return p + 5 + ln
        ev.append((p0, "BLOBREF", t, _u32(d, p + 1))); ctx.mark(p + 1, 4); return p + 5
    if t == 0x10:
        if d[p] == 0:
            ev.append((p0, "G10REF", _u32(d, p + 1))); ctx.mark(p + 1, 4); return p + 5
        if d[p] == 1 and d[p + 1] == 0:
            ev.append((p0, "G10REF", _u32(d, p + 2))); ctx.mark(p + 2, 4); return p + 6
        if d[p] == 1 and d[p + 1] == 1:
            g = d[p + 2:p + 18]
            ev.append((p0, "G10INL", _gswap(g))); ctx.mark_guid(p + 2); return p + 18
    if t == 0x16 and a == 1:
        # v0x16 timecode param: [F64be value][u32be timebase][u16be 0] — mirror
        # of keyg_walker2's T16TIME rule (kid/tag words marked by the caller)
        ev.append((p0, "T16TIME", struct.unpack_from(">d", d, p)[0], _u32(d, p + 8)))
        ctx.mark(p, 8); ctx.mark(p + 8, 4); ctx.mark(p + 12, 2)
        return p + 14
    if t == 0x06 and d[p] == 1 and d[p + 1] == 1:
        # v0x16 keyed GUID (FXScript plugin state), keyed-G10INL geometry
        ev.append((p0, "G10INL", _gswap(d[p + 2:p + 18]))); ctx.mark_guid(p + 2); return p + 18
    if t in FIXED_TAGS:
        marks = []
        for k in range(max(a, 1)):
            _mark_fixed(t, p + FIXED_TAGS[t] * k, marks)
        ctx.mark_all(marks)
        ev.append((p0, "FIXED", t, a)); return p + FIXED_TAGS[t] * max(a, 1)
    if t == 0x0c:
        if d[p] == 1 and d[p + 1] <= 1 and d[p + 6] <= 1:
            ev.append((p0, "T0C", a))
            ctx.mark(p + 2, 4); ctx.mark(p + 7, 4)
            if d[p + 6] == 0:
                return p + 12
            return p + 11
    if t == 0x20:
        if d[p] == 1:
            n = _u32(d, p + 1)
            if 0 < n <= 0x100 and all(0x20 <= c < 0x7f for c in d[p + 5:p + 5 + n]):
                ev.append((p0, "T20", d[p + 5:p + 5 + n].decode()))
                ctx.mark(p + 1, 4)
                q = p + 5 + n
                if _u32(d, q) == 1 and d[q + 4] in (0, 1) and _u32(d, q + 5) == 0:
                    ctx.mark(q, 4); ctx.mark(q + 5, 4)
                    q += 9
                return q
        elif d[p] == 0:
            ev.append((p0, "T20REF", _u32(d, p + 1))); ctx.mark(p + 1, 4); return p + 5
    # unknown tag (incl. the version-0x16-only 0x16/0x1a families): the LE
    # walker emits VUNK and re-walks the payload — mirrored via the fallback
    ev.append((p0, "VUNK", t))
    return p


def _value_extent_sane(d, tp, hi):
    """Cheap insanity check for a BE keyed value at tagword tp before an
    NKEY/DEF mirror commits to it: refuse constructs whose inline length
    would run past hi (junk misreads; the LE fallback then defines events —
    keyg_walker2._value itself carries no such bounds because the gated
    corpora are well-formed, but the mirror walks unknown-dialect junk)."""
    if d[tp:tp + 3] != b"\x00\x00\x00":
        return True                      # not BE-shaped: _value defers anyway
    t = d[tp + 3]
    q = tp + 5
    if t == 0x0b:
        return q + 4 + _u32(d, q) <= hi
    if t in (0x1f, 0x07, 0x18, 0x21):
        if q < hi and d[q] == 1:
            return q + 5 + _u32(d, q + 1) <= hi
        return True
    if t == 0x23:
        if q + 5 <= hi and d[q] == 1 and d[q + 1:q + 5] == b"\x00\x00\x00\x22":
            return q + 9 + _u32(d, q + 5) <= hi
        return True
    if t == 0x1e:
        return q + 8 * d[tp + 4] <= hi
    if t in FIXED_TAGS:
        return q + FIXED_TAGS[t] * max(d[tp + 4], 1) <= hi
    return True


def _orphan18_be_ctx(ev, d) -> bool:
    """BE-side twin of keyg_walker2._orphan18_ctx: same event context, with
    the version gate read big-endian (the swab only ever walks BE files, and
    the swabbed output carries the same version as a u32le — so both walks
    agree on the gate by construction)."""
    if len(ev) < 2 or d[0x2e] != 1 or _u32(d, 0x2f) != 0x13:
        return False
    k1, k2 = ev[-1][1], ev[-2][1]
    if k1 == "OBJSLOTREF" and ev[-1][2] == 1 \
            and k2 in ("SLOTGUIDREF", "BAREREF", "GUIDREF", "GUIDREF2", "CNTW"):
        return True
    return k1 == "BAREREF" and k2 == "CNTW"


def _le_step(d, p, hi, ev, ctx):
    """ONE iteration of the untouched LE walker's decision cascade on the RAW
    bytes at p.  Used when no mirror branch fired: the bytes stay identical
    in the swabbed file, so keyg_walker2 behaves exactly like this there.
    Port of keyg_walker2.tokenize()'s loop body (helpers delegated)."""
    u32 = _LE._u32
    p0 = p
    if d[p:p + 9] == b"\x01\x01\x00\x00\x00\x18\x00\x00\x00":
        if d[p + 9:p + 11] == b"\x01\x01":
            ev.append((p0, "GUIDINL", d[p + 11:p + 27])); return p + 38
        if d[p + 9:p + 11] == b"\x01\x00":
            ev.append((p0, "GUIDREF", u32(d, p + 11))); return p + 15
        ev.append((p0, "GUIDREF", u32(d, p + 10))); return p + 14
    if d[p:p + 9] == b"\x01\x01\x00\x00\x00\x10\x00\x00\x00":
        if d[p + 9:p + 11] == b"\x01\x01":
            ev.append((p0, "G10INL", d[p + 11:p + 27])); return p + 27
        if d[p + 9:p + 11] == b"\x01\x00":
            ev.append((p0, "G10REF", u32(d, p + 11))); return p + 15
        ev.append((p0, "G10REF", u32(d, p + 10))); return p + 14
    if d[p:p + 9] == b"\x01\x01\x00\x00\x00\x1a\x00\x00\x00":
        if d[p + 9:p + 11] == b"\x01\x01":
            ev.append((p0, "GUIDINL", d[p + 11:p + 27])); return p + 38
        if d[p + 9:p + 11] == b"\x01\x00":
            ev.append((p0, "GUIDREF", u32(d, p + 11))); return p + 15
        ev.append((p0, "GUIDREF", u32(d, p + 10))); return p + 14
    if d[p:p + 9] == b"\x01\x01\x00\x00\x00\x00\x00\x00\x00":
        if p + 13 <= hi and u32(d, p + 9) == 0:
            ev.append((p0, "OTAGOBJ")); return p + 9
        if d[p + 9] == 0:
            ev.append((p0, "OTAGREF", u32(d, p + 10))); return p + 14
        # version gate read BE: the LE walker sees the SWABBED version word
        # (u32le 0x13), which equals the original's u32be read
        if d[p + 9] == 0x05 and d[0x2e] == 1 and _u32(d, 0x2f) == 0x13 \
                and u32(d, p + 10) <= 0x100 \
                and p + 15 + u32(d, p + 10) <= hi \
                and d[p + 14 + u32(d, p + 10)] == 0:
            n05 = u32(d, p + 10)
            ev.append((p0, "OTAGINL"))
            ev.append((p + 9, "BLOBINL", 0x05, n05))
            return p + 15 + n05
        ev.append((p0, "OTAGINL")); p += 10
        r = _LE.try_dict_prelude(d, p, hi, ev)
        return r if r is not None else p
    if d[p:p + 9] == b"\x01\x02\x00\x00\x00\x18\x00\x00\x00" \
            and d[p + 9] == 0 and d[p + 14:p + 18] == b"\x18\x00\x00\x00":
        if d[p + 18] == 0:
            ev.append((p0, "GUIDREF", u32(d, p + 10)))
            ev.append((p + 14, "GUIDREF2", u32(d, p + 19)))
            return p + 23
        if d[p + 18:p + 20] == b"\x01\x00":
            ev.append((p0, "GUIDREF", u32(d, p + 10)))
            ev.append((p + 14, "GUIDREF2", u32(d, p + 20)))
            return p + 24
    if d[p:p + 9] == b"\x01\x02\x00\x00\x00\x10\x00\x00\x00" \
            and d[p + 9:p + 11] == b"\x01\x01":
        ev.append((p0, "G10INL", d[p + 11:p + 27])); return p + 27
    if p + 13 <= hi and u32(d, p) in (1, 2) and d[p + 4] in (0, 1):
        et = u32(d, p + 5)
        if et == 0:
            C = u32(d, p + 9)
            if C < 100000:
                ev.append((p0, "PRELUDE", C)); return p + 13
        elif et == 1:
            C = u32(d, p + 9)
            if C <= SLOT_MAX_COUNT and p + 13 + 4 * C <= hi:
                ev.append((p0, "ARRAY", 1, C)); return p + 13 + 4 * C
            if C < 100000:
                ev.append((p0, "PRELUDE", C)); return p + 13
        elif et == 0x20:
            C = u32(d, p + 9)
            r = _LE.try_named_array(d, p + 13, hi, C)
            if r is not None:
                ev.append((p0, "ARRAY", 0x20, C)); ctx.raw_arrays.add(p0); return r
        elif et in ARRAY_ELEM_SIZES or et in (0x1f, 0x07, 0x21):
            C = u32(d, p + 9)
            if C <= SLOT_MAX_COUNT:
                q = p + 13
                ok = True
                if et in ARRAY_ELEM_SIZES:
                    q += ARRAY_ELEM_SIZES[et] * C
                    ok = q <= hi
                else:
                    for _ in range(C):
                        r = _LE._flagged(d, q, hi)
                        if r is None:
                            ok = False; break
                        q = r[0]
                if ok:
                    ev.append((p0, "ARRAY", et, C)); ctx.raw_arrays.add(p0); return q
    if d[p] == 1 and d[p + 2:p + 5] == b"\x00\x00\x00":
        fs = _LE.try_filespec(d, p, hi)
        if fs and fs[1] >= 2:
            end, nf, spans = fs
            ev.append((p0, "FILESPEC", nf, tuple(spans))); return end
        r = _LE.try_slot(d, p, hi, ev)
        if r is not None:
            return r
        r = _LE.try_val32(d, p, hi, ev)
        if r is not None:
            return r
        if d[p + 5] == 0 and d[p + 6] <= 1 and p + 11 <= hi:
            sid = u32(d, p + 1)
            w = u32(d, p + 7)
            if (sid <= SLOT_MAX_ID
                    and w <= (0x10000 if d[p + 6] else SLOT_MAX_ID)
                    and _LE.plausible_record_start(d, p + 11, hi)):
                ev.append((p0, "OBJSLOTINL" if d[p + 6] else "OBJSLOTREF", sid, w))
                return p + 11
        if d[p + 1] == 0:
            r = _LE.try_dict_prelude(d, p + 1, hi, ev, strict=True)
            if r is not None:
                ev.insert(len(ev) - 1, (p0, "OBJINL1"))
                return r
        if d[p + 1] != 1:
            ev.append((p0, "PTOK", u32(d, p + 1))); return p + 5
        if _LE.plausible_record_start(d, p + 5, hi):
            ev.append((p0, "PTOK", 1)); return p + 5
    if d[p] == 1 and d[p + 1] == 0 and p + 6 <= hi:
        w = u32(d, p + 2)
        if w <= SLOT_MAX_ID and _LE.plausible_record_start(d, p + 6, hi):
            ev.append((p0, "BAREREF", w)); return p + 6
    if d[p] == 0 and d[p + 1] == 0x18 and d[p + 2:p + 5] == b"\x00\x00\x00" \
            and _orphan18_be_ctx(ev, d):
        # ORPHAN18 tails — port of the keyg_walker2 branch (see _mirror_step)
        if d[p + 5:p + 9] == b"\x00\x00\x00\x00" and d[p + 9] == 1 \
                and d[p + 10] == 0 and 0 < u32(d, p + 11) <= SLOT_MAX_ID:
            ev.append((p + 1, "CNTW", 0x18))
            ev.append((p + 11, "BAREREF", u32(d, p + 11)))
            return p + 15
        if d[p + 5] == 0 and 0 < u32(d, p + 6) <= SLOT_MAX_ID:
            ev.append((p + 1, "CNTW", 0x18))
            ev.append((p + 6, "BAREREF", u32(d, p + 6)))
            return p + 10
    if d[p] == 0 and d[p + 1]:
        fr = _LE.try_fnrec(d, p + 1, hi)
        if fr is not None:
            ev.append((p + 1, "FNREC", fr[0])); return fr[1]
    if d[p] == 0 and d[p + 1] and d[p + 5] < 0x30:
        kid = u32(d, p + 1)
        if (0 < kid <= SLOT_MAX_ID and d[p + 6:p + 9] == b"\x00\x00\x00"
                and (d[p + 5] in SLOT_TAGS or d[p + 5] in FIXED_TAGS
                     or d[p + 5] in (0x0c, 0x20, 0x10, 0x16, 0x06) or _LE.is_kfblob(d, p + 5))):
            if not (kid & 0xff == 1 and d[p + 5] == 0 and _LE.try_filespec(d, p + 1, hi)):
                ev.append((p0, "NKEY", kid)); return _LE._value(d, p + 5, ev, hi)
    if d[p] == 0 and d[p + 1] and d[p + 5] == 0 and d[p + 6] in (0x02, 0x05):
        kid = u32(d, p + 1)
        if (0 < kid <= SLOT_MAX_ID and d[p + 7:p + 10] == b"\x00\x00\x00"
                and p + 11 <= hi and d[p + 10] <= 1):
            ev.append((p0, "NKEY", kid)); return _LE._value(d, p + 6, ev, hi)
    if d[p] == 0 and d[p + 1] and d[p + 4] < 0x30:
        kid = u32(d, p)
        if (0 < kid <= SLOT_MAX_ID and d[p + 5:p + 8] == b"\x00\x00\x00"
                and (d[p + 4] in SLOT_TAGS or d[p + 4] in FIXED_TAGS or d[p + 4] in (0x0c, 0x10, 0x16, 0x06))):
            if not (d[p + 1] == 1 and d[p + 4] == 0 and _LE.try_filespec(d, p + 1, hi)):
                ev.append((p0, "NKEY", kid)); return _LE._value(d, p + 4, ev, hi)
    if d[p] == 0:
        return p + 1
    n = d[p]
    fr = _LE.try_fnrec(d, p, hi)
    if fr is not None:
        ev.append((p0, "FNREC", fr[0])); return fr[1]
    if 0 < n <= 80 and p + 1 + n <= hi and all(0x20 <= c < 0x7f for c in d[p + 1:p + 1 + n]):
        ev.append((p0, "DEF", d[p + 1:p + 1 + n].decode()))
        return _LE._value(d, p + 1 + n, ev, hi)
    kid = u32(d, p)
    if (0 < kid <= SLOT_MAX_ID and d[p + 4] < 0x30 and d[p + 5:p + 8] == b"\x00\x00\x00"
            and (d[p + 4] in SLOT_TAGS or d[p + 4] in FIXED_TAGS or d[p + 4] in (0x0c, 0x20, 0x10, 0x16, 0x06))):
        ev.append((p0, "NKEY", kid)); return _LE._value(d, p + 4, ev, hi)
    if (d[p + 1] == 0 and d[p + 2] == 0 and d[p + 3] == 0 and u32(d, p) <= 0x10000
            and _LE.plausible_record_start(d, p + 4, hi)):
        ev.append((p0, "CNTW", u32(d, p))); return p + 4
    if d[p] == 0x18 and d[p + 1:p + 5] == b"\x00\x00\x00\x00" and d[p + 5]:
        ev.append((p0, "GUIDORPH", u32(d, p + 5) & 0xff)); return p + 6
    ev.append((p0, "RAW", d[p])); return p + 1


def _mirror_step(d, p, hi, ev, ctx, prev_raw=False):
    """BE-mirror cascade in keyg_walker2's branch order.  Returns the new
    position when a mirror branch fires (spans marked), else None.
    prev_raw: the walk arrived here from a RAW byte (junk region) — the LE
    walker's evaluation there read forward on RAW bytes, so keyed-word mirrors
    must not swab within its reach."""
    p0 = p
    # --- GUID block magic -------------------------------------------------
    if d[p:p + 9] == MAG_GUID1:
        ctx.mark(p + 1, 4); ctx.mark(p + 5, 4)
        if d[p + 9:p + 11] == b"\x01\x01":
            ev.append((p0, "GUIDINL", _gswap(d[p + 11:p + 27])))
            ctx.mark_guid(p + 11)
            ctx.mark(p + 27 + 2, 4); ctx.mark(p + 27 + 7, 4)   # trailer 0/w words
            return p + 38
        if d[p + 9:p + 11] == b"\x01\x00":
            ev.append((p0, "GUIDREF", _u32(d, p + 11))); ctx.mark(p + 11, 4); return p + 15
        ev.append((p0, "GUIDREF", _u32(d, p + 10))); ctx.mark(p + 10, 4); return p + 14
    if d[p:p + 9] == MAG_G10_1:
        ctx.mark(p + 1, 4); ctx.mark(p + 5, 4)
        if d[p + 9:p + 11] == b"\x01\x01":
            ev.append((p0, "G10INL", _gswap(d[p + 11:p + 27])))
            ctx.mark_guid(p + 11); return p + 27
        if d[p + 9:p + 11] == b"\x01\x00":
            ev.append((p0, "G10REF", _u32(d, p + 11))); ctx.mark(p + 11, 4); return p + 15
        ev.append((p0, "G10REF", _u32(d, p + 10))); ctx.mark(p + 10, 4); return p + 14
    # --- v0x16 tag-0x1a GUID magic (kind word 0x1a, 0x18-family geometry) ----
    if d[p:p + 9] == MAG_T1A:
        ctx.mark(p + 1, 4); ctx.mark(p + 5, 4)
        if d[p + 9:p + 11] == b"\x01\x01":
            ev.append((p0, "GUIDINL", _gswap(d[p + 11:p + 27])))
            ctx.mark_guid(p + 11)
            ctx.mark(p + 27 + 2, 4); ctx.mark(p + 27 + 7, 4)   # trailer 0/w words
            return p + 38
        if d[p + 9:p + 11] == b"\x01\x00":
            ev.append((p0, "GUIDREF", _u32(d, p + 11))); ctx.mark(p + 11, 4); return p + 15
        ev.append((p0, "GUIDREF", _u32(d, p + 10))); ctx.mark(p + 10, 4); return p + 14
    # --- OTAG magic (BE form) ----------------------------------------------
    if d[p:p + 9] == MAG_OTAG:
        if p + 13 <= hi and _u32(d, p + 9) == 0:
            ev.append((p0, "OTAGOBJ")); ctx.mark(p + 1, 4); ctx.mark(p + 5, 4)
            return p + 9
        if d[p + 9] == 0:
            ev.append((p0, "OTAGREF", _u32(d, p + 10)))
            ctx.mark(p + 1, 4); ctx.mark(p + 5, 4); ctx.mark(p + 10, 4)
            return p + 14
        # v0x13 T05LIST: OTAG head + bare tag-5 byte list (BE mirror of the
        # keyg_walker2 rule): [05][u32be n][n x u8][00] — n word swaps,
        # payload bytes are endian-invariant
        if d[p + 9] == 0x05 and d[0x2e] == 1 and _u32(d, 0x2f) == 0x13 \
                and _u32(d, p + 10) <= 0x100 \
                and p + 15 + _u32(d, p + 10) <= hi \
                and d[p + 14 + _u32(d, p + 10)] == 0:
            n05 = _u32(d, p + 10)
            ev.append((p0, "OTAGINL"))
            ev.append((p + 9, "BLOBINL", 0x05, n05))
            ctx.mark(p + 1, 4); ctx.mark(p + 5, 4); ctx.mark(p + 10, 4)
            return p + 15 + n05
        # OTAGINL: [magic][01] + dict prelude
        ev.append((p0, "OTAGINL")); ctx.mark(p + 1, 4); ctx.mark(p + 5, 4)
        p = p + 10
        r = try_dict_prelude(d, p, hi, ev, ctx)
        return r if r is not None else p
    # --- 0x16-only count-C GUID-ref list continuation -----------------------
    # The count-less GUID-slot mirror (try_slot) has just consumed the head
    # [01][u32be C][u32be 0x18][01][00][u32be ref1] as SLOTGUIDREF(C, ref1);
    # in the 2008 dialect C >= 2 continues with C-1 trailer+entry units
    #   [01 01 + 9x00][00 pad][u32be 0x18][01][00][u32be ref]
    # and a final trailer.  Swapping each entry's tagword and ref word makes
    # the untouched LE walker read the run as pure glue — OTAGREF(0x180000) +
    # BAREREF(ref) per unit, OTAGOBJ at the final trailer — no keys, no
    # object heads.  The old junk framing (NKEY(0x1801) + open OBJINL per
    # unit) leaked open frames into every timeline-clip dict of the four
    # MUSEO_Souvenirs sequences and cascaded into audm/track loss (51 runs
    # live, C 16/18, all strict-layout).
    if d[p] == 1 and d[p + 1] == 1 and p >= 15 and d[p - 15] == 1:
        r = try_guidref_list(d, p, hi, ev, ctx)
        if r is not None:
            return r
    # --- loose GUID trailer glue: [01][01][u32 0][mk][u32be w], w != 0 ------
    # (w == 0 is byte-invariant: the LE fallback reads it as OTAGOBJ; recon
    #  swap_spec section 3.2 / museo_quirks section 3.2 — the w word MUST swap
    #  or the LE walker misframes the trailer as OTAGREF garbage.)
    if d[p] == 1 and d[p + 1] == 1 and d[p + 2:p + 6] == b"\x00\x00\x00\x00" \
            and d[p + 6] <= 1 and p + 11 <= hi:
        w = _u32(d, p + 7)
        limit = 0x10000 if d[p + 6] else SLOT_MAX_ID
        if 0 < w <= min(limit, 0xffff) and plausible_record_start(d, p + 11, hi):
            ev.append((p0, "OBJSLOTINL" if d[p + 6] else "OBJSLOTREF", 1, w))
            ctx.mark(p + 7, 4)
            return p + 11
    # --- count-2 GUID prelude ------------------------------------------------
    if d[p:p + 9] == MAG_GUID2 and d[p + 9] == 0 \
            and d[p + 14:p + 18] == b"\x00\x00\x00\x18":
        if d[p + 18] == 0:
            ev.append((p0, "GUIDREF", _u32(d, p + 10)))
            ev.append((p + 14, "GUIDREF2", _u32(d, p + 19)))
            ctx.mark(p + 1, 4); ctx.mark(p + 5, 4); ctx.mark(p + 10, 4)
            ctx.mark(p + 14, 4); ctx.mark(p + 19, 4)
            return p + 23
        if d[p + 18:p + 20] == b"\x01\x00":
            ev.append((p0, "GUIDREF", _u32(d, p + 10)))
            ev.append((p + 14, "GUIDREF2", _u32(d, p + 20)))
            ctx.mark(p + 1, 4); ctx.mark(p + 5, 4); ctx.mark(p + 10, 4)
            ctx.mark(p + 14, 4); ctx.mark(p + 20, 4)
            return p + 24
    if d[p:p + 9] == MAG_G10_2 and d[p + 9:p + 11] == b"\x01\x01":
        ev.append((p0, "G10INL", _gswap(d[p + 11:p + 27])))
        ctx.mark(p + 1, 4); ctx.mark(p + 5, 4); ctx.mark_guid(p + 11)
        return p + 27
    # --- zeros then bare inline marker [01] + strict dict prelude ------------
    # Protect the real OBJINL1 before ANY numeric mirror can claim its bytes.
    # Hoisted ABOVE the array gate: with the marker at p+3 the BE array gate
    # reads [pads][01][prelude] as kind-word u32be 1 and swallows the element
    # head as a fake INT array (observed at MUSEO seq apresModifs clip 2
    # @0x430825, read as ARRAY(1,32) — sheared the audm A-track wrappers).
    # k reaches 5: with the marker at p+4 the NKEY form-1 mirror misreads
    # pads+marker+prelude as kid `00 00 00 01` (the v0x16 empty-track
    # wrappers after 5-zero pads, e.g. @0x202777 in MUSEO seq2).
    if d[p] == 0:
        for k in (1, 2, 3, 4, 5):
            if d[p + k] == 1 and all(d[p + j] == 0 for j in range(1, k)):
                r = try_dict_prelude(d, p + k + 1, hi, ev, ctx, strict=True)
                if r is not None:
                    ev.insert(len(ev) - 1, (p + k, "OBJINL1"))
                    return r
            if d[p + k]:
                break
    # --- arrays / preludes: [u32be kind 1|2][u8 f][u32be et][u32be C] --------
    if p + 13 <= hi and _u32(d, p) in (1, 2) and d[p + 4] in (0, 1):
        et = _u32(d, p + 5)
        head = [(p, 4), (p + 5, 4), (p + 9, 4)]
        if et == 0:
            C = _u32(d, p + 9)
            if C < 100000:
                ev.append((p0, "PRELUDE", C)); ctx.mark_all(head); return p + 13
        elif et == 1:
            C = _u32(d, p + 9)
            if C <= SLOT_MAX_COUNT and p + 13 + 4 * C <= hi:
                ev.append((p0, "ARRAY", 1, C)); ctx.mark_all(head)
                for k in range(C):
                    ctx.mark(p + 13 + 4 * k, 4)
                return p + 13 + 4 * C
            if C < 100000:
                ev.append((p0, "PRELUDE", C)); ctx.mark_all(head); return p + 13
        elif et == 0x20:
            C = _u32(d, p + 9)
            marks = []
            r = try_named_array(d, p + 13, hi, C, marks)
            if r is not None:
                ev.append((p0, "ARRAY", 0x20, C))
                ctx.mark_all(head); ctx.mark_all(marks)
                ctx.pockets.append((p + 13, r, "named-array element bodies kept raw"))
                return r
        elif et in ARRAY_ELEM_SIZES or et in (0x1f, 0x07, 0x21):
            C = _u32(d, p + 9)
            if C <= SLOT_MAX_COUNT:
                q = p + 13
                ok = True
                marks = []
                if et in ARRAY_ELEM_SIZES:
                    sz = ARRAY_ELEM_SIZES[et]
                    if p + 13 + sz * C <= hi:
                        for k in range(C):
                            e = q + sz * k
                            if et == 0x03:
                                marks.append((e, 4))
                            elif et == 0x04:
                                marks.append((e, 8))
                            elif et == 0x1e:
                                marks.append((e + 2, 2)); marks.append((e + 4, 4))
                            elif et in FIXED_TAGS:
                                _mark_fixed(et, e, marks)
                        q += sz * C
                    else:
                        ok = False
                else:
                    for _ in range(C):
                        r = _flagged(d, q, hi, marks)
                        if r is None:
                            ok = False; break
                        q = r[0]
                if ok:
                    ev.append((p0, "ARRAY", et, C))
                    ctx.mark_all(head); ctx.mark_all(marks)
                    return q
    # --- [01]-headed records (BE gate: sid/tag word high bytes zero) --------
    if d[p] == 1 and d[p + 1:p + 4] == b"\x00\x00\x00":
        r = try_bare_guidref_list(d, p, hi, ev, ctx)
        if r is not None:
            return r
        fs = try_filespec(d, p, hi)
        if fs and fs[1] >= 2:
            end, nf, spans = fs
            ev.append((p0, "FILESPEC", nf, tuple(spans)))
            ctx.mark(p + 1, 4)
            for off, _ln in spans:
                ctx.mark(off - 4, 4)
            # span[4] is the Carbon path array [u32 flag][u32 q][u32 ncomp]
            # [ncomp x NUL-terminated component]: the three header words are
            # HOST-endian (unlike the natively-BE alias blob in span[0]) and
            # keyg_grouper._decode_carbon_path unpacks them '<III' — without
            # this swap every pathurl/source-TC lookup returns None.  The
            # components after the 12-byte header are endian-invariant.
            if len(spans) >= 5 and spans[4][1] >= 12 \
                    and 1 <= _u32(d, spans[4][0] + 8) <= 64:
                ctx.mark(spans[4][0], 4)
                ctx.mark(spans[4][0] + 4, 4)
                ctx.mark(spans[4][0] + 8, 4)
            return end
        r = try_slot(d, p, hi, ev, ctx)
        if r is not None:
            return r
        r = try_val32(d, p, hi, ev, ctx)
        if r is not None:
            return r
        # glue R3 obj-slot, BE shape: [01][u32be sid][00][mk<=1][u32be w].
        # sid == 0 excluded: post-swab the head reads u32le == 1, so the LE
        # walker's array/prelude gate fires first (checker diff family 0).
        if d[p + 5] == 0 and d[p + 6] <= 1 and p + 11 <= hi:
            sid = _u32(d, p + 1)
            w = _u32(d, p + 7)
            if (0 < sid <= SLOT_MAX_ID
                    and w <= (0x10000 if d[p + 6] else SLOT_MAX_ID)
                    and plausible_record_start(d, p + 11, hi)):
                ev.append((p0, "OBJSLOTINL" if d[p + 6] else "OBJSLOTREF", sid, w))
                ctx.mark(p + 1, 4); ctx.mark(p + 7, 4)
                return p + 11
        if d[p + 4] == 0:
            # bare inline marker [01] + strict dict prelude (prelude first
            # word must be zero, so d[p+4] == 0 is a cheap pre-gate)
            r = try_dict_prelude(d, p + 1, hi, ev, ctx, strict=True)
            if r is not None:
                ev.insert(len(ev) - 1, (p0, "OBJINL1"))
                return r
        if d[p + 4] != 1:
            r = try_be_refarray_v14(d, p, hi, ev, ctx)
            if r is not None:
                return r
            ev.append((p0, "PTOK", _u32(d, p + 1))); ctx.mark(p + 1, 4); return p + 5
        if plausible_record_start(d, p + 5, hi):
            ev.append((p0, "PTOK", 1)); ctx.mark(p + 1, 4); return p + 5
    # --- bare flagged ref [01][00][u32be ref] --------------------------------
    if d[p] == 1 and d[p + 1] == 0 and p + 6 <= hi:
        w = _u32(d, p + 2)
        if w <= SLOT_MAX_ID and plausible_record_start(d, p + 6, hi):
            ev.append((p0, "BAREREF", w)); ctx.mark(p + 2, 4); return p + 6
    # --- zero-marked records --------------------------------------------------
    if d[p] == 0:
        # (the zeros-then-OBJINL1 protection ran above, before the array gate)
        if prev_raw:
            # junk arrival: the LE walker's step at the preceding RAW byte(s)
            # read forward into this word on RAW bytes; swabbing it here would
            # retroactively change that read (hijack).  Leave the region raw —
            # the LE fallback then matches the LE walker by construction.
            return None
        # pad zero then a BE GUID magic: skip the pad so the magic branch
        # fires (the NKEY form-1 mirror below would misread the BE count
        # word's 01 byte as kid=1 and shred the record — observed after
        # UUID entries, e.g. itw's track GUIDREF @0xe0a6d).  The LE walker
        # at the swabbed pad is a plain zero-skip: its NKEY gate fails on
        # the 0x18/0x10 byte inside the swapped tag word.
        if d[p + 1] == 1 and (
                d[p + 1:p + 10] == MAG_GUID1 or d[p + 1:p + 10] == MAG_G10_1
                or d[p + 1:p + 10] == MAG_T1A
                or (d[p + 1:p + 10] == MAG_GUID2 and d[p + 10] == 0
                    and d[p + 15:p + 19] == b"\x00\x00\x00\x18")
                or (d[p + 1:p + 10] == MAG_G10_2
                    and d[p + 10:p + 12] == b"\x01\x01")):
            return p + 1
        # v0x14 pad zero before a BE [01]-headed record: skip the pad so the
        # [01] branch frames the record.  A FIXED-8 effect object's members
        # are followed by 2 pad zeros then a PTOK/CNTW/BAREREF/OBJSLOTREF glue
        # tail (mirror of the resaved-copy layout: FIXED(8,1) NKEY UUID
        # PTOK(7) CNTW(16) BAREREF OBJSLOTREF).  At the SECOND pad the LE-raw
        # fallback reads the record's BE [01][00 00 00 n] head as an LE
        # NKEY(1)+DATA07 (len 218103808 -> past EOF -> collapse at 0x486ea).
        # The d[p+2:p+5] zero gate excludes every BE NKEY form (their kid
        # mid/low bytes are nonzero there) and CNTW (needs d[p+3] nonzero), so
        # only a genuine [01][00 00 00 ...] record can follow; the [01] branch
        # then frames and swaps it, and the untouched LE walker at the swabbed
        # pad plain zero-skips to the same record.  Version-gated to 0x14 so it
        # cannot fire on Aaron v0x13 / MUSEO v0x16 / anika v0x17.
        if d[p + 1] == 1 and d[p + 2:p + 5] == b"\x00\x00\x00" \
                and d[0x2e] == 1 and _u32(d, 0x2f) == 0x14:
            return p + 1
        # v0x14 FNREC (reel/name filename record): the LE walker's try_fnrec is
        # a managed-dialect LE construct [L le][0][0][1 le][name][00 00]; in the
        # BE v0x14 stream it is the mirror [00 00 00 L][0][0][00 00 00 01][name]
        # [00 00 00].  The current parse misreads the L word as NKEY(<L>) then
        # fragments the name into DEF/VUNK/CNTW and desyncs (fatal @0x4059d3, the
        # reel string "11C 001").  Reverse the L word and the [00 00 00 01] word
        # so the untouched LE walker's try_fnrec (line 819) fires on the swabbed
        # bytes and consumes the whole record; emit FNREC at p+1 (the L byte) to
        # match its offset.  Signature is try_fnrec's (11 zero bytes + the 01
        # word + printable run + 00 00) — ZERO matches on any other corpus — and
        # version-gated to 0x14 so it cannot touch Aaron v0x13 / MUSEO v0x16 /
        # anika v0x17.
        if (d[0x2e] == 1 and _u32(d, 0x2f) == 0x14
                and d[p + 1:p + 4] == b"\x00\x00\x00" and 14 <= d[p + 4] <= 93
                and d[p + 5:p + 13] == b"\x00" * 8
                and d[p + 13:p + 16] == b"\x00\x00\x00" and d[p + 16] == 1):
            L = d[p + 4]
            nm_end = p + 4 + L                      # == p_le + 3 + n
            if (nm_end + 2 <= hi
                    and all(0x20 <= c < 0x7f for c in d[p + 17:nm_end])
                    and d[nm_end:nm_end + 2] == b"\x00\x00"):
                ev.append((p + 1, "FNREC", d[p + 17:nm_end].decode("ascii", "replace")))
                ctx.mark(p + 1, 4)                  # 00 00 00 L  -> L 00 00 00
                ctx.mark(p + 13, 4)                 # 00 00 00 01 -> 01 00 00 00
                return p + 6 + L                    # == p_le + 5 + n
        # v0x13 ORPHAN18 tails (BE mirror of the keyg_walker2 rule): detached
        # count-2 GUID-pair entries after a SLOTGUIDREF head.  LONG 15B
        # [00][u32be 0x18][u32be 0][01][00][u32be ref], SHORT 10B
        # [00][u32be 0x18][00][u32be ref] -> CNTW(0x18)+BAREREF(ref) glue.
        # Context-gated (see keyg_walker2._orphan18_ctx): the LONG form is
        # byte-identical to a genuine kid-24 keyed OBJREF.
        if d[p + 1:p + 5] == b"\x00\x00\x00\x18" and _orphan18_be_ctx(ev, d):
            if d[p + 5:p + 9] == b"\x00\x00\x00\x00" and d[p + 9] == 1 \
                    and d[p + 10] == 0 and 0 < _u32(d, p + 11) <= SLOT_MAX_ID:
                ev.append((p + 1, "CNTW", 0x18))
                ev.append((p + 11, "BAREREF", _u32(d, p + 11)))
                ctx.mark(p + 1, 4); ctx.mark(p + 11, 4)
                return p + 15
            if d[p + 5] == 0 and 0 < _u32(d, p + 6) <= SLOT_MAX_ID:
                ev.append((p + 1, "CNTW", 0x18))
                ev.append((p + 6, "BAREREF", _u32(d, p + 6)))
                ctx.mark(p + 1, 4); ctx.mark(p + 6, 4)
                return p + 10
        # orphaned count-2 GUID entry-2 (v0x16 dialect): [00][u32be 0x18][01]
        # [00][u32be ref][11B trailer] — the pair's second entry detached from
        # its [01 02 ... 0x18] head by an interleaved keyed OBJREF record.
        # Swapping tagword + ref makes the untouched LE walker read CNTW +
        # BAREREF glue (LINKBOX +1); the trailer's w word is handled by the
        # loose-trailer branch on the next step.  6 sites; @0x101752 alone
        # gates out the 7th sequence 'miroslav et Trad'.
        if (d[p + 1:p + 7] == b"\x00\x00\x00\x18\x01\x00" and p + 22 <= hi
                and _u32(d, p + 7) <= SLOT_MAX_ID
                and d[p + 11:p + 13] == b"\x01\x01"):
            ev.append((p + 1, "CNTW", 0x18))
            ev.append((p + 5, "BAREREF", _u32(d, p + 7)))
            ctx.mark(p + 1, 4); ctx.mark(p + 7, 4)
            return p + 11
        # keyed EXTRA-BYTE form (v0x16): [00][u32be kid][00][u32be tagword]
        # [value] with tag 0x02|0x05 — must run BEFORE NKEY form 1, whose
        # kid+pads gate misreads this shape as an OBJ-valued key (junk OBJREF
        # overshoots into the next record; sheared apresModifs' audm tracks)
        if p + 11 <= hi and d[p + 5] == 0 and d[p + 6:p + 9] == b"\x00\x00\x00" \
                and d[p + 9] in (0x02, 0x05) and d[p + 10] <= 1:
            kid = _u32(d, p + 1)
            if 0 < kid <= SLOT_MAX_ID and kid & 0xff:
                ev.append((p0, "NKEY", kid)); ctx.mark(p + 1, 4)
                return _value(d, p + 6, ev, hi, ctx)
        # v0x14 zero-led OBJSLOTREF (sid=0): a slot ref whose [01] marker is the
        # LOW byte of the BE word [00 00 00 01] (not a bare [01] like the d[p]==1
        # form).  Bytes [00 00 00 01][00][00][mk<=1][u32le w]: the bare-numeric
        # NKEY(1) mirror below marks(p,4) to swap the head [00 00 00 01] ->
        # [01 00 00 00], which is exactly what the LE walker reads as glue-R3
        # OBJSLOTREF(0, w) (sid=0 because the swapped head leaves the sid word
        # all-zero; w stays raw = u32le).  But that mirror then reads the value
        # as NKEY(1)+OBJREF(0), taking the w word's high byte (0x75) as the OBJ
        # alloc count and over-running to 14 B instead of the true 11 B — landing
        # mid-word on the next member's kid low byte, where the mirror can no
        # longer re-engage and the following keyed FOURCC ('final') desyncs into
        # a runaway (collapse @0x5bc715).  Consume exactly 11 B so the mirror
        # stays in lockstep with the LE walker.  Disambiguated from a genuine
        # NKEY(1)->OBJ by d[p+8] > 1 (an OBJ's alloc/marker byte there is 0 or 1;
        # here it is the w word's high-ish byte).  Version-gated to 0x14 so it
        # cannot fire on Aaron v0x13 / MUSEO v0x16 / anika v0x17.
        if (d[0x2e] == 1 and _u32(d, 0x2f) == 0x14 and p + 11 <= hi
                and d[p + 1] == 0 and d[p + 2] == 0 and d[p + 3] == 1
                and d[p + 4] == 0 and d[p + 5] == 0 and d[p + 6] <= 1
                and d[p + 8] > 1):
            # keyed-member misframe guard: these bytes are actually an NKEY
            # form-1 with a LOW-BYTE-0 kid (0x__00) carrying a valid value
            # tagword [00 00 00 <tag>], NOT a slot ref.  Rat King (v0x14)
            # serializes a `NKEY 0x100, BOOL 0` member here inside every
            # clip/generator effect-param dict's GUIDREF-GUIDREF triple; the
            # sid=0 OBJSLOTREF misread dropped it from the enclosing dict's
            # count, so the clip DICT ran one entry short and absorbed the next
            # sibling clip -- Titles video track 1's 7 clips collapsed into 1
            # and audm was severed (0 audio tracks).  The genuine zero-led
            # OBJSLOTREF (RESP 534 lesson) carries w's high byte (0x75) at p+8,
            # never a value tag, so the tag gate leaves it untouched.  NKEY(kid)
            # + BOOL consumes the same 11 B, keeping the mirror in lockstep.
            kid = _u32(d, p + 1)
            t8 = d[p + 8]
            if (d[p + 6] == 0 and d[p + 7] == 0 and kid & 0xff == 0
                    and (kid >> 8) & 0xff and 0 < kid <= SLOT_MAX_ID
                    and (t8 in SLOT_TAGS or t8 in FIXED_TAGS
                         or t8 in (0x0c, 0x20, 0x10, 0x16, 0x06))
                    and _value_extent_sane(d, p + 5, hi)):
                ev.append((p0, "NKEY", kid)); ctx.mark(p + 1, 4)
                return _value(d, p + 5, ev, hi, ctx)
            w = struct.unpack_from("<I", d, p + 7)[0]
            # the next record is a BE bare-numeric keyed member [u32be kid]
            # [tag<0x30][00 00 00]; plausible_record_start's BE mirror only knows
            # the leading-marker form, so accept either here.
            nxt = p + 11
            nxt_ok = (plausible_record_start(d, nxt, hi)
                      or (nxt + 8 <= hi and 0 < _u32(d, nxt) <= SLOT_MAX_ID
                          and d[nxt + 4:nxt + 7] == b"\x00\x00\x00" and d[nxt + 7] < 0x30))
            if w <= (0x10000 if d[p + 6] else SLOT_MAX_ID) and nxt_ok:
                ev.append((p0, "OBJSLOTINL" if d[p + 6] else "OBJSLOTREF", 0, w))
                ctx.mark(p, 4)          # 00 00 00 01 -> 01 00 00 00 (head)
                return p + 11
        # NKEY form 1: [00][u32be kid][u32be tagword] (kid low byte nonzero)
        if p + 9 <= hi:
            kid = _u32(d, p + 1)
            t = d[p + 8]
            if (0 < kid <= SLOT_MAX_ID and kid & 0xff
                    and d[p + 5:p + 8] == b"\x00\x00\x00"
                    and (t in SLOT_TAGS or t in FIXED_TAGS
                         or t in (0x0c, 0x20, 0x10, 0x16, 0x06) or _is_kfblob_be(d, p + 5))):
                # [pads][FILESPEC] masquerade: the 01 marker is the kid word's
                # low byte at p+4 (mirror of the LE walker's guard)
                if _value_extent_sane(d, p + 5, hi) and not (
                        kid & 0xff == 1 and d[p + 4] == 1 and try_filespec(d, p + 4, hi)):
                    ev.append((p0, "NKEY", kid)); ctx.mark(p + 1, 4)
                    return _value(d, p + 5, ev, hi, ctx)
        # NKEY form 2 (merged low-byte-0 kid): [u32be kid&0xff==0][u32be tagword]
        if p + 8 <= hi:
            kid = _u32(d, p)
            t = d[p + 7]
            if (0 < kid <= SLOT_MAX_ID and kid & 0xff == 0 and (kid >> 8) & 0xff
                    and d[p + 4:p + 7] == b"\x00\x00\x00"
                    and (t in SLOT_TAGS or t in FIXED_TAGS or t in (0x0c, 0x10, 0x16, 0x06))
                    and _value_extent_sane(d, p + 4, hi)):
                ev.append((p0, "NKEY", kid)); ctx.mark(p, 4)
                return _value(d, p + 4, ev, hi, ctx)
        # bare numeric key, marker eaten: [u32be kid][u32be tagword]
        if p + 8 <= hi:
            kid = _u32(d, p)
            t = d[p + 7]
            if (0 < kid <= SLOT_MAX_ID and kid & 0xff
                    and d[p + 4:p + 7] == b"\x00\x00\x00"
                    and (t in SLOT_TAGS or t in FIXED_TAGS or t in (0x0c, 0x20, 0x10, 0x16, 0x06))):
                if _value_extent_sane(d, p + 4, hi) and not (
                        kid & 0xff == 1 and d[p + 3] == 1 and try_filespec(d, p + 3, hi)):
                    ev.append((p0, "NKEY", kid)); ctx.mark(p, 4)
                    return _value(d, p + 4, ev, hi, ctx)
        # bare member-count word CNTW: [00 00 00 v] (LE last-resort form)
        if (d[p + 1] == 0 and d[p + 2] == 0 and d[p + 3]
                and plausible_record_start(d, p + 4, hi)):
            ev.append((p0, "CNTW", _u32(d, p))); ctx.mark(p, 4); return p + 4
        return None     # plain zero skip et al: LE fallback decides
    # --- DEF (endian-invariant bytes; the value dispatch is the mirror) -----
    n = d[p]
    if _LE.try_fnrec(d, p, hi) is not None:
        return None     # managed-dialect FNREC: raw construct, LE fallback
    if (0 < n <= 80 and p + 1 + n <= hi
            and all(0x20 <= c < 0x7f for c in d[p + 1:p + 1 + n])
            and _value_extent_sane(d, p + 1 + n, hi)):
        ev.append((p0, "DEF", d[p + 1:p + 1 + n].decode()))
        return _value(d, p + 1 + n, ev, hi, ctx)
    return None


def tokenize(d, lo, hi, ctx, guard_max=50_000_000):
    """BE tokenizer: mirror cascade first, LE-raw single-step fallback else."""
    p, ev, guard = lo, [], 0
    while p < hi and guard < guard_max:
        guard += 1
        prev_raw = (bool(ev) and ev[-1][1] == "RAW" and ev[-1][0] >= p - 4
                    and p != ctx.clean_from)
        q = _mirror_step(d, p, hi, ev, ctx, prev_raw)
        if q is None:
            q = _le_step(d, p, hi, ev, ctx)
        if q <= p:
            ev.append((p, "RAW", d[p])); q = p + 1     # safety: always advance
        p = q
    return ev


def _array_elem_events(d, e, hi, ctx):
    """Mirror of keyg_walker2._array_elem_events (fix 3).  Arrays framed by
    the LE fallback re-walk with the LE reader (their bytes stay raw)."""
    flag_le = e[0] in ctx.raw_arrays
    out = []
    q = e[0] + 13
    junk: list = []
    for _ in range(e[3]):
        if flag_le:
            r = _LE._flagged(d, q, hi)
        else:
            r = _flagged(d, q, hi, junk)
        if r is None:
            break
        q, sub = r[0], r[1]
        if sub[0] == "STRINL":
            out.append((q, "ASTRINL", sub[1] if e[2] == 0x1f else None))
        else:
            out.append((q, "AREF", sub[1]))
    return out


def tokenize_scoped(d, lo, hi, ctx):
    """Mirror of keyg_walker2.tokenize_scoped (scope relabel + array element
    events + G10 trailer relabel — pure event-level post-pass)."""
    ev = tokenize(d, lo, hi, ctx)
    in_scope = False
    out = []
    for i, e in enumerate(ev):
        k = e[1]
        if k == "DEF":
            nm = e[2]
            if not in_scope and nm in _LE.SCOPE_OPEN_KEYS and _LE._has_undo_dict(ev, i):
                in_scope = True
            elif in_scope and nm in _LE.SCOPE_CLOSE_KEYS:
                in_scope = False
        if in_scope and k in _LE.SUPPRESS_KINDS:
            out.append((e[0], k + "_S") + tuple(e[2:]))
        else:
            out.append(e)
        if k == "ARRAY" and e[2] in _LE.ARRAY_FLAGGED_ETS:
            out.extend(_array_elem_events(d, e, hi, ctx))
        if k == "OBJSLOTREF" and i > 0 and ev[i - 1][1] == "G10INL" \
                and e[0] == ev[i - 1][0] + 27 and e[2] == 1 and e[3] == 1:
            out[-1] = (e[0], "G10TRAILER") + tuple(e[2:])
    return out


# --------------------------------------------------------------------------
# Swab driver
# --------------------------------------------------------------------------

def is_big_endian(head: bytes) -> bool:
    """True iff the buffer starts a big-endian (PowerPC) KeyGrip file:
    magic + byte-order flag 0x00 at offset 8 (Intel files carry 0x01)."""
    return len(head) > 8 and head[:8] == MAGIC and head[8] == 0x00


def _swab_header(buf: bytearray) -> None:
    """Hand-coded header swab, 0x00-0x2d (swap_spec section 1).  The stream
    version [u8 01][u32]@0x2e is INSIDE the tokenized region (PTOK)."""
    buf[0x08] = 0x01                                  # byte-order flag
    buf[0x09:0x0d] = buf[0x09:0x0d][::-1]             # u32 build/format counter
    buf[0x0d:0x11] = buf[0x0d:0x11][::-1]             # format GUID data1
    buf[0x11:0x13] = buf[0x11:0x13][::-1]             # GUID data2
    buf[0x13:0x15] = buf[0x13:0x15][::-1]             # GUID data3
    buf[0x1d:0x21] = buf[0x1d:0x21][::-1]             # u32 = 3
    # 0x15-0x1c GUID data4, 0x21-0x2d zeros/u8: byte-identical


def _norm_event(e):
    """Comparable event tuple; floats -> their little-endian bit patterns so
    NaN payloads compare exactly (involution is bit-level, not float-level)."""
    out = [e[0], e[1]]
    for v in e[2:]:
        if isinstance(v, float):
            v = struct.pack("<d", v)
        out.append(v)
    return tuple(out)


def _diff_splice(ev_be, ev_le, hi):
    """Diff the two scoped streams event-for-event.  Where they diverge, find
    the resync point by exact-event match and SPLICE the LE walker's events
    over the divergence (mirror policy for junk pockets — see swab_analysis).
    Returns (merged events, pocket byte ranges).  Raises if a divergence
    never resyncs (that is a transcoder bug, not a pocket)."""
    A = [_norm_event(e) for e in ev_be]
    B = [_norm_event(e) for e in ev_le]
    i = j = 0
    merged = []
    pockets = []
    while i < len(A) and j < len(B):
        if A[i] == B[j]:
            merged.append(ev_be[i])
            i += 1; j += 1
            continue
        start = min(A[i][0], B[j][0])
        amap = {A[k]: k for k in range(min(i + 8000, len(A)) - 1, i - 1, -1)}
        sync = None
        for k in range(j, min(j + 8000, len(B))):
            m = amap.get(B[k])
            if m is not None:
                sync = (m, k)
                break
        if sync is None:
            raise AssertionError(
                f"involution divergence with no resync at 0x{start:x} "
                f"(BE {ev_be[i][:3]} vs LE {ev_le[j][:3]})")
        m, k = sync
        merged.extend(ev_le[j:k])
        pockets.append((start, A[m][0]))
        i, j = m, k
    if i < len(A) or j < len(B):
        # tail imbalance: adopt the LE tail (same rule as interior splices)
        start = ev_be[i][0] if i < len(A) else ev_le[j][0]
        merged.extend(ev_le[j:])
        pockets.append((start, hi))
    return merged, pockets


def _apply_spans(data: bytes, spans: dict, lo: int, pokes: dict | None = None) -> bytes:
    buf = bytearray(data)
    _swab_header(buf)
    last_end = 0
    for off in sorted(spans):
        w = spans[off]
        if off < last_end:
            raise AssertionError(f"overlapping swap spans at 0x{off:x}")
        if off < lo or off + w > len(data):
            raise AssertionError(f"span out of range: 0x{off:x}+{w}")
        buf[off:off + w] = buf[off:off + w][::-1]
        last_end = off + w
    # literal-byte fixups (applied after the reversals; must not overlap a span)
    for off, val in (pokes or {}).items():
        if off < lo or off + len(val) > len(data):
            raise AssertionError(f"poke out of range: 0x{off:x}+{len(val)}")
        buf[off:off + len(val)] = val
    return bytes(buf)


def swab_analysis(data: bytes, lo: int = 0x2e, hi: int | None = None):
    """Full walk + swab + involution closure.

    Walk the BE stream (mirror cascade + LE fallback), apply the recorded
    spans, then run the UNTOUCHED keyg_walker2.tokenize_scoped on the swabbed
    bytes and diff the two scoped event streams.  Divergences are confined to
    junk pockets (version-0x16-only constructs neither dialect's LE grammar
    can represent): there the LE walker's own events are adopted (MIRROR
    policy — recon flagged mask-vs-mirror as this session's decision; the
    mask/keep-raw alternative was tried and measured strictly worse, because
    keyg_walker2's unbounded junk length reads can swallow real records when
    fed raw big-endian pockets, while the mirror swab keeps it aligned with
    small, always-resyncing hiccups).  Every pocket is bounded by exact-event
    resync points and recorded in ctx.pockets; outside pockets the streams
    are verified identical event-for-event.

    Returns (swabbed bytes, scoped BE events == LE events, Ctx).
    """
    if not is_big_endian(data):
        raise ValueError("not a big-endian KeyGrip file (magic/flag byte 0x08)")
    # forged-magic junk gate: a real stream carries the version token
    # [01][u32be ver] at 0x2e (MUSEO: 0x16; Intel files: 0x13..0x15 as u32le)
    if len(data) < 0x2e + 16 + 5 or data[0x2e] != 0x01 \
            or not (1 <= _u32(data, 0x2f) <= 0x40):
        raise ValueError("not a KeyGrip stream (missing/invalid version token)")
    if hi is None:
        hi = len(data) - 16          # the pipeline's own read margin
    ctx = Ctx()
    ev = tokenize_scoped(data, lo, hi, ctx)
    out = _apply_spans(data, ctx.spans, lo, ctx.pokes)
    ev_le = _LE.tokenize_scoped(out, lo, hi)
    merged, pockets = _diff_splice(ev, ev_le, hi)
    ctx.pockets.extend((s, e, "junk pocket: LE-walk events adopted (resynced)")
                       for s, e in pockets)
    if merged and hi - merged[-1][0] > 8192:
        raise AssertionError(
            f"coverage collapse: last event at 0x{merged[-1][0]:x} vs hi 0x{hi:x}")
    return out, merged, ctx


def swab_bytes(data: bytes) -> bytes:
    """Transcode a big-endian KeyGrip buffer to little-endian byte order.
    Widths are preserved: len(out) == len(data) and every event offset is
    unchanged (the involution requirement)."""
    out, _ev, _ctx = swab_analysis(data)
    return out


def swab_file(src, dst) -> None:
    data = Path(src).read_bytes()
    Path(dst).write_bytes(swab_bytes(data))


def _main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python3 -m orchestrator.keyg_swab src.fcp dst.fcp", file=sys.stderr)
        return 2
    src, dst = argv
    data = Path(src).read_bytes()
    if not is_big_endian(data):
        print(f"{src}: not a big-endian KeyGrip file (nothing to do)", file=sys.stderr)
        return 1
    out, ev, ctx = swab_analysis(data)
    Path(dst).write_bytes(out)
    raw = sum(1 for e in ev if e[1] == "RAW")
    print(f"{src} -> {dst}: {len(out)} bytes, {len(ev)} events, "
          f"{len(ctx.spans)} swap spans, {raw} RAW events, {len(ctx.pockets)} pockets")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
