#!/usr/bin/env python3
# Clean-room reference reader for FCP7 .fcp files, written from spec/ ONLY
# (spec/stream-header.md, spec/dictionary-stream.md, spec/value-types.md).
# It parses a file end to end with the shared reference table and can emit a
# JSONL trace (offset, length, kind, key, value, depth) — the shape Phase 4's
# differential harness needs. Seeded 2026-10-06; see spec/README.md.
import struct, sys, json

class Err(Exception): pass

class NullBuilder:
    """Default tree-builder hooks (no-ops).  A builder receives the parse as structural callbacks so a
    consumer can build its own tree without re-implementing the grammar (orchestrator/keyg_specdoc.py)."""
    def value_begin(self, off, typ): pass
    def value_end(self, off, typ, v): pass
    def key(self, off, name, slot, is_ref): pass
    def entry(self, toff, typ, eflags): pass
    def dict_open(self, off, style, flags, count, slot, elem_type): pass
    def dict_close(self, off): pass
    def dict_ref(self, off, idx): pass
    def notifiers_open(self, off, count): pass
    def notifiers_close(self, off): pass
    def messageable_open(self, off): pass
    def messageable_close(self, off, guid, slot, has_info): pass
    def messageable_ref(self, off, idx): pass
    def cfuuid(self, off, tid, text, slot): pass
    def cfuuid_ref(self, off, idx): pass
    def object_open(self, off, cls, ver, slot): pass
    def object_close(self, off, members): pass
    def object_ref(self, off, idx): pass
    def file(self, off, marker_off, rec, slot): pass
    def file_ref(self, off, idx): pass
    def slot(self, idx, typ, val, pos): pass

class Reader:
    def __init__(self, data, trace=None, builder=None):
        self.d = data; self.pos = 0; self.le = True; self.refs = []; self.trace = trace; self.depth = 0
        self.stats = {}; self.strict = True; self.cftypeids = set(); self.classkeys = {}; self.legacy_strings = 0
        self.b = builder if builder is not None else NullBuilder()
    # --- primitives
    def take(self, n):
        if self.pos + n > len(self.d): raise Err(f"EOF: need {n} at {self.pos:#x}")
        b = self.d[self.pos:self.pos+n]; self.pos += n; return b
    def fmt(self, f): return ('<' if self.le else '>') + f
    def u8(self): return self.take(1)[0]
    def i16(self): return struct.unpack(self.fmt('h'), self.take(2))[0]
    def i32(self): return struct.unpack(self.fmt('i'), self.take(4))[0]
    def f32(self): return struct.unpack(self.fmt('f'), self.take(4))[0]
    def f64(self): return struct.unpack(self.fmt('d'), self.take(8))[0]
    def string(self):
        n = self.i32()
        if n < 0: raise Err(f"negative string length {n} at {self.pos:#x}")
        return self.take(n)
    def guid(self):
        a = struct.unpack(self.fmt('I'), self.take(4))[0]; b = struct.unpack(self.fmt('H'), self.take(2))[0]
        c = struct.unpack(self.fmt('H'), self.take(2))[0]; t = self.take(8)
        return f"{a:08X}-{b:04X}-{c:04X}-{t[:2].hex().upper()}-{t[2:].hex().upper()}"
    def ev(self, off, kind, key=None, value=None):
        if self.trace is not None:
            self.trace.append({"offset": off, "length": self.pos-off, "kind": kind, "key": key, "value": value, "depth": self.depth})
        self.stats[kind] = self.stats.get(kind, 0) + 1
    def slot(self, typ, val):
        self.refs.append((typ, val)); idx = len(self.refs)-1
        self.b.slot(idx, typ, val, self.pos)
        if self.trace is not None:
            self.trace.append({"offset": self.pos, "length": 0, "kind": "slot", "key": None, "value": {"slot": idx, "type": typ}, "depth": self.depth})
        return idx
    STRING_TYPES = (0x0A, 0x1F)
    def ref(self, idx, typ):
        if idx < 0 or idx >= len(self.refs): raise Err(f"ref {idx} out of range (table has {len(self.refs)}) at {self.pos:#x}")
        have = self.refs[idx][0]
        ok = (have == typ) or (typ in self.STRING_TYPES and have in self.STRING_TYPES)
        if not ok:
            self.stats['ref_type_mismatch'] = self.stats.get('ref_type_mismatch', 0) + 1
            if self.strict: raise Err(f"back-reference {idx} expected type {typ:#x} but slot holds {have:#x} at {self.pos:#x}")
        return ('ref', idx, have)
    # --- header
    def header(self):
        off = self.pos
        magic = self.take(8)
        if magic != b'\xa2KeyG\n\r\n': raise Err("bad magic")
        self.le = (self.u8() == 1)
        ver = self.i32(); doc = self.guid()
        self.ev(off, 'header', value={'le': self.le, 'stream_version': ver, 'class': doc})
        off = self.pos
        fmt = self.i32(); utf8 = self.i32(); script = self.i32()
        if fmt != 3: raise Err(f"reftable format {fmt}")
        self.ev(off, 'reftable_header', value={'utf8': utf8, 'script': script})
        return ver
    # --- values
    def value(self, typ):
        off = self.pos
        self.b.value_begin(off, typ)
        v = self._value(typ)
        self.b.value_end(off, typ, v)
        if self.trace is not None:
            self.trace.append({"offset": off, "length": self.pos - off, "kind": "value", "key": None, "value": None, "depth": self.depth, "type": typ})
        self.stats['value'] = self.stats.get('value', 0) + 1
        return v

    def _value(self, typ):
        off = self.pos
        if typ == 0x00: return self.dict_value()
        if typ in (0x01, 0x02): v = self.i32(); self.ev(off, 'int', value=v); return v
        if typ == 0x03: v = self.f32(); self.ev(off, 'float', value=v); return v
        if typ == 0x04: v = self.f64(); self.ev(off, 'double', value=v); return v
        if typ == 0x05: v = self.u8(); self.ev(off, 'bool', value=v); return v
        if typ == 0x06: return self.messageable()
        if typ == 0x07:
            m = self.u8()
            if m == 0: r = self.ref(self.i32(), 7); self.ev(off, 'blob_ref', value=r[1]); return r
            n = self.i32(); b = self.take(n); self.slot(7, len(b)); self.ev(off, 'blob', value=len(b)); return b
        if typ == 0x08: self.ev(off, 'null'); return None
        if typ in (0x0A, 0x1F):
            if typ == 0x0A: self.legacy_strings += 1
            m = self.u8()
            if m == 0: r = self.ref(self.i32(), typ); self.ev(off, 'string_ref', value=r[1]); return r
            s = self.string(); self.slot(typ, s); self.ev(off, 'string', value=s[:60].decode('utf-8','replace')); return s
        if typ == 0x0B: s = self.string(); self.ev(off, 'conststring', value=s[:60].decode('latin-1')); return s
        if typ == 0x0C: return self.file_record()
        if typ == 0x0E: v = (self.i32(), self.i32()); self.ev(off, 'point', value=v); return v
        if typ == 0x0F: v = (self.f32(), self.f32()); self.ev(off, 'floatpt', value=v); return v
        if typ == 0x10: v = (self.f32(), self.f32(), self.f32()); self.ev(off, '3dfloatpt', value=v); return v
        if typ == 0x11: v = tuple(self.i32() for _ in range(4)); self.ev(off, 'rect', value=v); return v
        if typ == 0x12: v = self.take(4); self.ev(off, 'rgba', value=v.hex()); return v
        if typ == 0x15:
            m = self.u8()
            if m == 0: r = self.ref(self.i32(), 0x15); self.ev(off, 'guid_ref', value=r[1]); return r
            g = self.guid(); self.slot(0x15, g); self.ev(off, 'guid', value=g); return g
        if typ == 0x16: v = (self.f64(), self.i32(), self.u8()); self.ev(off, 'timecode', value=v); return v
        if typ in (0x18, 0x19): v = tuple(self.f32() for _ in range(4)); self.ev(off, 'floatcolor', value=v); return v
        if typ == 0x1A: v = (self.i16(), self.i16(), self.i32()); self.ev(off, 'itemspec_old', value=v); return v
        if typ in (0x1B, 0x1C): v = self.i16(); self.ev(off, 'int16', value=v); return v
        if typ == 0x1D: v = (self.f64(),) + tuple(self.f32() for _ in range(8)) + (self.i32(), self.i32()); self.ev(off, 'bezier', value=None); return v
        if typ == 0x1E: v = (self.u8(), self.u8(), self.i16(), self.i32()); self.ev(off, 'itemspec', value=v); return v
        if typ == 0x20: return self.obj()
        if typ in (0x21, 0x22): b = self.take(8); v = struct.unpack(self.fmt('q'), b)[0]; self.ev(off, 'int64', value=v); return v
        if typ == 0x23: return self.cfuuid()
        raise Err(f"type {typ:#x} has no reader (offset {off:#x})")
    def dict_value(self):
        off = self.pos
        m = self.u8()
        if m == 0: r = self.ref(self.i32(), 0); self.b.dict_ref(off, r[1]); self.ev(off, 'dict_ref', value=r[1]); return r
        return self.dict_body(off)
    def dict_body(self, off):
        style = self.i32(); flags = self.u8()
        if style not in (0,1,2,3,4): raise Err(f"dict style {style} at {off:#x}")
        d = {'style': style, 'flags': flags}
        self.depth += 1
        if style in (0, 4):
            count = self.i32(); idx = self.slot(0, d); self.ev(off, 'dict_open', value={'style': style, 'count': count, 'slot': idx})
            self.b.dict_open(off, style, flags, count, idx, None)
            items = {}
            for i in range(count):
                if style == 0: k = self.key()
                else:
                    koff = self.pos; k = self._value(0x15); self.ev(koff, 'guidkey', value=str(k)); self.b.key(koff, str(k), None, False)
                toff = self.pos; typ = self.i32(); eflags = self.u8()
                self.b.entry(toff, typ, eflags)
                v = self.value(typ)
                self.notifiers()
                items[k if not isinstance(k, tuple) else str(k)] = v
            d['items'] = items
        elif style == 1:
            et = self.i32(); count = self.i32(); idx = self.slot(0, d); self.ev(off, 'array_open', value={'elem_type': et, 'count': count, 'slot': idx})
            self.b.dict_open(off, 1, flags, count, idx, et)
            d['items'] = [self.value(et) for _ in range(count)]
        elif style == 2:
            proto = self.take(16); count = self.i32(); idx = self.slot(0, d); self.ev(off, 'struct_open', value={'proto': proto.hex(), 'count': count, 'slot': idx})
            self.b.dict_open(off, 2, flags, count, idx, None)
            items = {}
            for i in range(count):
                koff = self.pos; name = self.string(); self.b.key(koff, name, None, False)
                toff = self.pos; typ = self.i32(); self.b.entry(toff, typ, 0); items[name] = self.value(typ)
            d['items'] = items
        elif style == 3:
            koff = self.pos; name = self.string(); toff = self.pos; typ = self.i32(); idx = self.slot(0, d); self.ev(off, 'single_open', value={'name': name.decode('latin-1'), 'type': typ, 'slot': idx})
            self.b.dict_open(off, 3, flags, 1, idx, None); self.b.key(koff, name, None, False); self.b.entry(toff, typ, 0)
            d['items'] = {name: self.value(typ)}; self.notifiers()
        self.notifiers()
        self.depth -= 1
        self.ev(off, 'dict_close')
        self.b.dict_close(off)
        return d
    def key(self):
        off = self.pos
        n = self.u8()
        if n == 0:
            r = self.ref(self.i32(), 0x0B); k = self.refs[r[1]][1]; self.ev(off, 'key_ref', key=k.decode('latin-1'), value=r[1]); self.b.key(off, k, r[1], True); return k
        if n == 0xFF: n = self.i32()
        k = self.take(n); idx = self.slot(0x0B, k); self.ev(off, 'key_def', key=k.decode('latin-1')); self.b.key(off, k, idx, False); return k
    def notifiers(self):
        off = self.pos
        present = self.u8()
        count = 0
        if present:
            count = self.i32()
            self.b.notifiers_open(off, count)
            for _ in range(count):
                flags = self.i32(); self.messageable()
            self.b.notifiers_close(off)
        self.ev(off, 'notifiers', value=count)
    def messageable(self):
        off = self.pos
        m = self.u8()
        if m == 0: r = self.ref(self.i32(), 6); self.b.messageable_ref(off, r[1]); self.ev(off, 'messageable_ref', value=r[1]); return r
        self.b.messageable_open(off)
        g = self._value(0x15)
        has = self.u8(); info = self.dict_value() if has else None
        idx = self.slot(6, g); self.ev(off, 'messageable', value=g if isinstance(g, str) else str(g))
        self.b.messageable_close(off, g, idx, bool(has)); return ('msg', g, info)
    def cfuuid(self):
        off = self.pos
        m = self.u8()
        if m == 0: r = self.ref(self.i32(), 0x23); self.b.cfuuid_ref(off, r[1]); self.ev(off, 'cfuuid_ref', value=r[1]); return r
        tid = self.i32(); s = self.string(); self.cftypeids.add(tid)
        if len(s) == 0:                       # spec §3.1: no UUID can be made from an empty text -> null value, no slot
            self.b.cfuuid(off, tid, s, None); self.ev(off, 'cfuuid', value={'cftypeid': tid, 'text': ''}); return None
        idx = self.slot(0x23, s); self.b.cfuuid(off, tid, s, idx); self.ev(off, 'cfuuid', value={'cftypeid': tid, 'text': s.decode('latin-1')}); return s
    def obj(self):
        off = self.pos
        m = self.u8()
        if m == 0: r = self.ref(self.i32(), 0x20); self.b.object_ref(off, r[1]); self.ev(off, 'object_ref', value=r[1]); return r
        koff = self.pos; key = self.string().decode('latin-1')
        if self.trace is not None:
            self.trace.append({"offset": koff, "length": self.pos - koff, "kind": "value", "key": None, "value": None, "depth": self.depth, "type": 0x0B})
        if key not in self.CLASSES:           # spec §8: an unknown class key fails before the version word
            raise Err(f"object class {key} is not registered (offset {self.pos:#x})")
        ver = self.i32(); idx = self.slot(0x20, key); self.classkeys[(key, ver)] = self.classkeys.get((key, ver), 0) + 1
        self.ev(off, 'object_open', value={'class': key, 'version': ver, 'slot': idx})
        self.b.object_open(off, key, ver, idx)
        self.depth += 1
        members = self.members(key, ver)
        self.depth -= 1
        self.ev(off, 'object_close')
        self.b.object_close(off, members)
        return ('obj', key, ver, members)
    CLASSES = ('22CProjectItemTableEntry', '21CProjectItemNestEntry', '6CAngle', '10CMulticlip', '20CMulticlipSharedInfo',
               '26CMulticlipSharedInfoClient', '11FCSpeedData', '13FCSpeedBezier', '14FCSpeedSegment', '17KGPortValueObject',
               '20ClipItemHistoryEntry')          # the class keys FCP 7 registers (spec §7)
    def members(self, key, ver):
        D = lambda: self.value(0x00)      # dictionary members go through the typed-value dispatch (oracle: V events)
        O = lambda: self._value(0x20)     # object members are read by the object reader directly: no typed-value
                                          # dispatch, hence no 'value' trace event (oracle: At The Horizon multiclips)
        # spec §7: a version other than the current one goes through the class's upgrade step INSTEAD of the
        # current layout; steps FCP 7 does not have fail, and accepting steps that read nothing leave no members.
        if key == '22CProjectItemTableEntry':
            if ver == 0x10001:
                clip = D(); u = self.cfuuid(); b1 = self.u8(); has = self.u8(); nests = D() if has else None
                return {'clip': clip, 'uuid': u, 'usedInBrowser': b1, 'nests': nests}
            if ver == 0x10000: return {'clip': D(), 'uuid': self.cfuuid()}
        if key == '21CProjectItemNestEntry' and ver == 0x10000: return {'a': D(), 'b': D()}
        if key == '6CAngle':
            if ver == 0x10002: return {'d': D(), 'i': self.i32()}
            if ver == 0x10001: return {'b': self.u8(), 'd': D(), 'i': self.i32()}
            # 0x10000 is rejected by FCP 7 (its step exists only for a reader at version 0x10001)
        if key == '10CMulticlip':
            if ver == 0x10006:
                a = self.i32(); b = self.i32(); c = self.u8(); d_ = self.i32(); has = self.u8(); u = self.cfuuid() if has else None; e = self.i32(); shared = O()
                return {'a': a, 'b': b, 'c': c, 'd': d_, 'uuid': u, 'e': e, 'shared': shared}
            if ver == 0x10003:
                a = self.i32(); b = self.i32(); c = self.i32(); d_ = self.u8(); e = self.i32(); f = self.i32(); n = self.i32()
                return {'a': a, 'b': b, 'c': c, 'd': d_, 'e': e, 'f': f, 'angles': [O() for _ in range(n)]}
            if ver == 0x10004:
                a = self.i32(); b = self.i32(); c = self.i32(); d_ = self.u8(); e = self.i32(); has = self.u8(); dct = D() if has else None
                f = self.i32(); n = self.i32()
                return {'a': a, 'b': b, 'c': c, 'd': d_, 'e': e, 'discarded': dct, 'f': f, 'angles': [O() for _ in range(n)]}
            # 0x10000-0x10002 and 0x10005 are rejected by FCP 7
        if key == '20CMulticlipSharedInfo':
            if ver == 0x10000:
                a = self.i32(); b = self.i32(); n = self.i32(); c = self.i32(); angles = [O() for _ in range(n)]
                return {'a': a, 'b': b, 'c': c, 'angles': angles}
            return {}                                     # any other version: accepted, nothing read
        if key == '26CMulticlipSharedInfoClient' and ver == 0x10000: return {'o': O()}
        if key == '11FCSpeedData': return {'a': D(), 'b': D()} if ver == 1 else {}
        if key in ('13FCSpeedBezier', '14FCSpeedSegment'): return {'d': D()} if ver == 1 else {}
        if key == '17KGPortValueObject' and ver == 0: n = self.i32(); return {'plist': self.take(n)}
        raise Err(f"object class {key} version {ver:#x} is rejected by the loader (or unknown to this reader) at {self.pos:#x}")
    def file_record(self):
        off = self.pos
        has = self.u8(); info = self.dict_value() if has else None
        moff = self.pos; m = self.u8()
        if m == 0: r = self.ref(self.i32(), 0x0C); self.b.file_ref(off, r[1]); self.ev(off, 'file_ref', value=r[1]); return r
        nblocks = self.i32()
        if nblocks < 5: raise Err(f"file record with {nblocks} blocks at {off:#x}")
        alen = self.i32(); alias = self.take(alen) if alen > 0 else b''
        mlen = self.i32()
        if mlen < 9: self.take(mlen)
        else:
            a = self.i32(); b = self.i32()
            if a + b + 8 != mlen: raise Err(f"moniker sum mismatch at {off:#x}")
            self.take(a + b)
        vol = self.string(); drive = self.string()
        plen = self.i32()
        if plen - 12 > 1024 or plen < 12: raise Err(f"path block {plen} at {off:#x}")
        ce = self.i32(); fe = self.i32(); pe = self.i32(); path = self.take(plen - 12)
        extra = []
        for _ in range(nblocks - 5):
            n = self.i32(); extra.append(self.take(n))
        rec = {'info': info, 'alias': len(alias), 'vol': vol, 'drive': drive, 'path': path.replace(b'\x00', b':'), 'path_raw': path, 'elems': (ce, fe, pe), 'extra': len(extra), 'end': self.pos}
        idx = self.slot(0x0C, rec); self.ev(off, 'file', value={'path': path.replace(b'\x00', b':')[:80].decode('utf-8','replace'), 'slot': idx, 'blocks': nblocks})
        self.b.file(off, moff, rec, idx)
        return rec

def run(path, trace_path=None):
    data = open(path, 'rb').read()
    tr = [] if trace_path else None
    r = Reader(data, tr)
    try:
        ver = r.header()
        root = r.value(0x00)
        status = 'OK' if r.pos == len(data) else f'OK-but-trailing {len(data)-r.pos} bytes'
        print(f"   stream_version={ver}")
    except Err as e:
        status = f'ERR {e}'; root = None
    except struct.error as e:
        status = f'ERR struct {e} at {r.pos:#x}'; root = None
    print(f"{path}\n   status={status} consumed={r.pos:#x}/{len(data):#x} ({100*r.pos/len(data):.2f}%) refs={len(r.refs)} le={r.le}")
    if root and isinstance(root, dict):
        print('   root style/flags/count:', root['style'], root['flags'], len(root['items']))
        print('   root keys:', [k.decode('latin-1') if isinstance(k, bytes) else k for k in list(root['items'].keys())[:30]])
        for want in (b'project_compatible_back_to_version', b'sequence_count', b'bin_count'):
            if want in root['items']: print('   ', want.decode(), '=', root['items'][want])
    top = sorted(r.stats.items(), key=lambda x: -x[1])[:14]
    print('   events:', top)
    print(f"   ref_type_mismatches={r.stats.get('ref_type_mismatch',0)} legacy_0x0A_strings={r.legacy_strings} cftypeids={sorted(r.cftypeids)} classes={ {k[0]+'@'+hex(k[1]): v for k, v in r.classkeys.items()} }")
    if tr is not None:
        with open(trace_path, 'w') as f:
            for e in tr: f.write(json.dumps(e, default=str) + '\n')
        print('   trace written:', trace_path, len(tr), 'events')
    return r

if __name__ == '__main__':
    args = sys.argv[1:]; trace_out = None
    if '--trace' in args:
        i = args.index('--trace'); trace_out = args[i + 1]; del args[i:i + 2]
    for p in args:
        run(p, trace_out)
