#!/usr/bin/env python3
"""KeyGrip (.fcp) EOF walker — tokenizer + object/intern table
(SESSION 9 VARIANT of orchestrator/keyg_walker3.py: + R19 CLSNAME + R20
 PTOK32ARR + R21 PTOKUUIDHDR — the multi_one.fcp T20-multiclip/clipList
 pocket credits. tokenize()/tokenize_scoped() are byte-identical to
 keyg_walker2/3 — allocation layer only.)

SESSION-9 gate numbers (2026-07, multiclip-oracle session; all re-measured):
  spans vs findings/report_d/keyg_intern_targets_v3.json: UNCHANGED
    palastin 384/385 local-exact, uniqueID +12; mc_two 100/100 drift 0
    (R19/R20/R21 have ZERO sites in palastin/mc_*/1.fcp/dup_one/gen_one —
     they fire only inside tokenizer RAW pockets, which exist only in
     multi_one.fcp; verified by census)
  gap.py 1.000 on all nine banked corpora (palastin 430/430, mc_one..four
    210/212/210/210, 1.fcp 57, dup_one 210, gen_one 245); multi_one (new,
    NOT banked) 213/217 — the 4 fails are the T20-multiclip class body and
    clipList registry byte pockets (tokenize() deliberately untouched)
  gateb7 --registry: 1029/1029 recall, precision 0.899 (identical to kw3)
  oracle refs: mc_one..four UUIDREF 4/7/10/13 all exact, STRREF 5/5 x4;
    dup_one 13/13 + 15/15; gen_one 7/7 + 7/7 (all identical to kw3)
  multi_one strict-pin ledger under THIS module: D=0 through 0xeb9, then a
    documented +4 EOF residual composed of EXACTLY five missing fresh-record
    stubs (ids 185 'bars', 263 multiclip, 308 'clip', 619 clipList entry,
    621 OTAG-form multiclip clipitem) minus one phantom (the multiclip
    record's nested angle clipitem member, bracketed to the k29..k66 member
    run 0x1b9e..0x1dae). See probe/bc session notes: the stub mechanism is
    byte-proven (self-ref topology r==s with gs==s+2 / OTAG refs==head+1)
    but is NOT banked as a rule because the copy-form (r==s-1, gs==s+1)
    reads identically under model ids in any D=-1 drift region (palastin
    0x5f0xxx family) — firing it safely requires family-B closure first.

SESSION-8 gate numbers (2026-07, tree-ancestry session; all re-measured):
  spans vs findings/report_d/keyg_intern_targets_v3.json:
    palastin 384/385 local-exact (was 383/385) — itemRender EXACT via R18;
      last bad span: uniqueID +12 (was +37) via R17
    mc_two 100/100, drift 0 (unchanged)
  gap.py 1.000: palastin 430/430, mc_one/two/three/four 210/212/210/210,
    1.fcp 57, dup_one 210, gen_one 245 — RAW=0 on all eight corpora
  mc oracles: STRREF 5/5 x4; UUIDREF 4/4, 7/7, 10/10, 13/13;
    dup_one STRREF 15/15 UUIDREF 13/13; gen_one 7/7 + 7/7 (both new
    FCP-oracle corpora walk zero-drift under this module)
  GATE B distinct names: 1029/1029 recall incl. registry (precision 0.899);
    main-doc 740/1029 (was 735) @ precision 0.933 (was 0.930)
  grouper gates (session-8 g3/grp/gates.py with this walker): GATE A 22/22,
    GATE B 3852/3852, positional names 3696/3852 (was 3671)
  backbone ledger: uniqueID-span nonzero windows 42 -> 17 (net +37 -> +12);
    itemRender/pre/mid regions fully clean
R17/R18 fire at exactly 25+1 palastin sites and NOWHERE else in any corpus
(mc_one..four, 1.fcp, dup_one, gen_one: zero allocation diffs vs keyg_walker2
except via rule R12 which is unchanged).

(SESSION 7 FINAL MERGE below: R13 PTOKBOX + R14 UUIDHEAD + R15 T0CSHAPE + R12-G10 gate
 + R10b megaslot-everywhere + R16 boxlist + R15 T0C SHAPE WEIGHTS).

Drop-in replacement for orchestrator/keyg_walker2.py (same public signatures:
tokenize / tokenize_scoped / final_allocs / object_table / key_ids).

Gate numbers (this module, 2026-07-07, win7/kww.py):
  gap.py 1.000 on palastin(430/430) + mc_one(210) mc_two(212) mc_three(210)
  mc_four(210) + 1.fcp(57); RAW=0 (tokenize byte-identical to dedup/kwm.py).
  Spans vs findings/report_c/keyg_intern_targets_corrected.json:
    palastin 383/385 local-exact, end-drift -168
      (residuals: itemRender -1, uniqueID -167; browser_opensequence FIXED)
    mc_two 98/100, end-drift 0 (canClip -1 / cType +1 are byte-proven
      target-mining artifacts: both ids carry "interval[...] forced" evidence,
      i.e. interpolated, and every independently mined target is delta-0;
      all 5 STRREF + 7 UUIDREF oracles resolve exactly under the prediction).
  mc_one..four: STRREF 5/5, UUIDREF 4/4 / 7/7 / 10/10 / 13/13, name-slots 4/4.
  Alloc diff vs dedup/kwm.py (byte-audited): palastin 662 sites exactly
  (243 T0C 0->1 = MEDrefs wrongly radius-suppressed by legacy R6;
   418 T0C 1->0 = 340 RENDref + 78 SEref; 1 OBJREF = the R12 0xcc8916
   drift-coincidence); mc_one..four + 1.fcp: ZERO diffs.
  NOTE on uniqueID -167 (was +16): the OLD +16 was ~+175 of T0C shape
  over-credits accidentally canceling ~-160 of true under-credit pockets
  (-7@0x4d605a -21@0x4db81c -13@0x4fa27f -18@0x4fab35 -16@0x526623
   -20@0x62f6d9 -17@0x6b67f3 -17@0x8c977c -19@0x9d74e4 -20@0xb82711
   -7@0xba6dd5 -17@0xc0aa28 + smaller), plus a ~32-window +1 over-credit
  class. R15 removes the masking; the pockets are now the dominant open
  construct (they sit ONLY inside the uniqueID span + the target-less deep
  tail past 0xcc39b2, which degrades to D=-448 by 0xde3058).

Layers:
  tokenize()        exact byte framing — byte-identical to session-6 kw2x
                    (+ the OBJEMPTY empty-object form); gap.py is provably
                    unaffected by everything below.
  tokenize_scoped() + itemHistory undo-scope relabel, typed-array element
                    events, GUID-trailer handling.
  final_allocs()    per-event object-table credits: session-6 rules R1-R6 +
                    session-7 merged rules (see the R_* toggles below and the
                    inline evidence at each rule).
  object_table()    index -> (kind, value); resolves STRREF/OBJREF/UUIDREF.

Session-7 merged rules (all allocation-layer post-passes):
  OBJEMPTY +1       keyed [00][pad3][a=0][mk=0] with no ref word interns an
                    empty object (7 palastin sites).
  R7  R_NULLOBJ     OBJREF with ref word 0, ONLY as composite member
                    ([...OBJINL][ARRAY(5)][PTOK][NKEY] context): +1. 43/51
                    palastin instances; count==residual in 8 spans (incl.
                    browser_viewcode 19, editedVideo 10). The other 8
                    instances (still-record context [F64 3000.0][VAL32(3)]
                    [NKEY(4)]) allocate 0 — proven by uuid-selfref drift
                    curves (url span) + the stillFrameOffset exact zero.
  R8  R_SLOTGUIDINL2 count-less slot-form GUID allocates 2 (no class slot);
                    1/1 instance (@0x38607d), zeroes sequenceDict.
  R9  R_KFBLOB      keyframe blob: +1 per 15-byte BLOB_UNIT; 12/12 instances,
                    zeroes bin_count and categoryname exactly.
  R10 R_MEGASLOT    SLOT(1,1,256) mega-slot interior credit via interior
                    re-tokenization (main-scope instance only; 11 instances,
                    zeroes the flop -32 span together with R11).
  R11 R_MASTERSTUB  master-clip stub [GUIDREF][OTAGOBJ][NKEY name][STRINL]
                    with its OWN FILESPEC in the same record run: +1.
                    187 palastin sites; zeroes 13 spans; per-site TRUE-ness
                    verified by the stub self-reference oracle (the GUIDREF
                    right after the name string targets the stub's own slot:
                    step +0 across every fresh site in opacity/url/uniqueID).
  R12 R_SEQDICT     sequence mainDict self-ref stub: [NKEY|DEF][OBJREF r]
                    right after an allocated OBJSLOTREF pair (slots s,s+1)
                    with r==s and double GUIDREF->r+2: +1 (id-topology,
                    subsumes the name-gated clipTop rule). Session 7c adds
                    the G10INL-head gate (an inline tag-0x10 GUID within 14
                    events before the OBJREF): the id-topology compares FILE
                    refs against MODEL cum ids and thus matches by
                    coincidence in drifted regions (R15 moved the match
                    0xcc8916 -> 0x496b80, +1-breaking the exact
                    renderSettings..categoryname span). Gated sites: exactly
                    the 4 oracle-proven mc sites (mc_one 0x1962, mc_two
                    0x1d35, mc_three 0x1fc0, mc_four 0x22ef — repairing each
                    corpus's single failing UUIDREF) + pal 0x81e2
                    (browser_viewer_location).

  R14 R_UUIDHEAD    the copy-vs-fresh master-stub discriminator (session 7b):
                    an R5-form site ([STRINL name][GUIDREF class][OTAGOBJ])
                    whose record HEAD carries an inline uuid member
                    ([OBJINL][DICT][NKEY 58][UUID ...]) is a re-serialized
                    clip snapshot and allocates NO stub. 61/61 palastin
                    sites byte-proven wrong by the backbone self-ref oracle
                    (see _uuid_headed docstring); exact spans contain zero
                    such sites; end-drift +69 -> +7.

  R15 R_T0CSHAPE    shape-based 'file'-T0C weights (session 7c), REPLACING
                    the legacy R6 MooV-radius suppression:
                      RENDref = the T0C under key 'file' inside an
                        [OBJINL][DICT 7] itemRender dict whose other members
                        read (INT,F64,F64,F64,F64,BOOL)  -> allocates 0
                        (395 palastin sites; the INLINE render-file form,
                        next member 'reader'+FOURCC, stays 1; 161 sites);
                      SEref = the f00 (double-ref) T0C inside an
                        [OBJINL1][DICT 10|11] start/end dict (registry
                        subclip window spec: start F64, end F64, file ref)
                        -> allocates 0 (1324 palastin sites);
                      every other T0C -> 1 (media ref & inline, waveCache,
                        render-inline; f00 or f11 alike).
                    Proof: the backbone ledger decomposes into 3882
                    between-record windows; tabulating T0C shapes against
                    the exact window gaps solves the weights with ZERO free
                    parameters — 3830/3882 windows read exactly 0 under R15
                    (the +-1 staircases 0x442002../0x446f55../0x7d2855../
                    0x9da2f7.. and the +55 catch-up 0x719162..0x741295 all
                    collapse: the +55 was 54 SEref sites the R6 radius
                    missed + 1 RENDref). The uuid-less stub sites 0x442932 /
                    0x59b1ad / 0x6cd645 / 0x9dd930 that read WRONG inside
                    the staircase noise now read CORRECT (stub labels:
                    236 CORRECT, 1 WRONG @0x7d71a0, 1 AMBIG-2 @0x3e26e2 =
                    the known missing 'Texte' stub). Only the two bad spans
                    move (browser_opensequence +8 -> exact, uniqueID -183);
                    R15 sites in mc_*/1.fcp: ZERO.
                    Legacy R6 kept under R_T0CMOOV=False: its radius rule
                    was RIGHT on SEref/RENDref near MooV entries and WRONG
                    everywhere else (243 wrong suppressions, 418 misses).

BACKBONE SELF-REF ORACLE (the session-7b measuring instrument): clip/master
records repeat one GUIDREF X (>=3x, after scene/take/comment members); in
mc_three/mc_four (zero drift) X == the OTAGOBJ's own table id, byte-exact,
and the palastin records are field-identical by key NAME. So D = pred - X is
an exact LOCAL drift reading at each of 5764 palastin records: D == 0 across
every exact span; a CORRECT credited stub reads D = drift-1 (stub slot
precedes the object id); a WRONG one reads D = drift and the next record
reads +1. The full ledger (probe/dedup/curve_all.txt) exposes the residual
non-stub noise: big model UNDER-credits at 0x4d605a(-7) 0x4db81c(-21)
0x4fa27f(-13) 0x4fab35(-18) 0x526623(-16), a +55 catch-up inside
0x719162..0x741295, and +-1 staircases (browser span 0x442002../0x446f55..,
0x7d2855..0x7ddc19, registry tail 0x9da2f7..) — none of them master-stub
sites.

Honest residuals (palastin): itemRender -1 — byte-localized to the 'Texte'
generator-master OTAGOBJ @0x3e0f6d: the record's own forward refs
(backbone GUIDREF 53731 == pred+1, orphan UUIDREF 53732 vs model uuid id
53731) prove ITS stub is missing. Session-7c census: the generator-master
form ([NKEY 99 alphatype][INT][NKEY 33 name][STRREF][GUIDREF 35][OTAGOBJ],
members itemspec/UUID-inline/masterClips-orphan-selfref/isMaster=0) occurs
at EXACTLY 3 sites in palastin: 0x3e0f6d (Texte, main doc), 0x841a3b and
0x8e5473 (registry tail). The two tail twins byte-read the OPPOSITE
direction (ledger brackets: drift -109 -> object D -108, -123 -> -122,
i.e. +1 over-credit windows, no missing stub), so "generator master =>
stub" is FALSIFIED as a global rule at n=3 and the brief's R11
effect-source-gate idea (itemspec/scriptid member, no FILESPEC) fires at
all 3 sites => same collateral; negative set clean (0/3512 STRREF-named
ledger sites match the form). Texte's stub license remains UNFOUND — left
uncredited. uniqueID -167: the under-credit pockets + a ~32-window +1
over-credit class (discriminator unfound; tested & refuted: same-(w1,w2)
T0C pairs, w2-w1==29 spacing, media-dict presence, orphan-uuid-inline,
end-site stub wrongness) + the target-less deep tail past uniqueID.

Registry finding (session 7): the ~5786 name-slot STRREFs inside the
render-registry byte range resolve against the MAIN table, not per-entry
local tables: refs targeting the cumulative-exact id zone resolve 1967/1967
(100.0%); per-entry-local is impossible (median ref value 60167 vs median
entry-local alloc budget 2301; only 21/5786 refs would even fit). The MooV
sub-document that DOES restart scope lives inside the FILESPEC blob bytes and
is never tokenized.
"""
from __future__ import annotations
import struct
from pathlib import Path

ROOT_GUID = bytes.fromhex("aa20b6bf74cdd011aa34000502e85810")
_u32 = lambda d, o: struct.unpack_from("<I", d, o)[0]

# KFBLOB unit: the 15-byte record repeated inside the renderSettings / speed-segment
# keyframe blob (see sync2/scanblob.py: 12/12 instances in palastin).
BLOB_UNIT = bytes.fromhex("010100000000050000000000000000")


def is_kfblob(d: bytes, tp: int) -> bool:
    """tp = tag byte of a keyed value. True iff it starts the speed/render
    keyframe blob: [tag T][pad3][T x 0x01][0x00][BLOB_UNIT ...] (ones == tag)."""
    t = d[tp]
    if not (5 <= t <= 0x20) or d[tp + 1:tp + 4] != b"\x00\x00\x00":
        return False
    op = tp + 4
    return (d[op:op + t] == b"\x01" * t and d[op + t] == 0
            and d[op + t + 1:op + t + 16] == BLOB_UNIT)


def refarray_end(d: bytes, q: int, n: int, hi: int) -> int:
    """A PTOK(n)-headed ref-array (effect keyframe/point ref-list): the PTOK
    count word is immediately followed by a CNTW-shaped [18 00 00 00] tag and
    then exactly `n` units of [00][u32le ref (a valid slot id)][18 00 00 00],
    the LAST unit's trailing 0x18 tag being dropped (a bare [00][u32 ref]).
    `q` points at the CNTW tag (== the PTOK site + 5).  Returns the byte offset
    just past the array iff all n units validate, else None.

    Parsed unit-by-unit the walker instead reads each pair of 9-byte units as
    one NKEY(bigid)+BLOBREF, and those phantom keyed members drain the enclosing
    channel DICT (Rat King: vidm closes n/2 members early, orphaning the intact
    audm).  Consumed whole, the array is one glue token = zero dict members.
    The all-units-validate gate makes the shape near-impossible to hit by
    accident (verified 0 fires on every gated corpus)."""
    if n < 2 or q + 4 > hi or d[q:q + 4] != b"\x18\x00\x00\x00":
        return None
    r = q + 4
    cnt = 0
    while cnt < n:
        if r + 5 > hi or d[r] != 0:
            break
        ref = _u32(d, r + 1)
        if not (0 < ref <= SLOT_MAX_ID):
            break
        r += 5
        if d[r:r + 4] == b"\x18\x00\x00\x00":   # full unit; last unit omits it
            r += 4
        cnt += 1
    return r if cnt == n else None

FILESPEC_MAX_FIELDS = 16
FILESPEC_MAX_LEN = 0x40000
SLOT_MAX_ID = 0xFFFFF
SLOT_MAX_COUNT = 0x8000
SLOT_TAGS = {0x01, 0x03, 0x04, 0x05, 0x07, 0x0b, 0x1e, 0x1f, 0x23, 0x18, 0x21, 0x00}
# anika-2007 inline masterClip/captureSource class bytes (schema id at head off+5):
# 0x17 reel/capture-source master, 0x37 KGScriptParser, 0x66 generator master.
MASTER_CLS = frozenset((0x17, 0x37, 0x66))
# merge toggles (each gap-gated separately)
F_CTAGS_SIZES = True     # ctags element sizes (02:5 08:1 0f:9 12:5) over dictb's (4/0/8/4)
F_0C_TAIL = True         # 0x0c: 12B when second flag==0 (tail 00), else 11B
F_VAL32 = True           # anonymous value [flag][tag][pad3][u32 n][payloads] (tok3_d)
F_UUIDL = True           # long inline uuid [00 00 00 01][22 00 00 00][len][ascii]
F_FS_SNIFF = True        # FILESPEC: nf==5 + alias sniff + L==0 variant (tok4/census)
F_1E_REF = True          # 0x1e slot ref-element variant (6B elems when payload starts 00)
F_GLUE_G10 = True        # tag 0x10 GUID-shaped family (glue R1)
if F_CTAGS_SIZES:
    FIXED_TAGS = {0x02: 5, 0x08: 1, 0x0e: 8, 0x0f: 9, 0x11: 16, 0x12: 5}
else:
    FIXED_TAGS = {0x02: 4, 0x08: 0, 0x0e: 8, 0x0f: 8, 0x11: 16, 0x12: 4}
DICT_MAX_COUNT = 0x2000
# per-element sizes for typed arrays [u32 kind][u8][u32 elem-tag][u32 C][C x elem]
ARRAY_ELEM_SIZES = {0x03: 4, 0x04: 8, 0x05: 1, 0x1e: 8} | FIXED_TAGS
# A FIXED-tag ARRAY element omits the per-element flag byte the scalar FIXED form
# carries, so an et=0x0f element is 8 bytes, not the scalar's 9 (F_CTAGS_SIZES).
# Rat King master motion-curve arrays: a 101-element 0x0f array sized at 9 over-ran
# its payload by 101 bytes, so the walker RAW'd into the trailing floats, lost
# containment, and the clipitem ran away to EOF (video tracks 2-3 + audm severed).
ARRAY_ELEM_SIZES[0x0f] = 8


def try_dict_prelude(d: bytes, p: int, hi: int, ev: list, strict=False):
    """Inline-object DICT body prelude: [u32le 0][u8 Y in 0|1][u32le C],
    then C entries [00][u32le key][KEYED VALUE][00 pad] flow to the main loop.
    Only called right after an inline-object marker. Returns end or None.
    strict=True additionally validates the first entry's key/tag/pad3 shape
    (used where a false match would eat a real record, e.g. after bare 01)."""
    if p + 9 > hi or _u32(d, p) != 0 or d[p + 4] > 1:
        return None
    C = _u32(d, p + 5)
    if C > DICT_MAX_COUNT or (strict and C == 0):
        return None
    if C == 0:                          # empty dict: consume prelude only
        ev.append((p, "DICT", 0))
        return p + 9
    b = d[p + 9]
    if b == 0:                          # numeric entry [00][u32 key][tag][pad3]
        if strict:
            key = _u32(d, p + 10)
            if not (0 < key <= SLOT_MAX_ID):
                return None
            t = d[p + 14]
            if t not in SLOT_TAGS and t not in FIXED_TAGS and t not in (0x0c, 0x16, 0x06):
                return None
            if d[p + 15:p + 18] != b"\x00\x00\x00":
                return None
    elif 1 <= b <= 40:                  # named entry [u8 len][ascii][tag]...
        if not all(0x20 <= c < 0x7f for c in d[p + 10:p + 10 + b]):
            return None
    else:
        return None
    ev.append((p, "DICT", C))
    return p + 9


def plausible_record_start(d: bytes, p: int, hi: int) -> bool:
    for _ in range(12):     # tail pads of 4-8 zeros observed; 5 was too tight
        if p >= hi:
            return True
        b = d[p]
        if b == 0:
            if p + 5 <= hi and d[p + 1] and d[p + 2:p + 5] == b"\x00\x00\x00" and d[p + 5] < 0x30:
                return True
            # multi-byte numeric key: [00][u32 kid][tag<0x30][pad3]
            if (p + 9 <= hi and d[p + 1] and _u32(d, p + 1) <= SLOT_MAX_ID
                    and d[p + 5] < 0x30 and d[p + 6:p + 9] == b"\x00\x00\x00"):
                return True
            p += 1
            continue
        if b == 1:
            return True
        if 2 <= b <= 40 and p + 1 + b <= hi and all(0x20 <= c < 0x7f for c in d[p + 1:p + 1 + b]):
            return True
        return False
    return False


_u16be = lambda d, o: struct.unpack_from(">H", d, o)[0]


def try_filespec(d: bytes, p: int, hi: int):
    if d[p] != 1 or p + 5 > hi:
        return None
    nf = _u32(d, p + 1)
    if F_FS_SNIFF:
        # census-proven form: nf == 5 always; blk0 = Mac Alias (u16be@+4 == L) or L==0
        if nf != 5 or p + 13 > hi:
            return None
        L = _u32(d, p + 5)
        if L > 0 and not (0x40 <= L < 0x8000 and p + 9 + L <= hi
                          and d[p + 9:p + 13] == b"\x00\x00\x00\x00" and _u16be(d, p + 13) == L):
            return None
    elif not (1 <= nf <= FILESPEC_MAX_FIELDS):
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
    if F_FS_SNIFF and _u32(d, p + 5) == 0:
        vol = spans[2]     # missing-file variant: demand printable volume name
        if not (0 < vol[1] < 0x100 and all(0x20 <= c < 0x7f for c in d[vol[0]:vol[0] + vol[1]])):
            return None
    if not plausible_record_start(d, q, hi):
        return None
    return q, nf, spans


def _flagged(d, p, hi, uuid=False):
    """One flagged payload at p: [01][inline...] or [00][u32le ref].
    Returns (end, event) or None if malformed."""
    if p >= hi:
        return None
    fl = d[p]
    if fl == 0:
        return p + 5, ("REF", _u32(d, p + 1))
    if fl != 1:
        return None
    if uuid:
        if d[p + 1:p + 5] != b"\x22\x00\x00\x00":
            return None
        ln = _u32(d, p + 5)
        if ln > 0x100:
            return None
        return p + 9 + ln, ("UUID", d[p + 9:p + 9 + ln].decode("ascii", "replace"))
    ln = _u32(d, p + 1)
    if ln > 0x400000 or p + 5 + ln > hi:
        return None
    return p + 5 + ln, ("STRINL", d[p + 5:p + 5 + ln].decode("utf-8", "replace"))


def try_named_array(d: bytes, p: int, hi: int, C: int):
    """Array of tag-0x20 elements: C x [01][u32 n][n ascii class name][body].
    Body length is class-specific; learn it from the spacing to the next
    element header, and reuse the mode for the final element. Returns end."""
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
    for k in range(C):
        e = elem_hdr(q)
        if e is None:
            return None
        if k == C - 1:
            if not blens:
                return None                     # single elem: length unlearnable
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
    return q if q <= hi else None


_SLOT_VALIDATE = True   # disabled during nested lookahead to bound recursion


def _slot_end_ok(d: bytes, q: int, hi: int) -> bool:
    """Killer validation (CONTEXT): the bytes after a slot must begin a valid
    record. plausible_record_start alone accepts a lone 0x01, which lets the
    11FCSpeedData mega-slot survive when its (wrong) end lands on a uuid's inline
    marker. So additionally tokenize a bounded window and reject if a RAW surfaces
    within ~32 bytes. Recursion is disabled inside (depth 1) to keep cost O(1)."""
    global _SLOT_VALIDATE
    if not plausible_record_start(d, q, hi):
        return False
    if q >= hi:
        return True
    _SLOT_VALIDATE = False
    try:
        sub = tokenize(d, q, min(q + 96, hi))
    finally:
        _SLOT_VALIDATE = True
    for e in sub:
        if e[0] - q > 32:
            break
        if e[1] == "RAW":
            return False
    return True


def try_slot(d: bytes, p: int, hi: int, ev: list):
    """SLOT RECORD [01][u32le id][tag][pad3][u32le count][count x payload].
    Emits events and returns end pos, or None (no mutation) if implausible."""
    if d[p] != 1 or p + 14 > hi:
        return None
    sid = _u32(d, p + 1)
    if sid > SLOT_MAX_ID:
        return None
    t = d[p + 5]
    if t not in SLOT_TAGS or d[p + 6:p + 9] != b"\x00\x00\x00":
        return None
    n = _u32(d, p + 9)
    if n > SLOT_MAX_COUNT:
        if t == 0x18 and d[p + 9] == 1:
            # count-less GUID slot (any sid): [01][sid][18][pad3] +
            # [01 01][16B GUID][11B trailer] | [01 00][u32 ref]
            if d[p + 10] == 1:
                ev.append((p, "SLOTGUIDINL", sid, d[p + 11:p + 27])); return p + 38
            if d[p + 10] == 0:
                ev.append((p, "SLOTGUIDREF", sid, _u32(d, p + 11))); return p + 15
        return None
    q = p + 13
    out = [(p, "SLOT", sid, t, n)]
    if t in (0x01, 0x03): q += 4 * n
    elif t == 0x04: q += 8 * n
    elif t == 0x05: q += 1 * n
    elif t == 0x1e:
        if F_1E_REF and n and q < hi and d[q] == 0:
            q += 6 * n                    # ref-element variant [00][flag][u32le ref]
        else:
            q += 8 * n
    elif t in (0x1f, 0x07, 0x21, 0x0b):
        for _ in range(n):
            r = _flagged(d, q, hi)
            if r is None:
                return None
            q, e = r
            out.append((q, "S" + e[0], e[1]))
    elif t == 0x23:
        for _ in range(n):
            r = _flagged(d, q, hi, uuid=True)
            if r is None:
                return None
            q, e = r
            out.append((q, "S" + e[0], e[1]))
    elif t == 0x18:
        for _ in range(n):
            if q < hi and d[q] == 1:
                out.append((q, "SGUIDINL", d[q + 1:q + 17])); q += 17
            elif q < hi and d[q] == 0:
                out.append((q, "SREF", _u32(d, q + 1))); q += 5
            else:
                return None
    elif t == 0x00:
        # object payloads: consume only the leading marker; inline bodies flow
        # back to the main loop (structural continuation, like keyed objects)
        if n == 0:
            pass
        elif d[q] == 0:
            out.append((q, "SOBJREF", _u32(d, q + 1))); q += 5
        elif d[q] == 1:
            out.append((q, "SOBJINL")); q += 1
            r = try_dict_prelude(d, q, hi, out)
            if r is not None:
                q = r
        else:
            return None
    if q > hi:
        return None
    # killer validation (CONTEXT): a slot's bytes must be followed by a valid
    # record. Rejects the SLOT(1,1,256) mega-mis-parse of PTOK(1)+records inside
    # 11FCSpeedData objects (count read from the next PTOK swallows ~1KB and lands
    # mid-F64/uuid). Zero regressions on palastin/mc_*/1.fcp; fixes 6 gaps.
    if _SLOT_VALIDATE:
        if not _slot_end_ok(d, q, hi):
            return None
    elif not plausible_record_start(d, q, hi):
        return None
    ev.extend(out)
    return q


VAL32_TAGS = {0x01, 0x03, 0x04, 0x05, 0x07, 0x1f, 0x21, 0x23}


def try_val32(d: bytes, p: int, hi: int, ev: list):
    """Anonymous value (tok3_d RULE 1): [u8 flag 01][u8 tag][pad3][u32le n][n x payload].
    Fires only after slot fails (slot's sid reading of these bytes is implausible)."""
    if d[p] != 1 or p + 10 > hi:
        return None
    t = d[p + 1]
    if t not in VAL32_TAGS or d[p + 2:p + 5] != b"\x00\x00\x00":
        return None
    n = _u32(d, p + 5)
    if not (1 <= n <= 64):
        return None
    q = p + 9
    out = [(p, "VAL32", t, n)]
    if t in (0x01, 0x03):
        q += 4 * n
    elif t == 0x04:
        q += 8 * n
    elif t == 0x05:
        q += 1 * n
    else:
        for _ in range(n):
            r = _flagged(d, q, hi, uuid=(t == 0x23))
            if r is None:
                return None
            q, e = r
            out.append((q, "V" + e[0], e[1]))
    if q > hi or not plausible_record_start(d, q, hi):
        return None
    ev.extend(out)
    return q



def try_fnrec(d: bytes, p: int, hi: int):
    """Managed (0x113) filename record inside an EMPTY-alias FILESPEC:
    [u4le L=len(name)+13][u4 0][u4 0][u4le 1][name][00 00].  Returns
    (name, end) or None.  The signature (11 zero bytes + the 01 word +
    printable run + 00 00) has ZERO matches on any other corpus."""
    n = d[p]
    if not (14 <= n <= 93 and d[p + 1:p + 4] == b"\x00\x00\x00"
            and _u32(d, p + 4) == 0 and _u32(d, p + 8) == 0
            and _u32(d, p + 12) == 1 and p + 5 + n <= hi
            and all(0x20 <= c < 0x7f for c in d[p + 16:p + 3 + n])
            and d[p + 3 + n:p + 5 + n] == b"\x00\x00"):
        return None
    return d[p + 16:p + 3 + n].decode("ascii", "replace"), p + 5 + n


def _orphan18_ctx(ev, d) -> bool:
    """v0x13 (PPC 2006 dialect) detached count-2 GUID-pair tail CONTEXT: a
    stream-version-0x13 document, with the walk sitting right after a GUID
    slot's 11-byte trailer (OBJSLOTREF(1,·) preceded by a GUID-slot/ref
    event) or right after a previous tail (CNTW+BAREREF).  The version gate
    is required: the LONG tail form is byte-identical to a genuine kid-24
    keyed OBJREF, which the v0x15 corpus (palastin) serializes in the same
    event context (2129 sites).  v0x13 Intel (managed) has ZERO sites of
    either shape — LE baseline + 26-check gate pin both."""
    if len(ev) < 2 or d[0x2e] != 1 or _u32(d, 0x2f) != 0x13:
        return False
    k1, k2 = ev[-1][1], ev[-2][1]
    if k1 == "OBJSLOTREF" and ev[-1][2] == 1 \
            and k2 in ("SLOTGUIDREF", "BAREREF", "GUIDREF", "GUIDREF2", "CNTW"):
        return True
    return k1 == "BAREREF" and k2 == "CNTW"


def tokenize(d: bytes, lo: int, hi: int, guard_max=50_000_000) -> list[tuple]:
    p, ev, guard = lo, [], 0
    while p < hi and guard < guard_max:
        guard += 1
        p0 = p
        if d[p:p + 9] == b"\x01\x01\x00\x00\x00\x18\x00\x00\x00":
            if d[p + 9:p + 11] == b"\x01\x01":
                ev.append((p0, "GUIDINL", d[p + 11:p + 27])); p += 38
            elif d[p + 9:p + 11] == b"\x01\x00":
                # [9B magic][01 marker][00 flag][u32le ref] = 15B
                # (9147/9147 instances in palastin: ref>>16==0, d[p+15]==0x01)
                ev.append((p0, "GUIDREF", _u32(d, p + 11))); p += 15
            else:
                ev.append((p0, "GUIDREF", _u32(d, p + 10))); p += 14
            continue
        if F_GLUE_G10 and d[p:p + 9] == b"\x01\x01\x00\x00\x00\x10\x00\x00\x00":
            if d[p + 9:p + 11] == b"\x01\x01":
                ev.append((p0, "G10INL", d[p + 11:p + 27])); p += 27
            elif d[p + 9:p + 11] == b"\x01\x00":
                ev.append((p0, "G10REF", _u32(d, p + 11))); p += 15
            else:
                ev.append((p0, "G10REF", _u32(d, p + 10))); p += 14
            continue
        if d[p:p + 9] == b"\x01\x01\x00\x00\x00\x1a\x00\x00\x00":
            # v0x16 dialect: the 0x18 GUID magic family with kind word 0x1a
            # (Time Remap keyframe region; 109 MUSEO sites, zero Intel sites).
            # Same three tails/extents as the 0x18 branch; same alloc weights.
            if d[p + 9:p + 11] == b"\x01\x01":
                ev.append((p0, "GUIDINL", d[p + 11:p + 27])); p += 38
            elif d[p + 9:p + 11] == b"\x01\x00":
                ev.append((p0, "GUIDREF", _u32(d, p + 11))); p += 15
            else:
                ev.append((p0, "GUIDREF", _u32(d, p + 10))); p += 14
            continue
        if d[p:p + 9] == b"\x01\x01\x00\x00\x00\x00\x00\x00\x00":
            if p + 13 <= hi and _u32(d, p + 9) == 0:
                # object-slot sid=1 with empty ref word: 9B header, body records
                # (zeros / NKEY / DEF) flow back to the main loop
                ev.append((p0, "OTAGOBJ")); p += 9
            elif d[p + 9] == 0:
                ev.append((p0, "OTAGREF", _u32(d, p + 10))); p += 14
            elif d[p + 9] == 0x05 and d[0x2e] == 1 and _u32(d, 0x2f) == 0x13 \
                    and _u32(d, p + 10) <= 0x100 \
                    and p + 15 + _u32(d, p + 10) <= hi \
                    and d[p + 14 + _u32(d, p + 10)] == 0:
                # v0x13 T05LIST: OTAG head + bare tag-5 byte list
                # [05][u32 n][n x u8][00] (browser/view prefs; 5 Aaron sites,
                # zero Intel sites — the junk framing cascaded ~30 RAW at the
                # two big sites and swallowed a GUIDINL).  Surfaced as a
                # 0-alloc BLOBINL scalar.
                n05 = _u32(d, p + 10)
                ev.append((p0, "OTAGINL"))
                ev.append((p + 9, "BLOBINL", 0x05, n05))
                p += 15 + n05
            else:
                ev.append((p0, "OTAGINL")); p += 10
                r = try_dict_prelude(d, p, hi, ev)
                if r is not None:
                    p = r
            continue
        # COUNT-2 GUID prelude (stream-0x113 family; 49 sites in palastin too):
        # [01 02][00 00 00 18][00 00 00] then entry1 [00][id1 u4le], entry2
        # [18 00 00 00][00][id2 u4le] (bare ref) | [01 00][id2 u4le] (marked
        # ref; its standard 11-byte GUID trailer follows as ordinary events).
        # The entry1-flag=01 flavors keep their existing count-less GUID-slot
        # parse (try_slot sid=2), which is byte-clean — only the flag=00 form
        # mis-framed (PTOK+CNTW+... on palastin by luck, RAW on 0x113).
        if d[p:p + 9] == b"\x01\x02\x00\x00\x00\x18\x00\x00\x00" \
                and d[p + 9] == 0 and d[p + 14:p + 18] == b"\x18\x00\x00\x00":
            if d[p + 18] == 0:
                ev.append((p0, "GUIDREF", _u32(d, p + 10)))
                ev.append((p + 14, "GUIDREF2", _u32(d, p + 19)))
                p += 23
                continue
            if d[p + 18:p + 20] == b"\x01\x00":
                ev.append((p0, "GUIDREF", _u32(d, p + 10)))
                ev.append((p + 14, "GUIDREF2", _u32(d, p + 20)))
                p += 24
                continue
        if F_GLUE_G10 and d[p:p + 9] == b"\x01\x02\x00\x00\x00\x10\x00\x00\x00" \
                and d[p + 9:p + 11] == b"\x01\x01":
            # count-2 inline tag-0x10 GUID: geometry identical to G10INL (GUID
            # at p+11..p+27, 11-byte trailer after), so the existing trailer
            # relabel and R12's G10INL-head gate apply unchanged
            ev.append((p0, "G10INL", d[p + 11:p + 27])); p += 27
            continue
        if p + 13 <= hi and _u32(d, p) in (1, 2) and d[p + 4] in (0, 1):
            et = _u32(d, p + 5)
            if et == 0:
                C = _u32(d, p + 9)
                if C < 100000:
                    ev.append((p0, "PRELUDE", C)); p += 13; continue
            elif et == 1:
                # INT array: header + C x u32le inline (browser_history etc.)
                C = _u32(d, p + 9)
                if C <= SLOT_MAX_COUNT and p + 13 + 4 * C <= hi:
                    ev.append((p0, "ARRAY", 1, C)); p += 13 + 4 * C; continue
                if C < 100000:
                    ev.append((p0, "PRELUDE", C)); p += 13; continue
            elif et == 0x20:
                C = _u32(d, p + 9)
                r = try_named_array(d, p + 13, hi, C)
                if r is not None:
                    ev.append((p0, "ARRAY", 0x20, C)); p = r; continue
            elif et in ARRAY_ELEM_SIZES or et in (0x1f, 0x07, 0x21):
                # typed array: [u32 kind][u8 f][u32 elem-tag][u32 C][C x payload]
                C = _u32(d, p + 9)
                if C <= SLOT_MAX_COUNT:
                    q = p + 13
                    ok = True
                    if et in ARRAY_ELEM_SIZES:
                        q += ARRAY_ELEM_SIZES[et] * C
                        ok = q <= hi
                    else:
                        for _ in range(C):
                            r = _flagged(d, q, hi)
                            if r is None:
                                ok = False; break
                            q = r[0]
                    if ok:
                        ev.append((p0, "ARRAY", et, C)); p = q; continue
        if d[p] == 1 and d[p + 2:p + 5] == b"\x00\x00\x00":
            fs = try_filespec(d, p, hi)
            if fs and fs[1] >= 2:
                end, nf, spans = fs
                ev.append((p0, "FILESPEC", nf, tuple(spans))); p = end; continue
            r = try_slot(d, p, hi, ev)
            if r is not None:
                p = r; continue
            if F_VAL32:
                r = try_val32(d, p, hi, ev)
                if r is not None:
                    p = r; continue
            # glue R3: 11B obj-slot [01][u32 sid][00 tag][u8 mk][u32 ref|count]
            # (OTAG's 9-byte all-zero signature is checked earlier, so this only
            #  sees the disjoint mk/ref combos, e.g. 01 01 00 00 00 00 00 01 ...)
            if d[p + 5] == 0 and d[p + 6] <= 1 and p + 11 <= hi:
                sid = _u32(d, p + 1)
                w = _u32(d, p + 7)
                if (sid <= SLOT_MAX_ID
                        and w <= (0x10000 if d[p + 6] else SLOT_MAX_ID)
                        and plausible_record_start(d, p + 11, hi)):
                    ev.append((p0, "OBJSLOTINL" if d[p + 6] else "OBJSLOTREF", sid, w))
                    p += 11; continue
            if d[p + 1] == 0:
                # bare inline marker [01] + dict prelude (composite members)
                r = try_dict_prelude(d, p + 1, hi, ev, strict=True)
                if r is not None:
                    ev.insert(len(ev) - 1, (p0, "OBJINL1"))
                    p = r; continue
            if d[p + 1] != 1:
                ptok_n = _u32(d, p + 1)
                ra = refarray_end(d, p + 5, ptok_n, hi)
                if ra is not None:
                    ev.append((p0, "PTOK", ptok_n))
                    ev.append((p + 5, "REFARRAY", ptok_n))
                    p = ra; continue
                ev.append((p0, "PTOK", ptok_n)); p += 5; continue
            if plausible_record_start(d, p + 5, hi):
                # sid=1 positional token (falls through OTAG/GUID magics);
                # only when a valid record follows (T20 body slots etc.)
                ev.append((p0, "PTOK", 1)); p += 5; continue
        if d[p] == 1 and d[p + 1] == 0 and p + 6 <= hi:
            # bare flagged ref [01][00][u32le ref] (6B) — the GUIDREF-15B tail
            # form appearing without its 9-byte magic (positional GUID/obj refs)
            w = _u32(d, p + 2)
            if w <= SLOT_MAX_ID and plausible_record_start(d, p + 6, hi):
                ev.append((p0, "BAREREF", w)); p += 6; continue
        if d[p] == 0 and d[p + 1] == 0x18 and d[p + 2:p + 5] == b"\x00\x00\x00" \
                and _orphan18_ctx(ev, d):
            # v0x13 ORPHAN18 tails (detached count-2 GUID-pair entries after a
            # SLOTGUIDREF head): LONG [00][0x18][u32 0][01][00][u32 ref] and
            # SHORT [00][0x18][00][u32 ref] both read as CNTW(0x18)+BAREREF
            # glue (LINKBOX credit, the palastin/MUSEO-proven weight).  The
            # old framing read the LONG form as a junk NKEY(24)+OBJREF entry
            # and DERAILED on the SHORT form (RAW cascades + phantom ids =
            # the Aaron master-pool E ramp / lost subclip names).
            if d[p + 5:p + 9] == b"\x00\x00\x00\x00" and d[p + 9] == 1 \
                    and d[p + 10] == 0 and 0 < _u32(d, p + 11) <= SLOT_MAX_ID:
                ev.append((p + 1, "CNTW", 0x18))
                ev.append((p + 11, "BAREREF", _u32(d, p + 11)))
                p += 15
                continue
            if d[p + 5] == 0 and 0 < _u32(d, p + 6) <= SLOT_MAX_ID:
                ev.append((p + 1, "CNTW", 0x18))
                ev.append((p + 6, "BAREREF", _u32(d, p + 6)))
                p += 10
                continue
        if d[p] == 0 and d[p + 1]:
            # a filename record's L byte follows a zero: claim it before the
            # NKEY reader mis-keys on [00][u4le L][tag 00] (managed 0x113 only)
            fr = try_fnrec(d, p + 1, hi)
            if fr is not None:
                ev.append((p + 1, "FNREC", fr[0])); p = fr[1]; continue
        if d[p] == 0 and d[p + 1] and d[p + 5] < 0x30:
            kid = _u32(d, p + 1)                    # numeric key is u32le (multi-byte for dict refs)
            if (0 < kid <= SLOT_MAX_ID and d[p + 6:p + 9] == b"\x00\x00\x00"
                    and (d[p + 5] in SLOT_TAGS or d[p + 5] in FIXED_TAGS
                         or d[p + 5] in (0x0c, 0x20, 0x10, 0x16, 0x06) or is_kfblob(d, p + 5))):
                # don't let [pad 00][FILESPEC 01 nf ...] masquerade as a key
                if not (kid & 0xff == 1 and d[p + 5] == 0 and try_filespec(d, p + 1, hi)):
                    ev.append((p0, "NKEY", kid)); p = _value(d, p + 5, ev, hi); continue
        if d[p] == 0 and d[p + 1] and d[p + 5] == 0 and d[p + 6] in (0x02, 0x05):
            # v0x16 keyed EXTRA-BYTE form: [00][u32 kid][00][u32 tagword][value]
            # (one pad byte between kid and tag word; only tags 0x02/0x05 are
            # byte-proven — 793 FIXED-0x02 + 20 BOOL sites in the PPC corpus,
            # zero Intel sites).  Disjoint from every legit form: a real OBJ
            # value has a <= 1 where this shape has the tag byte >= 2.  The
            # a-byte bound mirrors the BE gate in keyg_swab._mirror_step.
            kid = _u32(d, p + 1)
            if (0 < kid <= SLOT_MAX_ID and d[p + 7:p + 10] == b"\x00\x00\x00"
                    and p + 11 <= hi and d[p + 10] <= 1):
                ev.append((p0, "NKEY", kid)); p = _value(d, p + 6, ev, hi); continue
        if d[p] == 0 and d[p + 1] and d[p + 4] < 0x30:
            # key with LE low byte 0x00 (e.g. 0xb500): the leading 0x00 IS the
            # key's low byte here (marker eaten as pad) -> kid = u32 at p
            kid = _u32(d, p)
            if (0 < kid <= SLOT_MAX_ID and d[p + 5:p + 8] == b"\x00\x00\x00"
                    and (d[p + 4] in SLOT_TAGS or d[p + 4] in FIXED_TAGS or d[p + 4] in (0x0c, 0x10, 0x16, 0x06))):
                if not (d[p + 1] == 1 and d[p + 4] == 0 and try_filespec(d, p + 1, hi)):
                    ev.append((p0, "NKEY", kid)); p = _value(d, p + 4, ev, hi); continue
        if d[p] == 0:
            p += 1; continue
        n = d[p]
        fr = try_fnrec(d, p, hi)
        if fr is not None:
            ev.append((p0, "FNREC", fr[0])); p = fr[1]; continue
        # names up to 80: old-format P2/QT metadata keys are 41-70 chars
        # ('org.smpte.mxf...', 'com.panasonic.professionalplugin...device.
        # manufacturer'); every banked corpus tokenizes RAW-free with cap 40,
        # and a >40 printable run matches no earlier branch, so >40 only fires
        # inside former RAW pockets
        if 0 < n <= 80 and p + 1 + n <= hi and all(0x20 <= c < 0x7f for c in d[p + 1:p + 1 + n]):
            ev.append((p0, "DEF", d[p + 1:p + 1 + n].decode())); p = _value(d, p + 1 + n, ev, hi); continue
        # BARE numeric key (no 0x00 marker): [u32 key][tag][pad3][value...]
        # proven inside object bodies after PTOK/arrays (e.g. 0xe0438d region)
        kid = _u32(d, p)
        if (0 < kid <= SLOT_MAX_ID and d[p + 4] < 0x30 and d[p + 5:p + 8] == b"\x00\x00\x00"
                and (d[p + 4] in SLOT_TAGS or d[p + 4] in FIXED_TAGS or d[p + 4] in (0x0c, 0x20, 0x10, 0x16, 0x06))):
            ev.append((p0, "NKEY", kid)); p = _value(d, p + 4, ev, hi); continue
        # CNTW (tok3_d RULE 3): bare member-count word in object bodies —
        # last resort before RAW; positionally equals RAW+pads but keeps sync
        if (d[p + 1] == 0 and d[p + 2] == 0 and d[p + 3] == 0 and _u32(d, p) <= 0x10000
                and plausible_record_start(d, p + 4, hi)):
            ev.append((p0, "CNTW", _u32(d, p))); p += 4; continue
        # GUIDORPH (managed 0x113): the count-2 GUID prelude's SECOND entry
        # orphaned from its entry1 — a bare [18 00 00 00 00][id low byte] with
        # no [01 02] head (the entry1 was consumed as an OBJREF).  The current
        # parse RAWs the 0x18 and the id low byte with the 4 zeros skipped
        # between them, landing 6 bytes on; consume the same 6 bytes as one
        # 0-alloc token.  The TOKEN is byte- and alloc-neutral, but removing
        # the RAWs deliberately re-enables _megaslot_credit on managed (its
        # interiors now re-tokenize RAW-free and converge: +539 ids at 32
        # sites — the managed graph/link gates require the corrected ids).
        # Only fires at the RAW fallback (0x18 is never a record start), so it
        # cannot mis-eat a real record; 31 sites in managed, 0 elsewhere
        # (token streams byte-identical on every other corpus).
        if d[p] == 0x18 and d[p + 1:p + 5] == b"\x00\x00\x00\x00" and d[p + 5]:
            ev.append((p0, "GUIDORPH", _u32(d, p + 5) & 0xff)); p += 6; continue
        ev.append((p0, "RAW", d[p])); p += 1
    return ev


def _value(d: bytes, p: int, ev: list, hi: int) -> int:
    p0 = p
    t, a = d[p], d[p + 4]
    p += 5
    # KFBLOB (renderSettings / speed-segment keyframe blob): the tag value T is
    # ALSO the count of 0x01 flag bytes that follow, then 0x00, then N x BLOB_UNIT
    # (byte-proven: ones==tag & N==3 in all 12 palastin instances; scanblob.py).
    if 5 <= t <= 0x20 and d[p0 + 4:p0 + 4 + t] == b"\x01" * t and d[p0 + 4 + t] == 0:
        q = p0 + 4 + t + 1
        u = 0
        while d[q:q + 15] == BLOB_UNIT:
            u += 1; q += 15
        if u >= 1:
            ev.append((p0, "KFBLOB", t, u)); return q
    if t == 0x01: ev.append((p0, "INT", _u32(d, p))); return p + 4
    if t == 0x04: ev.append((p0, "F64", struct.unpack_from("<d", d, p)[0])); return p + 8
    if t == 0x05: ev.append((p0, "BOOL", d[p])); return p + 1
    if t == 0x03: ev.append((p0, "F32")); return p + 4
    if t == 0x0b:
        ln = _u32(d, p); ev.append((p0, "FOURCC", d[p + 4:p + 4 + ln].decode("latin1"))); return p + 4 + ln
    if t == 0x1f:
        if d[p] == 1:
            ln = _u32(d, p + 1); ev.append((p0, "STRINL", d[p + 5:p + 5 + ln].decode("utf-8", "replace"))); return p + 5 + ln
        ev.append((p0, "STRREF", _u32(d, p + 1))); return p + 5
    if t == 0x00:
        # anika-2007 inline masterClip/captureSource object (the LE side of
        # keyg_swab's MASTEROBJ; ZERO Intel sites — this shape only exists in the
        # transcoded PPC-2007 file).  Head after the swab: [00 00 00 00][a=0]
        # [class byte in MASTER_CLS][u32le 0x1f schema-tag][01 01][u32le namelen]
        # [ascii name].  Its body is a self-terminating keyed-metadata record
        # (reel GUID refs, timecode, capture settings) that the grouper isolates
        # and closes at the enclosing clip's next bare clipitem head.  Surface the
        # head and skip past the name to the body's first member.  Gated on the
        # 0x1f schema word + class set + 01 01 + printable name: matches no normal
        # tag-0x00 value (all of which carry pad3 == 0 at off+6).
        if a == 0 and d[p0 + 5] in MASTER_CLS and _u32(d, p0 + 6) == 0x1f \
                and d[p0 + 10:p0 + 12] == b"\x01\x01":
            nl = _u32(d, p0 + 12)
            if 1 <= nl <= 64 and p0 + 16 + nl <= hi \
                    and all(0x20 <= c < 0x7f for c in d[p0 + 16:p0 + 16 + nl]):
                ev.append((p0, "MASTEROBJ", d[p0 + 16:p0 + 16 + nl].decode("utf-8", "replace")))
                return p0 + 16 + nl
        # anika-dialect inline-class-name typed object: a keyed value whose tag
        # is 0x00 but whose would-be pad3 is instead [u8 L][L ascii classname]
        # (masterClips @0x5fe in anika's logo generator).  Every normal tag-0x00
        # value (OBJINL/OBJREF/OBJEMPTY/LEAF) has pad3 == 0, so a printable
        # length here is the discriminator and matches no other form.  The
        # walker used to read the class name byte-by-byte as RAW, leaving the
        # object's self-terminating members (isMaster/itemspec/markers/...) to
        # bubble as phantom entries of the enclosing counted FxPlug generator
        # DICT(20) — truncating it, and with it the whole timeline.  Surface the
        # value as an empty object and skip the class-name preamble (its
        # secondary "orphan" tag included) to the first clean keyed member so
        # the enclosing dict counts this as exactly one entry.  palastin's
        # masterClips/orphan form is DEF-keyed / OTAGOBJ (pad3 == 0) and never
        # reaches this branch.
        Lc = d[p0 + 1]
        if 1 <= Lc <= 40 and p0 + 2 + Lc <= hi \
                and all(0x20 <= c < 0x7f for c in d[p0 + 2:p0 + 2 + Lc]):
            for s in range(p0 + 2 + Lc, min(p0 + 2 + Lc + 0x40, hi)):
                Lm = d[s]
                if not (1 <= Lm <= 40) or s + 1 + Lm >= hi:
                    continue
                if not all(0x20 <= c < 0x7f for c in d[s + 1:s + 1 + Lm]):
                    continue
                vt = d[s + 1 + Lm]
                if vt in SLOT_TAGS or vt in FIXED_TAGS \
                        or vt in (0x0c, 0x20, 0x10, 0x16, 0x06):
                    ev.append((p0, "OBJEMPTY")); return s
        # v0x13 (PPC 2006 dialect) keyed-OBJ inline with a=0: one extra 00
        # between the tag word and the [01 01] inline pair, then the ordinary
        # body prelude (byte-proven against the healthy DEF twin @0x78253 in
        # Aaron_03: identical bytes except the extra 00; 5 sites, kid-24
        # keyframe ELEMS flavor x4 + kid-27 DICT flavor x1). Gate demands a
        # valid prelude head so a=0 junk cannot fire it; zero Intel sites
        # (LE baseline: stream+allocs hashes identical on all 8 corpora).
        if a == 0 and d[p] == 1 and d[p + 1] == 1:
            if _u32(d, p + 2) in (1, 2) and d[p + 6] in (0, 1):
                ev.append((p0, "OBJINL")); return p + 2
            sub: list = []
            r = try_dict_prelude(d, p + 2, hi, sub, strict=True)
            if r is not None:
                ev.append((p0, "OBJINL")); ev.extend(sub); return r
        mk = d[p]; p += 1
        if mk == 0:
            ref = _u32(d, p)
            # empty-object form [00][pad3][a=0][mk=0] with NO ref word: only when
            # the would-be ref is impossible AND dropping it lands on a record
            # (byte-proven @0x1852 palastin: the 'ref' swallowed a def length byte)
            if a == 0 and ref > SLOT_MAX_ID and plausible_record_start(d, p, hi):
                ev.append((p0, "OBJEMPTY")); return p
            ev.append((p0, "OBJREF", ref)); return p + 4
        if (d[p + 4] == 1 and d[p] == 0 and d[p + 1] == 0 and d[p + 2] == 0 and d[p + 3] == 0
                and 1 <= d[p + 9] <= 40 and all(0x20 <= c < 0x7f for c in d[p + 10:p + 10 + d[p + 9]])):
            ev.append((p0, "LEAF")); return p + 9
        ev.append((p0, "OBJINL"))
        r = try_dict_prelude(d, p, ev=ev, hi=hi)
        return r if r is not None else p
    if t == 0x23:
        if d[p] == 1 and d[p + 1:p + 5] == b"\x22\x00\x00\x00":
            ln = _u32(d, p + 5); ev.append((p0, "UUID", d[p + 9:p + 9 + ln].decode("ascii", "replace"))); return p + 9 + ln
        if F_UUIDL and d[p:p + 4] == b"\x00\x00\x00\x01" and d[p + 4:p + 8] == b"\x22\x00\x00\x00":
            ln = _u32(d, p + 8); ev.append((p0, "UUID", d[p + 12:p + 12 + ln].decode("ascii", "replace"))); return p + 12 + ln
        ev.append((p0, "UUIDREF", _u32(d, p + 1))); return p + 5
    if t == 0x1e:                                   # typed struct: u8 count x 8B
        ev.append((p0, "STRUCT1E", a)); return p + 8 * a
    if t == 0x07:
        if d[p] == 1:
            ln = _u32(d, p + 1); ev.append((p0, "DATA07", ln)); return p + 5 + ln
        ev.append((p0, "DATA07REF", _u32(d, p + 1))); return p + 5
    if t in (0x18, 0x21):
        if d[p] == 1:
            ln = _u32(d, p + 1)
            if p + 5 + ln <= hi:
                ev.append((p0, "BLOBINL", t, ln)); return p + 5 + ln
            # An inline blob cannot extend past the file: this is a misaligned
            # read inside a bare-GUID-ref run (muraishi CC 5.1 render tail:
            # one unit's id low byte lands on the flag position and the "length"
            # 0x1800004e swallowed the last 387KB — every browser item after
            # 0x147898, 14 of the 78 oracle sequences, vanished from the tree).
            # Emit RAW so the scanner resyncs at the next record header, the
            # same recovery the Aaron PPC dialect relies on.  No other corpus
            # carries an overrunning blob (checked all 13: gated + oracled).
            ev.append((p0, "RAW", d[p0])); return p0 + 1
        ev.append((p0, "BLOBREF", t, _u32(d, p + 1))); return p + 5
    if t == 0x10:                                   # GUID-shaped (glue R1 family), keyed form
        if d[p] == 0:
            ev.append((p0, "G10REF", _u32(d, p + 1))); return p + 5
        if d[p] == 1 and d[p + 1] == 0:
            ev.append((p0, "G10REF", _u32(d, p + 2))); return p + 6
        if d[p] == 1 and d[p + 1] == 1:
            ev.append((p0, "G10INL", d[p + 2:p + 18])); return p + 18
    if t == 0x16 and a == 1:                        # v0x16 timecode param (PPC dialect):
        # [u32 tag 0x16][u8 a=1][F64 value][u32 timebase][u16 0] — self-contained
        # scalar (mappedduration/sourceduration/mappedtime/sourcetime min/max/value
        # dict entries; byte-proven at all 3,312 MUSEO sites). Allocates 0 like F64.
        ev.append((p0, "T16TIME", struct.unpack_from("<d", d, p)[0], _u32(d, p + 8)))
        return p + 14
    if t == 0x06 and d[p] == 1 and d[p + 1] == 1:   # v0x16 keyed GUID (FXScript state):
        # [u32 tag 0x06][u8 a][01 01][16B GUID][11B trailer] — keyed-G10INL geometry
        ev.append((p0, "G10INL", d[p + 2:p + 18])); return p + 18
    if t in FIXED_TAGS:                             # proven fixed extents (see dictb/)
        ev.append((p0, "FIXED", t, a)); return p + FIXED_TAGS[t] * max(a, 1)
    if t == 0x0c:                                   # [01] + 2 x [flag 00|01][u32le] = 11B
        if d[p] == 1 and d[p + 1] <= 1 and d[p + 6] <= 1:
            ev.append((p0, "T0C", a))
            if F_0C_TAIL and d[p + 6] == 0:
                return p + 12                       # +1 trailing 00 iff second flag == 0
            return p + 11
    if t == 0x20:                                   # named object: [01][u32 n][class name], body flows
        if d[p] == 1:
            n = _u32(d, p + 1)
            if 0 < n <= 0x100 and all(0x20 <= c < 0x7f for c in d[p + 5:p + 5 + n]):
                ev.append((p0, "T20", d[p + 5:p + 5 + n].decode()))
                q = p + 5 + n
                # 9B sub-prelude [u32 1][u8 0|1][u32 0] precedes the body slots
                if _u32(d, q) == 1 and d[q + 4] in (0, 1) and _u32(d, q + 5) == 0:
                    q += 9
                return q
        elif d[p] == 0:
            ev.append((p0, "T20REF", _u32(d, p + 1))); return p + 5
    ev.append((p0, "VUNK", t)); return p


# ============================================================================
# FINAL MERGED ALLOCATION LAYER (gateb2) — SUBSCOPE + LINKBLK on tok5_sync
# ----------------------------------------------------------------------------
# tokenize() above is byte-for-byte identical to sync2/tok5_sync.py, so gap.py
# byte-sync is unaffected (verified 1.000 on palastin + mc_one/two/three/four).
# Everything below is a POST-PASS over the event stream (allocation only).
#
# Fix 1 — SUBSCOPE (probe/subscope/tok5_sub.py):
#   The value of DEF 'itemHistory' (when it carries a NON-EMPTY undo stack:
#   OBJINL, SLOT(0,0x23) doc-uuid, SUUID, then an object) is an undo-stack
#   sub-document. Anonymous inline objects (OBJINL/OBJINL1) inside it intern in
#   the sub-document's OWN scope and contribute 0 to the main table; DEF and
#   interned literals still allocate globally. tokenize_scoped() relabels those
#   events to OBJINL_S/OBJINL1_S (weight 0). Close = parent-schema resume
#   (DEF in SCOPE_CLOSE_KEYS) — name-gated; a byte-exact close remains OPEN.
#
# Fix 2 — LINKBLK (probe/linkblk/tok5_linkblk.py), deep clipitem-link blocks:
#   (1) OBJSLOTREF/OBJSLOTINL -> +1. The record `01 [u32 sid] 00 [mk<=1] [u32 w]`
#       is an inline dict/object slot allocating exactly 1 slot. When w==0 its
#       leading 9 bytes equal the OTAG signature 01 01 00 00 00 00 00 00 00 and
#       tok5 already credits it (OTAGOBJ/OTAGINL=+1); when w>0 it was OBJSLOTREF
#       at weight 0. That asymmetry was the drift.
#   (2) LINKBOX -> +1: boxed ref [u32 sz][01 00 u32 ref] — a CNTW immediately
#       followed (adjacent bytes) by a BAREREF.
#   (3) LINKROOT -> +1: keyed 0x1e (STRUCT1E) that is a DEF's value and begins
#       a boxed-ref chain (next events CNTW, BAREREF).
# ============================================================================

SCOPE_OPEN_KEYS = frozenset(("itemHistory",))
SCOPE_CLOSE_KEYS = frozenset(("lastModTime", "seqProps", "spec", "itemDict"))
# MERGE INTERACTION (validated on mc_two): the LINKBLK-credited anonymous
# constructs (OBJSLOT*, and the CNTW/STRUCT1E adjacency credits) also intern
# in the sub-document scope, so they are suppressed there too. Relabeling
# CNTW/STRUCT1E to *_S disables the LINKBOX/LINKROOT credits in-scope
# (their own base weight is 0 either way).
SUPPRESS_KINDS = frozenset(("OBJINL", "OBJINL1", "OBJSLOTREF", "OBJSLOTINL",
                            "CNTW", "STRUCT1E"))

FINAL_ALLOC1 = frozenset((
    "DEF", "PTOK", "STRINL", "SSTRINL", "VSTRINL", "UUID", "SUUID",
    "FILESPEC", "DATA07", "T0C", "LEAF", "T20",
    "OBJEMPTY",                          # empty-object value allocates +1 (session 7)
    "OBJINL", "OBJINL1", "SOBJINL", "OTAGOBJ", "OTAGINL",
    "OBJSLOTREF", "OBJSLOTINL",          # LINKBLK fix 1
    "ASTRINL",                           # ARRAY element interning (fix 3)
    "GUIDREF2",                          # count-2 GUID prelude's second entry:
                                         # registers ONE slot (byte-proven on
                                         # palastin: E reads exactly +1 at each
                                         # of its 49 sites without it)
))                                        # OBJINL_S / OBJINL1_S absent -> 0
FINAL_GUID_KINDS = frozenset(("GUIDINL", "SGUIDINL", "SLOTGUIDINL", "G10INL"))
FINAL_STR_KINDS = frozenset(("STRINL", "SSTRINL", "VSTRINL", "ASTRINL"))
FINAL_UUID_KINDS = frozenset(("UUID", "SUUID", "VUUID"))
FINAL_BASE = 2

# --- session-7 merged rules (final values; each independently measurable) ---
R_NULLOBJ = True         # R7: composite-member OBJREF(0) interns an empty object (+1)
R_SLOTGUIDINL2 = True    # R8: slot-form GUID allocates 2 (no class slot)
R_KFBLOB = True          # R9: keyframe blob allocates +1 per 15-byte BLOB_UNIT
R_MEGASLOT = True        # R10b: SLOT(1,1,256) mega-slot interior credit (ALL instances)
R_BOXLIST = True         # R16: render-preset box list mis-read as VAL32(t,16)
R_MASTERSTUB = "pm"      # R11: master-stub +1, fresh-FILESPEC gate ("pm")
R_MASTERSTUB_T0C = False # (off) fx alternative coupling: T0C(0,0) near stub -> -1
R_CLIPTOP = False        # (off) name-gated clipTop stub — subsumed by R12
R_SEQDICT = True         # R12: self-ref mainDict/clipTop stub (+1, id-topology)
R_PTOKBOX = True         # R13: PTOK box-list count prelude allocates 0 (not +1)
R_UUIDHEAD = True        # R14: uuid-headed clip snapshot -> R5 stub suppressed
R_T0CSHAPE = True        # R15: shape-based T0C weights (replaces R6 radius)
R_T0CMOOV = False        # legacy R6: MooV-filespec 4096-radius f00-T0C suppression
R_STUBT0C = True         # R17: fresh-registration coupled file-T0C (session 8)
R_GENSTUB = True         # R18: STRREF-named generator-master stub (session 8)
R_CLSNAME = True         # R19/R20/R21: T20-pocket class-name/header credits
                         # (session 9, multi_one oracle; RAW-pocket-only)


def _boxlist_units(d, p, t):
    """R16 helper — the render-quality box list of a sequence preset:
    [01][t][pad3] then t units, each [u32 sz 16|24][01 00 <u32 ref>]
    [OBJSLOTREF 01 <u32 sid=1> 00 <mk<=1> <u32 w>], separated by keyed
    object refs ([NKEY 628][OBJREF], or the NKEY 48726-48729/STRUCT1E
    preset-tail block before a trailing unit). The tag byte t (3|4|5 seen)
    is the TOTAL unit count, NOT a value tag: try_val32 reads it as F32/F64
    and swallows 4x/8x the true 16-byte payload, eating the interior units.
    Returns the byte positions of the units' size words."""
    units = []
    q = p + 5
    end_cap = p + 420
    while len(units) < t and q + 21 <= end_cap:
        sz = _u32(d, q)
        if (sz in (16, 24) and d[q + 4] == 1 and d[q + 5] == 0
                and _u32(d, q + 6) <= SLOT_MAX_ID
                and d[q + 10] == 1 and _u32(d, q + 11) == 1
                and d[q + 15] == 0 and d[q + 16] <= 1
                and _u32(d, q + 17) <= 0x100):
            units.append(q)
            q += 21
            continue
        q += 1
    return units



def _uuid_headed(ev, i):
    """R14 gate — is the OTAGOBJ at ev[i] the tail of a uuid-headed clip
    record ([OBJINL][DICT][NKEY <uuid>][UUID '...'][members][NKEY <name>]
    [STRINL name][GUIDREF class][OTAGOBJ])?

    Byte-proof (backbone self-ref oracle): every clip record repeats one
    GUIDREF X >= 3 times after its OTAGOBJ; in the zero-drift corpora
    (mc_three 0xe60/0x118f, mc_four +0x14be) X resolves EXACTLY to the
    OTAGOBJ's own table id, and the class layout (itemspec/markers/isMaster/
    scene/take/comment1-4/good) is field-identical to palastin's records, so
    X = own id there too. D = pred - X is then an exact per-site drift
    oracle. Chain-decoding all 5764 palastin backbone records: D == 0 across
    every exact span; each CORRECT credited stub reads D = drift-1 (the stub
    slot precedes the object); each WRONG one reads D = drift and drift
    rises +1 after. Result: 61/61 uuid-headed R5 sites are over-credited
    (58 clean WRONG, 3 next to known between-construct noise), 0 CORRECT;
    of the 237 uuid-less credited backbone stubs, 232 read CORRECT (5
    noise-adjacent exceptions left open). A uuid member in the record head
    = re-serialized clip snapshot (fresh uuid, no new master registration)."""
    for j in range(i - 3, max(i - 45, -1), -1):
        k = ev[j][1]
        if k in ("UUID", "SUUID"):
            return True
        if k in ("OBJINL", "OBJINL1", "OTAGOBJ", "DEF", "FILESPEC", "T20"):
            return False
    return False


_RENDSIG = ("INT", "F64", "F64", "F64", "F64", "BOOL")


def _t0c_member_sig(ev, i, n, k=6):
    """Value kinds of the next k keyed members after the T0C at ev[i]."""
    out = []
    j = i + 1
    while j + 1 < n and len(out) < k:
        if ev[j][1] not in ("NKEY", "DEF"):
            break
        out.append(ev[j + 1][1])
        j += 2
    return tuple(out)


def _t0c_rendref(ev, i, n):
    """R15a — itemRender-dict REF-form 'file' T0C: the T0C is the 'file'
    member of an [OBJINL][DICT 7] render dict whose remaining members are
    (renderItemMinSample INT, renderItemMin F64, renderItemMax F64,
    offsetRenderToSrc F64, <F64>, <BOOL>). Detector is fully structural
    (DICT count 7 + member-kind signature); byte-verified to split exactly
    from the inline form (next member = reader FOURCC): palastin 395 ref
    vs 161 inline, zero misclassifications, 0 sites in mc_*/1.fcp."""
    return (i >= 3 and ev[i - 2][1] == "DICT" and ev[i - 2][2] == 7
            and ev[i - 3][1] in ("OBJINL", "OBJINL1")
            and _t0c_member_sig(ev, i, n) == _RENDSIG)


def _t0c_seref(ev, i, d):
    """R15b — registry start/end-dict REF-form 'file' T0C: member of an
    [OBJINL1][DICT 10|11] whose first members are start F64 / end F64 /
    file T0C(f00 double-ref). 1324 palastin sites, all inside the render
    registry byte range; 0 in mc_*/1.fcp."""
    if not (i >= 6 and ev[i - 6][1] == "DICT" and ev[i - 5][1] == "NKEY"
            and ev[i - 4][1] == "F64" and ev[i - 3][1] == "NKEY"
            and ev[i - 2][1] == "F64" and ev[i - 1][1] == "NKEY"):
        return False
    p = ev[i][0]
    return d[p + 6] == 0 and d[p + 11] == 0


def _boxrun_len(ev, i):
    """Number of LINKBOX units (CNTW immediately followed by BAREREF) in the
    boxed-ref run starting at ev[i] (a CNTW). Boxes may be separated by
    NKEY/OBJREF/OBJSLOTREF/STRUCT1E; the run ends at the first event outside
    that separator set."""
    n = len(ev)
    SEP = {"OBJSLOTREF", "NKEY", "OBJREF", "STRUCT1E", "BAREREF", "CNTW"}
    nb = 0
    j = i
    while j + 1 < n and ev[j][1] == "CNTW" and ev[j + 1][1] == "BAREREF" \
            and ev[j + 1][0] == ev[j][0] + 4:
        nb += 1
        j += 2
        while j < n and ev[j][1] in SEP and ev[j][1] != "CNTW":
            j += 1
    return nb


def _has_undo_dict(ev, i):
    """True iff DEF at ev[i] ('itemHistory') is followed by a NON-EMPTY undo
    stack: value = OBJINL, SLOT(0,0x23) doc-uuid, SUUID, then OBJINL1/OBJINL.
    An EMPTY stack has a DEF right after the doc-uuid SUUID -> False."""
    saw_uuid = False
    for j in range(i + 1, min(i + 6, len(ev))):
        k = ev[j][1]
        if k in ("OBJINL", "SLOT"):
            continue
        if k == "SUUID":
            saw_uuid = True
            continue
        if k in ("OBJINL1", "OBJINL"):
            return saw_uuid
        return False
    return False


ARRAY_FLAGGED_ETS = (0x1f, 0x07, 0x21)


def _array_elem_events(d, e, hi):
    """Fix 3 — ARRAY element interning. tokenize() parses flagged typed-array
    payloads ([u32 kind][u8 f][u32 et][u32 C][C x flagged]) via _flagged but
    emits NO element events, so inline literals inside arrays were never
    credited. They intern exactly like STRINL (+1 each); refs allocate 0.
    Validated on targets_final.json: six spans zero out EXACTLY with residual
    == inline-element count (default 3, fontalign 4, fontcolor 3, align 4,
    col 3, champs 2), eight more improve, and the feature is 0 on all 425
    good spans (pal+mc2). Emits ASTRINL (value kept for et 0x1f) / AREF."""
    out = []
    q = e[0] + 13
    for _ in range(e[3]):
        r = _flagged(d, q, hi)
        if r is None:
            break
        q, sub = r
        if sub[0] == "STRINL":
            out.append((q, "ASTRINL", sub[1] if e[2] == 0x1f else None))
        else:
            out.append((q, "AREF", sub[1]))
    return out


def tokenize_scoped(d: bytes, lo: int, hi: int):
    """tokenize() + (a) relabel anonymous inline objects inside an itemHistory
    undo sub-document to *_S (allocation weight 0); (b) insert ASTRINL/AREF
    element events for flagged typed arrays. Byte extents unchanged."""
    ev = tokenize(d, lo, hi)
    in_scope = False
    out = []
    for i, e in enumerate(ev):
        k = e[1]
        if k == "DEF":
            nm = e[2]
            if not in_scope and nm in SCOPE_OPEN_KEYS and _has_undo_dict(ev, i):
                in_scope = True
            elif in_scope and nm in SCOPE_CLOSE_KEYS:
                in_scope = False
        if in_scope and k in SUPPRESS_KINDS:
            out.append((e[0], k + "_S") + tuple(e[2:]))
        else:
            out.append(e)
        if k == "ARRAY" and e[2] in ARRAY_FLAGGED_ETS:
            out.extend(_array_elem_events(d, e, hi))
        # Fix 4 — G10 trailer: the tag-0x10 GUID block is followed by the same
        # 11-byte trailer as 0x18 GUIDs (01 01 00 00 00 00 00 01 00 00 00),
        # which tok5 surfaces as a spurious OBJSLOTREF(1,1) at pos+27.
        # Relabel it G10TRAILER (weight 0). 2/2 instances (pal+mc2, ALL that
        # exist) are byte-identical; fixes the clipTop span exactly in both.
        if k == "OBJSLOTREF" and i > 0 and ev[i - 1][1] == "G10INL" \
                and e[0] == ev[i - 1][0] + 27 and e[2] == 1 and e[3] == 1:
            out[-1] = (e[0], "G10TRAILER") + tuple(e[2:])
    return out


def final_allocs(ev: list) -> list[int]:
    """Per-event object-table allocation count (parallel to ev).
    Input: SCOPED events (tokenize_scoped)."""
    out = [0] * len(ev)
    seen: set = set()
    n = len(ev)
    for i, e in enumerate(ev):
        k = e[1]
        if k == "G10INL":
            # tag-0x10 GUID block: +2 (trailer slots) but NO class slot —
            # proven by the clipTop span (true delta 3 = DEF+2) in pal AND mc2.
            out[i] = 2
            seen.add(e[-1])
            continue
        if k in FINAL_GUID_KINDS:
            g = e[-1]
            if R_SLOTGUIDINL2 and k == "SLOTGUIDINL":
                # R8 (session 7): the count-less slot-form GUID
                # [01][sid][18][pad3][01 01][16B GUID][11B trailer] allocates
                # the 2 trailer slots but NO class slot. 1/1 instance across
                # both corpora (@0x38607d palastin, sid 7): +3 over-credits the
                # sequenceDict span by exactly 1; consistent with the rule that
                # only the KEYED 0x18 form allocates the class slot.
                out[i] = 2
            else:
                out[i] = 2 + (1 if (g != ROOT_GUID and g not in seen) else 0)
            seen.add(g)
            continue
        a = 1 if k in FINAL_ALLOC1 else 0
        if k == "CNTW" and i + 1 < n and ev[i + 1][1] == "BAREREF" \
                and ev[i + 1][0] == e[0] + 4:                       # LINKBOX
            a += 1
        if k == "STRUCT1E" and i > 0 and ev[i - 1][1] == "DEF" \
                and i + 2 < n and ev[i + 1][1] == "CNTW" \
                and ev[i + 2][1] == "BAREREF":                      # LINKROOT
            a += 1
        out[i] = a
    return out


def object_table(d: bytes, lo: int = 0x2e, hi: int | None = None) -> dict:
    """FINAL sequential intern/object table: index -> (kind, value|None).
    Base index 2. Build is strictly sequential (c += alloc), so no index can
    ever be assigned twice (GATE C structural guarantee)."""
    if hi is None:
        hi = len(d)
    hi = min(hi, len(d) - 16)                # leave a read margin (tokenize peeks d[p+n])
    ev = tokenize_scoped(d, lo, hi)
    allocs = final_allocs(ev)
    c = FINAL_BASE
    table = {}
    for a, e in zip(allocs, ev):
        if not a:
            continue
        k = e[1]
        if k in FINAL_GUID_KINDS:
            if a == 3:
                table[c] = ("class", e[-1].hex()); c += 1
            table[c] = ("guidtrailer", None); c += 1
            table[c] = ("guidtrailer", None); c += 1
            continue
        base = 1 if k in FINAL_ALLOC1 else 0
        if base:
            val = None
            if k in FINAL_STR_KINDS or k in FINAL_UUID_KINDS or k in ("DEF", "T20"):
                val = e[2] if len(e) > 2 else None
            table[c] = (k, val); c += 1
        for _ in range(a - base):                 # LINKBOX / LINKROOT credits
            table[c] = ("LINKSLOT", None); c += 1
    return table


def key_ids(d: bytes, lo: int = 0x2e, hi: int | None = None) -> dict:
    ids = {}
    for i, (k, v) in object_table(d, lo, hi).items():
        if k == "DEF" and v not in ids:
            ids[v] = i
    return ids


# ---------------------------------------------------------------------------
# Allocation rules R1-R6 (session-6 "crush" layer; see report_c). The base
# final_allocs above is kept as _base_final_allocs; the public final_allocs /
# object_table / key_ids below apply the full rule set.
# ---------------------------------------------------------------------------
_base_final_allocs = final_allocs

GUIDPREV = frozenset(("GUIDREF", "G10REF", "SLOTGUIDREF", "GUIDREF2"))
STRK = frozenset(("STRINL", "SSTRINL", "VSTRINL", "ASTRINL"))
_UNDO_S_BASE = {"OBJINL_S": 1, "OBJINL1_S": 1, "OBJSLOTREF_S": 1,
                "OBJSLOTINL_S": 1, "CNTW_S": 0, "STRUCT1E_S": 0}


_IN_MEGA = False


def _megaslot_credit(ev: list, d: bytes) -> dict:
    """R-MEGASLOT — SLOT(1,1,256) mega-slot interior credit (fx agent).

    The byte pattern [01][sid=1][tag=01][pad3][n=256][1024B] is NOT an INT
    slot: it is the framing coincidence of PTOK(1) + a 14FCSpeedSegment
    record run (ARRAY header + DEF/NKEY records) inside 11FCSpeedData
    objects, whose 1037-byte extent happens to end on a valid record start
    so _slot_end_ok cannot reject it. All 11 instances in palastin (0 in
    mc_*) carry tag=0x01, n=256, and an interior that re-tokenizes RAW-free
    and re-converges with the outer walk right after the slot end.

    Allocation: the interior records intern in the MAIN document scope only
    for the instance that also DEFINES key names (DEF events inside). The
    10 instances inside the MooVKeyG render-registry (0x437afd..0xcc18a0)
    are sub-document snapshots (own intern scope, keys appear only as NKEY
    reuse), so they allocate 0. Credit = (true-parse alloc sum) - (current
    alloc sum) over the byte window up to re-convergence, +1 for the leading
    typed ARRAY (pinned by four independent NKEY reuse constraints:
    segment=0xc011, inputUsed=0xc014, outputDuration=0xc015,
    anchorOffset=0xc016 — each exactly +1 above the uncredited numbering)."""
    global _IN_MEGA
    out = {}
    if _IN_MEGA:
        return out
    for i, e in enumerate(ev):
        if not (e[1] == "SLOT" and e[2] == 1 and e[3] == 0x01 and e[4] == 256):
            continue
        p = e[0]
        send = p + 13 + 4 * e[4]
        _IN_MEGA = True
        try:
            inner = [(p, "PTOK", 1)] + tokenize_scoped(d, p + 5, min(send + 4096, len(d) - 16))
            # R10b (session 7c): the DEF gate is REMOVED. The 10 registry
            # instances were assumed own-scope snapshots (credit 0); the
            # backbone self-ref ledger disproves that byte-exactly: each sits
            # in a window whose local drift equals THIS credit (-21 @0x4d9fc5,
            # -13 @0x4f99de, -18 @0x4fa490, -16 @0x525f96, -20 @0x62deaa,
            # -17 @0x6b116c, -17 @0x8c8d21, -19 @0x9d69dd, -20 @0xb80ef8,
            # -17 @0xc08f87), and the NKEY-172 self-uuid right after the
            # 0x4fa490 interior resolves exactly under credited numbering
            # (UUIDREF 67669 == id of the UUID @0x4fa924, which only holds
            # with the interior's 18 credits). mc_*/1.fcp: zero instances.
            # convergence: first inner event >= slot end matching the outer
            # stream in POSITION AND KIND with the next event aligned too
            # (position-only sync mis-fired at 0x525f96: inner INT vs outer
            # CNTW @0x5263af read credit 17; true resync @0x5263b9 gives 16
            # == the ledger step).
            outer = []
            j = i
            while j < len(ev) and ev[j][0] < send + 4096:
                outer.append((j, ev[j]))
                j += 1
            okey = {(t[0], t[1]): j for j, t in outer}

            def _scan(inn):
                for k, t in enumerate(inn):
                    if t[0] >= send and (t[0], t[1]) in okey:
                        oj = okey[(t[0], t[1])]
                        if (k + 1 < len(inn) and oj + 1 < len(ev)
                                and inn[k + 1][0] == ev[oj + 1][0]
                                and inn[k + 1][1] == ev[oj + 1][1]):
                            return t[0]
                return None

            # NESTED COINCIDENCE (EPK-class speed-segment chains): the interior
            # re-tokenization itself hits further SLOT(1,1,256) framing
            # coincidences.  Two byte-proven failure modes (EPK): the nested
            # read swallows the true resync point (@0x10a66d: inner SLOT
            # @0x10aa66 overshoots the outer resync @0x10aa7a, where the true
            # stream reads [PTOK][NKEY][T20 14FCSpeedSegment]) -> NO
            # convergence; or its fake ~1KB extent lands near the outer resync
            # so convergence SUCCEEDS with a near-zero delta while ~14 true
            # interior credits stay hidden.  So: expand every nested mega-slot
            # that the OUTER stream cannot see (an outer-visible one is its own
            # credited site — expanding it here would double-count), then scan.
            # palastin's 11 sites have no invisible nested slots, so this loop
            # never fires there (verified: allocation byte-identical).
            conv = _scan(inner)
            for _ in range(8):
                bound = conv if conv is not None else send + 4096
                nk = next((kk for kk, t in enumerate(inner)
                           if t[1] == "SLOT" and t[2] == 1 and t[3] == 0x01
                           and t[4] == 256 and p < t[0] < bound
                           and (t[0], "SLOT") not in okey), None)
                if nk is None:
                    break
                q = inner[nk][0]
                inner = inner[:nk] + [(q, "PTOK", 1)] + tokenize_scoped(
                    d, q + 5, min(send + 4096, len(d) - 16))
                conv = _scan(inner)
            # a RAW pocket BEYOND the convergence point is outside the credited
            # window and harmless; one before it means the re-parse is untrusted
            if conv is None or any(t[1] == "RAW" and t[0] < conv for t in inner):
                continue
            twin = [t for t in inner if t[0] < conv]
            cwin = [t for _, t in outer if t[0] < conv]
            delta = sum(final_allocs(twin, d)) - sum(final_allocs(cwin, d))
            if len(twin) > 1 and twin[1][1] == "ARRAY":
                delta += 1
        finally:
            _IN_MEGA = False
        if delta:
            out[i] = delta
    return out


def rule_extras(ev: list, d: bytes) -> dict:
    """{evidx: delta} for rules R1-R6 (session 6) + the session-7 merge rules
    (see module docstring)."""
    import struct
    u32 = lambda o: struct.unpack_from("<I", d, o)[0]
    n = len(ev)
    out = {}

    def add(i, v):
        out[i] = out.get(i, 0) + v

    stub_sites = []
    for i, e in enumerate(ev):
        k = e[1]
        pk = ev[i - 1][1] if i else None
        if k == "OBJINL" and pk == "DEF" and ev[i - 1][2] in ("NOUNDO", "RUNTIME"):
            add(i, -1)                                          # R1
        elif k == "DEF" and (e[2] == "mainDict"
                             or (R_CLIPTOP and e[2] == "clipTop")) and i + 1 < n \
                and ev[i + 1][1] == "OBJREF":
            # R2 (+ session-7 clipTop extension): DEF('mainDict'|'clipTop')
            # whose value is an OBJREF allocates a +1 stub. clipTop proof
            # (mc_two, byte-pinned): DEF clipTop true id 284 = pred; the member
            # root OBJINL1's own mainDict self-ref OBJREF(286) fixes root=286;
            # the owner GUIDREF(288) fixes OBJSLOTREF slots 287/288 => true id
            # 285 is allocated between the DEF and the root, i.e. by the OBJREF
            # value stub. 2/2 instances per corpus. NAME-GATED: byte-identical
            # [DEF clipItemPtr|workprint1..3|sequenceDict|subsequenceDict|
            # itemDict|clipPtr][OBJREF] pairs allocate 0 (their spans are exact).
            add(i, 1)
        elif k in _UNDO_S_BASE:                                 # R3 un-suppress
            v = _UNDO_S_BASE[k]
            if k == "OBJSLOTREF_S" and pk in GUIDPREV:
                v += 1
            if v:
                add(i, v)
        elif k == "DEF" and e[2] == "itemHistory" and i + 2 < n \
                and ev[i + 1][1] == "OBJINL_S" and ev[i + 2][1] == "SLOT" \
                and ev[i + 2][3] == 0x23:
            add(i, -1)                                          # R3 opener
        elif k == "DICT" and e[2] >= 2 and i >= 2 \
                and ev[i - 1][1] == "OBJINL_S" and ev[i - 2][1] == "NKEY" \
                and ev[i - 2][2] == 41:
            add(i, 1)                                           # R3 master stub
        elif k == "OBJSLOTREF" and pk in GUIDPREV:
            add(i, 1)                                           # R4
        elif k == "OTAGOBJ" and i >= 2 and pk in ("GUIDREF", "G10REF") \
                and ev[i - 2][1] in STRK:
            if not (R_UUIDHEAD and _uuid_headed(ev, i)):
                add(i, 1)                                       # R5 (R14-gated)
        elif R_NULLOBJ and k == "OBJREF" and e[2] == 0 \
                and pk == "NKEY" and i >= 2 and ev[i - 2][1] == "PTOK":
            # R-NULLOBJ: [00][u32 0] null object ref AS A COMPOSITE MEMBER.
            # Index 0 cannot be a table entry (base index is 2), so the ref
            # word is a null/pad: the reader interns a fresh empty placeholder
            # object (+1) — the exact dual of OBJEMPTY. Context split (event
            # census, 51 palastin instances): 43 sites are the NKEY(5) member
            # right after [OBJINL][ARRAY(5)][PTOK(1)] in the browser/viewer
            # composite -> +1 (per-span count == residual EXACTLY in 8 spans,
            # incl. browser_viewcode 19, editedVideo 10); the other 8 sites are
            # the NKEY(4) value inside a still/transition record
            # ([NKEY(26) F64 3000.0][VAL32(3)][NKEY(4)][OBJREF 0][NKEY(30)
            # INT 2]) -> 0 (uuid-selfref drift curve rises +1 across each of
            # the 3 url instances; the stillFrameOffset instance is that
            # span's exact +1 excess). Discriminator: ev[i-2] is PTOK (member
            # form) vs VAL32 (still-record form) — fully structural.
            add(i, 1)
        if k == "PTOK" and pk == "OBJINL" and i >= 2 and i + 1 < n \
                and ((ev[i - 2][1] == "DEF" and ev[i - 2][2] == "qtMetadata")
                     or (ev[i - 2][1] == "NKEY" and ev[i + 1][1] == "DEF"
                         and len(ev[i + 1][2]) > 40)):
            # R22: a qtMetadata block's entry-count PTOK is structural, not an
            # interned object (same family as R13/R20 count preludes).
            # Byte-proof: the second metadata entry references keyName/typeCode/
            # valueSize at NKEY 457/459/460 == the first entry's DEF ids ONLY
            # when this PTOK allocates 0 (EPK @0x5a30 PTOK 3, @0x6d3a PTOK 24 -
            # the two sites in the corpus; the >40-char metadata-key DEF gate
            # has zero sites in any RAW-free banked corpus by construction).
            add(i, -1)
        if R_PTOKBOX and k == "PTOK" and i + 2 < n and ev[i + 1][1] == "CNTW" \
                and ev[i + 2][1] == "BAREREF" and ev[i + 2][0] == ev[i + 1][0] + 4 \
                and e[2] == _boxrun_len(ev, i + 1):
            # R13: a PTOK immediately followed by a boxed-ref run (CNTW+BAREREF
            # LINKBOX units) whose VALUE equals the number of boxes is the box
            # list's COUNT prelude, not an interned object -> allocates 0.
            # Distinct from the STRUCT1E root of exact-span box lists, whose
            # a-value is a struct element count (=1), never the box count.
            # UNIQUE in palastin (1 site @0x3b5a07, value 4 == 4 boxes; 0 in
            # exact spans, 0 in mc_*). Removes the freeze-frame record's +1
            # over-allocation -> fixes the url span.
            add(i, -1)
        if R_KFBLOB and k == "KFBLOB":
            # R-KFBLOB: +1 per 15-byte BLOB_UNIT (e[3] = unit count). Each
            # unit is a flagged slot record (leading 01 01) inside the blob.
            # 12/12 palastin instances (u=3): bin_count -3 and categoryname -3
            # zero EXACTLY; 0 instances in exact spans and mc corpora.
            add(i, e[3])
        if R_BOXLIST and k == "VAL32" and e[3] == 16 and e[2] in (3, 4, 5) \
                and d[e[0] + 9] == 1 and d[e[0] + 10] == 0:
            # R16: render-preset box list (session 7c). True credit is
            # 2 per unit except the head unit (1), i.e. 2t-1: t=5 sites
            # (extent accidentally right) natively credit 8 of 9; t=3 sites
            # 2 of 5; t=4 sites 0 of 7. Byte-proof: window-A pins (UUIDREF
            # 65665 -> UUID@0x4cfef6 gap 0 BEFORE, self-uuid UUIDREF 65700 ->
            # UUID@0x4d096b gap +7 AFTER) bracket the full -7 inside the
            # t=4 construct @0x4d0770; both t=4 windows read exactly -7,
            # both t=3 sites' tails are byte-identical; the t=5 twin
            # @0x4fd31b reads -1 between its local pins (67797 -> 67852).
            # Credit only byte-verified units (found == t at all 10 sites);
            # native CNTW/OBJSLOTREF events at unit positions keep their
            # weight, the swallowed remainder lands here. mc_*/1.fcp: 0.
            units = _boxlist_units(d, e[0], e[2])
            if len(units) == e[2]:
                upos = set()
                for uq in units:
                    upos.add(uq)          # CNTW word (LINKBOX credit)
                    upos.add(uq + 10)     # OBJSLOTREF
                native = 0
                for j in range(i + 1, min(i + 90, n)):
                    if ev[j][0] > units[-1] + 21:
                        break
                    if ev[j][0] in upos and ev[j][1] in ("CNTW", "OBJSLOTREF"):
                        native += 1
                add(i, max(0, 2 * len(units) - 1 - native))
        if R_MASTERSTUB and k == "OTAGOBJ" and i and pk in ("GUIDREF", "G10REF") \
                and i + 2 < n and ev[i + 1][1] == "NKEY" \
                and ev[i + 2][1] == "STRINL" \
                and not any(ev[j][1].endswith("_S")
                            for j in range(max(0, i - 4), min(i + 9, n))):
            stub_sites.append(i)
    # R15 (session 7c): SHAPE-based T0C weights, replacing the legacy R6
    # MooV-radius suppression. The backbone self-ref ledger decomposes into
    # per-record windows; tabulating T0C shapes against the exact window
    # gaps solves the weights with zero free parameters (win7/stair*.py):
    #   RENDref (itemRender-dict ref-form)      -> 0   (395 sites)
    #   SEref   (registry start/end-dict ref)   -> 0   (1324 sites)
    #   every other T0C (media ref/inline, wave, render-inline) -> 1
    # Validation: 3830/3882 ledger windows read EXACTLY 0 under this rule
    # (was: +-1 staircases + a +55 pocket); the browser_opensequence span
    # zeroes; only the two currently-bad spans move (delta +8 / -183);
    # 0 rule sites in mc_*/1.fcp. The remaining 52 windows are non-T0C
    # residue (see module docstring).
    if R_T0CSHAPE:
        for i, e in enumerate(ev):
            if e[1] != "T0C":
                continue
            if _t0c_rendref(ev, i, n) or _t0c_seref(ev, i, d):
                add(i, -1)
    # FILESPEC positions (used by the master-stub gates below)
    fs = []
    for i, e in enumerate(ev):
        if e[1] == "FILESPEC":
            a0, l0 = e[3][0]
            fs.append((i, e[0], b"MooVKeyG" in d[a0:a0 + l0]))
    if R_T0CMOOV:
        for kk, (i, pos, moov) in enumerate(fs):
            if not moov:
                continue
            j0 = fs[kk - 1][0] if kk > 0 else 0
            for j in range(i, j0, -1):
                if pos - ev[j][0] > 4096:
                    break
                e = ev[j]
                if e[1] == "T0C":
                    p = e[0]
                    if d[p + 6] == 0 and d[p + 11] == 0:
                        add(j, -1)
    # R-MASTERSTUB: master-clip guid-slot stub [GUIDREF][OTAGOBJ][NKEY name]
    # [STRINL] allocates +1 (fresh master registration).
    if R_MASTERSTUB:
        import bisect
        moovpos = sorted(pos for _, pos, moov in fs if moov)
        fspos = sorted(pos for _, pos, _ in fs)
        for i in stub_sites:
            p = ev[i][0]
            if R_MASTERSTUB in ("fx", "pmfx"):
                # fx gate: skip stubs inside a MooVKeyG entry header window
                j = bisect.bisect_left(moovpos, p)
                if j < len(moovpos) and moovpos[j] - p <= 4096:
                    continue
            if R_MASTERSTUB in ("pm", "pmfx"):
                # pm gate: the media item registered its OWN file alias — a
                # FILESPEC event in the immediately preceding record run
                fresh = False
                for j in range(i - 1, max(i - 15, -1), -1):
                    kk = ev[j][1]
                    if kk == "FILESPEC":
                        fresh = True
                        break
                    if kk in ("OTAGOBJ", "DEF", "STRINL", "SUUID", "T0C",
                              "OBJINL", "OBJINL1"):
                        break
                if not fresh:
                    continue
            add(i, 1)
            if R_MASTERSTUB_T0C:
                # fx coupling: ref-form T0C (flags 0,0) in the SAME record as
                # the stub allocates 0, not 1
                for j in range(i - 1, max(0, i - 120), -1):
                    kj = ev[j][1]
                    if kj == "T0C":
                        pj = ev[j][0]
                        if d[pj + 6] == 0 and d[pj + 11] == 0:
                            add(j, -1)
                        break
                    if kj == "OTAGOBJ":
                        break
    if R_MEGASLOT:
        for i, v in _megaslot_credit(ev, d).items():
            add(i, v)
    # R17 STUBT0C (session 8, tree-ancestry session): the fresh-vs-copy
    # coupling of report_d's "honest residual", byte-pinned per site.
    #
    # A FRESH master registration = a stub-credited OTAGOBJ (R5/R11 above,
    # uuid-less record head per R14) whose member run serializes the master
    # wrapper's own clip element with an INLINE masterClips uuid
    # ([OBJINL][DICT 1][NKEY][UUID]) and a double-ref 'file' T0C (f00).
    # That T0C consumes NO table id: the drift-profile bracket (refs from
    # copies anywhere in the file) pins the +1 jump EXACTLY across the T0C
    # at 25/25 palastin sites (probe/anc/persite.py; the staircase core
    # 0xadea2b..0xaef1b3 plus 0x7425bd.., 0xa03b34.., 0xafc251, 0xb0296e),
    # while the stub credit itself reads CORRECT at every one of them.
    # RE-SERIALIZED records (uuid-headed, stub suppressed by R14; e.g. the
    # 44 [T0Cinl + suppressed-R5] windows, and every record in the dup_one
    # oracle corpus) keep T0C=1 — dup_one byte-proves the weight-1 side
    # with zero drift (13/13 UUIDREF, 15/15 STRREF, backbone D=0).
    # Discriminator inside the run, scanning stub -> T0C:
    #   * [OBJINL][DICT 1][NKEY][UUID]  = the masterClips inline master-uuid
    #     motif: the record binds a FRESHLY-minted master identity -> the
    #     f00 'file' T0C that follows allocates 0;
    #   * any OTHER keyed inline UUID (the bare persistent-uuid member,
    #     key 'UUID'/172 in palastin) = re-serialized snapshot -> abort
    #     (T0C keeps 1; 3 such stub-credited sites incl. 0x9dd930, all in
    #     exact-reading windows);
    #   * a keyed UUIDREF (master identity re-used) -> abort (T0C 1; the
    #     131-window balanced fresh-FILESPEC form);
    #   * only the FIRST T0C of the run is the coupled 'file' member.
    # Firings: palastin exactly the 25 pinned sites; mc_one..four, 1.fcp,
    # dup_one: ZERO.
    if R_STUBT0C:
        for i in list(out):
            if out[i] <= 0 or ev[i][1] != "OTAGOBJ":
                continue
            motif = False
            for j in range(i + 1, min(i + 240, n)):
                kj = ev[j][1]
                if kj in ("OTAGOBJ", "DEF", "FILESPEC", "T20", "RAW"):
                    break
                if kj == "UUID":
                    if (j >= 3 and ev[j - 1][1] == "NKEY"
                            and ev[j - 2][1] == "DICT" and ev[j - 2][2] == 1
                            and ev[j - 3][1] == "OBJINL"):
                        motif = True            # masterClips master-uuid
                        continue
                    break                       # persistent-uuid member
                if kj == "UUIDREF":
                    break                       # re-used master identity
                if kj == "T0C":
                    pj = ev[j][0]
                    if (motif and d[pj + 6] == 0 and d[pj + 11] == 0
                            and out.get(j, 0) >= 0):
                        add(j, -1)
                    break
    # ------------------------------------------------------------------
    # SESSION 9 (multiclip-oracle session, probe/bc): pocket rules for the
    # T20-multiclip class body and clipList registry — the constructs live
    # inside tokenize() RAW pockets that exist ONLY in multi_one.fcp (all
    # other corpora walk with RAW=0, verified), so these rules are
    # zero-regression by construction.
    #
    # R19 CLSNAME: an inline nested class-name unit [01][u32 L][L ascii,
    #   digit-prefixed mangled name] interns +1 (like T20's own name). The
    #   tokenizer RAWs the unit when an earlier misparse ate its [01][L]
    #   header (multi_one '6CAngle' @0x1a40: preceding INT swallowed the
    #   header, so no PTOK credit was recorded). When the header WAS
    #   tokenized as PTOK(L) the +1 is already credited — suppressed here.
    #   Byte-proof: multi_one true ids 259/260 ('20CMulticlipSharedInfo',
    #   '6CAngle') pinned by UUIDREF(258)x2 (uuid E86F.. = 258) and the
    #   multiclip record's k14 OBJREF(261) == its own OBJSLOTREF head.
    # R20 PTOK32ARR: PTOK(0x20) immediately followed by an adjacent CNTW is
    #   the clipList named-array header [01][20 00 00 00][u32 C] misparse —
    #   a structural header, allocates 0 (PTOK's +1 withdrawn). Pinned by
    #   the registry bracket: D=+3 on both sides of the pocket with exactly
    #   4 true allocs inside (walker credited 6).
    # R21 PTOKUUIDHDR: PTOK(0x22) with d[p+5]==0 is a slot-uuid header
    #   [01][22 00 00 00] whose uuid is the REF form ([00][u32 ref]) — no
    #   inline literal, allocates 0. (The inline form has the length word
    #   at p+5, low byte != 0, e.g. 0x24 — multi_one @0x19db keeps its +1.)
    # ------------------------------------------------------------------
    if R_CLSNAME:
        for i, e in enumerate(ev):
            k = e[1]
            p = e[0]
            if k == "RAW":
                # only at a RAW-run start
                if i and ev[i - 1][1] == "RAW" and ev[i - 1][0] == p - 1:
                    continue
                if p < 5 or d[p - 5] != 1:
                    continue
                L = u32(p - 4)
                if not (4 <= L <= 0x40) or not d[p:p + 1].isdigit():
                    continue
                unit = d[p:p + L]
                if not (unit[:1].isdigit()
                        and all(0x20 <= c < 0x7f for c in unit)):
                    continue
                if ev[i - 1][1] == "PTOK" and ev[i - 1][2] == L \
                        and ev[i - 1][0] == p - 5:
                    continue                    # header already credited
                add(i, 1)                                       # R19
            elif k == "PTOK" and e[2] == 0x20 and i + 1 < n \
                    and ev[i + 1][1] == "CNTW" and ev[i + 1][0] == p + 5:
                add(i, -1)                                      # R20
            elif k == "PTOK" and e[2] == 0x22 and d[p + 5] == 0:
                add(i, -1)                                      # R21
    return out


_GUID_REF_KINDS = frozenset(("GUIDREF", "G10REF", "SLOTGUIDREF"))


def rule_extras2(ev: list, allocs: list) -> dict:
    """R-SEQDICT (pm1 R7, sequential pass on top of the accumulated model):
    a sequence object's mainDict entry [NKEY][OBJREF r] right after its boxed
    slot pair [GUIDREF][OBJSLOTREF] (2 slots s, s+1), where r == s (the ref
    points at the record's OWN first slot) and the next two GUID-refs both
    point at r+2, allocates ONE extra hidden slot (the mainDict stub, id r+2).
    Copies of the same sequence use r == the ORIGINAL's slot id (strictly
    smaller) and allocate nothing."""
    out = {}
    n = len(ev)
    cum = FINAL_BASE
    last_slot = None      # (evidx, first-slot id)
    for i, e in enumerate(ev):
        a = allocs[i]
        k = e[1]
        # R18 GENSTUB (session 8): the STRREF-named generator-master stub.
        # The gen_one oracle corpus (zero drift; gap 1.000, STRREF 7/7,
        # UUIDREF 7/7) byte-proves the fresh generator-master record form:
        # [labelComment STRINL][GUIDREF class][OTAGOBJ +STUB][alphatype INT]
        # [name][itemspec STRUCT1E][UUID inline][masterClips OBJINL DICT
        # {orphan/master UUIDREF -> the record's OWN uuid id}] — the
        # backbone reads D=0 only WITH the stub (a=2), and the masterClips
        # refs are SELF-refs. palastin's 'Texte' master @0x3e0f6d is the
        # same construct with its name serialized as a STRREF (the string
        # 'Texte' was already interned), which fails R5's STRINL gate; its
        # orphan self-ref reads own-uuid+1 = exactly the missing stub.
        # The two registry twins @0x841a3b/0x8e5473 match the shape but
        # their orphan refs point at EARLIER masters (deltas -4/-7): they
        # are copies and allocate nothing — the id-equation gate (self-ref
        # == cum-uuid-id + 1, evaluated sequentially like R12) fires at
        # exactly ONE site in all corpora (0x3e0f6d).
        if (R_GENSTUB and k == "OTAGOBJ" and a == 1 and i >= 5
                and ev[i - 1][1] == "GUIDREF" and ev[i - 2][1] == "STRREF"
                and ev[i - 3][1] == "NKEY" and ev[i - 4][1] == "INT"
                and ev[i - 5][1] == "NKEY"):
            # forward shape: [NKEY][STRUCT1E][NKEY][UUID inline] then
            # [NKEY][OBJINL][DICT 1|2][NKEY][UUIDREF X]
            j = i + 1
            u_id = None
            x = None
            if (j + 3 < n and ev[j][1] == "NKEY" and ev[j + 1][1] == "STRUCT1E"
                    and ev[j + 2][1] == "NKEY" and ev[j + 3][1] == "UUID"):
                # cum at the UUID event = cum + allocs of events i..j+2
                u_id = cum + a + sum(allocs[t] for t in range(j, j + 3))
                for t in range(j + 4, min(j + 12, n - 4)):
                    if (ev[t][1] == "NKEY" and ev[t + 1][1] == "OBJINL"
                            and ev[t + 2][1] == "DICT" and ev[t + 2][2] <= 2
                            and ev[t + 3][1] == "NKEY"
                            and ev[t + 4][1] == "UUIDREF"):
                        x = ev[t + 4][2]
                        break
                    if ev[t][1] in ("OTAGOBJ", "DEF", "FILESPEC"):
                        break
            if u_id is not None and x == u_id + 1:
                out[i] = out.get(i, 0) + 1
                a += 1
        if k == "OBJSLOTREF" and a >= 2:
            last_slot = (i, cum)
        elif k == "OBJREF" and last_slot is not None and i - last_slot[0] <= 6:
            r = e[2]
            if r == last_slot[1]:
                gs = [ev[j][2] for j in range(i + 1, min(i + 14, n))
                      if ev[j][1] in _GUID_REF_KINDS][:2]
                # G10INL-head gate (session 7c): the id-topology test compares
                # FILE ref values against MODEL cum ids, so in drifted regions
                # it can match by coincidence (it flipped 0xcc8916 -> 0x496b80
                # when R15 moved the tail drift, +1-breaking the exact
                # renderSettings..categoryname span). The byte-proven stub
                # sites (mc_one 0x1962 / mc_two 0x1d35 / mc_three 0x1fc0 /
                # mc_four 0x22ef / pal 0x81e2) all carry the INLINE tag-0x10
                # GUID (G10INL, first serialization of the sequence head) a
                # few events before the mainDict entry; the false-positive
                # records carry the ref form (G10REF) or no G10 at all.
                if len(gs) == 2 and gs[0] == gs[1] == r + 2 \
                        and any(ev[j][1] == "G10INL"
                                for j in range(max(0, i - 14), i)):
                    out[i] = out.get(i, 0) + 1
                    a += 1
        cum += a
    return out


def final_allocs(ev: list, d: bytes) -> list[int]:
    base = _base_final_allocs(ev)
    for i, v in rule_extras(ev, d).items():
        base[i] += v
    if R_SEQDICT:
        for i, v in rule_extras2(ev, base).items():
            base[i] += v
    return base


def object_table(d: bytes, lo: int = 0x2e, hi: int | None = None) -> dict:
    """Sequential intern table under the crush rules; extra credits beyond a
    kind's base weight appear as ('XSLOT', None) entries."""
    if hi is None:
        hi = len(d)
    hi = min(hi, len(d) - 16)                # leave a read margin (tokenize peeks d[p+n])
    ev = tokenize_scoped(d, lo, hi)
    allocs = final_allocs(ev, d)
    c = FINAL_BASE
    table = {}
    for a, e in zip(allocs, ev):
        if a <= 0:
            continue
        k = e[1]
        if k in FINAL_GUID_KINDS:
            if a == 3:
                table[c] = ("class", e[-1].hex()); c += 1
            table[c] = ("guidtrailer", None); c += 1
            table[c] = ("guidtrailer", None); c += 1
            continue
        val = None
        if k in FINAL_STR_KINDS or k in FINAL_UUID_KINDS or k in ("DEF", "T20"):
            val = e[2] if len(e) > 2 else None
        table[c] = (k, val); c += 1
        for _ in range(a - 1):
            table[c] = ("XSLOT", None); c += 1
    return table




def key_ids(d: bytes, lo: int = 0x2e, hi: int | None = None) -> dict:
    """Map each named key to the object id assigned at its first definition."""
    ids: dict[str, int] = {}
    for i, (k, v) in object_table(d, lo, hi).items():
        if k == "DEF" and v not in ids:
            ids[v] = i
    return ids


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "/Users/davidrice/fcpshare/palastin.fcp"
    raw = Path(path).read_bytes()
    d = raw + b"\x00" * 64
    ev = tokenize(d, 0x2e, len(raw))
    nraw = sum(1 for e in ev if e[1] == "RAW")
    print(f"events={len(ev)} RAW={nraw} last={ev[-1][0]:#x} of {len(raw):#x}")
    ids = key_ids(d, 0x2e, len(raw))
    for k in ("in", "mainDict", "name", "start", "end", "offline", "link",
              "itemspec", "itemRender", "channel"):
        if k in ids:
            print(f"  {k:12s} id={ids[k]:#x}")
