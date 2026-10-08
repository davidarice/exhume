"""xmeml_emit: a clean-room FCP 7 XML Interchange Format (xmeml version 5) emitter.

Written from spec/xmeml-export.md (the exporter) and spec/dictionary-stream.md (the project
dictionary), on the spec reader's document (keyg_specdoc.SpecDoc).  The exporter is a template
interpreter (spec §1.1, §2): rules select dictionary keys, scopes carry named slots, every
dictionary is walked in three passes (values, containers, elements), and an element's children
are written from its rule's child slots in rule order.  This module keeps that shape: the rule
catalogue of spec §5-§8 is written below as data tables (RULES), the engine (Translator) is
generic, and the "(code)" behaviours of the catalogue are small named functions (CODE).

Comments marked "oracle-observed, spec gap" record behaviour taken from FCP 7.0.3's own exports
(re-lab/traces/xml/*.ae.xml) where the spec is silent or only hypothesises; where the spec and those
exports disagree the spec is followed (a line break in text is written as &#13;, spec §4).

    python3 -m orchestrator.xmeml_emit project.fcp [-o out.xml]              # whole project
    python3 -m orchestrator.xmeml_emit project.fcp --item "Sequence 1"      # one item (name, index or UUID)
"""
import math
import os
import re
import struct
import sys

from . import keyg_grouper as G
from . import keyg_specdoc

# ---------------------------------------------------------------------------------------------
# §4 leaf formatting
# ---------------------------------------------------------------------------------------------

STRING, INTEGER, FLOAT, DOUBLE, BOOLEAN, POINT, FPOINT, RGBA = (
    "string", "integer", "float", "double", "boolean", "point", "fpoint", "rgba")

# value type codes (spec/value-types.md)
T_DICT, T_INT, T_UINT, T_F32, T_F64, T_BOOL = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05
T_MSG, T_BLOB, T_NULL = 0x06, 0x07, 0x08
T_CSTR, T_FILE, T_POINT, T_FPOINT, T_RGBA, T_GUID, T_TC = 0x0B, 0x0C, 0x0E, 0x0F, 0x12, 0x15, 0x16
T_ITEMSPEC, T_STR, T_OBJ, T_UUID = 0x1E, 0x1F, 0x20, 0x23


def fmt_g(x):
    """C printf %g: six significant digits, trailing zeros and point dropped, exponent form below
    1e-4 and from 1e6 up (spec §4).  Python's %g is the same conversion."""
    return "%g" % x


def fmt_whole(x):
    """Code-written whole numbers: rounded, no fraction (spec §4).  Rounding half away from zero
    (spec gap: the rounding direction of halves is not stated)."""
    x = float(x)
    if math.isnan(x) or math.isinf(x):
        return fmt_g(x)
    r = math.floor(abs(x) + 0.5)
    return str(int(-r if x < 0 else r))


def fmt_bool(b):
    return "TRUE" if b else "FALSE"


_XTYPE_OF = {STRING: (T_STR, T_CSTR), INTEGER: (T_INT,), FLOAT: (T_F32,), DOUBLE: (T_F64,), BOOLEAN: (T_BOOL,),
             POINT: (T_POINT,), FPOINT: (T_FPOINT,), RGBA: (T_RGBA,)}


def leaf_text(xtype, tc, value, vmap=None):
    """The text of a scalar leaf (spec §4): `value` is the stored value of type code `tc` (text,
    number, None for null).  A stored type other than the XML-side type converts when it is int32,
    float32 or float64 (to an integer by truncation, to a boolean as non-zero), boolean (1 or 0) or
    null (TRUE); any other stored type writes nothing (None).  A value map turns an integer into the
    word of its pair, an unmatched value writes nothing."""
    if vmap is not None:
        if tc not in (T_INT, T_F32, T_F64, T_BOOL) or value is None:
            return None
        return vmap.get(int(value))
    if tc in _XTYPE_OF.get(xtype, ()):
        if xtype == STRING:
            return value
        if xtype == INTEGER:
            return str(int(value))
        if xtype in (FLOAT, DOUBLE):
            return fmt_g(value)
        if xtype == BOOLEAN:
            return fmt_bool(value)
        return None
    if tc == T_NULL:
        n = 1
    elif tc == T_BOOL:
        n = 1 if value else 0
    elif tc in (T_INT, T_F32, T_F64) and value is not None:
        n = value
    else:
        return None
    if xtype == INTEGER:
        return str(int(n))
    if xtype in (FLOAT, DOUBLE):
        return fmt_g(n)
    if xtype == BOOLEAN:
        return fmt_bool(n != 0)
    return None


def leaf_element(name, xtype, tc, value, vmap=None):
    """A leaf element (spec §4): scalars through leaf_text; points as <horiz>/<vert> (integers or
    %g), RGBA colours as <alpha>, <red>, <green>, <blue> from the four stored bytes."""
    if vmap is None and xtype in (POINT, FPOINT):
        if tc not in (T_POINT, T_FPOINT) or not isinstance(value, tuple):
            return None
        f = (lambda a: str(int(a))) if xtype == POINT else fmt_g
        e = X(name)
        e.add(X("horiz", f(value[0])))
        e.add(X("vert", f(value[1])))
        return e
    if vmap is None and xtype == RGBA:
        if tc != T_RGBA or not isinstance(value, (bytes, bytearray)) or len(value) != 4:
            return None
        e = X(name)
        for nm, b in zip(("alpha", "red", "green", "blue"), value):
            e.add(X(nm, str(b)))
        return e
    t = leaf_text(xtype, tc, value, vmap)
    return X(name, t) if t is not None else None


_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def escape(s):
    """Leaf text and id escaping (spec §4, 7.0.3): `&`, `<`, `>` as entities, quotes unchanged;
    then a line feed or carriage return becomes `&#13;` and every other control character except
    tab one space."""
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace("\n", "&#13;").replace("\r", "&#13;")
    return _CTRL.sub(" ", s)


def to_text(b):
    """UTF-8 text of a stored string.  Invalid UTF-8 is re-decoded as Mac Roman, standing in for
    the application's best-effort decoder (spec §1.3; the decoder is not specified: spec gap)."""
    if isinstance(b, str):
        return b
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("mac_roman")


# ---------------------------------------------------------------------------------------------
# §3 identifiers
# ---------------------------------------------------------------------------------------------

def _trim_partial_utf8(b):
    """Drop an incomplete multi-byte UTF-8 sequence from the end of `b` (at most 3 bytes)."""
    for i in range(1, min(4, len(b) + 1)):
        c = b[-i]
        if c & 0xC0 == 0x80:                 # continuation byte: keep looking for its lead byte
            continue
        if c & 0x80 == 0:                    # ASCII: the tail is complete
            return b
        need = 2 if c & 0xE0 == 0xC0 else 3 if c & 0xF0 == 0xE0 else 4 if c & 0xF8 == 0xF0 else 1
        return b[:-i] if i < need else b
    return b


class IdTable:
    """One table for the whole export and all element kinds (spec §3).  `key` is the identity of
    the in-memory object (a dictionary or a file record); `base` its base string."""

    CUT = 118

    def __init__(self):
        self.ids = {}           # identity -> id text
        self.counts = {}        # normalised base (bytes) -> objects seen with it
        self.written = set()    # identities written in full

    @classmethod
    def normalise(cls, base):
        b = base.encode("utf-8") if isinstance(base, str) else bytes(base)
        if len(b) >= cls.CUT:
            # spec §3: cut to 118 bytes, always a space; a UTF-8 sequence the cut splits is dropped
            # (verified on Korean and Arabic names: FCP's id ends at the last whole character)
            return _trim_partial_utf8(b[:cls.CUT]) + b" "
        if b[-1:].isdigit():
            return b + b" "
        return b

    def get(self, key):
        return self.ids.get(key)

    def assign(self, key, base):
        """The object's id, assigned now if it has none: base, base1, base2, ... per normalised
        base, compared byte for byte."""
        got = self.ids.get(key)
        if got is not None:
            return got
        nb = self.normalise(base)
        n = self.counts.get(nb, 0)
        self.counts[nb] = n + 1
        ident = to_text(nb if n == 0 else nb + str(n).encode("ascii"))
        self.ids[key] = ident
        return ident


def file_id_base(fname):
    """A file record's id base: the file name without a final `.suffix` that contains a letter
    (spec §3; `.mov`, `.1tif` are removed, `.4` is kept).  oracle-observed, spec gap (the exact
    extension test is H): a suffix containing a space is no extension (`Ronald St. Pierre8`,
    `EXT. BAMBI REBECCA TRENT1-22` keep their whole names)."""
    i = fname.rfind(".")
    suffix = fname[i + 1:] if i > 0 else ""
    stem = fname[:i] if suffix and " " not in suffix and re.search(r"[A-Za-z]", suffix) else fname
    # oracle-observed, spec gap: a captured file's "-av" suffix is not part of the name the
    # application reports (Papa_Noel: file `xmem2-2-av`, id base `xmem2-2`); "-v"/"-a" are H
    if stem.endswith("-av") and len(stem) > 3:
        stem = stem[:-3]
    return stem


# ---------------------------------------------------------------------------------------------
# §7 pathurl
# ---------------------------------------------------------------------------------------------

_URL_SAFE = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~!$&'()*+,;=:@")


def url_escape(part):
    """Percent-escape one path element (spec §7 case b): every byte outside ASCII letters, digits
    and -._~!$&'()*+,;=:@ as %XX with capital hex digits."""
    b = part.encode("utf-8") if isinstance(part, str) else bytes(part)
    return "".join(chr(c) if c in _URL_SAFE else "%%%02X" % c for c in b)


def offline_pathurl(volume, elements):
    """`<pathurl>` of an offline record (spec §7 case b): file://localhost/ + volume and elements
    joined by `/`, a `/` inside an element written as `:`, each part percent-escaped.  None for a
    record with an empty volume name or no path elements."""
    if not volume or not elements:
        return None
    parts = [volume] + list(elements)
    return "file://localhost/" + "/".join(url_escape(bytes(p).replace(b"/", b":")) for p in parts)


def record_elements(rec):
    """The path elements of a file record (dictionary-stream §6): NUL-separated elements, or one
    NUL-terminated colon-separated string whose colons the loader turns into separators when
    their number is pathElements - 1."""
    raw = rec.get("path_raw", b"") or b""
    pe = rec.get("elems", (0, 0, 0))[2]
    s = raw.split(b"\x00")
    if len(s) > 1 and s[0].count(b":") == pe - 1 and pe > 1:
        return s[0].split(b":")                 # one NUL-terminated, colon-separated string
    if pe > 0 and len(s) >= pe:
        return s[:pe]                           # NUL-separated elements; what follows them is not path
    while s and s[-1] == b"":
        s.pop()
    return s


def private_encode(data):
    """Opaque binary as text (spec §4: "a private encoding (H: uuencode-like)").  oracle-observed,
    spec gap: uuencode lines of at most 45 bytes, each a length character chr(32 + n) and 4
    characters per 3 bytes (chr(32 + v), a zero written as a backquote), lines concatenated without
    separators.  The exporter pads a final partial group with whatever follows the value in memory;
    zeros stand in here (not reproducible)."""
    data = bytes(data)
    out = []
    for i in range(0, len(data), 45):
        line = data[i:i + 45]
        out.append(chr(32 + len(line)))
        d = line + b"\x00" * ((3 - len(line) % 3) % 3)
        for j in range(0, len(d), 3):
            a, b, c = d[j], d[j + 1], d[j + 2]
            for v in (a >> 2, ((a & 3) << 4) | (b >> 4), ((b & 15) << 2) | (c >> 6), c & 63):
                out.append("`" if v == 0 else chr(32 + v))
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# XML elements and the document text (§1.3)
# ---------------------------------------------------------------------------------------------

class X:
    """One XML element: a name, an optional id attribute, text or child elements.  `cdata` marks
    text written as a CDATA section, unescaped (spec §9 item 16: metadata values)."""
    __slots__ = ("name", "id", "text", "children", "cdata")

    def __init__(self, name, text=None, id=None, cdata=False):
        self.name = name
        self.id = id
        self.text = text
        self.children = []
        self.cdata = cdata

    def add(self, ch):
        self.children.append(ch)
        return ch

    def empty(self):
        return not self.children and not self.text

    def write(self, out):
        # spec §4 (H for a double quote inside an id): written as &quot; to keep the attribute well formed
        a = ' id="%s"' % escape(self.id).replace('"', "&quot;") if self.id is not None else ""
        if self.children:
            out.append("<%s%s>" % (self.name, a))
            for c in self.children:
                c.write(out)
            out.append("</%s>" % self.name)
        elif self.text and self.cdata:
            out.append("<%s%s><![CDATA[%s]]></%s>" % (self.name, a, self.text, self.name))
        elif self.text:
            out.append("<%s%s>%s</%s>" % (self.name, a, escape(self.text), self.name))
        else:
            out.append("<%s%s/>" % (self.name, a))

    def __repr__(self):
        return "<X %s%s %s>" % (self.name, " id=%r" % self.id if self.id else "",
                                repr(self.text) if self.text is not None else len(self.children))


HEAD = '<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE xmeml><xmeml version="%s">\n'


def document_string(tops, version=5):
    """The assembled document string (spec §1.3)."""
    out = [HEAD % fmt_g(version)]
    for t in tops:
        t.write(out)
    out.append("</xmeml>")
    return "".join(out)


def reflow(s):
    """The menu export's line re-flow (spec §1.3): cut after every `>` followed by `<`; each piece
    is one line of depth-counted tabs (at most 1023), the piece and a line feed."""
    pieces = s.replace("><", ">\x00<").split("\x00")
    out = []
    depth = 0
    prev_selfclose = False
    for p in pieces:
        if p.startswith("<?") or p.startswith("<!"):
            out.append(p + "\n")
            prev_selfclose = p.endswith("/>")
            continue
        if depth > 0:
            if p.startswith("</"):
                depth -= 1
            if prev_selfclose:
                depth -= 1
        out.append("\t" * min(max(depth, 0), 1023) + p + "\n")
        if "</" not in p:
            depth += 1
        prev_selfclose = p.endswith("/>")
    return "".join(out)


def document_bytes(tops, version=5):
    """UTF-8 bytes of the pretty-printed document, ending `</xmeml>` and three line feeds."""
    return (reflow(document_string(tops, version)) + "\n\n").encode("utf-8")


# ---------------------------------------------------------------------------------------------
# the project dictionary, as the exporter sees it (dictionary-stream §3-§7 over SpecDoc nodes)
# ---------------------------------------------------------------------------------------------

_KIND_TC = {"INT": T_INT, "F32": T_F32, "F64": T_F64, "BOOL": T_BOOL, "FOURCC": T_CSTR, "STRINL": T_STR,
            "STRREF": T_STR, "UUID": T_UUID, "UUIDREF": T_UUID, "DATA07": T_BLOB, "DATA07REF": T_BLOB,
            "T0C": T_FILE, "T20": T_OBJ, "T20REF": T_OBJ, "MSG": T_MSG, "MSGREF": T_MSG, "GUID": T_GUID,
            "GUIDREF": T_GUID, "T16TIME": T_TC, "PT3D": 0x10, "FCOLOR": 0x18, "ITEMSPEC1A": 0x1A,
            "INT16": 0x1B, "BEZIER": 0x1D, "STRUCT1E": T_ITEMSPEC, "INT64": 0x22, "OBJINL": T_DICT,
            "OBJINL1": T_DICT, "LEAF": T_DICT, "OBJREF": T_DICT, "ROOT": T_DICT}
HASH, ARRAY, STRUCT = 0, 1, 2              # dictionary body styles (dictionary-stream §4)


class Doc:
    """Typed access to a SpecDoc tree: type codes, back-references resolved to the shared object,
    entries in insertion (file) order without the notifier entries keyg_specdoc lifts for the walker."""

    def __init__(self, sd):
        self.sd = sd
        self.refs = sd.reader.refs

    def tc(self, n):
        if n is None:
            return None
        if n.kind == "FIXED":
            return n.value
        return _KIND_TC.get(n.kind)

    def deref(self, n):
        """The value a node stands for: back-referenced dictionaries, objects and file records resolve
        to the construct read first (dictionary-stream §0: one shared reference table)."""
        if n is None:
            return None
        k = n.kind
        if k in ("OBJREF", "T20REF") or k == "T0C":
            return self.sd.deref(n)
        return n

    def is_dict(self, n):
        return n is not None and (n.kind in ("OBJINL", "OBJINL1", "LEAF", "ROOT")
                                  or (n.kind in ("T20", "T0C") and n.i in self.sd.styles))

    def style(self, n):
        s = self.sd.styles.get(n.i)
        return HASH if s is None and n.kind == "ROOT" else s

    def entries(self, n):
        out = []
        for ch in n.children:
            if ch.role == "key" and not (ch.flags & keyg_specdoc.LIFTED) and ch.children:
                out.append((ch.name, ch.children[0]))
        return out

    def elements(self, n):
        return [ch for ch in n.children if ch.role == "element"]

    def get(self, n, key):
        """The (dereferenced) value of `key` in dictionary n, or None."""
        if n is None:
            return None
        for ch in n.children:
            if ch.role == "key" and ch.name == key and not (ch.flags & keyg_specdoc.LIFTED) and ch.children:
                return self.deref(ch.children[0])
        return None

    def path(self, n, *keys):
        for k in keys:
            n = self.get(n, k)
            if n is None:
                return None
        return n

    # -- scalar values ------------------------------------------------------------------------
    def raw_text(self, n):
        if n is None:
            return None
        if n.kind == "STRINL":
            return n.payload if isinstance(n.payload, (bytes, bytearray)) else (n.value or "").encode("utf-8")
        if n.kind == "STRREF":
            r = self.refs[n.value] if 0 <= n.value < len(self.refs) else None
            return r[1] if r is not None and isinstance(r[1], (bytes, bytearray)) else None
        if n.kind == "FOURCC":
            return n.payload if isinstance(n.payload, (bytes, bytearray)) else None
        return None

    def text(self, n):
        b = self.raw_text(n)
        return to_text(b) if b is not None else None

    def uuid(self, n):
        if n is None:
            return None
        if n.kind == "UUID":
            return n.value or None
        if n.kind == "UUIDREF":
            return self.sd.table_text(n.value)
        return None

    def num(self, n):
        """Numeric value of an int / float / double / bool / int16 / int64 / uint32 entry."""
        if n is None:
            return None
        tc = self.tc(n)
        if tc in (T_INT, T_F32, T_F64, T_BOOL, 0x1B, 0x1C, 0x21, 0x22):
            return n.payload
        if tc == T_UINT:
            return n.payload & 0xFFFFFFFF
        return None

    def name_of(self, d):
        return self.text(self.get(d, "name"))


# ---------------------------------------------------------------------------------------------
# rules (spec §2.1-§2.6) and the element catalogue (spec §5-§8) as data
# ---------------------------------------------------------------------------------------------

ELEM = "#elem"          # dictionary side "any array element"
IDX = "#idx"            # path wildcard: any array index
ANY = "#any"            # path wildcard: any key
TOP = "#top"            # path wildcard: the chain is empty (the document root)


class Rule:
    """One template rule (spec §2.1).  kind: 'E' element or 'C' container (value rules are the
    VALUE_KEYS set).  Dictionary side: key (a key name, ELEM for "any array element", or None for an
    element only ever built on the spot), path (innermost outwards, with the IDX/ANY/TOP wildcards),
    vtype ('dict', 'array' or None for any), conds ((key, value or tuple of values) pairs tested on the
    value's own dictionary).  XML side (elements): name, child slots in order, referenced (ids),
    link context, create if absent, local names, straight in (the elements its array produces go
    directly into its XML element), omitted when empty, forced child key, the slot it is filed under,
    and the media kind of a track item.  Containers: `up`, the slots handed to the parent ('*' all)."""
    __slots__ = ("id", "kind", "key", "path", "vtype", "conds", "name", "children", "ref", "linkctx",
                 "create", "local", "straight", "omit", "forced", "slot", "up", "media")

    def __init__(self, id, kind, key, path=(), vtype=None, conds=(), name=None, children=(), ref=False,
                 linkctx=False, create=False, local=(), straight=False, omit=False, forced=None,
                 slot=None, up=None, media=None):
        self.id, self.kind, self.key, self.path = id, kind, key, tuple(path)
        self.vtype, self.conds = vtype, tuple(conds)
        self.name, self.children, self.ref, self.linkctx, self.create = name, tuple(children), ref, linkctx, create
        self.local, self.straight, self.omit, self.forced = frozenset(local), straight, omit, forced
        self.slot = slot if slot is not None else (key if key not in (ELEM, None) else name)
        self.up = up
        self.media = media


# child slot constructors (spec §2.6 a-e)
def LIT(name, text):                    # a. literal text
    return ("lit", name, text)


def CODE(fn, *args):                    # b. a code behaviour
    return ("code", fn) + args


def VAL(key, name=None, xtype=STRING, vmap=None, default=None, cond=None):   # c. a value rule
    return ("val", key, name or key, xtype, vmap, default, cond)


def EL(rule_id, cond=None):             # d. an element rule
    return ("elem", rule_id, cond)


REQUIRED = "required"                   # cond marker of the required slots (spec §2.6)

# value maps (spec §4 and the code behaviours of §5)
FIELDDOM = {1: "none", 2: "upper", 3: "lower"}
SOURCETYPE = {1: "none", 2: "source", 4: "aux1", 8: "aux2"}
TRACKTYPE = {1: "none", 2: "source", 4: "aux1", 8: "aux2", 64: "sound"}
DISPLAYFORMAT = {0: "NDF", 1: "DF", 2: "frames"}
DOWNMIX = {1: "+10", 2: "+6", 3: "+3", 4: "0", 5: "-3", 6: "-6", 7: "-10", 8: "off"}
RENDERMODE = {0: "RGB", 1: "YUV8BPP", 2: "Float10BPP", 3: "Float"}
PIXELASPECT = {1: "Square", 2: "NTSC-601", 3: "PAL-601", 4: "HD-(960x720)", 5: "HD-(1280x1080)",
               6: "HD-(1440x1080)"}
ALPHATYPE = {0: "none", 1: "straight", 2: "black", 3: "white"}
# composite modes 1, 3, 10, 11 are spec H (§5.3); 13 is open
COMPOSITE = {0: "normal", 1: "add", 2: "subtract", 3: "difference", 4: "multiply", 5: "screen",
             6: "texturize", 7: "hardlight", 8: "softlight", 9: "darken", 10: "lighten", 11: "mask",
             12: "lumamask"}

# -- shared child-slot runs ------------------------------------------------------------------------
TIMING = [VAL("name", xtype=STRING), VAL("duration", xtype=DOUBLE), EL("rate"), EL("timecode"),
          VAL("in", xtype=DOUBLE), VAL("out", xtype=DOUBLE)]
# Local names (spec §5.6: an item's timing, logging, comment, marker, timecode and filter keys and
# most flags).  oracle-observed, spec gap: anamorphic, alphareverse, isMaster and still are inherited
# by every item (the items of a nested sequence take them from the nesting clip item: RESP 535,
# NoMansLand); labelComment is local to media clip items, generators and transitions but inherited
# by clips and nested-sequence items (a clip well's clip, SSTIKI); labelColor is local to all.
NEST_LOCAL = ("name", "duration", "in", "out", "start", "end", "subframeoffset", "sourceType",
              "inoffset", "outoffset", "stillFrameOffset", "stillGamma", "enable", "alphatype",
              "keytype", "sync", "fieldDom", "mediaDelay", "master", "subclipMaster",
              "marker", "filter", "timecode", "pAspectRatio", "volume", "pan", "rate",
              "effect", "clip", "angle", "layerIndex", "channelIndex", "mode",
              "label", "scene", "take", "lognote", "good", "labelColor",
              "comment1", "comment2", "comment3", "comment4", "comment5", "comment6")
ITEM_LOCAL = NEST_LOCAL + ("labelComment",)

# spec §5.2: a sequence's local names; oracle-observed, spec gap: labelColor too (a sequence in a
# labelled bin is not labelled, RESP 536)
SEQUENCE_LOCAL = ("uuid", "videoformat", "audioformat", "clip", "category", "labelComment", "outputs", "label",
                  "media", "track", "vidm", "audm", "marker", "link", "labelColor")

PARAM_LOCAL = ("specifier", "title", "min", "max", "keyframe", "value", "uiinfo", "uitype", "type", "default",
               "popupvalues")
PARAM_TAIL = [CODE("number", "min", "valuemin"), CODE("number", "max", "valuemax"), EL("keyframe"),
              EL("interpolation", cond="after_keyframe"), CODE("param_value")]

RULES = [
    # ---- §5.1 project, children, bin ---------------------------------------------------------------
    Rule("children", "E", "children", vtype="array", name="children", straight=True),
    Rule("bin", "E", ELEM, conds=(("subtype", 3),), name="bin",
         local=("name", "children", "labelColor", "labelComment", "comment1", "comment2", "comment3",
                "comment4", "comment5", "comment6", "label", "scene", "take", "lognote", "good"),
         children=[CODE("uuid"), VAL("name", cond=REQUIRED), EL("children"), EL("labels"), EL("comments")]),

    # ---- §5.2 sequence (top level / in a children array) -------------------------------------------
    Rule("sequence", "E", ELEM, conds=(("subtype", 20),), name="sequence", ref=True, linkctx=True,
         local=SEQUENCE_LOCAL,
         children=[CODE("uuid"), VAL("name", cond=REQUIRED), VAL("duration", xtype=DOUBLE, cond=REQUIRED),
                   EL("rate"), EL("timecode"), VAL("in", xtype=DOUBLE), VAL("out", xtype=DOUBLE),
                   EL("media"), CODE("file"), CODE("link"), CODE("masterclipid"),
                   VAL("isMaster", "ismasterclip", BOOLEAN), EL("marker"), VAL("label", "description"),
                   EL("labels"), EL("comments"), EL("logginginfo")]),

    # ---- §5.3 clip -----------------------------------------------------------------------------------
    Rule("clip", "E", ELEM, conds=(("subtype", (4, 5)),), name="clip", ref=True, linkctx=True,
         local=NEST_LOCAL + ("media", "vidm", "audm", "link", "videoformat", "audioformat", "outputs"),
         children=[CODE("uuid"), VAL("name", cond=REQUIRED), VAL("duration", xtype=DOUBLE, cond=REQUIRED),
                   EL("rate"), EL("timecode"), VAL("in", xtype=DOUBLE), VAL("out", xtype=DOUBLE),
                   EL("subclipinfo"), CODE("if_video", VAL("stillFrameOffset", "stillframeoffset", DOUBLE)),
                   CODE("if_video", VAL("still", "stillframe", BOOLEAN)), CODE("if_video", CODE("gamma")),
                   VAL("enable", "enabled", BOOLEAN), VAL("anamorphic", xtype=BOOLEAN),
                   VAL("alphatype", "alphatype", INTEGER, ALPHATYPE), VAL("alphareverse", xtype=BOOLEAN),
                   VAL("keytype", "compositemode", INTEGER, COMPOSITE), CODE("masterclipid"),
                   VAL("isMaster", "ismasterclip", BOOLEAN), EL("logginginfo"), EL("labels"), EL("comments"),
                   EL("media"), CODE("file"), EL("marker"), EL("filter"), CODE("link"),
                   VAL("angle", "defaultangle", STRING)]),

    # ---- §5.4 media, video, audio ----------------------------------------------------------------------
    Rule("media", "E", "media", vtype="dict", name="media", local=("vidm", "audm"),
         children=[EL("vidm"), EL("audm")]),
    Rule("vidm", "E", "vidm", path=("media",), vtype="dict", name="video", local=("track", "filter"),
         children=[EL("videoformat"), EL("track")]),
    Rule("audm", "E", "audm", path=("media",), vtype="dict", name="audio",
         local=("track", "in", "out", "masterLevel", "filter"),
         children=[EL("audioformat"), EL("outputs"), VAL("in", xtype=DOUBLE), VAL("out", xtype=DOUBLE),
                   EL("track"), CODE("master_level")]),
    Rule("videoformat", "E", None, name="format", slot="videoformat", omit=True, children=[
        EL("vsamplechar"),
        EL("fcpappdata")]),
    Rule("vsamplechar", "E", None, name="samplecharacteristics", create=True, omit=True, children=[
        VAL("width", xtype=INTEGER), VAL("height", xtype=INTEGER), VAL("anamorphic", xtype=BOOLEAN),
        VAL("pAspectRatio", "pixelaspectratio", INTEGER, PIXELASPECT),
        VAL("fieldDom", "fielddominance", INTEGER, FIELDDOM), EL("rate"), VAL("depth", "colordepth", INTEGER),
        EL("codec")]),
    Rule("fcpappdata", "E", None, name="appspecificdata", create=True, children=[
        LIT("appname", "Final Cut Pro"), LIT("appmanufacturer", "Apple Inc."), LIT("appversion", "7.0"),
        EL("fcpdata")]),
    Rule("fcpdata", "E", None, name="data", create=True, children=[EL("fcpimageprocessing")]),
    Rule("fcpimageprocessing", "E", None, name="fcpimageprocessing", create=True, children=[
        VAL("doYUV", "useyuv", BOOLEAN), VAL("doSuperWhite", "usesuperwhite", BOOLEAN),
        VAL("renderColorMode", "rendermode", INTEGER, RENDERMODE)]),
    Rule("audioformat", "E", None, name="format", slot="audioformat", omit=True, children=[EL("asamplechar")]),
    Rule("asamplechar", "E", None, name="samplecharacteristics", create=True, omit=True, children=[
        VAL("audioDepth", "depth", INTEGER), VAL("sampleRate", "samplerate", INTEGER)]),
    Rule("codec", "E", "codec", path=("final",), vtype="dict", name="codec",
         local=("name", "typeName", "cType", "vendor"),
         children=[VAL("name"), EL("qtappdata")]),
    Rule("qtappdata", "E", None, name="appspecificdata", create=True, children=[
        LIT("appname", "Final Cut Pro"), LIT("appmanufacturer", "Apple Inc."), LIT("appversion", "7.0"),
        EL("qtdata")]),
    Rule("qtdata", "E", None, name="data", create=True, children=[EL("qtcodec")]),
    Rule("qtcodec", "E", None, name="qtcodec", create=True, children=[
        VAL("name", "codecname"), VAL("typeName", "codectypename"), CODE("fourcc", "cType", "codectypecode"),
        CODE("fourcc", "vendor", "codecvendorcode"), VAL("spatialQuality", "spatialquality", INTEGER),
        VAL("temporalQuality", "temporalquality", INTEGER), VAL("keyFrameRate", "keyframerate", INTEGER),
        VAL("dataRate", "datarate", INTEGER)]),
    Rule("outputs", "E", "outputs", path=("audioGroup",), vtype="array", name="outputs", omit=True,
         children=[CODE("outputs")]),

    # ---- §5.5 track ------------------------------------------------------------------------------------
    # oracle-observed, spec gap: a track without `lock` inherits the enclosing track's (the tracks of a
    # nested sequence in a locked track are locked, SALVAGNO), so `enable`/`lock` are not local
    Rule("track", "E", ELEM, path=("track",), vtype="dict", name="track",
         children=[VAL("enable", "enabled", BOOLEAN, default="TRUE"), VAL("lock", "locked", BOOLEAN, default="FALSE"),
                   VAL("outputIndex", "outputchannelindex", INTEGER)]),

    # ---- §5.6 clipitem (media), video and audio -------------------------------------------------------
    Rule("clipitem_v", "E", ELEM, path=("clip", IDX, "track", "vidm"), conds=(("type", 1),), name="clipitem",
         ref=True, local=ITEM_LOCAL + ("link",), media="video",
         children=TIMING + [VAL("start", xtype=DOUBLE), VAL("end", xtype=DOUBLE),
                   VAL("subframeoffset", xtype=DOUBLE), VAL("sourceType", "primarytimecode", INTEGER, SOURCETYPE),
                   EL("subclipinfo"), VAL("stillFrameOffset", "stillframeoffset", DOUBLE),
                   VAL("pAspectRatio", "pixelaspectratio", INTEGER, PIXELASPECT), VAL("still", "stillframe", BOOLEAN),
                   CODE("gamma"), VAL("enable", "enabled", BOOLEAN), VAL("anamorphic", xtype=BOOLEAN),
                   VAL("alphatype", "alphatype", INTEGER, ALPHATYPE), VAL("alphareverse", xtype=BOOLEAN),
                   VAL("keytype", "compositemode", INTEGER, COMPOSITE), CODE("masterclipid"),
                   VAL("sync", "syncoffset", DOUBLE), EL("logginginfo"), EL("labels"), EL("comments"),
                   CODE("file"), EL("marker"), EL("filter"), EL("sourcetrack"), CODE("link"),
                   VAL("fieldDom", "fielddominance", INTEGER, FIELDDOM), CODE("multiclip"),
                   VAL("mediaDelay", "mediadelay", DOUBLE), CODE("itemhistory"), CODE("mixedratesoffset"),
                   CODE("timeremap")]),
    Rule("clipitem_a", "E", ELEM, path=("clip", IDX, "track", "audm"), conds=(("type", 1),), name="clipitem",
         ref=True, local=ITEM_LOCAL + ("link",), media="audio",
         children=TIMING + [VAL("start", xtype=DOUBLE), VAL("end", xtype=DOUBLE),
                   VAL("subframeoffset", xtype=DOUBLE), VAL("sourceType", "primarytimecode", INTEGER, SOURCETYPE),
                   EL("subclipinfo"), VAL("enable", "enabled", BOOLEAN), VAL("anamorphic", xtype=BOOLEAN),
                   VAL("alphatype", "alphatype", INTEGER, ALPHATYPE), VAL("alphareverse", xtype=BOOLEAN),
                   VAL("keytype", "compositemode", INTEGER, COMPOSITE), CODE("masterclipid"),
                   VAL("sync", "syncoffset", DOUBLE), EL("logginginfo"), EL("labels"), EL("comments"),
                   CODE("file"), EL("marker"), EL("filter"), EL("volume"), EL("pan"), EL("sourcetrack"),
                   CODE("link"), CODE("multiclip"), VAL("mediaDelay", "mediadelay", DOUBLE), CODE("itemhistory"),
                   CODE("mixedratesoffset"), CODE("timeremap")]),

    # ---- §8 nested-sequence clipitems ---------------------------------------------------------------------
    Rule("nestitem_v", "E", ELEM, path=("clip", IDX, "track", "vidm"), conds=(("type", 2),), name="clipitem",
         ref=True, local=NEST_LOCAL + ("link",), media="video",
         children=TIMING + [VAL("start", xtype=DOUBLE), VAL("end", xtype=DOUBLE),
                   VAL("sourceType", "primarytimecode", INTEGER, SOURCETYPE),
                   VAL("pAspectRatio", "pixelaspectratio", INTEGER, PIXELASPECT), EL("labels"), EL("comments"),
                   EL("logginginfo"), EL("marker"), EL("filter"), EL("nested"), EL("sourcetrack"),
                   VAL("keytype", "compositemode", INTEGER, COMPOSITE), CODE("link"), CODE("masterclipid"),
                   VAL("isMaster", "ismasterclip", BOOLEAN), VAL("fieldDom", "fielddominance", INTEGER, FIELDDOM),
                   VAL("mediaDelay", "mediadelay", DOUBLE), CODE("itemhistory"), CODE("timeremap")]),
    Rule("nestitem_a", "E", ELEM, path=("clip", IDX, "track", "audm"), conds=(("type", 2),), name="clipitem",
         ref=True, local=NEST_LOCAL + ("link",), media="audio",
         children=TIMING + [VAL("start", xtype=DOUBLE), VAL("end", xtype=DOUBLE),
                   VAL("sourceType", "primarytimecode", INTEGER, SOURCETYPE), EL("labels"), EL("logginginfo"),
                   EL("comments"), EL("marker"), EL("filter"), EL("volume"), EL("pan"), EL("nested"),
                   EL("sourcetrack"), CODE("link"), CODE("masterclipid"), VAL("isMaster", "ismasterclip", BOOLEAN),
                   VAL("mediaDelay", "mediadelay", DOUBLE), CODE("itemhistory"), CODE("timeremap")]),
    Rule("nested", "E", "clip", path=(IDX, "clip", IDX, "track"), vtype="dict", conds=(("subtype", 20),),
         name="sequence", ref=True, linkctx=True,
         local=SEQUENCE_LOCAL,
         children=[VAL("name", cond=REQUIRED), VAL("duration", xtype=DOUBLE, cond=REQUIRED), EL("rate"),
                   EL("timecode"), VAL("in", xtype=DOUBLE), VAL("out", xtype=DOUBLE), EL("media"), CODE("file"),
                   CODE("link"), EL("marker"), CODE("itemhistory")]),

    # ---- §5.7 transitionitem, generatoritem ------------------------------------------------------------
    Rule("transition_v", "E", ELEM, path=("clip", IDX, "track", "vidm"), conds=(("type", 3),),
         name="transitionitem", local=ITEM_LOCAL, media="video",
         children=[VAL("duration", xtype=DOUBLE), EL("rate"), EL("timecode"), VAL("in", xtype=DOUBLE),
                   VAL("out", xtype=DOUBLE), VAL("start", xtype=DOUBLE), VAL("end", xtype=DOUBLE),
                   CODE("alignment"), EL("effect")]),
    Rule("transition_a", "E", ELEM, path=("clip", IDX, "track", "audm"), conds=(("type", 3),),
         name="transitionitem", local=ITEM_LOCAL, media="audio",
         children=[VAL("duration", xtype=DOUBLE), EL("rate"), EL("timecode"), VAL("in", xtype=DOUBLE),
                   VAL("out", xtype=DOUBLE), VAL("start", xtype=DOUBLE), VAL("end", xtype=DOUBLE),
                   CODE("alignment"), EL("effect")]),
    Rule("generator_v", "E", ELEM, path=("clip", IDX, "track", "vidm"), conds=(("type", 4),),
         name="generatoritem", ref=True, local=ITEM_LOCAL + ("link",), media="video",
         children=TIMING + [VAL("start", xtype=DOUBLE), VAL("end", xtype=DOUBLE),
                   VAL("subframeoffset", xtype=DOUBLE), VAL("sourceType", "primarytimecode", INTEGER, SOURCETYPE),
                   VAL("enable", "enabled", BOOLEAN), VAL("anamorphic", xtype=BOOLEAN),
                   VAL("alphatype", "alphatype", INTEGER, ALPHATYPE), VAL("alphareverse", xtype=BOOLEAN),
                   VAL("keytype", "compositemode", INTEGER, COMPOSITE), CODE("masterclipid"),
                   VAL("pAspectRatio", "pixelaspectratio", INTEGER, PIXELASPECT), VAL("sync", "syncoffset", DOUBLE),
                   EL("logginginfo"), EL("labels"), EL("comments"), EL("effect"), EL("marker"), EL("filter"),
                   EL("sourcetrack"), CODE("link"), VAL("fieldDom", "fielddominance", INTEGER, FIELDDOM),
                   VAL("mediaDelay", "mediadelay", DOUBLE), CODE("itemhistory"), CODE("timeremap")]),
    Rule("generator_a", "E", ELEM, path=("clip", IDX, "track", "audm"), conds=(("type", 4),),
         name="generatoritem", ref=True, local=ITEM_LOCAL + ("link",), media="audio",
         children=TIMING + [VAL("start", xtype=DOUBLE), VAL("end", xtype=DOUBLE),
                   VAL("subframeoffset", xtype=DOUBLE), VAL("sourceType", "primarytimecode", INTEGER, SOURCETYPE),
                   VAL("enable", "enabled", BOOLEAN), VAL("anamorphic", xtype=BOOLEAN),
                   VAL("alphatype", "alphatype", INTEGER, ALPHATYPE), VAL("alphareverse", xtype=BOOLEAN),
                   VAL("keytype", "compositemode", INTEGER, COMPOSITE), CODE("masterclipid"),
                   VAL("pAspectRatio", "pixelaspectratio", INTEGER, PIXELASPECT), VAL("sync", "syncoffset", DOUBLE),
                   EL("logginginfo"), EL("labels"), EL("comments"), EL("effect"), EL("marker"), EL("filter"),
                   EL("sourcetrack"), CODE("link"), VAL("fieldDom", "fielddominance", INTEGER, FIELDDOM),
                   VAL("mediaDelay", "mediadelay", DOUBLE), CODE("itemhistory"), CODE("timeremap")]),

    # ---- §5.8 filter, effect, parameter, keyframe --------------------------------------------------------
    Rule("filter", "E", ELEM, path=("filters",), vtype="dict", name="filter",
         local=("enabled", "start", "end", "effect"),
         children=[VAL("enabled", xtype=BOOLEAN), VAL("start", xtype=DOUBLE), VAL("end", xtype=DOUBLE), EL("effect")]),
    Rule("effect", "E", "effect", vtype="dict", name="effect",
         local=("name", "group", "fxclass", "parameter", "wipecode", "wipeaccuracy", "startratio", "endratio",
                "reverseratio", "whateffect", "subtype"),
         children=[VAL("name"), CODE("effectid"), VAL("group", "effectcategory"), VAL("fxclass", "effectclass"),
                   CODE("effecttype"), CODE("effect_mediatype"), CODE("qteffect"),
                   CODE("if_transition", VAL("wipecode", xtype=INTEGER)),
                   CODE("if_transition", VAL("wipeaccuracy", xtype=INTEGER)),
                   CODE("if_transition", VAL("startratio", xtype=DOUBLE)),
                   CODE("if_transition", VAL("endratio", xtype=DOUBLE)),
                   CODE("if_transition", VAL("reverseratio", "reverse", BOOLEAN)),
                   CODE("privatestate"), EL("parameter"), CODE("generator_multiclip")]),
    Rule("effect_elem", "E", ELEM, conds=(("subtype", (11, 12, 13, 14, 15)),), name="effect",
         local=("name", "group", "fxclass", "parameter", "wipecode", "wipeaccuracy", "startratio", "endratio",
                "reverseratio", "whateffect", "subtype"),
         children=[VAL("name"), CODE("effectid"), VAL("group", "effectcategory"), VAL("fxclass", "effectclass"),
                   CODE("effecttype"), CODE("effect_mediatype"), CODE("qteffect"),
                   CODE("if_transition", VAL("wipecode", xtype=INTEGER)),
                   CODE("if_transition", VAL("wipeaccuracy", xtype=INTEGER)),
                   CODE("if_transition", VAL("startratio", xtype=DOUBLE)),
                   CODE("if_transition", VAL("endratio", xtype=DOUBLE)),
                   CODE("if_transition", VAL("reverseratio", "reverse", BOOLEAN)),
                   CODE("privatestate"), EL("parameter")]),
    Rule("parameter", "E", "#parameter", vtype="dict", name="parameter", slot="parameter", local=PARAM_LOCAL,
         children=[CODE("parameterid"), VAL("specifier", "parameterspecifier"), VAL("title", "name")] + PARAM_TAIL),
    Rule("keyframe", "E", ELEM, path=("keyframe",), vtype="dict", name="keyframe",
         local=("when", "value", "hadBezierIn", "hadBezierOut", "speedKFStart", "speedKFEnd", "speedKFIn",
                "speedKFOut", "anchorOffset", "speedVirtualKF", "origValue", "inscale", "inbez", "outscale",
                "outbez"),
         children=[VAL("when", xtype=DOUBLE), CODE("kf_value"), VAL("hadBezierIn", "hadbezierin", BOOLEAN),
                   VAL("hadBezierOut", "hadbezierout", BOOLEAN), VAL("speedKFStart", "speedkfstart", BOOLEAN),
                   VAL("speedKFEnd", "speedkfend", BOOLEAN), VAL("speedKFIn", "speedkfin", BOOLEAN),
                   VAL("speedKFOut", "speedkfout", BOOLEAN), VAL("anchorOffset", "anchorOffset", DOUBLE),
                   VAL("speedVirtualKF", "speedvirtualkf", BOOLEAN), VAL("origValue", "origvalue", DOUBLE),
                   VAL("inscale", xtype=DOUBLE), VAL("inbez", xtype=FPOINT), VAL("outscale", xtype=DOUBLE),
                   VAL("outbez", xtype=FPOINT)]),
    Rule("interpolation", "E", None, name="interpolation", create=True, children=[LIT("name", "FCPCurve")]),

    # ---- §5.9 marker -------------------------------------------------------------------------------------
    # oracle-observed, spec gap: a marker without comment1 takes its item's (an empty <comment/>)
    Rule("marker", "E", ELEM, path=("markers",), vtype="dict", name="marker",
         children=[VAL("name"), VAL("comment1", "comment"), CODE("marker_color"), VAL("in", xtype=DOUBLE),
                   VAL("out", xtype=DOUBLE)]),

    # ---- §5.10 rate, timecode ------------------------------------------------------------------------------
    Rule("rate", "E", "rate", vtype="dict", name="rate", create=True, omit=True,
         children=[VAL("ntscrate", "ntsc", BOOLEAN), VAL("framebase", "timebase", INTEGER)]),
    Rule("timecode", "E", ELEM, path=("tcTracks",), vtype="dict", name="timecode",
         local=("trackType", "displayFormat", "segStart", "rate"),
         children=[EL("rate"), CODE("tc_string"), CODE("tc_frame"), VAL("trackType", "source", INTEGER, TRACKTYPE),
                   VAL("displayFormat", "displayformat", INTEGER, DISPLAYFORMAT)]),

    # ---- §5.11 smaller elements ------------------------------------------------------------------------------
    Rule("logginginfo", "E", None, name="logginginfo", create=True, omit=True,
         children=[VAL("label", "description"), VAL("scene"), VAL("take", "shottake"), VAL("lognote"),
                   VAL("good", xtype=BOOLEAN), CODE("filmnotes")]),
    Rule("labels", "E", None, name="labels", create=True, omit=True,
         children=[CODE("label"), VAL("labelComment", "label2")]),
    Rule("comments", "E", None, name="comments", create=True, omit=True,
         children=[VAL("comment1", "mastercomment1"), VAL("comment2", "mastercomment2"),
                   VAL("comment3", "mastercomment3"), VAL("comment4", "mastercomment4"),
                   VAL("comment5", "clipcommenta"), VAL("comment6", "clipcommentb")]),
    # oracle-observed, spec gap: items store inoffset/outoffset directly (no `subclipinfo` dictionary),
    # so <subclipinfo> is built on the spot and dropped when empty
    Rule("subclipinfo", "E", None, name="subclipinfo", create=True, omit=True,
         children=[VAL("inoffset", "startoffset", DOUBLE), VAL("outoffset", "endoffset", DOUBLE)]),
    Rule("sourcetrack", "E", None, name="sourcetrack", create=True, children=[CODE("sourcetrack")]),

    # ---- §6 audio intrinsic filters --------------------------------------------------------------------------
    Rule("volume", "E", "volume", vtype="dict", name="filter", local=("min", "max", "value", "keyframe"),
         children=[CODE("audio_filter", "Audio Levels", "audiolevels", "Level", "level")]),
    Rule("pan", "E", "pan", vtype="dict", name="filter", local=("min", "max", "value", "keyframe"),
         children=[CODE("audio_filter", "Audio Pan", "audiopan", "Pan", "pan")]),

    # ---- §6 motion intrinsic filters: a <filter> per motion sub-dictionary, its <effect> made of literals,
    #      one <parameter> per parameter dictionary in the sub-dictionary's key order ------------------------
    Rule("m_basic", "E", "basic", path=("motion",), vtype="dict", name="filter", slot="filter",
         local=("parameter", "enabled"), children=[EL("e_basic")]),
    Rule("m_crop", "E", "crop", path=("motion",), vtype="dict", name="filter", slot="filter",
         local=("parameter", "enabled"), forced="#mparam", children=[EL("e_crop")]),
    Rule("m_deformation", "E", "deformation", path=("motion",), vtype="dict", name="filter", slot="filter",
         local=("parameter", "enabled"), children=[EL("e_deformation")]),
    Rule("m_opacity", "E", "opacity", path=("motion",), vtype="dict", name="filter", slot="filter",
         local=("parameter", "enabled"), forced="#mparam", children=[EL("e_opacity")]),
    Rule("m_dropshadow", "E", "dropshadow", path=("motion",), vtype="dict", name="filter", slot="filter",
         local=("parameter", "enabled"), forced="#mparam",
         children=[VAL("enabled", xtype=BOOLEAN), EL("e_dropshadow")]),
    Rule("m_motionblur", "E", "motionblur", path=("motion",), vtype="dict", name="filter", slot="filter",
         local=("parameter", "enabled"), children=[VAL("enabled", xtype=BOOLEAN), EL("e_motionblur")]),
    # spec §6: the template maps motion/timeremap to a Time Remap filter.  oracle-observed, spec gap:
    # only nested-sequence items keep such a dictionary (FCP 7 converts a media item's on loading);
    # the filter lists variablespeed, mappedduration, speed, reverse and frameblending in key order,
    # with valuemin/valuemax and, for the timecode only, a value
    Rule("m_timeremap", "E", "timeremap", path=("motion",), vtype="dict", name="filter", slot="filter",
         omit=True, children=[CODE("motion_timeremap")]),
] + [
    Rule("e_" + k, "E", None, name="effect", create=True,
         children=[LIT("name", n), LIT("effectid", k), LIT("effectcategory", "motion"), LIT("effecttype", "motion"),
                   LIT("mediatype", "video"), EL("parameter")])
    for k, n in (("basic", "Basic Motion"), ("crop", "Crop"), ("deformation", "Distort"), ("opacity", "Opacity"),
                 ("dropshadow", "Drop Shadow"), ("motionblur", "Motion Blur"))
] + [
    Rule("mp_%s_%s" % (owner, k), "E", k, path=(owner, "motion"), vtype="dict", name="parameter", slot="parameter",
         local=PARAM_LOCAL, children=[LIT("parameterid", k), LIT("name", n)] + PARAM_TAIL)
    for owner, k, n in (("basic", "scale", "Scale"), ("basic", "rotation", "Rotation"), ("basic", "center", "Center"),
                        ("basic", "centerOffset", "Anchor Point"), ("deformation", "ulcorner", "Upper Left"),
                        ("deformation", "urcorner", "Upper Right"), ("deformation", "lrcorner", "Lower Right"),
                        ("deformation", "llcorner", "Lower Left"), ("deformation", "aspect", "Aspect"),
                        ("motionblur", "duration", "% Blur"), ("motionblur", "samples", "Samples"))
] + [
    Rule("mparam", "E", "#mparam", vtype="dict", name="parameter", slot="parameter", local=PARAM_LOCAL,
         children=[CODE("parameterid"), CODE("parameterid", "name")] + PARAM_TAIL),

    # ---- containers (spec §2.1) --------------------------------------------------------------------------------
    Rule("c_motion", "C", "motion", vtype="dict", up=("filter",)),
    Rule("c_filters", "C", "filters", vtype="array", up=("filter",)),
    Rule("c_markers", "C", "markers", vtype="array", up=("marker",)),
    Rule("c_keyframe", "C", "keyframe", vtype="array", up=("keyframe",)),
    Rule("c_parms", "C", "parms", vtype="dict", up=("parameter", "stateinfokey", "patchName")),
    Rule("c_public", "C", "public", path=("parms",), vtype="dict", up=("parameter",), forced="#parameter"),
    Rule("c_private", "C", "private", path=("parms",), vtype="dict", up=("stateinfokey", "patchName")),
    Rule("c_seqprops", "C", "seqProps", vtype="dict", up=("videoformat", "audioformat", "outputs")),
    Rule("c_final", "C", "final", path=("seqProps",), vtype="dict", up="*"),
    Rule("c_processing", "C", "processing", path=("seqProps",), vtype="dict", up="*"),
    Rule("c_audiogroup", "C", "audioGroup", path=("seqProps",), vtype="dict", up="*"),
    Rule("c_qtaudio", "C", "QTAudioFormat", path=("final",), vtype="dict", up="*"),
    Rule("c_masterclips", "C", "masterClips", vtype="dict", up=("master", "subclipMaster")),
    Rule("c_tcdata", "C", "tcData", vtype="dict", up=("sourceType", "timecode")),
    Rule("c_tctracks", "C", "tcTracks", path=("tcData",), vtype="array", up=("timecode",)),
    Rule("c_tcsegments", "C", "tcSegments", path=(IDX, "tcTracks"), vtype="array", up="*"),
    Rule("c_tcsegment", "C", ELEM, path=("tcSegments",), vtype="dict", up="*"),
    Rule("c_track", "C", "track", path=(ANY, "media"), vtype="array", up=("track",)),
    Rule("c_clip", "C", "clip", path=(IDX, "track"), vtype="array", straight=True),
    Rule("c_selector", "C", "selector", path=(IDX, "clip", IDX, "track", "vidm"), vtype="dict", up=("layerIndex",)),
]

# value rules (pass 1): the keys whose values are parked in the current scope
VALUE_KEYS = frozenset((
    "name", "duration", "in", "out", "start", "end", "subframeoffset", "framebase", "ntscrate",
    "enable", "lock", "outputIndex", "anamorphic", "alphatype", "alphareverse", "keytype", "sync",
    "fieldDom", "mediaDelay", "isMaster", "label", "labelComment", "labelColor", "scene", "take",
    "lognote", "good", "comment1", "comment2", "comment3", "comment4", "comment5", "comment6",
    "stillFrameOffset", "still", "stillGamma", "angle", "pAspectRatio", "sourceType", "master",
    "subclipMaster", "inoffset", "outoffset", "trackType", "displayFormat", "segStart", "enabled",
    "group", "fxclass", "wipecode", "wipeaccuracy", "startratio", "endratio", "reverseratio",
    "specifier", "title", "min", "max", "when", "hadBezierIn", "hadBezierOut", "speedKFStart",
    "speedKFEnd", "speedKFIn", "speedKFOut", "anchorOffset", "speedVirtualKF", "origValue", "inscale",
    "inbez", "outscale", "outbez", "color", "value", "width", "height", "depth", "doYUV",
    "doSuperWhite", "renderColorMode", "typeName", "cType", "vendor", "spatialQuality",
    "temporalQuality", "keyFrameRate", "dataRate", "audioDepth", "sampleRate", "channels",
    "masterLevel", "stateinfokey", "patchName", "channelIndex", "layerIndex", "panInvert"))


# ---------------------------------------------------------------------------------------------
# the engine (spec §2)
# ---------------------------------------------------------------------------------------------

class ExportError(Exception):
    """The export stops: a required slot is empty (spec §2.6)."""


_MISSING = object()


class Scope:
    """Named slots plus the scope chain (spec §2.4).  A child scope sees its parent's slots (the
    parent is suspended while the child is translated, so this equals a copy taken at opening) except
    the names its element rule declares local.  Parked values are nodes; filed elements are lists."""
    __slots__ = ("slots", "parent", "chain", "local", "x", "straight", "linkctx", "rule", "dict",
                 "arr", "idx", "key", "forced")

    def __init__(self, parent, key, x, rule=None, local=frozenset(), straight=False):
        self.slots = {}
        self.parent = parent
        self.chain = (parent.chain + (key,)) if parent is not None else ()
        self.local = local
        self.x = x
        self.straight = straight
        self.linkctx = None
        self.rule = rule
        self.dict = None
        self.arr = None
        self.idx = None
        self.key = key
        self.forced = None

    def get(self, name):
        s = self
        while s is not None:
            v = s.slots.get(name, _MISSING)
            if v is not _MISSING:
                return v
            if name in s.local:
                return None
            s = s.parent
        return None

    def find(self, attr):
        s = self
        while s is not None:
            v = getattr(s, attr)
            if v is not None:
                return s
            s = s.parent
        return None

    def file(self, slot, x):
        if self.straight:
            self.x.add(x)
        else:
            self.slots.setdefault(slot, []).append(x)


def _path_ok(path, chain):
    j = len(chain) - 1
    for p in path:
        if j < 0:
            return p == TOP
        c = chain[j]
        if p == ANY:
            pass
        elif p == IDX:
            if not isinstance(c, int):
                return False
        elif p == TOP or p != c:
            return False
        j -= 1
    return True


class Translator:
    def __init__(self, doc, include_history=True):
        self.doc = doc if isinstance(doc, Doc) else Doc(doc)
        self.ids = IdTable()
        self.include_history = include_history
        self.by_key = {}
        self.cond_only = []
        self.by_id = {}
        order = {"E": 0, "C": 1, "V": 2}
        for r in RULES:
            self.by_id[r.id] = r
            if r.key is None:
                continue
            if r.key == ELEM and not r.path and r.kind == "E" and r.conds:
                self.cond_only.append(r)
                continue
            self.by_key.setdefault(r.key, []).append(r)
        for k, rs in self.by_key.items():
            rs.sort(key=lambda r: (order[r.kind], not r.path, not r.conds))
        self.masters = None
        self.master_refs = []        # master clips named by <masterclipid>/<subclipmasterid>, first-mention order

    # -- rule selection (spec §2.3) ----------------------------------------------------------
    def _type_ok(self, r, v):
        if r.vtype is None:
            return True
        if not self.doc.is_dict(v):
            return False
        if r.vtype == "array":
            return self.doc.style(v) == ARRAY
        return True

    def _conds_ok(self, r, v):
        D = self.doc
        for key, want in r.conds:
            got = D.num(D.get(v, key)) if D.is_dict(v) else None
            if isinstance(want, tuple):
                if got not in want:
                    return False
            elif got != want:
                return False
        return True

    def select(self, key, v, scope):
        for r in self.by_key.get(key, ()):
            if r.path and not _path_ok(r.path, scope.chain):
                continue
            if not self._type_ok(r, v):
                continue
            if r.conds and not self._conds_ok(r, v):
                continue
            return r
        if key == ELEM and self.doc.is_dict(v):
            for r in self.cond_only:
                if self._conds_ok(r, v):
                    return r
        if key in VALUE_KEYS:
            return "V"
        return None

    # -- walking a dictionary (spec §2.2) ---------------------------------------------------------
    def translate(self, d, scope):
        D = self.doc
        st = D.style(d)
        if st == STRUCT:
            return
        if st == ARRAY:
            for i, el in enumerate(D.elements(d)):
                v = D.deref(el)
                if v is None:
                    continue
                r = self.select(ELEM, v, scope)
                if r is None or r == "V":
                    continue
                if r.kind == "C":
                    self.container(r, i, v, scope, arr=d, idx=i)
                else:
                    self.element(r, i, v, scope, arr=d, idx=i)
            return
        ents = D.entries(d)
        keys = [k for k, _ in ents]
        if "vidm" in keys and "audm" in keys and keys.index("audm") < keys.index("vidm"):
            a, b = keys.index("audm"), keys.index("vidm")
            ents[a], ents[b] = ents[b], ents[a]
        sel = []
        for k, v in ents:
            v = D.deref(v)
            if v is None:
                continue
            look = k
            if scope.forced is not None and D.is_dict(v):
                look = scope.forced
            r = self.select(look, v, scope)
            if r is not None:
                sel.append((k, v, r))
        for k, v, r in sel:                         # pass 1: values
            if r == "V":
                scope.slots[k] = v
        for k, v, r in sel:                         # pass 2: containers
            if r != "V" and r.kind == "C":
                self.container(r, k, v, scope)
        for k, v, r in sel:                         # pass 3: elements
            if r != "V" and r.kind == "E":
                self.element(r, k, v, scope)

    def container(self, r, key, v, scope, arr=None, idx=None):
        cs = Scope(scope, key, scope.x, rule=r, straight=r.straight)
        cs.forced = r.forced
        cs.dict = v
        cs.arr, cs.idx = arr, idx
        self.translate(v, cs)
        for slot in CONTAINER_POST.get(r.id, ()):
            self.build(self.by_id[slot], None, None, cs, on_spot=True, file_to=cs)
        hook = CONTAINER_CODE.get(r.id)
        if hook is not None:
            hook(self, cs, v)
        names = list(cs.slots) if r.up == "*" else (r.up or ())
        for name in names:
            val = cs.slots.get(name, _MISSING)
            if val is _MISSING:
                continue
            if isinstance(val, list):
                scope.slots.setdefault(name, []).extend(val)
            else:
                scope.slots[name] = val

    # -- building an element (spec §2.5) ----------------------------------------------------------
    def element(self, r, key, v, scope, arr=None, idx=None):
        self.build(r, key, v, scope, arr=arr, idx=idx)

    def build(self, r, key, v, scope, arr=None, idx=None, on_spot=False, file_to=None):
        ident = None
        if r.ref and v is not None:
            obj = v
            if obj in self.ids.written:
                x = X(r.name, id=self.ids.get(obj))
                self._file(r, x, scope, file_to, on_spot)
                return x
            ident = self.ids.assign(obj, self.base(v))
            self.ids.written.add(obj)
        x = X(r.name, id=ident)
        cs = Scope(scope, key if key is not None else r.slot, x, rule=r, local=r.local,
                   straight=bool(r.straight))
        cs.dict = v
        cs.arr, cs.idx = arr, idx
        cs.forced = r.forced
        if r.linkctx:
            cs.linkctx = v
        if v is not None and self.doc.is_dict(v):
            self.translate(v, cs)
            if r.media is not None:
                _converted_speed_duration(self, cs, v)
        self.write_children(r, cs, x, v)
        if r.omit and x.empty():
            return None
        if on_spot and file_to is None:
            return x
        self._file(r, x, scope, file_to, on_spot)
        return x

    def _file(self, r, x, scope, file_to, on_spot):
        if file_to is not None:
            file_to.slots.setdefault(r.slot, []).append(x)
        elif not on_spot:
            scope.file(r.slot, x)

    def base(self, v):
        """Id base of a dictionary: its `name` (spec §3); a nameless dictionary's memory address is
        not reproducible, its file offset stands in."""
        nm = self.doc.raw_text(self.doc.get(v, "name"))
        return nm if nm is not None else str(v.off).encode("ascii")

    # -- child slots (spec §2.6) ------------------------------------------------------------------
    def write_children(self, r, cs, x, d):
        for spec in r.children:
            self.write_spec(spec, cs, x, d)

    def write_spec(self, spec, cs, x, d):
        kind = spec[0]
        if kind == "lit":
            x.add(X(spec[1], spec[2]))
        elif kind == "code":
            CODE_FN[spec[1]](self, cs, x, d, *spec[2:])
        elif kind == "val":
            self.write_val(spec, cs, x)
        elif kind == "elem":
            self.write_elem(spec, cs, x)

    def write_val(self, spec, cs, x):
        _, key, name, xtype, vmap, default, cond = spec
        node = cs.get(key)
        if node is None or isinstance(node, list):
            if cond == REQUIRED:
                raise ExportError("required <%s> missing in <%s>" % (name, x.name))
            if default is not None:
                x.add(X(name, default))
            return
        e = self.leaf(name, node, xtype, vmap)
        if e is not None:
            x.add(e)
        elif cond == REQUIRED:
            raise ExportError("required <%s> missing in <%s>" % (name, x.name))

    def write_elem(self, spec, cs, x):
        _, rid, cond = spec
        r = self.by_id[rid]
        if cond == "after_keyframe" and not any(c.name == "keyframe" for c in x.children):
            return
        els = cs.get(r.slot)
        if isinstance(els, list) and els:
            for e in els:
                x.add(e)
            return
        if r.create:
            e = self.build(r, None, None, cs, on_spot=True)
            if e is not None:
                x.add(e)

    # -- leaves (spec §4) --------------------------------------------------------------------------
    def leaf(self, name, node, xtype, vmap=None):
        D = self.doc
        tc = D.tc(node)
        if tc in (T_STR, T_CSTR):
            value = D.text(node)
        elif tc in (T_POINT, T_FPOINT, T_RGBA):
            value = node.payload
        else:
            value = D.num(node)
        return leaf_element(name, xtype, tc, value, vmap)


def _assign_master_ids(tr, cs, v):
    """oracle-observed, spec gap: the master clip ids that <masterclipid>/<subclipmasterid> will name
    are assigned when the item's masterClips container is translated (pass 2), i.e. before the
    elements of pass 3: a subclip's own clip item gets its id after its master clip (SSTIKI)."""
    D = tr.doc
    if D.get(v, "orphan") is not None:          # a deleted master clip is never named (spec §5.11)
        return
    for k, node in D.entries(v):
        if k in ("master", "subclipMaster"):
            u = D.uuid(D.deref(node))
            m = master_clip(tr, u) if u else None
            if m is not None:
                tr.ids.assign(m, tr.base(m))


CONTAINER_CODE = {"c_masterclips": _assign_master_ids}

CONTAINER_POST = {
    # oracle-observed, spec gap: the <format> elements of <video>/<audio> exist exactly for items that
    # have a seqProps dictionary (a clip without one has none, spec §5.4 "media branches of clips");
    # they are built from seqProps' slots and handed up as `videoformat`/`audioformat`, which is why
    # no item inherits the format values (anamorphic, pAspectRatio, ...) of its sequence.
    "c_seqprops": ("videoformat", "audioformat"),
}


# ---------------------------------------------------------------------------------------------
# code behaviours (the "(code)" children of spec §5-§8)
# ---------------------------------------------------------------------------------------------

def _media_of(cs):
    """'video' or 'audio': the media kind of the nearest enclosing track item."""
    s = cs
    while s is not None:
        if s.rule is not None and s.rule.media:
            return s.rule.media
        s = s.parent
    return None


def c_uuid(tr, cs, x, d):
    """<uuid>, <updatebehavior> (spec §5.2, §5.11): the item's UUID entry (inline or a reference to
    the shared table) and the word `add`."""
    u = tr.doc.uuid(tr.doc.get(d, "UUID")) if d is not None else None
    if u:
        x.add(X("uuid", u))
        x.add(X("updatebehavior", "add"))


def c_if_video(tr, cs, x, d, spec):
    if tr.doc.num(tr.doc.get(d, "subtype")) == 4:
        tr.write_spec(spec, cs, x, d)


def c_if_transition(tr, cs, x, d, spec):
    if tr.doc.num(tr.doc.get(d, "subtype")) in (11, 12):
        tr.write_spec(spec, cs, x, d)


def c_masterclipid(tr, cs, x, d):
    """<masterclipid>, <subclipmasterid> (spec §5.11): the export id of the project's master clip
    whose UUID the item's masterClips/master (subclipMaster) names, assigned now if new.  Nothing is
    named when the item's masterClips carries the `orphan` key (its master clip was deleted; FCP's
    own exports leave <masterclipid> out — Living_prayer_1 " FINAL_CHRISTIANITY VF+subs")."""
    if _orphan_master(tr, cs, d):
        return
    for key, name in (("master", "masterclipid"), ("subclipMaster", "subclipmasterid")):
        u = tr.doc.uuid(cs.get(key))
        m = master_clip(tr, u) if u else None
        if m is not None:
            x.add(X(name, tr.ids.assign(m, tr.base(m))))
            if m not in tr.master_refs:
                tr.master_refs.append(m)


def _orphan_master(tr, cs, d):
    """True when the item dictionary's masterClips holds the `orphan` key (spec §5.11)."""
    D = tr.doc
    item = d if d is not None else cs.dict
    if item is None or not D.is_dict(item):
        return False
    mc = D.get(item, "masterClips")
    return mc is not None and D.is_dict(mc) and D.get(mc, "orphan") is not None


def c_gamma(tr, cs, x, d):
    """<gamma> (spec §5.3: the application's gamma text for stillGamma).  oracle-observed, spec gap:
    stillGamma is a 16.16 fixed-point number written with two decimals (144179: 2.20); -1 writes
    nothing."""
    n = tr.doc.num(cs.get("stillGamma"))
    if n is None or n < 0:
        return
    x.add(X("gamma", "%.2f" % (n / 65536.0)))


def c_fourcc(tr, cs, x, d, key, name):
    """Four characters, most significant byte first (spec §5.4 codec type and vendor codes)."""
    n = tr.doc.num(cs.get(key))
    if n is None:
        return
    b = (int(n) & 0xFFFFFFFF).to_bytes(4, "big")
    x.add(X(name, b.decode("mac_roman")))


def _number_text(D, node):
    """A float, double or integer value as text (%g or decimal), else None."""
    tc = D.tc(node)
    if tc in (T_F32, T_F64):
        return fmt_g(node.payload)
    if tc in (T_INT, T_UINT, 0x1B, 0x1C, 0x21, 0x22):
        return str(int(D.num(node)))
    return None


def c_number(tr, cs, x, d, key, name):
    """<valuemin>/<valuemax>: whichever of float, double or integer is stored (spec §5.8)."""
    node = cs.get(key)
    if node is None or isinstance(node, list):
        return
    t = _number_text(tr.doc, node)
    if t is not None:
        x.add(X(name, t))


def c_parameterid(tr, cs, x, d, name="parameterid"):
    k = cs.key
    if isinstance(k, str):
        x.add(X(name, k))


def _typed_value(tr, node, name, keyframed):
    """The <value> matching the stored type (spec §5.8): float, double, integer, boolean; float
    point, point and colour only when no keyframe was written."""
    D = tr.doc
    tc = D.tc(node)
    if tc in (T_F32, T_F64):
        return X(name, fmt_g(node.payload))
    if tc in (T_INT, T_UINT, 0x1B, 0x1C, 0x21, 0x22):
        return X(name, str(int(D.num(node))))
    if tc == T_BOOL:
        return X(name, fmt_bool(node.payload))
    if tc in (T_FPOINT, T_POINT, T_RGBA) and not keyframed:
        return tr.leaf(name, node, {T_FPOINT: FPOINT, T_POINT: POINT, T_RGBA: RGBA}[tc])
    return None


def c_param_value(tr, cs, x, d):
    """The tail of a <parameter> (spec §5.8): string value, value list, then the typed value."""
    D = tr.doc
    node = cs.get("value")
    if isinstance(node, list):
        node = None
    keyframed = any(c.name == "keyframe" for c in x.children)
    if node is not None and D.tc(node) in (T_STR, T_CSTR):
        x.add(X("value", D.text(node)))
    c_valuelist(tr, cs, x, d)
    if node is None or D.tc(node) in (T_STR, T_CSTR):
        return
    if D.tc(node) == T_OBJ:
        obj = D.deref(node)
        e = _value_object(tr, obj)
        if e is not None:
            x.add(e)
        return
    if D.tc(node) == T_MSG and d is not None and D.num(D.get(d, "uitype")) == 5:
        e = _clip_well(tr, cs, node)
        if e is not None:
            x.add(e)
        return
    e = _typed_value(tr, node, "value", keyframed)
    if e is not None:
        x.add(e)


def _clip_well(tr, cs, node):
    """A clip well's <value> (spec §5.8, code, uitype 5): the messageable's info dictionary holds the
    clip, written as a <clip> element (referenced: `<clip id="..."/>` when already written)."""
    D = tr.doc
    for ch in node.children:
        if ch.role == "member" and D.is_dict(ch):
            clip = D.get(ch, "clip")
            if clip is not None and D.is_dict(clip):
                e = tr.build(tr.by_id["clip"], "clip", clip, cs, on_spot=True)
                if e is not None:
                    vx = X("value")
                    vx.add(e)
                    return vx
    return None


def _archived_class(data):
    """The class name of a keyed archive's root object, or None."""
    import plistlib
    try:
        pl = plistlib.loads(bytes(data))
        objs = pl["$objects"]
        top = pl["$top"]
        root = objs[(top["root"] if "root" in top else next(iter(top.values()))).data]
        return objs[root["$class"].data]["$classname"]
    except Exception:
        return None


def _value_object(tr, obj):
    """<value> from a serialised value object (spec §5.8, code): a 17KGPortValueObject's keyed-archiver
    bytes as opaque data in the private encoding.  oracle-observed, spec gap: a PFXGradient (the
    structured "RGB and alpha sample lists") writes no <value>; the structured forms are not modelled."""
    if obj is None or obj.kind != "T20":
        return None
    m = obj.payload
    if isinstance(m, tuple) and len(m) == 4 and m[0] == "obj":
        m = m[3]
    data = m.get("plist") if isinstance(m, dict) else None
    if not isinstance(data, (bytes, bytearray)):
        return None
    if _archived_class(data) == "PFXGradient":
        return None
    return X("value", private_encode(data))


def c_valuelist(tr, cs, x, d):
    """<valuelist> from uiinfo/labels, the popup's choices (spec §5.8, H): one <valueentry> per
    label with its name and value.  oracle-observed, spec gap: the values are the parameter's
    `popupvalues` when stored, else 1, 2, 3...; a "-" label (a menu separator) is written with an
    empty name."""
    D = tr.doc
    ui = D.get(d, "uiinfo") if d is not None else None
    labels = D.get(ui, "labels") if ui is not None else None
    if labels is None or not D.is_dict(labels):
        return
    els = D.elements(labels)
    if not els:
        return
    pv = D.get(d, "popupvalues")
    pvals = [D.num(D.deref(e)) for e in D.elements(pv)] if pv is not None and D.is_dict(pv) else []
    vl = X("valuelist")
    for i, el in enumerate(els):
        ve = X("valueentry")
        name = D.text(el) or ""
        ve.add(X("name", "" if name == "-" else name))
        v = pvals[i] if i < len(pvals) and pvals[i] is not None else i + 1
        ve.add(X("value", str(int(v))))
        vl.add(ve)
    x.add(vl)


def c_kf_value(tr, cs, x, d):
    node = cs.get("value")
    if node is None or isinstance(node, list):
        return
    e = _typed_value(tr, node, "value", False)
    if e is not None:
        x.add(e)


def c_effectid(tr, cs, x, d):
    """<effectid> (spec §6), in order of preference: scriptid, matchName, parms/private/patchName
    (QCMotionPatch plus the input file name), an audio transition's id, {type, subtype, manufacturer}."""
    D = tr.doc
    for k in ("scriptid", "matchName"):
        t = D.text(D.get(d, k))
        if t is not None:
            x.add(X("effectid", t))
            return
    pn = D.text(D.path(d, "parms", "private", "patchName"))
    if pn is not None:
        if pn.lower() == "qcmotionpatch":
            fn = D.text(D.path(d, "parms", "public", "inputFileName", "value"))
            if fn is not None:
                pn = "QCMotionPatch:" + fn
        x.add(X("effectid", pn))
        return
    if D.num(D.get(d, "subtype")) == 12:
        t = D.text(D.get(d, "id"))
        if t is not None:
            x.add(X("effectid", t))
            return
    ids = [D.get(d, k) for k in ("typeID", "subTypeID", "manufacturerID")]
    if all(n is not None and D.tc(n) in (T_INT, T_UINT) for n in ids):
        x.add(X("effectid", "{%s}" % ", ".join("%x" % (D.num(n) & 0xFFFFFFFF) for n in ids)))


_EFFECTTYPE = {11: "transition", 12: "transition", 13: "filter", 14: "filter", 15: "generator"}
_EFFECTMEDIA = {11: "video", 12: "audio", 13: "video", 14: "audio", 15: "video"}


def c_effecttype(tr, cs, x, d):
    t = _EFFECTTYPE.get(tr.doc.num(tr.doc.get(d, "subtype")))
    if t:
        x.add(X("effecttype", t))


def c_effect_mediatype(tr, cs, x, d):
    t = _EFFECTMEDIA.get(tr.doc.num(tr.doc.get(d, "subtype")))
    if t:
        x.add(X("mediatype", t))


def c_qteffect(tr, cs, x, d):
    """QuickTime effects (spec §6): <appspecificdata> with the application constants and
    <data><qteffectid><whateffect> as four characters."""
    n = tr.doc.num(tr.doc.get(d, "whateffect"))
    if n is None:
        return
    a = x.add(X("appspecificdata"))
    a.add(X("appname", "Final Cut Pro"))
    a.add(X("appmanufacturer", "Apple Inc."))
    a.add(X("appversion", "7.0"))
    q = a.add(X("data")).add(X("qteffectid"))
    q.add(X("whateffect", (int(n) & 0xFFFFFFFF).to_bytes(4, "big").decode("mac_roman")))


def c_marker_color(tr, cs, x, d):
    """<color> <- color (RGBA).  oracle-observed, spec gap: in a project saved by an older application
    (stream version below 222) a marker without a colour gets the colour FCP 7 gives such markers on
    loading: green (0, 48, 191, 72) for a sequence's markers and a nested-sequence item's, red
    (0, 255, 0, 0) for the others; FCP 7 projects keep colourless markers colourless."""
    node = cs.get("color")
    if node is not None and not isinstance(node, list):
        e = tr.leaf("color", node, RGBA)
        if e is not None:
            x.add(e)
        return
    if (tr.doc.sd.stream_version or 0) >= 222:
        return
    D = tr.doc
    s = cs.parent
    while s is not None and (s.rule is None or s.rule.kind != "E"):
        s = s.parent
    owner = s.dict if s is not None else None
    seq = D.num(D.get(owner, "subtype")) == 20 or D.num(D.get(owner, "type")) == 2
    x.add(leaf_element("color", RGBA, T_RGBA, b"\x00\x30\xbf\x48" if seq else b"\x00\xff\x00\x00"))


def c_privatestate(tr, cs, x, d):
    """<privatestate> (spec §5.8, code, not on audio transitions) from parms/private/stateinfokey.
    oracle-observed, spec gap: the key holds a messageable whose info dictionary's `sequenceData`
    blob is written in the private encoding, as CDATA."""
    D = tr.doc
    if D.num(D.get(d, "subtype")) == 12:
        return
    node = cs.get("stateinfokey")
    if node is None or isinstance(node, list):
        return
    data = None
    for ch in node.children:
        if ch.role == "member" and D.is_dict(ch):
            blob = D.get(ch, "sequenceData")
            if blob is not None and D.tc(blob) == T_BLOB:
                data = blob.payload if blob.kind == "DATA07" else D.refs[blob.value][1]
    if isinstance(data, (bytes, bytearray)):
        x.add(X("privatestate", private_encode(data), cdata=True))


def c_mixedratesoffset(tr, cs, x, d):
    """<mixedratesoffset> (spec §5.6, code: the computed offset of a mixed-rate item, only when
    non-zero).  oracle-observed, spec gap: the item's stored `mixedRatesOffset`, a whole number."""
    n = tr.doc.num(tr.doc.get(d, "mixedRatesOffset")) if d is not None else None
    if n:
        x.add(X("mixedratesoffset", fmt_whole(n)))


def c_timeremap(tr, cs, x, d):
    """The Time Remap <filter> (spec §6, code; parameter contents H): the last child of an item whose
    speed is variable, reversed or other than 100 %."""
    if d is None:
        return
    sp = _speed_model(tr, d)
    if sp is None:
        return
    segs = sp["segs"]
    if not sp["variable"] and not sp["reverse"] and segs[0]["used"] == segs[0]["outd"]:
        return
    x.add(_timeremap_filter(tr, cs, d, sp))


def _payload_dict(tr, v):
    """The items of a payload dictionary (the spec reader's raw value), following back-references."""
    if isinstance(v, tuple) and len(v) == 3 and v[0] == "ref":
        r = tr.doc.refs[v[1]] if 0 <= v[1] < len(tr.doc.refs) else None
        v = r[1] if r is not None else None
    return v.get("items") if isinstance(v, dict) else None


def _payload_obj(tr, v):
    """The members of a payload object, following a back-reference to the object's node."""
    if isinstance(v, tuple) and len(v) == 3 and v[0] == "ref":
        n = tr.doc.sd.slot_nodes.get(v[1])
        v = n.payload if n is not None else None
    if isinstance(v, tuple) and len(v) == 4 and v[0] == "obj":
        return v[3]
    return None


def _speed_model(tr, d):
    """The item's speed as segments (spec §6 Time Remap).  New-style items carry an FCSpeedData
    object in speedDataWrapper/speedData (input duration, flags and bezier handles, then one
    FCSpeedSegment per segment: inputFirst, inputUsed, outputDuration, anchorOffset, reverse); older
    items a `speed` factor, which FCP 7 converts on loading (oracle-observed, spec gap: the media
    duration stands for the input, the item's duration for the output, `ratefx` for frame blending;
    an approximation, the conversion also moves some items' timing by a frame)."""
    D = tr.doc
    sdw = D.get(d, "speedDataWrapper")
    sd = D.get(sdw, "speedData") if sdw is not None else None
    if sd is not None and sd.kind == "T20":
        m = _payload_obj(tr, sd.payload) or {}
        a = _payload_dict(tr, m.get("a")) or {}
        raw = _payload_dict(tr, m.get("b")) or []
        segs = []
        for item in raw if isinstance(raw, list) else []:
            sm = _payload_obj(tr, (_payload_dict(tr, item) or {}).get(b"segment"))
            sg = _payload_dict(tr, sm.get("d")) if sm is not None else None
            if sg is None or b"inputUsed" not in sg or not sg.get(b"outputDuration"):
                return None
            segs.append({"first": sg.get(b"inputFirst"), "used": float(sg[b"inputUsed"]),
                         "outd": float(sg[b"outputDuration"]), "anchor": sg.get(b"anchorOffset"),
                         "reverse": b"reverse" in sg})
        if not segs:
            return None
        bez = {}
        for k in (b"inBez", b"outBez"):
            bm = _payload_obj(tr, a.get(k))
            bd = _payload_dict(tr, bm.get("d")) if bm is not None else None
            if bd is not None:
                bez[k] = (bd.get(b"length"), bd.get(b"angle"))
        return {"in_dur": a.get(b"inputDuration"), "segs": segs, "reverse": segs[0]["reverse"],
                "blend": b"blendingOff" not in a, "variable": len(segs) > 1 or bool(bez),
                "inbez": bez.get(b"inBez"), "outbez": bez.get(b"outBez"), "factor": None}
    speed = D.num(D.get(d, "speed"))
    if speed is None:
        return None
    f = D.get(d, "file")
    media = D.num(D.get(f, "duration")) if f is not None else None
    outd = _old_speed_output(D, d) or D.num(D.get(d, "duration"))
    if not media or not outd:
        return None
    rev = bool(D.num(D.get(d, "reverse")))
    if speed == 1.0 and not rev and not D.num(D.get(d, "variablespeed")):
        return None
    return {"in_dur": media, "segs": [{"first": None, "used": float(media), "outd": float(outd), "anchor": None,
                                       "reverse": rev}],
            "reverse": rev, "blend": bool(D.num(D.get(d, "ratefx"))),
            "variable": bool(D.num(D.get(d, "variablespeed"))), "inbez": None, "outbez": None, "factor": speed}


def _old_speed_output(D, d):
    """The output duration FCP 7 gives a pre-FCP 7 constant speed on loading.  oracle-observed, spec
    gap (MUSEO, 070509): (media duration - 1) / speed + 1, but never short of the item's out point,
    when that is a whole number; None otherwise (the stored duration stands)."""
    if D.get(d, "speedDataWrapper") is not None or D.num(D.get(d, "reverse")):
        return None
    speed = D.num(D.get(d, "speed"))
    f = D.get(d, "file")
    media = D.num(D.get(f, "duration")) if f is not None else None
    if not speed or speed == 1.0 or not media:
        return None
    comp = (media - 1) / speed + 1
    if abs(comp - round(comp)) > 1e-6:
        return None
    out = D.num(D.get(d, "out"))
    return float(max(round(comp), out if out is not None else 0))


def _converted_speed_duration(tr, cs, d):
    """Park the converted duration of a pre-FCP 7 speed (see _old_speed_output) for <duration>."""
    outd = _old_speed_output(tr.doc, d)
    dur = cs.slots.get("duration")
    if outd is not None and dur is not None and not isinstance(dur, list) and tr.doc.num(dur) != outd:
        n = G.Node(-2, dur.off, "F64", "value")
        n.payload = n.value = outd
        cs.slots["duration"] = n


def _tr_param(pid, vmin=None, vmax=None, value=None):
    p = X("parameter")
    p.add(X("parameterid", pid))
    p.add(X("name", pid))
    if vmin is not None:
        p.add(X("valuemin", vmin))
        p.add(X("valuemax", vmax))
    if value is not None:
        p.add(X("value", value))
    return p


def _rate(sg):
    """A segment's rate, input frames per output frame: (inputUsed - 1) / (outputDuration - 1),
    divided in double precision and held in single precision.  The spec (§6) truncates the speed
    percentage from this single-precision ratio; oracle-observed, spec gap: the graph maps output
    frames to input frames with the same float32 rate (LesInsectesGeants_V8, 20120903B01_MVI_6656
    at its in point 90: 90 * f32(481 / 240) + anchorOffset 1.7875 is written 182.162, where the
    double ratio gives 182.163)."""
    return _f32((sg["used"] - 1) / (sg["outd"] - 1)) if sg["outd"] != 1 else 1.0


def _timeremap_filter(tr, cs, d, sp):
    """oracle-observed, spec gap (contents H in spec §6): parameters variablespeed, mappedduration (a
    zero timecode), speed (the truncated percentage of the rate, see _rate, of the segment at the
    item's in point), reverse, frameblending and graphdict.
    The graph's keyframes sit at the start, at each boundary between segments (segment k ends at
    output frame B(k-1) + outputDuration - 1 on input frame inputFirst(k+1); real keyframes), at the
    item's in and out points (virtual keyframes unless on a boundary) and at the end (B + the last
    outputDuration, valued inputFirst + inputUsed + anchorOffset).  Within a segment the input is
    inputFirst + (t - B) * rate + anchorOffset, in double precision on the float32 rate; a reversed
    single segment runs inputUsed - t * rate + anchorOffset, its start at inputUsed + 1 and its end
    at 1.  Values are written as float32."""
    D = tr.doc
    media = _media_of(cs) or "video"
    f = X("filter")
    e = f.add(X("effect"))
    for k, t in (("name", "Time Remap"), ("effectid", "timeremap"), ("effectcategory", "motion"),
                 ("effecttype", "motion"), ("mediatype", media)):
        e.add(X(k, t))
    e.add(_tr_param("variablespeed", "0", "1", "1" if sp["variable"] else "0"))
    md = e.add(_tr_param("mappedduration"))
    tc = md.add(X("value")).add(X("timecode"))
    tc.add(X("rate")).add(X("timebase", "0"))
    tc.add(X("string", "0"))
    tc.add(X("frame", "0"))
    tc.add(X("displayformat", "NDF"))
    segs = sp["segs"]
    rev = sp["reverse"] and len(segs) == 1
    # segment starts on the output axis, the end, and each segment's input origin
    starts = [0.0]
    for sg in segs[:-1]:
        starts.append(starts[-1] + sg["outd"] - 1)
    end_t = starts[-1] + segs[-1]["outd"]
    firsts = []
    for k, sg in enumerate(segs):
        if sg["first"] is not None:
            firsts.append(float(sg["first"]))
        elif k == 0:
            firsts.append(0.0)
        else:
            firsts.append(firsts[-1] + segs[k - 1]["used"] - 1)
    i_in = D.num(D.get(d, "in"))
    i_out = D.num(D.get(d, "out"))
    i_in = 0.0 if i_in is None or i_in < 0 else float(i_in)
    i_out = end_t if i_out is None or i_out < 0 else float(i_out)

    def seg_at(t):
        k = 0
        while k + 1 < len(segs) and starts[k + 1] <= t:
            k += 1
        return k

    def at(t):
        k = seg_at(t)
        sg = segs[k]
        a = sg["anchor"] or 0.0
        if rev:
            return sg["used"] - t * _rate(sg) + a + firsts[0]
        return firsts[k] + (t - starts[k]) * _rate(sg) + a

    anchor0 = segs[0]["anchor"]
    a0 = anchor0 or 0.0
    a_end = segs[-1]["anchor"] or 0.0
    if rev:
        start_v = segs[0]["used"] + 1 + a0 + firsts[0]
        end_v = 1 + a0 + firsts[0]
    else:
        start_v = firsts[0] + a0
        end_v = firsts[-1] + segs[-1]["used"] + a_end
    seg_in = segs[seg_at(i_in)]
    pct = sp["factor"] * 100 if sp.get("factor") is not None else 100 * _rate(seg_in)
    e.add(_tr_param("speed", "-10000", "10000", str(int(pct))))
    e.add(_tr_param("reverse", value=fmt_bool(sp["reverse"])))
    e.add(_tr_param("frameblending", value=fmt_bool(sp["blend"])))
    in_dur = sp["in_dur"] if sp["in_dur"] is not None else firsts[-1] + segs[-1]["used"]
    g = e.add(_tr_param("graphdict", "0", fmt_g(in_dur - 1)))

    bounds = {starts[k]: firsts[k] for k in range(1, len(segs))}
    kfs = {}                                    # when -> [value, flags, is_start, bez]
    kfs[0.0] = [start_v, ["speedkfin"] if i_in == 0 else ["speedkfstart", "speedvirtualkf"], True,
                "out" if (i_in == 0 and sp["inbez"]) else None]
    for t, v in bounds.items():
        kfs[t] = [v, [], False, None]
    if i_in != 0:
        if i_in in bounds:
            kfs[i_in][1] = ["speedkfin"]
        else:
            kfs[i_in] = [at(i_in), ["speedkfin", "speedvirtualkf"], False, "out" if sp["inbez"] else None]
    if i_out != end_t:
        if i_out in bounds:
            kfs[i_out][1] = ["speedkfout"]
        else:
            v_out, fl = at(i_out), ["speedkfout", "speedvirtualkf"]
            if not rev and v_out > in_dur - 1:
                # oracle-observed: an out point mapping past the last media frame is pinned to it and
                # is then a real keyframe (EPK 0006UU: 1736.12 written as 1731).  oracle-observed,
                # spec gap: the test is on the unrounded mapping, so a float32 rate a hair above the
                # exact ratio pins an out point that maps exactly onto the last frame (PAD_050412
                # H001_C024_10080L: 155 * f32(773 / 155) = 773.0000019 > 773, written 773 without
                # <speedvirtualkf>)
                v_out, fl = in_dur - 1, ["speedkfout"]
            kfs[i_out] = [v_out, fl, False, "in" if sp["outbez"] else None]
        kfs[end_t] = [end_v, ["speedkfend", "speedvirtualkf"], False, None]
    else:
        kfs[end_t] = [end_v, ["speedkfout", "speedvirtualkf"], False, "in" if sp["outbez"] else None]
    for when in sorted(kfs):
        val, flags, is_start, bez = kfs[when]
        k = g.add(X("keyframe"))
        k.add(X("when", fmt_g(when)))
        k.add(X("value", fmt_g(_f32(val))))     # oracle-observed: keyframe values are float32
        for fl in flags:
            k.add(X(fl, "TRUE"))
        if is_start and anchor0 is not None:
            k.add(X("anchorOffset", fmt_g(anchor0)))
        if bez is not None:
            length, angle = sp["outbez"] if bez == "in" else sp["inbez"]
            b = k.add(X("inbez" if bez == "in" else "outbez"))
            b.add(X("horiz", fmt_g(length)))
            b.add(X("vert", fmt_g(angle)))
    g.add(X("interpolation")).add(X("name", "FCPCurve"))
    if rev:
        v = (segs[0]["used"] - 1 + a0 + firsts[0]) if i_in == 0 else at(i_in) - 1
    else:
        v = kfs[i_in][0] if i_in in kfs else at(i_in)
    g.add(X("value", fmt_g(_f32(v))))
    return f


def _f32(x):
    """x rounded to the nearest float32."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


def c_motion_timeremap(tr, cs, x, d):
    D = tr.doc
    s = cs.parent
    while s is not None and (s.rule is None or s.rule.kind != "E"):
        s = s.parent
    item = s.dict if s is not None else None
    if item is None or D.num(D.get(item, "type")) != 2:
        return
    e = x.add(X("effect"))
    for k, t in (("name", "Time Remap"), ("effectid", "timeremap"), ("effectcategory", "motion"),
                 ("effecttype", "motion"), ("mediatype", _media_of(s) or "video")):
        e.add(X(k, t))
    for k, pdict in D.entries(d):
        if k not in ("variablespeed", "mappedduration", "speed", "reverse", "frameblending"):
            continue
        pdict = D.deref(pdict)
        p = e.add(X("parameter"))
        p.add(X("parameterid", k))
        p.add(X("name", k))
        lo, hi = _number_text(D, D.get(pdict, "min")), _number_text(D, D.get(pdict, "max"))
        if lo is not None and hi is not None:
            p.add(X("valuemin", lo))
            p.add(X("valuemax", hi))
        val = D.get(pdict, "value")
        if val is not None and val.kind == "T16TIME" and isinstance(val.payload, tuple):
            frames, base = val.payload[0], val.payload[1]
            tc = p.add(X("value")).add(X("timecode"))
            tc.add(X("rate")).add(X("timebase", str(int(base))))
            tc.add(X("string", _tc_text(frames, base, False) if base else "0"))
            tc.add(X("frame", fmt_whole(frames)))
            tc.add(X("displayformat", "NDF"))


def c_itemhistory(tr, cs, x, d):
    """<itemhistory> (spec §5.11): one <uuid> per entry of the item's itemHistory array; dropped when
    empty.  The run-time refresh of the list (spec §1.1) is not reproducible (spec gap)."""
    if not tr.include_history or d is None:
        return
    D = tr.doc
    arr = D.get(d, "itemHistory")
    if arr is None or not D.is_dict(arr):
        return
    us = [D.uuid(D.deref(e)) for e in D.elements(arr)]
    us = [u for u in us if u]
    if us:
        h = x.add(X("itemhistory"))
        for u in us:
            h.add(X("uuid", u))


def c_label(tr, cs, x, d):
    # spec §5.11: the name the exporting application's preferences give label colour labelColor
    n = tr.doc.num(cs.get("labelColor"))
    w = LABEL_NAMES.get(int(n)) if n is not None else None
    if w:
        x.add(X("label", w))


# oracle-observed, spec gap: the label names of the exporting machine's preferences (FCP 7 defaults)
LABEL_NAMES = {1: "Good Take", 2: "Best Take", 3: "Alternate Shots", 4: "Interviews", 5: "B Roll"}


def c_sourcetrack(tr, cs, x, d):
    """<sourcetrack> (spec §5.11): video: the media type and layerIndex + 1; audio: the media type
    and channelIndex."""
    media = _media_of(cs.parent) or "video"
    x.add(X("mediatype", media))
    if media == "video":
        n = tr.doc.num(cs.get("layerIndex"))
        if n is not None:
            x.add(X("trackindex", str(int(n) + 1)))
    else:
        n = tr.doc.num(cs.get("channelIndex"))
        if n is not None:
            x.add(X("trackindex", str(int(n))))


def c_alignment(tr, cs, x, d):
    """<alignment> (spec §5.7) from `mode`, with the -black adjustment from the neighbours in the
    track's clip array."""
    D = tr.doc
    m = D.num(cs.get("mode")) if cs.get("mode") is not None else D.num(D.get(d, "mode"))
    words = {1: "center", 2: "start", 3: "end", 4: "start-black", 5: "end-black"}
    w = words.get(int(m)) if m is not None else None
    if w is None:
        return
    arr, i = cs.arr, cs.idx
    els = [D.deref(e) for e in D.elements(arr)] if arr is not None else []
    if w == "start":
        # oracle-observed, spec error: a "start" transition with no item before it stays "start"
        # (476 traced); only a preceding item whose end is not -1 makes it "start-black"
        prev = els[i - 1] if i is not None and i > 0 else None
        if prev is not None and D.num(D.get(prev, "end")) != -1:
            w = "start-black"
    elif w == "end":
        nxt = els[i + 1] if i is not None and i + 1 < len(els) else None
        if nxt is None or D.num(D.get(nxt, "start")) != -1:
            w = "end-black"
    x.add(X("alignment", w))


def _tc_text(frame, base, df):
    """Timecode text of a segment start at a frame base (spec §5.10).  oracle-observed, spec gap:
    for drop frame the stored number counts timecode labels, so the text is that count in hours,
    minutes, seconds and frames at the nominal base with `;` before the frames field."""
    base = int(base) if base else 30
    f = int(round(frame))
    neg = f < 0
    f = abs(f)
    fr = f % base
    s = f // base
    txt = "%02d:%02d:%02d%s%02d" % (s // 3600, (s // 60) % 60, s % 60, ";" if df else ":", fr)
    return ("-" if neg else "") + txt


def _df_frame(frame, base):
    """The drop-frame conversion of `<frame>` (spec §5.10).  oracle-observed, spec gap: the stored
    label count less the labels drop frame skips (2 per minute at 30, 4 at 60, none in every tenth
    minute): 01:00:00;00 is frame 107892."""
    base = int(base)
    drop = 2 * (base // 30)
    f = int(round(frame))
    minutes = f // (base * 60)
    return f - drop * (minutes - minutes // 10)


def _df_ok(base):
    return int(base) in (30, 60) if base else False


def c_tc_string(tr, cs, x, d):
    D = tr.doc
    seg = D.num(cs.get("segStart"))
    base = D.num(cs.get("framebase"))
    if seg is None or base is None:
        return
    dfm = D.num(cs.get("displayFormat"))
    df = dfm in (1, 7) and _df_ok(base)
    x.add(X("string", _tc_text(seg, base, df)))


def c_tc_frame(tr, cs, x, d):
    D = tr.doc
    seg = D.num(cs.get("segStart"))
    if seg is None:
        return
    base = D.num(cs.get("framebase"))
    if D.num(cs.get("displayFormat")) in (1, 7) and _df_ok(base):
        seg = _df_frame(seg, base)
    x.add(X("frame", fmt_whole(seg)))


def _level_param(tr, cs, pname, pid, negate=False):
    """The single <parameter> of Audio Levels / Audio Pan (spec §6): name first, then id, valuemin,
    valuemax, keyframes, interpolation, value."""
    D = tr.doc
    p = X("parameter")
    p.add(X("name", pname))
    p.add(X("parameterid", pid))
    c_number(tr, cs, p, None, "min", "valuemin")
    c_number(tr, cs, p, None, "max", "valuemax")
    kfs = cs.get("keyframe")
    if isinstance(kfs, list) and kfs:
        for k in kfs:
            p.add(k)
        p.add(X("interpolation")).add(X("name", "FCPCurve"))
    v = cs.get("value")
    if v is not None and not isinstance(v, list):
        n = D.num(v)
        if n is not None:
            p.add(X("value", fmt_g(-n if negate else n)))
    return p


def c_audio_filter(tr, cs, x, d, ename, eid, pname, pid):
    e = x.add(X("effect"))
    e.add(X("name", ename))
    e.add(X("effectid", eid))
    e.add(X("effectcategory", eid))
    e.add(X("effecttype", eid))
    e.add(X("mediatype", "audio"))
    neg = False
    if pid == "pan":
        inv = cs.get("panInvert")
        neg = inv is not None and not isinstance(inv, list) and bool(tr.doc.num(inv))
    e.add(_level_param(tr, cs, pname, pid, negate=neg))


def c_master_level(tr, cs, x, d):
    """The master-level Audio Levels <filter> of <audio> (spec §6): valuemin 0, valuemax 3.98109,
    value from masterLevel; no keyframes, no <enabled>."""
    n = tr.doc.num(cs.get("masterLevel"))
    if n is None:
        return
    f = x.add(X("filter"))
    e = f.add(X("effect"))
    for k, t in (("name", "Audio Levels"), ("effectid", "audiolevels"), ("effectcategory", "audiolevels"),
                 ("effecttype", "audiolevels"), ("mediatype", "audio")):
        e.add(X(k, t))
    p = e.add(X("parameter"))
    p.add(X("name", "Level"))
    p.add(X("parameterid", "level"))
    p.add(X("valuemin", "0"))
    p.add(X("valuemax", "3.98109"))
    p.add(X("value", fmt_g(n)))


def c_outputs(tr, cs, x, d):
    """<outputs> from seqProps/audioGroup/outputs (spec §5.4, H).  oracle-observed, spec gap: one
    <group> per run of outputs entries, a `grouping` entry joining the next one; numchannels the
    run's length, downmix from the run's first entry, channels numbered across the groups."""
    D = tr.doc
    els = [D.deref(e) for e in D.elements(d)] if d is not None else []
    groups = []
    cur = []
    for e in els:
        cur.append(e)
        g = D.num(D.get(e, "grouping"))
        if not g or len(cur) >= 2:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    ch = 1
    for gi, g in enumerate(groups):
        gx = x.add(X("group"))
        gx.add(X("index", str(gi + 1)))
        gx.add(X("numchannels", str(len(g))))
        dm = DOWNMIX.get(D.num(D.get(g[0], "downmix")))
        if dm is not None:
            gx.add(X("downmix", dm))
        for _ in g:
            gx.add(X("channel")).add(X("index", str(ch)))
            ch += 1


def c_link(tr, cs, x, d):
    """<link> per element of the item's `link` array of item specs (spec §8): the linked item's id
    found through the nearest enclosing link context, the media type, track and clip index, and the
    group index when non-zero."""
    D = tr.doc
    arr = D.get(d, "link") if d is not None else None
    if arr is None or not D.is_dict(arr):
        return
    s = cs.find("linkctx")
    ctx = s.linkctx if s is not None else None
    for el in D.elements(arr):
        if el.kind != "STRUCT1E" or not isinstance(el.payload, tuple):
            continue
        mt, grp, ti, ci = el.payload
        lx = x.add(X("link"))
        item = resolve_spec(tr, ctx, mt, ti, ci) if ctx is not None else None
        if item is not None:
            lx.add(X("linkclipref", tr.ids.assign(item, tr.base(item))))
        lx.add(X("mediatype", "video" if mt == 1 else "audio"))
        lx.add(X("trackindex", str(ti)))
        lx.add(X("clipindex", str(ci)))
        if grp:
            lx.add(X("groupindex", str(grp)))


def c_file(tr, cs, x, d):
    """<file> (spec §7) from the item's `file` record: in full the first time the record is met,
    `<file id="..."/>` afterwards."""
    f = tr.doc.get(d, "file") if d is not None else None
    if f is None or f.kind != "T0C":
        return
    x.add(file_element(tr, f, item_name=tr.doc.raw_text(tr.doc.get(d, "name"))))


def _not_modelled(tr, cs, x, d, *args):
    """Code behaviours of the catalogue this emitter does not model, for want of a corpus example to
    check them against: <multiclip> of clip items and generators (spec §5.6, §5.8, §5.11) and the
    take, shot and scene notes of <logginginfo> from a media file's film metadata (§5.11).  They
    write nothing."""


CODE_FN = {name[2:]: fn for name, fn in list(globals().items()) if name.startswith("c_") and callable(fn)}
CODE_FN.update({"multiclip": _not_modelled, "generator_multiclip": _not_modelled, "filmnotes": _not_modelled})


# ---------------------------------------------------------------------------------------------
# media files (spec §7)
# ---------------------------------------------------------------------------------------------

def _filespec(f):
    for c in f.children:
        if c.kind == "FILESPEC":
            return c.payload
    return None


QT_METADATA_TYPES = {0: "binary", 1: "UTF8", 21: "signed", 22: "unsigned", 23: "float32", 24: "float64"}


def _metadata(tr, holder, out):
    """<metadata> per QuickTime metadata item of a file or of one of its tracks (spec §7 item 6, not
    analysed there).  oracle-observed, spec gap: storage `QuickTime`, the item's key, size, type word
    and value; binary values in the private encoding inside CDATA."""
    D = tr.doc
    md = D.get(holder, "qtMetadata")
    if md is None or not D.is_dict(md):
        return
    for _k, arr in D.entries(md):
        arr = D.deref(arr)
        if arr is None or not D.is_dict(arr):
            continue
        for e in D.elements(arr):
            e = D.deref(e)
            if e is None or not D.is_dict(e):
                continue
            m = out.add(X("metadata"))
            m.add(X("storage", "QuickTime"))
            key = D.text(D.get(e, "keyName"))
            if key is None:
                key = D.text(D.get(e, "name"))
            if key is not None:
                m.add(X("key", key))
            n = D.num(D.get(e, "valueSize"))
            if n is not None:
                m.add(X("size", str(int(n))))
            tcode = D.num(D.get(e, "typeCode"))
            tname = QT_METADATA_TYPES.get(tcode)
            if tname is not None:
                m.add(X("type", tname))
            v = D.get(e, "value")
            vt = D.tc(v)
            if vt in (T_STR, T_CSTR):
                m.add(X("value", D.text(v)))
            elif vt == T_BLOB:
                raw = v.payload if v.kind == "DATA07" else D.refs[v.value][1]
                m.add(X("value", private_encode(raw), cdata=True))
            elif vt in (T_F32, T_F64):
                m.add(X("value", fmt_g(v.payload)))
            elif vt in (T_INT, T_UINT):
                m.add(X("value", str(int(D.num(v)))))


def _file_media(tr, f, fx, generated=False):
    D = tr.doc
    vids = D.get(f, "video")
    auds = D.get(f, "audio")
    vels = [D.deref(e) for e in D.elements(vids)] if vids is not None and D.is_dict(vids) else []
    aels = [D.deref(e) for e in D.elements(auds)] if auds is not None and D.is_dict(auds) else []
    if not vels and not aels:
        return
    m = fx.add(X("media"))
    for li, v in enumerate(vels):
        vx = m.add(X("video"))
        dur = D.num(D.get(v, "duration"))
        if dur is None:
            dur = D.num(D.get(f, "duration"))
        if dur is not None:
            vx.add(X("duration", fmt_whole(dur)))
        if D.get(v, "still") is not None and not generated:   # oracle-observed: not for generator media
            vx.add(X("stillframe", "TRUE"))
        at = ALPHATYPE.get(D.num(D.get(v, "alphatype")))
        if at is not None:
            vx.add(X("alphatype", at))
        if len(vels) > 1:
            vx.add(X("layerindex", str(li)))
        sc = X("samplecharacteristics")
        for k in ("width", "height"):
            n = D.num(D.get(v, k))
            if n is not None:
                sc.add(X(k, fmt_whole(n)))
        if sc.children:
            vx.add(sc)
        _metadata(tr, v, vx)
    # oracle-observed, spec gap (spec §7 item 8 says only "skipping channels the channel map disables
    # (H)"): with an audioChannelMap, each file audio track takes the next `channels` entries of the
    # map; a track whose entries are all disabled is skipped; <layout> is the entries' layout tag and
    # each enabled entry gives an <audiochannel> numbered by its position in the map.  Without a map
    # no <layout> and no <audiochannel> are written.
    cmap = D.path(f, "audioChannelMap", "array")
    centries = [D.deref(e) for e in D.elements(cmap)] if cmap is not None and D.is_dict(cmap) else None
    pos = 0
    for a in aels:
        nch = D.num(D.get(a, "channels"))
        chans = []
        if centries is not None and nch is not None:
            for k in range(int(nch)):
                e = centries[pos + k] if pos + k < len(centries) else None
                if e is not None and D.num(D.get(e, "enabled")):
                    chans.append((pos + k + 1, e))
            pos += int(nch)
            if not chans:
                continue
        ax = m.add(X("audio"))
        sc = X("samplecharacteristics")
        n = D.num(D.get(a, "sampleRate"))
        if n is not None:
            sc.add(X("samplerate", fmt_whole(n)))
        n = D.num(D.get(a, "depth"))
        if n is not None:
            sc.add(X("depth", fmt_whole(n)))
        if sc.children:
            ax.add(sc)
        if nch is not None:
            ax.add(X("channelcount", fmt_whole(nch)))
        if chans:
            w = CHANNEL_LAYOUTS.get(D.num(D.get(chans[0][1], "layout")))
            if w is not None:
                ax.add(X("layout", w))
            for idx, e in chans:
                ac = ax.add(X("audiochannel"))
                ac.add(X("sourcechannel", str(idx)))
                lab = CHANNEL_LABELS.get(D.num(D.get(e, "label")))
                if lab is not None:
                    ac.add(X("channellabel", lab))
        _metadata(tr, a, ax)


# oracle-observed, spec gap: CoreAudio layout tags and channel labels as words
CHANNEL_LAYOUTS = {6553601: "mono", 6619138: "stereo"}
CHANNEL_LABELS = {1: "left", 2: "right", 400: "discrete"}


def _file_timecodes(tr, f, fx):
    D = tr.doc
    tracks = D.path(f, "tcData", "tcTracks")
    if tracks is None or not D.is_dict(tracks):
        return
    for t in [D.deref(e) for e in D.elements(tracks)]:
        segs = D.get(t, "tcSegments")
        sel = [D.deref(e) for e in D.elements(segs)] if segs is not None and D.is_dict(segs) else []
        seg = sel[0] if sel else None
        start = D.num(D.get(seg, "segStart")) if seg is not None else None
        base = D.num(D.get(t, "framebase"))
        if start is None or base is None:
            continue
        tx = fx.add(X("timecode"))
        r = tx.add(X("rate"))
        r.add(X("timebase", fmt_whole(base)))
        # oracle-observed, spec gap ("<ntsc>TRUE</ntsc> only for NTSC rates"): written when the file's
        # rate is 29.97 (NTSC, base 30) and the timecode counts 30 frames a second; never for a 24 or
        # 60 frame timecode, nor for a 30 frame timecode of a 23.98 file
        if D.num(D.get(f, "ntscrate")) and D.num(D.get(f, "framebase")) == 30 and int(base) == 30:
            r.add(X("ntsc", "TRUE"))
        dfm = D.num(D.get(seg, "displayFormat"))
        df = dfm in (1, 7) and _df_ok(base)
        tx.add(X("string", _tc_text(start, base, df)))
        tx.add(X("frame", fmt_whole(_df_frame(start, base) if df else start)))
        tx.add(X("displayformat", "DF" if dfm in (1, 7) else "NDF"))
        src = TRACKTYPE.get(D.num(D.get(t, "trackType")))
        if src is not None:
            tx.add(X("source", src))
        reel = D.text(D.get(t, "reel"))
        if reel:
            tx.add(X("reel")).add(X("name", reel))


def file_element(tr, f, item_name=None):
    """<file> for a file record (spec §7): name, pathurl (case b; generator media: mediaSource), rate,
    duration, a still's width and height, metadata, timecodes and media, in that order; a record
    written before is `<file id="..."/>` (spec §3)."""
    D = tr.doc
    if f in tr.ids.written:
        return X("file", id=tr.ids.get(f))
    rec = _filespec(f)
    els = record_elements(rec) if rec is not None else []
    generated = not els and not (rec or {}).get("vol")
    fname = to_text(els[-1]) if els else None
    if generated:
        # oracle-observed, spec gap: generator media (a record without volume or path) is named by
        # the application's generator name for its reader, known here for the generators the corpus
        # uses; otherwise the item's name stands in
        reader = D.text(D.get(f, "reader"))
        fname = GENERATOR_NAMES.get(reader) or (to_text(item_name) if item_name else None)
    base = file_id_base(fname) if fname else D.raw_text(D.get(f, "reader"))
    ident = tr.ids.assign(f, base) if base else None
    tr.ids.written.add(f)
    fx = X("file", id=ident)
    if fname:
        fx.add(X("name", fname))
    url = offline_pathurl(rec.get("vol", b""), els) if rec is not None else None
    if url:
        fx.add(X("pathurl", url))
    elif generated:
        # spec §7 item 2 (H: mediaSource); oracle-observed, spec gap: the reader's name
        ms = D.text(D.get(f, "mediaSource")) or D.text(D.get(f, "reader"))
        if ms:
            fx.add(X("mediaSource", ms))
    fb = D.num(D.get(f, "framebase"))
    if fb is not None:
        r = fx.add(X("rate"))
        r.add(X("timebase", fmt_whole(fb)))
        if D.num(D.get(f, "ntscrate")):
            r.add(X("ntsc", "TRUE"))
    dur = D.num(D.get(f, "duration"))
    if dur is not None:
        fx.add(X("duration", fmt_whole(dur)))
    vids = D.get(f, "video")
    v0 = D.deref(D.elements(vids)[0]) if vids is not None and D.is_dict(vids) and D.elements(vids) else None
    if v0 is not None and D.get(v0, "still") is not None and not generated:   # spec §7 item 5: stills
        for k in ("width", "height"):
            n = D.num(D.get(v0, k))
            if n is None:
                n = D.num(D.get(f, k))
            if n is not None:
                fx.add(X(k, fmt_whole(n)))
    _metadata(tr, f, fx)
    _file_timecodes(tr, f, fx)
    _file_media(tr, f, fx, generated)
    return fx


# oracle-observed, spec gap: FCP 7's display names of its built-in generator media, by reader
GENERATOR_NAMES = {"Slug": "Slug", "BarsAndTone": "Bars and Tone (NTSC)",
                   "BarsAndToneHD1080i60": "Bars and Tone (HD 1080i60)"}


def master_clip(tr, u):
    """The master clip dictionary with UUID u, from the project's masterClips/masterClipsTable."""
    if tr.masters is None:
        tr.masters = {}
        D = tr.doc
        table = D.path(D.sd.root, "masterClips", "masterClipsTable")
        if table is not None and D.is_dict(table):
            for e in D.elements(table):
                e = D.deref(e)
                uid = D.uuid(D.get(e, "uniqueID"))
                mc = D.get(e, "masterClips")
                if uid and mc is not None and D.is_dict(mc):
                    tr.masters.setdefault(uid, mc)
    return tr.masters.get(u)


def resolve_spec(tr, ctx, mt, ti, ci):
    """The item an item spec names in a link context (spec §8): media type (1 video, 2 audio),
    1-based track and clip index."""
    D = tr.doc
    ch = D.path(ctx, "media", "vidm" if mt == 1 else "audm")
    tracks = D.get(ch, "track") if ch is not None else None
    if tracks is None or not D.is_dict(tracks):
        return None
    tels = D.elements(tracks)
    if not 1 <= ti <= len(tels):
        return None
    clips = D.get(D.deref(tels[ti - 1]), "clip")
    if clips is None or not D.is_dict(clips):
        return None
    cels = D.elements(clips)
    if not 1 <= ci <= len(cels):
        return None
    return D.deref(cels[ci - 1])



# ---------------------------------------------------------------------------------------------
# export roots (spec §1.2)
# ---------------------------------------------------------------------------------------------

PROJECT = Rule("project", "E", None, name="project", children=[CODE("project_name"), EL("children")])


def c_project_name(tr, cs, x, d):
    nm = cs.get("#project_name")
    if nm is not None:
        x.add(X("name", nm))
    else:
        tr.write_spec(VAL("name", cond=REQUIRED), cs, x, d)


CODE_FN["project_name"] = c_project_name


def load(path):
    """The spec reader's document for a project file (never the walker)."""
    sd = keyg_specdoc.SpecDoc(path)
    if sd.reader_error is not None:
        raise ExportError("spec reader: %s" % sd.reader_error)
    return Doc(sd)


def project_element(doc, project_name=None, **kw):
    """<project> (spec §5.1).  `project_name`, when given, stands for the in-memory project name:
    oracle-observed, spec gap: FCP writes the open document's name (the project file's name without
    `.fcp`), not the root dictionary's stored `name`."""
    tr = Translator(doc, **kw)
    root = doc.sd.root
    if doc.num(doc.get(root, "subtype")) != 3:
        raise ExportError("the root item is not a project")
    top = Scope(None, None, None)
    if project_name is not None:
        top.slots["#project_name"] = project_name
    return tr.build(PROJECT, None, root, top, on_spot=True)


def browser_items(doc):
    """Every browser item in document order: (dictionary, depth) through the project's and bins'
    children arrays."""
    out = []

    def walk(arr, depth):
        for e in doc.elements(arr):
            e = doc.deref(e)
            if e is None or not doc.is_dict(e):
                continue
            out.append((e, depth))
            if doc.num(doc.get(e, "subtype")) == 3:
                ch = doc.get(e, "children")
                if ch is not None and doc.is_dict(ch):
                    walk(ch, depth + 1)

    ch = doc.get(doc.sd.root, "children")
    if ch is not None:
        walk(ch, 0)
    return out


def find_item(doc, which):
    """A browser item (not a bin) by index into browser_items' sequences and clips, UUID or name."""
    items = [e for e, _ in browser_items(doc) if doc.num(doc.get(e, "subtype")) != 3]
    if isinstance(which, int):
        return items[which]
    for e in items:
        if doc.uuid(doc.get(e, "UUID")) == which:
            return e
    for e in items:
        if doc.name_of(e) == which:
            return e
    raise KeyError(which)


def item_elements(doc, item, **kw):
    """A selection of one item (spec §1.2): translated like an element of a children array, under
    <xmeml> directly, followed by the synthetic "Master Clips" bin holding the master clips the
    selection names (its <masterclipid> targets) that are not in the selection, each written as a
    browser <clip>.  FCP's selection exports always carry this bin (verified on three real exports:
    last top-level element, <name> and <children> only, exactly the named master clips); the order
    of the clips inside it is not reproduced (H: neither name, browser nor table order).  Without it
    FCP 7 refuses to import the document ("XML Translation was aborted")."""
    tr = Translator(doc, **kw)
    top = Scope(None, None, X("xmeml"), straight=True)
    top.chain = ("children",)
    r = tr.select(ELEM, item, top)
    if r is None or r == "V":
        raise ExportError("not an exportable item")
    tr.build(r, 0, item, top)
    masters = [m for m in tr.master_refs if m is not item]
    if masters:
        b = X("bin")
        b.add(X("name", "Master Clips"))
        ch = b.add(X("children"))
        bscope = Scope(top, 1, b, straight=True)
        cscope = Scope(bscope, "children", ch, straight=True)
        for i, m in enumerate(masters):
            rc = tr.select(ELEM, m, cscope)
            if rc is None or rc == "V":
                continue
            tr.build(rc, i, m, cscope, idx=i)
        top.x.add(b)
    return top.x.children


def export_project(path, project_name=None, **kw):
    """UTF-8 bytes of the whole-project document (<xmeml version="5"><project>...).  The project's
    <name> is the document name, the file name without `.fcp` (see project_element)."""
    if isinstance(path, Doc):
        doc = path
    else:
        doc = load(path)
        if project_name is None:
            project_name = os.path.splitext(os.path.basename(path))[0]
    return document_bytes([project_element(doc, project_name=project_name, **kw)])


def export_item(path, which, **kw):
    """UTF-8 bytes of one top-level item (sequence or clip, by index, UUID or name) as its own
    <xmeml> document."""
    doc = path if isinstance(path, Doc) else load(path)
    return document_bytes(item_elements(doc, find_item(doc, which), **kw))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("project")
    ap.add_argument("--item", help="export one item: its name, UUID or index")
    ap.add_argument("--project-name", help="the project's <name> (default: the file name without .fcp)")
    ap.add_argument("-o", "--output", help="output file (default: standard output)")
    a = ap.parse_args(argv)
    if a.item is not None:
        which = int(a.item) if a.item.isdigit() else a.item
        data = export_item(a.project, which)
    else:
        data = export_project(a.project, project_name=a.project_name)
    if a.output:
        with open(a.output, "wb") as fh:
            fh.write(data)
    else:
        sys.stdout.buffer.write(data)


if __name__ == "__main__":
    main()
