"""GROUPER for KeyGrip (.fcp) projects: sequences -> ordered clipitems.

grouper(fcp_path) -> [{"name": str|None,
                       "items": [{"name","in","out","start","end","file"}]}]
one dict per PROJECT sequence in document order; items are the sequence's
clipitems track by track (vidm tracks then audm tracks, clips in array
order), transitions/generators excluded, nested-sequence/subclip uses
included as items named after the referenced sequence.

Validated (2026-07): mc_one/mc_two/mc_four reproduce their known
1-sequence/N-clip groupings exactly (clip names + in/out/start/end);
palastin.fcp vs FCP's own export (palgt2.xml): 22/22 sequences found
(GATE A counts 22/22 exact), ordered (in,out,start,end) tuples 3852/3852
(GATE B 1.0000), masters (1245 wrappers) excluded and all 19 nested
sequence uses present (GATE C; 18/19 with exact names, 1 unresolved).
Item names 3671/3852 match FCP's export (the rest are FCP-side
master-name substitutions for empty clip names the object table cannot
resolve yet -- the walker's residual allocation drift).

Layers (all byte-validated on mc_* first, then palastin):

1. EVENT SPLICES over keyg_walker2.tokenize_scoped: two known tokenizer
   misframes re-tokenized in place (SLOT(1,1,256) "megaslot" speed-segment
   runs; VAL32(t,16) sequence-preset box lists).
2. CONTAINMENT TREE (frame machine; every event attaches to exactly one
   node): KEY->one value; object bodies DICT(C)/PRELUDE(N)/ARRAY/SLOT-run/
   CNTW with EXACT counts; DICT(0) is always CLOSED (the 13-zero "open
   viewers" reading steals the next record: byte-proof in _dict0_is_open);
   OTAGOBJ is a mid-record registration marker, never a container; T20
   typed objects have a bounded extent (PTOK(C) head + positional tail);
   subsequence-link records (sequenceDict/subsequenceDict/itemDict/spec)
   and channel-dict itemHistory are uncounted.
3. SEQUENCE CENSUS: sequence-shaped dicts (media.vidm/audm) that are
   timeline-flavored (seqProps/tcData/selectionIn/selectionOut/reels vs
   the master-clip metadata keys scene/take/lognote/comment1/labelComment)
   with no sequence-shaped ancestor.  Masters and embedded copies fail
   this; the empty default sequence of a fresh project passes (it IS a
   project sequence -- mc files carry sequence_count=2).
4. NAMES: STRINL inline; STRREF via object_table; unresolved refs retried
   with canon-anchored drift correction (mainDict self-refs are byte-true
   ids); empty names take the master-clip name (FCP's own xmeml rule);
   nested uses take the embedded copy's name, inherited across duplicated
   timelines when unambiguous.

Only additive use of keyg_walker2 (tokenize/tokenize_scoped/final_allocs/
object_table/FINAL_BASE); the walker is unchanged.
"""
from __future__ import annotations

import bisect
import struct
import unicodedata
from pathlib import Path
from urllib.parse import quote, unquote

try:
    from . import keyg_walker2 as W
except ImportError:                      # standalone execution
    import keyg_walker2 as W

_u32 = lambda d, o: struct.unpack_from("<I", d, o)[0]



# ---------------------------------------------------------------------------
# node
# ---------------------------------------------------------------------------


class Node:
    __slots__ = ("i", "off", "kind", "role", "name", "value", "count",
                 "children", "parent", "flags", "_hi", "_emap")

    def __init__(self, i, off, kind, role, name=None, value=None, count=None):
        self.i = i              # event index (-1 for the synthetic root)
        self.off = off
        self.kind = kind        # event kind (or ROOT/OPENELEM)
        self.role = role        # root|key|value|element|glue|header|payload
        self.name = name        # DEF name / NKEY id for key nodes
        self.value = value      # scalar payload for leaf values
        self.count = count      # declared member/element count (containers)
        self.children = []
        self.parent = None
        self.flags = 0          # 1=open container, 2=isolated, 4=violation,
        #                         8=spurious clip-OBJREF link (uncounted)
        self._hi = None         # memoized max subtree offset (_subtree_hi)
        self._emap = None       # memoized key -> value-node map (entry_map)

    def add(self, ch):
        ch.parent = self
        self.children.append(ch)

    # -- navigation -------------------------------------------------------
    def entries(self):
        """(key, value-node) pairs of this container's keyed entries.
        Open (zero-prelude) member objects such as OTAGOBJ are transparent:
        their entries surface at this level (that is how they count)."""
        out = []
        for ch in self.children:
            if ch.role == "key":
                v = ch.children[0] if ch.children else None
                out.append((ch.name, v))
            elif ch.flags & 1 and ch.role != "element":
                out.extend(ch.entries())
        return out

    def entry_map(self):
        """key -> first value-node, transparent through open member objects,
        memoized (the tree is static once build_tree returns; nothing queries
        nodes during construction).  setdefault in child order reproduces
        get()'s first-match-wins EXACTLY.  Turns the drift machinery's
        repeated probe scans over one node into a single subtree pass + dict
        hits (a 4124-item project spent 90 s re-scanning clip subtrees for
        one absent key)."""
        m = self._emap
        if m is None:
            m = {}
            for ch in self.children:
                if ch.role == "key":
                    if ch.children and ch.name not in m:
                        m[ch.name] = ch.children[0]
                elif ch.flags & 1 and ch.role != "element":
                    for k, v in ch.entry_map().items():
                        m.setdefault(k, v)
            self._emap = m
        return m

    def get(self, key):
        """Value node of the first entry whose key (DEF name or NKEY id)
        equals `key` (transparent through open member objects)."""
        return self.entry_map().get(key)

    def get_all(self, key):
        out = []
        for ch in self.children:
            if ch.role == "key" and ch.name == key and ch.children:
                out.append(ch.children[0])
            elif ch.flags & 1 and ch.role != "element":
                out.extend(ch.get_all(key))
        return out

    def elements(self):
        """Element value-nodes of this array/prelude container, in order."""
        return [ch for ch in self.children if ch.role == "element"]

    def walk(self):
        stack = [self]
        while stack:
            n = stack.pop()
            yield n
            stack.extend(reversed(n.children))

    def __repr__(self):
        nm = f" {self.name!r}" if self.name is not None else ""
        vl = f"={self.value!r}" if self.value is not None else ""
        ct = f" n={self.count}" if self.count is not None else ""
        return f"<{self.kind}{nm}{vl}{ct} @{self.off:#x} {self.role}>"


# ---------------------------------------------------------------------------
# event-kind classes
# ---------------------------------------------------------------------------

def _core(k):
    return k[:-2] if k.endswith("_S") else k

# scalar / self-contained values (complete immediately)
SCALARS = frozenset((
    "INT", "F64", "F32", "BOOL", "FOURCC", "STRINL", "STRREF", "UUID",
    "UUIDREF", "DATA07", "DATA07REF", "BLOBINL", "BLOBREF", "STRUCT1E",
    "FIXED", "KFBLOB", "OBJREF", "OBJEMPTY", "T20REF", "OTAGREF", "VUNK",
    "G10REF", "G10INL",
    "T16TIME",   # v0x16 dialect keyed time value (F64 + timebase), PPC projects
))

# glue: uncounted leaf members of the current container
# (OTAGOBJ: mid-record object-registration marker -- never a container; its
#  members flow into the enclosing counted scope.  As an ELEMS "element" the
#  real element is the object that follows the marker.  nav/tree.py proven.)
GLUE = frozenset((
    "GUIDINL", "GUIDREF", "GUIDREF2", "G10REF", "G10INL", "G10TRAILER", "FNREC",
    "GUIDORPH", "SLOTGUIDINL",
    "SLOTGUIDREF", "PTOK", "BAREREF", "FILESPEC", "OBJSLOTREF", "OBJSLOTINL",
    "CNTW", "SLOT", "VAL32", "RAW", "OBJEMPTY", "STRUCT1E", "KFBLOB", "FIXED",
    "OTAGOBJ",
    # REFARRAY: a PTOK-counted array of [00][u32 ref][0x18 tag] units (an effect
    # keyframe/point ref-list, e.g. Rat King motion geometry).  The walker emits
    # it as ONE glue token so its N ref-units count as ZERO dict members; parsed
    # per-unit they would each complete a keyed member and drain the enclosing
    # channel DICT, closing vidm early and orphaning audm.
    "REFARRAY",
))

# payload events: attach to the nearest preceding carrier node of given kind
PAYLOAD = {
    "SSTRINL": "SLOT", "SREF": "SLOT", "SUUID": "SLOT", "SGUIDINL": "SLOT",
    "SOBJREF": "SLOT", "VSTRINL": "VAL32", "VREF": "VAL32", "VUUID": "VAL32",
    "ASTRINL": "ARRAY", "AREF": "ARRAY",
}

OBJHEADS = frozenset(("OBJINL", "OBJINL1", "OTAGINL", "SOBJINL", "T20"))

# frame types
F_ROOT, F_DICT, F_ELEMS, F_OPEN, F_KEY, F_SLOTBODY, F_T20 = range(7)

# key ids/names whose records do NOT consume the enclosing dict budget
# (the subsequence-link block; set per corpus via key_ids before build)
UNCOUNTED_KIDS: frozenset = frozenset()

# The `clip`-keyed OBJREF link record is a first-class clipitem member in the
# linked-clip dialect (the clip/type/link triple, e.g. RESP 533: clip->type)
# but a SPURIOUS inserted link in the file-clipitem dialect (mcsilver 'Main SD
# seq.': the record sits between `end` and `file`).  If it is COUNTED there the
# clipitem meets its member budget one entry early, its trailing member escapes
# UP into the enclosing vidm dict, and that shift cascades so media's 2nd slot
# lands off the audm channel -- every audio track is dropped.  Byte-gated to
# the file-clipitem dialect via CLIP_LINK_ID/FILE_KEY_ID (set per-doc in
# _configure): uncounted only when the clip-OBJREF's next member is `file`, so
# the linked-clip dialect (clip->type) is left byte-identical.
CLIP_LINK_ID = None    # `clip` DEF id, or None when the doc has no such key
FILE_KEY_ID = None     # `file` DEF id, or None

# itemHistory is a counted entry of ITEM dicts (clipitems/tracks; byte-proven
# by their declared counts) but NEVER of a media-CHANNEL dict (vidm/audm):
# the single such site in all corpora (palastin @0x56e578, the '- copie'
# sequence) breaks its vidm count and displaces audm if counted.  Channel
# dicts' legit entries are width/height/track/destMap/depth/player_distort/
# sampleRate only (population census).
CHANNEL_UNCOUNTED: frozenset = frozenset()   # {'itemHistory', its key id}
CHANNEL_KEYS: frozenset = frozenset()        # {'vidm','audm', their ids}

# The `track` DEF id (per-doc, set in _Doc._configure).  Gates the sparse-track
# channel-unwind (trigger B): a `track`-keyed object ELEMS whose declared element
# count exceeds the serialized element heads never closes by count, so it would
# ABSORB the following media-channel members (vidm-tail keys then audm -- the
# whole audio channel) as phantom array fields, severing media.get('audm').  When
# such a HUNGRY track ELEMS meets a media-CHANNEL key it is force-closed and its
# enclosing channel dict unwound so the channel key resumes under the MEDIA dict.
# None when the doc has no `track` key (the gate then never fires).
TRACK_KEY_ID = None

# The `filters` DEF id (per-doc, set in _Doc._configure).  Gates the count-less
# effect-glue close (v0x14 color-corrector param objects): see build_tree.
FILTERS_KEY_ID = None

# The `type`/`in`/`out` DEF ids (per-doc, set in _Doc._configure).  Gate the
# spilled-marker close (trigger E): a marker DICT carries in/out but never a
# `type` key, so a marker that spilled out of a clip's undercounted markers list
# is told apart from a real (always type-bearing) timeline element.
TYPE_KEY_ID = None
IN_KEY_ID = None
OUT_KEY_ID = None


class Frame:
    __slots__ = ("ftype", "node", "left", "iso", "kmode", "elem_key", "kelem",
                 "sawfs")

    def __init__(self, ftype, node, left=0):
        self.ftype = ftype
        self.node = node
        self.left = left       # remaining budget (DICT entries / ELEMS)
        self.iso = False       # counting barrier (unused; kept for debug)
        self.kmode = None      # ELEMS flavor: None | "object" | "keyed"
        self.elem_key = None   # keyed flavor: the (constant) element key
        self.kelem = False     # KEY frame: this key IS an element
        self.sawfs = False     # object ELEMS: the current element's trailing
                               #   FILESPEC has been seen — the next KEYED
                               #   record ends a SPARSE array early


def _dict0_is_open(d, off, nxt_kind):
    """DICT(0) is ALWAYS closed. Byte proof (palastin): the header's
    RUNTIME->viewers @0x82 and a filter's NOUNDO->viewers @0x359635 are
    byte-identical ([00 00 00 00 01 01] + 13 zeros + DEF), yet the filter
    dict's declared count (6) matches its entries only when 'viewers'
    COUNTS as NOUNDO's single entry -- i.e. the empty dict is closed and
    following records belong to the ENCLOSING container.  Treating the
    13-zero form as open steals the next record into the empty dict's
    owner and cascades (the big-sequence truncation bug)."""
    return False


def _t0c_inline_count(d, off):
    """T0C = [0c][pad3][a][01][f1][u32 w1][f2][u32 w2].
    inline (f1,f2)=(1,1), w1==0 -> member count w2; ref form -> None."""
    if d[off + 6] == 1 and d[off + 11] == 1 and _u32(d, off + 7) == 0:
        return _u32(d, off + 12)
    return None


def _leaf_count(d, off):
    """LEAF = [00][pad3][a][mk=1][u32 0][01][u32 W] -> W."""
    return _u32(d, off + 11)


# ---------------------------------------------------------------------------
# the consumer
# ---------------------------------------------------------------------------

def build_tree(events, d):
    """Arrange the scoped event stream into a containment tree.
    events: keyg_walker2.tokenize_scoped(d, ...) output; d: the file bytes
    (padded like the walker expects). Returns the root Node; diagnostics in
    root.value (dict): violations, open_at_eof."""
    root = Node(-1, 0, "ROOT", "root")
    stack = [Frame(F_ROOT, root)]
    violations = []
    n = len(events)
    i = 0
    _V14 = len(d) > 0x33 and d[0x2e] == 1 and _u32(d, 0x2f) == 0x14

    def top():
        return stack[-1]

    def counted_entry_done():
        """A keyed entry completed: bubble one count to the nearest counted
        frame, skipping OPEN frames and the KEY frames beneath them (a key
        whose value is open is part of the transparent chain); stop at
        ELEMS/ISOLATE/ROOT (uncounted)."""
        for f in reversed(stack):
            if (f.ftype == F_OPEN and not f.iso) or f.ftype == F_KEY:
                continue
            if f.ftype in (F_DICT, F_T20):
                f.left -= 1
            return

    def pop_completed():
        """Lazily pop frames that are complete: DICT/ELEMS with no budget
        left, plus OPEN frames (and their KEY frames) sitting above a
        completed counted frame."""
        while len(stack) > 1:
            f = top()
            if f.ftype in (F_DICT, F_ELEMS) and f.left <= 0:
                stack.pop()
                value_completed()
                continue
            if f.ftype == F_OPEN and not f.iso:
                # an open frame closes when the counted frame below it is
                # complete (transparent membership)
                done = False
                for g in reversed(stack[:-1]):
                    if (g.ftype == F_OPEN and not g.iso) or g.ftype == F_KEY:
                        continue
                    done = (g.ftype == F_DICT and g.left <= 0)
                    break
                if not done:
                    return
                stack.pop()              # close the open frame
                value_completed()        # pops its KEY frame (uncounted)
                continue
            return

    def value_completed():
        """The value subtree on top of the stack finished: close the KEY
        frame (if any) and count the entry / element."""
        f = top()
        if f.ftype == F_KEY:
            stack.pop()
            if f.node.flags & 8:
                return               # spurious clip-OBJREF link record: uncounted
            if f.node.name in UNCOUNTED_KIDS:
                return               # link-block record: uncounted
            if f.node.name in CHANNEL_UNCOUNTED:
                dn = f.node.parent
                kk = dn.parent if dn is not None else None
                if kk is not None and kk.role == "key" \
                        and kk.name in CHANNEL_KEYS:
                    return           # itemHistory in a channel dict: uncounted
            if f.kelem:
                # keyed element (sparse viewArray form): counts against the
                # ELEMS frame, not the nearest dict
                if top().ftype == F_ELEMS:
                    top().left -= 1
                return
            # key of an OPEN value does not count (viewers rule)
            v = f.node.children[0] if f.node.children else None
            if v is None or not (v.flags & 1):
                counted_entry_done()
        elif f.ftype == F_ELEMS:
            if f.node.children and (f.node.children[-1].flags & 4):
                return               # spilled marker (trigger E): parsed but not
                #                      a counted element -> preserve array budget
            f.left -= 1
            f.kmode = f.kmode or "object"

    def attach_value(node, open_=False):
        """Attach a value node under the current KEY/ELEMS/OPEN frame."""
        f = top()
        if f.ftype == F_KEY:
            node.role = "value"
        elif f.ftype == F_ELEMS:
            node.role = "element"
        f.node.add(node)
        if open_:
            node.flags |= 1
        return node

    def start_body(node, j):
        """Node is an object head at event j; open its body frame based on
        the following event. Returns the next event index to process."""
        e = events[j]
        k = _core(e[1])
        nk = _core(events[j + 1][1]) if j + 1 < n else None
        if k == "LEAF":
            w = _leaf_count(d, e[0])
            if w > 0:
                stack.append(Frame(F_DICT, node, w))
                node.count = w
            else:
                node.count = 0
                value_completed()
            return j + 1
        if k == "T0C":
            w = _t0c_inline_count(d, e[0])
            if w:
                stack.append(Frame(F_DICT, node, w))
                node.count = w
            else:
                value_completed()        # double-ref leaf
            return j + 1
        # OBJINL / OBJINL1 / OTAGINL / SOBJINL: body from next event
        if nk == "DICT":
            he = events[j + 1]
            c = he[2]
            node.count = c
            hn = Node(j + 1, he[0], "DICT", "header")
            node.add(hn)
            if c > 0:
                stack.append(Frame(F_DICT, node, c))
            elif _dict0_is_open(d, he[0],
                                _core(events[j + 2][1]) if j + 2 < n else None):
                stack.append(Frame(F_OPEN, node))
                node.flags |= 1
            else:
                value_completed()        # closed empty dict
            return j + 2
        if nk == "PRELUDE":
            he = events[j + 1]
            c = he[2]
            node.count = c
            hn = Node(j + 1, he[0], "PRELUDE", "header")
            node.add(hn)
            if c > 0:
                stack.append(Frame(F_ELEMS, node, c))
            else:
                value_completed()
            return j + 2
        if nk == "ARRAY":
            he = events[j + 1]
            node.count = he[3]
            hn = Node(j + 1, he[0], "ARRAY", "header")
            node.add(hn)
            # ASTRINL/AREF payloads attach to hn via PAYLOAD routing
            value_completed()
            return j + 2
        if nk == "SLOT":
            stack.append(Frame(F_SLOTBODY, node))
            return j + 1
        if nk == "CNTW":
            he = events[j + 1]
            c = he[2]
            node.count = c
            hn = Node(j + 1, he[0], "CNTW", "header")
            node.add(hn)
            if c > 0:
                stack.append(Frame(F_DICT, node, c))
            else:
                value_completed()
            return j + 2
        if nk == "PTOK" and j + 2 < n and _core(events[j + 2][1]) == "DEF" \
                and len(events[j + 2][2]) > 40:
            # qtMetadata window: [OBJINL][PTOK N][DEF <long metadata key>...] —
            # the PTOK is the window's ENTRY COUNT (allocation rule R22), and
            # the window is a COUNTED CLOSED body.  Leaving it open (the old
            # fallthrough) leaked its N long-key entries into the enclosing
            # file/clip dict budgets and truncated every later track element
            # (EPK Cut 1-3 read 1 track; the managed variant collapsed at clip
            # 28/169).  The >40-char key gate has zero sites on any RAW-free
            # banked corpus (their DEF names are all <= 40 chars).
            he = events[j + 1]
            c = he[2]
            node.count = c
            node.add(Node(j + 1, he[0], "PTOK", "header", value=c))
            if c > 0:
                stack.append(Frame(F_DICT, node, c))
            else:
                value_completed()
            return j + 2
        if k == "T20":
            # typed object (11FCSpeedData/14FCSpeedSegment): PTOK(C) counted
            # head, then a positional tail (VAL32/PTOK/SLOT fillers, keyed
            # nested T20s) closed by the first non-fitting event
            fr = Frame(F_T20, node)
            if nk == "PTOK":
                he = events[j + 1]
                fr.left = he[2]
                node.count = he[2]
                node.add(Node(j + 1, he[0], "PTOK", "header", value=he[2]))
                stack.append(fr)
                return j + 2
            stack.append(fr)
            return j + 1
        # bare object head with no recognizable body header: open.
        # EXCEPT a v0x14 count-less object that is the VALUE OF A KEYED FIELD
        # directly under a `filters` PRELUDE (F_ELEMS): such a bare F_OPEN can
        # NEVER close — pop_completed only closes an open frame sitting above a
        # completed F_DICT (transparent membership decrements the enclosing
        # dict), but an F_ELEMS is never decremented by an entry, so the open
        # frame absorbs the filters array's remaining element heads AND every
        # following clipitem/track/channel to EOF (Rat King v0x14 color-
        # corrector effect glue: a count-less high-id param object serialized as
        # an uncounted field of the filters array, e.g. id=81720 @0x645d05 ate
        # audm tracks 3-8).  Its members are effect glue irrelevant to the
        # census; close it now (its keyed fields fall to the array as uncounted
        # object-flavor fields) so the array's real element heads — the sibling
        # <filter>s — are still counted and the clipitem resumes after them.
        # Gated hard to a `filters`-parented F_ELEMS: a well-formed <filter>'s
        # effect params are all COUNTED dicts/scalars that close on their own and
        # never reach this count-less fallback, and only the color-corrector glue
        # form lands here — 4 fires on Rat King (both master audms), 0 on any
        # other structure; _V14-gated so no other dialect's tree can move.
        if _V14 and FILTERS_KEY_ID is not None and len(stack) >= 2 \
                and stack[-1].ftype == F_KEY and stack[-2].ftype == F_ELEMS \
                and stack[-2].node.parent is not None \
                and stack[-2].node.parent.role == "key" \
                and stack[-2].node.parent.name == FILTERS_KEY_ID:
            node.count = 0
            value_completed()
            return j + 1
        stack.append(Frame(F_OPEN, node))
        node.flags |= 1
        return j + 1

    def spurious_clip_link(j):
        """True iff events[j] is a `clip`-keyed record whose OBJREF value is a
        SPURIOUS inserted link (uncounted), not a first-class clipitem member.
        Signature (CLIP_LINK_ID/FILE_KEY_ID): value is an OBJREF and the next
        keyed member (past link glue) is `file`.  The linked-clip dialect writes
        clip->type here and returns False, so it is left byte-identical."""
        if FILE_KEY_ID is None or j + 1 >= n \
                or not _core(events[j + 1][1]).startswith("OBJREF"):
            return False
        p = j + 2
        while p < n:
            pk = _core(events[p][1])
            if pk in ("DEF", "NKEY"):
                return events[p][2] == FILE_KEY_ID
            if pk in GLUE or pk == "RAW":
                p += 1
                continue
            return False
        return False

    def spilled_marker_head(j):
        """True iff events[j] is a MARKER object head (OBJINL/OBJINL1 opening a
        small flat DICT of scalar members with `in`/`out` but NO `type`) that has
        spilled out of the previous clip's undercounted markers list into the
        enclosing clip F_ELEMS.  Every real timeline element (clip/generator/
        transition) declares a `type` key; a marker never does (it carries only
        name/in/out under a couple of marker-id keys).  A real element's DICT also
        has NESTED members (filters/masterClips objects), so any non-scalar member
        bails out -- this can only match the flat marker shape.  Left/absent-id
        guarded so it is inert unless `type`+`in`+`out` ids all resolve."""
        tid, iid, oid = TYPE_KEY_ID, IN_KEY_ID, OUT_KEY_ID
        if tid is None or iid is None or oid is None:
            return False
        if j + 1 >= n or _core(events[j + 1][1]) != "DICT":
            return False
        c = events[j + 1][2]
        if not isinstance(c, int) or c <= 0 or c > 12:
            return False
        p, keys = j + 2, set()
        for _ in range(c):
            if p + 1 >= n or _core(events[p][1]) not in ("DEF", "NKEY"):
                return False
            keys.add(events[p][2])
            if _core(events[p + 1][1]) not in SCALARS:
                return False          # nested member -> a real element, not a marker
            p += 2
        return tid not in keys and iid in keys and oid in keys

    # main loop -------------------------------------------------------------
    while i < n:
        e = events[i]
        off, kind = e[0], e[1]
        k = _core(kind)

        # payload events bind to their carrier (last node of that kind on
        # the current frame's children, searching innermost frames first)
        if k in PAYLOAD:
            want = PAYLOAD[k]
            carrier = None
            for f in reversed(stack):
                if f.ftype == F_SLOTBODY and want == "SLOT":
                    for ch in reversed(f.node.children):
                        if _core(ch.kind) == "SLOT":
                            carrier = ch
                            break
                if carrier:
                    break
                for ch in reversed(f.node.children):
                    if _core(ch.kind) == want or (
                            ch.role in ("value", "element", "glue")
                            and _core(ch.kind) == want):
                        carrier = ch
                        break
                    if ch.role == "key" and ch.children \
                            and _core(ch.children[0].kind) == want:
                        carrier = ch.children[0]
                        break
                    if ch.role == "header" and _core(ch.kind) == want:
                        carrier = ch
                        break
                if carrier or f.node.children:
                    break
            node = Node(i, off, kind, "payload",
                        value=e[2] if len(e) > 2 else None)
            (carrier or top().node).add(node)
            i += 1
            continue

        # slot-body frame: body = the contiguous SLOT run (self-terminating;
        # byte-proven: itemHistory = [OBJINL][SLOT(0,0x23)][SUUID] then the
        # parent schema resumes — mc_two/palastin)
        f = top()
        if f.ftype == F_SLOTBODY:
            if k == "SLOT":
                f.node.add(Node(i, off, kind, "glue", value=e[2:]))
                i += 1
                continue
            stack.pop()
            value_completed()
            pop_completed()
            continue            # re-dispatch e against the popped stack

        # T20 tail mode: once the PTOK-head budget is spent, only glue
        # (PTOK/VAL32/SLOT + payloads) and keyed nested T20s belong to the
        # typed object; anything else closes it (re-dispatch)
        if f.ftype == F_T20 and f.left <= 0 and k not in GLUE:
            nested = (k in ("DEF", "NKEY") and i + 1 < n
                      and _core(events[i + 1][1]) == "T20")
            if not nested:
                stack.pop()
                value_completed()
                pop_completed()
                continue

        # lazy-close completed frames before non-glue events
        if k not in GLUE:
            pop_completed()
        f = top()

        # anika-2007 masterClip isolate frame (MASTEROBJ): a self-terminating
        # keyed-metadata record whose members are ISOLATED from the enclosing
        # clipitem dict (f.iso absorbs their counts).  It ends at the enclosing
        # clip's next BARE object head — the following clipitem — which arrives
        # directly at the isolate frame (the master's own nested objects arrive
        # under a KEY frame, never here).  Close it and re-dispatch that head.
        # Keyed strictly to the isolate frame: no generic open-frame heuristic.
        if f.ftype == F_OPEN and f.iso and (k in OBJHEADS or k == "MASTEROBJ"):
            stack.pop()
            value_completed()
            pop_completed()
            continue

        # sparse keyed-element prelude (viewArray form): the element run is
        # over as soon as anything but [PTOK]* + [NKEY elem_key] arrives —
        # declared count C may exceed the serialized element count (the PTOK
        # position tokens mark the gaps). Close early and re-dispatch.
        if f.ftype == F_ELEMS and f.kmode == "keyed" and k not in GLUE:
            if not (k in ("DEF", "NKEY") and e[2] == f.elem_key and f.left > 0):
                stack.pop()
                value_completed()
                pop_completed()
                continue

        # keys ------------------------------------------------------------
        # inside an ELEMS frame a keyed record either IS an element (keyed
        # flavor: first body item is a key; all elements share that key) or
        # attaches as an uncounted field of the array object (object flavor:
        # e.g. children's browser_expanded/clipTop between window elements)
        if k in ("DEF", "NKEY"):
            # sparse-track runaway (trigger B): a `track`-keyed object ELEMS whose
            # declared element count exceeds the serialized heads never closes by
            # count, so it would ABSORB the following media-channel members (the
            # vidm-tail keys, then audm = the whole audio channel) as phantom
            # array fields and sever media.get('audm').  When such a HUNGRY track
            # ELEMS meets a CHANNEL key, force-close the track ELEMS AND unwind its
            # enclosing channel (vidm) DICT so the channel key attaches to the
            # MEDIA dict and audm resumes where it belongs.  Gated hard to the
            # media->channel->track topology and to an incoming channel key: dense
            # tracks close by count before any channel key, so this never fires on
            # them (0 fires on every gated corpus -> byte-identical trees).
            if (e[2] in CHANNEL_KEYS and f.ftype == F_ELEMS and f.left > 0
                    and f.kmode != "keyed"
                    and f.node.parent is not None
                    and f.node.parent.role == "key"
                    and f.node.parent.name == TRACK_KEY_ID
                    and f.node.parent.parent is not None
                    and f.node.parent.parent.parent is not None
                    and f.node.parent.parent.parent.role == "key"):
                chan_node = f.node.parent.parent      # the channel (vidm) object
                f.left = 0
                for cf in stack:
                    if cf.node is chan_node and cf.ftype == F_DICT:
                        cf.left = 0
                        break
                pop_completed()
                f = top()
            if f.ftype == F_ELEMS and f.sawfs:
                # SPARSE object array (waveCacheArray family): the declared
                # count is a CAPACITY — fewer items may be serialized (byte-
                # proven: EPK/managed C=4 arrays carry 2 items).  An element's
                # trailing FILESPEC has passed and the next record is KEYED,
                # not a new element: the array is over regardless of the
                # remaining budget.  Well-formed arrays close by count before
                # any key arrives, so they never take this path.
                stack.pop()
                value_completed()
                pop_completed()
                continue
            kn = Node(i, off, kind, "key", name=e[2])
            f.node.add(kn)
            kf = Frame(F_KEY, kn)
            if e[2] == CLIP_LINK_ID and f.ftype in (F_DICT, F_T20) \
                    and spurious_clip_link(i):
                kn.flags |= 8        # do not count this inserted link record
                # (value_completed skips the entry; keeps audm from being severed)
            # keyed flavor requires the PTOK position-token prefix (byte-
            # census: ALL keyed-element preludes are PTOK-first; keys in
            # ordinary preludes are uncounted array fields)
            if f.ftype == F_ELEMS and f.left > 0 and (
                    f.kmode == "keyed"
                    or (f.kmode is None
                        and len(f.node.children) >= 2
                        and f.node.children[1].kind == "PTOK")):
                f.kmode = "keyed"
                f.elem_key = e[2]
                kn.role = "element"
                kf.kelem = True
            stack.append(kf)
            i += 1
            continue

        # glue -------------------------------------------------------------
        if k in GLUE and f.ftype != F_KEY:
            node = Node(i, off, kind, "glue", value=e[2] if len(e) > 2 else None)
            f.node.add(node)
            if k == "FILESPEC" and f.ftype == F_ELEMS and f.kmode == "object":
                f.sawfs = True
            i += 1
            continue

        # spilled OTAG-GUID-list ref unit (trigger D, v0x14 ref-array family):
        # a clipitem/generatoritem DICT that closes BY COUNT before consuming
        # its trailing SLOTGUIDREF+OTAG-GUID-list effect glue spills that list
        # into the enclosing clip F_ELEMS.  The list's SLOTGUIDREF/BAREREF units
        # are GLUE (uncounted, they spill harmlessly), but each list ref is a
        # BARE scalar OTAGREF -- attach_value would register it as a phantom
        # ELEMENT, draining the array budget and truncating the real element
        # tail (Rat King "Master Sequence Locked 8 bit audio" vidm t0: a "Text"
        # generatoritem's 4-unit OTAG-GUID-list read as 4 phantom clips, which
        # shifted the array and dropped its trailing elements).  A real timeline
        # element is ALWAYS an object head (OBJINL1/OBJINL/OTAGINL opening a
        # DICT), never a bare OTAGREF; and this only fires when the array's most
        # recent child is the SLOTGUIDREF/BAREREF glue of the very list this ref
        # continues -- so a genuine object-flavor scalar array field (which is
        # never preceded by guid-list glue) can never land here.  _V14-gated so
        # no other dialect's tree can move; attach as glue (uncounted).
        if _V14 and k == "OTAGREF" and f.ftype == F_ELEMS and f.node.children \
                and f.node.children[-1].role == "glue" \
                and _core(f.node.children[-1].kind) in ("SLOTGUIDREF", "BAREREF"):
            f.node.add(Node(i, off, kind, "glue",
                            value=e[2] if len(e) > 2 else None))
            i += 1
            continue

        # values (keyed, element, or member of an open container) -----------
        if k in SCALARS or k in GLUE:
            node = Node(i, off, kind,
                        "member", value=e[2] if len(e) > 2 else None)
            attach_value(node)
            if f.ftype in (F_KEY, F_ELEMS):
                value_completed()
                pop_completed()
            i += 1
            continue

        if k == "MASTEROBJ":
            # anika-2007 inline masterClip: value of a clipitem's master-UUID key.
            # Open an ISOLATE frame so the record's own keyed members do not
            # decrement the enclosing clipitem dict; it self-terminates at the
            # next bare object head (see the isolate-close rule above).  The head
            # counts as ONE ordinary dict entry (flags open bit stays clear).
            if f.ftype == F_ELEMS:
                f.sawfs = False
            node = Node(i, off, kind, "member", name=e[2] if len(e) > 2 else None)
            attach_value(node)
            fr = Frame(F_OPEN, node)
            fr.iso = True
            node.flags |= 2
            stack.append(fr)
            i += 1
            continue

        # clip-level runaway close (trigger B, one level down): a HUNGRY object-
        # flavor clip-PRELUDE (F_ELEMS, budget left, its parent KEY is `clip`) whose
        # declared element count exceeds the serialized clipitem heads never closes
        # by count, so it ABSORBS the next sibling TRACK head as a phantom element
        # and cascades through the remaining video tracks and the whole audm channel
        # (video collapses, audio = 0).  When such a hungry clip-PRELUDE meets a
        # TRACK-SHAPED head (OBJINL/1 -> DICT -> `clip` key -> head -> PRELUDE),
        # force-close the clip-PRELUDE and unwind its enclosing track-element DICT so
        # the head re-attaches to the enclosing `track` PRELUDE (mirrors the trigger-B
        # unwind above, one level down).  Gated hard to the track-shaped lookahead:
        # a dense clip serializes all its declared elements and closes BY COUNT before
        # the next track head arrives (so the top frame is then the `track` PRELUDE,
        # not a clip-PRELUDE), and a clipitem's DICT-first key is filters/end/in/
        # masterClips, never `clip` -- so this never fires on a dense clip (0 fires on
        # every gated corpus -> byte-identical trees).  None-guarded on CLIP_LINK_ID
        # so it is inert on docs without a `clip` key.
        if (CLIP_LINK_ID is not None and k in OBJHEADS
                and f.ftype == F_ELEMS and f.left > 0
                and f.kmode != "keyed"
                and f.node.parent is not None
                and f.node.parent.role == "key"
                and f.node.parent.name == CLIP_LINK_ID
                and i + 4 < n and _core(events[i + 1][1]) == "DICT"
                and _core(events[i + 2][1]) in ("DEF", "NKEY")
                and events[i + 2][2] == CLIP_LINK_ID
                and _core(events[i + 4][1]) == "PRELUDE"):
            tdict = f.node.parent.parent      # the enclosing track-element object
            f.left = 0
            for tf in stack:
                if tf.node is tdict and tf.ftype in (F_DICT, F_T20):
                    tf.left = 0
                    break
            pop_completed()
            f = top()

        # clip-element sibling force-close (trigger C, one level down from B): a
        # HUNGRY clipitem DICT (F_DICT/T20, budget left) sitting DIRECTLY on a
        # clip-PRELUDE F_ELEMS whose own budget is unspent (more clipitems
        # declared).  In v0x14 a clipitem carrying effect ref-arrays
        # (SLOTGUIDREF+OTAG-GUID-list / PTOK+REFARRAY, all uncounted glue)
        # declares more DICT members than the grouper counts, so the clipitem
        # DICT never closes BY COUNT and would ABSORB the next clipitem head as a
        # phantom member — cascading through the remaining video tracks and the
        # whole audm channel (Rat King "Master Sequence Locked" track-2 clipitem-1
        # @0x5bc53d: DICT(19) = 15 keyed members + two 19-unit ref-arrays, ate
        # video track 3 + audm to EOF).  When such a hungry clipitem DICT meets a
        # bare object head, force-close it AND count it as the completed element so
        # the head re-attaches as the clip's NEXT element.  Gated to v0x14 and the
        # clip-PRELUDE topology: a well-formed clipitem closes BY COUNT before the
        # next head arrives (count == serialized members), so the top frame is then
        # the clip F_ELEMS — never a hungry clipitem DICT — and a clipitem's own
        # nested objects arrive under a KEY frame, never bare on the DICT.  So this
        # never fires on a well-formed clip (0 fires on the gated corpus).
        if (_V14 and k in OBJHEADS and CLIP_LINK_ID is not None
                and f.ftype in (F_DICT, F_T20) and f.left > 0
                and len(stack) >= 2
                and stack[-2].ftype == F_ELEMS
                and stack[-2].kmode != "keyed"
                and stack[-2].left > 0
                and stack[-2].node.parent is not None
                and stack[-2].node.parent.role == "key"
                and stack[-2].node.parent.name == CLIP_LINK_ID):
            f.left = 0
            pop_completed()
            f = top()

        # spilled marker (trigger E, v0x14 markers-list undercount): a clip's
        # markers list can declare fewer entries than serialized, so a trailing
        # marker object spills out of the clip DICT into the enclosing clip
        # F_ELEMS.  There it would be parsed as a phantom clip ELEMENT (type-less,
        # so _elem_kind reads it "clip"), draining the array budget and dropping a
        # real tail element (Rat King "Master Sequence Locked" vidm t0: a "Marker
        # 2" object read as a phantom clip, +1 over census).  Parse the marker as
        # an uncounted object-flavor field (flag 4 -> value_completed skips the
        # F_ELEMS decrement, and role "member" keeps it out of .elements()), so
        # the displaced real element keeps its slot.  Gated to v0x14 + a clip-
        # PRELUDE F_ELEMS (parent key == `clip`, object flavor, budget left) + the
        # flat type-less marker shape: a well-formed clip's markers stay nested
        # under its own `markers` key (never a bare head on the clip array), and a
        # real element always declares `type`, so this 0-fires on dense structures.
        if (_V14 and k in ("OBJINL", "OBJINL1") and CLIP_LINK_ID is not None
                and f.ftype == F_ELEMS and f.left > 0 and f.kmode != "keyed"
                and f.node.parent is not None
                and f.node.parent.role == "key"
                and f.node.parent.name == CLIP_LINK_ID
                and spilled_marker_head(i)):
            node = Node(i, off, kind, "member")
            attach_value(node)
            node.role = "member"
            node.flags |= 4
            i = start_body(node, i)
            continue

        if k in OBJHEADS or k in ("LEAF", "T0C"):
            if f.ftype == F_ELEMS:
                f.sawfs = False          # a new array item begins
            node = Node(i, off, kind, "member",
                        name=e[2] if k == "T20" else None)
            attach_value(node)
            i = start_body(node, i)
            continue

        if k in ("DICT", "PRELUDE", "ARRAY", "CNTW"):
            # stray body header (no preceding object head) — should not
            # happen; attach as glue and flag
            node = Node(i, off, kind, "glue", value=e[2] if len(e) > 2 else None)
            f.node.add(node)
            violations.append((i, off, f"stray-{k}"))
            i += 1
            continue

        # anything else: attach as glue member (flagged)
        node = Node(i, off, kind, "glue", value=e[2] if len(e) > 2 else None)
        f.node.add(node)
        violations.append((i, off, f"unhandled-{k}"))
        i += 1

    # EOF: close everything
    open_at_eof = []
    while len(stack) > 1:
        fr = stack.pop()
        if fr.ftype in (F_DICT, F_ELEMS, F_T20) and fr.left > 0:
            open_at_eof.append((fr.node.i, fr.node.off, fr.node.kind, fr.left))
    root.value = {"violations": violations, "open_at_eof": open_at_eof}
    return root


# ===========================================================================
# event-stream preprocessing: two tokenizer misframes re-tokenized in place
# (byte-validated; pure event surgery, the walker itself is untouched)
# ===========================================================================

# A SLOT(1,1,N) whose count N reaches this floor is treated as a candidate
# misframe (PTOK(1) + a record run swallowed as an INT-slot payload) and its
# interior is re-tokenized.  256 is the canonical speed-segment coincidence,
# but the same class occurs at other large N (anika: SLOT(1,1,280) x4 and
# SLOT(1,1,7680) x2, the latter burying whole sequences).  The floor is only a
# performance gate — a genuine LARGE int slot is protected by the reconvergence
# test below (nothing is spliced unless the interior re-parse rejoins the outer
# stream at a real event with the following event aligned too), so it never
# corrupts a real slot; it merely avoids paying re-tokenization on the many
# small genuine int slots (N < 256) that could false-reconverge on their few
# payload bytes.  On palastin/EPK/managed every large-N slot is exactly 256, so
# raising 256 from an equality to a floor leaves those corpora byte-identical.
_MEGASLOT_MIN_N = 256


def _splice_megaslots(d, ev):
    """SLOT(1,1,N>=256) is a framing coincidence (PTOK(1) + a 14FCSpeedSegment
    record run swallowed as an INT slot payload).  Re-tokenize the interior
    and splice the true events, re-converging with the outer stream."""
    out = []
    i = 0
    n = len(ev)
    while i < n:
        e = ev[i]
        if e[1] == "SLOT" and e[2] == 1 and e[3] == 0x01 and e[4] >= _MEGASLOT_MIN_N:
            p = e[0]
            send = p + 13 + 4 * e[4]
            inner = [(p, "PTOK", 1)] + W.tokenize(
                d, p + 5, min(send + 4096, len(d) - 16))
            okey = {}
            j = i
            while j < n and ev[j][0] < send + 4096:
                okey.setdefault((ev[j][0], ev[j][1]), j)
                j += 1

            def _scan(inn):
                for k, t in enumerate(inn):
                    if t[0] >= send and (t[0], t[1]) in okey:
                        cand = okey[(t[0], t[1])]
                        if (k + 1 < len(inn) and cand + 1 < n
                                and inn[k + 1][0] == ev[cand + 1][0]
                                and inn[k + 1][1] == ev[cand + 1][1]):
                            return t[0], cand
                return None

            hit = _scan(inner)
            # nested SLOT(1,1,256) coincidences inside the interior (chained
            # speed segments) either swallow the resync point or hide interior
            # records behind a convergence-by-luck — expand every nested slot
            # the outer stream cannot see, mirroring _megaslot_credit
            for _ in range(8):
                bound = hit[0] if hit is not None else send + 4096
                nk = next((kk for kk, t in enumerate(inner)
                           if t[1] == "SLOT" and t[2] == 1 and t[3] == 0x01
                           and t[4] >= _MEGASLOT_MIN_N and p < t[0] < bound
                           and (t[0], "SLOT") not in okey), None)
                if nk is None:
                    break
                q = inner[nk][0]
                inner = inner[:nk] + [(q, "PTOK", 1)] + W.tokenize(
                    d, q + 5, min(send + 4096, len(d) - 16))
                hit = _scan(inner)
            if hit is not None:
                conv, oj = hit
                out.extend(t for t in inner if t[0] < conv)
                i = oj
                continue
        out.append(e)
        i += 1
    return out


def _splice_boxlists(d, ev):
    """R16 mis-frame: the sequence-preset box list [01][t][pad3] + t units
    is read by try_val32 as VAL32(t,16), swallowing the interior units AND
    the interleaved keyed refs (clipTop / sequenceDict..spec link records).
    Re-tokenize the swallowed span."""
    out = []
    n = len(ev)
    for i, e in enumerate(ev):
        if (e[1] == "VAL32" and e[2] in (3, 4, 5) and e[3] == 16
                and d[e[0] + 9] == 1 and d[e[0] + 10] == 0):
            p = e[0]
            units = W._boxlist_units(d, p, e[2])
            if len(units) == e[2]:
                end = ev[i + 1][0] if i + 1 < n else len(d) - 16
                out.extend(W.tokenize(d, p + 5, end))
                continue
        out.append(e)
    return out


# ===========================================================================
# the grouper
# ===========================================================================

LINK_KEYS = ("sequenceDict", "subsequenceDict", "itemDict", "spec")
SEQ_FLAVOR = ("seqProps", "tcData", "selectionIn", "selectionOut", "reels")
MAS_FLAVOR = ("scene", "take", "lognote", "comment1", "labelComment")

# A mined backbone anchor whose implied drift E = true - model exceeds this is
# garbage and is dropped before it can poison the anchor curve (LesInsectesGeants_V8
# has two, both at true id 17, reading E ~= -640,000; every ref between id 17 and the
# next real anchor then got a ~640k-wide, mid-misplaced drift bracket — the O(n x 640k)
# scan that hung the parser >1h and segfaulted).  Legit drift is far below this:
# palastin/EPK/managed |E| <= 271, and even LesInsectes' genuine old-format ramp only
# reaches ~18,546 (34x under the bound), so no real anchor is ever filtered.
_MAX_ANCHOR_E = 65536
# Belt-and-suspenders width cap for the same corruption seen from the consuming side
# (a bracket this wide means a corrupt anchor slipped the filter); never triggers on
# legit drift, which stays <= ~18.5k after filtering.
_MAX_DRIFT_BRACKET = _MAX_ANCHOR_E


def _mine_backbone_anchors(rev, allocs):
    """Dense (true_id, model_id) anchors from the backbone self-ref oracle.

    Clip/master records repeat one GUIDREF X several times shortly after their
    OTAGOBJ registration, and X is the record's own TRUE table id (byte-proven on
    the zero-drift mc_three/mc_four corpora; see keyg_walker2's session-7b notes).
    Pairing X with the model id the walker assigned to the same OTAGOBJ yields a
    drift anchor E = true - model at that offset.  A stub-credited registration
    (alloc 2: the stub slot precedes the object) puts the object one PAST the
    event's first id, so the model id is `c + alloc - 1` — without this the
    anchor reads E+1 at every fresh-master site (which cost palastin ~1000
    previously-resolving names in the first cut of this resolver)."""
    out = []
    cur = None                    # [model_object_id, {guidref: count}]
    c = W.FINAL_BASE

    def flush():
        if cur is None or not cur[1]:
            return
        x, n = max(cur[1].items(), key=lambda kv: kv[1])
        if n >= 3:
            out.append((x, cur[0]))

    for a, e in zip(allocs, rev):
        k = e[1]
        if k == "OTAGOBJ":
            flush()
            cur = [c + max(a, 1) - 1, {}] if a > 0 else None
        elif k in ("DEF", "FILESPEC", "T20", "RAW"):
            # RAW must flush too: a pocket that swallows the next OTAGOBJ would
            # otherwise pair that record's self-refs with a STALE model id
            flush()
            cur = None
        elif k == "GUIDREF" and cur is not None:
            cur[1][e[2]] = cur[1].get(e[2], 0) + 1
        if a > 0:
            c += a
    flush()
    out.sort()
    return out


# value-kind classes for the drift-validated key lookup: a key's expected class
# is learned from its spelled DEF site; F32/FIXED merge (effect params are
# polymorphic across them), reference and inline forms of a class merge.
_KIND_CLASSES = {
    "OBJINL": "OBJ", "OBJINL1": "OBJ", "OTAGINL": "OBJ", "T0C": "OBJ",
    "LEAF": "OBJ", "OBJREF": "OBJ", "OBJEMPTY": "OBJ", "T20": "OBJ",
    "T20REF": "OBJ", "OTAGREF": "OBJ", "DICT": "OBJ", "CNTW": "OBJ",
    "STRINL": "STR", "STRREF": "STR",
    "UUID": "UUID", "UUIDREF": "UUID",
    "F32": "F32", "FIXED": "F32",
    "DATA07": "DATA", "DATA07REF": "DATA", "BLOBINL": "DATA", "BLOBREF": "DATA",
    "G10INL": "G10", "G10REF": "G10",
}


def _kind_class(k):
    if k.endswith("_S"):
        k = k[:-2]
    return _KIND_CLASSES.get(k, k)


class _Doc:
    """One parsed .fcp: containment tree + object table + drift anchors."""

    def __init__(self, path):
        raw = Path(path).read_bytes()
        self.d = raw + b"\x00" * 64
        hi = min(len(raw), len(self.d) - 16)
        self.table = W.object_table(self.d, 0x2E, hi)
        self.ids = {}
        for i, (k, v) in self.table.items():
            if k == "DEF" and v not in self.ids:
                self.ids[v] = i
        rev = W.tokenize_scoped(self.d, 0x2E, hi)
        allocs = W.final_allocs(rev, self.d)
        self.id_at_pos = {}
        c = W.FINAL_BASE
        for a, e in zip(allocs, rev):
            if a > 0:
                self.id_at_pos[e[0]] = c
                c += a
        self.ref_anchors = _mine_backbone_anchors(rev, allocs)
        ev = _splice_boxlists(self.d, _splice_megaslots(self.d, rev))
        self._configure()
        self.root = build_tree(ev, self.d)
        self.anchors = []          # (true_id, raw_id) at sequence heads
        self.fallbacks = []        # flagged degradations
        self._anch_cache = None    # merged (true, E) list for _resolve_ref
        self._def_kind_cache = None  # key name -> value-kind class (lazy)
        self._key_drift_cache = None  # DEF model id -> voted NKEY drift (lazy)

    def _configure(self):
        global UNCOUNTED_KIDS, CHANNEL_UNCOUNTED, CHANNEL_KEYS
        global CLIP_LINK_ID, FILE_KEY_ID, TRACK_KEY_ID, FILTERS_KEY_ID
        global TYPE_KEY_ID, IN_KEY_ID, OUT_KEY_ID
        unc = set(LINK_KEYS)
        unc.update(self.ids[k] for k in LINK_KEYS if k in self.ids)
        UNCOUNTED_KIDS = frozenset(unc)
        CLIP_LINK_ID = self.ids.get("clip")
        FILE_KEY_ID = self.ids.get("file")
        TRACK_KEY_ID = self.ids.get("track")
        FILTERS_KEY_ID = self.ids.get("filters")
        TYPE_KEY_ID = self.ids.get("type")
        IN_KEY_ID = self.ids.get("in")
        OUT_KEY_ID = self.ids.get("out")
        ch = {"itemHistory"}
        if "itemHistory" in self.ids:
            ch.add(self.ids["itemHistory"])
        CHANNEL_UNCOUNTED = frozenset(ch)
        ck = {"vidm", "audm"}
        ck.update(self.ids[k] for k in ("vidm", "audm") if k in self.ids)
        CHANNEL_KEYS = frozenset(ck)

    # -- lookups -----------------------------------------------------------
    def get(self, node, name):
        """node.get by key NAME: DEF string, then the NKEY id, then the object-
        slot id.

        `self.ids[name]` is the id of the *DEF* record.  In the object table each
        object-valued key is a consecutive `(DEF, OBJINL-slot)` pair, and a later
        NKEY reference to that key points at the OBJINL-*slot* id (`DEF + 1`), not
        the DEF id — so a clip that inlines `motion` resolves by string, but a
        sibling clip that references it misses on both the string and the DEF id.
        Fall back to the slot id when it is an object slot (byte-validated: takes
        all_motion motion/basic/scale from 1/11 to 11/11 clips with zero change to
        any existing resolution across palastin).

        GENERAL KEY DRIFT: a key's NKEY reference id = DEF model id + E at the
        DEF's intern position (the same E(pos) the string resolver brackets with
        the dense anchors).  In a drifted bracket EVERY probe — the aligned one
        included — is validated against the key's expected VALUE-KIND class
        (learned from its spelled DEF occurrence): with per-key drifts, one
        key's model id can be another key's true NKEY (managed: 'start' DEF 51
        collides with 'file' DEF 53 referenced at 51), and an unvalidated
        aligned hit returns the wrong entry.  Keys in well-aligned regions keep
        the fast unvalidated path."""
        v = node.get(name)
        if v is None and name in self.ids:
            tid = self.ids[name]
            t = self.table.get(tid + 1)
            slot = t is not None and t[0] in ("OBJINL", "OBJINL1", "OTAGINL", "T20")
            anch = self._merged_anchors()
            eprev = enext = 0
            if anch:
                trues = self._anch_cache[2]
                j = bisect.bisect_right(trues, tid) - 1
                eprev = anch[j][1] if j >= 0 else 0
                enext = anch[j + 1][1] if j + 1 < len(anch) else eprev
            if eprev == 0 and enext == 0:
                v = node.get(tid)
                if v is None and slot:
                    v = node.get(tid + 1)
                return v
            kd = self._key_drifts().get(tid)
            if kd is not None:
                # the voted per-key drift is authoritative: hit or ABSENT
                # (adjacent same-kind keys — start/end are neighbouring F64s —
                # make positional probing wrong-by-one; only the global vote
                # disambiguates them)
                v = node.get(tid + kd)
                if v is None and slot:
                    v = node.get(tid + kd + 1)
                if v is None and kd:
                    # Voted-drift miss: the vote measures how NKEY REFERENCES
                    # drift, but a node can also key by the SPELLED DEF id
                    # directly (SALVAGNO media dicts key 'vidm' at its exact
                    # DEF id while slot-form references voted kd=+1; the miss
                    # made every video-only sequence non-seq-shaped — census
                    # 14 vs FCP oracle 23).  Probe the exact id, kind-
                    # validated so an alien key drifted onto tid cannot
                    # answer with the wrong entry.
                    exp = self._def_kinds().get(name)
                    cand = node.get(tid)
                    if cand is None and slot:
                        cand = node.get(tid + 1)
                    if cand is not None and \
                            (exp is None or _kind_class(cand.kind) in exp):
                        v = cand
                return v
            exp = self._def_kinds().get(name)
            lo, hi = min(eprev, enext, 0) - 1, max(eprev, enext, 0) + 1
            mid = (eprev + enext) / 2
            # Probe only the node's ACTUAL keys that land in the drift bracket, not
            # every id in [lo, hi]: on old-format files the legit bracket is thousands
            # of ids wide (LesInsectesGeants_V8 accumulates E up to ~18.5k), so
            # materializing + sorting the whole range on every lookup was the dominant
            # cost.  A node has only tens of keys.  Semantics preserved exactly:
            # closest-to-mid (ties -> smaller d) kind-validated hit, with a direct id
            # taking precedence over its object-slot id at the same probe.
            em = node.entry_map()
            probes = []
            for K, cand in em.items():
                if type(K) is not int:
                    continue
                d = K - tid
                if lo <= d <= hi:
                    probes.append((abs(d - mid), d, cand))            # direct hit
                if slot and lo <= d - 1 <= hi and (K - 1) not in em:
                    probes.append((abs(d - 1 - mid), d - 1, cand))    # object-slot hit
            probes.sort(key=lambda p: (p[0], p[1]))
            for _, _, cand in probes:
                if exp is None or _kind_class(cand.kind) in exp:
                    return cand
            # nothing kind-validated: fall back to the exact aligned hit (the
            # pre-drift behavior).  The kind sets are sampled from SPELLED
            # occurrences only and can miss a legitimate class (managed spells
            # 'value' only as a generator STRING, so its F32 audio-keyframe
            # hits — at the exactly-aligned id — were rejected).  Keys with
            # real id collisions are already protected by the voted drift map.
            v = node.get(tid)
            if v is None and slot:
                v = node.get(tid + 1)
        return v

    def _key_drifts(self):
        """DEF model id -> globally-voted NKEY drift (per-doc, lazy).

        Method (validated on the aligned corpora: 0 false positives with the
        gates below): every NKEY id k with >=3 occurrences and a >=90%-majority
        value-kind class votes for the DEF ids of that class inside its anchor
        bracket (+-2 to cover local E dips between sparse anchors); singleton
        candidates claim their DEF, uniqueness propagates to a fixpoint.  The
        DEF-table gap structure disambiguates adjacent same-kind keys: managed
        'start'(51)/'end'(52) are referenced at 49/50, and 49 fits ONLY 'start'
        (no F64 DEF at 50/49), which claims it and pins 'end' by elimination."""
        if self._key_drift_cache is not None:
            return self._key_drift_cache
        anch = self._merged_anchors()
        if not anch or all(e == 0 for _, e in anch):
            self._key_drift_cache = {}
            return self._key_drift_cache
        trues = self._anch_cache[2]
        defk = {}
        kinds_by_name = self._def_kinds()
        for name, tid in self.ids.items():
            kc = kinds_by_name.get(name)
            if kc is not None:
                defk[tid] = kc
        occ = {}
        for nd in self.root.walk():
            for c in nd.children:
                if c.role == "key" and isinstance(c.name, int) and c.children:
                    occ.setdefault(c.name, {})
                    kc = _kind_class(c.children[0].kind)
                    occ[c.name][kc] = occ[c.name].get(kc, 0) + 1
        cands = {}
        for k, kinds in occ.items():
            total = sum(kinds.values())
            if total < 3:
                continue
            cls, cnt = max(kinds.items(), key=lambda kv: kv[1])
            if cnt < 0.9 * total:
                continue
            j = bisect.bisect_right(trues, k) - 1
            eprev = anch[j][1] if j >= 0 else 0
            enext = anch[j + 1][1] if j + 1 < len(anch) else eprev
            lo, hi = min(eprev, enext, 0) - 2, max(eprev, enext, 0) + 2
            if hi - lo > _MAX_DRIFT_BRACKET:
                continue                 # corrupt anchor: no reliable drift vote here
            s = {d for d in range(lo, hi + 1) if cls in defk.get(k - d, ())}
            if s:
                cands[k] = s
        # CONSECUTIVE NKEY RUNS drift together (true ids preserve DEF order, so
        # neighbouring references share one E): intersect the run members'
        # candidate sets — a unique common d claims the whole run.  This is
        # what splits adjacent same-kind pairs: managed start/end are
        # referenced at 49/50 with sets {-2,-3} and {-1,-2}; only d=-2 maps
        # both order-preservingly.
        ks = sorted(cands)
        i = 0
        while i < len(ks):
            j = i
            while j + 1 < len(ks) and ks[j + 1] == ks[j] + 1:
                j += 1
            if j > i:
                common = set.intersection(*(cands[k] for k in ks[i:j + 1]))
                if len(common) == 1:
                    for k in ks[i:j + 1]:
                        cands[k] = set(common)
            i = j + 1
        claimed = {}                      # def id -> (k, d)
        owner = {}                        # k -> def id
        changed = True
        while changed:
            changed = False
            for k in list(cands):
                s = {d for d in cands[k]
                     if (k - d) not in claimed or claimed[k - d][0] == k}
                if s != cands[k]:
                    cands[k] = s
                    changed = True
                if len(s) == 1 and k not in owner:
                    d = next(iter(s))
                    tid = k - d
                    if tid not in claimed:
                        claimed[tid] = (k, d)
                        owner[k] = tid
                        changed = True
        self._key_drift_cache = {tid: kd[1] for tid, kd in claimed.items()}
        return self._key_drift_cache

    def _def_kinds(self):
        """Key name -> SET of value-kind classes seen at the key's SPELLED
        occurrences in the tree.  A set, not a single class: effect-parameter
        keys are polymorphic ('value'/'min'/'max' carry F32 on audio levels but
        F64 on speed keyframes), and a single-class expectation rejected the
        legitimate aligned hit on managed volume keyframes.  Lazy, cached."""
        if self._def_kind_cache is None:
            m = {}
            for nd in self.root.walk():
                if nd.role == "key" and isinstance(nd.name, str) and nd.children:
                    m.setdefault(nd.name, set()).add(_kind_class(nd.children[0].kind))
            self._def_kind_cache = m
        return self._def_kind_cache

    def resolve_str(self, vnode):
        if vnode is None:
            return None
        k = vnode.kind[:-2] if vnode.kind.endswith("_S") else vnode.kind
        if k == "STRINL":
            return vnode.value
        if k == "STRREF":
            return self._resolve_ref(vnode.value)
        return None

    def _merged_anchors(self):
        """Sorted (true_id, E) anchor curve: dense backbone self-refs merged with
        the byte-true sequence mainDict anchors.  Cached; rebuilt when the
        sequence anchors are (re)set."""
        stamp = len(self.anchors)
        if self._anch_cache is not None and self._anch_cache[0] == stamp:
            return self._anch_cache[1]
        pts = {}
        for true, raw in self.ref_anchors:
            if abs(true - raw) > _MAX_ANCHOR_E:
                continue                       # corrupt self-ref pairing (drops LesInsectes' true=17 garbage)
            pts.setdefault(true, true - raw)
        for true, raw in self.anchors:        # sequence anchors override (byte-true)
            pts[true] = true - raw
        curve = sorted(pts.items())
        self._anch_cache = (stamp, curve, [a[0] for a in curve])
        return curve

    def _cluster_head(self, m):
        """True iff table[m] heads a NAME CLUSTER: a non-empty STRINL followed by
        >= 3 consecutive EMPTY STRINLs — the clip/master name string is serialized
        with its empty label/comment sibling strings right behind it (byte-verified
        on EPK: name + 9 empties).  Distinguishes the real name from the P2/MXF
        metadata copies of the same string elsewhere in the table."""
        for k in range(1, 4):
            t = self.table.get(m + k)
            if not (t and t[0].startswith("STRINL") and t[1] == ""):
                return False
        return True

    def _resolve_ref(self, ref):
        """Resolve a TRUE string-object id against the model table under drift.

        E(pos) = true - model accumulates on old-format files; the measured curve
        is piecewise-constant and always bounded by the surrounding anchors'
        E values (q1/q4 probes: 56 plateaus, EPK E 0->+558, palastin ~0).  So the
        true string's model id lies in [ref - E_hi, ref - E_lo] from the anchors
        bracketing `ref` in true-id space.  Narrow bracket: pick the STRINL
        (empty included) nearest the interpolated E, ties preferring a
        name-cluster head; wide bracket: demand the cluster signature.
        Unresolvable or empty -> None (correct-or-absent: the emitter falls back
        to the master/file name, FCP's own substitution)."""
        anch = self._merged_anchors()
        if not anch:
            t = self.table.get(ref)
            return t[1] if t and t[0].startswith("STRINL") and t[1] else None
        trues = self._anch_cache[2]
        j = bisect.bisect_right(trues, ref) - 1
        if j < 0:
            tprev, eprev = 0, 0
        else:
            tprev, eprev = anch[j]
        if j + 1 < len(anch):
            tnext, enext = anch[j + 1]
        else:
            tnext, enext = tprev, eprev
        spread = max(eprev, enext) - min(eprev, enext)
        # +-1 beyond the anchor bracket: E wiggles by one id BETWEEN anchors
        # (stub/copy-form +-1 pockets exist on palastin and EPK alike)
        lo, hi = min(eprev, enext) - 1, max(eprev, enext) + 1
        if tnext > tprev:
            eint = eprev + (enext - eprev) * (ref - tprev) / (tnext - tprev)
        else:
            eint = float(eprev)
        if hi - lo > _MAX_DRIFT_BRACKET:
            # corrupt anchor: the interpolated E is meaningless, so probe only the
            # exact-aligned id (correct-or-absent, same as the unanchored path).
            lo, hi, eint = -1, 1, 0.0
        cands = []
        for e in range(lo, hi + 1):
            t = self.table.get(ref - e)
            if t and t[0].startswith("STRINL") and t[1] is not None:
                cands.append((e, ref - e, t[1]))
        if not cands:
            return None
        if spread > 4:
            # wide bracket (an unanchored E ramp): a lone STRINL in it is NOT
            # evidence — demand the name-cluster signature (correct-or-absent)
            cands = [c for c in cands if c[2] and self._cluster_head(c[1])]
            if not cands:
                return None
            return min(cands, key=lambda c: abs(c[0] - eint))[2]
        # narrow bracket: select by position among ALL STRINLs, EMPTY included —
        # a ref whose true target is one of the empty label/comment strings that
        # trail a name (the cluster empties) must resolve to None, not slide
        # onto the neighbouring name head (that fingerprint — Label 2 == the
        # clip's own filename — is exactly how the drift garbage looked).
        # Distance ties prefer the cluster head.
        best = min(cands, key=lambda c: (abs(c[0] - eint),
                                         not self._cluster_head(c[1])))
        return best[2] or None


def _is_seq_shaped(doc, nd):
    if nd.count is None or not nd.children:
        return False
    med = doc.get(nd, "media")
    if med is None:
        return False
    return doc.get(med, "vidm") is not None or doc.get(med, "audm") is not None


def _tracks_of(doc, seq):
    med = doc.get(seq, "media")
    out = []
    for mk in ("vidm", "audm"):
        m = doc.get(med, mk)
        if m is None:
            continue
        trk = doc.get(m, "track")
        if trk is None:
            continue
        for te in trk.elements():
            cl = doc.get(te, "clip")
            if cl is not None:
                out.append(cl)
    return out


def _elem_kind(doc, el):
    """Timeline element kind: the `type` key is authoritative when it reads a
    valid code (1/2 = clip, 3 = transition, 4 = generator); the effect-subtree
    presence test is only the fallback for unreadable types.

    The effect test alone misclassifies BOTH ways in drift-unstable regions
    (Timebomb THIRD CUT ALT ENDING, 2026-07-13: 20 real Cross Dissolves read
    effect=None and exported as unnamed clips, while 13 clips spuriously
    resolved an alien `effect` and swallowed their neighbours' names; FCP
    Wedding silently lost 10 transitions the same way).  `type` reads
    correctly at all of those sites, and on the byte-exact gated corpora
    (EPK/managed/palastin/Aaron: 9,443 elements) type and effect agree 100%,
    so type-primacy cannot disturb them."""
    t = doc.get(el, "type")
    if t is not None and isinstance(t.value, int) and t.value in (1, 2, 3, 4):
        return {1: "clip", 2: "clip", 3: "transition", 4: "generator"}[t.value]
    if doc.get(el, "effect") is None:
        return "clip"
    return "generator" if (t is not None and int(t.value) == 4) else "transition"


def _transition_alignment(doc, el, prev_el, next_el):
    """xmeml <alignment> from the transition's `mode` INT + its NEIGHBOURS.

    mode 1 = center.  For 2 (start-on-edit) and 3 (end-on-edit) the '-black'
    suffix says the transition's FAR side has no media under it, which
    RESOLVE renders literally (a plain 'start' extends the incoming clip
    under the transition; 'start-black' fades from black) — calibrated
    against every non-center transition in FCP's own exports (33/33 on EPK,
    byte-identical set on managed):
      mode 2 -> 'start'        when the transition is the track's FIRST
                               element or the outgoing clip abuts under it
                               (raw end == -1); else 'start-black' (a prior
                               element exists but ends at/before the cut).
      mode 3 -> 'end'          when the incoming clip abuts under it (raw
                               start == -1); else 'end-black' (next element
                               absent, a transition, or starting at/after
                               the transition end)."""
    mode = doc.get(el, "mode")
    mv = int(mode.value) if mode is not None else 1
    if mv == 2:
        if prev_el is None:
            return "start"
        if _elem_kind(doc, prev_el) == "clip":
            pe = doc.get(prev_el, "end")
            if pe is not None and int(pe.value) == -1:
                return "start"
        return "start-black"
    if mv == 3:
        if next_el is not None and _elem_kind(doc, next_el) == "clip":
            ns = doc.get(next_el, "start")
            if ns is not None and int(ns.value) == -1:
                return "end"
        return "end-black"
    return "center"


def transition_fields(doc, el, mediatype, prev_el=None, next_el=None):
    """Surface a transitionitem track-element for the emitter: timeline start/end,
    alignment (from `mode` + neighbour geometry), and the raw effect id (English
    scriptid; may be None or a third-party plugin — the emitter maps only known
    built-ins and defaults the rest)."""
    align = _transition_alignment(doc, el, prev_el, next_el)
    eff = doc.get(el, "effect")
    # scriptid is the language-independent English effectid but drifts to None on busy
    # projects; `name` resolves reliably and == effectid on an English install, so use
    # scriptid when present else name (the emitter maps it to a known built-in).
    scriptid = doc.resolve_str(doc.get(eff, "scriptid")) if eff is not None else None
    name = doc.resolve_str(doc.get(eff, "name")) if eff is not None else None
    return {
        "kind": "transition", "mediatype": mediatype,
        "start": _f64_int(doc, el, "start", []),
        "end": _f64_int(doc, el, "end", []),
        "alignment": align,
        "effectid": scriptid or name,
    }


def _gen_text(doc, eff):
    """Recover a Text generator's displayed string: the first parameter override's
    value inside effect.parms. Returns None when the value STRREF hasn't resolved
    (the render-registry drift) or is only the 'EXEMPLE' template default."""
    if eff is None:
        return None
    parms = doc.get(eff, "parms")
    if parms is None:
        return None
    # the override list is the OBJINL child of parms with the most entries
    plist = None
    for _, c in parms.entries():
        if c.kind == "OBJINL" and (plist is None or (c.count or 0) > (plist.count or 0)):
            plist = c
    if plist is None:
        return None
    subs = [c for _, c in plist.entries()]
    if not subs:
        return None
    # within a parameter node the value is the last STRREF child (after id + label)
    strs = [c for _, c in subs[0].entries() if c.kind.startswith("STR")]
    txt = doc.resolve_str(strs[-1]) if strs else None
    if not txt or txt == "EXEMPLE":       # unresolved / template placeholder
        return None
    return txt


# --- media pathurls (real source paths from the embedded Mac Alias FILESPEC blobs) ---
#
# Each FILESPEC = [01][u32 nf=5][5 length-prefixed spans]; span[2] = volume name,
# span[4] = a Carbon path array [u32 flag][u32 ?][u32 ncomp][ncomp x NUL-term component]
# giving the volume-relative path.  The exact FCP <pathurl> = file://localhost/ + the
# NFD-normalised, percent-encoded join of [volume]+components, with intra-name '/'
# stored as ':'.  These three rules reproduce all 212 palastin oracle pathurls exactly.
# '&' stays literal (XML-escaped to &amp;), matching FCP; percent-encoding it as %26
# makes Premiere silently reject the import. See export._PATHURL_SAFE.
_PATHURL_SAFE = "/():,-._&"


def _decode_carbon_path(blob):
    if len(blob) < 12:
        return None
    _flag, _q, nc = struct.unpack_from("<III", blob, 0)
    if not (1 <= nc <= 64):
        return None
    off, comps = 12, []
    for _ in range(nc):
        e = blob.find(b"\x00", off)
        if e < 0:
            return None
        seg = blob[off:e]
        try:
            comps.append(seg.decode("utf-8"))
        except UnicodeDecodeError:
            try:
                comps.append(seg.decode("mac_roman"))
            except UnicodeDecodeError:
                return None
        off = e + 1
    return comps


def filespec_pathurl(d, node_off, hi):
    """Exact FCP <pathurl> for a FILESPEC node, or None if not a decodable source."""
    fs = W.try_filespec(d, node_off, hi)
    if not fs:
        return None
    _end, _nf, spans = fs
    if len(spans) < 5 or spans[2][1] == 0 or spans[4][1] == 0:
        return None
    vol = d[spans[2][0]:spans[2][0] + spans[2][1]].decode("utf-8", "replace")
    comps = _decode_carbon_path(d[spans[4][0]:spans[4][0] + spans[4][1]])
    if not comps:
        return None
    parts = [vol.replace("/", ":")] + [c.replace("/", ":") for c in comps]
    full = unicodedata.normalize("NFD", "/" + "/".join(parts))
    # A network mount (cifs/afp/smb/nfs) is written with its full /Volumes/ mount path
    # (the scheme marker trails the FILESPEC in the alias); a physical volume is written
    # volume-rooted (…/disque 1/… not /Volumes/disque 1/…) — FCP's own convention.
    if any(s in d[node_off:_end + 300]
           for s in (b"cifs", b"afpfs", b"smb://", b"afp://", b"nfs", b"webdav")):
        full = "/Volumes" + full
    return "file://localhost" + quote(full, safe=_PATHURL_SAFE)


def _is_cache_pathurl(p):
    return any(s in p for s in ("Final%20Cut%20Pro%20Documents", "Waveform",
                                "Render%20Files", "Thumbnail"))


_PTR_MIN = 0x1000000   # a masterClips value at/above this is a raw PPC heap
#                        pointer (v0x13 BE dialect), never a table id
_PATHURL_FS_WINDOW = 15000     # a master's own source FILESPEC can sit this far after
#                                its object head (older formats carry bulkier masters —
#                                tcData/SMPTE metadata — than the 4 KB that fit palastin)


def build_pathurl_resolver(doc):
    """Return resolve(el) -> (master_uuid, pathurl, subclip) for a clip
    element; subclip is None or the (startoffset, endoffset) pair of a
    consolidated subclip (v0x13, see below).

    Attribution is STRUCTURAL and name-independent (a basename can map to several
    real paths — e.g. the same clip name on different camera cards): a clip's
    masterClips.master id -> the master's file offset via id_at_pos -> the first
    source FILESPEC within a window.  pathurl is None when unresolved (caller keeps
    the offline placeholder).

    Two corrections make this hold across formats: (1) the id is a byte-TRUE id while
    id_at_pos is the raw running counter, so on drifted formats the two diverge
    (accumulating, per _seq_anchors) and a plain lookup lands on a NEIGHBOURING master
    — anchor-correct true->raw first; (2) older projects carry bulkier masters, so the
    FILESPEC window is 15 KB, not 4.  Validated: palastin 0 changed vs the prior 4 KB
    resolver (+306 clips gained, still 207 distinct sources), EPK Cut 6 256/262 clips
    at 100% precision vs FCP (was 134 mostly wrong)."""
    d, hi = doc.d, len(doc.d) - 16
    allfs = sorted((n.off, filespec_pathurl(d, n.off, hi))
                   for n in doc.root.walk() if n.kind == "FILESPEC")
    allfs = [(o, p) for o, p in allfs if p and not _is_cache_pathurl(p)]
    offs = [o for o, _ in allfs]
    pos_by_id = {v: k for k, v in doc.id_at_pos.items()}
    ids_sorted = sorted(pos_by_id)
    curve = doc._merged_anchors()                # (true_id, E) dense, sorted
    ctrues = [a[0] for a in curve]

    def _offset(u):
        # dense-anchor-corrected true->model before the offset lookup (the
        # sparse per-sequence delta misses when bulk-credited megaslot
        # interiors shift the mapping between anchor and master).  A master id
        # can itself land inside a bulk credit (a megaslot interior allocates
        # up to ~26 ids at one byte position), so fall back to the nearest
        # allocated id at or below the target: its event offset lower-bounds
        # the master's, and the first-FILESPEC-after window absorbs the slack.
        if isinstance(u, int):
            m = u
            if ctrues:
                j = bisect.bisect_right(ctrues, u) - 1
                if j >= 0:
                    m = u - curve[j][1]
            o = pos_by_id.get(m)
            if o is not None:
                return o
            j = bisect.bisect_right(ids_sorted, m) - 1
            if j >= 0 and m - ids_sorted[j] <= 32:
                return pos_by_id[ids_sorted[j]]
        return pos_by_id.get(u)

    # ------------------------------------------------------------------
    # v0x13 (PPC 2006 dialect): masterClips.master values are raw PowerPC
    # heap POINTERS (0x188d....), not table ids, so _offset() can never
    # resolve them.  The pointer maps structurally: every browser master's
    # own inner clipitem carries the SAME pointer as a self-reference.
    # A subclip master consolidates onto its SOURCE file (FCP's own export
    # shape: 2 file defs, 99/99 clipitems with <subclipinfo>) when its
    # startoffset/endoffset pair (two F64s on the inner clip, key ids
    # drift-mislabeled onto 'anamorphic'/+1 on this dialect) satisfies
    # startoffset + endoffset + subclip_duration == a recovered source
    # file's duration EXACTLY and uniquely (correct-or-absent: on gate
    # failure the caller keeps today's offline placeholder).  Byte-proven:
    # 81 masters satisfy the identity against the tape (dur 96249), all 39
    # named timeline sources, 38/38 oracle-exact subclipinfo, 0 wrong.
    # ------------------------------------------------------------------
    _v13 = {"built": False, "ptr": {}}

    def _clip_ptr(el):
        mc = doc.get(el, "masterClips")
        mu = doc.get(mc, "master") if mc is not None else None
        return mu.value if (mu is not None and mu.value) else None

    def _build_v13():
        _v13["built"] = True
        anam = doc.ids.get("anamorphic")
        media_by_path, _mbn = build_source_media_map(doc)
        src_durs = {pu: int(mc["duration"]) for pu, mc in media_by_path.items()
                    if mc.get("duration")}
        for nd in doc.root.walk():
            if not _is_seq_shaped(doc, nd) or _has_timeline(doc, nd):
                continue
            med = doc.get(nd, "media")
            inners = []
            for mk in ("vidm", "audm"):
                m = doc.get(med, mk) if med is not None else None
                trk = doc.get(m, "track") if m is not None else None
                for te in (trk.elements() if trk is not None else []):
                    cl = doc.get(te, "clip")
                    for el in (cl.elements() if cl is not None else []):
                        if _elem_kind(doc, el) == "clip":
                            inners.append(el)
            if not inners:
                continue
            ptr = _clip_ptr(inners[0])
            if not isinstance(ptr, int) or ptr < _PTR_MIN:
                continue
            entry = {"node": nd, "pathurl": None, "subclip": None}
            # (a) subclip consolidation: so/eo + duration identity (any inner
            # clip may carry the pair — the doc-head master's video clip
            # serializes at a different local key drift than its audio twins)
            du = doc.get(nd, "duration")
            saw_soeo = False
            for inner in inners:
                so = inner.get(anam) if anam else None
                eo = inner.get(anam + 1) if anam else None
                if (so is not None and eo is not None and du is not None
                        and so.kind == "F64" and eo.kind == "F64"
                        and so.value is not None and eo.value is not None
                        and du.value):
                    saw_soeo = True
                    total = int(so.value) + int(eo.value) + int(du.value)
                    hits = [pu for pu, D in src_durs.items() if D == total]
                    if len(hits) == 1:
                        entry["pathurl"] = hits[0]
                        entry["subclip"] = (int(so.value), int(eo.value))
                        break
            # (b) the master's own source FILESPEC — true originals only: a
            # subclip whose identity gate FAILED must stay offline (its
            # in/out are subclip-relative; a source ref without subclipinfo
            # would be WRONG relink data)
            if entry["pathurl"] is None and not saw_soeo:
                j = bisect.bisect_left(offs, nd.off)
                if j < len(offs) and offs[j] - nd.off <= _PATHURL_FS_WINDOW:
                    entry["pathurl"] = allfs[j][1]
            _v13["ptr"].setdefault(ptr, entry)

    def resolve(el):
        mc = doc.get(el, "masterClips")
        mu = doc.get(mc, "master") if mc is not None else None
        u = mu.value if (mu is not None and mu.value) else None
        if u is None:
            return None, None, None
        o0 = _offset(u)
        if o0 is None:
            if isinstance(u, int) and u >= _PTR_MIN:
                if not _v13["built"]:
                    _build_v13()
                ent = _v13["ptr"].get(u)
                if ent is not None and ent["pathurl"]:
                    # key consolidated subclips by their SOURCE so they share
                    # one file def (FCP's own export shape)
                    return "src:" + ent["pathurl"], ent["pathurl"], ent["subclip"]
            return u, None, None
        j = bisect.bisect_left(offs, o0)
        if j < len(offs) and offs[j] - o0 <= _PATHURL_FS_WINDOW:
            return u, allfs[j][1], None
        return u, None, None

    return resolve


def _tc_key_drift(doc):
    """The constant offset between the tc keys' DEF ids and the NKEY ids that actually
    reference them.  Most projects have 0, but some (older/managed FCP formats, e.g.
    EPK) diverge: the parser's `object_table` under-counts a few slots before the tc
    key block, so every NKEY reference to a tc key sits a fixed amount above its DEF
    id (e.g. +3: `segStart` DEF 481 but referenced as 484).  The whole tc key cluster
    (tcData/tcTracks/tcSegments/segStart/numFrames/displayFormat/reel) shares ONE
    drift, so we calibrate it once by voting on the F64 (`segStart`) key ids that sit
    just above the segStart DEF id."""
    seg = doc.ids.get("segStart")
    if seg is None:
        return 0
    votes = {}
    for nd in doc.root.walk():
        for c in nd.children:
            if c.role == "key" and isinstance(c.name, int) and c.children:
                v = c.children[0]
                if getattr(v, "kind", None) == "F64" and v.value and v.value > 50000:
                    d = c.name - seg
                    if 0 <= d <= 12:
                        votes[d] = votes.get(d, 0) + 1
    return max(votes, key=votes.get) if votes else 0


def build_source_tc_map(doc):
    """Return {pathurl: {'frame','displayformat','timebase','ntsc'}} — each source
    media file's embedded start timecode, keyed by its pathurl.

    FCP caches a source clip's embedded timecode on the BROWSER master object (name
    e.g. 'sync ordon') as tcData/tcTracks[]/tcSegments[]: the segment holds a F64
    `segStart` (the media start frame, e.g. 90000 = 01:00:00:00 @ 25) and
    `displayFormat`; the tcTrack holds the media rate `numFrames` (the MEDIA fps, not
    the sequence's — a 25fps clip in a 24fps timeline stays 25).  Resolve matches this
    start TC against the real media file on relink; without it a retimed/offset clip's
    source extents fall outside the media and it refuses to link ("timecode extents do
    not match any clip in the Media Pool").

    The browser master's UUID does NOT equal the timeline clip's masterClips.master
    ref, and the segments are too densely packed for offset-proximity attribution, so
    the join key is the PATHURL: a browser master and every timeline clip of the same
    source resolve (via the FILESPEC alias blobs) to the same media file.  Validated on
    palastin: all 114 timecode-named .WAV sources recover a segStart matching the
    timecode encoded in the filename (0 mismatches), 1141 clips attributed.  A per-doc
    key-id drift (see `_tc_key_drift`) is applied so the DEF-vs-NKEY divergence of
    older formats (EPK: +3) resolves the same as the aligned case (palastin: 0)."""
    tcd_id = doc.ids.get("tcData")
    if tcd_id is None or doc.ids.get("segStart") is None:
        return {}
    drift = _tc_key_drift(doc)

    def gd(node, name):
        """Drift-aware get: normal resolution, then the NKEY id shifted by the drift."""
        if node is None:
            return None
        v = doc.get(node, name)
        if v is None and drift and name in doc.ids:
            v = node.get(doc.ids[name] + drift)
        return v

    def has_tcdata(nd):
        for c in nd.children:
            if c.role == "key" and c.name in (tcd_id, tcd_id + drift, "tcData"):
                return True
        return False

    def first_elem(c):
        els = c.elements() if c is not None else []
        return els[0] if els else None

    def node_tc(nd):
        tcd = gd(nd, "tcData")
        tctrk = first_elem(gd(tcd, "tcTracks"))
        if tctrk is None:
            return None
        seg = first_elem(gd(tctrk, "tcSegments"))
        fr = gd(seg, "segStart")
        if fr is None:
            return None
        rate = gd(tctrk, "numFrames")
        df = gd(seg, "displayFormat")
        nt = gd(tctrk, "ntsc")
        reel = doc.resolve_str(gd(tctrk, "reel"))     # camera/tape reel for relink
        out = {"frame": int(round(float(fr.value))),
               "timebase": int(rate.value) if rate is not None else None,
               "displayformat": "DF" if (df is not None and df.value) else "NDF",
               "ntsc": "TRUE" if (nt is not None and nt.value) else "FALSE"}
        if reel:
            out["reel"] = reel
        return out

    hi = len(doc.d) - 16
    allfs = sorted((n.off, filespec_pathurl(doc.d, n.off, hi))
                   for n in doc.root.walk() if n.kind == "FILESPEC")
    allfs = [(o, p) for o, p in allfs if p and not _is_cache_pathurl(p)]
    fs_offs = [o for o, _ in allfs]
    # master-name -> pathurl: a browser master's name is its media file's stem
    # (e.g. '0034FL' -> '.../0034FL.mov'); the exact join, taken first wherever
    # the name resolves.
    stem_path = {}
    for _o, p in allfs:
        stem_path.setdefault(unquote(p.rsplit("/", 1)[-1]).rsplit(".", 1)[0], p)

    tcs = []
    for nd in doc.root.walk():
        if not has_tcdata(nd):
            continue
        tc = node_tc(nd)
        if tc is None:
            continue
        tcs.append((nd.off, tc, doc.resolve_str(gd(nd, "name"))))
    tcs.sort(key=lambda t: t[0])
    nd_offs = [o for o, _, _ in tcs]

    out = {}
    # pass 1: the exact master-name -> file-stem join (correct where names resolve).
    for _o, tc, nm in tcs:
        p = stem_path.get(nm) if nm else None
        if p is not None:
            out.setdefault(p, tc)
    # pass 2: STRUCTURAL mutual-nearest join — the same master-head -> own-FILESPEC
    # adjacency build_pathurl_resolver relies on (the tc-carrying node IS the browser
    # master object, its source FILESPEC follows within _PATHURL_FS_WINDOW).  The
    # pairing must be MUTUAL: the tc-node takes the first FILESPEC at off >= its own,
    # and only if it is also the LAST tc-node before that FILESPEC — a master whose
    # own FILESPEC is missing would otherwise steal the NEXT master's file and attach
    # a wrong timecode (worse than none: it breaks relink).  Validated: EPK 87/87
    # files match FCP's own <timecode> (0 wrong, 0 absent; was 25/87), palastin WAV
    # oracle 114/114 preserved.
    for i, (ndoff, tc, _nm) in enumerate(tcs):
        j = bisect.bisect_left(fs_offs, ndoff)
        if j >= len(fs_offs) or fs_offs[j] - ndoff > _PATHURL_FS_WINDOW:
            continue
        if bisect.bisect_right(nd_offs, fs_offs[j]) - 1 != i:
            continue                    # another tc-node sits between: not ours
        out.setdefault(allfs[j][1], tc)
    return out


def generator_fields(doc, el, mediatype):
    """Surface a generatoritem track-element (text/slug/colour) for the emitter."""
    eff = doc.get(el, "effect")
    return {
        "kind": "generator", "mediatype": mediatype,
        "name": doc.resolve_str(doc.get(el, "name")),
        "text": _gen_text(doc, eff),
        "in": _f64_int(doc, el, "in", []),
        "out": _f64_int(doc, el, "out", []),
        "start": _f64_int(doc, el, "start", []),
        "end": _f64_int(doc, el, "end", []),
        "duration": _f64_int(doc, el, "duration", []),
        "effectid": doc.resolve_str(doc.get(eff, "scriptid")) if eff is not None else None,
    }


def _f64_int(doc, el, key, flags):
    v = doc.get(el, key)
    if v is None:
        flags.append(key)
        return None
    try:
        return int(round(float(v.value)))
    except (TypeError, ValueError):
        flags.append(key)
        return None


# --- per-clip audio filters (audiolevels / audiopan) --------------------------
#
# The animation lives DIRECTLY under a clip element's `volume` and `pan` keys
# (the top-level `filters` key is empty for audio), each an object:
#     { min:F32, max:F32, value:F32, keyframe: [ {when:F64, value:F32}, ... ] }
# The stored numbers ARE what FCP emits verbatim -- no dB/base transform:
#   binary volume.value/keyframe.value == oracle <value> (a linear gain ratio,
#     i.e. 10^(dB/20) already applied), and keyframe.when F64 == oracle <when>,
#   both simply formatted with FCP's %g (6 sig figs).  Proven byte-exact against
#   "MONTAGE FINAL .xml": all 55 keyframed audio clips' (when,value) arrays match.
#
# The F32 leaf value is NOT carried in the walker event (keyg_walker2 emits F32
# without its payload); read it from the 4-byte little-endian float at off+5
# (tag[0], flag[4], float[5:9]).
import math as _math


def _f32_leaf(doc, node):
    if node is None or node.kind != "F32":
        return None
    v = struct.unpack_from("<f", doc.d, node.off + 5)[0]
    return v if _math.isfinite(v) else None


def _audio_param(doc, box, pname, pid, default):
    """Build one <parameter> spec (keyframed or static) from a volume/pan box,
    or None when the box is absent, unreadable, or default-valued (noise)."""
    if box is None:
        return None
    vmin = _f32_leaf(doc, doc.get(box, "min"))
    vmax = _f32_leaf(doc, doc.get(box, "max"))
    kf = doc.get(box, "keyframe")
    keys = []
    if kf is not None:
        for e in kf.elements():
            w = doc.get(e, "when")
            v = _f32_leaf(doc, doc.get(e, "value"))
            if w is None or v is None or not _math.isfinite(float(w.value)):
                continue
            keys.append((float(w.value), v))
    if keys:
        return {"name": pname, "parameterid": pid,
                "valuemin": vmin if vmin is not None else 0.0,
                "valuemax": vmax if vmax is not None else 1.0,
                "value": None, "keyframes": keys}
    val = _f32_leaf(doc, doc.get(box, "value"))
    if val is None or val == default:            # default/unreadable static: noise
        return None
    return {"name": pname, "parameterid": pid,
            "valuemin": vmin if vmin is not None else 0.0,
            "valuemax": vmax if vmax is not None else 1.0,
            "value": val, "keyframes": []}


def _fixed_point(doc, node):
    """A center/anchor keyframe value is a FIXED point -> (horiz, vert) F32 pair."""
    if node is None or node.kind != "FIXED":
        return None
    h = struct.unpack_from("<f", doc.d, node.off + 5)[0]
    v = struct.unpack_from("<f", doc.d, node.off + 9)[0]
    return (h, v) if (_math.isfinite(h) and _math.isfinite(v)) else None


def _motion_param(doc, box, pid, name, vmin, vmax, point=False, default=0.0):
    """One motion <parameter> spec, read drift-proof: the static value is the box's
    first F32 (scalar) or FIXED (point) leaf — `{value,min,max}` is value-first — and
    keyframes come from the box's child list, each element's F64 leaf = `when` and its
    F32/FIXED leaf = the value.  (The intra-node member keys id-drift, so we read by
    position, not name; the filter/param BOXES are still located by name via _Doc.get,
    which the object-slot fallback resolves.)

    When the box is ABSENT the param falls back to `default` — FCP omits a default
    param from the binary but still writes it in the XML (e.g. a still with only a
    scale+centre move has no rotation/anchor box, yet exports rotation=0/anchor=(0,0));
    so we always emit the full param set, defaulting the ones the clip didn't store."""
    if box is None:
        return {"name": name, "parameterid": pid, "valuemin": vmin, "valuemax": vmax,
                "value": default, "keyframes": [], "point": point, "idfirst": True}
    d = doc.d
    leafkind = "FIXED" if point else "F32"

    def rd(n):
        if point:
            return (struct.unpack_from("<f", d, n.off + 5)[0],
                    struct.unpack_from("<f", d, n.off + 9)[0])
        return struct.unpack_from("<f", d, n.off + 5)[0]

    keys = []
    kflist = next((v for _, v in box.entries() if v is not None and v.elements()), None)
    if kflist is not None:
        for e in kflist.elements():
            w = next((x for x in e.walk() if x.kind == "F64"), None)
            vv = next((x for x in e.walk() if x.kind == leafkind), None)
            if w is not None and vv is not None:
                keys.append((struct.unpack_from("<d", d, w.off + 5)[0], rd(vv)))
    fe = [v for _, v in box.entries() if v is not None and v.kind == leafkind]
    val = rd(fe[0]) if fe else (0.0, 0.0) if point else 0.0
    return {"name": name, "parameterid": pid, "valuemin": vmin, "valuemax": vmax,
            "value": val, "keyframes": keys, "point": point, "idfirst": True}


_CC_NUM = ("dispmode", "highlights", "mids", "blacklevel", "hue", "mag", "chroma",
           "phase", "centerang", "chromawidth", "chromasoft", "satmin", "satwidth",
           "satsoft", "lumamin", "lumawidth", "lumasoft", "edgethin", "edgefeather")
_CC_BOOL = ("dochroma", "dosat", "doluma", "invertsel", "debugshow")


def _cc_value(doc, cc, pid, is_bool):
    box = doc.get(cc, pid)
    if box is None:
        return None
    if box.kind == "BOOL":
        return bool(box.value)
    v = doc.get(box, "value")
    if v is None:
        return None
    if v.kind == "BOOL":
        return bool(v.value)
    if v.kind == "F32":
        return _f32_leaf(doc, v)
    if is_bool:
        return bool(v.value)
    if isinstance(v.value, float) and not _math.isfinite(v.value):
        return None                    # non-finite grade -> neutralize to default
    return v.value


# binary metadata key -> xmeml Browser-column field. Binary `label` is the free-text
# Description column (the colour Label is a separate enum, not handled here); `take` is
# Shot/Take; `labelComment` is Label 2; `comment1-4` are Master Comment 1-4.
_META_KEYS = {
    "label": "description", "scene": "scene", "take": "shottake",
    "lognote": "lognote", "labelComment": "label2",
    "comment1": "mastercomment1", "comment2": "mastercomment2",
    "comment3": "mastercomment3", "comment4": "mastercomment4",
}

# Comment A / Comment B live on the clip's track anchor (one level up), not the
# clipitem — recovered separately via clip_metadata's `container` argument.
_CONTAINER_META_KEYS = {"comment5": "clipcommenta", "comment6": "clipcommentb"}

# The Browser "Label" column: an INT enum on the `labelColor` key -> FCP's colour
# name (0 = None, no <label>).  Cracked against the labels oracle: five clips, one
# per colour, matched by both the master uuid->colour join and the timeline order.
_LABEL_COLORS = {
    1: "Good Take", 2: "Best Take", 3: "Alternate Shots",
    4: "Interviews", 5: "B Roll",
}


def clip_label_color(doc, el):
    """The Browser Label colour for a clip -> its FCP name, or None for "None".

    `labelColor` is an INT enum 0..5.  Per-clip object-table id drift can shift the
    key so the table mislabels it (the colour lands one id past where the table
    thinks labelColor is); when the labelColor-named entry resolves to a non-INT —
    the drift signature — we read the next byte-stream id and accept only a valid
    non-zero enum.  Validated: recovers every coloured clip in the labels oracle
    (masters + timeline) with zero false positives across palastin's 3852 clips."""
    base = doc.ids.get("labelColor")
    v = doc.get(el, "labelColor")
    val = 0
    if v is not None and v.kind == "INT" and 0 <= v.value <= 5:
        val = v.value
    elif base is not None and v is not None and v.kind == "BOOL":
        n = el.get(base + 1)                    # drift: labelColor sits one id later
        if n is not None and n.kind == "INT" and 1 <= n.value <= 5:
            val = n.value
    return _LABEL_COLORS.get(val)


# Composite (blend) mode: an INT enum on the `keytype` key -> the xmeml
# <compositemode> token.  0/absent = Normal (no element emitted).  Cracked against
# the composite_mode oracle (12 clips, one mode each, in this exact order); palastin
# reads 0/None on all 1954 clips (no false positives).  Note the UI->token renames:
# Overlay=texturize, Travel Matte Alpha=mask, Travel Matte Luma=lumamask.
_COMPOSITE_MODES = {
    0: "normal", 1: "add", 2: "subtract", 3: "difference", 4: "multiply",
    5: "screen", 6: "texturize", 7: "hardlight", 8: "softlight", 9: "darken",
    10: "lighten", 11: "mask", 12: "lumamask",
}


def clip_composite_mode(doc, el):
    """The clip's composite/blend mode -> its xmeml <compositemode> token, or None.

    FCP emits <compositemode> whenever the `keytype` key is PRESENT (0 -> the
    explicit `normal`, 1-12 -> the blend modes) and omits it when the key is absent
    (byte-proven on the alpha oracle: a Normal+reverse clip keeps keytype=0 and emits
    <compositemode>normal</compositemode>, while an untouched clip has no keytype)."""
    v = doc.get(el, "keytype")
    if v is not None and v.kind == "INT":
        return _COMPOSITE_MODES.get(v.value)
    return None


# Alpha handling: `alphatype` INT enum -> <alphatype> token, and the `alphareverse`
# BOOL -> <alphareverse>. Cracked against the alpha oracle (clips none/straight/black/
# white then a Normal+reverse clip); out-of-enum values (e.g. a generator's 5) and
# palastin fall back to "none".  alphareverse reads 0 TRUE across palastin (no FPs).
_ALPHA_TYPES = {0: "none", 1: "straight", 2: "black", 3: "white"}


def clip_alphatype(doc, el):
    """The clip's <alphatype> token; 'none' for the default or any out-of-enum value."""
    v = doc.get(el, "alphatype")
    if v is not None and v.kind == "INT":
        return _ALPHA_TYPES.get(v.value, "none")
    return "none"


def clip_alpha_reverse(doc, el):
    """True when the clip's Reverse Alpha flag is set (<alphareverse>TRUE</alphareverse>)."""
    v = doc.get(el, "alphareverse")
    return bool(v is not None and v.value)


def clip_metadata(doc, el, container=None):
    """Browser-column metadata (Description/Scene/Shot-Take/Log Note/Good/Label 2/
    Master Comment 1-4/Comment A-B) recovered from a clip's named binary keys.

    Comment A/B (comment5/comment6) are Browser columns stored one level up on the
    clip's track anchor rather than on the clipitem, so pass that node as
    ``container`` to recover them."""
    meta = {}
    sources = [(el, _META_KEYS)]
    if container is not None:
        sources.append((container, _CONTAINER_META_KEYS))
    for node, keymap in sources:
        for bkey, field in keymap.items():
            v = doc.get(node, bkey)
            if v is not None and v.kind.startswith("STR"):
                s = doc.resolve_str(v)
                if s:
                    meta[field] = s
    g = doc.get(el, "good")
    if g is not None and g.value:
        meta["good"] = True
    color = clip_label_color(doc, el)
    if color:
        meta["label_color"] = color
    return meta


def build_source_media_map(doc):
    """Per-source media characteristics -> ({pathurl: chars}, {name: chars}).

    Every source's characteristics live on its FILE OBJECT (the node carrying the
    `reader` FOURCC, e.g. 'QTMRead'): file-level `framebase` INT (= the file
    <rate><timebase>), `ntscrate` BOOL, `duration` F64 (media frames at framebase),
    `width`/`height` (on the first element of the `video` sub-object, falling back
    to file-level keys); on the first element of the `audio` sub-object:
    `sampleRate` (F32 — payload read via _f32_leaf), `channels`, `depth`.  The
    `still` key (FIXED) on the node marks stills/freeze-frames byte-accurately.
    Joins mirror build_source_tc_map: pass 1 = mutual-nearest first-FILESPEC-after
    within _PATHURL_FS_WINDOW; pass 2 = nearest preceding NAMED node (covers
    offline sources with no FILESPEC — all 23 in the managed project).  Oracle-
    validated on the EPK family: 279/279 timebase+ntsc, 270/270 width+height,
    252/252 samplerate+depth+channels, 0 wrong, 0 unjoined; palastin's binary
    carries native truth (24-bit WAVs, 44.1 kHz aiffs, native still dims) where
    FCP's offline exports wrote sequence-preset placeholders."""
    def first_elem(c):
        els = c.elements() if c is not None else []
        return els[0] if els else None

    def iv(x):
        return int(x.value) if x is not None and x.value is not None else None

    hi = len(doc.d) - 16
    allfs = sorted((n.off, filespec_pathurl(doc.d, n.off, hi))
                   for n in doc.root.walk() if n.kind == "FILESPEC")
    allfs = [(o, p) for o, p in allfs if p and not _is_cache_pathurl(p)]
    fs_offs = [o for o, _ in allfs]

    readers, named = [], []
    for nd in doc.root.walk():
        if doc.get(nd, "reader") is not None:
            readers.append(nd)
        else:
            nm = doc.resolve_str(doc.get(nd, "name"))
            if nm:
                named.append((nd.off, nm))
    named.sort()
    noffs = [o for o, _ in named]
    r_offs = [n.off for n in readers]

    def chars(nd):
        r = {"tb": iv(doc.get(nd, "framebase"))}
        nr = doc.get(nd, "ntscrate")
        r["ntsc"] = ("TRUE" if nr.value else "FALSE") if nr is not None else None
        st = doc.get(nd, "still")
        r["still"] = st is not None and st.value is not None
        dur = doc.get(nd, "duration")
        r["duration"] = int(dur.value) if dur is not None and dur.value is not None else None
        v = first_elem(doc.get(nd, "video"))
        if v is not None:
            r["width"], r["height"] = iv(doc.get(v, "width")), iv(doc.get(v, "height"))
        else:
            r["width"], r["height"] = iv(doc.get(nd, "width")), iv(doc.get(nd, "height"))
        a = first_elem(doc.get(nd, "audio"))
        if a is not None:
            sr = _f32_leaf(doc, doc.get(a, "sampleRate"))
            r["samplerate"] = int(round(sr)) if sr else None
            r["channels"] = iv(doc.get(a, "channels"))
            r["depth"] = iv(doc.get(a, "depth"))
        # which media blocks the file really has — FCP emits <video>/<audio>
        # blocks for the file's CONTENT, not its timeline usage (a mono-audio
        # .mov used only on V1 still gets its <audio> block)
        r["has_video"] = v is not None
        r["has_audio"] = a is not None
        return r

    by_path, by_name = {}, {}
    for i, nd in enumerate(readers):
        c = None
        j = bisect.bisect_left(fs_offs, nd.off)
        if (j < len(fs_offs) and fs_offs[j] - nd.off <= _PATHURL_FS_WINDOW
                and bisect.bisect_right(r_offs, fs_offs[j]) - 1 == i):
            c = chars(nd)
            by_path.setdefault(allfs[j][1], c)
        k = bisect.bisect_right(noffs, nd.off) - 1
        if k >= 0 and nd.off - named[k][0] <= _PATHURL_FS_WINDOW:
            by_name.setdefault(named[k][1], c or chars(nd))
    return by_path, by_name


def sequence_timecode(doc, seq):
    """The sequence's own start timecode, or None for FCP's default.

    Returns {'frame': int, 'displayformat': 'DF'|'NDF'} — frame in XML
    semantics (the real frame index; see the DF conversion below).

    Stored in the sequence node's tcData exactly like a source media tc.  The
    export gate (oracle matrix over every corpus): segStart is exported iff
    the track's `numFrames` (rate) OR the segment's `displayFormat` is truthy;
    else 00:00:00:00.
      * EPK family: numFrames=24, df=0, segStart=86400 -> verbatim NDF
        (01:00:00:00), 22/22 + Cut-oracle validated;
      * palastin: numFrames=0, df=0 -> 00:00:00:00 despite the stored 1-hour
        default (22/22 oracle-validated);
      * Aaron (v0x13 NTSC drop-frame): numFrames=0 but df=1 -> exported
        (FCP's own MASTER.xml: 01:00:00;00 / 107892 / DF).
    DF conversion: the stored segStart is DIGIT-ENCODED (HH:MM:SS:FF via
    plain NDF arithmetic: 01:00:00:00 -> 108000 @ tb30), while FCP's XML
    <frame> is the real DF frame index (107892 = 108000 - 2*(60-6)):
    frame = S - d*(min - min//10), min = S // (tb*60), d = 2*(tb//30)."""
    def first_elem(c):
        els = c.elements() if c is not None else []
        return els[0] if els else None
    tcd = doc.get(seq, "tcData")
    trk = first_elem(doc.get(tcd, "tcTracks")) if tcd is not None else None
    if trk is None:
        return None
    seg = first_elem(doc.get(trk, "tcSegments"))
    fr = doc.get(seg, "segStart") if seg is not None else None
    if fr is None or fr.value is None:
        return None
    nf = doc.get(trk, "numFrames")
    df = doc.get(seg, "displayFormat")
    dfv = bool(df is not None and df.value)
    if (nf is None or not nf.value) and not dfv:
        return {"frame": 0, "displayformat": "NDF"}
    s = int(fr.value)
    if dfv:
        tbn = doc.get(trk, "tcbase")
        if tbn is None or not tbn.value:
            # v0x13 tc tracks carry tcbase at a different local drift than the
            # rest of the cluster; the sequence's own framebase is the same
            # rate (both 30 on the DF corpus) and always resolves
            tbn = doc.get(seq, "framebase")
        tb = int(tbn.value) if tbn is not None and tbn.value else 0
        if tb and tb % 30 == 0:
            d = 2 * (tb // 30)
            mins = s // (tb * 60)
            return {"frame": s - d * (mins - mins // 10),
                    "displayformat": "DF"}
        # DF flagged at a non-NTSC/unknown base: DF math would be WRONG
        # relink data — keep the verbatim NDF reading (correct-or-absent)
    return {"frame": s, "displayformat": "NDF"}


def clip_markers(doc, el):
    """Markers on a clip element (or a sequence node) -> [{'name','in','out'}].

    The `markers` key holds an OBJINL element list; each marker element carries
    `name` (STRREF/STRINL), `in` (F64, source-time frames) and `out` (F64, -1 for
    a point marker) under the ordinary clip-timing keys — byte-verified against
    FCP's own <marker> blocks (name 'Marker 2' / in 146 / out -1 etc.).  Comments
    are empty across the corpus; the emitter writes FCP's defaults (<comment/>,
    red color)."""
    box = doc.get(el, "markers")
    if box is None:
        return []
    out = []
    for me in box.elements():
        iv = doc.get(me, "in")
        if iv is None or iv.value is None:
            continue
        ov = doc.get(me, "out")
        nm = doc.resolve_str(doc.get(me, "name"))
        out.append({"name": nm or "",
                    "in": int(iv.value),
                    "out": int(ov.value) if ov is not None and ov.value is not None else -1})
    return out


def clip_color_correctors(doc, el):
    """Recovered Color Corrector grades for a video clip: each user filter under
    el.filters that carries the grade params (identified by `highlights`) yields a
    {parameterid -> value} dict the emitter renders through the fixed CC template."""
    fil = doc.get(el, "filters")
    if fil is None:
        return []
    out = []
    for fe in fil.elements():
        # the CC param container is the node inside the filter carrying `highlights`
        cc = next((nd for nd in fe.walk() if doc.get(nd, "highlights") is not None), None)
        if cc is None:
            continue
        vals = {}
        for pid in _CC_NUM:
            v = _cc_value(doc, cc, pid, False)
            if v is not None:
                vals[pid] = v
        for pid in _CC_BOOL:
            v = _cc_value(doc, cc, pid, True)
            if v is not None:
                vals[pid] = v
        out.append(vals)
    return out


# Non-English filter display names -> canonical English library key (the binary
# `name` is the LOCALIZED display string; `scriptid` is the language-independent
# English id and is tried first now that drift-corrected resolution recovers it).
_FILTER_XLATE = {
    "Sépia": "Sepia", "Retournement": "Flop", "Étalonnage": "Color Corrector",
}


def clip_named_filters(doc, el):
    """Recover user video filters on a clip via the name->template library (blurs,
    stylize, distort, …). `scriptid` (English, language-independent) is the primary
    key; the display `name` (possibly localized — translated via _FILTER_XLATE) is
    the fallback. Color Corrector is handled separately (real grade extraction);
    audio + unknown/plugin -> skipped."""
    from .fcp_filters import VIDEO_FILTERS
    fil = doc.get(el, "filters")
    if fil is None:
        return []
    out = []
    for fe in fil.elements():
        eff = doc.get(fe, "effect")
        if eff is None:
            continue
        sid = doc.resolve_str(doc.get(eff, "scriptid"))
        nm = doc.resolve_str(doc.get(eff, "name"))
        nm = _FILTER_XLATE.get(nm, nm)
        if "Color Corrector" in (sid, nm):
            continue
        block = VIDEO_FILTERS.get(sid) or VIDEO_FILTERS.get(nm)
        if block:
            out.append(block)
    return out


import re as _re
# The Audio-Unit component descriptor inside an audio filter element:
# [02 00 00 02][00 00 00 01][subtype FourCC, little-endian][00 00 06 02]. The subtype
# is the per-filter identity (audio filter names don't resolve in the binary).
_AU_SUBTYPE_PAT = _re.compile(rb"\x02\x00\x00\x02\x00\x00\x00\x01(....)\x00\x00\x06\x02", _re.S)


def clip_audio_named_filters(doc, el):
    """Recover user AUDIO filters on a clip (EQ/compressor/reverb/AU…) by their AU
    component SUBTYPE code extracted from each filter element's bytes, mapped through
    the subtype-keyed AUDIO_FILTERS library. audiolevels/audiopan are handled elsewhere;
    video clips have no AU descriptor so this returns []."""
    from .fcp_audio_filters import AUDIO_FILTERS
    fil = doc.get(el, "filters")
    if fil is None:
        return []
    fes = fil.elements()
    offs = sorted(fe.off for fe in fes)
    out = []
    for fe in fes:
        nxt = min((o for o in offs if o > fe.off), default=fe.off + 3000)
        m = _AU_SUBTYPE_PAT.search(doc.d[fe.off:nxt])
        if not m:
            continue
        sub = m.group(1)[::-1].decode("mac_roman", "replace")   # little-endian -> FourCC
        block = AUDIO_FILTERS.get(sub)
        if block:
            out.append(block)
    return out


# The motion filters we emit, in FCP's clipitem order, with each param's (id, display
# name, valuemin, valuemax, is-point).  Basic Motion / Crop / Opacity are the always-on
# visible transforms and — unlike Drop Shadow / Motion Blur / Distort — carry no
# <enabled> wrapper and a regular {value,min,max} param layout, so they render through
# the standard filter path.  Drop Shadow / Motion Blur / Distort / Time Remap have
# irregular layouts (interleaved enabled flags, RGBA colour, relocated params) and are
# deferred; they default to off/identity, so omitting them is visually faithful.
# (paramid, display name, valuemin, valuemax, is-point, default) — `default` is used
# when the clip didn't store that param (FCP omits defaults from the binary but still
# writes them in the XML, so we fill them to emit the complete param set).
_MOTION_FILTERS = [
    ("basic", "Basic Motion", [
        ("scale", "Scale", 0.0, 1000.0, False, 100.0),
        ("rotation", "Rotation", -8640.0, 8640.0, False, 0.0),
        ("center", "Center", None, None, True, (0.0, 0.0)),
        ("centerOffset", "Anchor Point", None, None, True, (0.0, 0.0))]),
    ("crop", "Crop", [
        ("left", "left", 0.0, 100.0, False, 0.0), ("right", "right", 0.0, 100.0, False, 0.0),
        ("top", "top", 0.0, 100.0, False, 0.0), ("bottom", "bottom", 0.0, 100.0, False, 0.0),
        ("edgefeather", "edgefeather", 0.0, 100.0, False, 0.0)]),
    ("opacity", "Opacity", [("opacity", "opacity", 0.0, 100.0, False, 100.0)]),
]


def _motion_filters_from_box(doc, motion):
    """Basic Motion / Crop / Opacity specs from a `motion` box -> emit.Filter specs."""
    out = []
    for eid, nm, params in _MOTION_FILTERS:
        fbox = doc.get(motion, eid)
        if fbox is None:               # this filter's box isn't on the clip -> not emitted
            continue
        specs = [_motion_param(doc, doc.get(fbox, pid), pid, pn, vmin, vmax, pt, dflt)
                 for pid, pn, vmin, vmax, pt, dflt in params]
        out.append({"effectid": eid, "name": nm, "category": "motion",
                    "effecttype": "motion", "mediatype": "video", "parameters": specs})
    return out


def _recover_spilled_motion(doc, el):
    """Recover a `motion` box that spilled OUT of its clipitem dict.

    A few v0x17 opacity-fade clips whose waveform-cache-render FILESPEC seeds a
    tokenizer phantom lose their trailing `motion` box: the phantom consumes a
    member slot and cascades an overflow that expels the motion box (the clip's
    LAST member) out of the clipitem dict into an enclosing array, so
    doc.get(el,'motion') misses it.  The clip's name/in/out/duration/file are
    untouched (census/names/timing stay exact) — only the trailing motion box
    escapes.  It lands immediately past the clip's own subtree, as a stray keyed
    OBJINL child of one of el's ancestors (el.parent when the clip is a non-final
    array member; a higher ancestor when it is the array's last element and the
    array had already closed).

    Recover it structurally, correct-or-absent: among the stray keyed OBJINL
    children of el's ancestor chain whose byte offset falls in the clip's own span
    (past el's subtree, before the next clip), take the UNIQUE one that resolves as
    a keyframed motion box.  The resolve-as-keyframed-motion test rejects unrelated
    stray objects (empty render-cache siblings resolve no basic/crop/opacity param),
    and the single-match requirement keeps it from ever guessing."""
    par = el.parent
    if par is None:
        return None
    sibs = par.elements()
    try:
        idx = sibs.index(el)
    except ValueError:
        return None
    lo = _subtree_hi(el)
    last = idx + 1 >= len(sibs)
    hi = (lo + 0x100) if last else sibs[idx + 1].off
    cands = []
    node = par
    while node is not None:
        for ch in node.children:
            if ch.role == "key" and ch.children and lo < ch.off < hi:
                v = ch.children[0]
                if v is not None and v.kind in ("OBJINL", "OBJINL1", "OTAGINL") \
                        and any(len(p["keyframes"]) >= 2
                                for f in _motion_filters_from_box(doc, v)
                                for p in f["parameters"]):
                    cands.append(v)
        if not last:                   # a non-final member's box stays in el.parent;
            break                      #   only a last-element box spills further up
        node = node.parent
    return cands[0] if len(cands) == 1 else None


def clip_motion_filters(doc, el):
    """Basic Motion / Crop / Opacity for a video clip -> neutral filter specs (the
    emitter maps each to an emit.Filter, same path as audio/CC).  Emitted only when the
    clip carries a resolvable `motion` box — matching FCP, which writes these filters
    for a clip whose Motion tab was touched and none for untouched footage; Slugs and
    other generators don't resolve a motion box (R1) and are skipped.  Values/keyframes
    are read positionally by _motion_param (drift-proof).  Byte-validated against the
    all_motion (static), motion_keyframes (animated) and explicit-filter oracles.

    When doc.get misses the box because the phantom-cascade expelled it from the
    clipitem dict (_recover_spilled_motion), fall back to the recovered box."""
    motion = doc.get(el, "motion")
    if motion is None:
        motion = _recover_spilled_motion(doc, el)
        if motion is None:
            return []
    return _motion_filters_from_box(doc, motion)


def clip_audio_filters(doc, el):
    """Neutral filter specs for an audio clip element: audiolevels (from `volume`)
    and audiopan (from `pan`), each present ONLY when keyframed or non-default so
    import never carries byte-noise.  Each spec is a dict the emitter maps 1:1 to
    an emit.Filter -> emit.Parameter -> emit.Keyframe."""
    out = []
    lvl = _audio_param(doc, doc.get(el, "volume"), "Level", "level", 1.0)
    if lvl is not None:
        out.append({"effectid": "audiolevels", "name": "Audio Levels",
                    "category": "audiolevels", "effecttype": "audiolevels",
                    "mediatype": "audio", "parameters": [lvl]})
    pan = _audio_param(doc, doc.get(el, "pan"), "Pan", "pan", 0.0)
    if pan is not None:
        out.append({"effectid": "audiopan", "name": "Audio Pan",
                    "category": "audiopan", "effecttype": "audiopan",
                    "mediatype": "audio", "parameters": [pan]})
    return out


_SPEEDSEG = b"14FCSpeedSegment"
_SEG_F64 = _re.compile(rb"\x04\x00\x00\x00\x01(.{8})", _re.S)
_FIXED_TAGS = frozenset((0x02, 0x08, 0x0e, 0x0f, 0x11, 0x12))


def _seg_fields_from_bytes(d, seg):
    """Parse a 14FCSpeedSegment's OWN records from the byte stream (the fallback
    for clips whose segment the walker didn't attach as a T20 node).  COUNT-AWARE:
    the PTOK word after the class name is the segment's record count, so we read
    exactly that many keyed records [00][u4le key][tag][pad3][u4be cnt][value] /
    spelled DEFs — a sibling F64 past the count (the neighbouring start/end
    fields) can no longer leak into the anchorOffset sum, and a FIXED-tag record
    or literal `reverse` key flags reverse WITHOUT ending the scan (the anchor
    sub-offsets FOLLOW the flag on reverse clips).  Returns (iu, od, ao, reverse)
    or None; anchorOffset = sum of the F64s after inputUsed/outputDuration."""
    # record grammar (matches keyg_walker2._value): NKEY = [00][u4le key], then
    # VALUE = [tag][pad3][a][payload]; so from a record start p the tag is at p+5,
    # pad3 at p+6..8, the count byte at p+9, and an F64 payload at p+10 (len 18).
    p = seg + len(_SPEEDSEG)
    if d[p:p + 5] == b"\x01\x00\x00\x00\x01":          # T20 sub-prelude (9B)
        p += 9
    count = None
    if d[p] == 1 and d[p + 2:p + 5] == b"\x00\x00\x00":  # PTOK count word
        count = d[p + 1]
        p += 5
    def num_rec(q):
        """(tag, f64|None, end) for a numeric keyed record at q, or None."""
        if d[q] != 0 or d[q + 6:q + 9] != b"\x00\x00\x00":
            return None
        key = struct.unpack_from("<I", d, q + 1)[0]
        if not (0 < key <= 0xFFFFF):
            return None
        tag = d[q + 5]
        if tag == 0x04:
            return tag, struct.unpack_from("<d", d, q + 10)[0], q + 18
        if tag in _FIXED_TAGS or tag in (0x01, 0x05):
            return tag, None, q + 10 + (4 if tag in (0x01,) else 1)
        return None

    f64s, reverse, got = [], False, 0
    while got < (16 if count is None else count):
        for _skip in range(4):                # tolerate inter-record pad zeros
            if num_rec(p) is not None or d[p] != 0:
                break
            p += 1
        r = num_rec(p)
        if r is not None:
            tag, val, end = r
            if tag == 0x04:
                f64s.append(val); p = end; got += 1; continue
            if tag in _FIXED_TAGS:
                reverse = True; p = end; got += 1; continue
            break
        n = d[p]                                        # spelled key: [n][ascii] + VALUE
        if 0 < n <= 40 and all(0x20 <= c < 0x7f for c in d[p + 1:p + 1 + n]):
            q = p + 1 + n                               # VALUE start (tag)
            if d[p + 1:p + 1 + n] == b"reverse":
                reverse = True; p = q + 6; got += 1; continue
            if d[q] == 0x04:
                f64s.append(struct.unpack_from("<d", d, q + 5)[0]); p = q + 13; got += 1; continue
            if d[q] in _FIXED_TAGS:
                reverse = True; p = q + 6; got += 1; continue
        break
    if len(f64s) < 2 or not f64s[0] or not f64s[1]:
        return None
    return f64s[0], f64s[1], sum(f64s[2:]), reverse   # anchorOffset = sum of sub-offsets


def _t20_seg_count(d, off):
    """Record count of the 14FCSpeedSegment T20 whose node starts at `off`:
    [class name][optional 9B sub-prelude][01][u8 count][pad3].  None if the
    count word isn't there (walker variants without the PTOK prelude)."""
    seg = d.find(_SPEEDSEG, off, off + 64)
    if seg < 0:
        return None
    p = seg + len(_SPEEDSEG)
    if d[p:p + 5] == b"\x01\x00\x00\x00\x01":
        p += 9
    if d[p] == 1 and d[p + 2:p + 5] == b"\x00\x00\x00":
        return d[p + 1]
    return None


def _subtree_hi(node):
    """Max byte offset in a node's subtree, memoized on the node (the tree is
    static after build_tree).  Iterative post-order so chained/nested sequences
    can't blow the recursion limit.  Replaces the per-clip full-subtree walks
    that dominated parse time on clip-heavy projects (a 4124-item project spent
    89 s re-walking speed wrappers)."""
    if node._hi is not None:
        return node._hi
    stack = [(node, False)]
    while stack:
        n, ready = stack.pop()
        if ready:
            h = n.off
            for c in n.children:
                if c._hi is not None and c._hi > h:
                    h = c._hi
            n._hi = h
        elif n._hi is None:
            stack.append((n, True))
            stack.extend((c, False) for c in n.children)
    return node._hi


def _seg_fields_from_tree(doc, sdw):
    """Read a 14FCSpeedSegment's fields from the attached T20 tree node — precise
    and drift-immune (no key ids needed).  The T20's keyed children are, in order:
    inputUsed (1st F64), outputDuration (2nd F64), anchorOffset (3rd F64, absent =
    0); a FIXED-typed child is the REVERSE flag.  Byte-verified against FCP's own
    graphdict on all EPK/managed retimes (endpoints exact, incl. the 3 reverse
    clips the byte-regex mis-read).  Returns (iu, od, ao, reverse) or None."""
    if sdw is None:
        return None
    t20 = next((n for n in sdw.walk()
                if n.kind == "T20" and n.name == "14FCSpeedSegment"), None)
    if t20 is None:
        return None
    # COUNT-BOUND: the segment's PTOK word says how many keyed records are ITS
    # OWN; keyed children past that belong to the enclosing speed data (start/
    # end F64s) and must not leak into the anchorOffset sum.
    count = _t20_seg_count(doc.d, t20.off)
    f64s, reverse, seen = [], False, 0
    for c in t20.children:
        if c.role != "key":
            continue
        if count is not None and seen >= count:
            break
        seen += 1
        if not c.children:
            continue
        v = c.children[0]
        if v.kind == "F64" and v.value is not None:
            f64s.append(float(v.value))
        elif v.kind == "FIXED":
            reverse = True
    if len(f64s) < 2 or not f64s[0] or not f64s[1]:
        return None
    # anchorOffset = SUM of the F64 fields after inputUsed & outputDuration:
    # some segments split it across two sub-offset fields (managed 0x113 stores
    # keys 1208 + 2331), and FCP's graphdict V0 is their total (byte-verified:
    # (0,20) 0.973+4.898 = 5.871).  EPK's single-field clips are unaffected (a
    # one-element sum == that field).
    return f64s[0], f64s[1], sum(f64s[2:]), reverse


def clip_speed(doc, el):
    """Recover a retime for a video clip -> {speed, ratio, anchorOffset, duration,
    input_used, reverse} or None.  FCP stores speed as a `14FCSpeedSegment` whose
    fields are `inputUsed`, `outputDuration`, `anchorOffset` and a reverse flag;
    speed = inputUsed/outputDuration (byte-proven: 5134/7888 = 65% == FCP's 65).

    Two readers: PRIMARY reads the fields from the segment's attached T20 tree node
    (positional by value-kind — inputUsed/outputDuration/anchorOffset are the F64
    children in order, a FIXED child = reverse), which is precise and drift-immune.
    FALLBACK is the drift-immune `14FCSpeedSegment` byte marker + a positional F64
    regex over the clip's byte extent, kept for clips whose segment the walker only
    partially attaches (no T20 node); it reads forward-only and can mis-read the
    anchorOffset on reverse clips, so the T20 reader is tried first.

    A variable-speed RAMP is a cluster of segments; we take the first (dominant)
    segment's constant ratio.  FCP's graphdict endpoints are then reproduced exactly
    (y(x) = anchorOffset + ratio*x forward, mirrored for reverse); the interior
    keyframes are FCP-spline-smoothed (~1-3 frames), which we approximate linearly."""
    sdw = doc.get(el, "speedDataWrapper")
    # FAST PATH: the marker string is the T20's own class name, so if the bytes
    # `14FCSpeedSegment` don't occur in the wrapper's span there is neither a
    # T20 node to read nor a segment to byte-parse — skip both subtree walks.
    # (Most clips have a wrapper but NO retime; this check is one C-level find
    # over a memoized extent instead of a Python walk per clip.)
    wseg = -1
    if sdw is not None:
        wseg = doc.d.find(_SPEEDSEG, sdw.off, _subtree_hi(sdw) + 600)
    fields = _seg_fields_from_tree(doc, sdw) if wseg >= 0 else None
    if fields is not None:
        iu, od, ao, reverse = fields
    else:
        # STRUCTURAL primary for the byte path: scan the wrapper's subtree (managed
        # 0x113 clips are bulky enough the speed data sits ~12.3 KB in, past the
        # extent cap below, which stays as the last-resort fallback).
        rstart = rend = None
        if wseg >= 0:
            rstart, rend = sdw.off, _subtree_hi(sdw) + 600
        if rstart is None:
            hi = el.off                        # extent of the clip's own subtree
            for n in el.walk():
                if n.off > hi:
                    hi = n.off
                if hi - el.off > 12000:        # cap: a media clip's speed data is ~1 KB
                    break                      #   in; don't scan a nested subsequence
            rstart, rend = el.off, hi + 300
        seg = doc.d.find(_SPEEDSEG, rstart, rend)
        if seg < 0:                            # no 14FCSpeedSegment -> no retime
            return None
        parsed = _seg_fields_from_bytes(doc.d, seg)
        if parsed is None:
            # last resort: the original lenient flat-window regex (forward-only;
            # grabs the first two F64s anywhere in the segment window).  Kept so a
            # clip whose segment records the sequential parser can't follow still
            # yields a retime rather than being dropped.
            win = doc.d[seg: seg + 512]
            f64s = [struct.unpack("<d", m.group(1))[0] for m in _SEG_F64.finditer(win)]
            if len(f64s) < 2 or not f64s[0] or not f64s[1]:
                return None
            iu, od, ao, reverse = f64s[0], f64s[1], (f64s[2] if len(f64s) > 2 else 0.0), False
        else:
            iu, od, ao, reverse = parsed
    ratio = iu / od
    if not (0.01 < ratio < 100):               # sanity guard
        return None
    # FCP's graphdict slope is (iu-1)/(od-1), NOT iu/od: the segment maps od
    # output FRAMES onto iu source frames inclusive of both endpoints (byte-
    # verified on all 556 EPK/managed retime graphdicts — interior keyframe
    # error drops from ~7.7fr to <0.01fr).  <speed> = floor(100*slope).
    s = (iu - 1.0) / (od - 1.0) if od > 1 else ratio
    dur = doc.get(el, "duration")              # clip duration -> graphdict's last x-point
    return {"speed": _math.floor(100 * s + 1e-9), "ratio": ratio, "slope": s,
            "anchorOffset": ao if _math.isfinite(ao) else 0.0, "reverse": reverse,
            "duration": int(dur.value) if dur is not None else None,
            "input_used": iu,                  # real source-media length, fractional
                                               # (the clip's out-point overshoots it
                                               # when slowed)
            "output_duration": od}


def clip_reverse_remap(doc, el):
    """v0x13 (2006 PPC) reverse Time Remap -> a clip_speed-shaped retime dict,
    or None.  This dialect has no `14FCSpeedSegment`: the remap lives in the
    clip's Time Remap filter dict as a `keyframe` graph object plus a
    clip-level `reverse` BOOL (the dict's own reverse/speed param boxes hold
    stale defaults — Marker 34's box reads FALSE while FCP exports TRUE).

    Fires ONLY on the full byte-identity of a constant-100% reversed clip:
    exactly 4 speedKF*-flagged keyframes whose (when, value) pairs equal
    {(0, dur), (in, dur-in), (out, dur-out), (dur, 0)} with 0 < in < out < dur
    (Aaron oracle: 3/3 reverse clips match; the forward no-op graphs —
    Marker 57's identity, Walking #5's stale curve — and every other corpus
    fail the identity, so the rule is correct-or-absent by construction).
    The clip-level `reverse` lookup alone is NOT trusted: its drift-voted id
    collides with an unrelated BOOL on audio clips; it is only the cheap
    prefilter before the subtree walk.

    FCP's own export writes these clips' in/out/duration one frame LOWER than
    stored and the graphdict in the shifted coordinates (MASTER.xml: stored
    681/768/1271 exports 680/767/1270, graph (0,1271)(680,590)(767,503)
    (1270,1)); the returned dict carries the shifted duration and the caller
    shifts in/out, after which emit's reverse formulas reproduce FCP's graph
    byte-exactly (v_start = D+1, y(x) = D - x, v_end = 1, trail = y(in)-1)."""
    rv = doc.get(el, "reverse")
    if rv is None or rv.kind != "BOOL" or not rv.value:
        return None
    iv, ov, du = doc.get(el, "in"), doc.get(el, "out"), doc.get(el, "duration")
    try:
        inn, out, dur = int(iv.value), int(ov.value), int(du.value)
    except (AttributeError, TypeError):
        return None
    if not (0 < inn < out < dur):
        return None
    pairs = []
    for n in el.walk():
        if n.kind != "OBJINL1":
            continue
        w = doc.get(n, "when")
        if w is None or w.kind != "F64" or w.value is None:
            continue
        flags = sum(1 for c in n.children if c.role == "key" and c.children
                    and c.children[0].kind == "FIXED")
        if flags < 2:              # speedKFStart/In/Out/End + speedVirtualKF
            continue               # (volume/pan/motion keyframes carry <2)
        vals = [_f32_leaf(doc, c.children[0]) for c in n.children
                if c.role == "key" and c.children
                and c.children[0].kind == "F32"]
        vals = [v for v in vals if v is not None]
        if not vals:
            return None            # flagged speed keyframe, unreadable value
        pairs.append((float(w.value), vals[0]))
        if len(pairs) > 4:
            return None
    if sorted(pairs) != [(0.0, float(dur)), (float(inn), float(dur - inn)),
                         (float(out), float(dur - out)), (float(dur), 0.0)]:
        return None
    d1 = dur - 1
    return {"speed": 100, "ratio": 1.0, "slope": 1.0, "anchorOffset": 0.0,
            "reverse": True, "duration": d1, "input_used": float(d1),
            "output_duration": float(d1), "media_duration": None}


def clip_link_members(doc, el):
    """Decode a clip's `link` sync-group array
    -> [(mediatype, trackindex, clipindex, groupindex)].

    Exactly ONE member per group carries the array (the video clip for V+A
    groups; one audio channel for audio-only stereo pairs), as the value of the
    `link` key: a STRUCT1E (tag 0x1e) array of 8-byte entries
    [u8 mediatype][u8 stereo-flag][u16le trackindex][u16le clipindex][u16le pad],
    mediatype 1=video / 2=audio.  The stereo flag maps 1:1 to FCP's
    <groupindex>1</groupindex> on that member's <link> blocks (byte-verified:
    EPK's 116 flag=1 audio entries == the oracle's 232 gi=1 links across both
    holders; the flag also fires on speedchange's synced V+A group's audio
    members).  clipindex is the 1-based ordinal over ALL track items.  The
    non-carrier members have a `link` key with no STRUCT1E (returns []).
    Byte example (EPK '01 Deceptacon.aif' audio carrier @0x2cc309):
    entries (2,gi1,t3,c5),(2,gi1,t4,c5)."""
    lk = doc.get(el, "link")
    if lk is None:
        return []
    d = doc.d
    m = d.find(b"\x1e\x00\x00\x00", lk.off, lk.off + 48)
    if m < 0:
        return []
    cnt = struct.unpack_from("<I", d, m + 4)[0]
    if not (1 <= cnt <= 64) or m + 8 + 8 * cnt > len(d):
        return []
    out = []
    for i in range(cnt):
        mtf, ti, ci, pad = struct.unpack_from("<HHHH", d, m + 8 + 8 * i)
        mt, gi = mtf & 0xFF, mtf >> 8
        if mt not in (1, 2) or gi not in (0, 1) or pad != 0:
            return []
        out.append((mt, ti, ci, gi))
    return out


def _has_timeline(doc, nd):
    """True if a seq-shaped node arranges MORE THAN ONE clip on some single track —
    the signature of a real (possibly nested) sequence, as opposed to a single-clip
    subclip/master representation (one clip per track).  Used to keep a nested
    sequence that has NO separate top-level node (e.g. EPK's Cut 2-6 / Day sequences,
    stored chained inside one another) while still dropping embedded single-clip
    subclip copies (palastin's 19 buried subclips are 1 clip each)."""
    med = doc.get(nd, "media")
    if med is None:
        return False
    for mk in ("vidm", "audm"):
        m = doc.get(med, mk)
        trk = doc.get(m, "track") if m is not None else None
        if trk is None:
            continue
        for te in trk.elements():
            cl = doc.get(te, "clip")
            if cl is None:
                continue
            n = 0
            for el in cl.elements():
                if doc.get(el, "effect") is None:
                    n += 1
                    if n > 1:
                        return True
    return False


_MEDIA_SUFFIXES = (".mov", ".avi", ".mp4", ".m4v", ".mts", ".mp3", ".wav",
                   ".aif", ".aiff", ".psd", ".png", ".jpg", ".jpeg", ".tif",
                   ".tiff", ".tga")


def _clip_total(doc, nd):
    """Total clip elements across all of a seq-shaped node's tracks."""
    n = 0
    med = doc.get(nd, "media")
    if med is None:
        return 0
    for mk in ("vidm", "audm"):
        m = doc.get(med, mk)
        trk = doc.get(m, "track") if m is not None else None
        if trk is None:
            continue
        for te in trk.elements():
            cl = doc.get(te, "clip")
            if cl is not None:
                n += sum(1 for el in cl.elements()
                         if doc.get(el, "effect") is None)
    return n


def _census_junk(doc, nd, ss, ms):
    """Provably-not-a-browser-sequence nodes that still pass the flavor vote
    (byte evidence: the RESP 532-537 / muraishi census dumps, 2026-07-12):

      - 'PTVTmpFile': FCP's reserved Print-to-Video scratch-sequence name.
        Printing serializes it (plus a fresh copy of the printed sequence)
        into the document but never into the browser (RESP 533 census is
        oracle-exact once it is dropped; RESP 532-537 carry 1-7 each).
      - master-clip wrappers named after their media file: either the FULL
        master-metadata tie (ss == ms == 5: RESP 537's 'Respuestas N.aif')
        or no real timeline (muraishi's 'forestAmbience.aif', one clip on
        one track).  A sequence copy whose NAME merely drifted onto a media
        filename (RESP 536's '1 CONTINUAMOS.mov': ss=5, ms=0, real
        timeline) survives both arms on purpose.
      - empty unnamed: no name, no flavor keys, zero clips — the FCP 5.1
        muraishi phantom (that dialect carries no SEQ_FLAVOR keys at all,
        so the empty node was the only "sequence" the census surfaced).
      - nested INSIDE a PTVTmpFile render: Print-to-Video serializes a fresh
        copy of the printed sequence as a child of the scratch PTVTmpFile
        sequence; that copy is not a browser item (RESP 535/537 each carry a
        few, usually name-unresolved).  No gated corpus contains a PTVTmpFile
        at all, so this cannot touch palastin/EPK/managed/Aaron.
    """
    nm = doc.resolve_str(doc.get(nd, "name"))
    if nm == "PTVTmpFile":
        return True
    anc = nd.parent
    while anc is not None:
        if _is_seq_shaped(doc, anc) and \
                doc.resolve_str(doc.get(anc, "name")) == "PTVTmpFile":
            return True                  # Print-to-Video internal copy
        anc = anc.parent
    if nm is None:
        return ss == 0 and ms == 0 and _clip_total(doc, nd) == 0
    if nm.lower().endswith(_MEDIA_SUFFIXES):
        if _is_layered_psd_seq(doc, nd):
            return False                 # a layered-PSD browser sequence wears
            #                              a .psd (media-suffix) name and a full
            #                              master-metadata flavor tie, but IS a
            #                              browser item — keep it (anika's
            #                              '50pf1950_frei.psd', ss==ms==5).
        if ss == ms == len(SEQ_FLAVOR):
            return True
        if not _has_timeline(doc, nd) and _clip_total(doc, nd) > 0:
            return True
    return False


def _flavor(doc, nd):
    ss = sum(1 for k in SEQ_FLAVOR if doc.get(nd, k) is not None)
    ms = sum(1 for k in MAS_FLAVOR if doc.get(nd, k) is not None)
    return ss, ms


def _is_buried(doc, nd):
    anc = nd.parent
    while anc is not None:
        if _is_seq_shaped(doc, anc):
            return True                  # embedded subsequence copy
        anc = anc.parent
    return False


def _is_layered_psd_seq(doc, nd):
    """FCP represents a layered Photoshop (.psd) browser file as a SEQUENCE:
    one video track per Photoshop layer (audm empty), stored buried and
    isMaster-flagged exactly like a master clip.  _census_rescue's isMaster
    guard and the capture-field master guard would both drop it, so it is
    admitted here as its own keep-class.  anika's FCP-oracle instance is
    '50pf1950_frei.psd' (1 layer track, layer-clip with 0 sub-elements = 1/0/0).

    A plain PSD MASTER CLIP (RESP 535's 'Pantalla AMG.psd') wears the same .psd
    name + vidm track + isMaster flag, so the discriminator is the FULL
    sequence-settings flavor: a PSD imported as a sequence carries all of
    seqProps/tcData/selectionIn/selectionOut/reels (ss == len(SEQ_FLAVOR)),
    while a PSD master clip carries NONE (ss == 0).  Require that tie so the
    master clip stays dropped."""
    nm = doc.resolve_str(doc.get(nd, "name"))
    if nm is None or not nm.lower().endswith(".psd"):
        return False
    # Full sequence-settings flavor, tolerating ONE drift-dropped key: a PSD
    # imported as a sequence carries all of SEQ_FLAVOR, but the (correct)
    # phantom-free anika id space can leave a single member -- seqProps, whose
    # NKEY reference sits just past a 2-alloc local E step its DEF's tid bracket
    # under-samples -- one outside the drift bracket, so the node reads 4/5.  A
    # PSD MASTER CLIP carries NONE (RESP 535's 'Pantalla AMG.psd', ss == 0), so
    # a >= len-1 majority keeps the margin wide.
    if sum(1 for k in SEQ_FLAVOR if doc.get(nd, k) is not None) < len(SEQ_FLAVOR) - 1:
        return False
    # A layered-PSD SEQUENCE is only its layer tracks -- no timeline clips.  A
    # PSD master clip that wears the same .psd name and (drifted) 4/5 flavor
    # (anika's 'RLP+txt_cmyk.psd', 3 layer clips) carries media clips; the
    # clip-count tie is the discriminator the relaxed flavor threshold would
    # otherwise blur.  50pf1950_frei.psd holds 0 (byte-verified, OLD and NEW).
    if _clip_total(doc, nd) != 0:
        return False
    med = doc.get(nd, "media")
    if med is None:
        return False
    vm = doc.get(med, "vidm")
    return vm is not None and doc.get(vm, "track") is not None


def _census_rescue(doc, nd, ss, ms):
    """A buried, timeline-less seq-shaped node is normally an embedded
    subclip/master copy — but on chained-storage dialects it is how REAL
    browser sequences are stored (most of muraishi CC 5.1's 78 FCP-oracle
    sequences; anika's decade sequences).  Rescue it only on the
    browser-item signature (all FCP-oracle-calibrated, 2026-07-13):
      - no strong sequence flavor either (ss<=1): a full-flavored buried
        timeline-less node is a subclip copy (palastin's 19, wedding's
        'Sequence 1 <tc>' — rescuing those breaks exact gated censuses);
      - renderQuality present (sequence-settings key; muraishi masters have
        none, and the empty-media lesson stubs keep it);
      - not flagged an FCP master (isMaster truthy = master clip; anika);
      - a NOUNDO undo-pocket only appears on real sequences when no master
        metadata came with it (anika masters carry NOUNDO + comments);
      - the name is spelled INLINE here (STRINL): duplicate serializations
        back-reference their name (anika's tape-reel subclip copies).
      - a buried, timeline-less node that carries an FCP capture field
        ('multiclipName' or 'digitize') AND actually holds media clips is a
        master clip, never a browser-sequence stub: anika's 0340LW/0520GW/VHS
        false positives (and the DVD_Bienwald masters) each wrap one media
        clip.  muraishi's chained sequence stubs carry the same capture fields
        on their dialect but serialize EMPTY (content lives elsewhere,
        _clip_total==0), so they still pass -- mirroring the _census_junk
        'timeline-less + has clips = not a sequence' test, keyed on the
        capture field instead of a media-suffix filename."""
    if _is_layered_psd_seq(doc, nd):
        return True                      # layered-PSD browser sequence — kept
    #                                      ahead of the capture-field master
    #                                      guard, which fires on masters WITH
    #                                      clips (RLP's 3 layer clips) too.
    if (doc.get(nd, "multiclipName") is not None
            or doc.get(nd, "digitize") is not None) \
            and _clip_total(doc, nd) > 0:
        return False
    if ss > 1 or doc.get(nd, "renderQuality") is None:
        return False
    im = doc.get(nd, "isMaster")
    if im is not None and im.value:
        return False
    if doc.get(nd, "NOUNDO") is not None and ms > 0:
        return False
    nref = doc.get(nd, "name")
    return nref is not None and nref.kind == "STRINL"


def _item_stubs(doc, seen):
    """Non-seq-shaped browser-sequence serializations, two dialect shapes:

    B (Living_prayer): the item wrapper holds only in/mainDict/out/NOUNDO and
      the real sequence object (name/media/vidm...) is the NOUNDO value; the
      wrapper never looks seq-shaped, so 4 of the 8 FCP-oracle sequences were
      invisible.  Yields the inner object; keep when it has a real timeline.
    S (muraishi CC 5.1): a browser sequence item whose media serialized EMPTY
      (content lives elsewhere); mainDict+media+name keys with sequence
      flavor but no vidm/audm tracks.  Keep when the flavor vote passes
      strictly (ss>ms) — subclip stubs read ss<=1, ms=4.
    """
    out = []
    has_noundo = "NOUNDO" in doc.ids
    for nd in doc.root.walk():
        if nd.count is None or not nd.children or id(nd) in seen:
            continue
        nu = doc.get(nd, "NOUNDO") if has_noundo else None
        if nu is not None and nu.children and id(nu) not in seen:
            med = doc.get(nu, "media")
            if med is not None and (doc.get(med, "vidm") is not None or
                                    doc.get(med, "audm") is not None):
                ss, ms = _flavor(doc, nu)
                if _has_timeline(doc, nu) or ss > ms:
                    out.append((nu, ss, ms))
                    seen.add(id(nu))
                continue
        if doc.get(nd, "renderQuality") is None:
            continue                     # cheap gate: stubs keep seq settings
        if doc.get(nd, "mainDict") is None or doc.get(nd, "media") is None \
                or doc.get(nd, "name") is None:
            continue
        ss, ms = _flavor(doc, nd)
        if ss > ms:
            out.append((nd, ss, ms))
            seen.add(id(nd))
    return out


def _find_sequences(doc):
    """All project sequences, document order."""
    hits = []
    seen = set()
    for nd in doc.root.walk():
        if not _is_seq_shaped(doc, nd):
            continue
        seen.add(id(nd))
        ss, ms = _flavor(doc, nd)
        buried = _is_buried(doc, nd)
        if ss < ms and not buried and not _has_timeline(doc, nd) \
                and not _is_layered_psd_seq(doc, nd):
            continue                     # master-clip wrapper (more master- than seq-
        #                                  flavored). EXCEPT a layered-PSD browser
        #                                  sequence, whose one drift-dropped SEQ_FLAVOR
        #                                  key (seqProps) can tip ss below ms while it
        #                                  is genuinely a sequence (clip_total==0; a PSD
        #                                  master clip carries clips and is excluded).
        #                                  flavored). ss==ms==0 = a fresh minimal project
        #                                  sequence (no seqProps/reels set yet) -> keep.
        #                                  A REAL multi-clip timeline overrides the
        #                                  master-metadata vote: anika's '01 Gute Sätze'
        #                                  (FCP-oracle sequence) carries all 5 master
        #                                  comment keys on a dialect that writes them
        #                                  onto sequence items too.  Buried timeline-
        #                                  less nodes skip the vote entirely — the
        #                                  rescue below is their (stricter) test, and
        #                                  this dialect fakes ms>0 on real sequences
        #                                  via drift-aliased comment keys (muraishi).
        hits.append((nd, buried, ss, ms))
    # Keep every top-level sequence, PLUS any "buried" node that is itself a real
    # timeline with no separate top-level instance: some projects (older FCP, EPK)
    # store their sequences chained inside one another, so all but the first are
    # flagged buried though each is a unique, exportable sequence.  Buried
    # timeline-less nodes get one more look (_census_rescue): chained-storage
    # dialects serialize real browser sequences that way.  Then add the
    # non-seq-shaped item stubs (_item_stubs) and drop the provable
    # non-sequences the inclusive vote sweeps in (_census_junk) — with the
    # sequence-head anchors mined FIRST, so the junk filter resolves names
    # in the same drift context as the display path (one RESP 537 PTVTmpFile
    # name is a back-ref that only resolves with anchors set).
    keeps = [(nd, ss, ms) for nd, b, ss, ms in hits
             if not b or _has_timeline(doc, nd)
             or _census_rescue(doc, nd, ss, ms)]
    keeps += _item_stubs(doc, seen)
    tops = sorted(keeps, key=lambda t: t[0].off)
    _seq_anchors(doc, [nd for nd, _, _ in tops])
    tops = [nd for nd, ss, ms in tops if not _census_junk(doc, nd, ss, ms)]
    return _census_dup_prune(doc, _registry_gate(doc, tops))


# ===========================================================================
# the CProjectItemTableEntry registry gate
# ===========================================================================
#
# FCP's own browser-item registry — the project object's `clipList`, a chained
# hash table of `22CProjectItemTableEntry` records — lists every CURRENT
# browser item exactly once.  Each entry's first u32 is the TRUE object-table
# id of the item's mainDict (byte-proven: all 9 EPK + all 22 palastin census
# keeps join their mainDict OBJREF value exactly; the second u32 is a chain
# pointer to another entry's id — 100% of them re-occur as first-u32 values).
# A census top whose serialization is NOT in the registry is a duplicate
# (undo/PTV-source) copy or a subclip stub, never a browser sequence.
#
# Inline mainDicts (RESP-style chained storage) only have a MODEL id, drifted
# from the registry's TRUE id by the walker's allocation error E.  Joining
# them one-by-one against a drift bracket is ambiguous (probe3, 2026-07-12) —
# instead ALL item-shaped serializations are aligned against the sorted
# registry ids at once: order-preserving maximum matching with slowly-varying
# E (drift grows smoothly; RESP 537 accumulates E~13k over 250 items with
# local wobble under ~50 + 1/3 slope).  FCP-oracle-calibrated 2026-07-13:
# zero false drops on all 11 reliable-registry corpora; the gate FAILS OPEN
# whenever the registry is absent (Aaron PPC), the site pool disagrees with
# the entry count (muraishi 5.1 stores per-lesson copies), the alignment is
# poor (anika's BE-twin ids), or the doc is too large to align.

_REG_CLS = b"22CProjectItemTableEntry"


def _registry_ids(d):
    """TRUE mainDict ids of every registered browser item (list, unsorted)."""
    out = []
    for m in _re.finditer(_re.escape(_REG_CLS), d):
        o = m.end()
        if d[o:o+5] == b"\x01\x00\x01\x00\x00" and d[o+9] == 0:
            out.append(struct.unpack_from("<I", d, o + 5)[0])
        elif d[o:o+6] == b"\x00\x01\x00\x01\x00\x00":
            # big-endian-origin twin: keyg_swab raw-copies the registry
            # pocket, leaving its u32s in BE byte order (and the classname
            # keeps its NUL terminator)
            out.append(struct.unpack_from(">I", d, o + 6)[0])
    return out


def _registry_sites(doc):
    """Every browser-item-shaped serialization, in mainDict-position order:
    (model_id | None, exact_true_id | None, node).  The item signature is
    mainDict + name + (media | children) — timeline clip elements carry
    mainDicts too but no media/children of their own."""
    out = []
    for nd in doc.root.walk():
        if nd.count is None or not nd.children:
            continue
        md = doc.get(nd, "mainDict")
        if md is None or doc.get(nd, "name") is None:
            continue
        if doc.get(nd, "media") is None and doc.get(nd, "children") is None:
            continue
        if md.kind.startswith("OBJREF"):
            out.append((md.off, None, md.value, nd))
        elif md.kind.startswith("OBJINL"):
            m = doc.id_at_pos.get(md.off)
            if m is not None:
                out.append((md.off, m, None, nd))
    out.sort(key=lambda t: t[0])
    return [(m, exact, nd) for _, m, exact, nd in out]


def _registry_align(sites, reg_ids, e_min=-2, e_max=65536,
                    wobble=48, slope_div=3):
    """Order-preserving max matching sites -> registry ids, slowly-varying E.

    Chain table B[j] = best chain whose last match uses registry slot j:
    (count, -cost, E_last, m_last, backptr).  Each site extends the best
    B[j'] (j' < j) whose |E - E'| fits wobble + (m - m')//slope_div; exact
    (OBJREF) sites match only their own id and chain freely.  Maximize count,
    tie-break minimal total |dE|.  Returns {site_idx: slot_idx}."""
    R = sorted(reg_ids)
    k = len(R)
    B = {}
    for i, (m, exact, nd) in enumerate(sites):
        if exact is not None:
            j0 = bisect.bisect_left(R, exact)
            js = [j0] if j0 < k and R[j0] == exact else []
        else:
            js = range(bisect.bisect_left(R, m + e_min),
                       bisect.bisect_right(R, m + e_max))
        updates = {}
        for j in js:
            E = None if exact is not None else R[j] - m
            best = (1, 0, E, m, (i, j, None))
            for jp, (cnt, nc, Ep, mp, node) in B.items():
                if jp >= j:
                    continue
                if E is not None and Ep is not None and mp is not None:
                    if abs(E - Ep) > wobble + max(0, m - mp) // slope_div:
                        continue
                cost = nc - (abs(E - Ep)
                             if E is not None and Ep is not None else 0)
                if (cnt + 1, cost) > (best[0], best[1]):
                    best = (cnt + 1, cost, E, m if m is not None else mp,
                            (i, j, node))
            prev = updates.get(j)
            if prev is None or (best[0], best[1]) > (prev[0], prev[1]):
                updates[j] = best
        for j, v in updates.items():
            old = B.get(j)
            if old is None or (v[0], v[1]) > (old[0], old[1]):
                B[j] = v
    if not B:
        return {}
    endj = max(B, key=lambda j: (B[j][0], B[j][1]))
    matched = {}
    node = B[endj][4]
    while node is not None:
        i, j, node = node
        matched[i] = j
    return matched


_REG_MAX_SITES = 2000       # DP is O(sites^2)-ish; the >50MB projects fail open


def _registry_gate(doc, tops):
    """Drop census tops whose serialization is not a registered browser item.
    Fails open (returns tops unchanged) unless every reliability test passes."""
    reg = _registry_ids(doc.d)
    if not reg or len(reg) > _REG_MAX_SITES:
        return tops                      # absent, or too large to align —
    #                                      skip BEFORE the site walk (the
    #                                      50MB+ projects carry 2-3k entries)
    sites = _registry_sites(doc)
    if not sites or len(sites) > _REG_MAX_SITES \
            or len(sites) > 1.2 * len(reg):
        return tops                      # site pool disagrees with the table
    matched = _registry_align(sites, reg)
    if len(matched) < 0.9 * len(sites):
        return tops                      # alignment too poor to trust
    site_of = {id(nd): i for i, (_, _, nd) in enumerate(sites)}
    reg_a = set(reg)
    keep = []
    for nd in tops:
        i = site_of.get(id(nd))
        joined = i in matched if i is not None else False
        if not joined:
            # NOUNDO-wrapped item (Living_prayer): the WRAPPER carries the
            # registry identity as an exact OBJREF mainDict
            host = nd.parent
            while host is not None and host.count is None:
                host = host.parent
            if host is not None:
                md = doc.get(host, "mainDict")
                joined = (md is not None and md.kind.startswith("OBJREF")
                          and md.value in reg_a)
        nm = doc.resolve_str(doc.get(nd, "name"))
        if not joined and not (nm is None or _TC_SUFFIX.search(nm)):
            # CORROBORATION REQUIRED to drop: the alignment's max-count
            # matching cannot prefer a real item over an adjacent copy of
            # it — on RESP 534 the None dups STOLE four real sequences'
            # registry ids and the real (named, editor-XML-confirmed)
            # sequences came up unmatched.  A named top only falls when its
            # name is FCP's subclip auto-naming ('<source> <tc>': SALVAGNO's
            # 'ESTERNI 00:01:16:15'); unresolved-name tops are the RESP dup
            # class the gate exists for (535's no-site None).
            joined = True
        if joined:
            keep.append(nd)
        else:
            doc.fallbacks.append((nm, "registry",
                                  ["unregistered copy dropped"]))
    return keep


_TC_SUFFIX = _re.compile(r"\d{2}[:;]\d{2}[:;]\d{2}[:;]\d{2}\s*$")


def _census_sig(doc, nd):
    """Per-track clip-count vectors (video, audio) — a duplicate
    serialization repeats its source's vectors exactly."""
    med = doc.get(nd, "media")
    out = []
    for mk in ("vidm", "audm"):
        m = doc.get(med, mk) if med is not None else None
        trk = doc.get(m, "track") if m is not None else None
        v = []
        for te in (trk.elements() if trk is not None else []):
            cl = doc.get(te, "clip")
            v.append(sum(1 for el in cl.elements()
                         if doc.get(el, "effect") is None)
                     if cl is not None else 0)
        out.append(tuple(v))
    return tuple(out)


def _census_dup_prune(doc, tops):
    """Drop a name-unresolved top whose track vectors EXACTLY mirror a NAMED
    kept top's — a duplicate (undo/PTV-source) serialization of that item
    (byte evidence: RESP 537's None copies of LIT-537 and SPOT PROMO repeat
    their vectors field-for-field; FCP exports neither).  Trivial shapes are
    exempt (a real unnamed one-clip sequence could collide by chance): the
    mirror must span >=2 non-empty tracks or >=4 clips."""
    named = {}
    for nd in tops:
        if doc.resolve_str(doc.get(nd, "name")) is not None:
            named.setdefault(_census_sig(doc, nd), nd)
    keep = []
    for nd in tops:
        if doc.resolve_str(doc.get(nd, "name")) is None:
            s = _census_sig(doc, nd)
            nz = sum(1 for t in s for x in t if x)
            if s in named and (nz >= 2 or sum(x for t in s for x in t) >= 4):
                doc.fallbacks.append((None, "dup-shape",
                                      ["unnamed mirror of a named sequence"]))
                continue
        keep.append(nd)
    return keep


def _embedded_names(doc, tops):
    """Structural nested-item name map: every BURIED sequence-shaped object
    (embedded subsequence/subclip copy) names the clip element it hangs
    under, and its link-ref value names reuse sites."""
    by_element = {}
    by_ref = {}
    for nd in doc.root.walk():
        if not _is_seq_shaped(doc, nd):
            continue
        anc = nd.parent
        el = None
        while anc is not None:
            if el is None and anc.role == "element":
                host = anc
                if doc.get(host, "subsequenceDict") is not None or \
                        doc.get(host, "itemDict") is not None:
                    el = host
            if _is_seq_shaped(doc, anc):
                break
            anc = anc.parent
        if el is None:
            continue
        nm = doc.resolve_str(doc.get(nd, "name"))
        if nm is None:
            continue
        by_element.setdefault(id(el), nm)
        for k in ("subsequenceDict", "itemDict"):
            v = doc.get(el, k)
            if v is not None and v.kind.startswith("OBJREF"):
                by_ref.setdefault((k, v.value), nm)
    for nd in tops:
        nm = doc.resolve_str(doc.get(nd, "name"))
        md = doc.get(nd, "mainDict")
        if nm is not None and md is not None and md.kind.startswith("OBJREF"):
            by_ref.setdefault(("subsequenceDict", md.value), nm)
            by_ref.setdefault(("itemDict", md.value), nm)
    return by_element, by_ref


def _seq_anchors(doc, tops):
    anchors = []
    for nd in tops:
        md = doc.get(nd, "mainDict")
        raw = doc.id_at_pos.get(nd.off)
        if md is not None and md.kind.startswith("OBJREF") and raw is not None:
            anchors.append((md.value, raw))
    anchors.sort()
    doc.anchors = anchors


def _file_name(doc, el):
    f = doc.get(el, "file")
    if f is None:
        return None
    return doc.resolve_str(doc.get(f, "name"))


def _master_names(doc):
    """UUID -> name over every sequence-shaped wrapper (the master pool).
    FCP's own xmeml substitutes the master name for empty clip names."""
    u2n = {}
    for nd in doc.root.walk():
        if not _is_seq_shaped(doc, nd):
            continue
        u = doc.get(nd, "UUID")
        nm = doc.resolve_str(doc.get(nd, "name"))
        if u is not None and u.value and nm:
            u2n.setdefault(u.value, nm)
    return u2n


def _master_name_of(doc, el, u2n):
    mc = doc.get(el, "masterClips")
    if mc is None:
        return None
    mu = doc.get(mc, "master")
    if mu is None or not mu.value:
        return None
    return u2n.get(mu.value)


def grouper(fcp_path, with_meta=False):
    """Group a .fcp project into sequences of ordered clipitems (see module
    docstring for the exact contract and validation numbers)."""
    doc = _Doc(fcp_path)
    tops = _find_sequences(doc)
    _seq_anchors(doc, tops)
    by_element, by_ref = _embedded_names(doc, tops)
    u2n = _master_names(doc)

    out = []
    for seq in tops:
        sname = doc.resolve_str(doc.get(seq, "name"))
        items = []
        for cl in _tracks_of(doc, seq):
            for el in cl.elements():
                if _elem_kind(doc, el) != "clip":
                    continue             # transition / generator item — MUST
                    #                      use the same predicate as the
                    #                      _enriched_sequences tree walk, or
                    #                      the flat-item/element zip shifts
                flags = []
                nm = doc.resolve_str(doc.get(el, "name"))
                linked = any(doc.get(el, k) is not None
                             for k in ("subsequenceDict", "itemDict"))
                if (nm is None or nm == "") and (linked or id(el) in by_element):
                    nm2 = by_element.get(id(el))
                    if nm2 is None:
                        for k in ("subsequenceDict", "itemDict"):
                            v = doc.get(el, k)
                            if v is not None and v.kind.startswith("OBJREF"):
                                nm2 = by_ref.get((k, v.value))
                                if nm2 is not None:
                                    break
                    nm = nm2 if nm2 is not None else nm
                if nm is None or nm == "":
                    # FCP substitutes the master/file name for empty names
                    nm2 = _master_name_of(doc, el, u2n) or _file_name(doc, el)
                    nm = nm2 if nm2 else nm
                items.append({
                    "name": nm,
                    "in": _f64_int(doc, el, "in", flags),
                    "out": _f64_int(doc, el, "out", flags),
                    "start": _f64_int(doc, el, "start", flags),
                    "end": _f64_int(doc, el, "end", flags),
                    "file": _file_name(doc, el),
                    "_el": el, "_linked": linked,
                })
                if flags:
                    doc.fallbacks.append((sname, len(items) - 1, flags))
        out.append({"name": sname, "items": items})

    # post-pass: unnamed subsequence uses inherit the name of the identical
    # use elsewhere (duplicated timelines share (in, out, duration)); adopted
    # only when the key maps to exactly ONE name (5/5 GT-exact, 0 ambiguous
    # on palastin)
    named_uses = {}
    for s in out:
        for it in s["items"]:
            if it["_linked"] and it["name"]:
                dv = doc.get(it["_el"], "duration")
                key = (it["in"], it["out"], dv.value if dv is not None else None)
                named_uses.setdefault(key, set()).add(it["name"])
    for s in out:
        for it in s["items"]:
            if it["_linked"] and not it["name"]:
                dv = doc.get(it["_el"], "duration")
                key = (it["in"], it["out"], dv.value if dv is not None else None)
                got = named_uses.get(key)
                if got and len(got) == 1:
                    it["name"] = next(iter(got))
                    doc.fallbacks.append((s["name"], "name-inherited", key))
    for s in out:
        for it in s["items"]:
            del it["_el"], it["_linked"]
    if with_meta:
        return out, doc
    return out


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        seqs = grouper(p)
        print(f"{p}: {len(seqs)} sequences")
        for s in seqs:
            print(f"  {s['name']!r}: {len(s['items'])} items")
            for it in s["items"][:4]:
                print(f"    {it}")
