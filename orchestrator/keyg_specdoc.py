"""keyg_specdoc: the grouper's document built from the spec-derived reader.

SpecDoc is a drop-in for keyg_grouper._Doc: the same Node tree conventions the
semantic layer (keyg_grouper from _find_sequences on, export.py) consumes, built
from orchestrator/specreader.py's parse through its builder hooks instead of the
pattern-cascade walker.  Reference-table ids are exact, so the inherited drift
machinery of _Doc is inert (anchor lists stay empty).

Conventions reproduced from the walker tree (see spec/coverage-gaps.md,
Appendix A, and keyg_grouper.build_tree):
  key node        kind DEF (spelled) / NKEY (back-reference), role "key", name = the key text,
                  one child: the value node
  value node      role "value" (keyed), "element" (array element) or "member" (object member,
                  info dictionary); `off` is the entry's type word for keyed values, the value's
                  first byte otherwise; kinds and payloads as the walker: INT (unsigned), F64,
                  F32 (payload read from the bytes), BOOL, FOURCC, STRINL / STRREF (text / slot id),
                  UUID / UUIDREF, DATA07 / DATA07REF, FIXED (value = type code), STRUCT1E (value =
                  entry flags), T16TIME, OBJINL / LEAF / OBJINL1 / OBJREF (dictionaries: count =
                  entry or element count), T20 / T20REF (objects: name = class key; children = the
                  first member dictionary's entries), T0C (file records: children = the info
                  dictionary's entries plus a FILESPEC glue node at the inline marker)
  notifier blocks the info dictionary entries of a notifier's messageable are lifted onto the
                  dictionary that owns the block (flags bit 32), after a MSG glue node — the
                  walker leaked them there, and the semantic layer finds e.g. `mainDict` that way
Types the walker misread (0x10, 0x18, 0x19, 0x1A-0x1D, 0x21, 0x22, 0x06, 0x15, 0x0A) get their own
kinds; no downstream code tests those kinds.
"""
from pathlib import Path

from . import specreader
from . import keyg_grouper as G

_FIXED = frozenset((0x02, 0x08, 0x0E, 0x0F, 0x11, 0x12))
_SCALAR_KIND = {0x01: "INT", 0x03: "F32", 0x04: "F64", 0x05: "BOOL", 0x0B: "FOURCC", 0x1E: "STRUCT1E",
                0x16: "T16TIME", 0x10: "PT3D", 0x18: "FCOLOR", 0x19: "FCOLOR", 0x1A: "ITEMSPEC1A",
                0x1B: "INT16", 0x1C: "INT16", 0x1D: "BEZIER", 0x21: "INT64", 0x22: "INT64"}
LIFTED = 32          # Node.flags bit: entry lifted from a notifier's info dictionary


def _is_ref(v):
    return isinstance(v, tuple) and len(v) == 3 and v[0] == 'ref'


def _text(b, enc='utf-8'):
    if isinstance(b, bytes):
        return b.decode(enc, 'replace')
    return b


class _Builder(specreader.NullBuilder):
    def __init__(self):
        self.root = None
        self.stack = []                 # [node, created_by, value_off]  created_by: value | dict | msg | obj
        self.table = {}                 # slot id -> (kind, payload)   (the walker's object table shape)
        self.ids = {}                   # key text -> slot id of its spelled (first) occurrence
        self.id_at_pos = {}             # value node offset -> slot id
        self.ref_sites = {}             # slot id -> [OBJREF nodes referencing it]
        self.array_ids = set()          # id(node) of array containers
        self.pending_key = None
        self.pending_toff = None
        self.pending_eflags = 0
        self.notifier_owner = []
        self.i = 0
        # dictionary-stream §4/§5: what a back-reference stands for.  slot_nodes maps a reference-table
        # slot to the node of the dictionary, object or file record that took it; styles records each
        # dictionary body's style by Node.i; file_ref_slots the slot a back-referenced file record names.
        self.slot_nodes = {}
        self.styles = {}
        self.file_ref_slots = {}

    # -- helpers --------------------------------------------------------------
    def _node(self, off, kind, role, name=None, value=None, count=None):
        self.i += 1
        return G.Node(self.i, off, kind, role, name, value, count)

    def _top(self):
        return self.stack[-1][0] if self.stack else None

    def _value_at(self, off):
        """The value node whose payload starts at `off`, if it is the innermost open node."""
        if self.stack and self.stack[-1][1] == 'value' and self.stack[-1][2] == off:
            return self.stack[-1][0]
        return None

    def _attach(self, node):
        if self.pending_key is not None:
            node.role = "value"
            self.pending_key.add(node)
            self.pending_key = None
        else:
            top = self._top()
            node.role = "element" if (top is not None and id(top) in self.array_ids) else "member"
            if top is not None:
                top.add(node)
        return node

    # -- reference table ---------------------------------------------------
    def slot(self, idx, typ, val, pos):
        if typ == 0x0B:
            name = _text(val)
            self.table[idx] = ("DEF", name)
            self.ids.setdefault(name, idx)
        elif typ in (0x1F, 0x0A):
            self.table[idx] = ("STRINL", _text(val))
        elif typ == 0:
            self.table[idx] = ("OBJINL", None)
        elif typ == 0x20:
            self.table[idx] = ("T20", val)
        elif typ == 0x23:
            self.table[idx] = ("UUID", _text(val, 'ascii'))
        elif typ == 0x15:
            self.table[idx] = ("GUID", val)
        elif typ == 6:
            self.table[idx] = ("MSG", str(val))
        elif typ == 7:
            self.table[idx] = ("DATA07", val)
        elif typ == 0x0C:
            self.table[idx] = ("T0C", None)
        else:
            self.table[idx] = ("SLOT", None)

    # -- keys and entries ------------------------------------------------------
    def key(self, off, name, slot, is_ref):
        kn = self._node(off, "NKEY" if is_ref else "DEF", "key", name=_text(name))
        top = self._top()
        if top is not None:
            if top.kind == "OBJINL" and not is_ref and top.flags & 64:   # dictFlags 1 + spelled first key = the walker's LEAF
                top.kind = "LEAF"
            top.flags &= ~64
            top.add(kn)
        self.pending_key = kn

    def entry(self, toff, typ, eflags):
        self.pending_toff = toff
        self.pending_eflags = eflags

    # -- values -----------------------------------------------------------------
    def value_begin(self, off, typ):
        if self.root is None:
            self.root = G.Node(-1, 0, "ROOT", "root")
            self.stack.append([self.root, 'value', off])
            return
        keyed = self.pending_key is not None
        node = self._node(self.pending_toff if keyed else off, _SCALAR_KIND.get(typ, "VAL"), "member")
        node.value = self.pending_eflags if keyed else 0
        self._attach(node)
        self.stack.append([node, 'value', off])

    def value_end(self, off, typ, v):
        node, how, _voff = self.stack.pop()
        assert how == 'value', (how, node)
        if node is self.root:
            return
        eflags = node.value
        ref = _is_ref(v)
        if not ref and not isinstance(v, dict):
            node.payload = v                            # the decoded value, byte-order independent
        if typ == 0x00:
            if ref:
                node.kind, node.value = "OBJREF", v[1]
                self.ref_sites.setdefault(v[1], []).append(node)
            else:
                node.value = None                       # kind set by dict_open
        elif typ == 0x01:
            node.kind, node.value = "INT", v & 0xFFFFFFFF
        elif typ in _FIXED:
            node.kind, node.value = "FIXED", typ
        elif typ == 0x03:
            node.kind, node.value = "F32", None
        elif typ in (0x04, 0x05):
            node.kind, node.value = _SCALAR_KIND[typ], v
        elif typ == 0x0B:
            node.kind, node.value = "FOURCC", _text(v, 'latin1')
        elif typ in (0x1F, 0x0A):
            if ref:
                node.kind, node.value = "STRREF", v[1]
            else:
                node.kind, node.value = "STRINL", _text(v)
        elif typ == 0x23:
            if ref:
                node.kind, node.value = "UUIDREF", v[1]
            else:
                node.kind, node.value = "UUID", (_text(v, 'ascii') if v is not None else "")
        elif typ == 0x07:
            if ref:
                node.kind, node.value = "DATA07REF", v[1]
            else:
                node.kind, node.value = "DATA07", len(v)
        elif typ == 0x1E:
            node.kind, node.value = "STRUCT1E", eflags
        elif typ == 0x16:
            node.kind, node.value = "T16TIME", v[0]
        elif typ == 0x0C:
            node.kind, node.name, node.value = "T0C", eflags, None   # object heads carry their payload in `name`
        elif typ == 0x20:
            if ref:
                node.kind, node.value = "T20REF", v[1]
            # inline: kind/name set by object_open
        elif typ == 0x06:
            if ref:
                node.kind, node.value = "MSGREF", v[1]
            # inline: set by messageable_close
        elif typ == 0x15:
            if ref:
                node.kind, node.value = "GUIDREF", v[1]
            else:
                node.kind, node.value = "GUID", v
        else:
            node.kind, node.value = _SCALAR_KIND.get(typ, "VAL"), v

    # -- dictionaries -----------------------------------------------------------
    def dict_open(self, off, style, flags, count, slot, elem_type):
        top = self._top()
        val = self._value_at(off)
        if val is self.root:
            node = self.root                             # the root dictionary is the ROOT node itself
            node.count = None
        elif val is not None:
            node = val                                   # the dictionary read as a typed value
            node.kind = "OBJINL" if node.role == "value" else "OBJINL1"
            node.count = count
        else:
            node = self._node(off, "OBJINL1", "member", count=count)   # info dictionary (messageable / file record)
            if top is not None:
                top.add(node)
            self.stack.append([node, 'dict', off])
        if style == 1:
            self.array_ids.add(id(node))
        elif style in (0, 4) and flags == 1 and node is not self.root:
            node.flags |= 64                             # LEAF candidate until the first key is seen
        self.id_at_pos[node.off] = slot
        self.slot_nodes[slot] = node
        self.styles[node.i] = style

    def dict_close(self, off):
        if self.stack and self.stack[-1][1] == 'dict':
            node = self.stack.pop()[0]
            node.flags &= ~64
        else:
            self._top().flags &= ~64

    # -- notifiers and messageables --------------------------------------------
    def notifiers_open(self, off, count):
        self.notifier_owner.append(self._top())

    def notifiers_close(self, off):
        self.notifier_owner.pop()

    def messageable_open(self, off):
        top = self._top()
        val = self._value_at(off)
        if val is not None:
            val.kind = "MSG"                             # a messageable VALUE (type 6)
            return
        node = self._node(off, "MSG", "glue")
        if top is not None:
            top.add(node)
        self.stack.append([node, 'msg', off])

    def messageable_close(self, off, guid, slot, has_info):
        if self.stack and self.stack[-1][1] == 'msg':
            node = self.stack.pop()[0]
            node.value = guid
            owner = self.notifier_owner[-1] if self.notifier_owner else None
            if owner is not None:
                # lift the info dictionary's entries onto the owning dictionary (walker behaviour)
                for info in list(node.children):
                    if info.role == "member" and info.count is not None:
                        for kn in list(info.children):
                            if kn.role == "key":
                                info.children.remove(kn)
                                kn.flags |= LIFTED
                                owner.add(kn)
        else:
            top = self._top()
            if top is not None and top.kind == "MSG":
                top.value = guid

    def messageable_ref(self, off, idx):
        if self._value_at(off) is None and self._top() is not None:
            self._top().add(self._node(off, "MSGREF", "glue", value=idx))

    # -- CFUUIDs as object members ----------------------------------------------
    def cfuuid(self, off, tid, text, slot):
        top = self._top()
        if top is not None and self._value_at(off) is None:
            top.add(self._node(off, "UUID", "member", value=_text(text, 'ascii')))

    def cfuuid_ref(self, off, idx):
        top = self._top()
        if top is not None and self._value_at(off) is None:
            top.add(self._node(off, "UUIDREF", "member", value=idx))

    # -- objects ----------------------------------------------------------------
    def object_open(self, off, cls, ver, slot):
        top = self._top()
        val = self._value_at(off)
        if val is not None:
            node = val
            node.kind, node.name, node.value = "T20", cls, None
        else:
            node = self._node(off, "T20", "member", name=cls)
            if top is not None:
                top.add(node)
            self.stack.append([node, 'obj', off])
        self.id_at_pos[node.off] = slot
        self.slot_nodes[slot] = node

    def _merged(self, node, ch):
        """`ch`'s entries now live on `node`: a back-reference to ch's slot finds them there."""
        s = self.id_at_pos.get(ch.off)
        if s is not None and self.slot_nodes.get(s) is ch:
            self.slot_nodes[s] = node
        if ch.i in self.styles:
            self.styles[node.i] = self.styles[ch.i]

    def object_close(self, off, members):
        node = self.stack.pop()[0] if (self.stack and self.stack[-1][1] == 'obj') else self._top()
        ch = node.children[0] if node.children else None
        if ch is not None and ch.role == "member" and ch.kind in ("OBJINL", "OBJINL1", "LEAF") and ch.count is not None:
            node.count = ch.count                       # the walker's T20 body = its FIRST member dictionary
            node.children.remove(ch)
            for kn in ch.children:
                kn.parent = node
            node.children = ch.children + node.children
            self._merged(node, ch)
        node.payload = members

    def object_ref(self, off, idx):
        top = self._top()
        if top is not None and self._value_at(off) is None:
            top.add(self._node(off, "T20REF", "member", value=idx))

    # -- file records -----------------------------------------------------------
    def file(self, off, marker_off, rec, slot):
        node = self._top()
        for ch in node.children:
            if ch.role == "member" and ch.count is not None:
                node.count = ch.count
                node.children.remove(ch)
                for kn in ch.children:
                    kn.parent = node
                node.children = ch.children + node.children
                self._merged(node, ch)
                break
        fs = self._node(marker_off, "FILESPEC", "glue", value=_text(rec.get('path', b'')))
        fs.payload = rec                                 # vol / drive / path_raw / elems / end (spec reader record)
        node.add(fs)
        self.id_at_pos[node.off] = slot
        self.slot_nodes[slot] = node

    def file_ref(self, off, idx):
        node = self._value_at(off)
        if node is not None:
            self.file_ref_slots[node.i] = idx            # dictionary-stream §6: inline marker 0 -> i32 ref


class SpecDoc(G._Doc):
    """keyg_grouper._Doc built from the spec reader.  `reader_error` is None on a complete parse."""

    def __init__(self, path, strict=True):
        raw = Path(path).read_bytes()
        self.d = raw + b"\x00" * 64
        b = _Builder()
        r = specreader.Reader(raw, builder=b)
        r.strict = strict
        self.reader_error = None
        self.stream_version = r.header()
        try:
            r.value(0x00)
            if r.pos != len(raw):
                self.reader_error = "trailing %d bytes" % (len(raw) - r.pos)
        except specreader.Err as e:
            self.reader_error = str(e)
        self.reader = r
        self.le = r.le
        self.root = b.root if b.root is not None else G.Node(-1, 0, "ROOT", "root")
        self.table = b.table
        self.ids = b.ids
        self.id_at_pos = b.id_at_pos
        self.ref_sites = b.ref_sites
        self.slot_nodes = b.slot_nodes
        self.styles = b.styles
        self.file_ref_slots = b.file_ref_slots
        self.exact_ids = True
        self._registry = None
        self.ref_anchors = []
        self.anchors = []
        self.fallbacks = []
        self._anch_cache = None
        self._def_kind_cache = None
        self._key_drift_cache = None
        self._configure()

    # -- back-references (dictionary-stream §0, §5, §6) --------------------------------------
    def deref(self, node):
        """The node a back-referenced value stands for: a back-reference is an index into the shared
        reference table and denotes the construct that took that slot, so OBJREF (dictionary), T20REF
        (object) and a back-referenced file record resolve to the node read inline earlier.  Any other
        node is returned unchanged; an unresolvable reference returns None."""
        if node is None:
            return None
        k = node.kind
        if k in ("OBJREF", "T20REF"):
            return self.slot_nodes.get(node.value)
        if k == "T0C":
            s = self.file_ref_slots.get(node.i)
            if s is not None:
                return self.slot_nodes.get(s)
        return node

    def style(self, node):
        """Dictionary body style (dictionary-stream §4: 0 hash, 1 array, 2 structure, 3 single,
        4 GUID hash) of a dictionary node, or None."""
        return self.styles.get(node.i) if node is not None else None

    def table_text(self, idx):
        """The text held by reference-table slot `idx` (a string or CFUUID slot), or None."""
        t = self.table.get(idx)
        return t[1] if t is not None and t[0] in ("STRINL", "UUID") else None

    # -- exact-id census helpers (used by keyg_grouper._is_buried) -------------------------
    def registry_ids(self):
        """The project's item registry from the tree: every item-table-entry object's first member
        is the item's dictionary, by reference (its slot id) or inline (the dictionary's own slot,
        which follows the entry's slot by one: spec §5).  Byte-order independent; a superset of the
        walker's byte scan, which saw only the reference form.  Empty without a registry."""
        if self._registry is None:
            ids = set()
            for n in self.root.walk():
                if n.kind != "T20" or n.name != "22CProjectItemTableEntry":
                    continue
                m = n.payload
                if isinstance(m, tuple) and len(m) == 4 and m[0] == 'obj':
                    m = m[3]                                # value-level object: ('obj', class, version, members)
                clip = m.get("clip") if isinstance(m, dict) else None
                if _is_ref(clip):
                    ids.add(clip[1])
                elif isinstance(clip, dict):
                    oslot = self.id_at_pos.get(n.off)
                    if oslot is not None:
                        ids.add(oslot + 1)
            self._registry = ids
        return self._registry

    def in_browser(self, nd):
        """True if nd is listed in the browser: reached from the root through `children` arrays
        only (bins), or referenced by slot from such an element (a nested sequence serialised
        inline where it is first used)."""
        a = nd
        while a is not None and a is not self.root:
            if a.role == "element":
                arr = a.parent
                if arr is None or arr.parent is None or arr.parent.role != "key" or arr.parent.name != "children":
                    break
                a = arr.parent.parent                    # the dictionary owning `children`: root or a bin
                if a is not self.root and G._is_seq_shaped(self, a):
                    break
            elif a.role == "value" and a.parent is not None and a.parent.role == "key":
                break                                    # a keyed value (a clip's sequenceDict ...)
            else:
                a = a.parent
        else:
            return a is self.root
        return self.referenced_from_children(nd)

    def referenced_from_children(self, nd):
        """True if a browser `children` element outside any sequence references nd's slot."""
        slot = self.id_at_pos.get(nd.off)
        if slot is None:
            return False
        for r in self.ref_sites.get(slot, ()):
            arr = r.parent
            if r.role != "element" or arr is None or arr.parent is None \
                    or arr.parent.role != "key" or arr.parent.name != "children":
                continue
            a = arr
            while a is not None:
                if G._is_seq_shaped(self, a):
                    break
                a = a.parent
            else:
                return True
        return False
